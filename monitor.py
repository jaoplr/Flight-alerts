"""
Alerta de preços de voos (Google Flights) via ntfy.sh.

Uso:
    python3 monitor.py

Pensado pra rodar periodicamente via cron. A cada execução, pra cada rota
definida em config.py:
  1. consulta o menor preço disponível — usando a lib `gf_search`
     (pacote `google-flights-search`), que lê tanto a seção "Melhor
     opção" quanto "Outras opções" da página, cobrindo o mesmo conjunto
     de tarifas (incluindo ofertas de agências) que aparece na aba
     "Menores preços" do site.
  2. sempre envia uma notificação ntfy com o preço encontrado
  3. se o preço estiver dentro do limite (max_price), a notificação vem
     com prioridade urgente e um título de alerta

IMPORTANTE: chamamos a lib de forma customizada (não usamos a função
`search()` pronta dela) porque, por padrão, ela vem fixada em TWD/chinês
(hl=zh-TW, sem parâmetro de moeda). Aqui sobrescrevemos com
hl=pt-BR, gl=BR, curr=BRL e o `tfu` confirmado manualmente, pra garantir
preço real em reais. Repare que o campo `price` retornado pela lib vem
rotulado como "TWD 1234" mesmo pedindo BRL — isso é um bug de rótulo
fixo no código deles (fetcher.py/parser.py), o número em si já vem
correto na moeda pedida (confirmado manualmente contra o preço mostrado
no navegador). Nossa função `parse_price` já ignora esse rótulo e só lê
o número.

Exige Python 3.10+ — a VPS usa uma venv separada criada com
`python3.11 -m venv venv311` (não a venv padrão em Python 3.9).
"""

from __future__ import annotations

import sys

import requests
from gf_search.builder import build_tfs
from gf_search.parser import parse_js
from gf_search._utils import _make_client
from selectolax.lexbor import LexborHTMLParser

import config

_GF_SEARCH_URL = "https://www.google.com/travel/flights/search"
_TFU_CHEAPEST = "EgoIABAAGAAgAigB"  # confirmado manualmente: abre na aba "Menores preços"

_client = _make_client()


def parse_price(price_str: str):
    """Extrai o valor numérico de uma string tipo 'TWD 1007' -> 1007
    (o rótulo de moeda da lib é fixo/errado, mas o número já vem em BRL
    porque pedimos curr=BRL na requisição — ver nota no topo do arquivo)."""
    digits = "".join(ch for ch in price_str if ch.isdigit())
    return int(digits) if digits else None


def fetch_flights(route: dict) -> list[dict]:
    tfs = build_tfs(
        route["from_airport"],
        route["to_airport"],
        route["date"],
        route.get("return_date"),
        seat={"economy": 1, "premium-economy": 2, "business": 3, "first": 4}.get(config.SEAT, 1),
        adults=1,
    )
    params = {
        "tfs": tfs,
        "tfu": _TFU_CHEAPEST,
        "hl": config.LANGUAGE,
        "gl": "BR",
        "curr": config.CURRENCY,
    }
    headers = {"Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7"}

    res = _client.get(_GF_SEARCH_URL, params=params, headers=headers)
    html_parser = LexborHTMLParser(res.text)
    ds1 = html_parser.css_first(r"script.ds\:1")
    if not ds1:
        return []

    txt = ds1.text()
    if "data:" not in txt:
        return []

    return parse_js(txt)


def cheapest_flight(route: dict):
    """Retorna (preco, flight_dict) do voo mais barato encontrado, ou None."""
    try:
        results = fetch_flights(route)
    except Exception:
        return None

    if not results:
        return None

    max_stops = route.get("max_stops")
    if max_stops is not None:
        results = [f for f in results if f.get("stops", 99) <= max_stops]

    priced = [(parse_price(f["price"]), f) for f in results if parse_price(f["price"])]
    if not priced:
        return None

    return min(priced, key=lambda pf: pf[0])


def notify(title: str, message: str, url: str | None = None, priority: str = "default", tags: str = "") -> None:
    headers = {
        "Title": title.encode("utf-8"),
        "Priority": priority,
    }
    if tags:
        headers["Tags"] = tags
    if url:
        headers["Click"] = url
    requests.post(
        f"{config.NTFY_SERVER}/{config.NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers=headers,
        timeout=15,
    )


def google_flights_url(route: dict) -> str:
    tfs = build_tfs(
        route["from_airport"],
        route["to_airport"],
        route["date"],
        route.get("return_date"),
        seat=1,
        adults=1,
    )
    import urllib.parse

    query = urllib.parse.urlencode(
        {"tfs": tfs, "tfu": _TFU_CHEAPEST, "hl": config.LANGUAGE, "gl": "BR", "curr": config.CURRENCY}
    )
    return f"{_GF_SEARCH_URL}?{query}"


def check_route(route: dict) -> None:
    label = route.get("label", f"{route['from_airport']} -> {route['to_airport']}")
    print(f"Consultando {label}...")

    found = cheapest_flight(route)
    if found is None:
        print(f"  nenhum voo encontrado para {label}")
        return

    price, flight = found
    max_price = route["max_price"]
    url = google_flights_url(route)

    airlines = ",".join(flight.get("airlines", []))
    print(f"  menor preço encontrado: {config.CURRENCY} {price} ({flight.get('stops')} escalas, {airlines})")
    print(f"  confira no navegador: {url}")

    trip_info = f"Ida: {route['date']}" + (
        f" | Volta: {route['return_date']}" if route.get("return_date") else ""
    )

    if price <= max_price:
        title = f"🚨 ALERTA PREÇO ABAIXO DO QUE VC DESEJA! {label}"
        message = (
            f"{config.CURRENCY} {price} (seu limite: {config.CURRENCY} {max_price})\n"
            f"{trip_info}"
        )
        priority = "urgent"
        tags = "rotating_light"
    else:
        title = f"✈️ {label}: {config.CURRENCY} {price}"
        message = (
            f"Ainda acima do seu limite de {config.CURRENCY} {max_price}\n"
            f"{trip_info}"
        )
        priority = "default"
        tags = "airplane"

    notify(title=title, message=message, url=url, priority=priority, tags=tags)
    print("  notificação enviada!")


def main() -> None:
    for route in config.ROUTES:
        try:
            check_route(route)
        except Exception as exc:  # nunca deixa uma rota com erro derrubar as outras
            print(f"  erro ao consultar rota: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()