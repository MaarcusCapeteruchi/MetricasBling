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
        # Custo zerado/ausente na fonte não sobrescreve custo importado por
        # planilha (scripts/importar_custos.py) — o canônico pode ser mais
        # rico que a origem.
        custo = _extrair_custo(item)
        if custo:
            valores["preco_custo"] = custo
        upsert_por_id_externo(
            sessao, Produto, cliente_id, FONTE, item["id"], valores
        )
        total += 1
        if total % 100 == 0:
            sessao.commit()
            print(f"  produtos: {total}...")
    sessao.commit()
    return total


def _obter_canal(sessao, cliente_id: int, detalhe: dict) -> Canal | None:
    loja = detalhe.get("loja") or {}
    id_loja = loja.get("id")
    if not id_loja:
        return None
    canal = upsert_por_id_externo(
        sessao, Canal, cliente_id, FONTE, id_loja, {}
    )
    if not canal.nome:
        canal.nome = f"Loja Bling {id_loja}"
    return canal


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
                        ate: date, limite: int | None, inspecionar: bool) -> int:
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
        if total % 25 == 0:
            print(f"  pedidos: {total}...")
        if limite and total >= limite:
            break
    return total


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

    registro = Sincronizacao(cliente_id=args.cliente, fonte=FONTE)
    sessao.add(registro)
    sessao.commit()

    try:
        api = BlingAPI(sessao, args.cliente)

        if not args.sem_produtos:
            print("Sincronizando produtos...")
            registro.produtos_processados = sincronizar_produtos(api, sessao, args.cliente)

        print(f"Sincronizando pedidos de {args.desde} a {args.ate}...")
        registro.pedidos_processados = sincronizar_pedidos(
            api, sessao, args.cliente, args.desde, args.ate, args.limite, False
        )

        registro.status = "sucesso"
    except Exception as erro:
        registro.status = "erro"
        registro.mensagem = str(erro)[:2000]
        raise
    finally:
        registro.finalizada_em = datetime.utcnow()
        sessao.commit()

    print(
        f"\nConcluído: {registro.produtos_processados} produtos, "
        f"{registro.pedidos_processados} pedidos gravados no modelo canônico."
    )


if __name__ == "__main__":
    main()
