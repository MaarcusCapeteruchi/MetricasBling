"""Tabela de comissões — o plano B do cálculo de margem.

Usada quando o pedido NÃO traz a comissão real na tabela taxas_pedido
(origem 'fonte'). Para o Bling do piloto isso é sempre: a conta não recebe
as taxas dos marketplaces (campo `taxas` vem zerado).

As comissões ficam na tabela `regras_comissao`, POR CLIENTE, editáveis pela
tela de Configurações do dashboard. Enquanto um cliente não tem regras
próprias, o cálculo usa os PADRÕES abaixo (TABELA_COMISSOES).

Estrutura de cada canal: lista de faixas por VALOR UNITÁRIO DO ITEM, no
formato (limite_superior, percentual, fixo_por_unidade); limite None = sem
teto. A comissão do pedido é a soma das comissões de cada item.

Fontes dos padrões (pesquisa multi-fonte com verificação, 09/jul/2026):

- Shopee — OFICIAL, vigente desde 01/03/2026 (vendedores CNPJ):
  seller.shopee.com.br/edu/article/26839. Comissão variável por valor do
  item; o percentual já inclui a taxa de transação; Programa de Frete
  Grátis é automático e o subsídio é bancado pela Shopee (sem % extra).
  >> Conferir se o piloto vende como CNPJ (a tabela CPF difere). <<

- Mercado Livre — OFICIAL: anúncio Clássico custa entre 10% e 14% conforme
  a categoria. Usamos 14% (teto, conservador) até confirmar o % de calçados
  no painel logado do vendedor.

- TikTok Shop — os Termos confirmam comissão + taxa de transação em % por
  pedido, mas os percentuais NÃO são públicos. 12% é PLACEHOLDER.
"""
from sqlalchemy import select

from core import preferencias
from db.database import Sessao
from db.models import RegraComissao

# Tabela oficial Shopee (vigente 01/03/2026), por faixa de valor do item.
# CNPJ e CPF compartilham as faixas base; o vendedor CPF de ALTO VOLUME
# (acima de 450 pedidos em 90 dias) paga +R$3 por item — refletido no preset
# CPF. Fonte: seller.shopee.com.br/edu/article/26839 e /18484.
SHOPEE_CNPJ = [
    (79.99, 0.20, 4.00),
    (99.99, 0.14, 16.00),
    (199.99, 0.14, 20.00),
    (None, 0.14, 26.00),
]
SHOPEE_CPF = [
    (79.99, 0.20, 7.00),
    (99.99, 0.14, 19.00),
    (199.99, 0.14, 23.00),
    (None, 0.14, 29.00),
]

# Padrões de fábrica (usados quando o cliente ainda não editou suas regras).
TABELA_COMISSOES = {
    "shopee": SHOPEE_CNPJ,
    "mercado livre": [(None, 0.14, 0.00)],
    "tiktok": [(None, 0.12, 0.00)],
    "magalu": [(None, 0.128, 0.00)],
}

# Imposto estimado sobre a receita quando o dado não existir (ex.: Simples).
# 0.0 = não estimar imposto (padrão conservador).
IMPOSTO_PADRAO_PCT = 0.0


def regras_padrao() -> dict[str, list[tuple]]:
    """Cópia dos padrões de fábrica, no formato {canal: [(limite, pct, fixo)]}."""
    return {canal: list(faixas) for canal, faixas in TABELA_COMISSOES.items()}


def carregar_regras(cliente_id: int) -> dict[str, list[tuple]]:
    """Regras de comissão do cliente (do banco); cai nos padrões se não houver."""
    with Sessao() as sessao:
        linhas = sessao.execute(
            select(RegraComissao)
            .where(RegraComissao.cliente_id == cliente_id)
            .order_by(RegraComissao.canal, RegraComissao.ordem)
        ).scalars().all()

    if not linhas:
        return regras_padrao()

    regras: dict[str, list[tuple]] = {}
    for linha in linhas:
        limite = float(linha.valor_ate) if linha.valor_ate is not None else None
        regras.setdefault(linha.canal.lower(), []).append(
            (limite, float(linha.percentual), float(linha.fixo_por_item))
        )
    return regras


def _faixas_do_canal(regras: dict[str, list[tuple]], nome_canal: str) -> list[tuple] | None:
    nome = nome_canal.lower()
    for chave, faixas in regras.items():
        if chave in nome:
            return faixas
    return None


