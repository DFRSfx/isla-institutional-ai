# Segurança, RBAC e Proteção de Dados

## 1. Princípio Base

> **Nenhuma decisão de autorização é delegada ao LLM.**
> Todas as restrições de acesso, filtragem de linhas (*row-level scoping*) e ocultação de campos sensíveis (*field-level redaction*) são aplicadas no backend FastAPI e nas consultas SQL antes de qualquer dado ser devolvido ao utilizador ou ao orquestrador de IA.

## 2. Matriz de Permissões (RBAC)

Implementada de forma centralizada em `backend/app/core/permissions.py`:

| Permissão | `admin` | `direction` | `faculty` (Docente) |
| :--- | :---: | :---: | :---: |
| `manage_users` | Sim | Não | Não |
| `import_excel` | Sim | Não | Não |
| `sync_portal_api` | Sim | Não | Não |
| `sync_portal_api_force_nocache` | Sim | Não | Não |
| `view_institutional_publications` | Sim | Sim | Sim |
| `view_global_indicators` | Sim | Sim | Limitado |
| `view_all_researchers_internal` | Sim | Sim | Não |
| `view_own_researcher_data` | Sim | Sim | Sim |
| `generate_pdf_report` | Sim | Sim | Sim |
| `generate_excel_report` | Sim | Sim | Sim |
| `view_audit_logs` | Sim | Limitado | Não |

## 3. Filtragem de Dados e Campos Sensíveis

### Nível de registo (*Row-level*)
- **`admin` e `direction`**: podem consultar todos os registos de `researchers` e `publications`.
- **`faculty`**:
  - Na tabela `researchers`, só pode aceder ao **próprio registo** (`researcher.id == user.researcher_id`). Tentativas de consulta de outro docente por ID devolvem `403 Forbidden` (e ficam registadas em `audit_logs`).
  - Na tabela `publications`, pode consultar publicações institucionais públicas/bibliográficas e as suas próprias publicações.

### Nível de campo (*Field-level*)
Mesmo quando um docente consulta publicações institucionais, os seguintes campos são **removidos no backend** para o perfil `faculty`:
- `publications.internal_notes` (`Observações` internas do Portal)
- `publications.evaluation_score` (`Valor` / pontuação de avaliação)
- `publication_authors.raw_email` (emails de outros coautores)

## 4. Autenticação Institucional e Gestão de Credenciais

- **API de Autenticação Institucional (`https://auth.dariosoares.dev/v1/token`)**:
  - Chamada exclusivamente *server-to-server* pelo backend FastAPI (`backend/app/services/institutional_auth.py`), enviando `X-API-Key` e `Origin` configurados via variáveis de ambiente (`INSTITUTIONAL_AUTH_API_KEY`, `INSTITUTIONAL_AUTH_ORIGIN`). O token da app nunca é exposto ao browser.
  - Suporta três modos (`AUTH_MODE`): `hybrid` (tenta LDAP institucional e permite fallback para contas locais), `institutional` (exclusivamente LDAP) e `local`.
  - **Provisionamento JIT e ligação automática ao docente**: no primeiro login LDAP válido, o utilizador é criado/atualizado localmente por `email`, preserva promoções locais de perfil (ex.: docente promovido a `direction`), e é ligado automaticamente ao seu registo em `researchers` via `email`.
  - **Mapeamento de perfis**: aceita apenas perfis expressamente autorizados (`admin -> admin`, `direction -> direction`, `teacher -> faculty`). Perfis desconhecidos, vazios ou `student` são recusados com `403 Forbidden`.
  - **Modo estrito (`AUTH_MODE=institutional`)**: se `INSTITUTIONAL_AUTH_API_KEY` não estiver configurada, devolve `503 Service Unavailable` e nunca recorre ao login local.
- **Armazenamento de sessão no frontend**: no MVP de desenvolvimento, o JWT é guardado em `sessionStorage` (limpo ao fechar a sessão do browser); antes de disponibilização em produção sobre HTTPS, deverá migrar para *cookies* `HttpOnly; Secure; SameSite=Lax`.
- **Token da API do Portal Científico**: lido exclusivamente de variável de ambiente (`PORTAL_API_TOKEN`) no backend. Nunca é serializado em respostas HTTP, logs, estado do agente nem prompts de LLM.
- **Upload de Excel**:
  - Validação de extensão (`.xlsx`) e tamanho máximo (`MAX_EXCEL_UPLOAD_MB`).
  - Leitura segura com `openpyxl` (`data_only=True`, `read_only=True`), prevenindo avaliação arbitrária.
- **Proteção contra SQL Injection**: todas as queries usam ORM SQLAlchemy 2.0 / parâmetros ligados (*bound parameters*); o agente nunca executa SQL arbitrário escrito livremente pelo LLM.
- **Auditoria**: operações críticas (login, falha de acesso, sincronização da API, importação Excel, consultas restritas) são registadas em `audit_logs`.

## 5. Soberania de Dados, RGPD e NIS2 (LLM Local / On-Premise)

Por requisitos de proteção de dados (**RGPD**) e cibersegurança institucional (**Diretiva NIS2**), a arquitetura privilegia execução de **LLM local / on-premise** (ex.: Ollama ou vLLM na infraestrutura interna do ISLA), evitando transferências de dados institucionais para serviços cloud externos:

- **Bloqueio técnico por defeito (`LLM_ALLOW_EXTERNAL_ENDPOINTS=false`)**: `Settings` valida `LLM_BASE_URL` no arranque e recusa qualquer endereço externo/público, aceitando apenas `localhost`, serviços internos Docker (`ollama`, `vllm`) ou endereços privados LAN (RFC-1918).
- **Minimização de dados ao LLM**: mesmo com LLM local, o `tool_registry.py` envia apenas métricas agregadas e metadados autorizados para o perfil do utilizador autenticado (nunca dumps brutos da base de dados nem credenciais).
- **Modelos locais recomendados com suporte a *tool calling* e português**: `qwen2.5:7b-instruct`, `qwen2.5:14b-instruct` ou `llama3.1:8b` via `docker compose --profile local-llm up -d`.
