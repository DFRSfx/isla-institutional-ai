from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import UserRole
from app.models.audit import AuditLog
from app.models.conversation import Conversation, Message
from tests.conftest import auth_headers, make_user


def test_delete_own_conversation_and_block_cross_user_delete(
    client: TestClient,
    db_session: Session,
) -> None:
    user_a = make_user(db_session, email="docente.a@islagaia.pt", role=UserRole.FACULTY)
    user_b = make_user(db_session, email="docente.b@islagaia.pt", role=UserRole.FACULTY)
    headers_a = auth_headers(user_a)
    headers_b = auth_headers(user_b)

    # Criar conversação diretamente para user_a com 2 mensagens
    conv = Conversation(user_id=user_a.id, title="Análise EST 2025")
    db_session.add(conv)
    db_session.flush()
    db_session.add_all(
        [
            Message(conversation_id=conv.id, role="user", content="Olá"),
            Message(conversation_id=conv.id, role="assistant", content="Olá!"),
        ]
    )
    db_session.commit()

    # user_b não pode apagar a conversação de user_a
    denied = client.delete(f"/api/v1/conversations/{conv.id}", headers=headers_b)
    assert denied.status_code == 404
    assert db_session.get(Conversation, conv.id) is not None

    # user_a consegue apagar a sua própria conversação (cascata nas mensagens + audit log)
    deleted = client.delete(f"/api/v1/conversations/{conv.id}", headers=headers_a)
    assert deleted.status_code == 200
    assert deleted.json() == {"status": "deleted", "conversation_id": str(conv.id)}

    db_session.expire_all()
    assert db_session.get(Conversation, conv.id) is None
    remaining_msgs = db_session.scalars(
        select(Message).where(Message.conversation_id == conv.id)
    ).all()
    assert remaining_msgs == []

    audit = db_session.scalar(
        select(AuditLog).where(
            AuditLog.action == "conversation.delete",
            AuditLog.resource_id == str(conv.id),
        )
    )
    assert audit is not None
    assert audit.user_id == user_a.id
