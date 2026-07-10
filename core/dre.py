"""DRE gerencial por cliente e período, com exportação em PDF.

Estrutura (dados do modelo canônico):

    RECEITA BRUTA DE VENDAS
    (-) Comissões de marketplace
    (-) Fretes pagos pelo vendedor
    (-) Impostos sobre vendas
    (-) Outras taxas e custos operacionais
    = RECEITA LÍQUIDA
    (-) Custo dos produtos vendidos (CMV)
    = RESULTADO BRUTO (margem real)

O PDF segue a identidade da Caplace Consulting: branco como base, com
detalhes em laranja e azul.
"""
import io
from datetime import date, datetime

import pandas as pd

from core import metricas
from core.formatos import moeda, pct

AZUL = "#1c5cab"
LARANJA = "#e8731a"
CINZA = "#52514e"


def montar_dre(cliente_id: int, dt_ini: date, dt_fim: date,
               canais: list[str] | None = None) -> dict:
    """Linhas da DRE + quebra por canal + notas, para tela e PDF."""
    df = metricas.analitico_pedidos(cliente_id, dt_ini, dt_fim, canais)
    k = metricas.kpis(df)
    receita = k["receita"]

    def _pct(valor: float) -> float:
        return (valor / receita * 100) if receita else 0.0

    def _neg(valor: float) -> float:
        return -valor if valor else 0.0  # evita o feio "-0,00"

    receita_liquida = receita - k["taxas"]
    linhas = [
        {"conta": "RECEITA BRUTA DE VENDAS", "valor": receita,
         "pct": 100.0 if receita else 0.0, "tipo": "total"},
        {"conta": "(-) Comissões de marketplace", "valor": _neg(k["comissao"]),
         "pct": _neg(_pct(k["comissao"])), "tipo": "deducao"},
        {"conta": "(-) Fretes pagos pelo vendedor", "valor": _neg(k["frete"]),
         "pct": _neg(_pct(k["frete"])), "tipo": "deducao"},
        {"conta": "(-) Impostos sobre vendas", "valor": _neg(k["imposto"]),
         "pct": _neg(_pct(k["imposto"])), "tipo": "deducao"},
        {"conta": "(-) Outras taxas e custos", "valor": _neg(k["outros"]),
         "pct": _neg(_pct(k["outros"])), "tipo": "deducao"},
        {"conta": "= RECEITA LÍQUIDA", "valor": receita_liquida,
         "pct": _pct(receita_liquida), "tipo": "subtotal"},
        {"conta": "(-) Custo dos produtos vendidos (CMV)", "valor": _neg(k["custo"]),
         "pct": _neg(_pct(k["custo"])), "tipo": "deducao"},
        {"conta": "= RESULTADO BRUTO (margem real)", "valor": k["margem"],
         "pct": k["margem_pct"], "tipo": "resultado"},
    ]

    if df.empty:
        por_canal = pd.DataFrame()
        sem_custo = 0
    else:
        por_canal = (
            df.groupby("canal_nome", as_index=False)
            .agg(pedidos=("pedido_id", "count"), receita=("valor_total", "sum"),
                 taxas=("taxas_totais", "sum"), cmv=("custo_produtos", "sum"),
                 resultado=("margem", "sum"))
            .sort_values("receita", ascending=False)
        )
        por_canal["margem_pct"] = (
            por_canal["resultado"] / por_canal["receita"].replace(0, pd.NA) * 100
        ).astype(float).fillna(0.0)
        sem_custo = int((df["custo_produtos"] <= 0).sum())

    notas = [
        f"Período: {dt_ini.strftime('%d/%m/%Y')} a {dt_fim.strftime('%d/%m/%Y')} — "
        f"{k['pedidos']} pedidos válidos (cancelados excluídos); "
        f"ticket médio {moeda(k['ticket_medio'])}.",
        f"Comissões: {pct(k['pct_comissao_real'])} da receita com valor informado "
        "pela fonte; o restante é estimado pela tabela de comissões configurada.",
    ]
    if sem_custo:
        notas.append(
            f"{sem_custo} pedido(s) contêm produtos ainda sem preço de custo "
            "cadastrado — o CMV desses itens entra como zero (resultado a maior)."
        )
    if k["imposto"] <= 0:
        notas.append(
            "Impostos zerados: a fonte não os informa e nenhuma alíquota foi "
            "configurada em Configurações → Impostos e custos."
        )

    return {"linhas": linhas, "por_canal": por_canal, "kpis": k, "notas": notas}


