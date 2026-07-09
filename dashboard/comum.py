"""Peças compartilhadas entre as páginas do dashboard (senha e seletor)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st

from core import metricas


def exigir_senha() -> None:
    """Trava o acesso quando APP_SENHA está definida. Vale para todas as páginas."""
    senha = os.getenv("APP_SENHA", "").strip()
    if not senha or st.session_state.get("autenticado"):
        return
    st.title("📊 Métricas — Margem Real")
    with st.form("login"):
        digitada = st.text_input("Senha de acesso", type="password")
        if st.form_submit_button("Entrar"):
            if digitada == senha:
                st.session_state["autenticado"] = True
                st.rerun()
            st.error("Senha incorreta.")
    st.stop()


def selecionar_cliente(rotulo: str = "Cliente") -> tuple[int, str]:
    """Seletor de cliente que lembra a escolha entre páginas (session_state)."""
    clientes = metricas.listar_clientes()
    if clientes.empty:
        st.warning(
            "Banco vazio. Rode `python -m scripts.seed_demo` ou sincronize o Bling."
        )
        st.stop()

    nomes = dict(zip(clientes["nome"], clientes["id"]))
    lista = list(nomes)
    anterior = st.session_state.get("cliente_nome")
    indice = lista.index(anterior) if anterior in lista else 0
    nome = st.selectbox(rotulo, lista, index=indice)
    st.session_state["cliente_nome"] = nome
    return int(nomes[nome]), nome
