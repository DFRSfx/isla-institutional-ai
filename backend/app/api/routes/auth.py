import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, permissions_for_role
from app.core.config import get_settings
from app.core.permissions import UserRole
from app.core.security import create_access_token, hash_password, verify_password
from app.database.session import get_db
from app.models.researcher import Researcher
from app.models.user import User
from app.schemas import LoginRequest, TokenResponse, UserProfileResponse
from app.services.audit import record_audit_log
from app.services.institutional_auth import (
    InstitutionalAuthClient,
    InstitutionalAuthError,
    InstitutionalAuthForbiddenRole,
    InstitutionalAuthUnauthorized,
    InstitutionalIdentity,
)

router = APIRouter(prefix="/auth", tags=["auth"])

ROLE_PRECEDENCE: dict[str, int] = {
    UserRole.FACULTY.value: 1,
    UserRole.DIRECTION.value: 2,
    UserRole.ADMIN.value: 3,
}


def get_institutional_auth_client() -> InstitutionalAuthClient:
    return InstitutionalAuthClient()


def _provision_or_update_institutional_user(
    db: Session,
    identity: InstitutionalIdentity,
) -> User:
    user = db.scalar(select(User).where(User.email == identity.email))
    matched_researcher = db.scalar(select(Researcher).where(Researcher.email == identity.email))

    if user is None:
        user = User(
            email=identity.email,
            full_name=identity.display_name,
            # Conta gerida por LDAP: hash aleatório não utilizável para login local
            password_hash=hash_password(secrets.token_urlsafe(32)),
            role=identity.mapped_role.value,
            is_active=True,
            researcher_id=matched_researcher.id if matched_researcher else None,
        )
        db.add(user)
        db.flush()
        return user

    user.full_name = identity.display_name or user.full_name
    # Preserva promoções locais (ex.: docente promovido a 'direction' ou 'admin')
    if ROLE_PRECEDENCE.get(identity.mapped_role.value, 0) > ROLE_PRECEDENCE.get(user.role, 0):
        user.role = identity.mapped_role.value
    if user.researcher_id is None and matched_researcher is not None:
        user.researcher_id = matched_researcher.id
    db.flush()
    return user


@router.get("/config")
def auth_config(
    auth_client: InstitutionalAuthClient = Depends(get_institutional_auth_client),
) -> dict[str, object]:
    settings = get_settings()
    return {
        "auth_mode": settings.auth_mode,
        "institutional_enabled": auth_client.is_configured and settings.auth_mode != "local",
    }


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
    auth_client: InstitutionalAuthClient = Depends(get_institutional_auth_client),
) -> TokenResponse:
    settings = get_settings()
    identifier = (payload.username or "").strip()
    ip = request.client.host if request.client else None

    user: User | None = None
    auth_provider = "local"
    use_institutional = settings.auth_mode in {"institutional", "hybrid"} and auth_client.is_configured

    if use_institutional:
        try:
            identity = auth_client.authenticate(identifier, payload.password)
            user = _provision_or_update_institutional_user(db, identity)
            if not user.is_active:
                record_audit_log(
                    db,
                    action="auth.login",
                    resource_type="user",
                    resource_id=str(user.id),
                    user_id=user.id,
                    user_role=user.role,
                    status="denied",
                    details={"provider": "institutional_ldap", "reason": "user_inactive"},
                    ip_address=ip,
                )
                db.commit()
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Conta desativada pelo administrador.",
                )
            auth_provider = "institutional_ldap"
        except InstitutionalAuthForbiddenRole as exc:
            record_audit_log(
                db,
                action="auth.login.forbidden_role",
                resource_type="user",
                resource_id=identifier,
                status="denied",
                details={"provider": "institutional_ldap", "reason": str(exc)},
                ip_address=ip,
            )
            db.commit()
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        except InstitutionalAuthUnauthorized:
            if settings.auth_mode == "institutional":
                record_audit_log(
                    db,
                    action="auth.login",
                    resource_type="user",
                    resource_id=identifier,
                    status="denied",
                    details={"provider": "institutional_ldap"},
                    ip_address=ip,
                )
                db.commit()
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Credenciais institucionais inválidas.",
                )
        except InstitutionalAuthError as exc:
            if settings.auth_mode == "institutional":
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=str(exc),
                ) from exc

    # Fallback local (modo 'local' ou 'hybrid' para contas locais)
    if user is None:
        email_lower = identifier.lower()
        local_user = db.scalar(select(User).where(User.email == email_lower))
        if (
            local_user is None
            or not local_user.is_active
            or not verify_password(payload.password, local_user.password_hash)
        ):
            record_audit_log(
                db,
                action="auth.login",
                resource_type="user",
                resource_id=email_lower,
                user_id=local_user.id if local_user else None,
                user_role=local_user.role if local_user else None,
                status="denied",
                details={"provider": "local"},
                ip_address=ip,
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Credenciais inválidas.",
            )
        user = local_user

    token = create_access_token(subject=user.id, role=user.role)
    record_audit_log(
        db,
        action="auth.login",
        resource_type="user",
        resource_id=str(user.id),
        user_id=user.id,
        user_role=user.role,
        status="success",
        details={"provider": auth_provider},
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
