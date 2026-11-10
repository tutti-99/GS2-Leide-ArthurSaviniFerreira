import clima
import database
import seguranca
from conftest import PEDIDO_VALIDO


def criar(cliente, **mudancas):
    return cliente.post("/api/pedidos", json=dict(PEDIDO_VALIDO, **mudancas))


# ---------- POST
def test_criar_pedido_201(cliente, banco):
    r = criar(cliente)
    assert r.status_code == 201
    assert r.headers["Location"] == "/api/pedidos/1"
    assert r.get_json()["prioridade"] == "normal"
    assert banco.pedidos[1]["status"] == "aberto"


def test_farmacia_e_prioridade_alta(cliente):
    assert criar(cliente, tipo="farmacia").get_json()["prioridade"] == "alta"


def test_alerta_de_calor_sobe_prioridade(cliente, monkeypatch):
    monkeypatch.setattr(clima, "consultar_clima", lambda regiao: {"alerta": True})
    assert criar(cliente).get_json()["prioridade"] == "alta"


def test_clima_fora_do_ar_nao_impede_pedido(cliente, monkeypatch):
    def falha(regiao):
        raise clima.ClimaIndisponivel("Timeout")
    monkeypatch.setattr(clima, "consultar_clima", falha)
    r = criar(cliente)
    assert r.status_code == 201 and r.get_json()["prioridade"] == "normal"


def test_criar_invalido_400(cliente):
    r = criar(cliente, regiao="marte")
    assert r.status_code == 400
    assert "regiao" in r.get_json()["detalhes"]


def test_criar_sem_json_415(cliente):
    r = cliente.post("/api/pedidos", data="apelido=x", content_type="application/x-www-form-urlencoded")
    assert r.status_code == 415


def test_json_quebrado_400(cliente):
    r = cliente.post("/api/pedidos", data="{nao e json", content_type="application/json")
    assert r.status_code == 400


def test_corpo_grande_413(cliente):
    r = cliente.post("/api/pedidos", data="x" * 20_000, content_type="application/json")
    assert r.status_code == 413


def test_limite_de_taxa_429(cliente):
    codigos = [criar(cliente).status_code for _ in range(6)]
    assert codigos == [201] * 5 + [429]


# ---------- autenticação
def test_rotas_da_central_exigem_chave(cliente):
    criar(cliente)
    assert cliente.get("/api/pedidos").status_code == 401
    assert cliente.get("/api/pedidos/1", headers={"X-API-Key": "errada"}).status_code == 401
    assert cliente.put("/api/pedidos/1", json={"status": "cancelado"}).status_code == 401
    assert cliente.delete("/api/pedidos/1").status_code == 401


def test_forca_bruta_na_chave_bloqueia_ip(cliente, cabecalho_chave):
    codigos = [cliente.get("/api/pedidos", headers={"X-API-Key": f"chute-{i}"}).status_code
               for i in range(11)]
    assert codigos == [401] * 10 + [429]
    # bloqueado por um tempo, mesmo acertando a chave agora
    assert cliente.get("/api/pedidos", headers=cabecalho_chave).status_code == 429


# ---------- GET
def test_listar_e_detalhar(cliente, cabecalho_chave):
    criar(cliente)
    r = cliente.get("/api/pedidos?status=aberto", headers=cabecalho_chave)
    assert r.status_code == 200 and len(r.get_json()) == 1
    assert cliente.get("/api/pedidos/1", headers=cabecalho_chave).status_code == 200
    assert cliente.get("/api/pedidos/99", headers=cabecalho_chave).status_code == 404


def test_filtro_invalido_400(cliente, cabecalho_chave):
    assert cliente.get("/api/pedidos?status=x", headers=cabecalho_chave).status_code == 400


# ---------- PUT
def test_fluxo_de_atendimento(cliente, cabecalho_chave):
    criar(cliente)
    # assumir sem voluntário -> 400
    r = cliente.put("/api/pedidos/1", json={"status": "em_atendimento"}, headers=cabecalho_chave)
    assert r.status_code == 400
    # voluntário que não existe -> 400
    r = cliente.put("/api/pedidos/1", json={"status": "em_atendimento", "voluntario_id": 42},
                    headers=cabecalho_chave)
    assert r.status_code == 400
    # assumir com voluntário -> 200
    r = cliente.put("/api/pedidos/1", json={"status": "em_atendimento", "voluntario_id": 1},
                    headers=cabecalho_chave)
    assert r.status_code == 200 and r.get_json()["status"] == "em_atendimento"
    # concluir -> 200; depois reabrir -> 409 (status final)
    assert cliente.put("/api/pedidos/1", json={"status": "concluido"}, headers=cabecalho_chave).status_code == 200
    assert cliente.put("/api/pedidos/1", json={"status": "aberto"}, headers=cabecalho_chave).status_code == 409


def test_put_inexistente_404(cliente, cabecalho_chave):
    r = cliente.put("/api/pedidos/7", json={"status": "cancelado"}, headers=cabecalho_chave)
    assert r.status_code == 404


# ---------- DELETE
def test_excluir_204_depois_404(cliente, cabecalho_chave):
    criar(cliente)
    assert cliente.delete("/api/pedidos/1", headers=cabecalho_chave).status_code == 204
    assert cliente.delete("/api/pedidos/1", headers=cabecalho_chave).status_code == 404


# ---------- erros e cabeçalhos
def test_metodo_nao_permitido_405(cliente):
    r = cliente.patch("/api/pedidos/1")
    assert r.status_code == 405 and "Allow" in r.headers


