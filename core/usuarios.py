"""Usuários do painel: autenticação e gerenciamento.

Senhas nunca ficam em claro: hash PBKDF2-SHA256 com salt individual
(biblioteca padrão do Python — sem dependência extra). Além dos usuários do
banco existe o acesso mestre: usuário `admin` com a senha APP_SENHA do
ambiente — garante que ninguém se tranca para fora do sistema.
"""
import hashlib
import hmac
import os
import secrets

from sqlalchemy import select

from db.database import Sessao
from db.models import Usuario

_ITERACOES = 200_000


def _hash_senha(senha: str, salt_hex: str | None = None) -> str:
    salt_hex = salt_hex or secrets.token_hex(16)
    digesto = hashlib.pbkdf2_hmac(
        "sha256", senha.encode(), bytes.fromhex(salt_hex), _ITERACOES
    ).hex()
    return f"{salt_hex}${digesto}"


def _verificar_senha(senha: str, armazenado: str) -> bool:
    try:
        salt_hex, digesto = armazenado.split("$", 1)
    except ValueError:
        return False
    candidato = _hash_senha(senha, salt_hex).split("$", 1)[1]
    return hmac.compare_digest(candidato, digesto)


def autenticar(usuario: str, senha: str) -> dict | None:
    """Valida credenciais. Retorna dados da sessão ou None.

    Ordem: acesso mestre (admin + APP_SENHA do ambiente) e depois usuários
    do banco (ativos).
    """
    usuario = (usuario or "").strip().lower()
    senha_mestre = os.getenv("APP_SENHA", "").strip()
    if senha_mestre and usuario == "admin" and senha == senha_mestre:
        return {"id": 0, "nome": "Administrador", "usuario": "admin",
                "papel": "equipe", "cliente_id": None}

    with Sessao() as sessao:
        registro = sessao.execute(
            select(Usuario).where(Usuario.usuario == usuario, Usuario.ativo)
        ).scalar_one_or_none()
        if registro and _verificar_senha(senha, registro.senha_hash):
            return {"id": registro.id, "nome": registro.nome,
                    "usuario": registro.usuario, "papel": registro.papel,
                    "cliente_id": registro.cliente_id}
    return None


def ha_usuarios() -> bool:
    with Sessao() as sessao:
        return sessao.execute(select(Usuario.id).limit(1)).scalar_one_or_none() is not None


def login_obrigatorio() -> bool:
    """Login é exigido quando há senha mestre configurada OU usuários no banco."""
    return bool(os.getenv("APP_SENHA", "").strip()) or ha_usuarios()


def listar() -> list[dict]:
    with Sessao() as sessao:
        registros = sessao.execute(select(Usuario).order_by(Usuario.nome)).scalars().all()
        return [{"id": u.id, "nome": u.nome, "usuario": u.usuario, "papel": u.papel,
                 "cliente_id": u.cliente_id, "ativo": u.ativo} for u in registros]


def criar(nome: str, usuario: str, senha: str, papel: str = "equipe",
          cliente_id: int | None = None) -> str | None:
    """Cria usuário; retorna mensagem de erro ou None quando dá certo."""
    usuario = (usuario or "").strip().lower()
    if not nome.strip() or not usuario or not senha:
        return "Preencha nome, usuário e senha."
    if len(senha) < 6:
        return "A senha precisa de pelo menos 6 caracteres."
    if usuario == "admin":
        return "O usuário 'admin' é reservado ao acesso mestre (APP_SENHA)."
    papel = "cliente" if papel == "cliente" else "equipe"
    if papel == "cliente" and not cliente_id:
        return "Usuário com papel 'cliente' precisa de um cliente vinculado."

    with Sessao() as sessao:
        existe = sessao.execute(
            select(Usuario).where(Usuario.usuario == usuario)
        ).scalar_one_or_none()
        if existe:
            return f"Já existe um usuário '{usuario}'."
        sessao.add(Usuario(
            nome=nome.strip(), usuario=usuario, senha_hash=_hash_senha(senha),
            papel=papel, cliente_id=cliente_id if papel == "cliente" else None,
        ))
        sessao.commit()
    return None


def trocar_senha(usuario_id: int, senha_nova: str) -> str | None:
    if len(senha_nova) < 6:
        return "A senha precisa de pelo menos 6 caracteres."
    with Sessao() as sessao:
        registro = sessao.get(Usuario, usuario_id)
        if registro is None:
            return "Usuário não encontrado."
        registro.senha_hash = _hash_senha(senha_nova)
        sessao.commit()
    return None


def excluir(usuario_id: int) -> None:
    with Sessao() as sessao:
        registro = sessao.get(Usuario, usuario_id)
        if registro:
            sessao.delete(registro)
            sessao.commit()
