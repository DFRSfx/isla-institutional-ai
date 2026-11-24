from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.audit import AuditLog


def record_audit_log(
    db: Session,
    *,
    action: str,
    resource_type: str,
    user_id: UUID | None = None,
    user_role: str | None = None,
    resource_id: str | None = None,
    status: str = "success",
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        user_id=user_id,
        user_role=user_role,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        status=status,
        details=details or {},
        ip_address=ip_address,
    )
    db.add(entry)
    return entry
