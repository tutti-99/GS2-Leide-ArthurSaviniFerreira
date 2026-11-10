"""Log em arquivo: data e hora, ação e resultado de cada operação.

Exemplo de linha gerada:
2026-11-09 17:42:10 | INFO | acao=criar_pedido | resultado=201 | detalhe=id=7 prioridade=alta ip=127.0.0.1

Regra de privacidade: o log NUNCA recebe apelido ou descrição do pedido,
só identificadores e resultados (coleta mínima, LGPD).
"""
import logging
import os
import unicodedata
from logging.handlers import RotatingFileHandler

import config

_logger = None


def configurar(arquivo=None):
    """Prepara o logger. Cada processo (API e central TCP) usa seu próprio arquivo."""
    global _logger
    arquivo = arquivo or config.LOG_ARQUIVO
    os.makedirs(os.path.dirname(arquivo) or ".", exist_ok=True)

    logger = logging.getLogger(f"laco.{arquivo}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        # Arquivo "rotativo": ao chegar em 1 MB, guarda até 3 cópias antigas
        handler = RotatingFileHandler(arquivo, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        ))
        logger.addHandler(handler)
    _logger = logger
    return logger


def _limpar(texto):
    """Evita "log injection".

    Uma quebra de linha no texto (o caminho da URL, por exemplo, vem do
    usuário) poderia criar uma linha falsa no log; códigos de escape do
    terminal (ESC) poderiam esconder ou reescrever linhas ao exibir o log.
    Todo caractere de controle ou invisível vira espaço.
    """
    texto = str(texto)
    return "".join(" " if unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") else c
                   for c in texto[:200])


def registrar(acao, resultado, detalhe="", nivel="INFO"):
    """Grava uma linha no log com ação e resultado (a data e a hora entram automaticamente)."""
    if _logger is None:
        configurar()
    linha = f"acao={_limpar(acao)} | resultado={_limpar(resultado)}"
    if detalhe:
        linha += f" | detalhe={_limpar(detalhe)}"
    _logger.log(getattr(logging, nivel, logging.INFO), linha)
