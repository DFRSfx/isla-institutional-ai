# Dicionário de Dados e Análise do Excel da Intranet

## 1. Análise do Ficheiro de Referência (`ISLA GAIA - Investigadores.xlsx`)

Inspeção estrutural realizada sobre o ficheiro real disponível no ambiente de trabalho (sem exposição de dados pessoais):

| Métrica | Valor observado | Notas |
| :--- | :--- | :--- |
| Folhas existentes | 1 (`Docentes`) | Deteção automática suportada para múltiplas folhas |
| Registos totais | 121 | 101 `Teacher` + 20 `Student` (nota: versão mais recente do que os 99 docentes referidos inicialmente) |
| Registos com `CienciaVitae` | 88 (87 distintos) | 1 identificador Ciência Vitae duplicado |
| Registos com `CienciaVitae2` | 82 (81 distintos) | 80 iguais a `CienciaVitae`, 2 divergentes, 1 com parêntese final malformado (`XXXX-XXXX-XXXX)`) |
| Registos com `Google scholar` | 31 (30 distintos) | 1 duplicado |
| Registos com `Scopus` | 18 (17 distintos) | IDs numéricos de 11 dígitos; 1 duplicado |
| Registos com `Web of Science` | 33 (32 distintos) | ResearcherIDs (`AAA-0000-YYYY`); 1 duplicado |
| Escolas (`Escola`) | `ESG` (63), `EST` (58) | 100% preenchido |

## 2. Mapeamento das Colunas do Excel

| Coluna original | Coluna normalizada (`researchers`) | Tipo | Observações e Regras de Normalização |
| :--- | :--- | :--- | :--- |
| `CienciaVitae` | `ciencia_vitae_id` | `str \| null` | Validar padrão `^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$` em maiúsculas |
| `CienciaVitae2` | `ciencia_vitae_id_secondary` | `str \| null` | Usado como fallback apenas se `CienciaVitae` estiver vazio; divergências e caracteres inválidos (ex. `)`) geram *warning* explícito |
| `Docente` | `name` | `str` | Trim + normalização de espaços; `normalized_name` guardado em paralelo para pesquisa |
| `Email` | `email` | `str` | Minúsculas + trim; **campo restrito por RBAC** |
| `Acivo` *(erro de escrita na origem)* | `status_code` | `str \| null` | Aceita aliases `Acivo`, `Ativo`, `Estado`; guarda código bruto sem assumir significado |
| `Grau` | `degree_code` | `str \| null` | Guarda código bruto sem assumir significado |
| `Escola` | `school_id` (`schools.code`) | `FK -> schools` | Normalizado em maiúsculas (`EST`, `ESG`, ...) |
| `Afiliação` | `affiliation` | `str \| null` | Centro/unidade de investigação |
| `Área Formação` | `training_area` | `str \| null` | Área científica/formação |
| `Google scholar` | `google_scholar_id` | `str \| null` | ID do perfil Scholar |
| `scholar h-index` | `scholar_h_index` | `int \| null` | Convertido para inteiro quando numérico |
| `Scopus` | `scopus_author_id` | `str \| null` | ID de autor Scopus (string para preservar zeros/comprimento) |
| `scopus h-index` | `scopus_h_index` | `int \| null` | Convertido para inteiro quando numérico |
| `Web of Science` | `wos_researcher_id` | `str \| null` | ResearcherID WoS |
| `WoS h-index` | `wos_h_index` | `int \| null` | Convertido para inteiro quando numérico |
| `Categoria` | `category` | `str \| null` | Ex.: `Teacher`, `Student` |

## 3. Códigos por Confirmar com a Instituição (Não Assumidos no Código)

Conforme requisito explícito da especificação, **o sistema não traduz automaticamente** códigos cujo significado institucional não foi formalmente validado.

### Coluna `Acivo` (`status_code`)

| Código encontrado | Frequência | Significado confirmado | Estado |
| :--- | :--- | :--- | :--- |
| `Y` | 84 | *Por confirmar com o ISLA* | Pendente |
| `A` | 10 | *Por confirmar com o ISLA* | Pendente |
| `N` | 8 | *Por confirmar com o ISLA* | Pendente |
| `O` | 2 | *Por confirmar com o ISLA* | Pendente |
| *(vazio)* | 17 | *Por confirmar com o ISLA* | Pendente |

### Coluna `Grau` (`degree_code`)

| Código encontrado | Frequência | Significado confirmado | Estado |
| :--- | :--- | :--- | :--- |
| `D` | 47 | *Por confirmar com o ISLA* (hipótese frequente: Doutoramento) | Pendente |
| `M` | 41 | *Por confirmar com o ISLA* (hipótese frequente: Mestrado) | Pendente |
| `L` | 32 | *Por confirmar com o ISLA* (hipótese frequente: Licenciatura) | Pendente |
| `N` | 1 | *Por confirmar com o ISLA* | Pendente |

Quando o ISLA confirmar este dicionário, os significados oficiais deverão ser registados numa tabela/ficheiro de configuração versionado, mantendo sempre o código original preservado na base de dados.

## 4. Inconsistências Tratadas na Importação

O `ExcelImportService` executa validação em duas fases (**pré-visualização** sem escrita e **importação** transacional) e reporta estruturadamente:

- Duas colunas de Ciência Vitae (`CienciaVitae` vs `CienciaVitae2`) com sinalização de divergências entre ambas.
- Identificadores Ciência Vitae malformados (ex.: pontuação extra como `)`), distinguindo valor bruto vs valor sanitizado candidato.
- Identificadores duplicados dentro do mesmo ficheiro (`ciencia_vitae_id`, `email`, `google_scholar_id`, `scopus_author_id`, `wos_researcher_id`).
- Erros de nomenclatura de cabeçalhos conhecidos (`Acivo` -> `status_code`).
- Histórico completo em `excel_imports` (nome do ficheiro, SHA-256, folhas, total de linhas, criados, atualizados, avisos e erros).

## 5. Regras de Negócio e Qualidade Estatística

1. **Separação por categoria (`Teacher` vs `Student`)**:
   - Todos os registos do Excel (docentes e estudantes) são mantidos em `researchers` para assegurar o cruzamento completo de coautorias institucionais.
   - Nas análises e relatórios, o ranking de **Docentes Mais Produtivos** (`top_researchers`) inclui exclusivamente registos de categoria `Teacher` (não estudantes); a produção de estudantes (`Student`) é apresentada numa tabela separada (`top_students`).
2. **Ano editorial futuro (ex.: `2027` com data de referência `2026`)**:
   - Registos com ano posterior ao ano de referência não são rejeitados automaticamente (podem representar publicações com ano editorial futuro), mas são contabilizados em `data_quality.future_year_publications_count` e explicitados na secção de metodologia e limitações dos relatórios.
3. **Estado da publicação (`Estado`)**:
   - As métricas incluem a distribuição por estado (`status_distribution`, ex.: `Publicado`, `Aceite`, `Submetido`) e contagens separadas (`published_count` vs `non_published_count`). A regra final sobre inclusão de estados não publicados nos indicadores principais aguarda validação institucional com o ISLA.
4. **Notas pendentes de confirmação institucional**:
   - Confirmar qual a versão oficial atual do ficheiro da intranet (versão de 121 registos vs versão anterior de 99 registos).
   - Confirmar se o perfil `direction` deve manter acesso a campos sensíveis (`Email`, `Observações`, `Valor`).
