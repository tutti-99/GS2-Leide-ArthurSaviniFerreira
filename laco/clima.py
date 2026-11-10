"""Fonte externa de dados: previsão do tempo do Open-Meteo (requests + JSON).

Open-Meteo é gratuito e não exige chave (dados sob licença CC BY 4.0).
Idosos são o grupo mais afetado por calor extremo e ar seco, por isso a
API usa estes dados para (1) mostrar orientações na página e (2) subir a
prioridade dos pedidos feitos em regiões sob alerta.
"""
import threading
import time

import requests

import config

URL_OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_SEGUNDOS = 5        # nunca esperar para sempre por um serviço externo
CACHE_SEGUNDOS = 15 * 60    # reaproveita a resposta por 15 min (menos chamadas externas)
ESPERA_APOS_FALHA = 60      # depois de uma falha, 1 min sem tentar de novo ("disjuntor")

# Um ponto de referência por região de São Paulo (coordenadas aproximadas)
COORDENADAS = {
    "centro": (-23.5505, -46.6333),      # Sé
    "zona-norte": (-23.5017, -46.6250),  # Santana
    "zona-sul": (-23.6544, -46.7104),    # Santo Amaro
    "zona-leste": (-23.5400, -46.4560),  # Itaquera
    "zona-oeste": (-23.5226, -46.7036),  # Lapa
}

_cache = {}   # {regiao: (momento_da_consulta, dados)}
_falhas = {}  # {regiao: momento_da_ultima_falha}
_trava = threading.Lock()


class ClimaIndisponivel(Exception):
    """O serviço externo falhou ou devolveu algo inesperado."""


def _numero(valor):
    """Não confiamos cegamente em dados externos: precisa ser número."""
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ValueError("valor não numérico na resposta")
    return float(valor)


def _avaliar_riscos(dados):
    orientacoes = []
    if max(dados["maxima_hoje"], dados["sensacao"]) >= config.LIMIAR_CALOR:
        orientacoes.append("Calor forte: beba água várias vezes ao dia, evite sair entre "
                           "10h e 16h e prefira roupas leves.")
    if dados["umidade"] < config.LIMIAR_UMIDADE:
        orientacoes.append("Ar muito seco: beba bastante água, evite esforço ao ar livre "
                           "e deixe uma bacia com água ou toalha úmida no quarto.")
    return {"alerta": bool(orientacoes), "orientacoes": orientacoes}


def consultar_clima(regiao):
    """Devolve temperatura, sensação, umidade, máxima do dia e alertas da região."""
    if regiao not in COORDENADAS:
        raise ValueError("região inválida")

    agora = time.monotonic()
    with _trava:
        em_cache = _cache.get(regiao)
        ultima_falha = _falhas.get(regiao)
    if em_cache and agora - em_cache[0] < CACHE_SEGUNDOS:
        return em_cache[1]
    # Se o serviço acabou de falhar, responde na hora em vez de esperar mais um
    # timeout de 5 s. Sem isso, com o Open-Meteo fora do ar, todo pedido ficaria lento.
    if ultima_falha is not None and agora - ultima_falha < ESPERA_APOS_FALHA:
        raise ClimaIndisponivel("aguardando para tentar de novo")

    latitude, longitude = COORDENADAS[regiao]
    parametros = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m",
        "daily": "temperature_2m_max",
        "timezone": "America/Sao_Paulo",
        "forecast_days": 1,
    }
    try:
        resposta = requests.get(URL_OPEN_METEO, params=parametros, timeout=TIMEOUT_SEGUNDOS)
        resposta.raise_for_status()          # 4xx/5xx do Open-Meteo vira exceção
        corpo = resposta.json()              # texto JSON -> dicionário Python
        atual = corpo["current"]
        dados = {
            "regiao": regiao,
            "temperatura": _numero(atual["temperature_2m"]),
            "sensacao": _numero(atual["apparent_temperature"]),
            "umidade": _numero(atual["relative_humidity_2m"]),
            "maxima_hoje": _numero(corpo["daily"]["temperature_2m_max"][0]),
            "fonte": "Open-Meteo (CC BY 4.0)",
        }
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as erro:
        with _trava:
            _falhas[regiao] = time.monotonic()
        raise ClimaIndisponivel(type(erro).__name__) from erro

    dados.update(_avaliar_riscos(dados))
    with _trava:
        _cache[regiao] = (agora, dados)
        _falhas.pop(regiao, None)
    return dados
