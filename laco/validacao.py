"""Validação de TODA entrada que chega à API.

Estratégia: lista branca (whitelist). Só aceitamos campos conhecidos,
valores de listas fechadas e textos com tamanho e caracteres controlados.
Qualquer outra coisa é recusada com 400 antes de chegar ao banco.
"""
import re
import unicodedata

# Maior id que cabe numa coluna INT UNSIGNED do MySQL
ID_MAXIMO = 4_294_967_295

# Valores permitidos (os mesmos ENUMs do schema.sql: defesa em duas camadas)
REGIOES = ("centro", "zona-norte", "zona-sul", "zona-leste", "zona-oeste")
TIPOS = ("compras", "farmacia", "acompanhamento", "tecnologia", "companhia")
PERIODOS = ("manha", "tarde", "noite")
STATUS = ("aberto", "em_atendimento", "concluido", "cancelado")

# Para qual status cada status pode ir (dicionário de conjuntos)
TRANSICOES = {
    "aberto": {"em_atendimento", "cancelado"},
    "em_atendimento": {"aberto", "concluido", "cancelado"},
    "concluido": set(),   # status final
    "cancelado": set(),   # status final
}
STATUS_FINAIS = {status for status, destinos in TRANSICOES.items() if not destinos}

# O cliente só pode enviar estes campos. Prioridade e status iniciais são
# decididos pelo servidor (protege contra "mass assignment").
CAMPOS_CRIACAO = {"apelido", "regiao", "tipo", "periodo", "descricao"}
CAMPOS_ATUALIZACAO = {"status", "voluntario_id"}

RE_APELIDO = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ .'-]{1,39}$")
RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
RE_DATA = re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b")  # datas como 12/11 ou 12/11/2026
RE_MUITOS_DIGITOS = re.compile(r"(?:\d[\s.\-/()]*){8,}")   # telefone, CPF, CEP, cartão...


class ErroValidacao(Exception):
    """Entrada inválida. `erros` é um dicionário {campo: mensagem} devolvido ao cliente."""

    def __init__(self, erros):
        super().__init__("dados inválidos")
        self.erros = erros


def contem_dado_pessoal(texto):
    """True se o texto parece ter telefone, CPF, CEP ou e-mail (que não queremos guardar)."""
    sem_datas = RE_DATA.sub(" ", texto)  # datas são permitidas
    return bool(RE_EMAIL.search(sem_datas) or RE_MUITOS_DIGITOS.search(sem_datas))


def tem_caractere_invisivel(texto):
    """True se há caracteres de controle ou de formatação invisíveis.

    Além dos controles clássicos (Cc), recusa os de "formatação" (Cf), como o
    U+202E, que inverte a direção do texto, e os de largura zero. Com eles dá
    para disfarçar o que o voluntário lê na tela (ataque "Trojan Source").
    """
    return any(unicodedata.category(c) in ("Cc", "Cf", "Co", "Cs", "Cn") for c in texto)


def _texto(dados, campo, erros, minimo, maximo):
    valor = dados.get(campo)
    if not isinstance(valor, str):
        erros[campo] = "campo obrigatório (texto)"
        return None
    # NFC junta letra + acento em um caractere só ("e" + "´" vira "é"),
    # assim o tamanho contado aqui é o mesmo que o MySQL vai contar.
    valor = unicodedata.normalize("NFC", " ".join(valor.split()))  # também tira Enter/tab
    if tem_caractere_invisivel(valor):
        erros[campo] = "contém caracteres não permitidos"
        return None
    if not minimo <= len(valor) <= maximo:
        erros[campo] = f"deve ter entre {minimo} e {maximo} caracteres"
        return None
    return valor


def _opcao(dados, campo, opcoes, erros):
    valor = dados.get(campo)
    if valor not in opcoes:
        erros[campo] = "valor inválido; use: " + ", ".join(opcoes)
        return None
    return valor


