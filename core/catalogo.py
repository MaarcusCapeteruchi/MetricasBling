"""Leitura e edição do catálogo de produtos (preço de custo pela interface)."""
import pandas as pd
from sqlalchemy import text

from db.database import Sessao, engine
from db.models import Produto


def listar_produtos(cliente_id: int) -> pd.DataFrame:
    """Produtos do cliente com preço de venda e custo, para edição."""
    with engine.connect() as conexao:
        df = pd.read_sql(
            text("""
                SELECT id AS produto_id, sku, nome, preco_venda, preco_custo
                FROM produtos WHERE cliente_id = :c ORDER BY nome
            """),
            conexao, params={"c": cliente_id},
        )
    df["preco_venda"] = pd.to_numeric(df["preco_venda"], errors="coerce")
    df["preco_custo"] = pd.to_numeric(df["preco_custo"], errors="coerce")
    return df


def salvar_custos(cliente_id: int, custos: dict[int, float | None]) -> int:
    """Atualiza preco_custo dos produtos informados (id -> custo). Conta alterados."""
    alterados = 0
    with Sessao() as sessao:
        for produto_id, custo in custos.items():
            produto = sessao.get(Produto, int(produto_id))
            if produto is None or produto.cliente_id != cliente_id:
                continue
            novo = None if custo in (None, "") else round(float(custo), 2)
            atual = float(produto.preco_custo) if produto.preco_custo is not None else None
            if novo != atual:
                produto.preco_custo = novo
                alterados += 1
        sessao.commit()
    return alterados


def resumo_custos(cliente_id: int) -> dict:
    """Quantos produtos têm custo preenchido — mostrado na tela de configuração."""
    df = listar_produtos(cliente_id)
    com_custo = int(((df["preco_custo"].notna()) & (df["preco_custo"] > 0)).sum())
    return {"total": len(df), "com_custo": com_custo, "sem_custo": len(df) - com_custo}
