"""Simulador de preços por canal — margem e corredor de lucro."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from core import catalogo, metricas, preferencias, simulador
from core.formatos import moeda, pct
from dashboard.comum import aplicar_estilo, exigir_login, selecionar_cliente

load_dotenv()

st.set_page_config(page_title="Simulador de Preços — Métricas", page_icon="🧮", layout="wide")

exigir_login()
aplicar_estilo()

st.title("🧮 Simulador de Preços")

with st.sidebar:
    st.markdown("### 🧮 Simulador")
    cliente_id, nome_cliente = selecionar_cliente()


@st.cache_data(ttl=60)
def catalogo_cliente(cliente_id: int):
    return catalogo.listar_produtos(cliente_id)


produtos = catalogo_cliente(cliente_id)
canais = metricas.listar_canais(cliente_id)
imposto_pct = preferencias.obter_float(cliente_id, "imposto_pct")

st.caption(
    f"Cliente: **{nome_cliente}** · imposto configurado: {pct(imposto_pct, 0)} · "
    f"canais: {', '.join(canais) if canais else '—'}. "
    "As taxas vêm das Configurações (comissões por faixa + imposto)."
)


def escolher_produto(chave: str) -> tuple[float, dict]:
    """Selebox de produto que devolve (custo, precos_por_canal). Permite custo manual."""
    if produtos.empty:
        st.info("Sem produtos sincronizados para este cliente.")
        st.stop()
    rotulos = {
        f"{r.nome[:60]}  ·  {r.sku or 's/ SKU'}": r.produto_id
        for r in produtos.itertuples()
    }
    escolha = st.selectbox("Produto", list(rotulos), key=f"prod_{chave}")
    linha = produtos[produtos["produto_id"] == rotulos[escolha]].iloc[0]

    custo_produto = float(linha["preco_custo"]) if pd.notna(linha["preco_custo"]) else 0.0
    custo = st.number_input(
        "Custo do produto (R$)", value=round(custo_produto, 2), min_value=0.0,
        step=0.5, key=f"custo_{chave}",
        help="Vem do cadastro/planilha; ajuste se quiser simular outro custo.",
    )
    if custo_produto == 0:
        st.caption("⚠️ Produto sem custo cadastrado — informe acima para simular.")

    precos_canal = {}
    for canal in canais:
        if canal in linha.index and pd.notna(linha[canal]):
            precos_canal[canal] = float(linha[canal])
    return custo, precos_canal


aba_margem, aba_corredor = st.tabs(["💰 Margem por preço", "🎯 Corredor de lucro"])

# ── Aba 1: margem por preço (duas direções) ───────────────────────────────
with aba_margem:
    custo, precos_canal = escolher_produto("margem")
    direcao = st.radio(
        "O que você quer descobrir?",
        ["Tenho o preço → quanto sobra", "Tenho a margem-alvo → qual o preço"],
        horizontal=True,
    )

    if direcao.startswith("Tenho o preço"):
        preco = st.number_input("Preço de venda (R$)", value=49.90, min_value=0.0, step=1.0)
        linhas = simulador.simular_preco(cliente_id, preco, custo)
        tabela = pd.DataFrame([{
            "Canal": l["canal"], "Comissão": l["comissao"], "Imposto": l["imposto"],
            "Custo": l["custo"], "Sobra (lucro)": l["sobra"], "Margem %": l["margem_pct"],
        } for l in linhas])
        st.dataframe(
            tabela, hide_index=True, width="stretch",
            column_config={
                c: st.column_config.NumberColumn(format="R$ %.2f")
                for c in ["Comissão", "Imposto", "Custo", "Sobra (lucro)"]
            } | {"Margem %": st.column_config.NumberColumn(format="%.1f%%")},
        )
        melhor = max(linhas, key=lambda l: l["margem_pct"]) if linhas else None
        if melhor:
            st.success(
                f"A esse preço, o canal mais rentável é **{melhor['canal']}**: "
                f"sobram {moeda(melhor['sobra'])} ({pct(melhor['margem_pct'])} de margem)."
            )
    else:
        margem_alvo = st.number_input("Margem-alvo (%)", value=25.0, min_value=0.0,
                                      max_value=95.0, step=1.0)
        linhas = simulador.preco_para_margem(cliente_id, custo, margem_alvo)
        tabela = pd.DataFrame([{
            "Canal": l["canal"],
            "Preço mínimo para a margem": l["preco_minimo"],
        } for l in linhas])
        st.dataframe(
            tabela, hide_index=True, width="stretch",
            column_config={"Preço mínimo para a margem":
                           st.column_config.NumberColumn(format="R$ %.2f")},
        )
        st.caption(
            f"Preço mínimo em cada canal para o produto (custo {moeda(custo)}) render "
            f"{pct(margem_alvo, 0)} de margem. Abaixo disso, a margem cai. "
            "Vazio = margem inviável nas faixas configuradas."
        )

# ── Aba 2: corredor de lucro ──────────────────────────────────────────────
with aba_corredor:
    st.markdown(
        "Cruza o **piso** (preço mínimo para a sua margem-alvo) com o **teto** "
        "(preço de mercado/concorrente) e diz, por canal, se dá para competir. "
        "O teto começa no **preço médio real já praticado** no canal — ajuste "
        "para o preço do concorrente que quiser testar."
    )
    custo_c, precos_canal_c = escolher_produto("corredor")
    margem_alvo_c = st.number_input("Margem-alvo (%)", value=25.0, min_value=0.0,
                                    max_value=95.0, step=1.0, key="margem_corredor")

    st.markdown("**Preço de mercado por canal (teto)**")
    colunas = st.columns(max(len(canais), 1))
    tetos = {}
    for coluna, canal in zip(colunas, canais):
        padrao = round(precos_canal_c.get(canal, 0.0), 2)
        tetos[canal] = coluna.number_input(
            f"{canal} (R$)", value=padrao, min_value=0.0, step=1.0,
            key=f"teto_{canal}",
            help="Padrão: preço médio já praticado. Troque pelo preço do concorrente.",
        )

    linhas = simulador.corredor(cliente_id, custo_c, margem_alvo_c, tetos)
    for l in linhas:
        with st.container(border=True):
            col_a, col_b, col_c, col_d = st.columns([1.4, 1, 1, 1.6])
            col_a.markdown(f"**{l['canal']}**")
            col_b.metric("Piso", moeda(l["piso"]) if l["piso"] else "—")
            col_c.metric("Teto", moeda(l["teto"]) if l["teto"] else "—")
            if l["margem_no_teto"] is not None:
                col_d.metric("Margem no teto", pct(l["margem_no_teto"]))
            if not l["teto"]:
                st.info(
                    "Informe o preço de mercado deste canal acima para ver o "
                    "veredicto (o produto ainda não tem preço praticado aqui).",
                    icon="✍️",
                )
            elif l["piso"] is None:
                st.warning("Margem-alvo inviável neste canal (as taxas não deixam).", icon="🚫")
            elif l["cabe"]:
                st.success(
                    f"✅ Dá para competir: vendendo a {moeda(l['teto'])} você tem "
                    f"{pct(l['margem_no_teto'])} de margem — folga de {moeda(l['folga'])} "
                    "até o piso.", icon="✅",
                )
            else:
                st.error(
                    f"❌ Não compensa: para {pct(margem_alvo_c, 0)} de margem o preço "
                    f"mínimo é {moeda(l['piso'])}, acima do teto de mercado "
                    f"{moeda(l['teto'])}. Renegocie custo, mude de canal ou monte kit.",
                    icon="❌",
                )