def gerar_pdf_dre(nome_cliente: str, dt_ini: date, dt_fim: date, dre: dict) -> bytes:
    """PDF da DRE — identidade Caplace Consulting (laranja/azul sobre branco)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    azul = colors.HexColor(AZUL)
    laranja = colors.HexColor(LARANJA)
    cinza = colors.HexColor(CINZA)
    zebra = colors.HexColor("#f6f8fc")

    estilos = getSampleStyleSheet()
    marca = ParagraphStyle("marca", parent=estilos["Normal"], fontSize=16,
                           leading=20, spaceAfter=4,
                           fontName="Helvetica-Bold", textColor=laranja)
    titulo = ParagraphStyle("titulo", parent=estilos["Normal"], fontSize=12.5,
                            fontName="Helvetica-Bold", textColor=azul, spaceBefore=2)
    contexto = ParagraphStyle("contexto", parent=estilos["Normal"], fontSize=9.5,
                              textColor=cinza, spaceBefore=4)
    secao = ParagraphStyle("secao", parent=estilos["Normal"], fontSize=11,
                           fontName="Helvetica-Bold", textColor=azul,
                           spaceBefore=14, spaceAfter=4)
    nota = ParagraphStyle("nota", parent=estilos["Normal"], fontSize=8.5,
                          textColor=cinza, leading=11.5, leftIndent=8)
    rodape = ParagraphStyle("rodape", parent=estilos["Normal"], fontSize=8,
                            textColor=cinza)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=1.9 * cm, rightMargin=1.9 * cm,
        topMargin=1.6 * cm, bottomMargin=1.5 * cm,
        title=f"DRE — {nome_cliente}", author="Caplace Consulting",
    )

    historia = [
        Paragraph("Caplace Consulting", marca),
        Paragraph("Relatório DRE — Demonstração do Resultado", titulo),
        Paragraph(
            f"Cliente: <b>{nome_cliente}</b> &nbsp;·&nbsp; Período: "
            f"{dt_ini.strftime('%d/%m/%Y')} a {dt_fim.strftime('%d/%m/%Y')}",
            contexto),
        Spacer(1, 6),
        HRFlowable(width="100%", thickness=2.2, color=laranja, spaceAfter=10),
    ]

    # ── Tabela principal da DRE ──────────────────────────────────────────
    corpo = [["Conta", "Valor (R$)", "% da receita"]]
    estilo_linhas = []
    for i, linha in enumerate(dre["linhas"], start=1):
        corpo.append([
            linha["conta"],
            moeda(linha["valor"]).replace("R$ ", ""),
            pct(linha["pct"]),
        ])
        if linha["tipo"] == "total":
            estilo_linhas += [
                ("FONTNAME", (0, i), (-1, i), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, i), (-1, i), azul),
            ]
        elif linha["tipo"] == "subtotal":
            estilo_linhas += [
                ("FONTNAME", (0, i), (-1, i), "Helvetica-Bold"),
                ("LINEABOVE", (0, i), (-1, i), 0.8, azul),
                ("BACKGROUND", (0, i), (-1, i), colors.HexColor("#eef4fb")),
            ]
        elif linha["tipo"] == "resultado":
            estilo_linhas += [
                ("FONTNAME", (0, i), (-1, i), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, i), (-1, i), colors.white),
                ("BACKGROUND", (0, i), (-1, i), laranja),
            ]

    tabela = Table(corpo, colWidths=[10.4 * cm, 3.6 * cm, 3.0 * cm])
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), azul),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d7dfeb")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        *estilo_linhas,
    ]))
    historia.append(tabela)

    # ── Por canal ────────────────────────────────────────────────────────
    por_canal = dre["por_canal"]
    if len(por_canal):
        historia.append(Paragraph("Resultado por canal de venda", secao))
        corpo_canal = [["Canal", "Pedidos", "Receita (R$)", "Taxas (R$)",
                        "CMV (R$)", "Resultado (R$)", "Margem"]]
        for registro in por_canal.itertuples():
            corpo_canal.append([
                registro.canal_nome, f"{int(registro.pedidos)}",
                moeda(registro.receita).replace("R$ ", ""),
                moeda(registro.taxas).replace("R$ ", ""),
                moeda(registro.cmv).replace("R$ ", ""),
                moeda(registro.resultado).replace("R$ ", ""),
                pct(registro.margem_pct),
            ])
        tabela_canal = Table(
            corpo_canal,
            colWidths=[3.6 * cm, 1.7 * cm, 2.6 * cm, 2.4 * cm, 2.4 * cm, 2.7 * cm, 1.6 * cm],
        )
        tabela_canal.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), laranja),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.6),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, zebra]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e3d9cf")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        historia.append(tabela_canal)

    # ── Notas ────────────────────────────────────────────────────────────
    historia.append(Paragraph("Notas metodológicas", secao))
    for texto in dre["notas"]:
        historia.append(Paragraph(f"• {texto}", nota))
        historia.append(Spacer(1, 2))

    historia += [
        Spacer(1, 10),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#d7dfeb"), spaceAfter=4),
        Paragraph(
            f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} · "
            "Caplace Consulting · Painel MétricasBling — dados do modelo "
            "canônico (Bling API v3).",
            rodape),
    ]

    doc.build(historia)
    return buffer.getvalue()
