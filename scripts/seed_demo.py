"""Popula o banco com dados de demonstração realistas (fonte 'demo').

Permite rodar e apresentar o dashboard completo sem credenciais do Bling.
Determinístico (seed fixo): rodar de novo gera exatamente os mesmos dados.

    python -m scripts.seed_demo

Por segurança, só apaga e recria dados automaticamente no SQLite local.
Contra um Postgres real (DATABASE_URL preenchida), exige --forcar.
"""
import argparse
import random
from datetime import date, datetime, timedelta

from db.database import USANDO_SQLITE, Sessao, engine
from db.models import (
    Base,
    Canal,
    Cliente,
    ItemPedido,
    Pedido,
    Produto,
    Sincronizacao,
    TaxaPedido,
    criar_tabelas,
)

FONTE = "demo"

PRODUTOS_PILOTO = [
    # (sku, nome, preço venda, custo) — custos ~40-60% do preço; alguns
    # deliberadamente ruins para acionar o alerta de margem baixa
    ("KIT-AIR-01", "Kit 3 Potes Herméticos para Mantimentos", 89.90, 38.50),
    ("GAR-INX-750", "Garrafa Térmica Inox 750ml", 79.90, 31.20),
    ("ORG-GAV-04", "Organizador de Gavetas 4 Peças", 49.90, 21.40),
    ("LUM-LED-RGB", "Luminária LED RGB com Controle", 64.90, 26.80),
    ("SUP-NOTE-AL", "Suporte de Notebook em Alumínio", 99.90, 44.30),
    ("CAB-USBC-2M", "Cabo USB-C Reforçado 2m", 29.90, 9.80),
    ("FON-BT-TWS", "Fone Bluetooth TWS com Case", 119.90, 58.70),
    ("MOU-PAD-XL", "Mousepad Gamer XL Speed", 44.90, 17.60),
    ("CAD-CERV-6", "Kit 6 Caldereta de Cerveja 350ml", 74.90, 33.10),
    ("TAP-COZ-3P", "Jogo de Tapetes de Cozinha 3 Peças", 69.90, 29.50),
    ("ESC-DENT-EL", "Escova de Dentes Elétrica Recarregável", 129.90, 61.20),
    ("BAL-COZ-DIG", "Balança Digital de Cozinha 10kg", 39.90, 15.70),
    ("VEN-PORT-US", "Mini Ventilador Portátil USB", 34.90, 13.20),
    ("CAR-TURBO-20", "Carregador Turbo 20W USB-C", 49.90, 19.90),
    ("CAP-CEL-ANT", "Capa Anti-Impacto Premium", 39.90, 12.40),
    ("PEL-VID-3D", "Película de Vidro 3D (2 unidades)", 24.90, 6.90),
    ("SMART-LAMP", "Lâmpada Inteligente Wi-Fi", 54.90, 24.10),
    ("REL-DIG-LED", "Relógio Digital LED de Mesa", 59.90, 26.30),
    # Margem apertada/negativa de propósito (custo alto ou preço promocional):
    ("AIRFRY-ACC", "Kit Acessórios AirFryer 8 Peças", 59.90, 41.90),
    ("PAN-ANT-05", "Jogo de Panelas Antiaderente 5 Peças", 189.90, 132.50),
    ("ASP-PO-PORT", "Aspirador de Pó Portátil 12V", 99.90, 71.80),
    ("UMID-AR-2L", "Umidificador de Ar Ultrassônico 2L", 89.90, 63.40),
    ("SEC-CAB-VIA", "Secador de Viagem Dobrável", 69.90, 49.10),
    ("MIX-INOX-3V", "Mixer Inox 3 Velocidades", 84.90, 58.90),
]

PRODUTOS_SECUNDARIO = [
    ("VES-FLO-M", "Vestido Floral Midi", 129.90, 52.30),
    ("BLU-CRP-P", "Blusa Cropped Canelada", 49.90, 18.70),
    ("CAL-JEA-38", "Calça Jeans Skinny", 119.90, 55.60),
    ("SAI-PLI-M", "Saia Plissada Midi", 89.90, 36.40),
    ("JAQ-JEA-M", "Jaqueta Jeans Oversized", 149.90, 68.20),
    ("CON-MOL-GG", "Conjunto Moletom Feminino", 139.90, 63.10),
    ("BOD-BAS-P", "Body Básico Manga Longa", 44.90, 16.80),
    ("KIM-EST-U", "Kimono Estampado", 79.90, 41.50),
]


