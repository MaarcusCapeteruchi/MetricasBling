"""Onboarding de cliente novo 100% pela interface.

Fluxo: cadastrar nome + credenciais do app Bling (criado na conta DO cliente)
→ link de autorização → o Bling redireciona de volta para a página de
cadastro com ?code=&state= → trocamos o code por tokens e salvamos.

O `state` é um token aleatório de uso único gravado em `preferencias`
(chave oauth_state_pendente): identifica o cliente no retorno — que chega
numa sessão nova do navegador — e impede code forjado de terceiros.
"""
import secrets

from sqlalchemy import func, select

from conector.bling_auth import (
    FONTE,
    montar_url_autorizacao,
    salvar_tokens,
    trocar_code_por_tokens,
)
from db.database import Sessao
from db.models import Cliente, Credencial, Pedido, Preferencia, criar_tabelas

CHAVE_STATE = "oauth_state_pendente"


def criar_cliente_com_app(nome: str, client_id: str,
                          client_secret: str) -> tuple[int | None, str | None]:
    """Cria o cliente já com as credenciais do app dele. (cliente_id, erro)."""
    nome = (nome or "").strip()
    client_id = (client_id or "").strip()
    client_secret = (client_secret or "").strip()
    if not nome or not client_id or not client_secret:
        return None, "Preencha nome, client_id e client_secret."
    if len(client_id) < 20 or len(client_secret) < 20:
        return None, "client_id/client_secret parecem incompletos — copie do painel do app no Bling."

    criar_tabelas()
    with Sessao() as sessao:
        existente = sessao.execute(
            select(Cliente).where(func.lower(Cliente.nome) == nome.lower())
        ).scalar_one_or_none()
        if existente:
            return None, f"Já existe um cliente chamado '{existente.nome}' (id {existente.id})."

        cliente = Cliente(nome=nome)
        sessao.add(cliente)
        sessao.flush()
        sessao.add(Credencial(
            cliente_id=cliente.id, fonte=FONTE,
            client_id=client_id, client_secret=client_secret,
        ))
        sessao.commit()
        return cliente.id, None


def url_autorizacao(cliente_id: int) -> tuple[str | None, str | None]:
    """Gera a URL de autorização do Bling com state persistido. (url, erro)."""
    with Sessao() as sessao:
        credencial = sessao.execute(
            select(Credencial).where(
                Credencial.cliente_id == cliente_id, Credencial.fonte == FONTE
            )
        ).scalar_one_or_none()
        if credencial is None or not credencial.client_id:
            return None, "Cliente sem credenciais de app cadastradas."

        state = secrets.token_urlsafe(24)
        pref = sessao.execute(
            select(Preferencia).where(
                Preferencia.cliente_id == cliente_id,
                Preferencia.chave == CHAVE_STATE,
            )
        ).scalar_one_or_none()
        if pref is None:
            pref = Preferencia(cliente_id=cliente_id, chave=CHAVE_STATE)
            sessao.add(pref)
        pref.valor = state
        sessao.commit()

        url, _ = montar_url_autorizacao(credencial.client_id, state)
        return url, None


def resolver_callback(code: str, state: str) -> dict:
    """Processa o retorno do OAuth: acha o cliente pelo state (uso único),
    troca o code por tokens e salva. Retorna {ok, mensagem, cliente_id}."""
    with Sessao() as sessao:
        pref = sessao.execute(
            select(Preferencia).where(
                Preferencia.chave == CHAVE_STATE, Preferencia.valor == state
            )
        ).scalar_one_or_none()
        if pref is None:
            return {"ok": False, "cliente_id": None,
                    "mensagem": "Autorização não reconhecida (state inválido ou já usado). "
                                "Gere um novo link de autorização e tente de novo."}

        cliente_id = pref.cliente_id
        cliente = sessao.get(Cliente, cliente_id)
        credencial = sessao.execute(
            select(Credencial).where(
                Credencial.cliente_id == cliente_id, Credencial.fonte == FONTE
            )
        ).scalar_one_or_none()
        if credencial is None or not credencial.client_id:
            return {"ok": False, "cliente_id": cliente_id,
                    "mensagem": "Credenciais do app não encontradas para este cliente."}

        try:
            tokens = trocar_code_por_tokens(
                code, credencial.client_id, credencial.client_secret
            )
        except RuntimeError as erro:
            return {"ok": False, "cliente_id": cliente_id, "mensagem": str(erro)}

        salvar_tokens(sessao, cliente_id, tokens)
        sessao.delete(pref)  # state é de uso único
        sessao.commit()
        return {"ok": True, "cliente_id": cliente_id,
                "mensagem": f"Bling autorizado para {cliente.nome}."}


def situacao_clientes() -> list[dict]:
    """Visão do onboarding: app cadastrado? autorizado? quantos pedidos já tem?"""
    with Sessao() as sessao:
        linhas = []
        for cliente in sessao.execute(select(Cliente).order_by(Cliente.nome)).scalars():
            credencial = sessao.execute(
                select(Credencial).where(
                    Credencial.cliente_id == cliente.id, Credencial.fonte == FONTE
                )
            ).scalar_one_or_none()
            pedidos = sessao.execute(
                select(func.count()).select_from(Pedido).where(
                    Pedido.cliente_id == cliente.id
                )
            ).scalar()
            linhas.append({
                "id": cliente.id,
                "nome": cliente.nome,
                "tem_app": bool(credencial and credencial.client_id),
                "autorizado": bool(credencial and credencial.refresh_token),
                "pedidos": int(pedidos or 0),
            })
        return linhas
