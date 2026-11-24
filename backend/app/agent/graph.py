import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.llm_client import LLMClientError, OpenAICompatibleLLMClient
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.state import AgentPlan, AgentTurnResult
from app.agent.tool_registry import OPENAI_TOOL_SCHEMAS, execute_registered_tool
from app.agent.tools import (
    ToolContext,
    find_researcher,
    get_data_sources_status,
    get_scientific_production_report_data,
)
from app.core.config import get_settings
from app.models.conversation import Conversation, Message
from app.models.user import User
from app.services.audit import record_audit_log
from app.services.data_normalization import normalize_text
from app.services.report_generator import ReportGeneratorService

PT_NUMBER_WORDS: dict[str, int] = {
    "dois": 2,
    "duas": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
    "dez": 10,
}

CV_PATTERN = re.compile(r"\b[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}\b", re.IGNORECASE)
EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")
SCHOOL_PATTERN = re.compile(r"\b(EST|ESG)\b", re.IGNORECASE)


def _extract_last_scope(messages: list[Message]) -> dict[str, Any]:
    for msg in reversed(messages):
        if msg.role == "assistant" and msg.tool_calls_json:
            for call in reversed(msg.tool_calls_json):
                if isinstance(call, dict) and isinstance(call.get("scope"), dict):
                    return call["scope"]
    return {}


def _extract_timeframe(
    norm_text: str,
    *,
    reference_year: int,
) -> tuple[int | None, int | None, tuple[int, int] | None]:
    # 1. Comparação explícita entre dois anos (ex.: "comparação entre 2024 e 2025")
    comp_match = re.search(
        r"(?:compara\w*|entre|vs\.?|versus)\s*(?:entre\s+)?(20\d{2})\s*(?:e|com|vs\.?|versus|-)\s*(20\d{2})",
        norm_text,
    )
    compare_years: tuple[int, int] | None = None
    if comp_match:
        y1, y2 = int(comp_match.group(1)), int(comp_match.group(2))
        compare_years = (min(y1, y2), max(y1, y2))

    # 2. Intervalo relativo ("últimos cinco anos", "últimos 5 anos")
    rel_match = re.search(
        r"ultimos?\s+(\d+|dois|duas|tres|quatro|cinco|seis|sete|oito|nove|dez)\s+anos?",
        norm_text,
    )
    if rel_match:
        token = rel_match.group(1)
        span = int(token) if token.isdigit() else PT_NUMBER_WORDS[token]
        return reference_year - span + 1, reference_year, compare_years

    # 3. Intervalo explícito ("de 2021 a 2025", "2021-2025")
    range_match = re.search(r"(?:de\s+)?(20\d{2})\s*(?:a|ate|-|–)\s*(20\d{2})", norm_text)
    if range_match and not comp_match:
        y1, y2 = int(range_match.group(1)), int(range_match.group(2))
        return min(y1, y2), max(y1, y2), compare_years

    # 4. "desde 2022"
    since_match = re.search(r"desde\s+(20\d{2})", norm_text)
    if since_match:
        return int(since_match.group(1)), reference_year, compare_years

    # 5. Ano único mencionado (fora de uma comparação)
    if not compare_years:
        years = [int(y) for y in YEAR_PATTERN.findall(norm_text)]
        if len(years) == 1:
            return years[0], years[0], None

    return None, None, compare_years


def _extract_researcher_name_hint(raw_text: str) -> str | None:
    patterns = [
        r"(?:docente|investigador(?:a)?|professor(?:a)?)\s+([A-ZÀ-Ú][a-zà-ú]+(?:\s+(?:da|de|do|dos|das|e|[A-ZÀ-Ú][a-zà-ú]+)){0,4})",
        r"(?:publica[çc][õo]es\s+d[eo]a?\s+)([A-ZÀ-Ú][a-zà-ú]+(?:\s+(?:da|de|do|dos|das|e|[A-ZÀ-Ú][a-zà-ú]+)){0,4})",
    ]
    for pat in patterns:
        match = re.search(pat, raw_text)
        if match:
            candidate = match.group(1).strip(" .,;:?!")
            if normalize_text(candidate) not in {"est", "esg", "isla", "mais produtivos"}:
                return candidate
    return None


