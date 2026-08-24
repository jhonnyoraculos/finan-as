# Finanças Pessoais

Aplicação local, mobile-first, para controle financeiro pessoal com Streamlit, PostgreSQL/Neon, SQLAlchemy, Plotly e uma interface Dark Liquid Glass.

O projeto mantém compras de cartão separadas do saldo bancário: a compra entra na fatura e a conta só é debitada quando a fatura é paga. Transferências também são vinculadas e não entram como receita ou despesa.

## Funcionalidades

- Contas, saldos derivados e dinheiro físico
- Receitas, despesas, PIX, dinheiro, débito, boleto e transferências
- Cadastro rápido com parsing de moeda brasileira
- Cartões, faturas abertas/fechadas/pagas e limite disponível
- Compras parceladas com meses restantes, progresso e data de término
- Empréstimos mensais com valor recebido, total financiado, parcelas já pagas,
  saldo devedor, cronograma e baixa da próxima parcela
- Contas a pagar, recorrências e assinaturas
- Histórico paginado, pesquisa global, filtros, edição e soft delete
- Dashboard, relatório mensal, gráficos e indicadores locais
- Previsão de saldo com contas, faturas, assinaturas e receitas futuras
- Orçamentos por categoria, metas e aportes
- Ativos, passivos, patrimônio líquido e snapshots históricos
- Calendário financeiro mensal
- Favoritos, modo privacidade e exportação CSV/ZIP
- Onboarding e dados de demonstração opcionais

## Requisitos

- Python 3.11 ou mais recente (3.12 recomendado)
- Uma conta e um projeto PostgreSQL no [Neon](https://neon.tech/)
- Windows, macOS ou Linux

## 1. Ambiente virtual

No diretório do projeto:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Windows Prompt de Comando:

```bat
.venv\Scripts\activate.bat
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Instale as dependências:

```bash
python -m pip install -r requirements.txt
```

Também é possível usar `uv`:

```bash
uv venv --python 3.12
uv pip install -r requirements.txt
```

## 2. Criar e configurar o Neon

1. Crie um projeto no Neon.
2. Abra **Connect** e copie a connection string PostgreSQL.
3. Crie `.streamlit/secrets.toml` a partir do exemplo:

```powershell
Copy-Item .streamlit\secrets.toml.example .streamlit\secrets.toml
```

4. Edite o arquivo real:

```toml
DATABASE_URL = "postgresql+psycopg://usuario:senha@host.neon.tech/neondb?sslmode=require"
```

URLs fornecidas pelo Neon como `postgresql://...` também são aceitas e convertidas internamente para o driver psycopg 3.

Como alternativa, copie `.env.example` para `.env` e defina `DATABASE_URL`. A ordem de preferência é:

1. `.streamlit/secrets.toml`
2. variável de ambiente / `.env`

Nunca versione `.env` ou `.streamlit/secrets.toml`; ambos estão no `.gitignore`.

## 3. Inicializar o banco

```bash
python -m database.init_db
```

O comando usa `CREATE TABLE IF NOT EXISTS` por meio do SQLAlchemy. Ele cria tabelas e índices ausentes e nunca apaga dados ou executa o seed de demonstração.

A aplicação também verifica as tabelas ao iniciar, portanto este passo pode ser omitido no primeiro teste.

## 4. Iniciar a aplicação

```bash
streamlit run app.py
```

Abra o endereço mostrado no terminal, normalmente `http://localhost:8501`. Para testar no celular na mesma rede, use o endereço de rede exibido pelo Streamlit e permita o acesso no firewall local apenas se desejar.

Na primeira execução, crie a primeira conta e informe o saldo atual. Cartões e renda são opcionais.

## Dados de demonstração

O seed nunca é executado automaticamente. Para liberar a ação manual em **Mais → Configurações → Dados**, defina:

```env
FINANCE_APP_ENV=development
```

A função `seed_demo_data()` é idempotente e marca as movimentações com `source="demo_seed"`.

## Testes

```bash
python -m pytest
```

A suíte cobre parsing BRL, parcelamento de cartão e empréstimo, competência/fechamento de fatura, saldo, transferências, recorrências, análises e previsão.

## Estrutura

```text
.
├── app.py                    # Bootstrap e roteador Streamlit
├── views/                    # Telas e fluxos de interface
├── components/               # Cards, gráficos, navegação e dialogs
├── styles/                   # CSS Liquid Glass e tema Plotly
├── database/
│   ├── connection.py         # Pool SQLAlchemy / Neon
│   ├── models.py             # Schema relacional
│   ├── repository.py         # CRUD e consultas eficientes
│   ├── init_db.py            # Criação não destrutiva
│   └── seed.py               # Categorias padrão e demo opcional
├── services/                 # Regras financeiras e casos de uso
├── utils/                    # Moeda, datas e helpers seguros
├── tests/                    # Testes das regras críticas
└── .streamlit/               # Tema e exemplo de secrets
```

## Modelo financeiro

- Dinheiro usa `NUMERIC(14,2)` no PostgreSQL e `Decimal` no Python.
- Datas de compra, competência, fechamento, vencimento e pagamento são separadas.
- Compra feita até o dia de fechamento pertence à fatura que fecha naquele ciclo; compra posterior vai para a próxima.
- Cada parcela vira apenas o seu valor mensal. A soma das parcelas sempre é igual ao total original.
- Compra em cartão não afeta a conta bancária; `pay_invoice()` cria a saída de caixa.
- Pagamento da fatura é excluído das despesas por competência para não duplicar gastos.
- O empréstimo recebido altera o saldo da conta, mas não é tratado como renda; cada
  parcela paga é uma despesa e reduz o saldo devedor no patrimônio líquido.
- Transferências possuem um grupo e duas pontas; não alteram receitas ou despesas gerais.
- Registros financeiros importantes usam `deleted_at` e podem ser restaurados futuramente.

## Segurança e desempenho

- Credenciais nunca ficam no código.
- SQLAlchemy gera consultas parametrizadas.
- Valores inseridos em HTML são escapados.
- CSVs neutralizam células que poderiam executar fórmulas.
- O engine usa pool com `pool_pre_ping`; histórico usa paginação e consultas agregadas.
- Erros técnicos ficam no terminal, enquanto a interface mostra mensagens curtas.

## Fora do escopo desta versão local

- Deploy e configuração de domínio
- Autenticação e interface multiusuário (o schema já possui `user_id`)
- Backup automático em serviço externo
- Importação de extratos OFX/CSV e conciliação bancária
- Exportação Excel nativa
- Temas Light e OLED
- Migrações versionadas para futuras alterações de schema
