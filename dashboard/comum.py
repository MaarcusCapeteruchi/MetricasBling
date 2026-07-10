"""Peças compartilhadas entre as páginas do dashboard (login, seletor, estilo)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

from core import catalogo, metricas, usuarios
from core.formatos import moeda

# CSS: ajustes para telas pequenas (celular) — KPIs, títulos e respiros
_ESTILO = """
<style>
@media (max-width: 640px) {
    .block-container {
        padding-left: 0.9rem; padding-right: 0.9rem; padding-top: 2.4rem;
    }
    [data-testid="stMetricValue"] { font-size: 1.35rem; }
    [data-testid="stMetricLabel"] { font-size: 0.8rem; }
    h1 { font-size: 1.5rem !important; }
    h2 { font-size: 1.2rem !important; }
}
</style>
"""


def aplicar_estilo() -> None:
    st.markdown(_ESTILO, unsafe_allow_html=True)


def exigir_login() -> dict:
    """Tela de login (usuário + senha). Retorna o usuário da sessão.

    Contas ficam na tabela `usuarios` (gerenciadas em Configurações →
    Usuários); o acesso mestre é `admin` + APP_SENHA do ambiente. Sem senha
    mestre e sem usuários cadastrados, o painel abre direto (modo dev local).
    """
    if "usuario_logado" in st.session_state:
        _botao_sair()
        return st.session_state["usuario_logado"]

    if not usuarios.login_obrigatorio():
        st.session_state["usuario_logado"] = {
            "id": 0, "nome": "Acesso local", "usuario": "local",
            "papel": "equipe", "cliente_id": None,
        }
        return st.session_state["usuario_logado"]

    aplicar_estilo()
    _, centro, _ = st.columns([1, 2, 1])
    with centro:
        st.markdown("## 📊 Métricas — Margem Real")
        st.caption("Entre com a sua conta para acessar o painel.")
        with st.form("login"):
            usuario = st.text_input("Usuário", autocomplete="username")
            senha = st.text_input("Senha", type="password", autocomplete="current-password")
            if st.form_submit_button("Entrar", type="primary", width="stretch"):
                sessao = usuarios.autenticar(usuario, senha)
                if sessao:
                    st.session_state["usuario_logado"] = sessao
                    st.rerun()
                st.error("Usuário ou senha incorretos.")
    st.stop()


def _botao_sair() -> None:
    usuario = st.session_state.get("usuario_logado") or {}
    with st.sidebar:
        st.caption(f"👤 {usuario.get('nome', '')}")
        if st.button("Sair", width="stretch"):
            for chave in ("usuario_logado", "cliente_nome"):
                st.session_state.pop(chave, None)
            st.rerun()


def selecionar_cliente(rotulo: str = "Cliente") -> tuple[int, str]:
    """Seletor de cliente. Usuário com papel 'cliente' fica travado no seu."""
    clientes = metricas.listar_clientes()
    if clientes.empty:
        st.warning(
            "Banco vazio. Rode `python -m scripts.seed_demo` ou sincronize o Bling."
        )
        st.stop()

    usuario = st.session_state.get("usuario_logado") or {}
    if usuario.get("papel") == "cliente" and usuario.get("cliente_id"):
        proprio = clientes[clientes["id"] == usuario["cliente_id"]]
        if proprio.empty:
            st.error("O cliente vinculado a este usuário não existe mais.")
            st.stop()
        nome = proprio.iloc[0]["nome"]
        st.caption(f"Cliente: **{nome}**")
        return int(proprio.iloc[0]["id"]), nome

    nomes = dict(zip(clientes["nome"], clientes["id"]))
    lista = list(nomes)
    anterior = st.session_state.get("cliente_nome")
    indice = lista.index(anterior) if anterior in lista else 0
    nome = st.selectbox(rotulo, lista, index=indice)
    st.session_state["cliente_nome"] = nome
    return int(nomes[nome]), nome


def exigir_equipe(usuario: dict) -> None:
    """Bloqueia páginas administrativas para usuários com papel 'cliente'."""
    if usuario.get("papel") == "cliente":
        st.warning("Esta área é restrita à equipe.", icon="🔒")
        st.stop()


def montar_visao_produtos(produtos: pd.DataFrame):
    """Tabela de produtos pronta para exibição (painel e Configurações).

    Retorna (visao, column_config): preços por canal e média formatados em
    R$ com '—' quando o produto não vendeu no canal; Preço custo numérico
    (editável apenas onde a página usar data_editor).
    """
    canais = [c for c in produtos.columns if c not in catalogo.COLUNAS_FIXAS]
    renome = {
        "sku": "SKU", "nome": "Produto", "qtd_vendida": "Vendidos",
        "preco_medio_real": "Média geral (R$)", "preco_custo": "Preço custo (R$)",
    }
    renome.update({canal: f"{canal} (R$)" for canal in canais})
    colunas_canal = [f"{canal} (R$)" for canal in canais]

    visao = produtos.rename(columns=renome)[
        ["produto_id", "SKU", "Produto", "Vendidos"]
        + colunas_canal + ["Média geral (R$)", "Preço custo (R$)"]
    ]
    for coluna in colunas_canal + ["Média geral (R$)"]:
        visao[coluna] = visao[coluna].map(
            lambda v: "—" if pd.isna(v) else moeda(float(v))
        )

    config = {
        "produto_id": None,
        "Vendidos": st.column_config.NumberColumn(
            format="%.0f", help="Unidades vendidas no histórico (todos os canais)."),
        "Média geral (R$)": st.column_config.TextColumn(
            help="Média dos preços reais de venda entre todos os marketplaces. "
                 "— significa que o produto ainda não vendeu."),
        "Preço custo (R$)": st.column_config.NumberColumn(
            format="R$ %.2f", min_value=0,
            help="Quanto o produto custou para o cliente."),
    }
    for canal, coluna in zip(canais, colunas_canal):
        config[coluna] = st.column_config.TextColumn(
            help=f"Preço médio de venda real em {canal}. "
                 "— significa que o produto ainda não vendeu neste canal.")
    return visao, config
