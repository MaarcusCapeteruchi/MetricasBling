"""Tabela de comissões da empresa — o plano B do cálculo de margem.

Usada apenas quando o pedido NÃO traz a comissão real na tabela
taxas_pedido (origem 'fonte'). Rode o conector com --inspecionar para
descobrir se o Bling entrega a comissão; se entregar, esta tabela quase
não é usada.

>>> ATENÇÃO: valores abaixo são um PONTO DE PARTIDA aproximado. <<<
Substitua pela tabela oficial de comissões da empresa (por canal e, se
preciso, por categoria/plano) antes de apresentar números ao cliente.
"""

# Casamento por nome do canal (comparação em minúsculas, por "contém")
TABELA_COMISSOES = {
    "shopee": {"percentual": 0.14, "fixo_por_item": 4.00},
    "mercado livre": {"percentual": 0.12, "fixo_por_item": 0.00},
    "tiktok": {"percentual": 0.12, "fixo_por_item": 0.00},
    "magalu": {"percentual": 0.128, "fixo_por_item": 0.00},
}

# Imposto estimado sobre a receita quando o dado não existir (ex.: Simples).
# 0.0 = não estimar imposto (padrão conservador).
IMPOSTO_PADRAO_PCT = 0.0


def comissao_para_canal(nome_canal: str | None) -> dict | None:
    """Regra de comissão para o canal, ou None se o canal não é marketplace."""
    if not nome_canal:
        return None
    nome = nome_canal.lower()
    for chave, regra in TABELA_COMISSOES.items():
        if chave in nome:
            return regra
    return None
