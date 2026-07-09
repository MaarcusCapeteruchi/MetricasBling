"""Leitura e edição do catálogo de produtos (preço de custo pela interface)."""
import pandas as pd
from sqlalchemy import text

from db.database import Sessao, engine
from db.models import Produto

# Colunas fixas de listar_produtos — o que vier além destas são os canais
# (uma coluna de preço médio por marketplace, dinâmica por cliente).
COLUNAS_FIXAS = ["produto_id", "sku", "nome", "preco_custo",
                 "preco_medio_real", "qtd_vendida"]


def listar_produtos(cliente_id: int) -> pd.DataFrame:
    """Produtos do cliente para edição de custo.

    Preços de venda vêm das VENDAS REAIS (itens dos pedidos), não do cadastro
    do Bling — este costuma vir zerado quando o preço fica na variação.
    Como o preço difere por marketplace, além da média geral
    (preco_medio_real) sai uma coluna por canal, ordenadas pelo volume.
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
        por_canal = pd.read_sql(
            text("""
                SELECT i.produto_id, COALESCE(c.nome, 'Sem canal') AS canal,
                       AVG(i.valor_unitario) AS preco_medio,
                       SUM(i.quantidade) AS qtd
                FROM itens_pedido i
                JOIN pedidos p ON p.id = i.pedido_id
                LEFT JOIN canais c ON c.id = p.canal_id
                WHERE i.cliente_id = :c AND i.produto_id IS NOT NULL
                GROUP BY i.produto_id, COALESCE(c.nome, 'Sem canal')
            """),
            conexao, params={"c": cliente_id},
        )

    df["preco_medio_real"] = pd.to_numeric(df["preco_medio_real"], errors="coerce")
    df["preco_custo"] = pd.to_numeric(df["preco_custo"], errors="coerce")
    df["qtd_vendida"] = pd.to_numeric(df["qtd_vendida"], errors="coerce").fillna(0)

    if not por_canal.empty:
        por_canal["preco_medio"] = pd.to_numeric(por_canal["preco_medio"], errors="coerce")
        por_canal["qtd"] = pd.to_numeric(por_canal["qtd"], errors="coerce").fillna(0)
        # canais mais vendidos primeiro (Shopee antes de ML, por exemplo)
        ordem = (por_canal.groupby("canal")["qtd"].sum()
                 .sort_values(ascending=False).index.tolist())
        pivo = por_canal.pivot_table(index="produto_id", columns="canal",
                                     values="preco_medio", aggfunc="mean")
        pivo = pivo.reindex(columns=[c for c in ordem if c in pivo.columns])
        df = df.merge(pivo.reset_index(), on="produto_id", how="left")

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
