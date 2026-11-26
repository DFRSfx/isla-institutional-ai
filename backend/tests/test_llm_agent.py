import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.graph import AgentOrchestrator
from app.agent.llm_client import OpenAICompatibleLLMClient, strip_reasoning_tags
from app.agent.tool_registry import execute_registered_tool
from app.agent.tools import ToolContext
from app.core.config import Settings
from app.core.permissions import UserRole
from app.models.audit import AuditLog
from app.models.researcher import Researcher
from app.services.excel_import import ExcelImportService
from app.services.portal_api import PortalFetchResult, PortalSyncService
from app.services.report_generator import ReportGeneratorService
from tests.conftest import build_synthetic_researchers_xlsx, make_user
from tests.test_portal_sync import SAMPLE_PORTAL_PAYLOAD_V1


def _seed_data(db: Session) -> None:
    ExcelImportService().import_workbook(
        db, build_synthetic_researchers_xlsx(), "docentes.xlsx"
    )
    PortalSyncService().sync_publications(
        db,
        prefetched=PortalFetchResult(
            records=SAMPLE_PORTAL_PAYLOAD_V1,
            source_version="40",
            reported_record_count=2,
            cache_ttl_minutes=1440,
            endpoint="/api/powerbi/publications",
            forced_nocache=False,
        ),
    )


def test_llm_client_readiness_and_local_only_rgpd_guardrail() -> None:
    # Desativado por defeito
    assert OpenAICompatibleLLMClient(Settings()).is_ready is False

    # Por RGPD/NIS2, endpoint externo é recusado por defeito (LLM_ALLOW_EXTERNAL_ENDPOINTS=False)
    with pytest.raises(ValidationError):
        Settings(
            llm_provider="openai_compatible",
            llm_base_url="https://api.openai.com/v1",
            llm_model="gpt-4o-mini",
            llm_api_key="sk-test-key",
        )

    # Remoto apenas permitido com opt-in explícito e API key válida (não placeholder)
    assert (
        OpenAICompatibleLLMClient(
            Settings(
                llm_provider="openai_compatible",
                llm_base_url="https://api.openai.com/v1",
                llm_model="gpt-4o-mini",
                llm_api_key="CHANGE_ME",
                llm_allow_external_endpoints=True,
            )
        ).is_ready
        is False
    )

    # Ollama local e rede privada LAN (RFC-1918) funcionam sem opt-in externo nem API key
    for local_url in (
        "http://localhost:11434/v1",
        "http://ollama:11434/v1",
        "http://192.168.1.50:11434/v1",
    ):
        assert (
            OpenAICompatibleLLMClient(
                Settings(
                    llm_provider="openai_compatible",
                    llm_base_url=local_url,
                    llm_model="qwen2.5:7b-instruct",
                    llm_api_key="",
                )
            ).is_ready
            is True
        )


