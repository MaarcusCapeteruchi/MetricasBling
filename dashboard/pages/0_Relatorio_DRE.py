"""Relatório DRE por cliente e período, com exportação em PDF (Caplace)."""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from core import dre as mod_dre
from core.formatos import moeda, pct
from dashboard.comum import aplicar_estilo, exigir_login, selecionar_cliente

load_dotenv()

st.set_page_config(page_title="Relatório DRE — Métricas", page_icon="📑", layout="wide")

exigir_login()
aplicar_estilo()

st.title("📑 Relatório DRE")
st.caption("Demonstração do Resultado por cliente e período — na tela e em PDF.")

with st.sidebar:
    st.markdown("### 📑 DRE")
    cliente_id, nome_cliente = selecionar_cliente()

    preset = st.radio("Período", ["Últimos 30 dias", "Últimos 90 dias",
                                  "Este mês", "Mês passado", "Personalizado"], index=0)
    hoje = date.today()
    if preset == "Últimos 30 dias":
        dt_ini, dt_fim = hoje - timedelta(days=29), hoje
    elif preset == "Últimos 90 dias":
        dt_ini, dt_fim = hoje - timedelta(days=89), hoje
    elif preset == "Este mês":
        dt_ini, dt_fim = hoje.replace(day=1), hoje
    elif preset == "Mês passado":
        primeiro_deste = hoje.replace(day=1)
        dt_fim = primeiro_deste - timedelta(days=1)
        dt_ini = dt_fim.replace(day=1)
    else:
        intervalo = st.date_input("Intervalo", value=(hoje - timedelta(days=29), hoje),
                                  max_value=hoje)
        if len(intervalo) != 2:
            st.stop()
        dt_ini, dt_fim = intervalo


@st.cache_data(ttl=60)
def carregar_dre(cliente_id: int, ini: date, fim: date):
    return mod_dre.montar_dre(cliente_id, ini, fim)


dre = carregar_dre(cliente_id, dt_ini, dt_fim)
kpis = dre["kpis"]

st.markdown(
    f"**{nome_cliente}** · {dt_ini.strftime('%d/%m/%Y')} a {dt_fim.strftime('%d/%m/%Y')} "
    f"· {kpis['pedidos']} pedidos válidos"
)

if kpis["pedidos"] == 0:
    st.info("Nenhum pedido no período selecionado.")
    st.stop()

# ── DRE na tela ───────────────────────────────────────────────────────────
tabela_dre = pd.DataFrame([
    {"Conta": linha["conta"], "Valor": moeda(linha["valor"]),
     "% da receita": pct(linha["pct"])}
    for linha in dre["linhas"]
])
st.dataframe(tabela_dre, hide_index=True, width="stretch",
             height=min(60 + 36 * len(tabela_dre), 420))

coluna_a, coluna_b, coluna_c = st.columns(3)
coluna_a.metric("Receita bruta", moeda(kpis["receita"]))
coluna_b.metric("Resultado bruto", moeda(kpis["margem"]))
coluna_c.metric("Margem", pct(kpis["margem_pct"]))

# ── Por canal ─────────────────────────────────────────────────────────────
por_canal = dre["por_canal"]
if len(por_canal):
    st.markdown("**Resultado por canal**")
    visao_canal = por_canal.rename(columns={
        "canal_nome": "Canal", "pedidos": "Pedidos", "receita": "Receita",
        "taxas": "Taxas", "cmv": "CMV", "resultado": "Resultado",
        "margem_pct": "Margem %",
    })
    st.dataframe(
        visao_canal, hide_index=True, width="stretch",
        column_config={
            "Pedidos": st.column_config.NumberColumn(format="%.0f"),
            "Receita": st.column_config.NumberColumn(format="R$ %.2f"),
            "Taxas": st.column_config.NumberColumn(format="R$ %.2f"),
            "CMV": st.column_config.NumberColumn(format="R$ %.2f"),
            "Resultado": st.column_config.NumberColumn(format="R$ %.2f"),
            "Margem %": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )

with st.expander("📝 Notas metodológicas"):
    for texto in dre["notas"]:
        st.markdown(f"- {texto}")

# ── PDF ───────────────────────────────────────────────────────────────────
st.divider()
nome_arquivo = (
    f"DRE_{nome_cliente.replace(' ', '_')}_"
    f"{dt_ini.strftime('%Y-%m-%d')}_a_{dt_fim.strftime('%Y-%m-%d')}.pdf"
)
st.download_button(
    "📄 Baixar DRE em PDF",
    data=mod_dre.gerar_pdf_dre(nome_cliente, dt_ini, dt_fim, dre),
    file_name=nome_arquivo, mime="application/pdf", type="primary",
    help="PDF com a identidade Caplace Consulting, pronto para enviar ao cliente.",
)