def build_execution_plan(
    user_message: str,
    *,
    previous_scope: dict[str, Any] | None = None,
    reference_year: int | None = None,
) -> AgentPlan:
    """
    Planeador determinístico de intenção e ferramentas.
    Respeita o princípio da especificação: pede esclarecimento em pedidos vagos
    e reutiliza o contexto da conversação em refinamentos iterativos.
    """
    prev = previous_scope or {}
    ref_year = reference_year or datetime.now(UTC).year
    norm = normalize_text(user_message)

    wants_reports = any(
        kw in norm
        for kw in ("relatorio", "pdf", "excel", "export", "acrescenta", "adiciona", "atualiza")
    )

    # Pedido sobre estado das fontes
    if any(kw in norm for kw in ("fontes", "ultima atualizacao", "sincronizac", "snapshot")):
        return AgentPlan(
            intent="sources_status",
            steps=["Consultar metadados e datas de atualização das fontes"],
        )

    cv_match = CV_PATTERN.search(user_message)
    email_match = EMAIL_PATTERN.search(user_message)
    school_match = SCHOOL_PATTERN.search(user_message)
    name_hint = _extract_researcher_name_hint(user_message)
    year_from, year_to, compare_years = _extract_timeframe(norm, reference_year=ref_year)

    is_institutional_wide = any(
        kw in norm for kw in ("institucional", "isla", "todas as escolas", "global")
    )
    is_own_request = any(
        kw in norm for kw in ("meus dados", "minhas publicacoes", "minha producao", "meu perfil")
    )
    is_followup_refinement = bool(prev) and (
        compare_years is not None
        or any(kw in norm for kw in ("acrescenta", "adiciona", "inclui", "tambem", "compara"))
    )

    # Caso 1: refinamento iterativo com base no contexto da conversação
    if is_followup_refinement:
        merged_school = school_match.group(1).upper() if school_match else prev.get("school_code")
        merged_yf = year_from if year_from is not None else prev.get("year_from")
        merged_yt = year_to if year_to is not None else prev.get("year_to")
        merged_res_id = UUID(prev["researcher_id"]) if prev.get("researcher_id") else None
        steps = [
            "Recuperar âmbito da conversação anterior",
            "Cruzar publicações do Portal Científico e dados de docentes da intranet",
        ]
        if compare_years:
            steps.append(f"Calcular comparação direta entre {compare_years[0]} e {compare_years[1]}")
        if wants_reports or prev:
            steps.append("Gerar nova versão dos relatórios PDF e Excel")
        return AgentPlan(
            intent="school_report",
            school_code=merged_school,
            year_from=merged_yf,
            year_to=merged_yt,
            compare_years=compare_years,
            researcher_id=merged_res_id,
            wants_reports=True,
            steps=steps,
        )

    # Caso 2: pedido focado num docente específico (CV ID, email ou nome)
    researcher_query = (
        cv_match.group(0).upper()
        if cv_match
        else (email_match.group(0).lower() if email_match else name_hint)
    )
    if researcher_query or is_own_request:
        steps = [
            "Identificar docente respeitando permissões RBAC",
            "Consultar publicações e cruzar com dados da intranet",
        ]
        if wants_reports:
            steps.append("Gerar relatórios PDF e Excel com fontes citadas")
        return AgentPlan(
            intent="researcher_report",
            researcher_query=researcher_query or "__self__",
            year_from=year_from,
            year_to=year_to,
            compare_years=compare_years,
            wants_reports=wants_reports,
            steps=steps,
        )

    # Caso 3: análise/relatório por escola ou institucional com âmbito suficientemente claro
    school_code = school_match.group(1).upper() if school_match else None
    has_clear_scope = bool(school_code or is_institutional_wide or year_from or compare_years)
    if has_clear_scope:
        steps = [
            "Identificar intervalo temporal e âmbito institucional",
            "Consultar docentes da intranet e publicações do Portal Científico",
            "Calcular indicadores (produção anual, Scopus/WoS, quartis, citações, top docentes)",
            "Validar lacunas de dados e referenciar fontes",
        ]
        if wants_reports:
            steps.append("Gerar relatórios PDF e Excel")
        return AgentPlan(
            intent="school_report",
            school_code=school_code,
            year_from=year_from,
            year_to=year_to,
            compare_years=compare_years,
            wants_reports=wants_reports,
            steps=steps,
        )

    # Caso 4: pedido vago/ambíguo -> pedir esclarecimento antes de executar
    return AgentPlan(
        intent="clarify",
        needs_clarification=True,
        clarification_question=(
            "Para garantir resultados rigorosos, podes precisar o âmbito do pedido? "
            "Por exemplo:\n"
            "- **Âmbito**: uma escola específica (`EST` ou `ESG`), toda a instituição (`ISLA`), "
            "ou um docente (nome, email ou Ciência Vitae ID)?\n"
            "- **Período temporal**: ex. últimos 5 anos, 2021–2025 ou comparação entre dois anos?\n"
            "- **Formato**: apenas resumo na conversa ou também exportação em PDF e Excel?"
        ),
        steps=["Detetar ambiguidade no pedido e solicitar esclarecimento ao utilizador"],
    )


