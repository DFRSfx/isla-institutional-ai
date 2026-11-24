from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.permissions import can_view_all_researchers, can_view_sensitive_fields
from app.database.session import get_db
from app.models.publication import Publication, PublicationAuthor
from app.models.researcher import Researcher
from app.models.school import School
from app.models.user import User
from app.schemas import (
    PublicationAuthorResponse,
    PublicationResponse,
    ResearcherResponse,
)
from app.services.audit import record_audit_log
from app.services.data_normalization import normalize_text

router = APIRouter(tags=["data"])


def _serialize_researcher(researcher: Researcher, include_email: bool) -> ResearcherResponse:
    return ResearcherResponse(
        id=researcher.id,
        ciencia_vitae_id=researcher.ciencia_vitae_id,
        ciencia_vitae_id_secondary=researcher.ciencia_vitae_id_secondary,
        name=researcher.name,
        email=researcher.email if include_email else None,
        school_code=researcher.school.code if researcher.school else researcher.school_code_raw,
        affiliation=researcher.affiliation,
        training_area=researcher.training_area,
        degree_code=researcher.degree_code,
        status_code=researcher.status_code,
        category=researcher.category,
        google_scholar_id=researcher.google_scholar_id,
        scholar_h_index=researcher.scholar_h_index,
        scopus_author_id=researcher.scopus_author_id,
        scopus_h_index=researcher.scopus_h_index,
        wos_researcher_id=researcher.wos_researcher_id,
        wos_h_index=researcher.wos_h_index,
        data_quality_flags=researcher.data_quality_flags,
    )


def _serialize_publication(publication: Publication, user: User) -> PublicationResponse:
    allow_sensitive = can_view_sensitive_fields(user.role)
    authors_out: list[PublicationAuthorResponse] = []
    for pa in publication.authors:
        is_self = user.researcher_id is not None and pa.researcher_id == user.researcher_id
        authors_out.append(
            PublicationAuthorResponse(
                author_order=pa.author_order,
                researcher_id=pa.researcher_id,
                raw_ciencia_vitae_id=pa.raw_ciencia_vitae_id,
                raw_name=pa.raw_name,
                raw_email=pa.raw_email if (allow_sensitive or is_self) else None,
                raw_school=pa.raw_school,
                raw_affiliation=pa.raw_affiliation,
                match_method=pa.match_method,
                match_confidence=pa.match_confidence,
                needs_review=pa.needs_review,
            )
        )

    return PublicationResponse(
        id=publication.id,
        portal_id=publication.portal_id,
        doi=publication.doi,
        doi_url=publication.doi_url,
        title=publication.title,
        year=publication.year,
        pub_type=publication.pub_type,
        status=publication.status,
        journal_name=publication.journal_name,
        conference_name=publication.conference_name,
        venue_name=publication.venue_name,
        venue_type=publication.venue_type,
        publisher=publication.publisher,
        quartile=publication.quartile,
        is_indexed_scopus=publication.is_indexed_scopus,
        is_indexed_wos=publication.is_indexed_wos,
        indexed_in=publication.indexed_in,
        citations_count=publication.citations_count,
        references_count=publication.references_count,
        is_open_access=publication.is_open_access,
        oa_status=publication.oa_status,
        oa_url=publication.oa_url,
        keywords=publication.keywords,
        apa_citation=publication.apa_citation,
        schools_raw=publication.schools_raw,
        internal_notes=publication.internal_notes if allow_sensitive else None,
        evaluation_score=publication.evaluation_score if allow_sensitive else None,
        authors=authors_out,
    )


@router.get("/researchers", response_model=list[ResearcherResponse])
def list_researchers(
    school: str | None = Query(default=None),
    category: str | None = Query(default=None),
    search: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ResearcherResponse]:
    stmt = select(Researcher).options(selectinload(Researcher.school))

    # Regra RBAC: docente só pode consultar os seus próprios dados internos
    if not can_view_all_researchers(user.role):
        if user.researcher_id is None:
            return []
        stmt = stmt.where(Researcher.id == user.researcher_id)
    else:
        if school:
            stmt = stmt.join(School, Researcher.school_id == School.id).where(
                School.code == school.strip().upper()
            )
        if category:
            stmt = stmt.where(Researcher.category == category.strip())
        if search:
            norm = normalize_text(search)
            stmt = stmt.where(Researcher.normalized_name.contains(norm))

    researchers = db.scalars(stmt.order_by(Researcher.name)).all()
    include_email = can_view_sensitive_fields(user.role) or not can_view_all_researchers(user.role)
    return [_serialize_researcher(r, include_email=include_email) for r in researchers]


@router.get("/researchers/{researcher_id}", response_model=ResearcherResponse)
def get_researcher(
    researcher_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ResearcherResponse:
    if not can_view_all_researchers(user.role) and user.researcher_id != researcher_id:
        record_audit_log(
            db,
            action="researcher.read.denied",
            resource_type="researcher",
            resource_id=str(researcher_id),
            user_id=user.id,
            user_role=user.role,
            status="denied",
            ip_address=request.client.host if request.client else None,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Um docente não tem autorização para consultar dados internos de outros docentes.",
        )

    researcher = db.scalar(
        select(Researcher)
        .options(selectinload(Researcher.school))
        .where(Researcher.id == researcher_id)
    )
    if researcher is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Docente não encontrado.")

    return _serialize_researcher(researcher, include_email=True)


@router.get("/publications", response_model=list[PublicationResponse])
def list_publications(
    year_from: int | None = Query(default=None),
    year_to: int | None = Query(default=None),
    quartile: str | None = Query(default=None),
    scopus: bool | None = Query(default=None),
    wos: bool | None = Query(default=None),
    researcher_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PublicationResponse]:
    stmt = (
        select(Publication)
        .options(selectinload(Publication.authors))
        .where(Publication.is_active.is_(True))
    )

    if year_from is not None:
        stmt = stmt.where(Publication.year >= year_from)
    if year_to is not None:
        stmt = stmt.where(Publication.year <= year_to)
    if quartile:
        stmt = stmt.where(Publication.quartile == quartile.strip().upper())
    if scopus is not None:
        stmt = stmt.where(Publication.is_indexed_scopus.is_(scopus))
    if wos is not None:
        stmt = stmt.where(Publication.is_indexed_wos.is_(wos))
    if researcher_id is not None:
        stmt = stmt.join(PublicationAuthor).where(PublicationAuthor.researcher_id == researcher_id)

    pubs = db.scalars(stmt.order_by(Publication.year.desc()).limit(limit)).unique().all()
    return [_serialize_publication(p, user) for p in pubs]
