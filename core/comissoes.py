"""Tabela de comissões — o plano B do cálculo de margem.

Usada quando o pedido NÃO traz a comissão real na tabela taxas_pedido
(origem 'fonte'). Para o Bling do piloto isso é sempre: a conta não recebe
as taxas dos marketplaces (campo `taxas` vem zerado).

Estrutura por canal: lista de faixas por VALOR UNITÁRIO DO ITEM, no formato
(limite_superior, percentual, fixo_por_unidade); limite None = sem teto.
A comissão do pedido é a soma das comissões de cada item.

Fontes (pesquisa multi-fonte com verificação, 09/jul/2026):

- Shopee — OFICIAL, vigente desde 01/03/2026 (vendedores CNPJ):
  seller.shopee.com.br/edu/article/26839. Comissão variável por valor do
  item; o percentual já inclui a taxa de transação; Programa de Frete
  Grátis é automático e o subsídio é bancado pela Shopee (sem % extra).
  >> Conferir se o piloto vende como CNPJ (a tabela CPF difere). <<

- Mercado Livre — OFICIAL: anúncio Clássico custa entre 10% e 14% conforme
  a categoria (mercadolivre.com.br/ajuda/quanto-custa-vender-um-produto_1338).
  O % exato de calçados fica na página logada do vendedor — usamos 14%
  (teto, conservador) até confirmar. Custo fixo por unidade só para itens
  baratos (abaixo de ~R$79) — não atinge o piloto (itens R$85-130).

- TikTok Shop — os Termos confirmam comissão + taxa de transação em % por
  pedido, mas os percentuais NÃO são públicos (só na Central do Vendedor
  logada). 12% é PLACEHOLDER — confirmar na conta do cliente.
"""

TABELA_COMISSOES = {
    "shopee": {
        "faixas": [
            (79.99, 0.20, 4.00),
            (99.99, 0.14, 16.00),
            (199.99, 0.14, 20.00),
            (None, 0.14, 26.00),
        ],
        "vigencia": "2026-03-01",
        "status": "oficial",
    },
    "mercado livre": {
        "faixas": [(None, 0.14, 0.00)],
        "status": "estimado — confirmar % de calçados no painel do vendedor",
    },
    "tiktok": {
        "faixas": [(None, 0.12, 0.00)],
        "status": "PLACEHOLDER — % não é público; confirmar na Central do Vendedor",
    },
    "magalu": {
        "faixas": [(None, 0.128, 0.00)],
        "status": "estimado",
    },
}

# Imposto estimado sobre a receita quando o dado não existir (ex.: Simples).
# 0.0 = não estimar imposto (padrão conservador).
IMPOSTO_PADRAO_PCT = 0.0


def regras_para_canal(nome_canal: str | None) -> dict | None:
    """Regra de comissão para o canal, ou None se não é marketplace mapeado."""
    if not nome_canal:
        return None
    nome = nome_canal.lower()
    for chave, regra in TABELA_COMISSOES.items():
        if chave in nome:
            return regra
    return None


def comissao_por_item(nome_canal: str | None, valor_unitario: float,
                      quantidade: float = 1) -> float | None:
    """Comissão estimada para um item do pedido, pela faixa do valor unitário.

    Retorna None quando o canal não tem regra (ex.: site próprio).
    """
    regra = regras_para_canal(nome_canal)
    if not regra:
        return None
    for limite, percentual, fixo in regra["faixas"]:
        if limite is None or valor_unitario <= limite:
            return quantidade * (valor_unitario * percentual + fixo)
    return None