def _criar_cliente(sessao, nome: str, canais_spec: list[tuple[str, str]],
                   produtos_spec: list[tuple], dias: int, pedidos_dia: tuple[int, int],
                   hoje: date) -> None:
    cliente = Cliente(nome=nome)
    sessao.add(cliente)
    sessao.flush()

    canais = []
    for id_ext, nome_canal in canais_spec:
        canal = Canal(cliente_id=cliente.id, fonte=FONTE, id_externo=id_ext, nome=nome_canal)
        sessao.add(canal)
        canais.append(canal)
    sessao.flush()

    produtos = []
    for sku, nome_prod, preco, custo in produtos_spec:
        produto = Produto(
            cliente_id=cliente.id, fonte=FONTE, id_externo=sku, sku=sku,
            nome=nome_prod, preco_venda=preco, preco_custo=custo,
        )
        sessao.add(produto)
        produtos.append(produto)
    sessao.flush()

    seq = 0
    n_pedidos = 0
    for dias_atras in range(dias - 1, -1, -1):
        dia = hoje - timedelta(days=dias_atras)
        volume = random.randint(*pedidos_dia)
        if dia.weekday() >= 5:  # fim de semana vende um pouco menos
            volume = max(1, int(volume * 0.7))

        for _ in range(volume):
            seq += 1
            canal = random.choices(canais, weights=[5, 4, 2][: len(canais)])[0]
            eh_marketplace = "shopee" in canal.nome.lower() or "mercado" in canal.nome.lower()

            sorteados = random.sample(produtos, k=random.choices([1, 2, 3], [6, 3, 1])[0])
            situacao = random.choices(
                ["Atendido", "Em aberto", "Cancelado"], weights=[90, 6, 4]
            )[0]

            pedido = Pedido(
                cliente_id=cliente.id, canal_id=canal.id, fonte=FONTE,
                id_externo=f"{cliente.id}-{seq}", numero=str(10000 + seq),
                data=dia, situacao=situacao,
            )
            sessao.add(pedido)

            total = 0.0
            unidades = 0
            for produto in sorteados:
                qtd = random.choices([1, 2], weights=[8, 2])[0]
                preco_unit = round(float(produto.preco_venda) * random.uniform(0.92, 1.0), 2)
                total_item = round(qtd * preco_unit, 2)
                total += total_item
                unidades += qtd
                pedido.itens.append(ItemPedido(
                    cliente_id=cliente.id, produto_id=produto.id, descricao=produto.nome,
                    quantidade=qtd, valor_unitario=preco_unit, valor_total=total_item,
                ))
            pedido.valor_total = round(total, 2)

            taxas = []
            if eh_marketplace:
                # ~15% dos pedidos sem comissão no dado → exercita o plano B
                # (tabela de comissões) e o indicador de origem no dashboard
                if random.random() > 0.15:
                    if "shopee" in canal.nome.lower():
                        comissao = 0.14 * total + 4.00 * unidades
                    else:
                        comissao = 0.12 * total + (6.00 * unidades if total < 79 else 0.0)
                    taxas.append(TaxaPedido(
                        cliente_id=cliente.id, tipo="comissao",
                        valor=round(comissao, 2), origem="fonte",
                        descricao="taxaComissao (Bling)",
                    ))
                if random.random() < 0.6:  # frete subsidiado pelo vendedor
                    taxas.append(TaxaPedido(
                        cliente_id=cliente.id, tipo="frete",
                        valor=round(random.uniform(6.0, 18.0), 2), origem="fonte",
                        descricao="custoFrete (Bling)",
                    ))
            else:
                taxas.append(TaxaPedido(
                    cliente_id=cliente.id, tipo="outros",
                    valor=round(0.025 * total, 2), origem="fonte",
                    descricao="taxa do gateway de pagamento",
                ))

            taxas.append(TaxaPedido(
                cliente_id=cliente.id, tipo="imposto",
                valor=round(0.06 * total, 2), origem="fonte",
                descricao="Simples Nacional 6%",
            ))
            pedido.taxas = taxas
            n_pedidos += 1

    sessao.add(Sincronizacao(
        cliente_id=cliente.id, fonte=FONTE,
        iniciada_em=datetime.utcnow() - timedelta(minutes=2),
        finalizada_em=datetime.utcnow(), status="sucesso",
        pedidos_processados=n_pedidos, produtos_processados=len(produtos),
    ))
    print(f"  [{cliente.id}] {cliente.nome}: {len(produtos)} produtos, {n_pedidos} pedidos")


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera dados de demonstração")
    parser.add_argument("--forcar", action="store_true",
                        help="permite recriar dados mesmo em Postgres (apaga tudo!)")
    args = parser.parse_args()

    if not USANDO_SQLITE and not args.forcar:
        raise SystemExit(
            "DATABASE_URL aponta para um Postgres real. O seed apaga TODOS os "
            "dados — se é isso mesmo, rode com --forcar."
        )

    print(f"Banco alvo: {engine.url}")
    Base.metadata.drop_all(engine)
    criar_tabelas()

    random.seed(42)
    hoje = date.today()
    sessao = Sessao()

    print("Gerando dados de demonstração...")
    _criar_cliente(
        sessao, "Loja Piloto Demo Ltda",
        [("1", "Shopee"), ("2", "Mercado Livre"), ("3", "Site Próprio")],
        PRODUTOS_PILOTO, dias=90, pedidos_dia=(4, 12), hoje=hoje,
    )
    _criar_cliente(
        sessao, "Moda Bella ME",
        [("10", "Shopee"), ("11", "Site Próprio")],
        PRODUTOS_SECUNDARIO, dias=30, pedidos_dia=(1, 4), hoje=hoje,
    )
    sessao.commit()
    print("Seed concluído.")


if __name__ == "__main__":
    main()
