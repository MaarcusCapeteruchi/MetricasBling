"""Conexão com o banco: Neon/Postgres em produção, SQLite local como fallback.

O dashboard e o conector leem DATABASE_URL do .env. Sem DATABASE_URL,
usa-se um SQLite local (dados_demo.db) — suficiente para desenvolvimento
e para a demo offline; o modelo de dados é o mesmo nos dois casos.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

RAIZ_PROJETO = Path(__file__).resolve().parents[1]
load_dotenv(RAIZ_PROJETO / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
USANDO_SQLITE = not DATABASE_URL

if USANDO_SQLITE:
    DATABASE_URL = f"sqlite:///{(RAIZ_PROJETO / 'dados_demo.db').as_posix()}"
elif DATABASE_URL.startswith("postgres://"):
    # Algumas telas do Neon exibem o esquema antigo; o SQLAlchemy exige postgresql://
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
Sessao = sessionmaker(bind=engine, expire_on_commit=False)
