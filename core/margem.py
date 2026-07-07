"""Cálculo de margem real por pedido.

    margem = valor_total
             − comissão (dado real ou tabela de comissões)
             − frete (custo do vendedor)
             − imposto
             − custo dos produtos vendidos

Opera sobre um DataFrame com uma linha por pedido (montado em
core.metricas) e devolve as colunas de margem. Mantido separado do
dashboard: qualquer front futuro reaproveita este módulo intacto.
"""
import pandas as pd

from core.comissoes import IMPOSTO_PADRAO_PCT, comissao_para_canal


def aplicar_margem(df: pd.DataFrame) -> pd.DataFrame:
    """Espera colunas: valor_total, comissao_fonte, frete, imposto,
    custo_produtos, qtd_itens, canal_nome. Adiciona comissao, origem_comissao,
    taxas_totais, margem e margem_pct."""
    df = df.copy()

    def _comissao(linha):
        if linha["comissao_fonte"] > 0:
            return linha["comissao_fonte"], "fonte"
        regra = comissao_para_canal(linha["canal_nome"])
        if regra:
            estimada = (
                linha["valor_total"] * regra["percentual"]
                + linha["qtd_itens"] * regra["fixo_por_item"]
            )
            return round(estimada, 2), "tabela_comissoes"
        return 0.0, "sem_comissao"

    resultado = df.apply(_comissao, axis=1, result_type="expand")
    df["comissao"] = resultado[0]
    df["origem_comissao"] = resultado[1]

    sem_imposto = df["imposto"] <= 0
    if IMPOSTO_PADRAO_PCT > 0:
        df.loc[sem_imposto, "imposto"] = (
            df.loc[sem_imposto, "valor_total"] * IMPOSTO_PADRAO_PCT
        ).round(2)

    if "outros" not in df.columns:
        df["outros"] = 0.0
    df["taxas_totais"] = df["comissao"] + df["frete"] + df["imposto"] + df["outros"]
    df["margem"] = (
        df["valor_total"] - df["taxas_totais"] - df["custo_produtos"]
    ).round(2)
    df["margem_pct"] = (
        (df["margem"] / df["valor_total"].replace(0, pd.NA)) * 100
    ).astype(float).fillna(0.0)

    return df
