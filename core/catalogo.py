"""Leitura e edição do catálogo de produtos (preço de custo pela interface)."""
import pandas as pd
from sqlalchemy import text

from db.database import Sessao, engine
from db.models import Produto

# Colunas fixas de listar_produtos — o que vier além destas são os canais
# (uma coluna de preço médio por marketplace, dinâmica por cliente).
COLUNAS_FIXAS = ["produto_id", "sku", "nome", "preco_custo",
                 "preco_medio_real", "qtd_vendida"]


def listar_produtos(cliente_id: int) -> pd.DataFrame:
    """Produtos do cliente para edição de custo.

    Preços de venda vêm das VENDAS REAIS (itens dos pedidos), não do cadastro
    do Bling — este costuma vir zerado quando o preço fica na variação.
    Como o preço difere por marketplace, além da média geral
    (preco_medio_real) sai uma coluna por canal, ordenadas pelo volume.
    """
    with engine.connect() as conexao:
        df = pd.read_sql(
            text("""
                SELECT pr.id AS produto_id, pr.sku, pr.nome, pr.preco_custo,
                       AVG(i.valor_unitario) AS preco_medio_real,
                       COALESCE(SUM(i.quantidade), 0) AS qtd_vendida
                FROM produtos pr
                LEFT JOIN itens_pedido i ON i.produto_id = pr.id
                WHERE pr.cliente_id = :c
                GROUP BY pr.id, pr.sku, pr.nome, pr.preco_custo
                ORDER BY qtd_vendida DESC, pr.nome
            """),
            conexao, params={"c": cliente_id},
        )
        por_canal = pd.read_sql(
            text("""
                SELECT i.produto_id, COALESCE(c.nome, 'Sem canal') AS canal,
                       AVG(i.valor_unitario) AS preco_medio,
                       SUM(i.quantidade) AS qtd
                FROM itens_pedido i
                JOIN pedidos p ON p.id = i.pedido_id
                LEFT JOIN canais c ON c.id = p.canal_id
                WHERE i.cliente_id = :c AND i.produto_id IS NOT NULL
                GROUP BY i.produto_id, COALESCE(c.nome, 'Sem canal')
            """),
            conexao, params={"c": cliente_id},
        )

    df["preco_medio_real"] = pd.to_numeric(df["preco_medio_real"], errors="coerce")
    df["preco_custo"] = pd.to_numeric(df["preco_custo"], errors="coerce")
    df["qtd_vendida"] = pd.to_numeric(df["qtd_vendida"], errors="coerce").fillna(0)

    if not por_canal.empty:
        por_canal["preco_medio"] = pd.to_numeric(por_canal["preco_medio"], errors="coerce")
        por_canal["qtd"] = pd.to_numeric(por_canal["qtd"], errors="coerce").fillna(0)
        # canais mais vendidos primeiro (Shopee antes de ML, por exemplo)
        ordem = (por_canal.groupby("canal")["qtd"].sum()
                 .sort_values(ascending=False).index.tolist())
        pivo = por_canal.pivot_table(index="produto_id", columns="canal",
                                     values="preco_medio", aggfunc="mean")
        pivo = pivo.reindex(columns=[c for c in ordem if c in pivo.columns])
        df = df.merge(pivo.reset_index(), on="produto_id", how="left")

    return df


def gerar_planilha_modelo(cliente_id: int) -> bytes:
    """Planilha Excel com os produtos do cliente para preencher o custo.

    Colunas: SKU, Produto, Vendidos, Preço médio de venda e Preço custo
    (com o valor atual, se houver). O usuário preenche a última e importa.
    """
    import io

    df = listar_produtos(cliente_id)
    modelo = df[["sku", "nome", "qtd_vendida", "preco_medio_real", "preco_custo"]].rename(
        columns={"sku": "SKU", "nome": "Produto", "qtd_vendida": "Vendidos",
                 "preco_medio_real": "Preco medio de venda (R$)",
                 "preco_custo": "Preco custo (R$)"}
    )
    buffer = io.BytesIO()
    modelo.to_excel(buffer, index=False, sheet_name="Custos")
    return buffer.getvalue()


