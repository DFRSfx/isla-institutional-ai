from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, permissions_for_role
from app.core.security import create_access_token, verify_password
from app.database.session import get_db
from app.models.user import User
from app.schemas import LoginRequest, TokenResponse, UserProfileResponse
from app.services.audit import record_audit_log

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TokenResponse:
    email = payload.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    ip = request.client.host if request.client else None

    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        record_audit_log(
            db,
            action="auth.login",
            resource_type="user",
            resource_id=email,
            user_id=user.id if user else None,
            user_role=user.role if user else None,
            status="denied",
            ip_address=ip,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais inválidas.",
        )

    token = create_access_token(subject=user.id, role=user.role)
    record_audit_log(
        db,
        action="auth.login",
        resource_type="user",
        resource_id=str(user.id),
        user_id=user.id,
        user_role=user.role,
        status="success",
        ip_address=ip,
    )
    db.commit()

    profile = UserProfileResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        researcher_id=user.researcher_id,
        permissions=permissions_for_role(user.role),
    )
    return TokenResponse(access_token=token, user=profile)


@router.get("/me", response_model=UserProfileResponse)
def me(user: User = Depends(get_current_user)) -> UserProfileResponse:
    return UserProfileResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        researcher_id=user.researcher_id,
        permissions=permissions_for_role(user.role),
    )
