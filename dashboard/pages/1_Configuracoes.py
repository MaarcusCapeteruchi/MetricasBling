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

from core import catalogo, clientes, comissoes, metricas, preferencias, usuarios
from core.formatos import moeda
from dashboard.comum import (
    aplicar_estilo,
    exigir_equipe,
    exigir_login,
    montar_visao_produtos,
    selecionar_cliente,
)

load_dotenv()

st.set_page_config(page_title="Configurações — Métricas", page_icon="⚙️", layout="wide")

usuario_logado = exigir_login()
exigir_equipe(usuario_logado)
aplicar_estilo()

st.title("⚙️ Configurações")
cliente_id, nome_cliente = selecionar_cliente()
st.caption(f"As configurações abaixo valem para **{nome_cliente}**.")

aba_comissoes, aba_custos, aba_estimativas, aba_clientes, aba_usuarios = st.tabs(
    ["💸 Comissões por canal", "🏷️ Custos dos produtos",
     "🧾 Impostos e custos", "👥 Clientes", "🔐 Usuários"]
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
    st.caption(
        "Os preços de venda vêm das **vendas reais** (não do cadastro do Bling, "
        "que costuma vir zerado): uma coluna com o preço médio em **cada "
        "marketplace** e uma com a **média geral**. Célula vazia = o produto "
        "ainda não vendeu naquele canal."
    )
    busca = st.text_input("🔎 Buscar por nome ou SKU", "")

    produtos = catalogo.listar_produtos(cliente_id)
    if busca.strip():
        filtro = busca.strip().lower()
        produtos = produtos[
            produtos["nome"].str.lower().str.contains(filtro, na=False)
            | produtos["sku"].fillna("").str.lower().str.contains(filtro, na=False)
        ]

    visao, config_colunas = montar_visao_produtos(produtos)
    editado_custos = st.data_editor(
        visao, hide_index=True, width="stretch", height=440, key=f"custos_{cliente_id}",
        disabled=[c for c in visao.columns if c != "Preço custo (R$)"],
        column_config=config_colunas,
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

    st.divider()
    st.markdown("**📊 Planilha de custos (Excel)** — para preencher muitos produtos de uma vez")
    col_exportar, col_importar = st.columns(2)
    with col_exportar:
        st.download_button(
            "📥 Baixar planilha modelo",
            data=catalogo.gerar_planilha_modelo(cliente_id),
            file_name=f"custos_{nome_cliente.replace(' ', '_').lower()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            help="Excel com todos os produtos (SKU, preço de venda) e a coluna "
                 "de custo para preencher.",
        )
        st.caption("Preencha a coluna **Preco custo (R$)** e importe ao lado.")
    with col_importar:
        arquivo = st.file_uploader(
            "📤 Importar planilha preenchida", type=["xlsx", "csv"],
            key=f"upload_custos_{cliente_id}",
        )
        if arquivo is not None and st.button("Aplicar custos da planilha", type="primary"):
            resultado = catalogo.importar_planilha(cliente_id, arquivo, arquivo.name)
            if resultado.get("erro"):
                st.error(resultado["erro"])
            else:
                st.cache_data.clear()
                st.success(
                    f"✅ {resultado['produtos_atualizados']} produto(s) atualizados "
                    f"a partir de {resultado['linhas_com_custo']} linha(s) com custo."
                )
                if resultado["nao_encontrados"]:
                    st.warning(
                        f"SKUs não encontrados ({len(resultado['nao_encontrados'])}): "
                        + ", ".join(resultado["nao_encontrados"][:15]), icon="⚠️",
                    )

# ── Impostos e custos estimados ──────────────────────────────────────────
with aba_estimativas:
    st.markdown(
        "Valores usados quando o pedido **não** traz a taxa da fonte — o dado "
        "real do Bling/marketplace **sempre tem prioridade**; a estimativa só "
        "preenche o que falta. Deixe **0** para não estimar."
    )

    imposto_atual = preferencias.obter_float(cliente_id, "imposto_pct")
    frete_atual = preferencias.obter_float(cliente_id, "frete_estimado_pedido")
    operacional_atual = preferencias.obter_float(cliente_id, "custo_operacional_pedido")

    imposto_novo = st.number_input(
        "Imposto (% sobre a receita do pedido)",
        value=imposto_atual, min_value=0.0, max_value=100.0, step=0.5,
        help="Alíquota efetiva do cliente (ex.: Simples Nacional). Aplica em "
             "todos os pedidos sem imposto informado pela fonte.",
    )
    frete_novo = st.number_input(
        "Frete estimado por pedido (R$)",
        value=frete_atual, min_value=0.0, step=1.0,
        help="Custo de frete do vendedor quando a fonte não informa. "
             "Atenção: na Shopee o frete já está embutido na comissão — "
             "só preencha se algum canal cobrar frete à parte (ex.: Mercado Envios).",
    )
    operacional_novo = st.number_input(
        "Custo operacional por pedido (R$)",
        value=operacional_atual, min_value=0.0, step=0.5,
        help="Embalagem, etiqueta, mão de obra por pedido. Entra como 'Outras' "
             "na composição de taxas.",
    )

    if st.button("💾 Salvar impostos e custos", type="primary"):
        preferencias.definir(cliente_id, "imposto_pct", str(imposto_novo))
        preferencias.definir(cliente_id, "frete_estimado_pedido", str(frete_novo))
        preferencias.definir(cliente_id, "custo_operacional_pedido", str(operacional_novo))
        st.cache_data.clear()
        st.success("Salvo. O painel e o gráfico de taxas já refletem os novos valores.")
        st.rerun()

    st.info(
        "Estes valores aparecem no gráfico **\"Para onde vão as taxas\"** do "
        "painel: imposto vira a barra *Imposto*, frete vira *Frete* e o custo "
        "operacional vira *Outras*.", icon="📊",
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

# ── Usuários ─────────────────────────────────────────────────────────────
with aba_usuarios:
    st.markdown(
        "Contas de acesso ao painel. **Equipe** enxerga todos os clientes e as "
        "Configurações; **Cliente** enxerga apenas o painel do cliente vinculado. "
        "O usuário `admin` (senha mestre dos Secrets) sempre funciona — é a "
        "garantia de nunca ficar trancado para fora."
    )

    lista_usuarios = usuarios.listar()
    if lista_usuarios:
        clientes_df = metricas.listar_clientes()
        nomes_clientes = dict(zip(clientes_df["id"], clientes_df["nome"]))
        st.dataframe(
            [{"Nome": u["nome"], "Usuário": u["usuario"],
              "Papel": "Equipe" if u["papel"] == "equipe" else "Cliente",
              "Cliente vinculado": nomes_clientes.get(u["cliente_id"], "—"),
              "Ativo": "sim" if u["ativo"] else "não"} for u in lista_usuarios],
            hide_index=True, width="stretch",
        )
    else:
        st.info("Nenhum usuário cadastrado ainda — só o acesso mestre `admin` funciona.")

    st.divider()
    col_novo, col_gerir = st.columns(2)

    with col_novo:
        st.subheader("Criar usuário")
        with st.form("novo_usuario", clear_on_submit=True):
            nome_novo = st.text_input("Nome completo")
            login_novo = st.text_input("Usuário (para entrar)")
            senha_nova = st.text_input("Senha (mín. 6 caracteres)", type="password")
            papel_novo = st.radio("Papel", ["equipe", "cliente"], horizontal=True,
                                  format_func=lambda p: "Equipe" if p == "equipe" else "Cliente")
            clientes_df = metricas.listar_clientes()
            opcoes_cliente = dict(zip(clientes_df["nome"], clientes_df["id"]))
            vinculo_nome = st.selectbox(
                "Cliente vinculado (para papel Cliente)", ["—"] + list(opcoes_cliente))
            if st.form_submit_button("➕ Criar", type="primary"):
                erro = usuarios.criar(
                    nome_novo, login_novo, senha_nova, papel_novo,
                    opcoes_cliente.get(vinculo_nome),
                )
                if erro:
                    st.error(erro)
                else:
                    st.success(f"Usuário '{login_novo}' criado.")
                    st.rerun()

    with col_gerir:
        st.subheader("Trocar senha / excluir")
        if lista_usuarios:
            mapa = {f"{u['nome']} ({u['usuario']})": u["id"] for u in lista_usuarios}
            alvo = st.selectbox("Usuário", list(mapa))
            alvo_id = mapa[alvo]
            nova = st.text_input("Nova senha", type="password", key="nova_senha_usuario")
            col_a, col_b = st.columns(2)
            if col_a.button("🔑 Trocar senha"):
                erro = usuarios.trocar_senha(alvo_id, nova)
                st.error(erro) if erro else st.success("Senha alterada.")
            if col_b.button("🗑️ Excluir usuário"):
                usuarios.excluir(alvo_id)
                st.success("Usuário excluído.")
                st.rerun()
        else:
            st.caption("Crie o primeiro usuário ao lado.")