def validar_criacao(dados):
    """Valida o corpo do POST /api/pedidos e devolve só os campos limpos."""
    if not isinstance(dados, dict):
        raise ErroValidacao({"corpo": "envie um objeto JSON"})

    erros = {}
    if set(dados) - CAMPOS_CRIACAO:
        erros["corpo"] = "envie apenas: " + ", ".join(sorted(CAMPOS_CRIACAO))

    apelido = _texto(dados, "apelido", erros, 2, 40)
    if apelido and not RE_APELIDO.match(apelido):
        erros["apelido"] = "use só letras, espaços, ponto, apóstrofo ou hífen"

    regiao = _opcao(dados, "regiao", REGIOES, erros)
    tipo = _opcao(dados, "tipo", TIPOS, erros)
    periodo = _opcao(dados, "periodo", PERIODOS, erros)

    descricao = _texto(dados, "descricao", erros, 10, 280)
    if descricao and contem_dado_pessoal(descricao):
        erros["descricao"] = ("não escreva telefone, CPF, CEP ou e-mail; "
                              "o contato é feito pela instituição parceira")

    if erros:
        raise ErroValidacao(erros)
    return {"apelido": apelido, "regiao": regiao, "tipo": tipo,
            "periodo": periodo, "descricao": descricao}


def validar_atualizacao(dados):
    """Valida o corpo do PUT /api/pedidos/<id>: só status e/ou voluntario_id."""
    if not isinstance(dados, dict) or not dados:
        raise ErroValidacao({"corpo": "envie status e/ou voluntario_id"})

    erros, limpo = {}, {}
    if set(dados) - CAMPOS_ATUALIZACAO:
        erros["corpo"] = "envie apenas: status, voluntario_id"

    if "status" in dados:
        status = _opcao(dados, "status", STATUS, erros)
        if status:
            limpo["status"] = status

    if "voluntario_id" in dados:
        vid = dados["voluntario_id"]
        # bool é subclasse de int em Python, então True/False são recusados à parte
        if vid is None or (isinstance(vid, int) and not isinstance(vid, bool) and 0 < vid <= ID_MAXIMO):
            limpo["voluntario_id"] = vid
        else:
            erros["voluntario_id"] = "deve ser um número inteiro positivo ou null"

    if erros:
        raise ErroValidacao(erros)
    return limpo


def validar_filtros(args):
    """Valida os filtros opcionais do GET (?status=...&regiao=...)."""
    filtros, erros = {}, {}
    for campo, opcoes in (("status", STATUS), ("regiao", REGIOES)):
        valor = args.get(campo)
        if valor:
            if valor in opcoes:
                filtros[campo] = valor
            else:
                erros[campo] = "valor inválido; use: " + ", ".join(opcoes)
    if erros:
        raise ErroValidacao(erros)
    return filtros


def transicao_permitida(atual, novo):
    return novo in TRANSICOES.get(atual, set())


def planejar_atualizacao(atual, campos):
    """Decide o que o PUT grava, garantindo um pedido sempre coerente.

    Regras (as mesmas do CHECK do schema.sql):
      * pedido concluído ou cancelado não muda mais;
      * aberto não tem voluntário: voltar para a fila tira o voluntário sozinho;
      * em atendimento sempre tem voluntário;
      * ao concluir ou cancelar, o voluntário não pode ser trocado.

    Devolve (campos_para_gravar, None) ou (None, (codigo_http, mensagem)).
    """
    if atual["status"] in STATUS_FINAIS:
        return None, (409, f"O pedido já está '{atual['status']}' e não pode mais ser alterado.")

    novo_status = campos.get("status", atual["status"])
    if novo_status != atual["status"] and not transicao_permitida(atual["status"], novo_status):
        return None, (409, f"Não é possível mudar de '{atual['status']}' para '{novo_status}'.")

    gravar = dict(campos)
    if novo_status == "aberto":
        if campos.get("voluntario_id") is not None:
            raise ErroValidacao({"voluntario_id": "pedido aberto não tem voluntário; "
                                                  "use status em_atendimento para atribuir"})
        if atual["voluntario_id"] is not None:
            gravar["voluntario_id"] = None  # devolvido para a fila
    elif novo_status == "em_atendimento":
        if campos.get("voluntario_id", atual["voluntario_id"]) is None:
            raise ErroValidacao({"voluntario_id": "informe o voluntário que vai atender"})
    elif "voluntario_id" in campos and campos["voluntario_id"] != atual["voluntario_id"]:
        raise ErroValidacao({"voluntario_id": "não troque o voluntário ao concluir ou cancelar"})
    return gravar, None
