"""Preferências chave/valor por cliente (tabela `preferencias`)."""
from sqlalchemy import select

from db.database import Sessao
from db.models import Preferencia


def obter(cliente_id: int, chave: str, padrao: str | None = None) -> str | None:
    with Sessao() as sessao:
        pref = sessao.execute(
            select(Preferencia).where(
                Preferencia.cliente_id == cliente_id, Preferencia.chave == chave
            )
        ).scalar_one_or_none()
        return pref.valor if pref else padrao


def obter_float(cliente_id: int, chave: str, padrao: float = 0.0) -> float:
    valor = obter(cliente_id, chave)
    try:
        return float(valor) if valor not in (None, "") else padrao
    except ValueError:
        return padrao


def definir(cliente_id: int, chave: str, valor: str) -> None:
    with Sessao() as sessao:
        pref = sessao.execute(
            select(Preferencia).where(
                Preferencia.cliente_id == cliente_id, Preferencia.chave == chave
            )
        ).scalar_one_or_none()
        if pref is None:
            pref = Preferencia(cliente_id=cliente_id, chave=chave)
            sessao.add(pref)
        pref.valor = valor
        sessao.commit()
