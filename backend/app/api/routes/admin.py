from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import permissions_for_role, require_permission
from app.core.permissions import Permission, UserRole
from app.core.security import hash_password
from app.database.session import get_db
from app.models.publication import PublicationAuthor
from app.models.researcher import Researcher
from app.models.user import User
from app.schemas import (
    AuthorMatchDecisionRequest,
    PendingAuthorMatchCandidate,
    PendingAuthorMatchResponse,
    UserCreateRequest,
    UserProfileResponse,
    UserUpdateRequest,
)
from app.services.audit import record_audit_log
from app.services.data_normalization import normalize_email, normalize_text

router = APIRouter(tags=["admin"])


def _to_user_profile(user: User) -> UserProfileResponse:
    return UserProfileResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        researcher_id=user.researcher_id,
        permissions=permissions_for_role(user.role),
    )


@router.get("/users", response_model=list[UserProfileResponse])
def list_users(
    _: User = Depends(require_permission(Permission.MANAGE_USERS)),
    db: Session = Depends(get_db),
) -> list[UserProfileResponse]:
    users = db.scalars(select(User).order_by(User.created_at.desc())).all()
    return [_to_user_profile(u) for u in users]


@router.post("/users", response_model=UserProfileResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreateRequest,
    request: Request,
    admin: User = Depends(require_permission(Permission.MANAGE_USERS)),
    db: Session = Depends(get_db),
) -> UserProfileResponse:
    email = normalize_email(payload.email)
    if not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email inválido.")

    try:
        resolved_role = UserRole(payload.role.strip().lower())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Perfil inválido. Valores permitidos: admin, direction, faculty.",
        ) from exc

    if db.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe um utilizador com este email.",
        )

    if payload.researcher_id is not None:
        res = db.scalar(select(Researcher).where(Researcher.id == payload.researcher_id))
        if res is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Docente associado não encontrado.",
            )

    new_user = User(
        email=email,
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        role=resolved_role.value,
        is_active=True,
        researcher_id=payload.researcher_id,
    )
    db.add(new_user)
    db.flush()

    record_audit_log(
        db,
        action="user.create",
        resource_type="user",
        resource_id=str(new_user.id),
        user_id=admin.id,
        user_role=admin.role,
        status="success",
        details={"created_email": email, "role": resolved_role.value},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(new_user)
    return _to_user_profile(new_user)


@router.patch("/users/{user_id}", response_model=UserProfileResponse)
def update_user(
    user_id: UUID,
    payload: UserUpdateRequest,
    request: Request,
    admin: User = Depends(require_permission(Permission.MANAGE_USERS)),
    db: Session = Depends(get_db),
) -> UserProfileResponse:
    target = db.scalar(select(User).where(User.id == user_id))
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilizador não encontrado.")

    if target.id == admin.id:
        if payload.is_active is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Um administrador não pode desativar a própria conta.",
            )
        if payload.role is not None and payload.role.strip().lower() != UserRole.ADMIN.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Um administrador não pode remover o próprio perfil de administrador.",
            )

    if payload.full_name is not None:
        target.full_name = payload.full_name.strip()
    if payload.role is not None:
        try:
            target.role = UserRole(payload.role.strip().lower()).value
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Perfil inválido.",
            ) from exc
    if payload.is_active is not None:
        target.is_active = payload.is_active
    if "researcher_id" in payload.model_fields_set:
        if payload.researcher_id is not None:
            res = db.scalar(select(Researcher).where(Researcher.id == payload.researcher_id))
            if res is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Docente associado não encontrado.",
                )
        target.researcher_id = payload.researcher_id

    record_audit_log(
        db,
        action="user.update",
        resource_type="user",
        resource_id=str(target.id),
        user_id=admin.id,
        user_role=admin.role,
        status="success",
        details={"role": target.role, "is_active": target.is_active},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(target)
    return _to_user_profile(target)


@router.get("/review/author-matches", response_model=list[PendingAuthorMatchResponse])
def list_pending_author_matches(
    _: User = Depends(require_permission(Permission.MANAGE_USERS)),
    db: Session = Depends(get_db),
) -> list[PendingAuthorMatchResponse]:
    pending = db.scalars(
        select(PublicationAuthor)
        .options(selectinload(PublicationAuthor.publication))
        .where(PublicationAuthor.needs_review.is_(True))
        .order_by(PublicationAuthor.created_at.desc())
        .limit(100)
    ).all()

    all_researchers = list(
        db.scalars(select(Researcher).options(selectinload(Researcher.school))).all()
    )

    results: list[PendingAuthorMatchResponse] = []
    for pa in pending:
        norm_raw_name = normalize_text(pa.raw_name)
        candidates: list[PendingAuthorMatchCandidate] = []
        for r in all_researchers:
            cv_hit = (
                pa.raw_ciencia_vitae_id
                and r.ciencia_vitae_id
                and r.ciencia_vitae_id.upper() == pa.raw_ciencia_vitae_id.upper()
            )
            name_hit = norm_raw_name and norm_raw_name in r.normalized_name
            if cv_hit or name_hit:
                candidates.append(
                    PendingAuthorMatchCandidate(
                        id=r.id,
                        name=r.name,
                        ciencia_vitae_id=r.ciencia_vitae_id,
                        email=r.email,
                        school_code=r.school.code if r.school else r.school_code_raw,
                    )
                )

        results.append(
            PendingAuthorMatchResponse(
                authorship_id=pa.id,
                publication_id=pa.publication_id,
                publication_title=pa.publication.title if pa.publication else "",
                publication_year=pa.publication.year if pa.publication else None,
                raw_name=pa.raw_name,
                raw_ciencia_vitae_id=pa.raw_ciencia_vitae_id,
                raw_email=pa.raw_email,
                match_method=pa.match_method,
                match_confidence=pa.match_confidence,
                current_researcher_id=pa.researcher_id,
                candidates=candidates[:10],
            )
        )
    return results


@router.post("/review/author-matches/{authorship_id}")
def decide_author_match(
    authorship_id: UUID,
    payload: AuthorMatchDecisionRequest,
    request: Request,
    admin: User = Depends(require_permission(Permission.MANAGE_USERS)),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    pa = db.scalar(select(PublicationAuthor).where(PublicationAuthor.id == authorship_id))
    if pa is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registo de autoria não encontrado.",
        )

    if payload.action == "approve":
        if payload.researcher_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Indique 'researcher_id' para aprovar a correspondência.",
            )
        researcher = db.scalar(select(Researcher).where(Researcher.id == payload.researcher_id))
        if researcher is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Docente não encontrado.",
            )
        pa.researcher_id = researcher.id
        pa.match_method = "manual_verified"
        pa.match_confidence = "exact"
        pa.needs_review = False
    else:
        pa.researcher_id = None
        pa.match_method = "unmatched"
        pa.match_confidence = "unmatched"
        pa.needs_review = False

    record_audit_log(
        db,
        action=f"author_match.{payload.action}",
        resource_type="publication_author",
        resource_id=str(pa.id),
        user_id=admin.id,
        user_role=admin.role,
        status="success",
        details={
            "researcher_id": str(pa.researcher_id) if pa.researcher_id else None,
            "match_method": pa.match_method,
        },
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {
        "authorship_id": str(pa.id),
        "researcher_id": str(pa.researcher_id) if pa.researcher_id else None,
        "match_method": pa.match_method,
        "needs_review": pa.needs_review,
    }
