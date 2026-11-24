# Revisão Bibliográfica Inicial — Agentes LLM sobre Dados Institucionais Estruturados

> Documento de base para a **Fase 1 — Proposta Científica (15 dezembro 2026)** do projeto *ISLA Institutional AI Agent*.

## 1. Enquadramento Temático

A literatura recente sobre Inteligência Artificial aplicada a sistemas de informação organizacionais divide-se em cinco eixos diretamente relevantes para o problema de investigação do ISLA:

1. **Agentes LLM aumentados por ferramentas (*Tool-Augmented LLMs*)**
2. **Consulta estruturada (*Structured Tool Calling*) versus RAG vetorial**
3. **Mitigação de alucinações, fundamentação (*Grounding*) e pedidos ambíguos**
4. **Resolução de entidades (*Entity Resolution*) em bibliometria científica**
5. **Privacidade, RBAC, RGPD e NIS2 com LLMs locais (*On-Premise*)**

---

## 2. Eixos da Literatura

### 2.1. Agentes LLM com *Tool Calling* e Orquestração com Estado
A capacidade de um *Large Language Model* (LLM) intercalar raciocínio em linguagem natural com chamadas a ferramentas externas foi formalizada por abordagens como **ReAct** (Yao et al., 2023) e **Toolformer** (Schick et al., 2023). Ao separar o planeamento semântico da execução determinística de funções, estes sistemas superam limitações clássicas dos modelos puramente paramétricos — nomeadamente conhecimento desatualizado, incapacidade de executar aritmética fiável em grande escala e ausência de acesso a bases de dados privadas.

Em sistemas empresariais, arquiteturas com grafos de estado (como o paradigma LangGraph) permitem controlar ciclos limitados de invocação de ferramentas, gerir memória contextual entre turnos e impor pontos explícitos de clarificação antes de executar operações custosas ou irreversíveis.

### 2.2. Consulta Estruturada vs. RAG Vetorial
A arquitetura *Retrieval-Augmented Generation* (**RAG**, Lewis et al., 2020) demonstrou elevada eficácia na recuperação de passagens textuais não estruturadas através de *embeddings* e bases vetoriais. Contudo, a investigação sobre dados tabulares e *Business Intelligence* conversacional evidencia que o RAG vetorial clássico apresenta limitações severas em:
- **Agregações exatas** (contagens, somas, médias, percentagens, evoluções anuais e rankings);
- **Junções relacionais multi-fonte** (ex.: cruzar publicações bibliográficas com atributos internos de docentes);
- **Controlo de acesso granular (*row-level* e *field-level* RBAC)**.

Por esta razão, trabalhos recentes distinguem **RAG não estruturado** (para documentos PDF/Word) de **acesso estruturado via ferramentas parametrizadas / SQL validado**, recomendando que o LLM nunca execute cálculos numéricos críticos por si próprio nem receba *dumps* completos das bases de dados.

### 2.3. Fundamentação, Rastreabilidade e Pedidos Ambíguos
Um dos principais obstáculos à adoção de agentes LLM em contexto institucional é a taxa de afirmações não fundamentadas (*hallucinations*). A literatura aponta três mecanismos complementares de mitigação:
1. **Computação determinística isolada**: todos os indicadores são calculados por SQL/Python e injetados como factos estruturados.
2. **Proveniência explícita (*Data Lineage*)**: associação de cada resposta e relatório às versões, *hashes* e datas de atualização das fontes (*snapshots*).
3. **Deteção de ambiguidade (*Clarification-first*)**: quando um pedido é subespecificado (ex.: sem âmbito temporal ou organizacional) ou quando existe ambiguidade de identidade (ex.: pesquisa apenas por nome), o agente deve solicitar esclarecimento antes de produzir conclusões.

### 2.4. Resolução de Entidades em Bibliometria Científica
A integração entre sistemas bibliográficos (Scopus, Web of Science, OpenAlex, Ciência Vitae) e diretórios institucionais sofre historicamente do problema de desambiguação de autores (*Author Name Disambiguation*). Boas práticas internacionais (ORCID, Ciência Vitae) recomendam hierarquias determinísticas ancoradas em identificadores persistentes e únicos (Ciência Vitae ID, DOI, email institucional), tratando correspondências exclusivamente nominais como hipóteses sujeitas a validação humana (*human-in-the-loop*).

### 2.5. Governança, RBAC, RGPD e Diretiva NIS2
No espaço europeu, o processamento de dados pessoais e institucionais de docentes por agentes de IA está sujeito ao **RGPD** (minimização de dados, limitação da conservação, controlo de transferências internacionais) e aos requisitos de gestão de risco e segurança da cadeia de abastecimento da **Diretiva NIS2**.

A literatura de segurança em sistemas agênticos destaca duas regras críticas:
- **Autorização fora do modelo**: políticas RBAC nunca podem depender de instruções no *prompt* (suscetíveis a *prompt injection*); têm de ser aplicadas no backend e nas queries à base de dados antes de o modelo observar os dados.
- **Soberania de dados (*On-Premise LLMs*)**: a execução de modelos abertos locais com suporte a *tool calling* (ex.: família Qwen 2.5 / Llama 3.1 via Ollama ou vLLM na rede interna) elimina transferências para fornecedores *cloud* externos e permite auditoria total.

---

## 3. Síntese Comparativa e Posicionamento do Projeto

| Abordagem | Exatidão Numérica | Cruzamento Multi-fonte | Controlo RBAC Rigoroso | Soberania RGPD/NIS2 |
| :--- | :---: | :---: | :---: | :---: |
| LLM isolado (Configuração A) | Baixa | Não | Não aplicável | Depende do alojamento |
| RAG vetorial sobre texto/PDF | Média/Baixa | Limitado | Complexo | Depende do alojamento |
| Agente com 1 fonte (Configuração B) | Alta (1 fonte) | Não | Parcial | Alta (se local) |
| **ISLA Institutional AI Agent (Configuração C)** | **Exata (SQL/Python)** | **Sim (API + Excel)** | **Backend + BD (0 fugas)** | **Alta (LLM local por defeito)** |

---

## 4. Referências Base a Consolidar na Versão Final

- Lewis, P., et al. (2020). *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*. NeurIPS.
- Schick, T., et al. (2023). *Toolformer: Language Models Can Teach Themselves to Use Tools*. NeurIPS.
- Yao, S., et al. (2023). *ReAct: Synergizing Reasoning and Acting in Language Models*. ICLR.
- Regulamento (UE) 2016/679 (**RGPD**) — Proteção das pessoas singulares no que diz respeito ao tratamento de dados pessoais.
- Diretiva (UE) 2022/2555 (**NIS2**) — Medidas destinadas a garantir um elevado nível comum de cibersegurança na União.
