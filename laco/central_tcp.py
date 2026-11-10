"""Central de voluntários: servidor socket TCP que recebe alertas de novos pedidos.

Rode em um terminal separado:  python central_tcp.py
Cada conexão é atendida em uma thread, para uma conexão lenta não travar as outras.
"""
import socket
import threading
from datetime import datetime

import auditoria
import config
import protocolo

TAMANHO_MAXIMO = 4096  # bytes; nenhuma mensagem legítima passa disso
MAX_CONEXOES = 20      # conexões atendidas ao mesmo tempo (o resto é recusado)

filtro_replay = protocolo.FiltroDeReplay()
vagas = threading.BoundedSemaphore(MAX_CONEXOES)  # evita criar threads sem limite
NOMES_TIPO = {
    "compras": "Compras", "farmacia": "Farmácia", "acompanhamento": "Acompanhamento",
    "tecnologia": "Ajuda com tecnologia", "companhia": "Companhia",
}


def receber_linha(conexao):
    """Lê até o "\\n", com limite de tamanho (evita estourar a memória)."""
    bruto = b""
    while not bruto.endswith(b"\n"):
        parte = conexao.recv(1024)
        if not parte:
            break
        bruto += parte
        if len(bruto) > TAMANHO_MAXIMO:
            raise ValueError("mensagem grande demais")
    return bruto


def tratar_cliente(conexao, endereco):
    try:
        _atender(conexao, endereco)
    finally:
        vagas.release()


def _atender(conexao, endereco):
    with conexao:
        conexao.settimeout(5)  # cliente que não manda nada é desconectado
        try:
            dados = protocolo.desempacotar(receber_linha(conexao), filtro_replay)
        except (ValueError, OSError) as erro:
            auditoria.registrar("central_receber", "rejeitado",
                                f"origem={endereco[0]} motivo={erro}", "WARNING")
            try:
                conexao.sendall(b"ERRO\n")
            except OSError:
                pass
            return

        hora = datetime.now().strftime("%H:%M:%S")
        destaque = ">>> PRIORIDADE ALTA <<<" if dados["prioridade"] == "alta" else "prioridade normal"
        print(f"[{hora}] Novo pedido #{dados['id']} | {NOMES_TIPO[dados['tipo']]} | "
              f"{dados['regiao']} | {destaque}", flush=True)
        auditoria.registrar("central_receber", "ok", f"pedido={dados['id']} prioridade={dados['prioridade']}")
        try:
            conexao.sendall(b"OK\n")
        except OSError:
            pass  # a API desistiu de esperar; o alerta já foi mostrado e registrado


def iniciar():
    auditoria.configurar(config.LOG_CENTRAL)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as servidor:
        servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        servidor.bind((config.CENTRAL_HOST, config.CENTRAL_PORT))
        servidor.listen(5)
        print(f"Central de voluntários ouvindo em {config.CENTRAL_HOST}:{config.CENTRAL_PORT} "
              "(Ctrl+C para sair)", flush=True)
        auditoria.registrar("central_iniciar", "ok", f"porta={config.CENTRAL_PORT}")
        servidor.settimeout(1.0)  # acorda a cada 1 s para o Ctrl+C funcionar também no Windows
        while True:
            try:
                conexao, endereco = servidor.accept()
            except TimeoutError:
                continue
            if not vagas.acquire(blocking=False):  # muitas conexões abertas: recusa esta
                auditoria.registrar("central_receber", "recusado",
                                    f"origem={endereco[0]} motivo=limite de conexoes", "WARNING")
                conexao.close()
                continue
            threading.Thread(target=tratar_cliente, args=(conexao, endereco), daemon=True).start()


if __name__ == "__main__":
    try:
        iniciar()
    except KeyboardInterrupt:
        print("\nCentral encerrada.")
    except OSError as erro:
        print(f"Não foi possível abrir a porta {config.CENTRAL_PORT}: {erro.strerror}")
