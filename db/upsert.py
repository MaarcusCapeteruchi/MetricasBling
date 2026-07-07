"""Upsert genérico pela trinca (cliente_id, fonte, id_externo)."""
from sqlalchemy import select
from sqlalchemy.orm import Session


def upsert_por_id_externo(sessao: Session, modelo, cliente_id: int, fonte: str,
                          id_externo: str, valores: dict):
    """Atualiza o registro se a trinca já existe; senão insere. Retorna a instância."""
    registro = sessao.execute(
        select(modelo).where(
            modelo.cliente_id == cliente_id,
            modelo.fonte == fonte,
            modelo.id_externo == str(id_externo),
        )
    ).scalar_one_or_none()

    if registro is None:
        registro = modelo(cliente_id=cliente_id, fonte=fonte, id_externo=str(id_externo))
        sessao.add(registro)

    for campo, valor in valores.items():
        setattr(registro, campo, valor)

    return registro
