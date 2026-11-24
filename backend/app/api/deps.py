from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import ROLE_PERMISSIONS, Permission, UserRole, has_permission
from app.core.security import decode_access_token
from app.database.session import get_db
from app.models.user import User
from app.services.audit import record_audit_log

SESSION_COOKIE_NAME = "isla_ai_session"
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    raw_token = credentials.credentials if credentials is not None else request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticação obrigatória.",
        )

    try:
        payload = decode_access_token(raw_token)
        user_id = UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de autenticação inválido ou expirado.",
        )

    user = db.scalar(select(User).where(User.id == user_id))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utilizador inativo ou inexistente.",
        )
    return user


def require_permission(permission: Permission):
    def _dependency(
        request: Request,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if not has_permission(user.role, permission):
            record_audit_log(
                db,
                action=f"permission.denied.{permission.value}",
                resource_type="endpoint",
                resource_id=str(request.url.path),
                user_id=user.id,
                user_role=user.role,
                status="denied",
                details={"required_permission": permission.value},
                ip_address=request.client.host if request.client else None,
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Sem permissões para executar esta operação.",
            )
        return user

    return _dependency


def permissions_for_role(role: str) -> list[str]:
    try:
        resolved = UserRole(role)
    except ValueError:
        return []
    return sorted(p.value for p in ROLE_PERMISSIONS[resolved])
