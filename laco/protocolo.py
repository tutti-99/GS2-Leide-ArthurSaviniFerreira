"""Protocolo das mensagens TCP entre a API e a central de voluntários.

Formato: uma linha JSON terminada em "\n":
    {"dados": {...}, "assinatura": "<hmac-sha256 em hexadecimal>"}

A assinatura HMAC (com o SOCKET_SECRET do .env) garante que a mensagem
veio da API e não foi alterada no caminho: quem não tem o segredo não
consegue gerar uma assinatura válida, então não consegue injetar alertas
falsos na central.

Contra "replay" (alguém captura uma mensagem verdadeira e reenvia):
  * o campo "ts" (timestamp) limita a validade a 60 s;
  * o campo "nonce" (número aleatório de uso único) torna cada mensagem
    diferente, e a central guarda as assinaturas já vistas nesse período:
    a mesma mensagem chegando de novo é recusada.
"""
import hashlib
import hmac
import json
import re
import secrets
import threading
import time

import config
from validacao import REGIOES, TIPOS

VALIDADE_SEGUNDOS = 60
PRIORIDADES = ("normal", "alta")
RE_NONCE = re.compile(r"^[0-9a-f]{32}$")


def novo_nonce():
    return secrets.token_hex(16)  # 128 bits aleatórios, impossível de adivinhar


class FiltroDeReplay:
    """Lembra as assinaturas aceitas nos últimos segundos e recusa repetidas."""

    def __init__(self, validade=VALIDADE_SEGUNDOS):
        self.validade = validade
        self._vistas = {}  # {assinatura: momento em que chegou}
        self._trava = threading.Lock()  # a central atende cada conexão numa thread

    def primeira_vez(self, assinatura):
        agora = time.monotonic()
        with self._trava:
            # esquece o que já passou da validade (o "ts" já recusaria essas)
            for antiga in [a for a, t in self._vistas.items() if agora - t > 2 * self.validade]:
                del self._vistas[antiga]
            if assinatura in self._vistas:
                return False
            self._vistas[assinatura] = agora
            return True


def assinar(dados):
    # sort_keys garante que o mesmo dicionário gere sempre o mesmo texto
    mensagem = json.dumps(dados, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(config.SOCKET_SECRET.encode("utf-8"), mensagem, hashlib.sha256).hexdigest()


def empacotar(dados):
    """Dicionário -> bytes prontos para enviar pelo socket."""
    pacote = {"dados": dados, "assinatura": assinar(dados)}
    return (json.dumps(pacote) + "\n").encode("utf-8")


def desempacotar(bruto, filtro_replay=None):
    """Bytes recebidos -> dicionário validado. Lança ValueError se algo estiver errado.

    Com `filtro_replay`, também recusa uma mensagem que já foi aceita antes.
    """
    try:
        pacote = json.loads(bruto.decode("utf-8"))
        dados, assinatura = pacote["dados"], pacote["assinatura"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        raise ValueError("formato inválido") from None

    if not isinstance(dados, dict) or not isinstance(assinatura, str):
        raise ValueError("formato inválido")
    # compare_digest compara em tempo constante (evita ataque de temporização)
    if not hmac.compare_digest(assinar(dados), assinatura):
        raise ValueError("assinatura inválida")

    ts = dados.get("ts")
    if not isinstance(ts, int) or isinstance(ts, bool) or abs(time.time() - ts) > VALIDADE_SEGUNDOS:
        raise ValueError("mensagem expirada")

    pedido_id = dados.get("id")
    nonce = dados.get("nonce")
    if (set(dados) != {"evento", "id", "tipo", "regiao", "prioridade", "ts", "nonce"}
            or dados.get("evento") != "novo_pedido"
            or not isinstance(pedido_id, int) or isinstance(pedido_id, bool) or pedido_id <= 0
            or dados.get("tipo") not in TIPOS
            or dados.get("regiao") not in REGIOES
            or dados.get("prioridade") not in PRIORIDADES
            or not isinstance(nonce, str) or not RE_NONCE.match(nonce)):
        raise ValueError("conteúdo inválido")

    # Por último: só "gasta" a assinatura depois que tudo foi validado
    if filtro_replay is not None and not filtro_replay.primeira_vez(assinatura):
        raise ValueError("mensagem repetida (replay)")
    return dados
