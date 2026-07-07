"""Consultas analíticas sobre o modelo canônico.

Única porta de entrada de dados do dashboard: tudo aqui filtra por
cliente_id (multi-tenant) e lê exclusivamente do banco — nunca da API.
"""
from datetime import date

import pandas as pd
from sqlalchemy import text

from core.margem import aplicar_margem
from db.database import engine


def _df(sql: str, params: dict) -> pd.DataFrame:
    with engine.connect() as conexao:
        return pd.read_sql(text(sql), conexao, params=params)


def listar_clientes() -> pd.DataFrame:
    return _df("SELECT id, nome FROM clientes ORDER BY nome", {})


def listar_canais(cliente_id: int) -> list[str]:
    df = _df(
        "SELECT DISTINCT nome FROM canais WHERE cliente_id = :c ORDER BY nome",
        {"c": cliente_id},
    )
    return df["nome"].tolist()


def ultima_sincronizacao(cliente_id: int) -> dict | None:
    df = _df(
        """
        SELECT fonte, iniciada_em, finalizada_em, status,
               pedidos_processados, produtos_processados
        FROM sincronizacoes WHERE cliente_id = :c
        ORDER BY iniciada_em DESC LIMIT 1
        """,
        {"c": cliente_id},
    )
    return df.iloc[0].to_dict() if len(df) else None


def analitico_pedidos(cliente_id: int, dt_ini: date, dt_fim: date,
                      canais: list[str] | None = None) -> pd.DataFrame:
    """Uma linha por pedido no período, com margem real calculada."""
    pedidos = _df(
        """
        SELECT p.id AS pedido_id, p.numero, p.data, p.situacao,
               p.valor_total, COALESCE(c.nome, 'Sem canal') AS canal_nome
        FROM pedidos p
        LEFT JOIN canais c ON c.id = p.canal_id
        WHERE p.cliente_id = :c AND p.data BETWEEN :ini AND :fim
        """,
        {"c": cliente_id, "ini": dt_ini.isoformat(), "fim": dt_fim.isoformat()},
    )
    if pedidos.empty:
        return pedidos

    itens = _df(
        """
        SELECT i.pedido_id,
               SUM(i.quantidade) AS qtd_itens,
               SUM(i.quantidade * COALESCE(pr.preco_custo, 0)) AS custo_produtos
        FROM itens_pedido i
        LEFT JOIN produtos pr ON pr.id = i.produto_id
        WHERE i.cliente_id = :c
        GROUP BY i.pedido_id
        """,
        {"c": cliente_id},
    )
    taxas = _df(
        """
        SELECT pedido_id,
               SUM(CASE WHEN tipo = 'comissao' THEN valor ELSE 0 END) AS comissao_fonte,
               SUM(CASE WHEN tipo = 'frete'    THEN valor ELSE 0 END) AS frete,
               SUM(CASE WHEN tipo = 'imposto'  THEN valor ELSE 0 END) AS imposto,
               SUM(CASE WHEN tipo NOT IN ('comissao','frete','imposto')
                        THEN valor ELSE 0 END) AS outros
        FROM taxas_pedido WHERE cliente_id = :c
        GROUP BY pedido_id
        """,
        {"c": cliente_id},
    )

    df = pedidos.merge(itens, on="pedido_id", how="left").merge(
        taxas, on="pedido_id", how="left"
    )
    for coluna in ["valor_total", "qtd_itens", "custo_produtos",
                   "comissao_fonte", "frete", "imposto", "outros"]:
        df[coluna] = pd.to_numeric(df[coluna], errors="coerce").fillna(0.0)
    df["data"] = pd.to_datetime(df["data"]).dt.date

    # Cancelados ficam fora da análise de margem
    df = df[~df["situacao"].str.lower().str.startswith("cancel", na=False)]
    if canais:
        df = df[df["canal_nome"].isin(canais)]
    if df.empty:
        return df

    return aplicar_margem(df.reset_index(drop=True))


