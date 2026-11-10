"""Prepara o MySQL do zero: cria o banco, as tabelas, os dados fictícios e um
usuário da aplicação com privilégio mínimo (só SELECT/INSERT/UPDATE/DELETE).

Uso:  python setup_db.py
Ele pede o usuário e a senha de ADMINISTRADOR do MySQL (ex.: root) só na hora,
sem salvar em lugar nenhum. O usuário da aplicação e a senha dele vêm do .env.
"""
import getpass
import re
from pathlib import Path

import mysql.connector

import config

PASTA_SQL = Path(__file__).parent / "sql"


def executar_arquivo(cursor, caminho):
    """Executa um arquivo .sql comando por comando (separados por ';')."""
    texto = caminho.read_text(encoding="utf-8")
    linhas = [linha for linha in texto.splitlines() if not linha.strip().startswith("--")]
    for comando in "\n".join(linhas).split(";"):
        if comando.strip():
            cursor.execute(comando)


def main():
    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", config.DB_NAME):
        raise SystemExit("DB_NAME inválido no .env (use letras, números e _).")
    if config.DB_NAME != "laco":
        raise SystemExit("Os arquivos em sql/ usam o banco 'laco'. Mantenha DB_NAME=laco no .env.")

    print(f"Conectando ao MySQL em {config.DB_HOST}:{config.DB_PORT} como administrador.")
    admin_usuario = input("Usuário administrador [root]: ").strip() or "root"
    admin_senha = getpass.getpass("Senha do administrador (não aparece ao digitar): ")

    try:
        conexao = mysql.connector.connect(host=config.DB_HOST, port=config.DB_PORT,
                                          user=admin_usuario, password=admin_senha)
    except mysql.connector.Error as erro:
        raise SystemExit(f"Não foi possível conectar como administrador (erro {erro.errno}).")

    cursor = conexao.cursor()
    try:
        cursor.execute("SELECT VERSION()")
        versao = cursor.fetchone()[0]
        numeros = tuple(int(n) for n in re.findall(r"\d+", versao)[:3])
        if numeros < (8, 0, 16):
            raise SystemExit(f"MySQL {versao} é antigo demais: use 8.0.16 ou mais novo "
                             "(as regras CHECK do banco dependem disso).")

        executar_arquivo(cursor, PASTA_SQL / "schema.sql")
        # CREATE TABLE IF NOT EXISTS não mexe numa tabela que já existe: se o banco
        # veio de uma versão antiga do projeto, as regras novas não estariam lá.
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.CHECK_CONSTRAINTS "
            "WHERE CONSTRAINT_SCHEMA = %s AND CONSTRAINT_NAME = %s",
            (config.DB_NAME, "ck_pedido_status_voluntario"),
        )
        if cursor.fetchone()[0] == 0:
            raise SystemExit("O banco 'laco' é de uma versão antiga do projeto. No MySQL Workbench, "
                             "rode  DROP DATABASE laco;  e execute  python setup_db.py  de novo.")
        print("Banco e tabelas OK.")

        cursor.execute("SELECT COUNT(*) FROM laco.voluntarios")
        if cursor.fetchone()[0] == 0:
            executar_arquivo(cursor, PASTA_SQL / "dados_ficticios.sql")
            print("Dados fictícios inseridos.")
        else:
            print("Já existem dados; os fictícios não foram inseridos de novo.")

        # Usuário da aplicação com privilégio mínimo (não pode DROP, ALTER, GRANT...).
        # Criado para 'localhost' e '127.0.0.1' porque o MySQL trata os dois como hosts diferentes.
        for host in ("localhost", "127.0.0.1"):
            cursor.execute("CREATE USER IF NOT EXISTS %s@%s IDENTIFIED BY %s",
                           (config.DB_USER, host, config.DB_PASSWORD))
            cursor.execute("ALTER USER %s@%s IDENTIFIED BY %s",
                           (config.DB_USER, host, config.DB_PASSWORD))
            cursor.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON `{config.DB_NAME}`.* TO %s@%s",
                           (config.DB_USER, host))
        conexao.commit()
        print(f"Usuário da aplicação '{config.DB_USER}' pronto (só SELECT, INSERT, UPDATE, DELETE).")
    except mysql.connector.Error as erro:
        conexao.rollback()
        raise SystemExit(f"Erro ao preparar o banco (erro {erro.errno}): {erro.msg}")
    finally:
        cursor.close()
        conexao.close()

    print("Pronto! Agora rode: python central_tcp.py  (em um terminal) e  python app.py  (em outro).")


if __name__ == "__main__":
    main()
