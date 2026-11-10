import pytest

from conftest import PEDIDO_VALIDO
from validacao import (ID_MAXIMO, ErroValidacao, contem_dado_pessoal, planejar_atualizacao,
                       transicao_permitida, validar_atualizacao, validar_criacao,
                       validar_filtros)


def test_pedido_valido_e_normalizado():
    dados = dict(PEDIDO_VALIDO, descricao="  Preciso de ajuda\ncom as compras  ")
    limpo = validar_criacao(dados)
    assert limpo["descricao"] == "Preciso de ajuda com as compras"


def test_campo_extra_e_recusado():
    # o cliente não pode escolher a própria prioridade (mass assignment)
    with pytest.raises(ErroValidacao) as erro:
        validar_criacao(dict(PEDIDO_VALIDO, prioridade="alta"))
    assert "corpo" in erro.value.erros


@pytest.mark.parametrize("campo,valor", [
    ("regiao", "zona-x"),
    ("tipo", "'; DROP TABLE pedidos; --"),
    ("periodo", "madrugada"),
    ("apelido", "<script>alert(1)</script>"),
    ("apelido", "A"),
    ("descricao", "curto"),
    ("descricao", "x" * 281),
    ("apelido", 123),
])
def test_valores_invalidos(campo, valor):
    with pytest.raises(ErroValidacao) as erro:
        validar_criacao(dict(PEDIDO_VALIDO, **{campo: valor}))
    assert campo in erro.value.erros


@pytest.mark.parametrize("texto", [
    "Me liga no 11 98765-4321 por favor",
    "Meu CPF é 123.456.789-09",
    "Moro no CEP 08210-000",
    "Escreve para cida@exemplo.com",
])
def test_detecta_dado_pessoal(texto):
    assert contem_dado_pessoal(texto)


def test_data_nao_e_dado_pessoal():
    assert not contem_dado_pessoal("Consulta no dia 18/11/2026 às 14h, sala 3")


def test_atualizacao_aceita_so_status_e_voluntario():
    assert validar_atualizacao({"status": "concluido"}) == {"status": "concluido"}
    assert validar_atualizacao({"voluntario_id": None}) == {"voluntario_id": None}
    for corpo in ({}, {"apelido": "x"}, {"voluntario_id": True}, {"voluntario_id": -1},
                  {"status": "apagado"}):
        with pytest.raises(ErroValidacao):
            validar_atualizacao(corpo)


def test_filtros():
    assert validar_filtros({"status": "aberto"}) == {"status": "aberto"}
    with pytest.raises(ErroValidacao):
        validar_filtros({"regiao": "1 OR 1=1"})


def test_transicoes():
    assert transicao_permitida("aberto", "em_atendimento")
    assert not transicao_permitida("concluido", "aberto")
    assert not transicao_permitida("cancelado", "em_atendimento")


@pytest.mark.parametrize("invisivel", ["‮", "​", "﻿", "\x00"])
def test_caracteres_invisiveis_sao_recusados(invisivel):
    """U+202E inverte o texto na tela; U+200B some: servem para disfarçar o pedido."""
    with pytest.raises(ErroValidacao) as erro:
        validar_criacao(dict(PEDIDO_VALIDO, descricao=f"Preciso de ajuda {invisivel}no mercado"))
    assert "descricao" in erro.value.erros


def test_acentos_sao_normalizados():
    # "e" + acento combinado (2 caracteres) vira "é" (1 caractere), como o MySQL conta
    limpo = validar_criacao(dict(PEDIDO_VALIDO, apelido="José"))
    assert limpo["apelido"] == "José"


def test_voluntario_id_acima_do_int_do_mysql():
    with pytest.raises(ErroValidacao):
        validar_atualizacao({"voluntario_id": ID_MAXIMO + 1})
    assert validar_atualizacao({"voluntario_id": ID_MAXIMO}) == {"voluntario_id": ID_MAXIMO}


ABERTO = {"status": "aberto", "voluntario_id": None}
ATENDIMENTO = {"status": "em_atendimento", "voluntario_id": 1}


def test_planejar_devolver_para_fila_tira_voluntario():
    gravar, conflito = planejar_atualizacao(ATENDIMENTO, {"status": "aberto"})
    assert conflito is None and gravar == {"status": "aberto", "voluntario_id": None}


@pytest.mark.parametrize("atual,campos", [
    (ABERTO, {"voluntario_id": 1}),                         # aberto com voluntário
    (ABERTO, {"status": "aberto", "voluntario_id": 1}),
    (ABERTO, {"status": "em_atendimento"}),                 # atender sem voluntário
    (ATENDIMENTO, {"voluntario_id": None}),                 # tirar o voluntário sem devolver
    (ATENDIMENTO, {"status": "concluido", "voluntario_id": 2}),  # trocar ao concluir
])
def test_planejar_recusa_estado_incoerente(atual, campos):
    with pytest.raises(ErroValidacao):
        planejar_atualizacao(atual, campos)


@pytest.mark.parametrize("status_final", ["concluido", "cancelado"])
def test_planejar_pedido_finalizado_nao_muda(status_final):
    _, conflito = planejar_atualizacao({"status": status_final, "voluntario_id": 1},
                                       {"voluntario_id": 2})
    assert conflito[0] == 409
