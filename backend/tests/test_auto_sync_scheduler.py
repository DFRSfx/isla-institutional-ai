from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import SourceSnapshot
from app.models.audit import AuditLog
from app.services.portal_api import PortalFetchResult, PortalSyncService
from app.services.scheduler import run_portal_auto_sync_if_due, seconds_until_next_portal_sync
from tests.test_portal_sync import SAMPLE_PORTAL_PAYLOAD_V1


class _StubPortalSyncService(PortalSyncService):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def sync_publications(
        self,
        db: Session,
        *,
        nocache: bool = False,
        triggered_by_user_id: object = None,
        prefetched: PortalFetchResult | None = None,
    ) -> SourceSnapshot:
        _ = (nocache, triggered_by_user_id, prefetched)
        self.calls += 1
        return super().sync_publications(
            db,
            prefetched=PortalFetchResult(
                records=SAMPLE_PORTAL_PAYLOAD_V1,
                source_version="41",
                reported_record_count=len(SAMPLE_PORTAL_PAYLOAD_V1),
                cache_ttl_minutes=720,
                endpoint="/api/powerbi/publications",
                forced_nocache=False,
            ),
        )


def test_auto_sync_respects_12h_interval_and_records_audit(db_session: Session) -> None:
    cfg = Settings(
        _env_file=None,
        portal_api_token="valid-test-token",
        portal_auto_sync_enabled=True,
        portal_auto_sync_interval_minutes=720,
    )
    stub = _StubPortalSyncService()
    t0 = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)

    # 1. Sem snapshot prévio -> deve sincronizar imediatamente
    assert seconds_until_next_portal_sync(db_session, interval_minutes=720, now=t0) == 0.0
    ran, next_wait = run_portal_auto_sync_if_due(
        db_session,
        settings=cfg,
        sync_service=stub,
        now=t0,
    )
    assert ran is True
    assert stub.calls == 1
    assert next_wait == 720 * 60

    audit = db_session.scalar(select(AuditLog).where(AuditLog.action == "portal.sync.auto"))
    assert audit is not None
    assert audit.status == "success"

    # 2. 2 horas depois -> ainda dentro do TTL de 12h, não deve voltar a chamar a API
    latest = db_session.scalar(
        select(SourceSnapshot).where(SourceSnapshot.source_type == "portal_api")
    )
    assert latest is not None
    latest.synced_at = t0
    db_session.commit()

    t_2h = t0 + timedelta(hours=2)
    ran_2h, wait_2h = run_portal_auto_sync_if_due(
        db_session,
        settings=cfg,
        sync_service=stub,
        now=t_2h,
    )
    assert ran_2h is False
    assert stub.calls == 1
    assert 9.9 * 3600 < wait_2h <= 10 * 3600

    # 3. 12h05 depois -> snapshot expirou, deve sincronizar novamente
    t_12h = t0 + timedelta(hours=12, minutes=5)
    ran_12h, _ = run_portal_auto_sync_if_due(
        db_session,
        settings=cfg,
        sync_service=stub,
        now=t_12h,
    )
    assert ran_12h is True
    assert stub.calls == 2
