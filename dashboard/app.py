"""Dashboard de margem real — lê exclusivamente do modelo canônico.

Rodar localmente:
    streamlit run dashboard/app.py

Nunca chama a API do Bling: o que está no banco é o que aparece.
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from core import catalogo, metricas
from core.formatos import inteiro, moeda, pct
from dashboard.comum import (
    aplicar_estilo,
    exigir_login,
    montar_visao_produtos,
    selecionar_cliente,
)

load_dotenv()

# Paleta validada (dataviz): identidade fixa por série, nunca por posição
COR_RECEITA = "#2a78d6"
COR_MARGEM = "#1baf7a"
COR_INK_MUTED = "#898781"   # legível em tema claro e escuro
COR_GRADE = "#e1e0d9"

st.set_page_config(page_title="Métricas — Margem Real", page_icon="📊", layout="wide")


@st.cache_data(ttl=60)
def carregar_analitico(cliente_id: int, ini: date, fim: date, canais: tuple):
    df = metricas.analitico_pedidos(cliente_id, ini, fim, list(canais) or None)
    itens = metricas.analitico_itens(cliente_id, df)
    produtos = metricas.analitico_produtos(cliente_id, df)
    return df, produtos, itens


@st.cache_data(ttl=60)
def carregar_catalogo(cliente_id: int):
    return catalogo.listar_produtos(cliente_id)


exigir_login()
aplicar_estilo()

# ── Filtros (sidebar) ─────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📊 Métricas")
    cliente_id, nome_cliente = selecionar_cliente()

    preset = st.radio("Período", ["7 dias", "30 dias", "90 dias", "Personalizado"], index=1)
    hoje = date.today()
    if preset == "Personalizado":
        intervalo = st.date_input(
            "Intervalo", value=(hoje - timedelta(days=30), hoje), max_value=hoje
        )
        if len(intervalo) != 2:
            st.stop()
        dt_ini, dt_fim = intervalo
    else:
        dt_fim = hoje
        dt_ini = hoje - timedelta(days=int(preset.split()[0]) - 1)

    canais_disponiveis = metricas.listar_canais(cliente_id)
    canais = st.multiselect("Canais", canais_disponiveis, default=canais_disponiveis)

    limiar = st.number_input(
        "Alerta: margem abaixo de (%)",
        value=float(os.getenv("MARGEM_ALERTA_PCT", "10")), min_value=0.0, step=1.0,
    )

df, produtos, itens_vendidos = carregar_analitico(cliente_id, dt_ini, dt_fim, tuple(canais))

st.title(f"Margem real — {nome_cliente}")
sinc = metricas.ultima_sincronizacao(cliente_id)
if sinc:
    st.caption(
        f"Última sincronização ({sinc['fonte']}): {sinc['status']} — "
        f"{sinc['pedidos_processados']} pedidos, {sinc['produtos_processados']} produtos."
    )

if df.empty:
    st.info("Nenhum pedido no período/canais selecionados.")
    st.stop()

# ── Alerta de margem baixa (valor proativo, não só relatório) ─────────────
margem_baixa = metricas.produtos_margem_baixa(produtos, limiar)
if not margem_baixa.empty:
    piores = " · ".join(
        f"**{linha.produto}** ({pct(linha.margem_pct)})"
        for linha in margem_baixa.head(5).itertuples()
    )
    st.error(
        f"**{len(margem_baixa)} produto(s) com margem abaixo de {pct(limiar, 0)} "
        f"no período:** {piores}",
        icon="⚠️",
    )

# ── KPIs ──────────────────────────────────────────────────────────────────
k = metricas.kpis(df)
colunas = st.columns(5)
colunas[0].metric("Vendas no período", moeda(k["receita"]))
colunas[1].metric("Pedidos", inteiro(k["pedidos"]),
                  delta=f"ticket médio {moeda(k['ticket_medio'])}", delta_color="off")
colunas[2].metric("Taxas pagas", moeda(k["taxas"]),
                  delta=f"-{pct(k['taxas'] / k['receita'] * 100 if k['receita'] else 0)} da receita",
                  delta_color="off")
colunas[3].metric("Custo dos produtos", moeda(k["custo"]))
colunas[4].metric("Margem real", moeda(k["margem"]), delta=pct(k["margem_pct"]) + " da receita")

if k["pct_comissao_real"] < 100:
    st.caption(
        f"Comissões: {pct(k['pct_comissao_real'])} da receita com comissão real da fonte; "
        "o restante foi estimado pela tabela de comissões (core/comissoes.py)."
    )

st.divider()

# ── Evolução de vendas e margem ───────────────────────────────────────────
serie = metricas.vendas_por_dia(df)
grafico = go.Figure()
grafico.add_trace(go.Scatter(
    x=serie["data"], y=serie["receita"], name="Receita",
    mode="lines", line=dict(color=COR_RECEITA, width=2),
    hovertemplate="R$ %{y:,.2f}<extra>Receita</extra>",
))
grafico.add_trace(go.Scatter(
    x=serie["data"], y=serie["margem"], name="Margem real",
    mode="lines", line=dict(color=COR_MARGEM, width=2),
    hovertemplate="R$ %{y:,.2f}<extra>Margem real</extra>",
))
grafico.update_layout(
    title=dict(text="Evolução diária — receita × margem real", font=dict(size=15)),
    hovermode="x unified",
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color=COR_INK_MUTED),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    margin=dict(l=10, r=10, t=60, b=10), height=380,
    xaxis=dict(showgrid=False, linecolor=COR_GRADE),
    yaxis=dict(gridcolor=COR_GRADE, zeroline=False, tickprefix="R$ ", separatethousands=True),
)
st.plotly_chart(grafico, width="stretch")

# ── Composição das taxas + top produtos ───────────────────────────────────
coluna_taxas, coluna_produtos = st.columns([2, 3])

with coluna_taxas:
    st.markdown("**Para onde vão as taxas**")
    categorias = [("Comissão", k["comissao"]), ("Frete", k["frete"]),
                  ("Imposto", k["imposto"]), ("Outras", k["outros"])]
    categorias = [c for c in categorias if c[1] > 0]
    barras = go.Figure(go.Bar(
        y=[c[0] for c in categorias][::-1],
        x=[c[1] for c in categorias][::-1],
        orientation="h", marker=dict(color=COR_RECEITA),
        text=[moeda(c[1]) for c in categorias][::-1],
        textposition="outside", cliponaxis=False,
        hovertemplate="%{text}<extra>%{y}</extra>",
    ))
    barras.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=COR_INK_MUTED),
        xaxis=dict(visible=False), yaxis=dict(ticksuffix="  "),
        margin=dict(l=10, r=60, t=10, b=10), height=260,
    )
    st.plotly_chart(barras, width="stretch")

with coluna_produtos:
    st.markdown("**Top produtos por margem no período**")
    tabela = produtos.rename(columns={
        "produto": "Produto", "qtd_vendida": "Qtd", "receita": "Receita",
        "taxas": "Taxas", "custo": "Custo", "margem": "Margem", "margem_pct": "Margem %",
    })
    st.dataframe(
        tabela, hide_index=True, width="stretch", height=300,
        column_config={
            "Qtd": st.column_config.NumberColumn(format="%.0f"),
            "Receita": st.column_config.NumberColumn(format="R$ %.2f"),
            "Taxas": st.column_config.NumberColumn(format="R$ %.2f"),
            "Custo": st.column_config.NumberColumn(format="R$ %.2f"),
            "Margem": st.column_config.NumberColumn(format="R$ %.2f"),
            "Margem %": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )

with st.expander("🛒 Últimas vendas — produto a produto (mais recentes primeiro)"):
    if itens_vendidos.empty:
        st.caption("Sem vendas no período selecionado.")
    else:
        feed = itens_vendidos.sort_values(
            ["data", "pedido_id"], ascending=False
        ).head(300)
        feed = feed.rename(columns={
            "data": "Data", "numero": "Pedido", "canal_nome": "Canal",
            "sku": "SKU", "produto": "Produto", "quantidade": "Qtd",
            "valor_unitario": "Preço unit.", "receita_item": "Receita",
            "margem_item": "Margem", "margem_pct_item": "Margem %",
        })[["Data", "Pedido", "Canal", "SKU", "Produto", "Qtd",
            "Preço unit.", "Receita", "Margem", "Margem %"]]
        st.dataframe(
            feed, hide_index=True, width="stretch", height=380,
            column_config={
                "Qtd": st.column_config.NumberColumn(format="%.0f"),
                "Preço unit.": st.column_config.NumberColumn(format="R$ %.2f"),
                "Receita": st.column_config.NumberColumn(format="R$ %.2f"),
                "Margem": st.column_config.NumberColumn(
                    format="R$ %.2f",
                    help="Margem do item: receita menos taxas rateadas e custo."),
                "Margem %": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )
        st.caption(
            f"Mostrando as {len(feed)} vendas mais recentes do período filtrado "
            "(atualiza a cada sincronização)."
        )

with st.expander("📦 Catálogo — preços por marketplace e custo (todos os produtos)"):
    visao_catalogo, config_catalogo = montar_visao_produtos(carregar_catalogo(cliente_id))
    st.dataframe(
        visao_catalogo, hide_index=True, width="stretch", height=380,
        column_config=config_catalogo,
    )
    st.caption(
        "Somente leitura. Para editar custos ou usar a planilha Excel: "
        "Configurações → Custos dos produtos."
    )

with st.expander("Ver dados diários em tabela"):
    st.dataframe(
        serie.rename(columns={"data": "Data", "receita": "Receita", "margem": "Margem real"}),
        hide_index=True, width="stretch",
        column_config={
            "Receita": st.column_config.NumberColumn(format="R$ %.2f"),
            "Margem real": st.column_config.NumberColumn(format="R$ %.2f"),
        },
    )

st.caption(
    "Margem real = vendas − comissões − frete − impostos − custo dos produtos. "
    "Fonte: modelo canônico (o painel nunca consulta a API ao vivo)."
)
