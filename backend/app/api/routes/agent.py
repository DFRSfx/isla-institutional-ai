from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.agent.graph import AgentOrchestrator
from app.api.deps import get_current_user
from app.database.session import get_db
from app.models.conversation import Conversation, Message
from app.models.user import User
from app.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationResponse,
    MessageResponse,
    ReportBundleResponse,
)

router = APIRouter(tags=["agent"])


def get_orchestrator() -> AgentOrchestrator:
    return AgentOrchestrator()


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    orchestrator: AgentOrchestrator = Depends(get_orchestrator),
) -> ChatResponse:
    result = orchestrator.handle_message(
        db,
        user=user,
        message_text=payload.message,
        conversation_id=payload.conversation_id,
        ip_address=request.client.host if request.client else None,
    )
    return ChatResponse(
        conversation_id=result.conversation_id,
        message_id=result.message_id,
        answer=result.answer,
        needs_clarification=result.needs_clarification,
        plan=result.plan,
        tool_calls=result.tool_calls,
        sources=result.sources,
        report_bundle=(
            ReportBundleResponse(**result.report_bundle) if result.report_bundle else None
        ),
        analytics_summary=result.analytics_summary,
    )


@router.get("/conversations", response_model=list[ConversationResponse])
def list_conversations(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ConversationResponse]:
    convs = db.scalars(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(desc(Conversation.updated_at))
        .limit(50)
    ).all()
    return [ConversationResponse.model_validate(c) for c in convs]


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
def list_conversation_messages(
    conversation_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[MessageResponse]:
    conv = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user.id,
        )
    )
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversação não encontrada.",
        )
    msgs = db.scalars(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at)
    ).all()

    out: list[MessageResponse] = []
    for m in msgs:
        restored_bundle: ReportBundleResponse | None = None
        for tc in reversed(m.tool_calls_json or []):
            if isinstance(tc, dict) and isinstance(tc.get("report_bundle"), dict):
                restored_bundle = ReportBundleResponse(**tc["report_bundle"])
                break
        item = MessageResponse.model_validate(m)
        item.report_bundle = restored_bundle
        out.append(item)
    return out
