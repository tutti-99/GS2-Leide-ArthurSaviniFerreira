"""Testes do protocolo TCP (HMAC) e do cliente do Open-Meteo, sem rede."""
import json
import time

import pytest
import requests

import auditoria
import clima
import notificador
import protocolo

DADOS = {"evento": "novo_pedido", "id": 3, "tipo": "farmacia", "regiao": "centro",
         "prioridade": "alta", "nonce": "0123456789abcdef0123456789abcdef"}


def test_mensagem_assinada_e_aceita():
    dados = dict(DADOS, ts=int(time.time()))
    assert protocolo.desempacotar(protocolo.empacotar(dados)) == dados


def test_replay_e_recusado():
    """A mesma mensagem verdadeira, reenviada dentro dos 60 s, é recusada."""
    filtro = protocolo.FiltroDeReplay()
    bruto = protocolo.empacotar(dict(DADOS, ts=int(time.time())))
    assert protocolo.desempacotar(bruto, filtro)["id"] == 3
    with pytest.raises(ValueError, match="replay"):
        protocolo.desempacotar(bruto, filtro)


def test_mensagens_diferentes_passam_no_filtro():
    filtro = protocolo.FiltroDeReplay()
    for _ in range(3):
        dados = dict(DADOS, ts=int(time.time()), nonce=protocolo.novo_nonce())
        protocolo.desempacotar(protocolo.empacotar(dados), filtro)


def test_campo_extra_na_mensagem_e_recusado():
    with pytest.raises(ValueError, match="conteúdo"):
        protocolo.desempacotar(protocolo.empacotar(dict(DADOS, ts=int(time.time()), apelido="x")))


def test_notificador_manda_nonce_unico(monkeypatch):
    enviados = []

    class ConexaoFalsa:
        def __enter__(self):
            return self

        def __exit__(self, *erro):
            return False

        def sendall(self, dados):
            enviados.append(json.loads(dados)["dados"])

        def recv(self, tamanho):
            return b"OK\n"

    monkeypatch.setattr(notificador.socket, "create_connection", lambda *a, **k: ConexaoFalsa())
    assert notificador.notificar_novo_pedido(1, "compras", "centro", "normal") is True
    assert notificador.notificar_novo_pedido(1, "compras", "centro", "normal") is True
    assert enviados[0]["nonce"] != enviados[1]["nonce"]
    for dados in enviados:  # o que o notificador manda passa na validação da central
        protocolo.desempacotar(protocolo.empacotar(dados))


def test_mensagem_adulterada_e_recusada():
    pacote = json.loads(protocolo.empacotar(dict(DADOS, ts=int(time.time()))))
    pacote["dados"]["prioridade"] = "normal"  # alguém mudou no caminho
    with pytest.raises(ValueError, match="assinatura"):
        protocolo.desempacotar(json.dumps(pacote).encode())


def test_mensagem_antiga_e_recusada():
    with pytest.raises(ValueError, match="expirada"):
        protocolo.desempacotar(protocolo.empacotar(dict(DADOS, ts=int(time.time()) - 600)))


def test_lixo_e_recusado():
    with pytest.raises(ValueError):
        protocolo.desempacotar(b"\xff\xfe nao e json")


class RespostaFalsa:
    def __init__(self, corpo, status=200):
        self._corpo, self.status_code = corpo, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return self._corpo


# Formato real da resposta do Open-Meteo (/v1/forecast com current + daily)
RESPOSTA_OPEN_METEO = {
    "latitude": -23.5, "longitude": -46.625, "timezone": "America/Sao_Paulo",
    "current": {"time": "2026-11-09T15:00", "interval": 900, "temperature_2m": 33.1,
                "apparent_temperature": 34.8, "relative_humidity_2m": 28},
    "daily": {"time": ["2026-11-09"], "temperature_2m_max": [34.2]},
}


@pytest.fixture(autouse=True)
def limpar_cache():
    clima._cache.clear()
    clima._falhas.clear()
    yield
    clima._cache.clear()
    clima._falhas.clear()


def test_clima_com_alerta(monkeypatch):
    chamadas = []

    def get_falso(url, params, timeout):
        chamadas.append((url, params, timeout))
        return RespostaFalsa(RESPOSTA_OPEN_METEO)

    monkeypatch.setattr(clima.requests, "get", get_falso)
    dados = clima.consultar_clima("zona-norte")
    assert dados["alerta"] is True and len(dados["orientacoes"]) == 2  # calor + ar seco
    assert chamadas[0][2] == clima.TIMEOUT_SEGUNDOS
    clima.consultar_clima("zona-norte")
    assert len(chamadas) == 1  # a segunda veio do cache


def test_clima_resposta_estranha(monkeypatch):
    estranha = json.loads(json.dumps(RESPOSTA_OPEN_METEO))
    estranha["current"]["temperature_2m"] = "<script>"
    monkeypatch.setattr(clima.requests, "get", lambda *a, **k: RespostaFalsa(estranha))
    with pytest.raises(clima.ClimaIndisponivel):
        clima.consultar_clima("centro")


def test_clima_timeout(monkeypatch):
    def estoura(*a, **k):
        raise requests.Timeout()
    monkeypatch.setattr(clima.requests, "get", estoura)
    with pytest.raises(clima.ClimaIndisponivel):
        clima.consultar_clima("centro")


def test_falha_do_clima_nao_e_repetida_por_1_minuto(monkeypatch):
    """Com o Open-Meteo fora do ar, só a 1ª consulta espera o timeout; as outras falham na hora."""
    chamadas = []

    def estoura(*a, **k):
        chamadas.append(1)
        raise requests.Timeout()
    monkeypatch.setattr(clima.requests, "get", estoura)
    for _ in range(3):
        with pytest.raises(clima.ClimaIndisponivel):
            clima.consultar_clima("centro")
    assert len(chamadas) == 1


def test_log_sem_caracteres_de_controle():
    """Quebra de linha e escape de terminal (ESC) não chegam ao arquivo de log."""
    limpo = auditoria._limpar("GET /api/x\nINFO | acao=falsa\x1b[2K‮")
    assert "\n" not in limpo and "\x1b" not in limpo and "‮" not in limpo