def analitico_produtos(cliente_id: int, df_pedidos: pd.DataFrame) -> pd.DataFrame:
    """Margem por produto, com as taxas do pedido rateadas pela receita do item."""
    if df_pedidos.empty:
        return pd.DataFrame()

    itens = _df(
        """
        SELECT i.pedido_id, i.quantidade, i.valor_total AS receita_item,
               COALESCE(pr.nome, i.descricao) AS produto,
               COALESCE(pr.preco_custo, 0) AS preco_custo
        FROM itens_pedido i
        LEFT JOIN produtos pr ON pr.id = i.produto_id
        WHERE i.cliente_id = :c
        """,
        {"c": cliente_id},
    )
    for coluna in ["quantidade", "receita_item", "preco_custo"]:
        itens[coluna] = pd.to_numeric(itens[coluna], errors="coerce").fillna(0.0)

    base = itens.merge(
        df_pedidos[["pedido_id", "valor_total", "taxas_totais"]],
        on="pedido_id", how="inner",
    )
    if base.empty:
        return pd.DataFrame()

    proporcao = (base["receita_item"] / base["valor_total"].replace(0, pd.NA)).fillna(0.0)
    base["taxas_item"] = (base["taxas_totais"] * proporcao).round(2)
    base["custo_item"] = (base["quantidade"] * base["preco_custo"]).round(2)
    base["margem_item"] = base["receita_item"] - base["taxas_item"] - base["custo_item"]

    por_produto = (
        base.groupby("produto", as_index=False)
        .agg(
            qtd_vendida=("quantidade", "sum"),
            receita=("receita_item", "sum"),
            taxas=("taxas_item", "sum"),
            custo=("custo_item", "sum"),
            margem=("margem_item", "sum"),
        )
    )
    por_produto["margem_pct"] = (
        (por_produto["margem"] / por_produto["receita"].replace(0, pd.NA)) * 100
    ).astype(float).fillna(0.0)
    return por_produto.sort_values("margem", ascending=False).reset_index(drop=True)


def kpis(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "receita": 0.0, "pedidos": 0, "ticket_medio": 0.0, "taxas": 0.0,
            "comissao": 0.0, "frete": 0.0, "imposto": 0.0, "outros": 0.0,
            "custo": 0.0, "margem": 0.0, "margem_pct": 0.0, "pct_comissao_real": 0.0,
        }
    receita = float(df["valor_total"].sum())
    margem = float(df["margem"].sum())
    com_comissao_real = float(df.loc[df["origem_comissao"] == "fonte", "valor_total"].sum())
    return {
        "receita": receita,
        "pedidos": int(len(df)),
        "ticket_medio": receita / len(df),
        "taxas": float(df["taxas_totais"].sum()),
        "comissao": float(df["comissao"].sum()),
        "frete": float(df["frete"].sum()),
        "imposto": float(df["imposto"].sum()),
        "outros": float(df["outros"].sum()),
        "custo": float(df["custo_produtos"].sum()),
        "margem": margem,
        "margem_pct": (margem / receita * 100) if receita else 0.0,
        "pct_comissao_real": (com_comissao_real / receita * 100) if receita else 0.0,
    }


def vendas_por_dia(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["data", "receita", "margem"])
    diario = (
        df.groupby("data", as_index=False)
        .agg(receita=("valor_total", "sum"), margem=("margem", "sum"))
        .sort_values("data")
    )
    dias = pd.DataFrame({
        "data": pd.date_range(diario["data"].min(), diario["data"].max()).date
    })
    return dias.merge(diario, on="data", how="left").fillna(0.0)


def produtos_margem_baixa(df_produtos: pd.DataFrame, limiar_pct: float) -> pd.DataFrame:
    if df_produtos.empty:
        return df_produtos
    filtro = (df_produtos["margem_pct"] < limiar_pct) & (df_produtos["receita"] > 0)
    return df_produtos[filtro].sort_values("margem_pct").reset_index(drop=True)
