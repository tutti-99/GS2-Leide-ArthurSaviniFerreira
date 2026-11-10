"""Laço: API REST (Flask) da rede de apoio a idosos e pessoas com deficiência.

Rotas principais (CRUD de pedidos):
    POST   /api/pedidos        cria um pedido (público, com limite de taxa)   201
    GET    /api/pedidos        lista pedidos (central, exige X-API-Key)       200
    GET    /api/pedidos/resumo contagem por status (central)                  200
    GET    /api/pedidos/<id>   detalha um pedido (central)                    200 / 404
    PUT    /api/pedidos/<id>   muda status / voluntário (central)             200 / 404 / 409
    DELETE /api/pedidos/<id>   exclui um pedido (central)                     204 / 404
Apoio:
    GET /api/clima?regiao=...  dados do Open-Meteo + alertas                  200 / 503
    GET /api/voluntarios       voluntários ativos (central)                   200
    GET /api/saude             a API e o banco estão no ar?                   200 / 503
    GET /                      interface web
"""
from flask import Flask, abort, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

import auditoria
import clima
import config
import database
import notificador
import seguranca
import validacao
from validacao import ErroValidacao

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024  # 16 KB: corpo maior que isso recebe 413
app.json.ensure_ascii = False                   # acentos aparecem normais no JSON

limitador_pedidos = seguranca.LimitadorDeTaxa(limite=5, janela=60)  # 5 pedidos/min por IP
TIPOS_URGENTES = {"farmacia", "acompanhamento"}


def _log(acao, resultado, detalhe="", nivel="INFO"):
    detalhe = f"{detalhe} ip={request.remote_addr}".strip()
    auditoria.registrar(acao, resultado, detalhe, nivel)


def _corpo_json():
    """Lê o corpo da requisição exigindo JSON válido."""
    if not request.is_json:
        abort(415)  # Unsupported Media Type
    dados = request.get_json(silent=True)
    if dados is None:
        raise ErroValidacao({"corpo": "JSON inválido"})
    return dados


def calcular_prioridade(tipo, regiao):
    """Alta se o pedido é de farmácia/acompanhamento ou se a região está sob alerta climático."""
    if tipo in TIPOS_URGENTES:
        return "alta"
    try:
        if clima.consultar_clima(regiao)["alerta"]:
            return "alta"
    except clima.ClimaIndisponivel:
        # O serviço externo caiu: o pedido segue com a regra básica (degradação controlada)
        auditoria.registrar("consultar_clima", "falha", "prioridade calculada sem clima", "WARNING")
    return "normal"


# ----------------------------------------------------------------- páginas
@app.get("/")
def pagina_inicial():
    return render_template("index.html")


@app.get("/api/saude")
def saude():
    try:
        database.verificar_conexao()
        return jsonify(api="ok", banco="ok"), 200
    except database.ErroBanco:
        return jsonify(api="ok", banco="indisponível"), 503


# ----------------------------------------------------------------- pedidos
@app.post("/api/pedidos")
def criar_pedido():
    if not limitador_pedidos.permitir(request.remote_addr or "desconhecido"):
        _log("criar_pedido", "429", "limite de taxa", "WARNING")
        return jsonify(erro="Muitos pedidos em pouco tempo. Tente de novo em 1 minuto."), 429

    dados = validacao.validar_criacao(_corpo_json())
    prioridade = calcular_prioridade(dados["tipo"], dados["regiao"])
    novo_id = database.criar_pedido(dados, prioridade)
    central_avisada = notificador.notificar_novo_pedido(novo_id, dados["tipo"], dados["regiao"], prioridade)

    _log("criar_pedido", "201",
         f"id={novo_id} prioridade={prioridade} central={'ok' if central_avisada else 'offline'}")
    resposta = {
        "id": novo_id,
        "status": "aberto",
        "prioridade": prioridade,
        "central_avisada": central_avisada,
        "mensagem": "Pedido registrado. Um voluntário da sua região vai assumir em breve.",
    }
    return jsonify(resposta), 201, {"Location": f"/api/pedidos/{novo_id}"}


@app.get("/api/pedidos")
@seguranca.exige_chave
def listar_pedidos():
    filtros = validacao.validar_filtros(request.args)
    pedidos = database.listar_pedidos(**filtros)
    _log("listar_pedidos", "200", f"quantidade={len(pedidos)}")
    return jsonify(pedidos), 200


@app.get("/api/pedidos/resumo")
@seguranca.exige_chave
def resumir_pedidos():
    resumo = database.resumo_pedidos()
    _log("resumir_pedidos", "200", f"total={resumo['todos']}")
    return jsonify(resumo), 200


@app.get("/api/pedidos/<int:pedido_id>")
@seguranca.exige_chave
def detalhar_pedido(pedido_id):
    pedido = database.buscar_pedido(pedido_id)
    if pedido is None:
        _log("detalhar_pedido", "404", f"id={pedido_id}")
        return jsonify(erro="Pedido não encontrado."), 404
    _log("detalhar_pedido", "200", f"id={pedido_id}")
    return jsonify(pedido), 200


