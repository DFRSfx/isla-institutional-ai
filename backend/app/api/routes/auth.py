import secrets
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import SESSION_COOKIE_NAME, get_current_user, permissions_for_role
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
    UserRole.STUDENT.value: 0,
    UserRole.FACULTY.value: 1,
    UserRole.DIRECTION.value: 2,
    UserRole.ADMIN.value: 3,
}

LOGIN_RATE_LIMIT_MAX_ATTEMPTS = 5
LOGIN_RATE_LIMIT_WINDOW_SECONDS = 300
_failed_login_attempts: dict[str, list[float]] = defaultdict(list)


def reset_login_rate_limiter() -> None:
    _failed_login_attempts.clear()


def _is_login_rate_limited(key: str) -> bool:
    now = time.monotonic()
    cutoff = now - LOGIN_RATE_LIMIT_WINDOW_SECONDS
    recent = [ts for ts in _failed_login_attempts.get(key, []) if ts > cutoff]
    _failed_login_attempts[key] = recent
    return len(recent) >= LOGIN_RATE_LIMIT_MAX_ATTEMPTS


def _record_failed_login(key: str) -> None:
    _failed_login_attempts[key].append(time.monotonic())


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
    response: Response,
    db: Session = Depends(get_db),
    auth_client: InstitutionalAuthClient = Depends(get_institutional_auth_client),
) -> TokenResponse:
    settings = get_settings()
    identifier = (payload.username or "").strip()
    ip = request.client.host if request.client else None
    throttle_key = f"{identifier.lower()}|{ip or 'unknown'}"

    if _is_login_rate_limited(throttle_key):
        record_audit_log(
            db,
            action="auth.login.rate_limited",
            resource_type="user",
            resource_id=identifier.lower(),
            status="denied",
            ip_address=ip,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiadas tentativas de autenticação falhadas. Tente novamente dentro de alguns minutos.",
        )

    user: User | None = None
    auth_provider = "local"
    auth_mode = settings.auth_mode.strip().lower()

    if auth_mode == "institutional" and not auth_client.is_configured:
        record_audit_log(
            db,
            action="auth.login.misconfigured",
            resource_type="auth",
            resource_id=identifier,
            status="error",
            details={"provider": "institutional_ldap", "reason": "api_key_not_configured"},
            ip_address=ip,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Autenticação institucional não está configurada no servidor.",
        )

    use_institutional = auth_mode in {"institutional", "hybrid"} and auth_client.is_configured

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
            if auth_mode == "institutional":
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
            if auth_mode == "institutional":
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=str(exc),
                ) from exc

    # Fallback local (apenas permitido explicitamente em 'local' ou 'hybrid')
    if user is None and auth_mode in {"local", "hybrid"}:
        email_lower = identifier.lower()
        local_user = db.scalar(select(User).where(User.email == email_lower))
        if (
            local_user is None
            or not local_user.is_active
            or not verify_password(payload.password, local_user.password_hash)
        ):
            _record_failed_login(throttle_key)
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
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.app_env.strip().lower() in {"production", "prod"},
        max_age=settings.jwt_access_token_expire_minutes * 60,
        path="/",
    )
    return TokenResponse(access_token=token, user=profile)


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    record_audit_log(
        db,
        action="auth.logout",
        resource_type="user",
        resource_id=str(user.id),
        user_id=user.id,
        user_role=user.role,
        status="success",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"status": "logged_out"}


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
