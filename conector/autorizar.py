"""Autorização do app Bling pelo cliente piloto (roda uma única vez por cliente).

Uso:
    python -m conector.autorizar --cliente 1
    python -m conector.autorizar --novo-cliente "Nome da Loja"

Abre o navegador na tela de autorização do Bling (entre com a conta Bling DO
CLIENTE), captura o `code` no callback local e salva os tokens no banco.
A URL de redirecionamento cadastrada no app do Bling deve ser exatamente a
BLING_REDIRECT_URI do .env (padrão: http://localhost:8484/callback).
"""
import argparse
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

from conector.bling_auth import montar_url_autorizacao, salvar_tokens, trocar_code_por_tokens
from db.database import Sessao
from db.models import Cliente, criar_tabelas

load_dotenv()

resultado: dict = {}


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        resultado["code"] = (query.get("code") or [None])[0]
        resultado["state"] = (query.get("state") or [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if resultado["code"]:
            self.wfile.write(
                "<h2>Autorizado!</h2><p>Pode fechar esta aba e voltar ao terminal.</p>".encode()
            )
        else:
            self.wfile.write(
                "<h2>Falhou.</h2><p>Nenhum code recebido — veja o terminal.</p>".encode()
            )
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def log_message(self, *args):  # silencia o log padrão do http.server
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Autoriza um cliente no Bling (OAuth 2.0)")
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--cliente", type=int, help="id de um cliente já cadastrado")
    grupo.add_argument("--novo-cliente", help="nome para cadastrar um cliente novo")
    args = parser.parse_args()

    criar_tabelas()
    sessao = Sessao()

    if args.novo_cliente:
        cliente = Cliente(nome=args.novo_cliente)
        sessao.add(cliente)
        sessao.commit()
        print(f"Cliente cadastrado: [{cliente.id}] {cliente.nome}")
    else:
        cliente = sessao.get(Cliente, args.cliente)
        if cliente is None:
            raise SystemExit(f"Cliente {args.cliente} não existe no banco.")

    redirect_uri = os.getenv("BLING_REDIRECT_URI", "http://localhost:8484/callback")
    porta = urlparse(redirect_uri).port or 80

    url, state = montar_url_autorizacao()
    print("\nAbra (com a conta Bling do cliente) e autorize o app:")
    print(f"\n  {url}\n")
    print(f"Aguardando o callback em {redirect_uri} ...")
    webbrowser.open(url)

    servidor = HTTPServer(("localhost", porta), CallbackHandler)
    servidor.timeout = 300
    servidor.serve_forever()

    if not resultado.get("code"):
        raise SystemExit("Nenhum code recebido no callback. Tente novamente.")
    if resultado.get("state") != state:
        raise SystemExit("State divergente no callback — fluxo abortado por segurança.")

    tokens = trocar_code_por_tokens(resultado["code"])
    salvar_tokens(sessao, cliente.id, tokens)
    print(f"\nTokens salvos para o cliente [{cliente.id}] {cliente.nome}.")
    print("Próximo passo: python -m conector.sincronizar --cliente", cliente.id, "--inspecionar")


if __name__ == "__main__":
    main()