@app.put("/api/pedidos/<int:pedido_id>")
@seguranca.exige_chave
def atualizar_pedido(pedido_id):
    campos = validacao.validar_atualizacao(_corpo_json())
    atual = database.buscar_pedido(pedido_id)
    if atual is None:
        _log("atualizar_pedido", "404", f"id={pedido_id}")
        return jsonify(erro="Pedido não encontrado."), 404

    gravar, conflito = validacao.planejar_atualizacao(atual, campos)
    if conflito:
        codigo, mensagem = conflito
        _log("atualizar_pedido", str(codigo), f"id={pedido_id} status={atual['status']}")
        return jsonify(erro=mensagem), codigo
    if gravar.get("voluntario_id") is not None and not database.voluntario_existe(gravar["voluntario_id"]):
        raise ErroValidacao({"voluntario_id": "voluntário não encontrado"})

    # Gravação condicional: só vale se o status ainda for o que acabamos de ler
    if not database.atualizar_pedido(pedido_id, gravar, status_esperado=atual["status"]):
        if database.buscar_pedido(pedido_id) is None:
            _log("atualizar_pedido", "404", f"id={pedido_id} excluido durante a alteracao")
            return jsonify(erro="Pedido não encontrado."), 404
        _log("atualizar_pedido", "409", f"id={pedido_id} alterado por outra pessoa")
        return jsonify(erro="Outra pessoa alterou este pedido agora há pouco. "
                            "Atualize a lista e tente de novo."), 409

    _log("atualizar_pedido", "200", f"id={pedido_id} campos={','.join(sorted(gravar))}")
    return jsonify(database.buscar_pedido(pedido_id)), 200


@app.delete("/api/pedidos/<int:pedido_id>")
@seguranca.exige_chave
def excluir_pedido(pedido_id):
    if not database.excluir_pedido(pedido_id):
        _log("excluir_pedido", "404", f"id={pedido_id}")
        return jsonify(erro="Pedido não encontrado."), 404
    _log("excluir_pedido", "204", f"id={pedido_id}")
    return "", 204


# ----------------------------------------------------------------- apoio
@app.get("/api/voluntarios")
@seguranca.exige_chave
def listar_voluntarios():
    voluntarios = database.listar_voluntarios()
    _log("listar_voluntarios", "200", f"quantidade={len(voluntarios)}")
    return jsonify(voluntarios), 200


@app.get("/api/clima")
def consultar_clima():
    regiao = request.args.get("regiao", "")
    if regiao not in validacao.REGIOES:
        raise ErroValidacao({"regiao": "valor inválido; use: " + ", ".join(validacao.REGIOES)})
    try:
        dados = clima.consultar_clima(regiao)
    except clima.ClimaIndisponivel as erro:
        _log("consultar_clima", "503", f"regiao={regiao} erro={erro}", "WARNING")
        return jsonify(erro="Serviço de clima indisponível no momento."), 503
    _log("consultar_clima", "200", f"regiao={regiao} alerta={dados['alerta']}")
    return jsonify(dados), 200


# ----------------------------------------------------------------- erros
# Regra: o cliente recebe uma mensagem genérica; o detalhe técnico vai só para o log.
@app.errorhandler(ErroValidacao)
def tratar_erro_validacao(erro):
    _log(f"{request.method} {request.path}", "400", "campos=" + ",".join(sorted(erro.erros)))
    return jsonify(erro="Dados inválidos.", detalhes=erro.erros), 400


@app.errorhandler(database.ErroBanco)
def tratar_erro_banco(erro):
    _log(f"{request.method} {request.path}", "500", str(erro), "ERROR")
    return jsonify(erro="Erro interno. Tente novamente mais tarde."), 500


@app.errorhandler(HTTPException)
def tratar_erro_http(erro):
    mensagens = {
        404: "Recurso não encontrado.",
        405: "Método não permitido nesta rota.",
        413: "Requisição grande demais.",
        415: "Envie o corpo como JSON (Content-Type: application/json).",
    }
    _log(f"{request.method} {request.path}", str(erro.code))
    resposta = jsonify(erro=mensagens.get(erro.code, "Requisição inválida."))
    if erro.code == 405 and getattr(erro, "valid_methods", None):
        resposta.headers["Allow"] = ", ".join(erro.valid_methods)
    return resposta, erro.code


@app.errorhandler(Exception)
def tratar_erro_inesperado(erro):
    _log(f"{request.method} {request.path}", "500", type(erro).__name__, "ERROR")
    return jsonify(erro="Erro interno. Tente novamente mais tarde."), 500


@app.after_request
def cabecalhos_de_seguranca(resposta):
    return seguranca.aplicar_cabecalhos(resposta)


if __name__ == "__main__":
    # 127.0.0.1: a API só aceita conexões da própria máquina
    app.run(host="127.0.0.1", port=5000, debug=config.FLASK_DEBUG)
