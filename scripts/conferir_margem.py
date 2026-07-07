"""Confere a margem de um pedido "na mão" contra o cálculo do sistema.

    python -m scripts.conferir_margem --cliente 1            # último pedido
    python -m scripts.conferir_margem --cliente 1 --pedido 42

Refaz a conta a partir das linhas cruas do banco (itens, taxas, custos) e
compara com o valor que o dashboard exibe (core.metricas/core.margem).
É o item do checklist da demo: margem conferida em pelo menos 1 pedido.
"""
import argparse
from datetime import date

from sqlalchemy import select

from core import metricas
from core.comissoes import comissao_para_canal
from db.database import Sessao
from db.models import Canal, ItemPedido, Pedido, Produto, TaxaPedido


def main() -> None:
    parser = argparse.ArgumentParser(description="Confere a margem de 1 pedido")
    parser.add_argument("--cliente", type=int, required=True)
    parser.add_argument("--pedido", type=int, help="id interno do pedido (padrão: o mais recente)")
    args = parser.parse_args()

    sessao = Sessao()
    consulta = select(Pedido).where(Pedido.cliente_id == args.cliente)
    if args.pedido:
        consulta = consulta.where(Pedido.id == args.pedido)
    else:
        consulta = consulta.where(~Pedido.situacao.ilike("cancel%")).order_by(
            Pedido.data.desc(), Pedido.id.desc()
        )
    pedido = sessao.execute(consulta.limit(1)).scalar_one_or_none()
    if pedido is None:
        raise SystemExit("Pedido não encontrado.")

    canal = sessao.get(Canal, pedido.canal_id) if pedido.canal_id else None
    canal_nome = canal.nome if canal else "Sem canal"

    print(f"Pedido #{pedido.numero} (id {pedido.id}) — {pedido.data} — {canal_nome}")
    print(f"  Receita (valor_total): {float(pedido.valor_total):>10.2f}")

    custo = 0.0
    qtd_itens = 0.0
    print("  Itens:")
    for item in sessao.execute(
        select(ItemPedido).where(ItemPedido.pedido_id == pedido.id)
    ).scalars():
        produto = sessao.get(Produto, item.produto_id) if item.produto_id else None
        custo_unit = float(produto.preco_custo or 0) if produto else 0.0
        custo_item = float(item.quantidade) * custo_unit
        custo += custo_item
        qtd_itens += float(item.quantidade)
        print(f"    {item.descricao[:44]:<46} {float(item.quantidade):>4.0f} x "
              f"venda {float(item.valor_unitario):>8.2f} | custo {custo_unit:>8.2f}")

    taxas = {"comissao": 0.0, "frete": 0.0, "imposto": 0.0, "outros": 0.0}
    print("  Taxas registradas:")
    for taxa in sessao.execute(
        select(TaxaPedido).where(TaxaPedido.pedido_id == pedido.id)
    ).scalars():
        tipo = taxa.tipo if taxa.tipo in taxas else "outros"
        taxas[tipo] += float(taxa.valor)
        print(f"    {taxa.tipo:<10} {float(taxa.valor):>10.2f}  ({taxa.origem}: {taxa.descricao})")

    comissao = taxas["comissao"]
    origem = "fonte"
    if comissao == 0:
        regra = comissao_para_canal(canal_nome)
        if regra:
            comissao = round(
                float(pedido.valor_total) * regra["percentual"]
                + qtd_itens * regra["fixo_por_item"], 2,
            )
            origem = "tabela_comissoes"
            print(f"    comissão estimada pela tabela ({canal_nome}): {comissao:.2f}")

    receita = float(pedido.valor_total)
    margem_manual = round(
        receita - comissao - taxas["frete"] - taxas["imposto"] - taxas["outros"] - custo, 2
    )

    print("\n  Conta manual:")
    print(f"    {receita:.2f} (receita) - {comissao:.2f} (comissão/{origem}) "
          f"- {taxas['frete']:.2f} (frete) - {taxas['imposto']:.2f} (imposto) "
          f"- {taxas['outros']:.2f} (outras) - {custo:.2f} (custo)")
    print(f"    = margem {margem_manual:.2f} "
          f"({margem_manual / receita * 100 if receita else 0:.1f}% da receita)")

    df = metricas.analitico_pedidos(args.cliente, pedido.data, pedido.data)
    linha = df[df["pedido_id"] == pedido.id]
    if linha.empty:
        raise SystemExit("  Sistema: pedido fora da análise (verifique situação/cancelamento).")
    margem_sistema = round(float(linha.iloc[0]["margem"]), 2)
    print(f"\n  Margem pelo sistema (core.metricas): {margem_sistema:.2f}")

    if abs(margem_sistema - margem_manual) <= 0.01:
        print("  [OK] CONFERE — conta manual e sistema batem.")
    else:
        raise SystemExit(
            f"  [ERRO] DIVERGE em {abs(margem_sistema - margem_manual):.2f} — investigar!"
        )


if __name__ == "__main__":
    main()