def _format_sources_footer(sources: list[dict[str, Any]]) -> str:
    if not sources:
        return "\n\n**Fontes**: Nenhuma fonte sincronizada disponível."
    lines = ["\n\n**Fontes utilizadas**:"]
    for s in sources:
        lines.append(
            f"- {s['label']} (`{s['endpoint_or_filename']}` · versão `{s['version']}` · "
            f"{s['record_count']} registos · atualizado em `{str(s['synced_at'])[:19]} UTC`)"
        )
    return "\n".join(lines)


class AgentOrchestrator:
    def __init__(
        self,
        reports_dir: Path | None = None,
        llm_client: OpenAICompatibleLLMClient | None = None,
    ) -> None:
        self.report_generator = ReportGeneratorService()
        self.reports_dir = reports_dir
        self.llm_client = llm_client or OpenAICompatibleLLMClient()

    def _run_llm_tool_loop(
        self,
        *,
        ctx: ToolContext,
        prev_messages: list[Message],
        user_message: str,
        reference_year: int | None,
    ) -> tuple[str, bool, list[str], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None]:
        settings = get_settings()
        ref_year = reference_year or datetime.now(UTC).year

        role_context = (
            f"Contexto de sessão (aplicado pelo backend): perfil={ctx.user.role}, "
            f"ano_referencia={ref_year}, "
            f"tem_docente_associado={ctx.user.researcher_id is not None}"
        )
        if ctx.user.researcher_id is not None:
            role_context += f", own_researcher_id={ctx.user.researcher_id}"

        llm_messages: list[dict[str, Any]] = [
            {"role": "system", "content": f"{SYSTEM_PROMPT}\n\n{role_context}"}
        ]
        for old in prev_messages[-8:]:
            if old.role in {"user", "assistant"}:
                llm_messages.append({"role": old.role, "content": old.content})
        llm_messages.append({"role": "user", "content": user_message})

        plan_steps: list[str] = ["Interpretar pedido com LLM + Tool Calling"]
        tool_calls_meta: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        report_bundle: dict[str, Any] | None = None
        analytics_summary: dict[str, Any] | None = None
        final_answer: str | None = None

        max_steps = max(1, min(settings.llm_max_tool_steps, 8))
        for _ in range(max_steps):
            response = self.llm_client.chat_completion(
                messages=llm_messages,
                tools=OPENAI_TOOL_SCHEMAS,
            )

            if not response.tool_calls:
                final_answer = (response.content or "").strip()
                break

            assistant_tool_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in response.tool_calls
                ],
            }
            llm_messages.append(assistant_tool_msg)

            for tc in response.tool_calls:
                plan_steps.append(f"Executar ferramenta `{tc.name}` com validação RBAC")
                execution = execute_registered_tool(
                    name=tc.name,
                    arguments=tc.arguments,
                    ctx=ctx,
                    report_generator=self.report_generator,
                    reports_dir=self.reports_dir,
                    reference_year=reference_year,
                )
                tool_calls_meta.append(execution.audit_meta)
                if execution.sources:
                    sources = execution.sources
                if execution.analytics_summary is not None:
                    analytics_summary = execution.analytics_summary
                if execution.report_bundle is not None:
                    report_bundle = execution.report_bundle

                llm_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tc.name,
                        "content": json.dumps(execution.llm_payload, ensure_ascii=False),
                    }
                )

        if not final_answer:
            raise LLMClientError("LLM não produziu resposta final dentro do limite de passos.")

        if sources and "Fontes utilizadas" not in final_answer:
            final_answer = final_answer + _format_sources_footer(sources)

        needs_clarification = len(tool_calls_meta) == 0 and "?" in final_answer
        return (
            final_answer,
            needs_clarification,
            plan_steps,
            tool_calls_meta,
            sources,
            report_bundle,
            analytics_summary,
        )

    def handle_message(
        self,
        db: Session,
        *,
        user: User,
        message_text: str,
        conversation_id: UUID | None = None,
        ip_address: str | None = None,
        reference_year: int | None = None,
    ) -> AgentTurnResult:
        # 1. Obter ou criar conversação (isolada por utilizador)
        conversation: Conversation | None = None
        if conversation_id is not None:
            conversation = db.scalar(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user.id,
                )
            )
        if conversation is None:
            conversation = Conversation(
                user_id=user.id,
                title=message_text.strip()[:80] or "Nova conversação",
            )
            db.add(conversation)
            db.flush()

        prev_messages = list(
            db.scalars(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.created_at)
            ).all()
        )
        previous_scope = _extract_last_scope(prev_messages)

        # Guardar mensagem do utilizador
        db.add(Message(conversation_id=conversation.id, role="user", content=message_text))
        db.flush()

        ctx = ToolContext(db=db, user=user, ip_address=ip_address)
        execution_mode = "deterministic"

        # 2A. Modo LLM + Tool Calling (quando configurado e pronto)
        if self.llm_client.is_ready:
            try:
                (
                    answer,
                    needs_clarification,
                    plan_steps,
                    tool_calls,
                    sources,
                    report_bundle,
                    analytics_summary,
                ) = self._run_llm_tool_loop(
                    ctx=ctx,
                    prev_messages=prev_messages,
                    user_message=message_text,
                    reference_year=reference_year,
                )
                execution_mode = "llm_tool_calling"
                assistant_msg = Message(
                    conversation_id=conversation.id,
                    role="assistant",
                    content=answer,
                    sources_json=sources,
                    tool_calls_json=tool_calls,
                )
                db.add(assistant_msg)
                db.flush()
                record_audit_log(
                    db,
                    action="agent.chat.turn",
                    resource_type="conversation",
                    resource_id=str(conversation.id),
                    user_id=user.id,
                    user_role=user.role,
                    status="success",
                    details={
                        "mode": execution_mode,
                        "needs_clarification": needs_clarification,
                        "report_generated": report_bundle is not None,
                        "tools_used": [tc.get("tool") for tc in tool_calls],
                    },
                    ip_address=ip_address,
                )
                db.commit()
                db.refresh(assistant_msg)
                return AgentTurnResult(
                    conversation_id=conversation.id,
                    message_id=assistant_msg.id,
                    answer=answer,
                    needs_clarification=needs_clarification,
                    plan=plan_steps,
                    tool_calls=tool_calls,
                    sources=sources,
                    report_bundle=report_bundle,
                    analytics_summary=analytics_summary,
                )
            except LLMClientError as exc:
                record_audit_log(
                    db,
                    action="agent.llm.fallback",
                    resource_type="conversation",
                    resource_id=str(conversation.id),
                    user_id=user.id,
                    user_role=user.role,
                    status="error",
                    details={"reason": str(exc)},
                    ip_address=ip_address,
                )

        # 2B. Planeador determinístico (padrão offline ou fallback seguro)
        plan = build_execution_plan(
            message_text,
            previous_scope=previous_scope,
            reference_year=reference_year,
        )
        tool_calls = []
        sources = []
        report_bundle = None
        analytics_summary = None

        # 3. Executar plano
        if plan.needs_clarification:
            answer = plan.clarification_question or "Podes clarificar o pedido?"
        elif plan.intent == "sources_status":
            status_res = get_data_sources_status(ctx)
            sources = status_res["sources"]
            tool_calls.append({"tool": "get_data_sources_status", "result_count": len(sources)})
            if not sources:
                answer = "Ainda não existem fontes sincronizadas (API do Portal Científico ou Excel de docentes)."
            else:
                answer = "Estado atual das fontes de dados carregadas no sistema:" + _format_sources_footer(sources)
        elif plan.intent == "researcher_report":
            target_researcher_id: UUID | None = None
            target_label: str = ""
            if plan.researcher_query == "__self__":
                target_researcher_id = user.researcher_id
                target_label = user.full_name
                if target_researcher_id is None:
                    answer = "A tua conta ainda não está associada a um registo de docente na intranet."
            else:
                lookup = find_researcher(ctx, plan.researcher_query or "")
                sources = lookup["sources"]
                tool_calls.append(
                    {
                        "tool": "find_researcher",
                        "query": plan.researcher_query,
                        "access_denied": lookup["access_denied"],
                        "matches": len(lookup["matches"]),
                        "hypotheses": len(lookup["hypotheses"]),
                    }
                )
                if lookup["access_denied"]:
                    answer = lookup["message"] + _format_sources_footer(sources)
                elif len(lookup["matches"]) == 1:
                    target_researcher_id = UUID(lookup["matches"][0]["id"])
                    target_label = lookup["matches"][0]["name"]
                elif len(lookup["matches"]) > 1 or len(lookup["hypotheses"]) >= 1:
                    # Regra P0 de integridade: correspondência apenas por nome é sempre
                    # uma hipótese que exige validação (mesmo com 1 único candidato).
                    candidates = lookup["matches"] or lookup["hypotheses"]
                    names_list = "\n".join(
                        f"- {c['name']} ({c.get('school_code') or 'Sem escola'} · CV: `{c.get('ciencia_vitae_id') or 'N/D'}`)"
                        for c in candidates[:5]
                    )
                    plan.needs_clarification = True
                    answer = (
                        "A correspondência apenas pelo nome exige validação antes de gerar relatórios. "
                        "Confirma a identidade indicando o identificador Ciência Vitae ou email institucional:\n"
                        f"{names_list}"
                    )
                else:
                    answer = (
                        f"Não foi encontrado nenhum docente correspondente a `{plan.researcher_query}` "
                        "no âmbito autorizado." + _format_sources_footer(sources)
                    )

            if target_researcher_id is not None:
                data = get_scientific_production_report_data(
                    ctx,
                    researcher_id=target_researcher_id,
                    year_from=plan.year_from,
                    year_to=plan.year_to,
                    compare_years=plan.compare_years,
                    reference_year=reference_year,
                )
                sources = data["sources"]
                tool_calls.append(
                    {
                        "tool": "get_scientific_production_report_data",
                        "scope": data["scope"],
                        "reproducibility_id": data["reproducibility_id"],
                    }
                )
                if data.get("access_denied"):
                    answer = data["message"] + _format_sources_footer(sources)
                else:
                    analytics_summary = {
                        "kpis": data["kpis"],
                        "annual_evolution": data["annual_evolution"],
                        "year_comparison": data["year_comparison"],
                        "reproducibility_id": data["reproducibility_id"],
                    }
                    if plan.wants_reports:
                        report_bundle = self.report_generator.save_report_bundle(
                            data,
                            owner_id=user.id,
                            title=f"Produção Científica — {target_label}",
                            output_dir=self.reports_dir,
                        )
                        tool_calls.append(
                            {"tool": "report_generator", "report_id": report_bundle["report_id"]}
                        )
                    answer = self._compose_grounded_answer(
                        heading=f"Produção Científica — {target_label}",
                        data=data,
                        report_bundle=report_bundle,
                    )
        else:
            data = get_scientific_production_report_data(
                ctx,
                school_code=plan.school_code,
                year_from=plan.year_from,
                year_to=plan.year_to,
                researcher_id=plan.researcher_id,
                compare_years=plan.compare_years,
                reference_year=reference_year,
            )
            sources = data["sources"]
            tool_calls.append(
                {
                    "tool": "get_scientific_production_report_data",
                    "scope": data["scope"],
                    "reproducibility_id": data["reproducibility_id"],
                }
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
            scope_title = (
                f"Produção Científica da {plan.school_code}"
                if plan.school_code
                else "Produção Científica Institucional — ISLA"
            )
            if plan.year_from and plan.year_to:
                scope_title += f" ({plan.year_from}–{plan.year_to})"
            if plan.wants_reports:
                report_bundle = self.report_generator.save_report_bundle(
                    data,
                    owner_id=user.id,
                    title=scope_title,
                    output_dir=self.reports_dir,
                )
                tool_calls.append(
                    {"tool": "report_generator", "report_id": report_bundle["report_id"]}
                )
            answer = self._compose_grounded_answer(
                heading=scope_title,
                data=data,
                report_bundle=report_bundle,
            )

        assistant_msg = Message(
            conversation_id=conversation.id,
            role="assistant",
            content=answer,
            sources_json=sources,
            tool_calls_json=tool_calls,
        )
        db.add(assistant_msg)
        db.flush()

        record_audit_log(
            db,
            action="agent.chat.turn",
            resource_type="conversation",
            resource_id=str(conversation.id),
            user_id=user.id,
            user_role=user.role,
            status="success",
            details={
                "intent": plan.intent,
                "needs_clarification": plan.needs_clarification,
                "report_generated": report_bundle is not None,
                "tools_used": [tc["tool"] for tc in tool_calls],
            },
            ip_address=ip_address,
        )
        db.commit()
        db.refresh(assistant_msg)

        return AgentTurnResult(
            conversation_id=conversation.id,
            message_id=assistant_msg.id,
            answer=answer,
            needs_clarification=plan.needs_clarification,
            plan=plan.steps,
            tool_calls=tool_calls,
            sources=sources,
            report_bundle=report_bundle,
            analytics_summary=analytics_summary,
        )

    @staticmethod
    def _compose_grounded_answer(
        *,
        heading: str,
        data: dict[str, Any],
        report_bundle: dict[str, Any] | None,
    ) -> str:
        kpis = data["kpis"]
        annual = data["annual_evolution"]
        top_res = data["top_researchers"]
        comparison = data.get("year_comparison")
        quality = data["data_quality"]

        lines: list[str] = [
            f"### {heading}",
            f"- **Total de publicações**: {kpis['publications']}",
            f"- **Indexadas Scopus**: {kpis['scopus']} ({kpis['scopus_pct']}%) | **Web of Science**: {kpis['wos']} ({kpis['wos_pct']}%)",
            f"- **Quartis**: Q1={kpis['q1']}, Q2={kpis['q2']}, Q3={kpis['q3']}, Q4={kpis['q4']} (sem quartil: {quality['missing_quartile_count']})",
            f"- **Citações totais**: {kpis['citations']} (média: {kpis['avg_citations']}) | **Open Access**: {kpis['open_access']} ({kpis['open_access_pct']}%)",
        ]

        if annual:
            evo_str = ", ".join(f"{r['year']}: {r['publications']}" for r in annual)
            lines.append(f"- **Evolução anual**: {evo_str}")

        if top_res:
            top_str = ", ".join(
                f"{r['name']} ({r['publications']} pub., {r['citations']} cit.)"
                for r in top_res[:5]
            )
            lines.append(f"- **Docentes mais produtivos**: {top_str}")

        if comparison:
            ya, yb = comparison["year_a"], comparison["year_b"]
            d_pub = comparison["deltas"]["publications"]
            d_cit = comparison["deltas"]["citations"]
            sign_p = "+" if d_pub["delta"] > 0 else ""
            sign_c = "+" if d_cit["delta"] > 0 else ""
            lines.append(
                f"- **Comparação {ya} vs {yb}**: Publicações {d_pub['year_a']} -> {d_pub['year_b']} "
                f"({sign_p}{d_pub['delta']}, {sign_p}{d_pub['delta_pct']}%); "
                f"Citações {d_cit['year_a']} -> {d_cit['year_b']} ({sign_c}{d_cit['delta']})"
            )

        if quality["name_hypotheses_pending_validation"] or quality["missing_quartile_count"]:
            lines.append(
                f"- **Alertas de qualidade**: {quality['missing_quartile_count']} publicações sem quartil; "
                f"{quality['name_hypotheses_pending_validation']} associações por nome pendentes de validação."
            )

        lines.append(f"- **ID de reprodutibilidade**: `{data['reproducibility_id']}`")

        if report_bundle:
            lines.append(
                f"\n**Relatórios gerados**: "
                f"[PDF]({report_bundle['pdf_url']}) | [Excel]({report_bundle['excel_url']})"
            )

        return "\n".join(lines) + _format_sources_footer(data["sources"])
