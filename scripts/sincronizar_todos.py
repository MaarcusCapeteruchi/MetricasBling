"""Sincroniza TODOS os clientes autorizados — pensado para o agendador diário.

    python -m scripts.sincronizar_todos            # janela padrão: 40 dias
    python -m scripts.sincronizar_todos --dias 90

A janela de 40 dias reprocessa pedidos recentes de propósito: o Bling
preenche a comissão dias depois da venda (na liquidação) e cancelamentos
acontecem depois — o upsert substitui estimativas por valores reais.
A falha de um cliente não interrompe os demais; o código de saída indica
se houve alguma falha (para o agendador alertar).
"""
import argparse
import sys
from datetime import date, timedelta

from sqlalchemy import select

from conector.sincronizar import executar
from db.database import Sessao
from db.models import Cliente, Credencial, criar_tabelas


def main() -> None:
    parser = argparse.ArgumentParser(description="Sincroniza todos os clientes")
    parser.add_argument("--dias", type=int, default=40,
                        help="janela de dias a (re)buscar — padrão 40")
    args = parser.parse_args()

    criar_tabelas()
    # Lê a lista e FECHA a conexão: uma sincronização longa deixaria esta
    # sessão ociosa e o Neon derruba conexões ociosas (~5 min). Cada
    # executar() abre e administra as próprias conexões.
    with Sessao() as sessao:
        autorizados = sessao.execute(
            select(Credencial.cliente_id, Cliente.nome)
            .join(Cliente, Cliente.id == Credencial.cliente_id)
            .where(Credencial.refresh_token.is_not(None))
            .order_by(Credencial.cliente_id)
        ).all()

    if not autorizados:
        print("Nenhum cliente autorizado — nada a sincronizar.")
        return

    hoje = date.today()
    desde = hoje - timedelta(days=args.dias)
    falhas = []

    for cliente_id, nome in autorizados:
        print(f"\n=== [{cliente_id}] {nome} — {desde} a {hoje} ===")
        try:
            resultado = executar(cliente_id, desde, hoje)
            print(f"OK: {resultado['pedidos']} pedidos, {resultado['produtos']} produtos")
        except Exception as erro:  # um cliente com problema não derruba os demais
            falhas.append(nome)
            print(f"FALHA em {nome}: {erro}")

    print(f"\nResumo: {len(autorizados) - len(falhas)} ok, {len(falhas)} falha(s).")
    if falhas:
        sys.exit(1)


if __name__ == "__main__":
    main()