def test_llm_tool_calling_executes_analytics_minimizes_payload_and_generates_reports(
    db_session: Session, tmp_path: Path
) -> None:
    _seed_data(db_session)
    direction = make_user(db_session, email="direcao@islagaia.pt", role=UserRole.DIRECTION)

    captured_requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        req_body = json.loads(request.read().decode("utf-8"))
        captured_requests.append(req_body)

        if len(captured_requests) == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "tool_calls",
                            "message": {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call_est_1",
                                        "type": "function",
                                        "function": {
                                            "name": "get_scientific_production_report_data",
                                            "arguments": json.dumps(
                                                {
                                                    "school_code": "EST",
                                                    "year_from": 2022,
                                                    "year_to": 2026,
                                                    "generate_reports": True,
                                                }
                                            ),
                                        },
                                    }
                                ],
                            },
                        }
                    ]
                },
            )

        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": (
                                "A EST registou 2 publicações no período 2022–2026, ambas indexadas "
                                "em Scopus e com 17 citações acumuladas. Os relatórios PDF e Excel "
                                "foram gerados."
                            ),
                        },
                    }
                ]
            },
        )

    llm_client = OpenAICompatibleLLMClient(
        settings=Settings(
            llm_provider="openai_compatible",
            llm_base_url="http://localhost:11434/v1",
            llm_model="qwen2.5:7b-instruct",
        ),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    orchestrator = AgentOrchestrator(reports_dir=tmp_path, llm_client=llm_client)

    result = orchestrator.handle_message(
        db_session,
        user=direction,
        message_text="Faz-me um resumo e relatórios da EST entre 2022 e 2026.",
        reference_year=2026,
    )

    assert len(captured_requests) == 2
    # Verificar minimização de dados enviados ao LLM na 2.ª chamada (sem lista bruta 'publications')
    tool_msg = next(m for m in captured_requests[1]["messages"] if m["role"] == "tool")
    tool_payload = json.loads(tool_msg["content"])
    assert "publications" not in tool_payload
    assert tool_payload["kpis"]["publications"] == 2
    assert tool_payload["kpis"]["citations"] == 17

    assert result.needs_clarification is False
    assert result.analytics_summary is not None
    assert result.analytics_summary["kpis"]["publications"] == 2
    assert result.report_bundle is not None
    assert (tmp_path / f"{result.report_bundle['report_id']}.pdf").exists()
    assert (tmp_path / f"{result.report_bundle['report_id']}.xlsx").exists()
    assert "Fontes utilizadas" in result.answer


def test_llm_tool_calling_enforces_rbac_and_falls_back_on_provider_error(
    db_session: Session, tmp_path: Path
) -> None:
    _seed_data(db_session)
    ana = db_session.scalar(select(Researcher).where(Researcher.email == "ana.silva@isla.test"))
    assert ana is not None
    faculty = make_user(
        db_session,
        email="ana.silva@islagaia.pt",
        role=UserRole.FACULTY,
        full_name="Ana Silva",
        researcher_id=ana.id,
    )

    # 1. Mesmo com LLM ativo, tentativa de docente consultar outro docente é bloqueada pelo backend
    calls = 0

    def rbac_handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        req_body = json.loads(request.read().decode("utf-8"))
        if calls == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "tool_calls",
                            "message": {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call_find_1",
                                        "type": "function",
                                        "function": {
                                            "name": "find_researcher",
                                            "arguments": json.dumps({"query": "CCCC-2222-DDDD"}),
                                        },
                                    }
                                ],
                            },
                        }
                    ]
                },
            )
        tool_msg = next(m for m in req_body["messages"] if m["role"] == "tool")
        tool_payload = json.loads(tool_msg["content"])
        assert tool_payload["access_denied"] is True
        assert "Bruno Costa" not in tool_msg["content"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "Não tem autorização para consultar dados internos de outros docentes.",
                        },
                    }
                ]
            },
        )

    llm_client = OpenAICompatibleLLMClient(
        settings=Settings(
            llm_provider="openai_compatible",
            llm_base_url="http://localhost:11434/v1",
            llm_model="llama3.1",
        ),
        http_client=httpx.Client(transport=httpx.MockTransport(rbac_handler)),
    )
    res = AgentOrchestrator(reports_dir=tmp_path, llm_client=llm_client).handle_message(
        db_session,
        user=faculty,
        message_text="Dá-me os dados do docente CCCC-2222-DDDD",
    )
    assert "não tem autorização" in res.answer.lower()
    assert "Bruno Costa" not in res.answer

    # 2. Se o fornecedor LLM falhar (503), faz fallback limpo para o planeador determinístico
    failing_client = OpenAICompatibleLLMClient(
        settings=Settings(
            llm_provider="openai_compatible",
            llm_base_url="http://localhost:11434/v1",
            llm_model="llama3.1",
        ),
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda _req: httpx.Response(503))
        ),
    )
    fallback_res = AgentOrchestrator(reports_dir=tmp_path, llm_client=failing_client).handle_message(
        db_session,
        user=faculty,
        message_text="Mostra-me as minhas publicações",
    )
    assert fallback_res.analytics_summary is not None
    assert fallback_res.analytics_summary["kpis"]["publications"] == 1
    fallback_logs = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "agent.llm.fallback")
    ).all()
    assert len(fallback_logs) == 1


def test_strip_qwen3_think_tags_and_hide_uuid_on_name_hypotheses(db_session: Session) -> None:
    # 1. Tags <think>...</think> emitidas pelo Qwen3 devem ser removidas antes de mostrar ao utilizador
    raw = "<think>\nVou analisar os indicadores da EST...\n</think>\nA EST tem 2 publicações."
    assert strip_reasoning_tags(raw) == "A EST tem 2 publicações."

    # 2. Hipóteses por nome em find_researcher não podem expor 'id' ao LLM
    _seed_data(db_session)
    direction = make_user(db_session, email="direcao@islagaia.pt", role=UserRole.DIRECTION)
    out = execute_registered_tool(
        name="find_researcher",
        arguments={"query": "Bruno Costa"},
        ctx=ToolContext(db=db_session, user=direction),
        report_generator=ReportGeneratorService(),
    )
    assert out.llm_payload["matches"] == []
    assert len(out.llm_payload["hypotheses"]) == 1
    assert "id" not in out.llm_payload["hypotheses"][0]
    assert out.llm_payload["hypotheses"][0]["requires_confirmation"] is True