def _para_numero(valor) -> float | None:
    """Aceita 45.9, '45,90', 'R$ 1.234,56' e afins. None quando vazio."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return None if pd.isna(valor) else float(valor)
    texto = str(valor).strip().replace("R$", "").replace(" ", "")
    if not texto:
        return None
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def _eh_coluna_sku(nome) -> bool:
    return "sku" in str(nome).strip().lower()


def _eh_coluna_custo(nome) -> bool:
    """Reconhece 'Preco custo', 'CUSTO', 'VALOR DA COMPRA + FRETE' e variações."""
    texto = str(nome).strip().lower()
    return "custo" in texto or ("compra" in texto and "frete" in texto)


def _extrair_custos_da_aba(bruta: pd.DataFrame) -> dict[str, float]:
    """Extrai {SKU: custo} de uma aba lida SEM cabeçalho.

    Acha a linha de cabeçalho procurando 'SKU' + coluna de custo nas
    primeiras 10 linhas — tolera títulos e linhas soltas antes da tabela.
    Abas sem esse par (ex.: tabelas de frete) retornam vazio.
    """
    for indice in range(min(10, len(bruta))):
        cabecalho = bruta.iloc[indice]
        col_sku = next((c for c in bruta.columns if _eh_coluna_sku(cabecalho[c])), None)
        col_custo = next((c for c in bruta.columns if _eh_coluna_custo(cabecalho[c])), None)
        if col_sku is None or col_custo is None:
            continue

        custos: dict[str, float] = {}
        for _, linha in bruta.iloc[indice + 1:].iterrows():
            sku = str(linha[col_sku] if linha[col_sku] is not None else "").strip()
            custo = _para_numero(linha[col_custo])
            if not sku or sku.lower() in ("nan", "none", "0") or custo is None:
                continue
            custos[sku.upper()] = round(custo, 2)
        return custos
    return {}


def importar_planilha(cliente_id: int, arquivo, nome_arquivo: str = "") -> dict:
    """Aplica custos de uma planilha (xlsx/csv) casando por SKU.

    Lê TODAS as abas do Excel (planilhas de precificação costumam ter uma
    aba por marketplace); reconhece a coluna de custo por 'custo' ou
    'valor da compra + frete', e acha o cabeçalho mesmo fora da 1ª linha.
    O mesmo SKU em várias abas usa o último valor lido.
    """
    if nome_arquivo.lower().endswith(".csv"):
        tabela = pd.read_csv(arquivo, sep=None, engine="python", header=None, dtype=str)
        abas = {"csv": tabela}
    else:
        abas = pd.read_excel(arquivo, sheet_name=None, header=None)

    custos_por_sku: dict[str, float] = {}
    abas_usadas = []
    for nome_aba, bruta in abas.items():
        extraidos = _extrair_custos_da_aba(bruta)
        if extraidos:
            custos_por_sku.update(extraidos)
            abas_usadas.append(str(nome_aba))

    if not custos_por_sku:
        return {"erro": "Nenhuma aba com colunas de SKU e custo encontrada. "
                        "A coluna de custo deve conter 'custo' ou "
                        "'valor da compra + frete' no nome."}

    produtos = listar_produtos(cliente_id)
    por_sku: dict[str, list[int]] = {}
    for linha in produtos.itertuples():
        if linha.sku:
            por_sku.setdefault(str(linha.sku).strip().upper(), []).append(int(linha.produto_id))

    custos: dict[int, float] = {}
    nao_encontrados: list[str] = []
    for sku, custo in custos_por_sku.items():
        ids = por_sku.get(sku)
        if not ids:
            nao_encontrados.append(sku)
            continue
        for produto_id in ids:
            custos[produto_id] = custo

    atualizados = salvar_custos(cliente_id, custos) if custos else 0
    return {
        "abas_usadas": abas_usadas,
        "linhas_com_custo": len(custos_por_sku),
        "produtos_atualizados": atualizados,
        "nao_encontrados": nao_encontrados,
    }


def salvar_custos(cliente_id: int, custos: dict[int, float | None]) -> int:
    """Atualiza preco_custo dos produtos informados (id -> custo). Conta alterados."""
    alterados = 0
    with Sessao() as sessao:
        for produto_id, custo in custos.items():
            produto = sessao.get(Produto, int(produto_id))
            if produto is None or produto.cliente_id != cliente_id:
                continue
            novo = None if custo in (None, "") else round(float(custo), 2)
            atual = float(produto.preco_custo) if produto.preco_custo is not None else None
            if novo != atual:
                produto.preco_custo = novo
                alterados += 1
        sessao.commit()
    return alterados


def resumo_custos(cliente_id: int) -> dict:
    """Quantos produtos têm custo preenchido — mostrado na tela de configuração."""
    df = listar_produtos(cliente_id)
    com_custo = int(((df["preco_custo"].notna()) & (df["preco_custo"] > 0)).sum())
    return {"total": len(df), "com_custo": com_custo, "sem_custo": len(df) - com_custo}
