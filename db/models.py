"""Modelo canônico — independente da fonte dos dados.

O Bling é apenas o primeiro conector: ele despeja dados neste modelo e o
dashboard lê daqui, sem saber de onde vieram. Conectores futuros (Mercado
Livre, Shopee) gravam nas mesmas tabelas.

Todo registro de negócio carrega (cliente_id, fonte, id_externo), com
índice único nessa trinca para permitir upsert. O cliente_id entra no
índice para que contas Bling de clientes diferentes nunca colidam.
"""
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from db.database import engine


class Base(DeclarativeBase):
    pass


class Cliente(Base):
    __tablename__ = "clientes"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(200))
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Canal(Base):
    """Canal de venda (Shopee, Mercado Livre, site próprio...)."""

    __tablename__ = "canais"
    __table_args__ = (UniqueConstraint("cliente_id", "fonte", "id_externo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True)
    fonte: Mapped[str] = mapped_column(String(30))
    id_externo: Mapped[str] = mapped_column(String(60))
    nome: Mapped[str] = mapped_column(String(120))


class Produto(Base):
    __tablename__ = "produtos"
    __table_args__ = (UniqueConstraint("cliente_id", "fonte", "id_externo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True)
    fonte: Mapped[str] = mapped_column(String(30))
    id_externo: Mapped[str] = mapped_column(String(60))
    sku: Mapped[str | None] = mapped_column(String(120))
    nome: Mapped[str] = mapped_column(String(300))
    preco_venda: Mapped[float | None] = mapped_column(Numeric(12, 2))
    preco_custo: Mapped[float | None] = mapped_column(Numeric(12, 2))
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Pedido(Base):
    __tablename__ = "pedidos"
    __table_args__ = (UniqueConstraint("cliente_id", "fonte", "id_externo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True)
    canal_id: Mapped[int | None] = mapped_column(ForeignKey("canais.id"))
    fonte: Mapped[str] = mapped_column(String(30))
    id_externo: Mapped[str] = mapped_column(String(60))
    numero: Mapped[str | None] = mapped_column(String(60))
    data: Mapped[date] = mapped_column(Date, index=True)
    situacao: Mapped[str | None] = mapped_column(String(60))
    valor_total: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    dados_cru: Mapped[dict | None] = mapped_column(JSON)

    canal: Mapped["Canal | None"] = relationship()
    itens: Mapped[list["ItemPedido"]] = relationship(
        back_populates="pedido", cascade="all, delete-orphan"
    )
    taxas: Mapped[list["TaxaPedido"]] = relationship(
        back_populates="pedido", cascade="all, delete-orphan"
    )


class ItemPedido(Base):
    __tablename__ = "itens_pedido"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos.id"), index=True)
    produto_id: Mapped[int | None] = mapped_column(ForeignKey("produtos.id"))
    descricao: Mapped[str] = mapped_column(String(300))
    quantidade: Mapped[float] = mapped_column(Numeric(12, 3), default=1)
    valor_unitario: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    valor_total: Mapped[float] = mapped_column(Numeric(12, 2), default=0)

    pedido: Mapped["Pedido"] = relationship(back_populates="itens")
    produto: Mapped["Produto | None"] = relationship()


class TaxaPedido(Base):
    """Custo incidente sobre o pedido: comissão, frete, imposto, outros.

    origem = 'fonte' quando o valor veio do dado do Bling/marketplace;
    origem = 'tabela_comissoes' quando foi estimado pela tabela da empresa.
    """

    __tablename__ = "taxas_pedido"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(30))  # comissao | frete | imposto | outros
    valor: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    origem: Mapped[str] = mapped_column(String(30), default="fonte")
    descricao: Mapped[str | None] = mapped_column(String(200))

    pedido: Mapped["Pedido"] = relationship(back_populates="taxas")


class Sincronizacao(Base):
    """Registro de cada execução do conector — base para alertas de falha."""

    __tablename__ = "sincronizacoes"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True)
    fonte: Mapped[str] = mapped_column(String(30))
    iniciada_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finalizada_em: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="executando")
    pedidos_processados: Mapped[int] = mapped_column(Integer, default=0)
    produtos_processados: Mapped[int] = mapped_column(Integer, default=0)
    mensagem: Mapped[str | None] = mapped_column(Text)


class Credencial(Base):
    """Tokens OAuth por cliente e fonte.

    Em produção estes valores devem ser criptografados em repouso —
    ponto registrado no roadmap do README.
    """

    __tablename__ = "credenciais"
    __table_args__ = (UniqueConstraint("cliente_id", "fonte"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True)
    fonte: Mapped[str] = mapped_column(String(30))
    # Credenciais do APP registrado no Bling do cliente (cada cliente tem o
    # seu app). Quando vazias, vale o fallback BLING_CLIENT_ID/SECRET do .env.
    client_id: Mapped[str | None] = mapped_column(String(120))
    client_secret: Mapped[str | None] = mapped_column(String(200))
    access_token: Mapped[str | None] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text)
    expira_em: Mapped[datetime | None] = mapped_column(DateTime)
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Usuario(Base):
    """Usuário do painel. papel 'equipe' vê todos os clientes; papel 'cliente'
    (com cliente_id preenchido) enxerga só o próprio cliente — a base do
    acesso dos clientes finais. Senha guardada com hash PBKDF2 (nunca em claro)."""

    __tablename__ = "usuarios"
    __table_args__ = (UniqueConstraint("usuario"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    usuario: Mapped[str] = mapped_column(String(60))
    senha_hash: Mapped[str] = mapped_column(String(200))
    papel: Mapped[str] = mapped_column(String(20), default="equipe")  # equipe | cliente
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("clientes.id"))
    ativo: Mapped[bool] = mapped_column(default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Preferencia(Base):
    """Preferências simples por cliente (chave/valor). Ex.: perfil de vendedor
    na Shopee (cnpj/cpf). Genérica para não criar colunas a cada ajuste."""

    __tablename__ = "preferencias"
    __table_args__ = (UniqueConstraint("cliente_id", "chave"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True)
    chave: Mapped[str] = mapped_column(String(60))
    valor: Mapped[str] = mapped_column(String(200))


class RegraComissao(Base):
    """Faixa de comissão por canal, editável pela interface, por cliente.

    Uma linha por faixa: a comissão de um item é
    `valor_unitario * percentual + fixo_por_item`, escolhida pela primeira
    faixa cujo `valor_ate` cobre o valor unitário (valor_ate nulo = sem teto).
    O `canal` casa por "contém" no nome do canal do pedido (ex.: "shopee").
    Sem regras para um cliente, o cálculo usa os padrões de core/comissoes.py.
    """

    __tablename__ = "regras_comissao"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True)
    canal: Mapped[str] = mapped_column(String(120))
    valor_ate: Mapped[float | None] = mapped_column(Numeric(12, 2))
    percentual: Mapped[float] = mapped_column(Numeric(6, 4), default=0)  # fração 0..1
    fixo_por_item: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    ordem: Mapped[int] = mapped_column(Integer, default=0)


def criar_tabelas() -> None:
    Base.metadata.create_all(engine)


if __name__ == "__main__":
    criar_tabelas()
    print(f"Tabelas criadas/atualizadas em: {engine.url}")
