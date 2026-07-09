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

from core import catalogo, clientes, comissoes, metricas
from core.formatos import moeda
from dashboard.comum import exigir_senha, selecionar_cliente

load_dotenv()

st.set_page_config(page_title="Configurações — Métricas", page_icon="⚙️", layout="wide")

exigir_senha()

st.title("⚙️ Configurações")
cliente_id, nome_cliente = selecionar_cliente()
st.caption(f"As configurações abaixo valem para **{nome_cliente}**.")

aba_comissoes, aba_custos, aba_clientes = st.tabs(
    ["💸 Comissões por canal", "🏷️ Custos dos produtos", "👥 Clientes"]
)

# ── Comissões ────────────────────────────────────────────────────────────
with aba_comissoes:
    st.markdown(
        "Comissão estimada quando o marketplace **não** envia a taxa no pedido. "
        "Cada linha é uma faixa por **valor do item**: a comissão é "
        "`valor × %  +  taxa fixa`."
    )

    # Perfil do vendedor na Shopee — troca as faixas da Shopee pelo preset oficial
    perfil_atual = comissoes.perfil_shopee(cliente_id)
    rotulos = {"cnpj": "Vendedor CNPJ", "cpf": "Vendedor CPF"}
    escolha = st.radio(
        "Perfil do vendedor na **Shopee**",
        options=["cnpj", "cpf"],
        index=0 if perfil_atual == "cnpj" else 1,
        format_func=lambda p: rotulos[p],
        horizontal=True,
        help="Troca automaticamente as faixas da Shopee pela tabela oficial do "
             "perfil. CNPJ e CPF têm as mesmas faixas; o CPF de alto volume "
             "(+450 pedidos/90 dias) paga +R$3 por item.",
    )
    if escolha != perfil_atual:
        comissoes.aplicar_perfil_shopee(cliente_id, escolha)
        st.cache_data.clear()
        st.session_state.pop(f"editor_comissoes_{cliente_id}", None)
        st.rerun()
    if escolha == "cpf":
        st.caption(
            "Perfil CPF assume vendedor de **alto volume** (+450 pedidos/90 dias, "
            "+R$3 por item). Se for CPF de baixo volume, edite a taxa fixa das linhas Shopee."
        )

    with st.expander("❓ O que é cada coluna"):
        st.markdown(
            "- **Canal** — nome da plataforma. Casa por parte do nome: `shopee` "
            "cobre \"Shopee\", `mercado livre` cobre \"Mercado Livre\" etc. "
            "Canais sem regra (ex.: site próprio) não têm comissão estimada.\n"
            "- **Vale até R$ (vazio = sem limite)** — teto do **valor do item** "
            "para esta faixa valer. Ex.: `99,99` = vale para itens até R$99,99. "
            "Deixe vazio na última faixa (dali para cima).\n"
            "- **Comissão (%)** — percentual sobre o valor do item.\n"
            "- **Taxa fixa por item (R$)** — valor fixo somado por unidade vendida.\n\n"
            "A comissão de cada item = `valor × Comissão% + Taxa fixa`, pela primeira "
            "faixa que cobre o valor. A do pedido é a soma dos itens."
        )

    chave = f"editor_comissoes_{cliente_id}"
    if chave not in st.session_state:
        st.session_state[chave] = comissoes.regras_para_edicao(cliente_id)

    df_regras = pd.DataFrame(st.session_state[chave])
    editado = st.data_editor(
        df_regras, num_rows="dynamic", width="stretch", key=f"de_{cliente_id}",
        column_config={
            "Canal": st.column_config.TextColumn(
                required=True,
                help="Nome do canal. Casa por parte do nome (ex.: 'shopee' cobre 'Shopee')."),
            "Vale até R$ (vazio = sem limite)": st.column_config.NumberColumn(
                format="%.2f",
                help="Teto do VALOR DO ITEM para esta faixa. Vazio = sem limite (última faixa)."),
            "Comissão (%)": st.column_config.NumberColumn(
                format="%.2f", min_value=0, max_value=100,
                help="Percentual cobrado sobre o valor do item."),
            "Taxa fixa por item (R$)": st.column_config.NumberColumn(
                format="%.2f", min_value=0,
                help="Valor fixo somado por unidade vendida, além do percentual."),
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

# ── Clientes ─────────────────────────────────────────────────────────────
with aba_clientes:
    st.markdown("Clientes cadastrados no sistema:")
    lista = metricas.listar_clientes()
    st.dataframe(
        lista.rename(columns={"id": "ID", "nome": "Cliente"}),
        hide_index=True, width="stretch",
    )

    st.divider()
    st.subheader("Excluir um cliente")
    st.warning(
        "A exclusão remove **todos os dados** do cliente (pedidos, produtos, "
        "canais, taxas, comissões, tokens do Bling). **Não há como desfazer.**",
        icon="⚠️",
    )

    nomes = dict(zip(lista["nome"], lista["id"]))
    alvo_nome = st.selectbox("Cliente a excluir", list(nomes), key="excluir_alvo")
    alvo_id = int(nomes[alvo_nome])
    resumo = clientes.resumo_cliente(alvo_id)

    col1, col2 = st.columns(2)
    col1.metric("Pedidos", resumo.get("pedidos", 0))
    col2.metric("Produtos", resumo.get("produtos", 0))
    if resumo.get("tem_credencial"):
        st.info(
            "Este cliente tem conexão ativa com o Bling (tokens OAuth). Excluir "
            "também remove essa conexão — será preciso autorizar de novo para "
            "voltar a sincronizar.", icon="🔌",
        )

    st.caption(f"Para confirmar, digite o nome exato do cliente: **{alvo_nome}**")
    confirmacao = st.text_input("Nome do cliente", key="excluir_confirma",
                                label_visibility="collapsed", placeholder=alvo_nome)
    pode_excluir = confirmacao.strip() == alvo_nome

    if st.button("🗑️ Excluir cliente definitivamente", type="primary",
                 disabled=not pode_excluir):
        apagado = clientes.excluir_cliente(alvo_id)
        st.cache_data.clear()
        # limpa seleção lembrada para não apontar para um cliente que sumiu
        for chave in ("cliente_nome", "excluir_alvo", "excluir_confirma",
                      f"editor_comissoes_{alvo_id}"):
            st.session_state.pop(chave, None)
        st.success(
            f"Cliente **{apagado.get('nome')}** excluído "
            f"({apagado.get('pedidos', 0)} pedidos, {apagado.get('produtos', 0)} produtos)."
        )
        st.rerun()

    if not pode_excluir and confirmacao.strip():
        st.caption("O nome digitado não confere — a exclusão fica bloqueada.")
