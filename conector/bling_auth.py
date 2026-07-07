"""OAuth 2.0 da API v3 do Bling: troca de code, renovação e guarda de tokens.

Os tokens ficam na tabela `credenciais`, um registro por (cliente, fonte) —
o sistema é multi-cliente desde o início. client_id/secret vêm do .env.
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


def _credenciais_app() -> tuple[str, str]:
    client_id = os.getenv("BLING_CLIENT_ID", "").strip()
    client_secret = os.getenv("BLING_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise RuntimeError(
            "BLING_CLIENT_ID/BLING_CLIENT_SECRET ausentes no .env. "
            "Registre o app na Central de Extensões do Bling e preencha o .env."
        )
    return client_id, client_secret


def montar_url_autorizacao(state: str | None = None) -> tuple[str, str]:
    """URL para o cliente piloto autorizar o app. Retorna (url, state)."""
    client_id, _ = _credenciais_app()
    state = state or secrets.token_urlsafe(16)
    params = {"response_type": "code", "client_id": client_id, "state": state}
    return f"{URL_AUTORIZACAO}?{urlencode(params)}", state


def _chamar_endpoint_token(payload: dict) -> dict:
    client_id, client_secret = _credenciais_app()
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


def trocar_code_por_tokens(code: str) -> dict:
    return _chamar_endpoint_token({"grant_type": "authorization_code", "code": code})


def renovar_tokens(refresh_token: str) -> dict:
    return _chamar_endpoint_token(
        {"grant_type": "refresh_token", "refresh_token": refresh_token}
    )


def salvar_tokens(sessao: Session, cliente_id: int, dados_token: dict) -> Credencial:
    credencial = sessao.execute(
        select(Credencial).where(
            Credencial.cliente_id == cliente_id, Credencial.fonte == FONTE
        )
    ).scalar_one_or_none()

    if credencial is None:
        credencial = Credencial(cliente_id=cliente_id, fonte=FONTE)
        sessao.add(credencial)

    credencial.access_token = dados_token["access_token"]
    # O Bling rotaciona o refresh_token; se não vier, mantém o atual
    credencial.refresh_token = dados_token.get("refresh_token") or credencial.refresh_token
    expira_em_s = int(dados_token.get("expires_in", 21600))
    credencial.expira_em = datetime.utcnow() + timedelta(seconds=expira_em_s)
    sessao.commit()
    return credencial


def obter_access_token(sessao: Session, cliente_id: int) -> str:
    """Access token válido para o cliente, renovando automaticamente se preciso."""
    credencial = sessao.execute(
        select(Credencial).where(
            Credencial.cliente_id == cliente_id, Credencial.fonte == FONTE
        )
    ).scalar_one_or_none()

    if credencial is None or not credencial.refresh_token:
        raise RuntimeError(
            f"Cliente {cliente_id} ainda não autorizou o Bling. "
            "Rode: python -m conector.autorizar --cliente <id>"
        )

    precisa_renovar = (
        not credencial.access_token
        or credencial.expira_em is None
        or credencial.expira_em <= datetime.utcnow() + MARGEM_RENOVACAO
    )
    if precisa_renovar:
        credencial = salvar_tokens(
            sessao, cliente_id, renovar_tokens(credencial.refresh_token)
        )

    return credencial.access_token