def test_erro_de_banco_nao_vaza_detalhes(cliente, cabecalho_chave, monkeypatch):
    def quebra(**filtros):
        raise database.ErroBanco("Falha no MySQL (errno 1045)")
    monkeypatch.setattr(database, "listar_pedidos", quebra)
    r = cliente.get("/api/pedidos", headers=cabecalho_chave)
    assert r.status_code == 500
    assert "1045" not in r.get_data(as_text=True)
    assert r.get_json() == {"erro": "Erro interno. Tente novamente mais tarde."}


def test_cabecalhos_de_seguranca(cliente):
    r = cliente.get("/")
    assert r.status_code == 200
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert "camera=()" in r.headers["Permissions-Policy"]


def test_clima_regiao_invalida_400(cliente):
    assert cliente.get("/api/clima?regiao=xyz").status_code == 400
    assert cliente.get("/api/clima?regiao=centro").status_code == 200


# ---------- regras de coerência e concorrência do PUT
def assumir(cliente, cabecalho_chave, voluntario_id=1, pedido_id=1):
    return cliente.put(f"/api/pedidos/{pedido_id}", headers=cabecalho_chave,
                       json={"status": "em_atendimento", "voluntario_id": voluntario_id})


def test_dois_voluntarios_assumem_ao_mesmo_tempo(cliente, cabecalho_chave, banco, monkeypatch):
    """Condição de corrida: os dois leem "aberto", mas só o primeiro UPDATE vale."""
    criar(cliente)
    leitura_antiga = banco.buscar_pedido(1)   # o que o 2º voluntário leu, ainda "aberto"
    assert assumir(cliente, cabecalho_chave, 1).status_code == 200
    # O 2º chega com a leitura velha: a API acha que está aberto, mas o UPDATE condicional recusa
    monkeypatch.setattr(database, "buscar_pedido",
                        lambda pid: dict(leitura_antiga) if pid == 1 else None)
    r = assumir(cliente, cabecalho_chave, 2)
    assert r.status_code == 409
    assert banco.pedidos[1]["voluntario_id"] == 1  # o primeiro não foi sobrescrito


def test_pedido_excluido_durante_alteracao_404(cliente, cabecalho_chave, banco, monkeypatch):
    criar(cliente)
    leitura = banco.buscar_pedido(1)
    del banco.pedidos[1]
    chamadas = []
    monkeypatch.setattr(database, "buscar_pedido",
                        lambda pid: chamadas.append(pid) or (dict(leitura) if len(chamadas) == 1 else None))
    assert assumir(cliente, cabecalho_chave).status_code == 404


def test_devolver_para_fila_tira_o_voluntario(cliente, cabecalho_chave, banco):
    criar(cliente)
    assumir(cliente, cabecalho_chave)
    r = cliente.put("/api/pedidos/1", json={"status": "aberto"}, headers=cabecalho_chave)
    assert r.status_code == 200
    assert r.get_json()["voluntario_id"] is None and banco.pedidos[1]["voluntario_id"] is None


def test_pedido_aberto_nao_recebe_voluntario(cliente, cabecalho_chave):
    criar(cliente)
    r = cliente.put("/api/pedidos/1", json={"voluntario_id": 1}, headers=cabecalho_chave)
    assert r.status_code == 400 and "voluntario_id" in r.get_json()["detalhes"]


def test_trocar_voluntario_durante_atendimento(cliente, cabecalho_chave, banco):
    criar(cliente)
    assumir(cliente, cabecalho_chave, 1)
    r = cliente.put("/api/pedidos/1", json={"voluntario_id": 2}, headers=cabecalho_chave)
    assert r.status_code == 200 and banco.pedidos[1]["voluntario_id"] == 2


def test_pedido_concluido_nao_muda_mais(cliente, cabecalho_chave):
    criar(cliente)
    assumir(cliente, cabecalho_chave)
    cliente.put("/api/pedidos/1", json={"status": "concluido"}, headers=cabecalho_chave)
    r = cliente.put("/api/pedidos/1", json={"voluntario_id": 2}, headers=cabecalho_chave)
    assert r.status_code == 409


# ---------- resumo
def test_resumo_conta_pelo_banco(cliente, cabecalho_chave):
    criar(cliente)
    criar(cliente, tipo="farmacia")
    assumir(cliente, cabecalho_chave, pedido_id=1)
    r = cliente.get("/api/pedidos/resumo", headers=cabecalho_chave)
    assert r.status_code == 200
    assert r.get_json() == {"aberto": 1, "em_atendimento": 1, "concluido": 0, "cancelado": 0,
                            "alta_abertos": 1, "todos": 2}
    assert cliente.get("/api/pedidos/resumo").status_code == 401


# ---------- limitador de taxa
def test_limitador_esquece_ips_antigos(monkeypatch):
    """IPs sem atividade recente saem da memória (senão ela cresceria sem fim)."""
    relogio = [1000.0]
    monkeypatch.setattr(seguranca.time, "monotonic", lambda: relogio[0])
    limitador = seguranca.LimitadorDeTaxa(limite=5, janela=60)
    for i in range(500):
        limitador.permitir(f"10.0.{i // 256}.{i % 256}")
    assert limitador.ips_monitorados() == 500
    relogio[0] += 61                       # passou a janela
    limitador.permitir("192.168.0.1")      # qualquer chamada dispara a faxina
    assert limitador.ips_monitorados() == 1
    assert not limitador.excedeu("10.0.0.1")
    assert limitador.ips_monitorados() == 1  # só consultar não cria entrada
