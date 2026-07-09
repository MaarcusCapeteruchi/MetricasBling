# MétricasBling — Dashboard de Margem Real

Sistema de análise de métricas para operações de marketplace. Extrai pedidos e
produtos do **Bling (API v3)**, grava num **modelo canônico** próprio (Postgres)
e apresenta num **dashboard Streamlit** o número que mais importa: a **margem
real por pedido** (vendas − comissões − frete − impostos − custo dos produtos).

> **Princípio de arquitetura:** o Bling é só o primeiro conector. O dashboard lê
> exclusivamente do modelo canônico — quando entrarem conectores diretos de
> Mercado Livre/Shopee, o painel não muda nada. O sistema é multi-cliente desde
> o início (`cliente_id` em todas as tabelas e consultas).

```
Bling API v3 ──► conector/ ──► modelo canônico (Postgres/Neon) ──► dashboard/ (Streamlit)
   (OAuth)        upsert          clientes, canais, produtos,          lê só do banco
                                  pedidos, itens, taxas, sincs
```

## Estrutura

| Pasta | Papel |
|---|---|
| `conector/` | OAuth Bling + sincronização (paginação, rate limit, upsert) |
| `db/` | Modelo canônico SQLAlchemy + conexão (Neon ou SQLite local) |
| `core/` | Regras de negócio: margem real, tabela de comissões, consultas |
| `dashboard/` | App Streamlit — só apresentação, nenhuma regra de negócio |
| `scripts/` | Seed de demonstração e conferência manual de margem |

## Rodar localmente (demo offline, sem credenciais)

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt

python -m scripts.seed_demo       # dados de demonstração (fonte 'demo')
streamlit run dashboard/app.py    # abre em http://localhost:8501
```

Sem `DATABASE_URL` no `.env`, usa-se um SQLite local (`dados_demo.db`) — mesmo
modelo de dados do Postgres.

### Configurações pela interface (sem editar código)

A página **⚙️ Configurações** (menu lateral do dashboard) deixa o usuário
ajustar, por cliente e sem tocar no código:

- **Comissões por canal** — faixas por valor do item (percentual + taxa fixa);
  gravadas na tabela `regras_comissao`. Enquanto o cliente não edita, valem os
  padrões de `core/comissoes.py` (Shopee oficial mar/2026; ML e TikTok
  estimados). Botão para restaurar o padrão. Cada coluna tem tooltip (ícone ?)
  e há uma legenda expansível.
- **Perfil do vendedor na Shopee (CNPJ/CPF)** — um seletor troca as faixas da
  Shopee pela tabela oficial do perfil (o CPF de alto volume, +450 pedidos/90
  dias, paga +R$3 por item). A escolha fica na tabela `preferencias`.
- **Custos dos produtos** — edição direta do preço de custo, com busca. Para
  cargas grandes, use `scripts/importar_custos.py`.
- **Clientes** — lista os clientes e permite **excluir** um deles (com todos os
  seus dados) pela interface, protegido por confirmação (digitar o nome).
- **Usuários** — contas de acesso com papel **Equipe** (vê tudo) ou **Cliente**
  (vê só o painel do cliente vinculado; sem Configurações). Senhas com hash
  PBKDF2. O usuário `admin` + APP_SENHA é o acesso mestre, sempre disponível.

### Login e celular

O painel exige login (usuário + senha) sempre que `APP_SENHA` está definida ou
existem usuários cadastrados. A interface é responsiva: no celular os KPIs
empilham e o layout se ajusta. Obs.: recarregar a página (F5) encerra a sessão
do Streamlit — é preciso entrar de novo.

Ao salvar, o painel recalcula a margem na hora.

## Plugar o Bling real (cliente piloto)

1. **Registrar o app** na Central de Extensões do Bling, com escopos
   *Pedidos de Venda* e *Produtos* e URL de redirecionamento
   `http://localhost:8484/callback`.
2. Copiar `.env.exemplo` para `.env` e preencher `BLING_CLIENT_ID` /
   `BLING_CLIENT_SECRET` (e `DATABASE_URL` do Neon, se for usar Postgres).
3. **Autorizar com a conta Bling do cliente:**
   ```bash
   python -m conector.autorizar --novo-cliente "Nome da Loja"
   ```
4. **Check que define a demo** — inspecionar um pedido cru para ver se a
   comissão do marketplace vem no dado (campo `taxas`):
   ```bash
   python -m conector.sincronizar --cliente 1 --inspecionar
   ```
   Se vier, a margem é leitura pura. Se não vier, ajuste a tabela em
   [core/comissoes.py](core/comissoes.py) — **os valores atuais são
   aproximados; substitua pela tabela oficial da empresa.**
5. **Sincronizar** (teste pequeno primeiro, depois completo):
   ```bash
   python -m conector.sincronizar --cliente 1 --limite 20
   python -m conector.sincronizar --cliente 1 --desde 2026-04-01
   ```
6. **Conferir a margem de um pedido na mão** (checklist da demo):
   ```bash
   python -m scripts.conferir_margem --cliente 1
   ```

## Deploy no Streamlit Community Cloud (custo R$ 0)

1. Suba o repositório no GitHub (o `.gitignore` já protege `.env` e o banco).
2. Em [share.streamlit.io](https://share.streamlit.io), conecte o repositório e
   aponte para `dashboard/app.py`.
3. Em **App settings → Secrets**, configure (viram variáveis de ambiente):
   ```toml
   DATABASE_URL = "postgresql://usuario:senha@ep-xxxx.neon.tech/neondb?sslmode=require"
   APP_SENHA = "uma-senha-forte"
   MARGEM_ALERTA_PCT = "10"
   ```
4. A sincronização roda da sua máquina (ou de um agendador futuro) contra o
   mesmo Neon; o painel na nuvem só lê o banco.

`APP_SENHA` ativa a tela de senha — recomendado, pois a URL do Community Cloud
é pública.

## Roadmap (fases seguintes)

- Sincronização agendada (GitHub Actions cron) com alerta de falha — a tabela
  `sincronizacoes` já registra cada execução.
- Criptografia dos tokens OAuth em repouso e login multiusuário.
- Conectores diretos Mercado Livre/Shopee gravando no mesmo modelo canônico.
- Front white-label (FastAPI + React) quando virar produto — `core/` e `db/`
  permanecem intactos.
