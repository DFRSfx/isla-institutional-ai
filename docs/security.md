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

## 4. Gestão de Credenciais e Proteção de Inputs

- **Token da API do Portal Científico**: lido exclusivamente de variável de ambiente (`PORTAL_API_TOKEN`) no backend. Nunca é serializado em respostas HTTP, logs, estado do agente nem prompts de LLM.
- **Upload de Excel**:
  - Validação de extensão (`.xlsx`) e tamanho máximo (`MAX_EXCEL_UPLOAD_MB`).
  - Leitura segura com `openpyxl` (`data_only=True`, `read_only=True`), prevenindo avaliação arbitrária.
- **Proteção contra SQL Injection**: todas as queries usam ORM SQLAlchemy 2.0 / parâmetros ligados (*bound parameters*); o agente nunca executa SQL arbitrário escrito livremente pelo LLM.
- **Auditoria**: operações críticas (login, falha de acesso, sincronização da API, importação Excel, consultas restritas) são registadas em `audit_logs`.

## 5. Política de Desenvolvimento com LLM Externo

Enquanto não existir aprovação institucional formal do contrato de processamento/retenção de dados de um fornecedor LLM:
- O desenvolvimento e os testes funcionais decorrem com **dados de teste anonimizados/sintéticos**.
- Os dados enviados ao LLM são minimizados (apenas métricas agregadas ou registos estritamente necessários e autorizados para o utilizador autenticado).
