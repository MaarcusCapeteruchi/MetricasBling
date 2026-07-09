"""Gerenciamento de clientes (multi-tenant), incluindo exclusão em cascata."""
from sqlalchemy import func, select

from db.database import Sessao
from db.models import (
    Canal,
    Cliente,
    Credencial,
    ItemPedido,
    Pedido,
    Preferencia,
    Produto,
    RegraComissao,
    Sincronizacao,
    TaxaPedido,
)

# Ordem de exclusão que respeita as chaves estrangeiras (filhos antes dos pais).
_MODELOS_FILHOS = [
    TaxaPedido, ItemPedido, Pedido, Produto, Canal,
    Sincronizacao, Credencial, RegraComissao, Preferencia,
]


def resumo_cliente(cliente_id: int) -> dict:
    """Nome e contagens do que existe para o cliente — mostrado antes de excluir."""
    with Sessao() as sessao:
        cliente = sessao.get(Cliente, cliente_id)
        if cliente is None:
            return {}
        pedidos = sessao.scalar(
            select(func.count()).select_from(Pedido).where(Pedido.cliente_id == cliente_id)
        )
        produtos = sessao.scalar(
            select(func.count()).select_from(Produto).where(Produto.cliente_id == cliente_id)
        )
        tem_credencial = sessao.scalar(
            select(func.count()).select_from(Credencial).where(Credencial.cliente_id == cliente_id)
        ) > 0
        return {
            "nome": cliente.nome,
            "pedidos": int(pedidos or 0),
            "produtos": int(produtos or 0),
            "tem_credencial": bool(tem_credencial),
        }


def excluir_cliente(cliente_id: int) -> dict:
    """Apaga o cliente e TODOS os seus dados. Ação irreversível.

    Retorna o resumo do que foi apagado (para exibir confirmação ao usuário).
    """
    resumo = resumo_cliente(cliente_id)
    if not resumo:
        return {}
    with Sessao() as sessao:
        for modelo in _MODELOS_FILHOS:
            sessao.query(modelo).filter(modelo.cliente_id == cliente_id).delete(
                synchronize_session=False
            )
        sessao.query(Cliente).filter(Cliente.id == cliente_id).delete(
            synchronize_session=False
        )
        sessao.commit()
    return resumo
