from dataclasses import dataclass
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.ingestion import ExcelImport, SourceSnapshot
from app.models.user import User


@dataclass(frozen=True)
class ToolContext:
    db: Session
    user: User
    ip_address: str | None = None


def collect_latest_sources(db: Session) -> list[dict[str, Any]]:
    """Devolve metadados verificáveis das versões mais recentes de cada fonte de dados."""
    sources: list[dict[str, Any]] = []

    latest_portal = db.scalar(
        select(SourceSnapshot)
        .where(SourceSnapshot.source_type == "portal_api")
        .order_by(desc(SourceSnapshot.synced_at))
        .limit(1)
    )
    if latest_portal is not None:
        sources.append(
            {
                "source_type": "portal_api",
                "label": "Portal Científico do ISLA (API)",
                "endpoint_or_filename": latest_portal.endpoint_or_filename,
                "snapshot_id": str(latest_portal.id),
                "version": latest_portal.source_version or latest_portal.content_hash[:12],
                "content_hash": latest_portal.content_hash,
                "record_count": latest_portal.record_count,
                "synced_at": latest_portal.synced_at.isoformat(),
            }
        )

    latest_excel = db.scalar(
        select(ExcelImport)
        .where(ExcelImport.status == "completed")
        .order_by(desc(ExcelImport.imported_at))
        .limit(1)
    )
    if latest_excel is not None:
        sources.append(
            {
                "source_type": "excel_import",
                "label": "Excel de Docentes da Intranet",
                "endpoint_or_filename": latest_excel.filename,
                "snapshot_id": str(latest_excel.snapshot_id) if latest_excel.snapshot_id else str(latest_excel.id),
                "version": latest_excel.file_sha256[:12],
                "content_hash": latest_excel.file_sha256,
                "record_count": latest_excel.imported_rows,
                "synced_at": latest_excel.imported_at.isoformat(),
            }
        )

    return sources
