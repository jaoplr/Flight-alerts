"""
Configuração do alerta de voos.

Edite os valores abaixo. Cada item da lista ROUTES é uma rota monitorada
de forma independente — você pode adicionar quantas quiser.
"""

# ── Notificações via ntfy.sh ────────────────────────────────────────────
# ntfy.sh não exige cadastro: você só escolhe um "tópico" (um nome único,
# tipo uma senha), instala o app ntfy (ou entra em https://ntfy.sh/<topico>
# no navegador) e "assina" esse tópico para receber as notificações.
# Troque o valor abaixo por algo único e difícil de adivinhar.
NTFY_TOPIC = "joaopedro-alerta-voos-8x2f"

# Se você mesmo hospeda um servidor ntfy, troque a URL base. Caso contrário
# deixe como está (servidor público ntfy.sh).
NTFY_SERVER = "https://ntfy.sh"


# ── Rotas monitoradas ────────────────────────────────────────────────────
# from_airport / to_airport: código IATA do aeroporto (ex: "GRU", "SSA")
# date: data de ida, formato "AAAA-MM-DD"
# return_date: data de volta (formato "AAAA-MM-DD") ou None para só ida
# max_price: notifica quando o preço (em BRL) ficar IGUAL OU ABAIXO disso
# max_stops: 0 = só voo direto | 1 = até 1 escala | None = sem restrição
ROUTES = [
    {
        "label": "SSA -> RJ(GIG)",       # nome livre, só pra você identificar no alerta
        "from_airport": "SSA",
        "to_airport": "GIG",
        "date": "2026-10-21",
        "return_date": "2026-10-25",
        "max_price": 700,
        "max_stops": None,
    },
    # {
    #     "label": "SSA -> LIS",
    #     "from_airport": "SSA",
    #     "to_airport": "LIS",
    #     "date": "2027-01-10",
    #     "return_date": "2027-01-25",
    #     "max_price": 3500,
    #     "max_stops": 1,
    # },
]

# ── Outras opções ────────────────────────────────────────────────────────
CURRENCY = "BRL"
LANGUAGE = "pt-BR"
SEAT = "economy"          # economy | premium-economy | business | first

# Arquivo onde o script guarda o último preço notificado por rota, pra não
# ficar te notificando repetidamente do mesmo preço a cada execução do cron.
STATE_FILE = "state.json"