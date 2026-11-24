# Arquitetura Técnica — ISLA Institutional AI Agent (MVP v1.0)

## 1. Princípios Arquiteturais

1. **Separação estrita entre raciocínio (LLM) e computação (SQL/Python)**: o LLM interpreta pedidos em linguagem natural, planeia chamadas a ferramentas e redige respostas fundamentadas. Todos os cálculos, agregações e cruzamentos são executados de forma determinística no backend sobre dados estruturados em PostgreSQL.
2. **Sem dependência de Power BI Pro e sem base vetorial no MVP**: os dados iniciais (Portal Científico + Excel de docentes) são estruturados. RAG/vetores ficam reservados para a evolução P2 (documentos PDF/Word).
3. **Segurança aplicada antes do LLM**: autenticação, RBAC e filtragem por docente/campos sensíveis ocorrem exclusivamente no backend e nas queries SQL, nunca delegadas a instruções de prompt.
4. **Reprodutibilidade e rastreabilidade**: cada sincronização da API e cada importação de Excel gera um registo versionado (`source_snapshots` e `excel_imports`), permitindo reproduzir relatórios e citar exatamente as versões e datas das fontes.

## 2. Diagrama de Arquitetura

```mermaid
flowchart TD
    FE["Frontend (React + TypeScript)\nChat · Histórico · Relatórios · Administração"] --> API["Backend API (Python + FastAPI)\nAutenticação · RBAC · Validação"]

    API --> ORCH["AI Orchestration Layer (LangGraph)\nInterpretação · Planeamento · Tool Calling"]
    API --> SYNC["Data Ingestion Services\nportal_api.py · excel_import.py · data_normalization.py"]
    API --> REP["Report Generator\nReportLab (PDF) · OpenPyXL (Excel)"]

    ORCH --> T1["Portal Query Tool"]
    ORCH --> T2["Researcher / Excel Query Tool"]
    ORCH --> T3["Validated SQL Analytics Tool"]
    ORCH --> T4["Report Generator Tool"]

    T1 --> DB[("PostgreSQL\nDados normalizados + Snapshots + Auditoria")]
    T2 --> DB
    T3 --> DB
    SYNC --> DB
    REP --> DB

    SYNC --> PORTAL["Portal Científico ISLA\nGET /api/powerbi/publications"]
    SYNC --> XLSX["Excel Intranet\nImportação manual (.xlsx)"]
```

## 3. Fluxo de Execução do Agente

```mermaid
flowchart LR
    U["Pedido em linguagem natural"] --> AUTH["Identificar utilizador e RBAC"]
    AUTH --> INT["Interpretar intenção e criar plano"]
    INT --> CLR{"Pedido claro?"}
    CLR -- "Não" --> ASK["Solicitar esclarecimento"]
    CLR -- "Sim" --> TOOLS["Executar ferramentas autorizadas\n(SQL/Python sobre PostgreSQL)"]
    TOOLS --> VAL["Validar integridade, fontes e lacunas"]
    VAL --> ANS["Gerar resposta fundamentada\n+ citações de fontes"]
    ANS --> EXP["Opcional: Exportar PDF / Excel"]
```

## 4. Modelo de Dados Relacional

```mermaid
erDiagram
    USERS {
        uuid id PK
        string email UK
        string role
        uuid researcher_id FK
        boolean is_active
    }
    SCHOOLS {
        uuid id PK
        string code UK
        string name
    }
    RESEARCHERS {
        uuid id PK
        string ciencia_vitae_id
        string email
        string name
        uuid school_id FK
        string degree_code
        string status_code
        string category
    }
    PUBLICATIONS {
        uuid id PK
        string portal_id UK
        string doi
        string title
        int year
        string pub_type
        string quartile
        int citations_count
        boolean is_indexed_scopus
        boolean is_indexed_wos
    }
    PUBLICATION_AUTHORS {
        uuid id PK
        uuid publication_id FK
        uuid researcher_id FK
        int author_order
        string match_method
        string match_confidence
    }
    SOURCE_SNAPSHOTS {
        uuid id PK
        string source_type
        string source_version
        string content_hash
        datetime synced_at
    }
    EXCEL_IMPORTS {
        uuid id PK
        string filename
        string file_sha256
        int total_rows
        uuid imported_by FK
        datetime imported_at
    }
    CONVERSATIONS {
        uuid id PK
        uuid user_id FK
        string title
    }
    MESSAGES {
        uuid id PK
        uuid conversation_id FK
        string role
        text content
    }
    AUDIT_LOGS {
        uuid id PK
        uuid user_id FK
        string action
        string resource_type
    }

    SCHOOLS ||--o{ RESEARCHERS : "enquadra"
    RESEARCHERS ||--o{ PUBLICATION_AUTHORS : "participa"
    PUBLICATIONS ||--o{ PUBLICATION_AUTHORS : "inclui"
    USERS ||--o{ EXCEL_IMPORTS : "importa"
    USERS ||--o{ CONVERSATIONS : "cria"
    CONVERSATIONS ||--o{ MESSAGES : "contém"
    USERS ||--o{ AUDIT_LOGS : "regista"
    RESEARCHERS ||--o| USERS : "associa"
```

## 5. Estratégia de Correspondência de Docentes (Entity Resolution)

A ligação entre publicações do Portal Científico e docentes da intranet segue uma hierarquia determinística (sem associação definitiva baseada apenas em nome):

1. **Prioridade 1 — `ciencia_vitae_id` normalizado** (`XXXX-XXXX-XXXX`, maiúsculas): associação automática com confiança `exact` (`match_method = "ciencia_vitae_id"`).
2. **Prioridade 2 — `email` institucional normalizado** (minúsculas, sem espaços): associação automática com confiança `exact` (`match_method = "institutional_email"`).
3. **Prioridade 3 — Nome normalizado**: **nunca** cria associação definitiva automática. Fica marcada como `match_method = "name_hypothesis"` com `match_confidence = "needs_validation"` para revisão administrativa ou sinalização explícita de incerteza nos relatórios.
4. **Sem correspondência na intranet**: o registo em `publication_authors` preserva os dados brutos do autor vindos do Portal (`raw_ciencia_vitae_id`, `raw_name`, `raw_email`, `raw_school`) com `researcher_id = NULL` e `match_method = "unmatched"`, garantindo que nenhuma publicação se perde nos indicadores globais.

## 6. Fases de Entrega

| Fase | Data alvo | Foco técnico |
| :--- | :--- | :--- |
| Fase 1 — Proposta científica | 15 dezembro 2026 | Problema, revisão bibliográfica, arquitetura, fontes, metodologia e plano |
| Fase 2 — Protótipo funcional | 5 janeiro 2027 | API integrada, importação Excel, BD normalizada, primeiras ferramentas e UI inicial |
| Fase final — MVP | 14 janeiro 2027 | Agente completo, cruzamento, RBAC, PDF/Excel, avaliação experimental (A/B/C) |
