from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.permissions import Permission, UserRole
from app.database.session import get_db
from app.models.audit import AuditLog
from app.models.user import User
from app.schemas import AuditLogResponse

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/logs", response_model=list[AuditLogResponse])
def list_audit_logs(
    limit: int = Query(default=50, ge=1, le=200),
    action: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    user: User = Depends(require_permission(Permission.VIEW_AUDIT_LOGS)),
    db: Session = Depends(get_db),
) -> list[AuditLogResponse]:
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action.contains(action))
    if status_filter:
        stmt = stmt.where(AuditLog.status == status_filter)

    rows = db.scalars(stmt.order_by(desc(AuditLog.created_at)).limit(limit)).all()
    is_admin = user.role == UserRole.ADMIN.value

    result: list[AuditLogResponse] = []
    for row in rows:
        item = AuditLogResponse.model_validate(row)
        # Direção tem visão limitada (sem endereços IP)
        if not is_admin:
            item.ip_address = None
        result.append(item)
    return result
