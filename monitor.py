"""
Alerta de preços de voos (Google Flights) via ntfy.sh.

Uso:
    python3 monitor.py

Pensado pra rodar periodicamente via cron. A cada execução, pra cada rota
definida em config.py:
  1. consulta o menor preço disponível
  2. sempre envia uma notificação ntfy com o preço encontrado
  3. se o preço estiver dentro do limite (max_price), a notificação vem
     com prioridade urgente e um título de alerta

Usa fast-flights==2.2 (fixado no requirements.txt) — versão compatível com
Python 3.9, que é o que vem por padrão no Oracle Linux 9.
"""

from __future__ import annotations

import sys
import urllib.parse

import requests
from fast_flights import FlightData, Passengers, create_filter, get_flights_from_filter

import config


def build_filter(route: dict):
    flight_data = [
        FlightData(
            date=route["date"],
            from_airport=route["from_airport"],
            to_airport=route["to_airport"],
        )
    ]
    if route.get("return_date"):
        flight_data.append(
            FlightData(
                date=route["return_date"],
                from_airport=route["to_airport"],
                to_airport=route["from_airport"],
            )
        )

    return create_filter(
        flight_data=flight_data,
        trip="round-trip" if route.get("return_date") else "one-way",
        passengers=Passengers(adults=1),
        seat=config.SEAT,
        max_stops=route.get("max_stops"),
    )


def parse_price(price_str: str):
    """Extrai o valor numérico de uma string tipo 'R$1,234' -> 1234."""
    digits = "".join(ch for ch in price_str if ch.isdigit())
    return int(digits) if digits else None


def cheapest_flight(route: dict):
    """Retorna (preco, flight) do voo mais barato encontrado, ou None."""
    flt = build_filter(route)
    try:
        result = get_flights_from_filter(flt, currency=config.CURRENCY)
    except Exception:
        return None

    priced = [
        (parse_price(f.price), f) for f in result.flights if parse_price(f.price)
    ]
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
    flt = build_filter(route)
    tfs = flt.as_b64().decode("utf-8")
    query = urllib.parse.urlencode({"tfs": tfs, "hl": config.LANGUAGE, "curr": config.CURRENCY})
    return f"https://www.google.com/travel/flights?{query}"


def check_route(route: dict) -> None:
    label = route.get("label", f"{route['from_airport']} -> {route['to_airport']}")
    print(f"Consultando {label}...")

    found = cheapest_flight(route)
    if found is None:
        print(f"  nenhum voo encontrado para {label}")
        return

    price, _flight = found
    max_price = route["max_price"]
    url = google_flights_url(route)

    print(f"  menor preço encontrado: {config.CURRENCY} {price}")
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