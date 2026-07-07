"""Formatação de números no padrão brasileiro."""


def moeda(valor: float) -> str:
    texto = f"{valor:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
    return f"R$ {texto}"


def pct(valor: float, casas: int = 1) -> str:
    return f"{valor:.{casas}f}".replace(".", ",") + "%"


def inteiro(valor: float) -> str:
    return f"{valor:,.0f}".replace(",", ".")
