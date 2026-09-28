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

import base64 as _b64
import sys

import requests
from gf_search._utils import _field_len, _field_varint, _make_client
from gf_search.builder import CITY_ENTITIES, _FIELD16_ALL_RESULTS, _airport_bytes
from gf_search.parser import parse_js
from selectolax.lexbor import LexborHTMLParser

import config

_GF_SEARCH_URL = "https://www.google.com/travel/flights/search"
_TFU_CHEAPEST = "EgoIABAAGAAgAigB"  # confirmado manualmente: abre na aba "Menores preços"

_client = _make_client()


def _flight_data_bytes_with_stops(date: str, frm: str, to: str, max_stops):
    """Igual à função interna da lib, mas adicionando o campo 5 (max_stops)
    do protobuf — a lib `gf_search` não expõe isso em build_tfs(), então
    reimplementamos aqui (mesmo layout que o fast-flights usava com sucesso).
    Sem esse campo, o Google não aplica o filtro de escalas do lado dele,
    e a oferta mais barata "só direto" da aba Menores Preços nunca aparece
    pra gente — só filtrar depois, no nosso código, não é a mesma coisa."""
    data = (
        _field_len(2, date.encode())
        + _field_len(13, _airport_bytes(frm))
        + _field_len(14, _airport_bytes(to))
    )
    if max_stops is not None:
        data += _field_varint(5, max_stops)
    return data


def build_tfs_with_stops(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None,
    max_stops,
    seat: int = 1,
    adults: int = 1,
) -> str:
    info = (
        _field_varint(1, 28)
        + _field_varint(2, 2)
        + _field_len(3, _flight_data_bytes_with_stops(departure_date, origin, destination, max_stops))
    )
    if return_date:
        info += _field_len(
            3, _flight_data_bytes_with_stops(return_date, destination, origin, max_stops)
        )
    for _ in range(adults):
        info += _field_varint(8, 1)
    info += _field_varint(9, seat)
    info += _field_varint(14, 1)
    info += _field_len(16, _FIELD16_ALL_RESULTS)
    info += _field_varint(19, 1 if return_date else 2)
    return _b64.urlsafe_b64encode(info).rstrip(b"=").decode("ascii")


def parse_price(price_str: str):
    """Extrai o valor numérico de uma string tipo 'TWD 1007' -> 1007
    (o rótulo de moeda da lib é fixo/errado, mas o número já vem em BRL
    porque pedimos curr=BRL na requisição — ver nota no topo do arquivo)."""
    digits = "".join(ch for ch in price_str if ch.isdigit())
    return int(digits) if digits else None


def fetch_flights(route: dict, cache_bust: str | None = None) -> list[dict]:
    tfs = build_tfs_with_stops(
        route["from_airport"],
        route["to_airport"],
        route["date"],
        route.get("return_date"),
        route.get("max_stops"),
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
    if cache_bust:
        # Parâmetro sem efeito nos dados pedidos, só pra variar a URL e
        # evitar que o Google (ou algum cache no meio do caminho) devolva
        # sempre a mesma resposta congelada pras tentativas de retry —
        # foi isso que explicava rodadas de 3 em 3h retornando o preço
        # idêntico, tentativa após tentativa.
        params["_cb"] = cache_bust
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
    """Retorna (preco, flight_dict) do voo mais barato encontrado, ou None.

    O Google às vezes responde com "cache frio" (a seção de ofertas
    extras/OTAs, data[3], vem vazia) — nessas horas só teríamos os
    preços da aba "Melhor opção", mais caros. Pra mitigar, consultamos
    até 5 vezes com um intervalo entre elas e juntamos tudo que veio em
    cada tentativa antes de escolher o mais barato — o cache do Google
    costuma "esquentar" e trazer a lista completa numa das tentativas.
    Isso reduz a inconsistência, mas não elimina 100%: é comportamento
    documentado do lado do Google, não bug nosso.
    """
    import random
    import time

    all_results: list[dict] = []
    seen = set()
    attempts = 5

    for attempt in range(1, attempts + 1):
        global _client
        _client = _make_client()  # sessão nova a cada tentativa — evita cache atrelado a cookie
        cache_bust = f"{int(time.time() * 1000)}-{random.randint(1000, 9999)}"
        try:
            batch = fetch_flights(route, cache_bust=cache_bust)
        except Exception:
            batch = []

        novos = 0
        for f in batch:
            key = (tuple(f.get("airlines", [])), f.get("price"), f.get("stops"))
            if key not in seen:
                seen.add(key)
                all_results.append(f)
                novos += 1

        print(f"    tentativa {attempt}: {len(batch)} voos na resposta ({novos} novos, {len(all_results)} no total)")

        # Se já veio uma lista razoável (indício de cache quente), não
        # precisa insistir nas próximas tentativas.
        if len(all_results) >= 8:
            break
        if attempt < attempts:
            time.sleep(3)

    results = all_results
    if not results:
        return None

    print(f"    total bruto (todas as tentativas somadas): {len(results)} voos")
    for f in sorted(results, key=lambda x: parse_price(x.get("price", "")) or 9**9):
        print(f"      R$ {parse_price(f.get('price', '')):>5}  stops={f.get('stops')!r}  {f.get('airlines')}")

    max_stops = route.get("max_stops")
    if max_stops is not None:
        antes = len(results)
        results = [f for f in results if f.get("stops", 99) <= max_stops]
        print(f"    após filtro de max_stops={max_stops}: {len(results)} voos (de {antes})")

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
    tfs = build_tfs_with_stops(
        route["from_airport"],
        route["to_airport"],
        route["date"],
        route.get("return_date"),
        route.get("max_stops"),
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
    import datetime

    inicio = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"=== Execução iniciada em {inicio} ===")
    for route in config.ROUTES:
        try:
            check_route(route)
        except Exception as exc:  # nunca deixa uma rota com erro derrubar as outras
            print(f"  erro ao consultar rota: {exc}", file=sys.stderr)
    fim = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"=== Execução finalizada em {fim} ===")


if __name__ == "__main__":
    main()