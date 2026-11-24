from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.core.permissions import Permission, has_permission
from app.database.session import get_db
from app.models.ingestion import SourceSnapshot
from app.models.user import User
from app.schemas import PortalSyncRequest, SourceSnapshotResponse
from app.services.portal_api import PortalApiError, PortalSyncService

router = APIRouter(prefix="/sync", tags=["sync"])


def get_portal_sync_service() -> PortalSyncService:
    return PortalSyncService()


@router.post("/portal", response_model=SourceSnapshotResponse)
def sync_portal_publications(
    payload: PortalSyncRequest,
    request: Request,
    user: User = Depends(require_permission(Permission.SYNC_PORTAL_API)),
    db: Session = Depends(get_db),
    sync_service: PortalSyncService = Depends(get_portal_sync_service),
) -> SourceSnapshotResponse:
    if payload.nocache and not has_permission(user.role, Permission.SYNC_PORTAL_API_FORCE_NOCACHE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas administradores podem forçar nocache=1.",
        )

    try:
        snapshot = sync_service.sync_publications(
            db,
            nocache=payload.nocache,
            synced_by=user.id,
            user_role=user.role,
            ip_address=request.client.host if request.client else None,
        )
    except PortalApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return SourceSnapshotResponse.model_validate(snapshot)


@router.get("/snapshots", response_model=list[SourceSnapshotResponse])
def list_snapshots(
    limit: int = 20,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SourceSnapshotResponse]:
    bounded_limit = max(1, min(limit, 100))
    snapshots = db.scalars(
        select(SourceSnapshot).order_by(desc(SourceSnapshot.synced_at)).limit(bounded_limit)
    ).all()
    return [SourceSnapshotResponse.model_validate(s) for s in snapshots]
