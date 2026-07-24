"""Estação de precificação: registra a decisão de preço e mantém o espelho Excel.

A decisão congela o contexto (custo, peso, margem-alvo e preço + margem
esperada por canal) para o robô auditar depois contra a venda real. Liga-se
ao produto por SKU — não exige produto já sincronizado do Bling.
"""
import io

import pandas as pd
from sqlalchemy import select

from core import simulador
from core.formatos import moeda, pct
from db.database import Sessao
from db.models import Precificacao


def calcular(cliente_id: int, custo: float, peso: float | None,
             margem_alvo_pct: float) -> list[dict]:
    """Preço sugerido + margem por canal para a margem-alvo (usa o simulador)."""
    minimos = {l["canal"]: l["preco_minimo"]
               for l in simulador.preco_para_margem(cliente_id, custo, margem_alvo_pct, peso)}
    linhas = []
    for canal, preco in minimos.items():
        if preco is None:
            linhas.append({"canal": canal, "preco": None, "margem_pct": None})
            continue
        # margem exata no preço sugerido (confirma o alvo)
        sim = next((s for s in simulador.simular_preco(cliente_id, preco, custo, peso)
                    if s["canal"] == canal), None)
        linhas.append({"canal": canal, "preco": preco,
                       "margem_pct": sim["margem_pct"] if sim else margem_alvo_pct})
    return linhas


def salvar(cliente_id: int, sku: str, produto: str, custo: float,
           peso: float | None, margem_alvo_pct: float,
           precos_por_canal: dict[str, dict], observacao: str = "",
           usuario: str = "") -> int:
    """Grava a decisão. Uma precificação por (cliente, sku): regrava se repetir."""
    with Sessao() as sessao:
        registro = None
        if sku:
            registro = sessao.execute(
                select(Precificacao).where(
                    Precificacao.cliente_id == cliente_id,
                    Precificacao.sku == sku.strip(),
                )
            ).scalar_one_or_none()
        if registro is None:
            registro = Precificacao(cliente_id=cliente_id)
            sessao.add(registro)
        registro.sku = (sku or "").strip() or None
        registro.produto = produto.strip() or "(sem nome)"
        registro.custo = round(custo, 2)
        registro.peso = peso
        registro.margem_alvo = round(margem_alvo_pct, 2)
        registro.precos = precos_por_canal
        registro.observacao = (observacao or "").strip() or None
        registro.usuario = usuario or None
        sessao.commit()
        return registro.id


def listar(cliente_id: int) -> pd.DataFrame:
    """Histórico enxuto (1 linha por canal precificado), mais recente primeiro."""
    with Sessao() as sessao:
        registros = sessao.execute(
            select(Precificacao)
            .where(Precificacao.cliente_id == cliente_id)
            .order_by(Precificacao.decidido_em.desc())
        ).scalars().all()

    linhas = []
    for r in registros:
        for canal, dados in (r.precos or {}).items():
            linhas.append({
                "Data": r.decidido_em.strftime("%d/%m/%Y"),
                "SKU": r.sku or "",
                "Produto": r.produto,
                "Canal": canal,
                "Preço decidido": dados.get("preco"),
                "Margem %": dados.get("margem_pct"),
                "Custo": float(r.custo),
                "Obs.": r.observacao or "",
            })
    return pd.DataFrame(linhas)


def excluir(precificacao_id: int) -> None:
    with Sessao() as sessao:
        registro = sessao.get(Precificacao, precificacao_id)
        if registro:
            sessao.delete(registro)
            sessao.commit()


def ids_por_sku(cliente_id: int) -> dict[str, int]:
    """Mapa SKU -> id (para o histórico oferecer exclusão)."""
    with Sessao() as sessao:
        registros = sessao.execute(
            select(Precificacao.id, Precificacao.sku, Precificacao.produto)
            .where(Precificacao.cliente_id == cliente_id)
            .order_by(Precificacao.decidido_em.desc())
        ).all()
    return {f"{sku or '(sem SKU)'} — {produto[:40]}": pid for pid, sku, produto in registros}


def exportar_excel(cliente_id: int) -> bytes:
    """Espelho da lista de precificações em Excel (Forma A — download local)."""
    df = listar(cliente_id)
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, sheet_name="Precificacoes")
    return buffer.getvalue()
