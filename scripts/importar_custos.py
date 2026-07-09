"""Importa preços de custo de um CSV para os produtos do modelo canônico.

    python -m scripts.importar_custos --cliente 3 --arquivo custos.csv
    python -m scripts.importar_custos --cliente 3 --arquivo custos.csv --prefixo
    python -m scripts.importar_custos --cliente 3 --arquivo custos.csv --simular

CSV com cabeçalho `sku,custo` (separador vírgula ou ponto-e-vírgula; decimal
com vírgula ou ponto). Com --prefixo, cada sku do CSV casa todos os SKUs que
começam por ele — ex.: a linha "Mod016,45,90" cobre Mod016Cafe36,
Mod016Preto37 etc. Com --simular, mostra o que faria sem gravar.

O conector do Bling nunca sobrescreve estes custos: valores zerados vindos
da fonte são ignorados no upsert (ver conector/sincronizar.py).
"""
import argparse
import csv
from pathlib import Path

from sqlalchemy import func, select, update

from db.database import Sessao
from db.models import Produto


def _ler_csv(caminho: Path) -> list[tuple[str, float]]:
    try:
        texto = caminho.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        texto = caminho.read_text(encoding="latin-1")

    separador = ";" if texto.splitlines()[0].count(";") > texto.splitlines()[0].count(",") else ","
    linhas = []
    for i, registro in enumerate(csv.reader(texto.splitlines(), delimiter=separador)):
        if not registro or not registro[0].strip():
            continue
        sku = registro[0].strip()
        if i == 0 and sku.lower() in ("sku", "codigo", "código"):
            continue
        if len(registro) < 2:
            raise SystemExit(f"Linha sem custo: {registro}")
        custo_texto = registro[1].strip().replace("R$", "").replace(" ", "")
        # 1.234,56 -> 1234.56 | 45,90 -> 45.90
        if "," in custo_texto:
            custo_texto = custo_texto.replace(".", "").replace(",", ".")
        try:
            custo = float(custo_texto)
        except ValueError:
            raise SystemExit(f"Custo inválido na linha {i + 1}: {registro[1]!r}")
        linhas.append((sku, custo))
    return linhas


def main() -> None:
    parser = argparse.ArgumentParser(description="Importa custos de produtos por SKU")
    parser.add_argument("--cliente", type=int, required=True)
    parser.add_argument("--arquivo", type=Path, required=True)
    parser.add_argument("--prefixo", action="store_true",
                        help="cada sku do CSV casa todos os SKUs que começam por ele")
    parser.add_argument("--simular", action="store_true", help="não grava, só mostra")
    args = parser.parse_args()

    if not args.arquivo.exists():
        raise SystemExit(f"Arquivo não encontrado: {args.arquivo}")

    linhas = _ler_csv(args.arquivo)
    sessao = Sessao()
    atualizados_total = 0
    sem_correspondencia = []

    for sku, custo in linhas:
        condicao = (
            Produto.sku.like(f"{sku}%") if args.prefixo else Produto.sku == sku
        )
        resultado = sessao.execute(
            update(Produto)
            .where(Produto.cliente_id == args.cliente, condicao)
            .values(preco_custo=custo)
        )
        if resultado.rowcount == 0:
            sem_correspondencia.append(sku)
        else:
            atualizados_total += resultado.rowcount
            print(f"  {sku:<24} custo {custo:>10.2f}  -> {resultado.rowcount} produto(s)")

    if args.simular:
        sessao.rollback()
        print(f"\n[SIMULACAO] {atualizados_total} produto(s) receberiam custo. Nada gravado.")
    else:
        sessao.commit()
        print(f"\n{atualizados_total} produto(s) atualizados.")

    if sem_correspondencia:
        print(f"SKUs do CSV sem produto correspondente ({len(sem_correspondencia)}): "
              + ", ".join(sem_correspondencia[:20]))

    com_custo = sessao.execute(
        select(func.count()).select_from(Produto).where(
            Produto.cliente_id == args.cliente,
            Produto.preco_custo.is_not(None),
            Produto.preco_custo > 0,
        )
    ).scalar()
    total = sessao.execute(
        select(func.count()).select_from(Produto).where(Produto.cliente_id == args.cliente)
    ).scalar()
    print(f"Situação do cliente {args.cliente}: {com_custo}/{total} produtos com custo.")


if __name__ == "__main__":
    main()
