import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.conversation import Conversation
from app.services.audit import record_audit_log


def cleanup_expired_data(
    db: Session,
    *,
    retention_days: int | None = None,
    reports_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    """
    Aplica a política de retenção de conversações e ficheiros de relatórios gerados
    (Secção 8 — Proteção de Dados / RGPD).
    """
    settings = get_settings()
    days = retention_days if retention_days is not None else settings.conversation_retention_days
    reference_now = now or datetime.now(UTC)
    cutoff = reference_now - timedelta(days=days)

    # 1. Eliminar conversações (e mensagens em cascata) anteriores à janela de retenção
    expired_convs = list(
        db.scalars(select(Conversation).where(Conversation.updated_at < cutoff)).all()
    )
    deleted_conversations = len(expired_convs)
    for conv in expired_convs:
        db.delete(conv)

    # 2. Eliminar ficheiros de relatórios (.meta.json, .pdf, .xlsx) expirados
    target_dir = reports_dir or Path(settings.reports_output_dir)
    deleted_reports = 0
    if target_dir.exists():
        for meta_path in target_dir.glob("*.meta.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                created_raw = meta.get("created_at")
                created_at = (
                    datetime.fromisoformat(created_raw)
                    if created_raw
                    else datetime.fromtimestamp(meta_path.stat().st_mtime, tz=UTC)
                )
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=UTC)
            except (ValueError, OSError):
                continue

            if created_at < cutoff:
                report_id = meta_path.name.removesuffix(".meta.json")
                for ext in (".meta.json", ".pdf", ".xlsx"):
                    f = target_dir / f"{report_id}{ext}"
                    if f.exists():
                        f.unlink()
                deleted_reports += 1

    record_audit_log(
        db,
        action="maintenance.retention_cleanup",
        resource_type="system",
        status="success",
        details={
            "retention_days": days,
            "deleted_conversations": deleted_conversations,
            "deleted_reports": deleted_reports,
        },
    )
    db.commit()
    return {
        "deleted_conversations": deleted_conversations,
        "deleted_reports": deleted_reports,
    }
