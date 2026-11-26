import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin, utcnow


class Publication(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "publications"

    portal_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    doi: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    doi_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    title: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(512), index=True, nullable=False)
    year: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)

    pub_type: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    status: Mapped[str | None] = mapped_column(String(128), nullable=True)

    journal_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    conference_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    venue_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    venue_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(255), nullable=True)
    book_title: Mapped[str | None] = mapped_column(String(512), nullable=True)

    quartile: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    is_indexed_scopus: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)
    is_indexed_wos: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)
    indexed_in: Mapped[str | None] = mapped_column(String(255), nullable=True)

    citations_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    references_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    is_open_access: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    oa_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    oa_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    keywords: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    apa_citation: Mapped[str | None] = mapped_column(Text, nullable=True)

    isbn: Mapped[str | None] = mapped_column(String(255), nullable=True)
    issn: Mapped[str | None] = mapped_column(String(255), nullable=True)
    handle: Mapped[str | None] = mapped_column(String(512), nullable=True)
    scopus_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    wos_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    openalex_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    scholar_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    scholar_article_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    schools_raw: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    affiliations_raw: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    # Campos sensíveis — ocultados para perfis sem VIEW_SENSITIVE_FIELDS
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluation_score: Mapped[str | None] = mapped_column(String(64), nullable=True)

    record_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)

    last_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("source_snapshots.id"),
        nullable=True,
        index=True,
    )
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    authors = relationship(
        "PublicationAuthor",
        back_populates="publication",
        cascade="all, delete-orphan",
        order_by="PublicationAuthor.author_order",
    )
    last_snapshot = relationship("SourceSnapshot")


class PublicationAuthor(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "publication_authors"

    publication_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("publications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    researcher_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("researchers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    author_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    raw_ciencia_vitae_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    raw_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_email: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    raw_school: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_affiliation: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ciencia_vitae_id | institutional_email | name_hypothesis | unmatched
    match_method: Mapped[str] = mapped_column(String(32), default="unmatched", nullable=False)
    # exact | needs_validation | unmatched
    match_confidence: Mapped[str] = mapped_column(String(32), default="unmatched", nullable=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    publication = relationship("Publication", back_populates="authors")
    researcher = relationship("Researcher", back_populates="authorships")
