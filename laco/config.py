"""Configurações do Laço, lidas do arquivo .env.

Nenhuma senha ou chave fica escrita no código: tudo vem de variáveis de
ambiente (arquivo .env, que NÃO vai para o GitHub). O .env.example mostra
quais variáveis existem, sem os valores reais.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

PASTA_PROJETO = Path(__file__).resolve().parent
load_dotenv(PASTA_PROJETO / ".env")  # lê o .env da pasta do projeto, de onde quer que rode


def _caminho(valor):
    """Caminho relativo vira relativo à pasta do projeto (não à pasta do terminal)."""
    caminho = Path(valor)
    return str(caminho if caminho.is_absolute() else PASTA_PROJETO / caminho)


def _inteiro(nome, padrao):
    valor = os.getenv(nome, str(padrao))
    try:
        return int(valor)
    except ValueError:
        raise RuntimeError(f"Variável {nome} no .env precisa ser um número inteiro.") from None


def _decimal(nome, padrao):
    valor = os.getenv(nome, str(padrao))
    try:
        return float(valor)
    except ValueError:
        raise RuntimeError(f"Variável {nome} no .env precisa ser um número.") from None


def _obrigatoria(nome, tamanho_minimo=1):
    """Lê uma variável obrigatória; para o programa com mensagem clara se faltar."""
    valor = os.getenv(nome, "")
    if len(valor) < tamanho_minimo:
        raise RuntimeError(
            f"Variável {nome} ausente ou curta demais no .env "
            f"(mínimo {tamanho_minimo} caracteres). Veja o .env.example."
        )
    return valor


# Banco de dados (MySQL)
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = _inteiro("DB_PORT", 3306)
DB_NAME = os.getenv("DB_NAME", "laco")
DB_USER = _obrigatoria("DB_USER")
DB_PASSWORD = _obrigatoria("DB_PASSWORD", 8)

# Chave que a central de voluntários usa para ler, alterar e excluir pedidos
API_KEY_CENTRAL = _obrigatoria("API_KEY_CENTRAL", 16)

# Socket TCP da central (recebe os alertas de novos pedidos)
CENTRAL_HOST = os.getenv("CENTRAL_HOST", "127.0.0.1")
CENTRAL_PORT = _inteiro("CENTRAL_PORT", 5050)
SOCKET_SECRET = _obrigatoria("SOCKET_SECRET", 16)  # segredo do HMAC

# Limiares de alerta climático (configuráveis)
LIMIAR_CALOR = _decimal("LIMIAR_CALOR", 32)      # °C
LIMIAR_UMIDADE = _decimal("LIMIAR_UMIDADE", 30)  # % de umidade relativa

# Outras
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"  # nunca ligar em produção
LOG_ARQUIVO = _caminho(os.getenv("LOG_ARQUIVO", "logs/laco.log"))
LOG_CENTRAL = _caminho(os.getenv("LOG_CENTRAL", "logs/central.log"))
