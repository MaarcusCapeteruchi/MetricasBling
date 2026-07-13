"""Sincroniza produtos e pedidos de venda do Bling para o modelo canônico.

Uso:
    python -m conector.sincronizar --cliente 1 --inspecionar   # 1º uso: ver pedido cru
    python -m conector.sincronizar --cliente 1 --limite 20     # teste com poucos pedidos
    python -m conector.sincronizar --cliente 1 --desde 2026-01-01

O modo --inspecionar imprime o JSON cru do primeiro pedido e sai — é o
check que define a demo: conferir se a comissão do marketplace vem no dado
(campo `taxas`). Se vier, a margem é leitura pura; se não vier, o cálculo
usa a tabela de comissões em core/comissoes.py.
"""
import argparse
import json
from datetime import date, datetime, timedelta

from conector.bling_api import BlingAPI
from db.database import Sessao
from db.models import (
    Canal,
    ItemPedido,
    Pedido,
    Produto,
    Sincronizacao,
    TaxaPedido,
    criar_tabelas,
)
from db.upsert import upsert_por_id_externo

FONTE = "bling"

# A API v3 devolve a situação como código; nomes das situações padrão do Bling.
SITUACOES_BLING = {
    6: "Em aberto", 9: "Atendido", 12: "Cancelado", 15: "Em andamento",
    18: "Venda agenciada", 21: "Em digitação", 24: "Verificado",
}

# Identificação automática do marketplace pelo CNPJ do intermediador do
# pedido — identidade jurídica da plataforma, não muda. Shopee/ML/TikTok
# conferidos neste projeto com pedidos reais.
CNPJ_PLATAFORMAS = {
    "35.635.824/0001-12": "Shopee",
    "03.007.331/0001-41": "Mercado Livre",
    "27.415.911/0001-36": "TikTok Shop",
    "47.960.950/0001-21": "Magalu",
    "15.436.940/0001-03": "Amazon",
}
# Plano B quando o pedido não traz intermediador: padrão da transportadora.
SERVICO_PLATAFORMAS = [
    ("shopee", "Shopee"),
    ("lsv-", "TikTok Shop"),
    ("mercado envios", "Mercado Livre"),
]
PREFIXO_CANAL_PENDENTE = "Loja Bling "


def _inferir_nome_canal(detalhe: dict) -> str | None:
    cnpj = ((detalhe.get("intermediador") or {}).get("cnpj") or "").strip()
    if cnpj in CNPJ_PLATAFORMAS:
        return CNPJ_PLATAFORMAS[cnpj]
    volumes = (detalhe.get("transporte") or {}).get("volumes") or []
    servico = (volumes[0].get("servico") or "").lower() if volumes else ""
    for padrao, nome in SERVICO_PLATAFORMAS:
        if padrao in servico:
            return nome
    return None


def _num(valor, padrao=0.0) -> float:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return padrao


def _extrair_custo(produto_json: dict) -> float | None:
    """O campo de custo varia conforme o cadastro; tenta os caminhos conhecidos."""
    candidatos = [
        produto_json.get("precoCusto"),
        (produto_json.get("precos") or {}).get("precoCusto"),
        (produto_json.get("fornecedor") or {}).get("precoCusto"),
        (produto_json.get("fornecedor") or {}).get("precoCompra"),
    ]
    for candidato in candidatos:
        if candidato is not None:
            return _num(candidato)
    return None


def sincronizar_produtos(api: BlingAPI, sessao, cliente_id: int) -> int:
    total = 0
    for item in api.listar_paginado("/produtos"):
        valores = {
            "sku": item.get("codigo"),
            "nome": item.get("nome") or f"Produto {item['id']}",
            "preco_venda": _num(item.get("preco"), None),
        }
        # Custo/peso zerados na fonte não sobrescrevem valores já enriquecidos
        # (planilha/backfill) — o canônico pode ser mais rico que a origem.
        custo = _extrair_custo(item)
        if custo:
            valores["preco_custo"] = custo
        peso = _num(item.get("pesoBruto"), 0) or _num(item.get("pesoLiquido"), 0)
        if peso:
            valores["peso"] = peso
        upsert_por_id_externo(
            sessao, Produto, cliente_id, FONTE, item["id"], valores
        )
        total += 1
        if total % 100 == 0:
            sessao.commit()
            print(f"  produtos: {total}...")
    sessao.commit()
    return total


