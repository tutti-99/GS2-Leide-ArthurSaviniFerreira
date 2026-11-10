"""Controles de segurança da API: autenticação da central, limite de taxa e cabeçalhos."""
import hmac
import threading
import time
from collections import deque
from functools import wraps

from flask import jsonify, request

import auditoria
import config


def chave_valida(chave_recebida):
    if not chave_recebida:
        return False
    # compare_digest: comparação em tempo constante, não "vaza" quantos caracteres acertou
    return hmac.compare_digest(chave_recebida.encode("utf-8"), config.API_KEY_CENTRAL.encode("utf-8"))


class LimitadorDeTaxa:
    """Janela deslizante: no máximo `limite` eventos a cada `janela` segundos por IP.

    Para cada IP guardamos uma fila (deque) com os horários dos últimos
    eventos; horários mais velhos que a janela saem pela esquerda. IPs sem
    eventos recentes são apagados, então a memória não cresce sem limite
    (senão um atacante com muitos IPs poderia encher a RAM do servidor).
    """

    def __init__(self, limite, janela):
        self.limite = limite
        self.janela = janela
        self._historico = {}            # {ip: deque de horários}
        self._ultima_faxina = time.monotonic()
        self._trava = threading.Lock()  # o Flask pode atender requisições em paralelo

    def _descartar_antigos(self, fila, agora):
        while fila and agora - fila[0] > self.janela:
            fila.popleft()

    def _faxina(self, agora):
        """Uma vez por janela, apaga os IPs que não têm mais eventos recentes."""
        if agora - self._ultima_faxina < self.janela:
            return
        for chave in list(self._historico):
            self._descartar_antigos(self._historico[chave], agora)
            if not self._historico[chave]:
                del self._historico[chave]
        self._ultima_faxina = agora

    def _contar(self, chave, agora):
        """Quantos eventos recentes este IP tem (sem criar entrada para IP novo)."""
        self._faxina(agora)
        fila = self._historico.get(chave)
        if fila is None:
            return 0
        self._descartar_antigos(fila, agora)
        if not fila:
            del self._historico[chave]
            return 0
        return len(fila)

    def excedeu(self, chave):
        """Só consulta: este IP já atingiu o limite?"""
        with self._trava:
            return self._contar(chave, time.monotonic()) >= self.limite

    def registrar(self, chave):
        """Conta mais um evento para este IP."""
        agora = time.monotonic()
        with self._trava:
            self._contar(chave, agora)
            self._historico.setdefault(chave, deque()).append(agora)

    def permitir(self, chave):
        """Consulta e conta de uma vez: True se ainda está dentro do limite."""
        agora = time.monotonic()
        with self._trava:
            if self._contar(chave, agora) >= self.limite:
                return False
            self._historico.setdefault(chave, deque()).append(agora)
            return True

    def ips_monitorados(self):
        """Quantos IPs estão na memória agora (usado nos testes)."""
        with self._trava:
            return len(self._historico)


# Contra força bruta na chave: 10 erros em 5 min bloqueiam o IP por um tempo
limitador_falhas_chave = LimitadorDeTaxa(limite=10, janela=300)


def exige_chave(funcao):
    """Decorador: a rota só executa se o cabeçalho X-API-Key tiver a chave da central."""
    @wraps(funcao)
    def envoltorio(*args, **kwargs):
        ip = request.remote_addr or "desconhecido"
        acao = f"{request.method} {request.path}"
        if limitador_falhas_chave.excedeu(ip):  # bloqueado mesmo que agora acerte a chave
            auditoria.registrar(acao, "429", f"bloqueio por tentativas de chave ip={ip}", "WARNING")
            return jsonify(erro="Muitas tentativas. Tente de novo mais tarde."), 429
        if not chave_valida(request.headers.get("X-API-Key", "")):
            limitador_falhas_chave.registrar(ip)
            auditoria.registrar(acao, "401", f"chave ausente ou inválida ip={ip}", "WARNING")
            return jsonify(erro="Não autorizado."), 401
        return funcao(*args, **kwargs)
    return envoltorio


def aplicar_cabecalhos(resposta):
    """Cabeçalhos HTTP de segurança em todas as respostas."""
    resposta.headers["X-Content-Type-Options"] = "nosniff"   # navegador não "adivinha" o tipo
    resposta.headers["X-Frame-Options"] = "DENY"             # impede clickjacking em iframe
    resposta.headers["Referrer-Policy"] = "no-referrer"
    # a página não usa câmera, microfone, localização etc.: bloqueia de vez
    resposta.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    resposta.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    resposta.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    resposta.headers["Content-Security-Policy"] = (          # só executa script do próprio site
        "default-src 'self'; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'self'"
    )
    if request.path.startswith("/api/"):
        resposta.headers["Cache-Control"] = "no-store"       # dados não ficam em cache
    return resposta
