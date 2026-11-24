# Integração com a API do Portal Científico do ISLA

## 1. Contrato Real do Endpoint

Confirmado diretamente na implementação atual do Portal Científico (`app/Http/Controllers/Api/PowerBiApiController.php` e `routes/api.php`):

- **Endpoint principal**: `GET /api/powerbi/publications` (alias: `GET /api/powerbi`)
- **Autenticação**: `Authorization: Bearer <TOKEN>` (também suporta `X-API-KEY`; nunca usar `?token=` em produção para evitar exposição em logs)
- **Cache de origem**: configurada por defeito para `1440` minutos (24 horas)
- **Atualização forçada**: `?nocache=1` (ou `?fresh=1`), reservada exclusivamente ao perfil `admin`

### Headers de Resposta Úteis para Versionamento

| Header | Uso no ISLA Institutional AI Agent |
| :--- | :--- |
| `X-PowerBI-Version` | Guardado em `source_snapshots.source_version` |
| `X-PowerBI-Records` | Validado face ao número de registos efetivamente ingeridos |
| `X-PowerBI-Cache-TTL-Minutes` | Guardado nos metadados do *snapshot* |

## 2. Estrutura do Payload e Particularidades Críticas

A API devolve um array JSON plano onde **cada elemento representa uma publicação única já deduplicada** entre perfis (por DOI limpo e título normalizado no backend do Portal), restringida aos autores com `include_in_powerbi = true`.

### Campos multivalor de coautoria

Os coautores institucionais são agregados numa única linha com delimitadores específicos (extraídos de `PowerBiApiController::buildPublicationsData`):

| Campo JSON | Delimitador | Observações |
| :--- | :--- | :--- |
| `authors` | `;` | Lista de Ciência Vitae IDs (ordenados pela ordem APA) |
| `Ciência ID` | `;#` | Lista de Ciência Vitae IDs no formato SharePoint/Power BI |
| `Email` | `;#` | Lista de emails institucionais (campo sensível) |
| `Nome` | `; ` | Lista de nomes completos |
| `Afiliação` | `; ` | Lista deduplicada de afiliações (pode ter cardinalidade inferior à dos autores) |
| `Escola` | `;#` | Lista deduplicada de escolas (pode ter cardinalidade inferior à dos autores) |

> **Nota de engenharia**: como `Afiliação` e `Escola` são deduplicadas no Portal (`array_unique`), o mapeamento autor-a-autor usa primariamente `Ciência ID` / `authors` e `Email` (alinhados pela ordem dos autores), recorrendo à tabela `researchers` (Excel da intranet) para atribuir com rigor a escola/grau/categoria de cada coautor.

### Mapeamento de Campos Bibliográficos

| Campo JSON da API | Coluna em `publications` | Notas |
| :--- | :--- | :--- |
| `ID` | `portal_id` | Chave natural externa (`external_reference_id` ou `id`) |
| `Title` | `title` | Título da publicação |
| `Ano` | `year` | Inteiro resolvido pelo Portal |
| `Tipo Publicação` | `pub_type` | Ex.: `Artigo em Jornal - SCOPUS/WOS(ISI)` |
| `Estado` | `status` | Ex.: `Publicado` |
| `DOI` / `DOI/URL` | `doi` / `doi_url` | DOI normalizado (`10.xxxx/...`) + URL |
| `Jornal` | `journal_name` | Nome da revista |
| `Conferência` | `conference_name` | Nome da conferência |
| `Fonte` / `Tipo Fonte` | `venue_name` / `venue_type` | Metadados OpenAlex/Crossref |
| `Editora` / `Livro` | `publisher` / `book_title` | Metadados editoriais |
| `Quartil` / `Classificação Jornal` | `quartile` | Normalizado para `Q1`–`Q4` quando aplicável |
| `Indexada Scopus` | `is_indexed_scopus` | Booleano |
| `Indexada WoS` | `is_indexed_wos` | Booleano |
| `Indexado` | `indexed_in` | String normalizada (`Scopus; WoS; ...`) |
| `Numero de Citações` | `citations_count` | Inteiro |
| `Referencias` | `references_count` | Inteiro |
| `Open Access` / `OA Status` / `OA URL` | `is_open_access` / `oa_status` / `oa_url` | Estado de acesso aberto |
| `Keywords` | `keywords` | Lista normalizada (JSON) |
| `APA` | `apa_citation` | Referência bibliográfica APA |
| `ISBN` / `ISSN` / `Handle` | `isbn` / `issn` / `handle` | Identificadores editoriais |
| `Scopus ID` / `WoS ID` / `OpenAlex ID` | `scopus_id` / `wos_id` / `openalex_id` | Identificadores de bases bibliométricas |
| `Observações` | `internal_notes` | **Campo restrito por RBAC** |
| `Valor` | `evaluation_score` | **Campo restrito por RBAC** |
| `Email` (dos autores) | `publication_authors.raw_email` | **Campo restrito por RBAC** |

## 3. Deteção de Alterações entre Sincronizações

Cada sincronização executada pelo `PortalSyncService`:

1. Calcula o *hash* SHA-256 canónico do payload recebido e o *hash* individual (`record_hash`) de cada publicação.
2. Compara com os registos ativos na tabela `publications`:
   - `records_created`: novos `portal_id`
   - `records_updated`: `portal_id` existentes cujo `record_hash` mudou
   - `records_unchanged`: `portal_id` sem alteração
   - `records_removed`: `portal_id` que deixaram de constar na resposta da API (marcados com `is_active = false`, preservando histórico)
3. Regista tudo em `source_snapshots` (incluindo `diff_summary` em JSON) e escreve entrada em `audit_logs`.
