import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.mixins import UUIDPrimaryKeyMixin, utcnow


class SourceSnapshot(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "source_snapshots"

    source_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    endpoint_or_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)

    record_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_unchanged: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_removed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    cache_ttl_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forced_nocache: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    diff_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    synced_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        index=True,
        nullable=False,
    )


class ExcelImport(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "excel_imports"

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    sheet_names: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    selected_sheet: Mapped[str] = mapped_column(String(128), nullable=False)
    detected_headers: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    imported_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    warning_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    warnings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="completed", nullable=False)

    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("source_snapshots.id"),
        nullable=True,
        index=True,
    )
    imported_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        index=True,
        nullable=False,
    )

    importer = relationship("User", back_populates="excel_imports")
    snapshot = relationship("SourceSnapshot")
