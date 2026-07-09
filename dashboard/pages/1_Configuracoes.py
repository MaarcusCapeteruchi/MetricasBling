"""Configurações editáveis pelo usuário — comissões por canal e custos.

Objetivo: o sistema opera sem depender de edição de código. Aqui o usuário
ajusta as taxas de cada plataforma e os custos dos produtos; tudo grava no
banco (por cliente) e o painel recalcula na hora.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from core import catalogo, comissoes
from core.formatos import moeda
from dashboard.comum import exigir_senha, selecionar_cliente

load_dotenv()

st.set_page_config(page_title="Configurações — Métricas", page_icon="⚙️", layout="wide")

exigir_senha()

st.title("⚙️ Configurações")
cliente_id, nome_cliente = selecionar_cliente()
st.caption(f"As configurações abaixo valem para **{nome_cliente}**.")

aba_comissoes, aba_custos = st.tabs(["💸 Comissões por canal", "🏷️ Custos dos produtos"])

# ── Comissões ────────────────────────────────────────────────────────────
with aba_comissoes:
    st.markdown(
        "Comissão estimada quando o marketplace **não** envia a taxa no pedido. "
        "Cada linha é uma faixa por **valor do item**: a comissão é "
        "`valor × %  +  taxa fixa`. Use várias faixas para tabelas escalonadas "
        "(ex.: Shopee). O **canal** casa por parte do nome (ex.: `shopee` cobre "
        "\"Shopee\")."
    )

    chave = f"editor_comissoes_{cliente_id}"
    if chave not in st.session_state:
        st.session_state[chave] = comissoes.regras_para_edicao(cliente_id)

    df_regras = pd.DataFrame(st.session_state[chave])
    editado = st.data_editor(
        df_regras, num_rows="dynamic", width="stretch", key=f"de_{cliente_id}",
        column_config={
            "Canal": st.column_config.TextColumn(required=True, help="ex.: shopee, mercado livre, tiktok"),
            "Vale até R$ (vazio = sem limite)": st.column_config.NumberColumn(
                format="%.2f", help="Teto do valor do item para esta faixa. Vazio = sem limite."),
            "Comissão (%)": st.column_config.NumberColumn(format="%.2f", min_value=0, max_value=100),
            "Taxa fixa por item (R$)": st.column_config.NumberColumn(format="%.2f", min_value=0),
        },
    )

    col_salvar, col_padrao, _ = st.columns([1, 1, 3])
    if col_salvar.button("💾 Salvar comissões", type="primary"):
        n = comissoes.salvar_regras(cliente_id, editado.to_dict("records"))
        st.cache_data.clear()
        st.session_state[chave] = comissoes.regras_para_edicao(cliente_id)
        st.success(f"{n} faixa(s) salva(s). O painel já usa os novos valores.")
        st.rerun()

    if col_padrao.button("↺ Restaurar padrão da pesquisa"):
        comissoes.restaurar_padrao(cliente_id)
        st.cache_data.clear()
        st.session_state.pop(chave, None)
        st.success("Voltou aos valores padrão (Shopee oficial mar/2026; ML e TikTok estimados).")
        st.rerun()

    st.info(
        "**Confirmar quando possível:** Shopee oficial é para vendedor **CNPJ** "
        "(a de CPF difere). Mercado Livre (14%) e TikTok Shop (12%) são estimativas "
        "— os valores exatos ficam nos painéis de vendedor de cada plataforma.",
        icon="ℹ️",
    )

# ── Custos ───────────────────────────────────────────────────────────────
with aba_custos:
    resumo = catalogo.resumo_custos(cliente_id)
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Produtos", resumo["total"])
    col_b.metric("Com custo", resumo["com_custo"])
    col_c.metric("Sem custo", resumo["sem_custo"])
    if resumo["sem_custo"]:
        st.warning(
            f"{resumo['sem_custo']} produto(s) sem custo — a margem fica "
            "superestimada até preencher.", icon="⚠️",
        )

    st.markdown(
        "Edite o **preço de custo** direto na tabela (a coluna verde). Os demais "
        "campos são só leitura. Use a busca para achar produtos."
    )
    busca = st.text_input("🔎 Buscar por nome ou SKU", "")

    produtos = catalogo.listar_produtos(cliente_id)
    if busca.strip():
        filtro = busca.strip().lower()
        produtos = produtos[
            produtos["nome"].str.lower().str.contains(filtro, na=False)
            | produtos["sku"].fillna("").str.lower().str.contains(filtro, na=False)
        ]

    visao = produtos.rename(columns={
        "sku": "SKU", "nome": "Produto",
        "preco_venda": "Preço venda (R$)", "preco_custo": "Preço custo (R$)",
    })
    editado_custos = st.data_editor(
        visao, hide_index=True, width="stretch", height=440, key=f"custos_{cliente_id}",
        disabled=["produto_id", "SKU", "Produto", "Preço venda (R$)"],
        column_config={
            "produto_id": None,
            "Preço venda (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
            "Preço custo (R$)": st.column_config.NumberColumn(format="R$ %.2f", min_value=0),
        },
    )

    if st.button("💾 Salvar custos", type="primary"):
        mapa = {
            int(linha["produto_id"]): linha["Preço custo (R$)"]
            for linha in editado_custos.to_dict("records")
        }
        alterados = catalogo.salvar_custos(cliente_id, mapa)
        st.cache_data.clear()
        st.success(f"{alterados} produto(s) atualizado(s). O painel já recalculou a margem.")
        st.rerun()

    st.caption(
        "Dica: para muitos produtos de uma vez, use "
        "`python -m scripts.importar_custos --cliente <id> --arquivo custos.csv --prefixo`."
    )