def comissao_por_item(regras: dict[str, list[tuple]], nome_canal: str | None,
                      valor_unitario: float, quantidade: float = 1) -> float | None:
    """Comissão estimada de um item, pela faixa do valor unitário.

    `regras` vem de carregar_regras(cliente_id). Retorna None quando o canal
    não tem regra (ex.: site próprio) — nesse caso não há comissão a estimar.
    """
    if not nome_canal:
        return None
    faixas = _faixas_do_canal(regras, nome_canal)
    if not faixas:
        return None
    # Faixas sem teto (limite None) são avaliadas por último.
    ordenadas = sorted(faixas, key=lambda f: (f[0] is None, f[0] if f[0] is not None else 0))
    for limite, percentual, fixo in ordenadas:
        if limite is None or valor_unitario <= limite:
            return quantidade * (valor_unitario * percentual + fixo)
    return None


# ── Persistência para a tela de Configurações ────────────────────────────────

def regras_para_edicao(cliente_id: int) -> list[dict]:
    """Regras do cliente como linhas amigáveis para o editor (percentual em %)."""
    regras = carregar_regras(cliente_id)
    linhas = []
    for canal, faixas in regras.items():
        for limite, percentual, fixo in faixas:
            linhas.append({
                "Canal": canal,
                "Vale até R$ (vazio = sem limite)": limite,
                "Comissão (%)": round(percentual * 100, 2),
                "Taxa fixa por item (R$)": fixo,
            })
    return linhas


def salvar_regras(cliente_id: int, linhas: list[dict]) -> int:
    """Substitui as regras do cliente pelas linhas do editor. Retorna a contagem."""
    registros = []
    contadores: dict[str, int] = {}
    for linha in linhas:
        canal = str(linha.get("Canal") or "").strip().lower()
        if not canal:
            continue
        percentual = linha.get("Comissão (%)")
        percentual = float(percentual) / 100 if percentual not in (None, "") else 0.0
        fixo = linha.get("Taxa fixa por item (R$)")
        fixo = float(fixo) if fixo not in (None, "") else 0.0
        limite = linha.get("Vale até R$ (vazio = sem limite)")
        limite = float(limite) if limite not in (None, "") else None

        ordem = contadores.get(canal, 0)
        contadores[canal] = ordem + 1
        registros.append(RegraComissao(
            cliente_id=cliente_id, canal=canal, valor_ate=limite,
            percentual=percentual, fixo_por_item=fixo, ordem=ordem,
        ))

    with Sessao() as sessao:
        sessao.query(RegraComissao).filter(
            RegraComissao.cliente_id == cliente_id
        ).delete()
        sessao.add_all(registros)
        sessao.commit()
    return len(registros)


def restaurar_padrao(cliente_id: int) -> None:
    """Apaga as regras do cliente — volta a usar os padrões de fábrica."""
    with Sessao() as sessao:
        sessao.query(RegraComissao).filter(
            RegraComissao.cliente_id == cliente_id
        ).delete()
        sessao.commit()


# ── Perfil do vendedor na Shopee (CNPJ x CPF) ────────────────────────────────

PERFIL_SHOPEE_CHAVE = "perfil_shopee"


def perfil_shopee(cliente_id: int) -> str:
    """'cnpj' (padrão) ou 'cpf', conforme escolhido na tela de Configurações."""
    return preferencias.obter(cliente_id, PERFIL_SHOPEE_CHAVE, "cnpj")


def _linha_editor(canal: str, limite, percentual: float, fixo: float) -> dict:
    return {
        "Canal": canal,
        "Vale até R$ (vazio = sem limite)": limite,
        "Comissão (%)": round(percentual * 100, 2),
        "Taxa fixa por item (R$)": fixo,
    }


def aplicar_perfil_shopee(cliente_id: int, perfil: str) -> None:
    """Grava o perfil e reescreve APENAS as faixas da Shopee com o preset
    oficial correspondente (CNPJ ou CPF), preservando os demais canais."""
    perfil = "cpf" if str(perfil).lower() == "cpf" else "cnpj"
    preferencias.definir(cliente_id, PERFIL_SHOPEE_CHAVE, perfil)

    preset = SHOPEE_CPF if perfil == "cpf" else SHOPEE_CNPJ
    regras = carregar_regras(cliente_id)

    linhas = []
    for canal, faixas in regras.items():
        if "shopee" in canal:
            continue  # substituída pelo preset abaixo
        for limite, pct, fixo in faixas:
            linhas.append(_linha_editor(canal, limite, pct, fixo))
    for limite, pct, fixo in preset:
        linhas.append(_linha_editor("shopee", limite, pct, fixo))

    salvar_regras(cliente_id, linhas)
