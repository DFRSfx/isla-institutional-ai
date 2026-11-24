# ISLA Institutional AI Agent (MVP v1.0)

Agente de Inteligência Artificial institucional para consultar, cruzar, analisar e exportar informação científica e dados de docentes do ISLA, através de linguagem natural com rastreabilidade, validação determinística (SQL/Python) e controlo de acessos RBAC no backend.

## Estado atual (Fase 2 — Backend MVP funcional)

- [x] Estrutura modular do repositório (`backend/`, `frontend/`, `research/`, `docs/`)
- [x] Documentação de arquitetura, integração da API, dicionário de dados e segurança
- [x] Modelo de dados relacional (SQLAlchemy 2.0 + migrações Alembic)
- [x] Cliente e sincronização da API do Portal Científico (`GET /api/powerbi/publications`) com *snapshots* e deteção de alterações (*diff*)
- [x] Serviço de importação, pré-visualização, validação e normalização de ficheiros Excel de docentes
- [x] Camada de autenticação, RBAC, auditoria e filtragem de campos sensíveis no backend
- [x] Ferramentas analíticas determinísticas (SQL/Python) com cruzamento API × Excel e `reproducibility_id`
- [x] Orquestrador conversacional do agente com esclarecimento de pedidos ambíguos e memória contextual entre mensagens
- [x] Geração e download RBAC de relatórios PDF (ReportLab com gráficos e tabelas) e Excel (OpenPyXL com 6 folhas)
- [x] Frontend React + TypeScript + Tailwind + shadcn (`v0-ai-chat`, histórico, relatórios e administração)
- [ ] Integração de fornecedor LLM externo / LangGraph (após aprovação institucional)
- [ ] Avaliação experimental (Configurações A / B / C)

## Estrutura do repositório

```text
isla-institutional-ai/
├── backend/                # API FastAPI, modelos SQLAlchemy, migrações Alembic, serviços e testes
│   ├── app/
│   │   ├── api/            # Endpoints HTTP (auth, sync, imports, researchers, publications)
│   │   ├── core/           # Configuração, segurança, RBAC e permissões
│   │   ├── database/       # Engine, sessões e Base ORM
│   │   ├── models/         # Entidades relacionais (10 tabelas)
│   │   ├── schemas/        # Contratos Pydantic v2
│   │   ├── services/       # portal_api, excel_import, data_normalization, report_generator
│   │   ├── agent/          # Esqueleto LangGraph (state, prompts, graph, tools)
│   │   └── main.py
│   ├── migrations/         # Migrações Alembic
│   └── tests/              # Testes automatizados (pytest)
├── frontend/               # Aplicação React + TypeScript (fase seguinte)
├── research/               # Revisão bibliográfica, metodologia, dataset de teste e experiências
├── docs/                   # Documentação técnica
│   ├── architecture.md
│   ├── api-integration.md
│   ├── data-dictionary.md
│   └── security.md
├── docker-compose.yml      # PostgreSQL 16 + serviço backend
└── .env.example
```

## Arranque rápido (desenvolvimento local)

### 1. Configurar variáveis de ambiente

```bash
cp .env.example .env
```

Preencher `PORTAL_API_BASE_URL` e `PORTAL_API_TOKEN` com as credenciais do Portal Científico (nunca expor no frontend nem enviar ao LLM).

### 2. Iniciar PostgreSQL com Docker (opcional para dev; os testes correm também com SQLite em memória)

```bash
docker compose up -d db
```

### 3. Configurar ambiente Python e executar migrações

```bash
cd backend
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

alembic upgrade head
uvicorn app.main:app --reload
```

### 4. Executar testes

```bash
cd backend
pytest
```

## Documentação

- [Arquitetura Técnica](docs/architecture.md)
- [Integração com a API do Portal Científico](docs/api-integration.md)
- [Dicionário de Dados e Normalização](docs/data-dictionary.md)
- [Segurança, RBAC e Proteção de Dados](docs/security.md)