def preencher_pesos_faltantes(api: BlingAPI, sessao, cliente_id: int,
                              maximo: int = 600) -> int:
    """Busca o peso no DETALHE do produto para quem ainda não tem.

    A listagem nem sempre traz peso; o detalhe traz (pesoBruto/pesoLiquido).
    Roda ao fim da sincronização de produtos — depois da primeira passada,
    o custo diário disso é praticamente zero."""
    pendentes = (
        sessao.query(Produto)
        .filter(Produto.cliente_id == cliente_id, Produto.peso.is_(None))
        .limit(maximo)
        .all()
    )
    preenchidos = 0
    for produto in pendentes:
        detalhe = api.get(f"/produtos/{produto.id_externo}").get("data") or {}
        peso = _num(detalhe.get("pesoBruto"), 0) or _num(detalhe.get("pesoLiquido"), 0)
        produto.peso = peso if peso else 0  # 0 = consultado e sem peso (não repete)
        preenchidos += 1 if peso else 0
        if preenchidos % 50 == 0:
            sessao.commit()
    sessao.commit()
    return preenchidos


def _obter_canal(sessao, cliente_id: int, detalhe: dict) -> Canal | None:
    loja = detalhe.get("loja") or {}
    id_loja = loja.get("id")
    if not id_loja:
        return None
    canal = upsert_por_id_externo(
        sessao, Canal, cliente_id, FONTE, id_loja, {}
    )
    inferido = _inferir_nome_canal(detalhe)
    if not canal.nome:
        canal.nome = inferido or f"{PREFIXO_CANAL_PENDENTE}{id_loja}"
    elif inferido and canal.nome.startswith(PREFIXO_CANAL_PENDENTE):
        # upgrade do placeholder; nome dado pelo usuário nunca é sobrescrito
        canal.nome = inferido
    return canal


def nomear_canais_automaticamente(sessao, cliente_id: int) -> list[str]:
    """Resolve canais ainda com nome-placeholder olhando o CNPJ do
    intermediador nos pedidos já gravados. Roda ao fim de cada sincronização."""
    renomeados = []
    pendentes = (
        sessao.query(Canal)
        .filter(Canal.cliente_id == cliente_id,
                Canal.nome.like(f"{PREFIXO_CANAL_PENDENTE}%"))
        .all()
    )
    for canal in pendentes:
        amostra = (
            sessao.query(Pedido)
            .filter(Pedido.cliente_id == cliente_id, Pedido.canal_id == canal.id,
                    Pedido.dados_cru.isnot(None))
            .limit(10)
            .all()
        )
        for pedido in amostra:
            inferido = _inferir_nome_canal(pedido.dados_cru or {})
            if inferido:
                canal.nome = inferido
                renomeados.append(f"{canal.id_externo} -> {inferido}")
                break
    if renomeados:
        sessao.commit()
    return renomeados


def _mapear_pedido(sessao, cliente_id: int, detalhe: dict) -> None:
    situacao = detalhe.get("situacao") or {}
    canal = _obter_canal(sessao, cliente_id, detalhe)
    sessao.flush()

    pedido = upsert_por_id_externo(
        sessao, Pedido, cliente_id, FONTE, detalhe["id"],
        {
            "numero": str(detalhe.get("numero") or detalhe.get("numeroLoja") or detalhe["id"]),
            "data": date.fromisoformat(detalhe["data"][:10]),
            "situacao": SITUACOES_BLING.get(
                situacao.get("id"), str(situacao.get("valor") or situacao.get("id") or "")
            ),
            "valor_total": _num(detalhe.get("total")),
            "canal_id": canal.id if canal else None,
            "dados_cru": detalhe,
        },
    )

    itens = []
    for item in detalhe.get("itens") or []:
        id_produto_externo = (item.get("produto") or {}).get("id")
        produto = None
        if id_produto_externo:
            produto = (
                sessao.query(Produto)
                .filter_by(cliente_id=cliente_id, fonte=FONTE, id_externo=str(id_produto_externo))
                .one_or_none()
            )
        quantidade = _num(item.get("quantidade"), 1)
        valor_unitario = _num(item.get("valor"))
        itens.append(
            ItemPedido(
                cliente_id=cliente_id,
                produto_id=produto.id if produto else None,
                descricao=item.get("descricao") or (produto.nome if produto else "Item"),
                quantidade=quantidade,
                valor_unitario=valor_unitario,
                valor_total=round(quantidade * valor_unitario, 2),
            )
        )
    pedido.itens = itens

    # Check crítico da demo: se o Bling trouxer `taxas`, a comissão é dado real
    taxas_fonte = detalhe.get("taxas") or {}
    taxas = []
    comissao = _num(taxas_fonte.get("taxaComissao"))
    if comissao > 0:
        taxas.append(TaxaPedido(cliente_id=cliente_id, tipo="comissao",
                                valor=comissao, origem="fonte",
                                descricao="taxaComissao (Bling)"))
    custo_frete = _num(taxas_fonte.get("custoFrete"))
    if custo_frete > 0:
        taxas.append(TaxaPedido(cliente_id=cliente_id, tipo="frete",
                                valor=custo_frete, origem="fonte",
                                descricao="custoFrete (Bling)"))
    pedido.taxas = taxas


