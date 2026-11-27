from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from app.agent.tools import (
    ToolContext,
    find_researcher,
    get_data_sources_status,
    get_scientific_production_report_data,
)
from app.services.report_generator import ReportGeneratorService
from app.services.semantic_search import EmbeddingClientError, search_publications_semantic

OPENAI_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_data_sources_status",
            "description": (
                "Consulta a versão, número de registos e data da última atualização das fontes "
                "de dados sincronizadas (API do Portal Científico e Excel de docentes)."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_researcher",
            "description": (
                "Pesquisa um docente por Ciência Vitae ID (ex. AAAA-1111-BBBB), email institucional "
                "ou nome. Respeita RBAC no backend. Correspondências apenas por nome devolvem "
                "hipóteses que exigem validação antes de gerar relatórios."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Ciência Vitae ID, email institucional ou nome a pesquisar.",
                    }
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_scientific_production_report_data",
            "description": (
                "Executa cálculos determinísticos cruzados entre Portal Científico e Excel de docentes "
                "(KPIs, evolução anual, quartis, Scopus/WoS, estado das publicações, docentes/estudantes "
                "mais produtivos, comparação entre dois anos e alertas de qualidade). "
                "Opcionalmente gera os ficheiros PDF e Excel prontos para download."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "school_code": {
                        "type": ["string", "null"],
                        "description": "Código da escola (ex.: 'EST' ou 'ESG'), ou null para âmbito institucional.",
                    },
                    "year_from": {
                        "type": ["integer", "null"],
                        "description": "Ano inicial do intervalo (inclusivo).",
                    },
                    "year_to": {
                        "type": ["integer", "null"],
                        "description": "Ano final do intervalo (inclusivo).",
                    },
                    "researcher_id": {
                        "type": ["string", "null"],
                        "description": (
                            "Identificador exato do docente: Ciência Vitae ID (ex.: C21A-91DC-B90B), "
                            "email institucional (ex.: nome@islagaia.pt) ou UUID interno "
                            "(apenas após correspondência exata, confirmação do utilizador ou próprio utilizador)."
                        ),
                    },
                    "compare_year_a": {
                        "type": ["integer", "null"],
                        "description": "Primeiro ano para comparação direta (ex.: 2024).",
                    },
                    "compare_year_b": {
                        "type": ["integer", "null"],
                        "description": "Segundo ano para comparação direta (ex.: 2025).",
                    },
                    "generate_reports": {
                        "type": "boolean",
                        "description": "Se true, gera imediatamente os relatórios PDF e Excel.",
                    },
                    "report_title": {
                        "type": ["string", "null"],
                        "description": "Título opcional para o relatório PDF/Excel.",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_publications_semantic",
            "description": (
                "Pesquisa semântica (RAG) por tema, tópico científico ou área de investigação "
                "nas publicações do ISLA (ex.: 'quem investiga inteligência artificial na educação', "
                "'artigos sobre cibersegurança', 'publicações sobre sustentabilidade'). "
                "Usar APENAS para descoberta temática; para contagens exatas, KPIs ou relatórios "
                "usar sempre `get_scientific_production_report_data`."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Tema, palavras-chave ou frase descritiva do assunto científico a pesquisar.",
                    },
                    "school_code": {
                        "type": ["string", "null"],
                        "description": "Filtro opcional por escola (ex.: 'EST' ou 'ESG').",
                    },
                    "year_from": {
                        "type": ["integer", "null"],
                        "description": "Ano inicial opcional (inclusivo).",
                    },
                    "year_to": {
                        "type": ["integer", "null"],
                        "description": "Ano final opcional (inclusivo).",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Número máximo de publicações semelhantes a devolver (1 a 15, padrão 8).",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
]


@dataclass
class ToolExecutionOutput:
    tool_name: str
    llm_payload: dict[str, Any]
    sources: list[dict[str, Any]]
    audit_meta: dict[str, Any]
    analytics_summary: dict[str, Any] | None = None
    report_bundle: dict[str, Any] | None = None


def execute_registered_tool(
    *,
    name: str,
    arguments: dict[str, Any],
    ctx: ToolContext,
    report_generator: ReportGeneratorService,
    reports_dir: Path | None = None,
    reference_year: int | None = None,
) -> ToolExecutionOutput:
    """
    Executa uma ferramenta registada respeitando RBAC e minimização de dados enviados ao LLM.
    """
    if name == "get_data_sources_status":
        res = get_data_sources_status(ctx)
        return ToolExecutionOutput(
            tool_name=name,
            llm_payload=res,
            sources=res["sources"],
            audit_meta={"tool": name, "result_count": len(res["sources"])},
        )

    if name == "find_researcher":
        query = str(arguments.get("query") or "")
        res = find_researcher(ctx, query)
        # Regra P0 de integridade: ocultar o UUID em hipóteses apenas por nome para
        # impedir fisicamente que um LLM pequeno avance para relatório sem validação.
        sanitized_hypotheses = [
            {k: v for k, v in h.items() if k != "id"}
            for h in res["hypotheses"]
        ]
        llm_res = {**res, "hypotheses": sanitized_hypotheses}
        return ToolExecutionOutput(
            tool_name=name,
            llm_payload=llm_res,
            sources=res["sources"],
            audit_meta={
                "tool": name,
                "query": query,
                "access_denied": res["access_denied"],
                "matches": len(res["matches"]),
                "hypotheses": len(res["hypotheses"]),
            },
        )

    if name == "get_scientific_production_report_data":
        school_code = arguments.get("school_code")
        year_from = arguments.get("year_from")
        year_to = arguments.get("year_to")
        raw_res_id = arguments.get("researcher_id")
        researcher_uuid: UUID | None = None
        if raw_res_id:
            raw_str = str(raw_res_id).strip()
            try:
                researcher_uuid = UUID(raw_str)
            except ValueError:
                lookup = find_researcher(ctx, raw_str)
                if lookup["access_denied"]:
                    return ToolExecutionOutput(
                        tool_name=name,
                        llm_payload={
                            "access_denied": True,
                            "reason": lookup.get("reason")
                            or "Sem permissão para consultar dados individuais de outros docentes.",
                            "sources": lookup.get("sources", []),
                        },
                        sources=lookup.get("sources", []),
                        audit_meta={"tool": name, "access_denied": True},
                    )
                if len(lookup["matches"]) == 1:
                    researcher_uuid = UUID(lookup["matches"][0]["id"])
                else:
                    return ToolExecutionOutput(
                        tool_name=name,
                        llm_payload={
                            "error": (
                                "Identificador do docente não confirmado ou não encontrado. "
                                "Use o Ciência Vitae ID ou email institucional exato do docente."
                            ),
                            "requires_confirmation": bool(lookup["hypotheses"]),
                            "hypotheses": [
                                {k: v for k, v in h.items() if k != "id"}
                                for h in lookup["hypotheses"]
                            ],
                        },
                        sources=lookup.get("sources", []),
                        audit_meta={"tool": name, "error": "unconfirmed_researcher_identifier"},
                    )

        cy_a = arguments.get("compare_year_a")
        cy_b = arguments.get("compare_year_b")
        compare_years = (
            (min(int(cy_a), int(cy_b)), max(int(cy_a), int(cy_b)))
            if cy_a is not None and cy_b is not None
            else None
        )

        data = get_scientific_production_report_data(
            ctx,
            school_code=str(school_code) if school_code else None,
            year_from=int(year_from) if year_from is not None else None,
            year_to=int(year_to) if year_to is not None else None,
            researcher_id=researcher_uuid,
            compare_years=compare_years,
            reference_year=reference_year,
        )

        if data.get("access_denied"):
            return ToolExecutionOutput(
                tool_name=name,
                llm_payload=data,
                sources=data.get("sources", []),
                audit_meta={"tool": name, "access_denied": True},
            )

        report_bundle: dict[str, Any] | None = None
        if bool(arguments.get("generate_reports")):
            title = str(arguments.get("report_title") or "").strip() or (
                f"Produção Científica da {data['scope']['school_code']}"
                if data["scope"].get("school_code")
                else "Produção Científica Institucional — ISLA"
            )
            report_bundle = report_generator.save_report_bundle(
                data,
                owner_id=ctx.user.id,
                title=title,
                output_dir=reports_dir,
            )

        analytics_summary = {
            "kpis": data["kpis"],
            "status_distribution": data["status_distribution"],
            "annual_evolution": data["annual_evolution"],
            "top_researchers": data["top_researchers"],
            "top_students": data["top_students"],
            "year_comparison": data["year_comparison"],
            "data_quality": data["data_quality"],
            "reproducibility_id": data["reproducibility_id"],
        }

        # Minimização e compactação para o LLM local: apenas métricas agregadas essenciais
        # (reduz drasticamente tokens de contexto, evita truncagem do prompt e acelera inferência;
        # os dados completos mantêm-se intactos em `analytics_summary`, PDF e Excel).
        compact_annual = [
            {
                "year": p.get("year"),
                "pubs": p.get("publications"),
                "indexed": p.get("indexed_scopus_or_wos"),
                "citations": p.get("citations"),
            }
            for p in data["annual_evolution"][-10:]
        ]
        compact_top_researchers = [
            {
                "name": r.get("name"),
                "school": r.get("school_code"),
                "pubs": r.get("publications"),
                "indexed": r.get("indexed_scopus_or_wos"),
                "q1": r.get("q1"),
            }
            for r in data["top_researchers"][:5]
        ]
        compact_top_students = [
            {
                "name": s.get("name"),
                "school": s.get("school_code"),
                "pubs": s.get("publications"),
            }
            for s in data["top_students"][:5]
        ]
        compact_sources = [
            {
                "label": s.get("label"),
                "version": s.get("version"),
                "records": s.get("record_count"),
                "synced_at": str(s.get("synced_at") or "")[:19],
            }
            for s in data["sources"]
        ]
        dq = data["data_quality"]
        compact_quality = {
            k: v
            for k, v in dq.items()
            if (isinstance(v, int) and v > 0) or (k == "notes" and v)
        }
        minimized_llm_payload = {
            "scope": data["scope"],
            "reproducibility_id": data["reproducibility_id"],
            "kpis": data["kpis"],
            "status_distribution": data["status_distribution"],
            "annual_evolution_recent": compact_annual,
            "quartile_distribution": data["quartile_distribution"],
            "top_researchers": compact_top_researchers,
            "top_students": compact_top_students,
            "year_comparison": data["year_comparison"],
            "data_quality": compact_quality,
            "sources": compact_sources,
            "report_generated": report_bundle is not None,
        }
        return ToolExecutionOutput(
            tool_name=name,
            llm_payload=minimized_llm_payload,
            sources=data["sources"],
            audit_meta={
                "tool": name,
                "scope": data["scope"],
                "reproducibility_id": data["reproducibility_id"],
                "report_generated": report_bundle is not None,
                "report_bundle": report_bundle,
            },
            analytics_summary=analytics_summary,
            report_bundle=report_bundle,
        )

    if name == "search_publications_semantic":
        query = str(arguments.get("query") or "").strip()
        if not query:
            return ToolExecutionOutput(
                tool_name=name,
                llm_payload={"error": "Parâmetro 'query' obrigatório para pesquisa semântica."},
                sources=[],
                audit_meta={"tool": name, "error": "empty_query"},
            )
        school_code = arguments.get("school_code")
        year_from = arguments.get("year_from")
        year_to = arguments.get("year_to")
        top_k = arguments.get("top_k", 8)
        try:
            res = search_publications_semantic(
                ctx,
                query,
                school_code=str(school_code) if school_code else None,
                year_from=int(year_from) if year_from is not None else None,
                year_to=int(year_to) if year_to is not None else None,
                top_k=int(top_k) if top_k is not None else 8,
            )
        except EmbeddingClientError as exc:
            return ToolExecutionOutput(
                tool_name=name,
                llm_payload={"error": str(exc)},
                sources=[],
                audit_meta={"tool": name, "error": "embedding_error"},
            )
        return ToolExecutionOutput(
            tool_name=name,
            llm_payload=res,
            sources=res.get("sources", []),
            audit_meta={
                "tool": name,
                "query": query,
                "matches": len(res.get("matches", [])),
            },
        )

    return ToolExecutionOutput(
        tool_name=name,
        llm_payload={"error": f"Ferramenta desconhecida: {name}"},
        sources=[],
        audit_meta={"tool": name, "error": "unknown_tool"},
    )
