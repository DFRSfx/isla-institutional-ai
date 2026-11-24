from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass
class AgentPlan:
    intent: str  # school_report | researcher_lookup | researcher_report | sources_status | clarify
    school_code: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    compare_years: tuple[int, int] | None = None
    researcher_query: str | None = None
    researcher_id: UUID | None = None
    wants_reports: bool = False
    needs_clarification: bool = False
    clarification_question: str | None = None
    steps: list[str] = field(default_factory=list)


@dataclass
class AgentTurnResult:
    conversation_id: UUID
    message_id: UUID
    answer: str
    needs_clarification: bool
    plan: list[str]
    tool_calls: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    report_bundle: dict[str, Any] | None = None
    analytics_summary: dict[str, Any] | None = None
