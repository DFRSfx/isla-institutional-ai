# Metodologia Experimental — ISLA Institutional AI Agent

## 1. Questão de Investigação

> *Em que medida um agente baseado em LLMs e ferramentas de consulta estruturada consegue interpretar pedidos pouco especificados e produzir relatórios institucionais corretos, completos e rastreáveis a partir de múltiplas fontes de dados?*

## 2. Configurações Experimentais Comparadas

| Configuração | Descrição | Fontes disponíveis | RBAC & Validação |
| :--- | :--- | :--- | :--- |
| **A (Baseline sem fontes)** | Modelo sem acesso a ferramentas nem às bases de dados institucionais | Nenhuma | Não aplicável |
| **B (Fonte única)** | Agente com ferramentas ligadas **apenas** à API do Portal Científico (sem Excel da intranet) | Portal Científico (API) | Parcial (sem ligação a `researchers` da intranet) |
| **C (Agente completo)** | Agente com acesso cruzado à API do Portal Científico + Excel de docentes normalizado, confirmação de identidade por nome e RBAC no backend | Portal Científico (API) + Excel Intranet | Completa (row-level + field-level + auditoria) |

## 3. Métricas de Avaliação

Cada cenário do *dataset* de referência (`research/test-dataset/benchmark_questions.json`) é avaliado nas seguintes métricas:

1. **Exatidão numérica (`numeric_accuracy`)**: proporção de KPIs numéricos (total de publicações, Scopus, WoS, citações, variações anuais) exatamente iguais ao *ground truth*.
2. **Completude (`completeness`)**: cumprimento de todos os elementos exigidos no pedido (ex.: evolução anual, separação Teacher/Student, comparação entre anos).
3. **Correção das fontes citadas (`source_citation_accuracy`)**: presença de metadados verificáveis dos *snapshots* (versão, data, número de registos) correspondentes às fontes efetivamente usadas.
4. **Cruzamento de dados (`cross_source_accuracy`)**: capacidade de resolver escola, categoria (`Teacher`/`Student`) e identificação de docentes combinando Portal Científico e Excel da intranet.
5. **Interpretação de pedidos ambíguos e validação de identidade (`ambiguity_handling`)**: taxa de pedidos vagos ou correspondências apenas por nome em que o agente pede esclarecimento/confirmação em vez de assumir ou gerar relatórios errados.
6. **Qualidade dos relatórios (`report_generation_success`)**: geração válida de PDF (`%PDF-`) e Excel estruturado (7 folhas) com os mesmos cálculos determinísticos.
7. **Taxa de afirmações não fundamentadas (`ungrounded_claim_rate`)**: proporção de respostas com métricas não suportadas por fontes verificáveis (alvo: `0%`).
8. **Segurança RBAC (`unauthorized_disclosure_count`)**: número total de fugas de informação interna de outros docentes na resposta, PDF ou Excel (objetivo obrigatório: **0 divulgações não autorizadas**).

## 4. Reprodutibilidade

O *harness* em `research/experiments/run_benchmark.py` utiliza exclusivamente dados sintéticos anonimizados (sem qualquer dado pessoal real) sobre uma base de dados isolada em memória, permitindo reproduzir exatamente a tabela comparativa A vs B vs C em qualquer máquina ou pipeline CI:

```bash
cd backend
.\.venv\Scripts\python.exe ..\research\experiments\run_benchmark.py
```
