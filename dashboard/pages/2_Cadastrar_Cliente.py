"""Cadastro de cliente novo 100% pela interface (equipe).

Passo 1: criar o app no Bling do cliente e colar client_id/client_secret.
Passo 2: autorizar — o Bling redireciona de volta para ESTA página com o
código, e o sistema troca por tokens sozinho.
Passo 3: sincronizar com barra de progresso.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st
from dotenv import load_dotenv

from core import onboarding
from conector.sincronizar import executar
from dashboard.comum import aplicar_estilo, exigir_equipe, exigir_login

load_dotenv()

st.set_page_config(page_title="Cadastrar Cliente — Métricas", page_icon="➕", layout="wide")

# ── Retorno do OAuth: chega numa sessão NOVA (antes do login) ─────────────
# O state (uso único, aleatório) identifica o cliente e barra código forjado.
params = st.query_params
if "code" in params and "state" in params:
    resultado = onboarding.resolver_callback(params["code"], params["state"])
    st.query_params.clear()
    if resultado["ok"]:
        st.success(f"✅ {resultado['mensagem']} Faça login para sincronizar os dados.")
        st.balloons()
    else:
        st.error(f"Falha na autorização: {resultado['mensagem']}")

usuario_logado = exigir_login()
exigir_equipe(usuario_logado)
aplicar_estilo()

st.title("➕ Cadastrar Cliente")

# URL desta página — é o link de redirecionamento que vai no app do Bling
try:
    host = st.context.headers.get("host", "localhost:8501")
except Exception:
    host = "localhost:8501"
protocolo = "http" if host.startswith("localhost") else "https"
url_desta_pagina = f"{protocolo}://{host}/Cadastrar_Cliente"

situacao = onboarding.situacao_clientes()

# ── Passo 1: app no Bling + credenciais ───────────────────────────────────
st.subheader("1️⃣ Criar o app no Bling do cliente")
with st.expander("📖 Passo a passo no Bling (uma vez por cliente)"):
    st.markdown(
        f"""
1. Acesse **developer.bling.com.br** logado na **conta Bling do cliente**.
2. **Criar aplicativo** → tipo **API** → uso **Privado**.
3. Dados básicos: nome `Métricas — Margem Real`, categoria *Dashboards e BI*.
4. **Link de redirecionamento** (copie exatamente):
"""
    )
    st.code(url_desta_pagina)
    st.markdown(
        """
5. **Escopos**: marque só **Pedidos de Venda** e **Produtos** (caixa principal
   = visualizar; deixe os sub-itens de edição desmarcados).
6. Salve e copie o **client_id** e o **client_secret** da tela
   *Informações do app* para o formulário abaixo.
"""
    )

with st.form("novo_cliente_app"):
    nome = st.text_input("Nome do cliente (ex.: nome da loja)")
    client_id = st.text_input("client_id do app")
    client_secret = st.text_input("client_secret do app", type="password")
    if st.form_submit_button("💾 Cadastrar cliente", type="primary"):
        novo_id, erro = onboarding.criar_cliente_com_app(nome, client_id, client_secret)
        if erro:
            st.error(erro)
        else:
            st.success(f"Cliente cadastrado (id {novo_id}). Agora gere o link de autorização abaixo.")
            st.rerun()

# ── Passo 2: autorizar ────────────────────────────────────────────────────
st.subheader("2️⃣ Autorizar o acesso")
pendentes = [c for c in situacao if c["tem_app"] and not c["autorizado"]]
if pendentes:
    nomes_pendentes = {c["nome"]: c["id"] for c in pendentes}
    escolhido = st.selectbox("Cliente aguardando autorização", list(nomes_pendentes))
    url_autorizar, erro = onboarding.url_autorizacao(nomes_pendentes[escolhido])
    if erro:
        st.error(erro)
    else:
        st.warning(
            "Abra o link **logado na conta Bling do cliente** (ou numa janela "
            "anônima com o login dele) e clique em Autorizar. Você voltará "
            "para esta página automaticamente.", icon="🔑",
        )
        st.link_button("🔑 Autorizar no Bling", url_autorizar, type="primary")
else:
    st.caption("Nenhum cliente aguardando autorização.")

# ── Passo 3: sincronizar ──────────────────────────────────────────────────
st.subheader("3️⃣ Sincronizar os dados")
autorizados = [c for c in situacao if c["autorizado"]]
if autorizados:
    nomes_autorizados = {c["nome"]: c for c in autorizados}
    alvo_nome = st.selectbox("Cliente", list(nomes_autorizados))
    alvo = nomes_autorizados[alvo_nome]
    st.caption(f"Pedidos já no banco: {alvo['pedidos']}")

    dias = st.radio("Período a buscar", [30, 60, 90], index=2, horizontal=True,
                    format_func=lambda d: f"últimos {d} dias")
    st.caption(
        "A busca respeita o limite de velocidade do Bling — 90 dias de uma "
        "loja movimentada leva ~10 minutos. Deixe esta aba aberta até o fim."
    )
    if st.button("🔄 Sincronizar agora", type="primary"):
        hoje = date.today()
        progresso = st.empty()
        with st.status(f"Sincronizando {alvo_nome}...", expanded=True) as caixa:
            st.write("Buscando produtos...")
            resultado = executar(
                alvo["id"], hoje - timedelta(days=dias), hoje,
                ao_progredir=lambda n: progresso.write(f"📦 {n} pedidos gravados..."),
            )
            caixa.update(label="Sincronização concluída!", state="complete")
        st.cache_data.clear()
        st.success(
            f"✅ {resultado['pedidos']} pedidos e {resultado['produtos']} produtos "
            f"sincronizados. O painel do cliente já está pronto."
        )
else:
    st.caption("Nenhum cliente autorizado ainda.")

st.divider()
st.markdown("**Situação geral**")
st.dataframe(
    [{"Cliente": c["nome"],
      "App cadastrado": "✅" if c["tem_app"] else "—",
      "Bling autorizado": "✅" if c["autorizado"] else "—",
      "Pedidos no banco": c["pedidos"]} for c in situacao],
    hide_index=True, width="stretch",
)
