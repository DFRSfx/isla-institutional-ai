import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.database.session import SessionLocal
from app.models import SourceSnapshot
from app.services.audit import record_audit_log
from app.services.portal_api import PortalApiError, PortalSyncService

logger = logging.getLogger("isla.scheduler")


def _has_valid_portal_token(settings: Settings) -> bool:
    token = settings.portal_api_token.strip()
    return bool(token) and "CHANGE_ME" not in token.upper()


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def seconds_until_next_portal_sync(
    db: Session,
    *,
    interval_minutes: int,
    now: datetime | None = None,
) -> float:
    """
    Calcula quantos segundos faltam até à próxima sincronização devida do Portal Científico.
    Devolve 0.0 se não existir snapshot prévio ou se o último snapshot já tiver expirado.
    """
    current = _as_utc(now or datetime.now(UTC))
    latest = db.scalar(
        select(SourceSnapshot)
        .where(SourceSnapshot.source_type == "portal_api")
        .order_by(desc(SourceSnapshot.synced_at))
        .limit(1)
    )
    if latest is None or latest.synced_at is None:
        return 0.0

    elapsed = current - _as_utc(latest.synced_at)
    interval = timedelta(minutes=max(interval_minutes, 1))
    remaining = (interval - elapsed).total_seconds()
    return max(0.0, remaining)


def run_portal_auto_sync_if_due(
    db: Session,
    *,
    settings: Settings | None = None,
    sync_service: PortalSyncService | None = None,
    now: datetime | None = None,
) -> tuple[bool, float]:
    """
    Executa sincronização automática se o último snapshot tiver ultrapassado o intervalo
    configurado. Devolve `(executado, segundos_ate_proxima_verificacao)`.
    """
    cfg = settings or get_settings()
    interval_minutes = max(int(cfg.portal_auto_sync_interval_minutes), 1)
    interval_seconds = float(interval_minutes * 60)

    if not cfg.portal_auto_sync_enabled or not _has_valid_portal_token(cfg):
        return False, interval_seconds

    remaining = seconds_until_next_portal_sync(
        db,
        interval_minutes=interval_minutes,
        now=now,
    )
    if remaining > 0:
        return False, remaining

    service = sync_service or PortalSyncService()
    try:
        snapshot = service.sync_publications(db, nocache=False)
        record_audit_log(
            db,
            action="portal.sync.auto",
            resource_type="source_snapshot",
            resource_id=str(snapshot.id),
            status="success",
            details={
                "source_version": snapshot.source_version,
                "record_count": snapshot.record_count,
                "created": snapshot.records_created,
                "updated": snapshot.records_updated,
                "removed": snapshot.records_removed,
                "interval_minutes": interval_minutes,
            },
        )
        db.commit()
        logger.info(
            "Sincronização automática do Portal concluída (v%s, %d registos: +%d / ~%d / -%d).",
            snapshot.source_version,
            snapshot.record_count,
            snapshot.records_created,
            snapshot.records_updated,
            snapshot.records_removed,
        )
        return True, interval_seconds
    except (PortalApiError, RuntimeError, ValueError) as exc:
        db.rollback()
        record_audit_log(
            db,
            action="portal.sync.auto",
            resource_type="source_snapshot",
            resource_id="portal_api",
            status="error",
            details={"error": str(exc), "interval_minutes": interval_minutes},
        )
        db.commit()
        logger.warning("Falha na sincronização automática do Portal: %s", exc)
        # Em caso de erro transitório, tenta novamente dentro de 15 minutos
        return False, min(900.0, interval_seconds)


async def portal_auto_sync_loop(
    *,
    session_factory: Callable[[], Session] = SessionLocal,
    settings: Settings | None = None,
) -> None:
    """Loop em background gerido pelo lifespan do FastAPI (sem bloquear o event loop)."""
    cfg = settings or get_settings()
    if not cfg.portal_auto_sync_enabled:
        logger.info("Sincronização automática do Portal desativada (PORTAL_AUTO_SYNC_ENABLED=false).")
        return
    if not _has_valid_portal_token(cfg):
        logger.info("Sincronização automática do Portal em espera: PORTAL_API_TOKEN não configurado.")
        return

    logger.info(
        "Sincronização automática do Portal ativa (intervalo: %d minutos).",
        cfg.portal_auto_sync_interval_minutes,
    )

    def _tick() -> float:
        with session_factory() as db:
            _, wait_seconds = run_portal_auto_sync_if_due(db, settings=cfg)
            return wait_seconds

    while True:
        try:
            wait_seconds = await asyncio.to_thread(_tick)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Erro inesperado no scheduler de sincronização do Portal")
            wait_seconds = 900.0

        await asyncio.sleep(max(wait_seconds, 60.0))
