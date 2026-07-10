"""OAuth 2.0 da API v3 do Bling: troca de code, renovação e guarda de tokens.

Cada cliente tem o SEU app registrado no Bling dele — client_id/client_secret
ficam na tabela `credenciais`, na linha do cliente. Quando não estão lá, vale
o fallback BLING_CLIENT_ID/BLING_CLIENT_SECRET do .env (modo dev/CLI local).
"""
import base64
import os
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Credencial

load_dotenv()

URL_AUTORIZACAO = "https://www.bling.com.br/Api/v3/oauth/authorize"
URL_TOKEN = "https://api.bling.com.br/Api/v3/oauth/token"
FONTE = "bling"

# Renova o access_token quando faltar menos que isto para expirar
MARGEM_RENOVACAO = timedelta(minutes=5)


def _credencial_do_cliente(sessao: Session, cliente_id: int) -> Credencial | None:
    return sessao.execute(
        select(Credencial).where(
            Credencial.cliente_id == cliente_id, Credencial.fonte == FONTE
        )
    ).scalar_one_or_none()


def credenciais_app(sessao: Session | None = None,
                    cliente_id: int | None = None) -> tuple[str, str]:
    """(client_id, client_secret) do app Bling do cliente, ou do .env."""
    if sessao is not None and cliente_id is not None:
        credencial = _credencial_do_cliente(sessao, cliente_id)
        if credencial and credencial.client_id and credencial.client_secret:
            return credencial.client_id, credencial.client_secret

    client_id = os.getenv("BLING_CLIENT_ID", "").strip()
    client_secret = os.getenv("BLING_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise RuntimeError(
            "Sem credenciais do app Bling: cadastre client_id/client_secret "
            "para o cliente (tela Cadastrar Cliente) ou preencha o .env."
        )
    return client_id, client_secret


def montar_url_autorizacao(client_id: str, state: str | None = None) -> tuple[str, str]:
    """URL para o cliente autorizar o app. Retorna (url, state)."""
    state = state or secrets.token_urlsafe(16)
    params = {"response_type": "code", "client_id": client_id, "state": state}
    return f"{URL_AUTORIZACAO}?{urlencode(params)}", state


def _chamar_endpoint_token(payload: dict, client_id: str, client_secret: str) -> dict:
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    resposta = requests.post(
        URL_TOKEN,
        data=payload,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        timeout=30,
    )
    if resposta.status_code != 200:
        raise RuntimeError(
            f"Bling recusou a operação de token (HTTP {resposta.status_code}): {resposta.text}"
        )
    return resposta.json()


def trocar_code_por_tokens(code: str, client_id: str, client_secret: str) -> dict:
    return _chamar_endpoint_token(
        {"grant_type": "authorization_code", "code": code}, client_id, client_secret
    )


def renovar_tokens(refresh_token: str, client_id: str, client_secret: str) -> dict:
    return _chamar_endpoint_token(
        {"grant_type": "refresh_token", "refresh_token": refresh_token},
        client_id, client_secret,
    )


def salvar_tokens(sessao: Session, cliente_id: int, dados_token: dict,
                  client_id: str | None = None,
                  client_secret: str | None = None) -> Credencial:
    credencial = _credencial_do_cliente(sessao, cliente_id)
    if credencial is None:
        credencial = Credencial(cliente_id=cliente_id, fonte=FONTE)
        sessao.add(credencial)

    if client_id:
        credencial.client_id = client_id
    if client_secret:
        credencial.client_secret = client_secret
    credencial.access_token = dados_token["access_token"]
    # O Bling rotaciona o refresh_token; se não vier, mantém o atual
    credencial.refresh_token = dados_token.get("refresh_token") or credencial.refresh_token
    expira_em_s = int(dados_token.get("expires_in", 21600))
    credencial.expira_em = datetime.utcnow() + timedelta(seconds=expira_em_s)
    sessao.commit()
    return credencial


def obter_access_token(sessao: Session, cliente_id: int) -> str:
    """Access token válido para o cliente, renovando automaticamente se preciso."""
    credencial = _credencial_do_cliente(sessao, cliente_id)
    if credencial is None or not credencial.refresh_token:
        raise RuntimeError(
            f"Cliente {cliente_id} ainda não autorizou o Bling. Use a tela "
            "Cadastrar Cliente (ou: python -m conector.autorizar --cliente <id>)."
        )

    precisa_renovar = (
        not credencial.access_token
        or credencial.expira_em is None
        or credencial.expira_em <= datetime.utcnow() + MARGEM_RENOVACAO
    )
    if precisa_renovar:
        client_id, client_secret = credenciais_app(sessao, cliente_id)
        credencial = salvar_tokens(
            sessao, cliente_id,
            renovar_tokens(credencial.refresh_token, client_id, client_secret),
        )

    return credencial.access_token
