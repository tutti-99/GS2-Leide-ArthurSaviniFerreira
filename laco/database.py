"""Acesso ao MySQL: CRUD feito à mão com mysql-connector (sem ORM).

Regra de ouro contra SQL injection: valores NUNCA são colados no texto do
SQL. Eles vão separados, nos parâmetros (%s), e o driver faz o escape.
Os únicos trechos montados dinamicamente são nomes de colunas, e esses
vêm de uma lista fixa definida aqui no código (nunca do usuário).
"""
from contextlib import contextmanager

import mysql.connector
from mysql.connector.constants import ClientFlag

import config

LIMITE_LISTAGEM = 200  # a central nunca recebe uma lista sem fim


class ErroBanco(Exception):
    """Falha no banco. O detalhe técnico vai só para o log, nunca para o cliente."""


@contextmanager
def _cursor(commit=False):
    """Abre conexão + cursor, faz commit/rollback e sempre fecha a conexão."""
    conexao = None
    try:
        conexao = mysql.connector.connect(
            host=config.DB_HOST, port=config.DB_PORT, database=config.DB_NAME,
            user=config.DB_USER, password=config.DB_PASSWORD,
            connection_timeout=5,
            # rowcount do UPDATE passa a contar as linhas ENCONTRADAS (não só as
            # alteradas): gravar o mesmo valor de novo não parece "pedido sumiu".
            client_flags=[ClientFlag.FOUND_ROWS],
        )
        cursor = conexao.cursor(dictionary=True)
        yield cursor
        if commit:
            conexao.commit()
    except mysql.connector.Error as erro:
        if conexao is not None and conexao.is_connected():
            conexao.rollback()
        raise ErroBanco(f"Falha no MySQL (errno {erro.errno})") from erro
    finally:
        if conexao is not None and conexao.is_connected():
            conexao.close()


SELECT_PEDIDO = """
    SELECT p.id, p.apelido, p.regiao, p.tipo, p.periodo, p.descricao,
           p.prioridade, p.status, p.voluntario_id, v.apelido AS voluntario,
           p.criado_em, p.atualizado_em
    FROM pedidos p
    LEFT JOIN voluntarios v ON v.id = p.voluntario_id
"""

COLUNAS_ATUALIZAVEIS = ("status", "voluntario_id")  # whitelist de colunas do UPDATE


def _serializar(linha):
    """Converte datas do MySQL para texto ISO 8601 (o JSON não tem tipo data)."""
    for campo in ("criado_em", "atualizado_em"):
        if linha.get(campo) is not None:
            linha[campo] = linha[campo].isoformat(timespec="seconds")
    return linha


def listar_pedidos(status=None, regiao=None):
    condicoes, parametros = [], []
    if status:
        condicoes.append("p.status = %s")
        parametros.append(status)
    if regiao:
        condicoes.append("p.regiao = %s")
        parametros.append(regiao)

    sql = SELECT_PEDIDO
    if condicoes:
        sql += " WHERE " + " AND ".join(condicoes)
    # Ordem da fila: primeiro o que ainda precisa de ação (abertos, depois em
    # atendimento), com prioridade alta na frente e o mais antigo antes. Os
    # finalizados vêm depois, do mais recente para o mais antigo. Assim o
    # LIMIT nunca esconde um pedido aberto atrás de pedidos já resolvidos.
    sql += """
        ORDER BY FIELD(p.status, 'aberto', 'em_atendimento', 'concluido', 'cancelado'),
                 CASE WHEN p.status IN ('aberto', 'em_atendimento')
                      THEN (p.prioridade = 'alta') END DESC,
                 CASE WHEN p.status IN ('aberto', 'em_atendimento') THEN p.criado_em END ASC,
                 p.atualizado_em DESC
        LIMIT %s
    """
    parametros.append(LIMITE_LISTAGEM)

    with _cursor() as cursor:
        cursor.execute(sql, tuple(parametros))
        return [_serializar(linha) for linha in cursor.fetchall()]


def resumo_pedidos():
    """Contagem por status direto no banco (não depende do LIMIT da listagem)."""
    with _cursor() as cursor:
        cursor.execute("""
            SELECT status, COUNT(*) AS total,
                   SUM(prioridade = 'alta') AS alta
            FROM pedidos
            GROUP BY status
        """)
        linhas = cursor.fetchall()
    resumo = {status: 0 for status in ("aberto", "em_atendimento", "concluido", "cancelado")}
    alta_abertos = 0
    for linha in linhas:
        resumo[linha["status"]] = int(linha["total"])
        if linha["status"] == "aberto":
            alta_abertos = int(linha["alta"] or 0)
    resumo["alta_abertos"] = alta_abertos
    resumo["todos"] = sum(resumo[s] for s in ("aberto", "em_atendimento", "concluido", "cancelado"))
    return resumo


def buscar_pedido(pedido_id):
    with _cursor() as cursor:
        cursor.execute(SELECT_PEDIDO + " WHERE p.id = %s", (pedido_id,))
        linha = cursor.fetchone()
    return _serializar(linha) if linha else None


def criar_pedido(dados, prioridade):
    sql = """INSERT INTO pedidos (apelido, regiao, tipo, periodo, descricao, prioridade)
             VALUES (%s, %s, %s, %s, %s, %s)"""
    valores = (dados["apelido"], dados["regiao"], dados["tipo"],
               dados["periodo"], dados["descricao"], prioridade)
    with _cursor(commit=True) as cursor:
        cursor.execute(sql, valores)
        return cursor.lastrowid


def atualizar_pedido(pedido_id, campos, status_esperado):
    """Grava só se o pedido AINDA estiver no status que a API conferiu.

    Evita a "condição de corrida" (TOCTOU): se dois voluntários clicam em
    "Assumir" ao mesmo tempo, os dois leem "aberto", mas só o primeiro UPDATE
    encontra o pedido aberto. O segundo não altera nada e recebe False.
    Devolve True se gravou.
    """
    colunas = [c for c in COLUNAS_ATUALIZAVEIS if c in campos]
    if not colunas:
        return True
    trecho_set = ", ".join(f"{coluna} = %s" for coluna in colunas)
    valores = [campos[coluna] for coluna in colunas] + [pedido_id, status_esperado]
    with _cursor(commit=True) as cursor:
        cursor.execute(f"UPDATE pedidos SET {trecho_set} WHERE id = %s AND status = %s",
                       tuple(valores))
        return cursor.rowcount > 0


def excluir_pedido(pedido_id):
    with _cursor(commit=True) as cursor:
        cursor.execute("DELETE FROM pedidos WHERE id = %s", (pedido_id,))
        return cursor.rowcount > 0


def listar_voluntarios():
    with _cursor() as cursor:
        cursor.execute(
            "SELECT id, apelido, regiao FROM voluntarios WHERE ativo = 1 ORDER BY apelido"
        )
        return cursor.fetchall()


def voluntario_existe(voluntario_id):
    with _cursor() as cursor:
        cursor.execute("SELECT 1 FROM voluntarios WHERE id = %s AND ativo = 1", (voluntario_id,))
        return cursor.fetchone() is not None


def verificar_conexao():
    with _cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
