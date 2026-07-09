"""Leitura e edição do catálogo de produtos (preço de custo pela interface)."""
import pandas as pd
from sqlalchemy import text

from db.database import Sessao, engine
from db.models import Produto


def listar_produtos(cliente_id: int) -> pd.DataFrame:
    """Produtos do cliente para edição de custo.

    Traz o PREÇO MÉDIO DE VENDA REAL (dos pedidos), não o preço do cadastro
    do Bling — este costuma vir zerado quando o vendedor cadastra o preço na
    variação. O preço real varia por marketplace; aqui é a média entre eles.
    """
    with engine.connect() as conexao:
        df = pd.read_sql(
            text("""
                SELECT pr.id AS produto_id, pr.sku, pr.nome, pr.preco_custo,
                       AVG(i.valor_unitario) AS preco_medio_real,
                       COALESCE(SUM(i.quantidade), 0) AS qtd_vendida
                FROM produtos pr
                LEFT JOIN itens_pedido i ON i.produto_id = pr.id
                WHERE pr.cliente_id = :c
                GROUP BY pr.id, pr.sku, pr.nome, pr.preco_custo
                ORDER BY qtd_vendida DESC, pr.nome
            """),
            conexao, params={"c": cliente_id},
        )
    df["preco_medio_real"] = pd.to_numeric(df["preco_medio_real"], errors="coerce")
    df["preco_custo"] = pd.to_numeric(df["preco_custo"], errors="coerce")
    df["qtd_vendida"] = pd.to_numeric(df["qtd_vendida"], errors="coerce").fillna(0)
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
