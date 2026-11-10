"""Configuração dos testes: variáveis de ambiente falsas e um "banco em memória".

Os testes de API não precisam de MySQL: trocamos (monkeypatch) as funções do
módulo database por versões que guardam os pedidos num dicionário.
"""
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# Valores só para teste (definidos antes de importar config.py)
os.environ.setdefault("DB_USER", "teste")
os.environ.setdefault("DB_PASSWORD", "senha-de-teste")
os.environ.setdefault("API_KEY_CENTRAL", "chave-de-teste-1234567890")
os.environ.setdefault("SOCKET_SECRET", "segredo-de-teste-1234567890")
os.environ.setdefault("LOG_ARQUIVO", str(RAIZ / "logs" / "teste.log"))

import pytest  # noqa: E402

import app as modulo_app  # noqa: E402
import clima  # noqa: E402
import database  # noqa: E402
import notificador  # noqa: E402

CHAVE = os.environ["API_KEY_CENTRAL"]


class BancoFalso:
    def __init__(self):
        self.pedidos = {}
        self.proximo_id = 1
        self.voluntarios = {1: {"id": 1, "apelido": "Bia", "regiao": "zona-leste"},
                            2: {"id": 2, "apelido": "Rafa", "regiao": "zona-norte"}}

    def criar_pedido(self, dados, prioridade):
        pid = self.proximo_id
        self.proximo_id += 1
        self.pedidos[pid] = {**dados, "id": pid, "prioridade": prioridade, "status": "aberto",
                             "voluntario_id": None, "voluntario": None,
                             "criado_em": "2026-11-09T10:00:00", "atualizado_em": "2026-11-09T10:00:00"}
        return pid

    def buscar_pedido(self, pid):
        pedido = self.pedidos.get(pid)
        return dict(pedido) if pedido else None

    def listar_pedidos(self, status=None, regiao=None):
        return [dict(p) for p in self.pedidos.values()
                if (not status or p["status"] == status) and (not regiao or p["regiao"] == regiao)]

    def atualizar_pedido(self, pid, campos, status_esperado):
        # mesma regra do UPDATE ... WHERE id = %s AND status = %s
        pedido = self.pedidos.get(pid)
        if pedido is None or pedido["status"] != status_esperado:
            return False
        pedido.update(campos)
        pedido["voluntario"] = (self.voluntarios[pedido["voluntario_id"]]["apelido"]
                                if pedido["voluntario_id"] else None)
        return True

    def resumo_pedidos(self):
        resumo = {s: 0 for s in ("aberto", "em_atendimento", "concluido", "cancelado")}
        for p in self.pedidos.values():
            resumo[p["status"]] += 1
        resumo["alta_abertos"] = sum(1 for p in self.pedidos.values()
                                     if p["status"] == "aberto" and p["prioridade"] == "alta")
        resumo["todos"] = len(self.pedidos)
        return resumo

    def excluir_pedido(self, pid):
        return self.pedidos.pop(pid, None) is not None

    def listar_voluntarios(self):
        return list(self.voluntarios.values())

    def voluntario_existe(self, vid):
        return vid in self.voluntarios

    def verificar_conexao(self):
        return None


@pytest.fixture
def banco(monkeypatch):
    falso = BancoFalso()
    for nome in ("criar_pedido", "buscar_pedido", "listar_pedidos", "resumo_pedidos",
                 "atualizar_pedido", "excluir_pedido", "listar_voluntarios", "voluntario_existe",
                 "verificar_conexao"):
        monkeypatch.setattr(database, nome, getattr(falso, nome))
    return falso


@pytest.fixture
def cliente(banco, monkeypatch):
    # Clima sem alerta e central "desligada", para os testes não dependerem da internet
    monkeypatch.setattr(clima, "consultar_clima", lambda regiao: {
        "regiao": regiao, "temperatura": 24.0, "sensacao": 25.0, "umidade": 60.0,
        "maxima_hoje": 27.0, "fonte": "teste", "alerta": False, "orientacoes": []})
    monkeypatch.setattr(notificador, "notificar_novo_pedido", lambda *args: False)
    # Limitador novo a cada teste (senão os testes "gastam" a cota uns dos outros)
    monkeypatch.setattr(modulo_app, "limitador_pedidos", modulo_app.seguranca.LimitadorDeTaxa(5, 60))
    monkeypatch.setattr(modulo_app.seguranca, "limitador_falhas_chave",
                        modulo_app.seguranca.LimitadorDeTaxa(10, 300))
    modulo_app.app.config["TESTING"] = True
    return modulo_app.app.test_client()


@pytest.fixture
def cabecalho_chave():
    return {"X-API-Key": CHAVE}


PEDIDO_VALIDO = {
    "apelido": "Dona Cida",
    "regiao": "zona-leste",
    "tipo": "compras",
    "periodo": "manha",
    "descricao": "Preciso de ajuda para trazer as compras do mercado.",
}
