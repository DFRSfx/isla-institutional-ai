import json
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.permissions import Permission, UserRole, has_permission
from app.database.session import get_db
from app.models.user import User
from app.services.audit import record_audit_log

router = APIRouter(prefix="/reports", tags=["reports"])


def get_reports_dir() -> Path:
    return Path(get_settings().reports_output_dir)


@router.get("/{report_id}/{fmt}")
def download_report(
    report_id: UUID,
    fmt: Literal["pdf", "excel"],
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    reports_dir: Path = Depends(get_reports_dir),
) -> Response:
    required_perm = (
        Permission.GENERATE_PDF_REPORT if fmt == "pdf" else Permission.GENERATE_EXCEL_REPORT
    )
    if not has_permission(user.role, required_perm):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sem permissões para descarregar este formato de relatório.",
        )

    meta_path = reports_dir / f"{report_id}.meta.json"
    if not meta_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Relatório não encontrado.",
        )

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("owner_id") != str(user.id) and user.role != UserRole.ADMIN.value:
        record_audit_log(
            db,
            action="report.download.denied",
            resource_type="report",
            resource_id=str(report_id),
            user_id=user.id,
            user_role=user.role,
            status="denied",
            ip_address=request.client.host if request.client else None,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sem autorização para aceder a este relatório.",
        )

    ext = "pdf" if fmt == "pdf" else "xlsx"
    file_path = reports_dir / f"{report_id}.{ext}"
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ficheiro de relatório em falta.",
        )

    record_audit_log(
        db,
        action=f"report.download.{fmt}",
        resource_type="report",
        resource_id=str(report_id),
        user_id=user.id,
        user_role=user.role,
        status="success",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()

    media_type = (
        "application/pdf"
        if fmt == "pdf"
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return Response(
        content=file_path.read_bytes(),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="isla_relatorio_{report_id}.{ext}"'
        },
    )
