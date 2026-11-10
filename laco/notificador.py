"""Cliente socket TCP: avisa a central de voluntários sobre um novo pedido.

Só viajam id, tipo, região e prioridade. Apelido e descrição não são
enviados (coleta mínima): o voluntário vê os detalhes no painel, com chave.
"""
import socket
import time

import config
import protocolo


def notificar_novo_pedido(pedido_id, tipo, regiao, prioridade):
    """Envia o alerta. Devolve True se a central confirmou com "OK".

    Se a central estiver desligada, devolve False e o pedido continua salvo
    normalmente: o alerta em tempo real é um extra, não pode derrubar a API.
    """
    dados = {
        "evento": "novo_pedido",
        "id": pedido_id,
        "tipo": tipo,
        "regiao": regiao,
        "prioridade": prioridade,
        "ts": int(time.time()),
        "nonce": protocolo.novo_nonce(),  # deixa cada mensagem única (contra replay)
    }
    try:
        with socket.create_connection((config.CENTRAL_HOST, config.CENTRAL_PORT), timeout=2) as conexao:
            conexao.sendall(protocolo.empacotar(dados))
            resposta = conexao.recv(16).decode("utf-8", errors="replace").strip()
        return resposta == "OK"
    except OSError:  # conexão recusada, timeout, rede fora do ar...
        return False
