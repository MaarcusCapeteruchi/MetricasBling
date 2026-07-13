"""Simulador de precificação por canal.

Dois modos, ambos sobre as mesmas regras já configuradas (comissões por
faixa + imposto do cliente):

- Simulador de margem: dado um preço, quanto sobra em cada canal; e o
  inverso, o preço mínimo para uma margem-alvo (respeitando as faixas).
- Corredor de lucro: cruza o PISO (preço mínimo para a margem-alvo) com o
  TETO (preço de mercado/concorrente) e diz, por canal, se dá para competir.

O piso vem dos nossos dados (custo + taxa + imposto). O teto vem de fora:
por padrão usamos o preço médio REAL já praticado no canal (dos pedidos),
que o usuário pode sobrescrever com o preço do concorrente.
"""
from core import comissoes, metricas, preferencias


def _parametros(cliente_id: int):
    regras = comissoes.carregar_regras(cliente_id)
    imposto_pct = preferencias.obter_float(cliente_id, "imposto_pct")
    canais = metricas.listar_canais(cliente_id)
    return regras, imposto_pct, canais


def simular_preco(cliente_id: int, preco: float, custo: float) -> list[dict]:
    """Para cada canal: comissão, imposto, custo, sobra e margem % a esse preço."""
    regras, imposto_pct, canais = _parametros(cliente_id)
    t = imposto_pct / 100
    linhas = []
    for canal in canais:
        comissao = comissoes.comissao_por_item(regras, canal, preco, 1) or 0.0
        imposto = preco * t
        sobra = preco - comissao - imposto - custo
        margem = (sobra / preco * 100) if preco else 0.0
        linhas.append({
            "canal": canal, "preco": round(preco, 2),
            "comissao": round(comissao, 2), "imposto": round(imposto, 2),
            "custo": round(custo, 2), "sobra": round(sobra, 2),
            "margem_pct": round(margem, 1),
        })
    return linhas


def _preco_para_margem_canal(faixas, custo: float, t: float, m: float) -> float | None:
    """Menor preço que atinge a margem m (fração), consistente com a faixa.

    P tal que P - P*pct - fixo - P*t - custo = m*P
      -> P = (custo + fixo) / (1 - pct - t - m)
    O pct/fixo dependem da faixa, que depende de P: testamos cada faixa e só
    aceitamos a solução que cai dentro do próprio intervalo (pega o efeito
    'penhasco de taxa' nas fronteiras)."""
    if not faixas:  # canal sem comissão (ex.: site próprio)
        denom = 1 - t - m
        return round(custo / denom, 2) if denom > 0 else None

    ordenadas = sorted(faixas, key=lambda f: (f[0] is None, f[0] if f[0] is not None else 0))
    prev = 0.0
    solucoes = []
    for limite, pct, fixo in ordenadas:
        denom = 1 - pct - t - m
        sup = limite if limite is not None else float("inf")
        if denom > 0:
            preco = (custo + fixo) / denom
            if prev < preco <= sup:
                solucoes.append(preco)
        prev = sup if sup != float("inf") else prev
    return round(min(solucoes), 2) if solucoes else None


def preco_para_margem(cliente_id: int, custo: float, margem_alvo_pct: float) -> list[dict]:
    """Preço mínimo por canal para atingir a margem-alvo (None se inviável)."""
    regras, imposto_pct, canais = _parametros(cliente_id)
    t = imposto_pct / 100
    m = margem_alvo_pct / 100
    linhas = []
    for canal in canais:
        faixas = comissoes._faixas_do_canal(regras, canal)
        preco = _preco_para_margem_canal(faixas, custo, t, m)
        linhas.append({"canal": canal, "preco_minimo": preco})
    return linhas


def corredor(cliente_id: int, custo: float, margem_alvo_pct: float,
             tetos: dict[str, float]) -> list[dict]:
    """Por canal: piso (p/ margem-alvo), teto (mercado), margem no teto e veredicto."""
    pisos = {linha["canal"]: linha["preco_minimo"]
             for linha in preco_para_margem(cliente_id, custo, margem_alvo_pct)}
    simulados_no_teto = {}
    for linha in _linhas_no_teto(cliente_id, custo, tetos):
        simulados_no_teto[linha["canal"]] = linha

    linhas = []
    for canal, piso in pisos.items():
        teto = tetos.get(canal)
        no_teto = simulados_no_teto.get(canal, {})
        cabe = piso is not None and teto is not None and piso <= teto
        linhas.append({
            "canal": canal,
            "piso": piso,
            "teto": round(teto, 2) if teto else None,
            "margem_no_teto": no_teto.get("margem_pct"),
            "sobra_no_teto": no_teto.get("sobra"),
            "cabe": cabe,
            "folga": round(teto - piso, 2) if cabe else None,
        })
    return linhas


def _linhas_no_teto(cliente_id: int, custo: float, tetos: dict[str, float]) -> list[dict]:
    """Simula, por canal, a margem no respectivo preço-teto."""
    regras, imposto_pct, canais = _parametros(cliente_id)
    t = imposto_pct / 100
    linhas = []
    for canal in canais:
        preco = tetos.get(canal)
        if not preco:
            linhas.append({"canal": canal, "margem_pct": None, "sobra": None})
            continue
        comissao = comissoes.comissao_por_item(regras, canal, preco, 1) or 0.0
        sobra = preco - comissao - preco * t - custo
        margem = (sobra / preco * 100) if preco else 0.0
        linhas.append({"canal": canal, "margem_pct": round(margem, 1),
                       "sobra": round(sobra, 2)})
    return linhas
