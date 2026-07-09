"""Migra todos os dados do SQLite local para o Postgres (DATABASE_URL do .env).

    python -m scripts.migrar_banco            # recusa se o destino já tem dados
    python -m scripts.migrar_banco --forcar   # apaga o destino e migra de novo

Copia as tabelas na ordem de dependência preservando os ids e, ao final,
realinha as sequências do Postgres. O SQLite (dados_demo.db) fica intacto.
"""
import argparse

from sqlalchemy import create_engine, func, select, text

from db.database import DATABASE_URL, RAIZ_PROJETO, USANDO_SQLITE
from db.models import Base

LOTE = 500


def main() -> None:
    parser = argparse.ArgumentParser(description="Migra SQLite local -> Postgres")
    parser.add_argument("--forcar", action="store_true",
                        help="apaga as tabelas do destino antes de migrar")
    args = parser.parse_args()

    if USANDO_SQLITE:
        raise SystemExit("DATABASE_URL não está preenchida no .env — nada a migrar.")

    caminho_sqlite = RAIZ_PROJETO / "dados_demo.db"
    if not caminho_sqlite.exists():
        raise SystemExit(f"Banco de origem não encontrado: {caminho_sqlite}")

    origem = create_engine(f"sqlite:///{caminho_sqlite.as_posix()}")
    destino = create_engine(DATABASE_URL, pool_pre_ping=True)
    print(f"Origem : {origem.url}")
    print(f"Destino: {destino.url.host}/{destino.url.database}")

    with destino.begin() as cx:
        if args.forcar:
            Base.metadata.drop_all(cx)
        Base.metadata.create_all(cx)

    with destino.connect() as cx:
        existentes = cx.execute(
            select(func.count()).select_from(Base.metadata.tables["clientes"])
        ).scalar()
    if existentes and not args.forcar:
        raise SystemExit(
            f"Destino já tem {existentes} cliente(s). Use --forcar para recriar."
        )

    with origem.connect() as cx_origem, destino.begin() as cx_destino:
        for tabela in Base.metadata.sorted_tables:
            linhas = [
                dict(linha._mapping)
                for linha in cx_origem.execute(select(tabela))
            ]
            for inicio in range(0, len(linhas), LOTE):
                cx_destino.execute(tabela.insert(), linhas[inicio:inicio + LOTE])
            print(f"  {tabela.name:<16} {len(linhas):>6} linhas")

        # Inserimos ids explícitos; realinha as sequências do Postgres
        for tabela in Base.metadata.sorted_tables:
            if "id" in tabela.c:
                cx_destino.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('{tabela.name}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {tabela.name}), 1))"
                ))

    print("\nConferência (origem = destino?):")
    with origem.connect() as cx_origem, destino.connect() as cx_destino:
        tudo_ok = True
        for tabela in Base.metadata.sorted_tables:
            n_origem = cx_origem.execute(
                select(func.count()).select_from(tabela)).scalar()
            n_destino = cx_destino.execute(
                select(func.count()).select_from(tabela)).scalar()
            situacao = "OK" if n_origem == n_destino else "DIVERGE!"
            tudo_ok = tudo_ok and n_origem == n_destino
            print(f"  {tabela.name:<16} {n_origem:>6} -> {n_destino:<6} {situacao}")

    if not tudo_ok:
        raise SystemExit("Migração com divergências — NÃO use o destino ainda.")
    print("\nMigração concluída. O sistema passa a usar o Postgres do .env.")


if __name__ == "__main__":
    main()