def sincronizar_pedidos(api: BlingAPI, sessao, cliente_id: int, desde: date,
                        ate: date, limite: int | None, inspecionar: bool,
                        ao_progredir=None) -> int:
    params = {"dataInicial": desde.isoformat(), "dataFinal": ate.isoformat()}
    total = 0
    for resumo in api.listar_paginado("/pedidos/vendas", params):
        detalhe = api.get(f"/pedidos/vendas/{resumo['id']}").get("data") or resumo

        if inspecionar:
            print("\n=== PEDIDO CRU (JSON) — inspecione os campos de taxa/comissão ===\n")
            print(json.dumps(detalhe, indent=2, ensure_ascii=False))
            print("\n=== O que procurar ===")
            print("- `taxas.taxaComissao` / `taxas.custoFrete`: comissão real do marketplace.")
            print("  -> Se existirem, a margem real é leitura pura (melhor cenário).")
            print("  -> Se não existirem, ajuste a tabela em core/comissoes.py (plano B).")
            return 0

        _mapear_pedido(sessao, cliente_id, detalhe)
        sessao.commit()
        total += 1
        if ao_progredir:
            ao_progredir(total)
        elif total % 25 == 0:
            print(f"  pedidos: {total}...")
        if limite and total >= limite:
            break
    return total


def executar(cliente_id: int, desde: date, ate: date, limite: int | None = None,
             sem_produtos: bool = False, ao_progredir=None) -> dict:
    """Sincronização completa reutilizável (CLI e interface web).

    ao_progredir(n) é chamado a cada pedido gravado — a tela usa para a barra
    de progresso. Retorna {"produtos": n, "pedidos": n}.
    """
    criar_tabelas()
    sessao = Sessao()
    registro = Sincronizacao(cliente_id=cliente_id, fonte=FONTE)
    sessao.add(registro)
    sessao.commit()

    try:
        api = BlingAPI(sessao, cliente_id)
        if not sem_produtos:
            registro.produtos_processados = sincronizar_produtos(api, sessao, cliente_id)
            preencher_pesos_faltantes(api, sessao, cliente_id)
        registro.pedidos_processados = sincronizar_pedidos(
            api, sessao, cliente_id, desde, ate, limite, False, ao_progredir
        )
        nomear_canais_automaticamente(sessao, cliente_id)
        registro.status = "sucesso"
    except Exception as erro:
        registro.status = "erro"
        registro.mensagem = str(erro)[:2000]
        raise
    finally:
        registro.finalizada_em = datetime.utcnow()
        sessao.commit()

    return {"produtos": registro.produtos_processados,
            "pedidos": registro.pedidos_processados}


def main() -> None:
    parser = argparse.ArgumentParser(description="Sincroniza Bling → modelo canônico")
    parser.add_argument("--cliente", type=int, required=True)
    parser.add_argument("--desde", type=lambda s: date.fromisoformat(s),
                        default=date.today() - timedelta(days=90))
    parser.add_argument("--ate", type=lambda s: date.fromisoformat(s), default=date.today())
    parser.add_argument("--limite", type=int, help="máx. de pedidos (para testes)")
    parser.add_argument("--sem-produtos", action="store_true")
    parser.add_argument("--inspecionar", action="store_true",
                        help="imprime o 1º pedido cru e sai, sem gravar")
    args = parser.parse_args()

    criar_tabelas()
    sessao = Sessao()

    if args.inspecionar:
        api = BlingAPI(sessao, args.cliente)
        sincronizar_pedidos(api, sessao, args.cliente, args.desde, args.ate, None, True)
        return

    print(f"Sincronizando produtos e pedidos de {args.desde} a {args.ate}...")
    resultado = executar(
        args.cliente, args.desde, args.ate, args.limite, args.sem_produtos
    )
    print(
        f"\nConcluído: {resultado['produtos']} produtos, "
        f"{resultado['pedidos']} pedidos gravados no modelo canônico."
    )


if __name__ == "__main__":
    main()
