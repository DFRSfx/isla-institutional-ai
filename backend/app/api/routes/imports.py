from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.config import get_settings
from app.core.permissions import Permission
from app.database.session import get_db
from app.models.ingestion import ExcelImport
from app.models.user import User
from app.schemas import ExcelImportResponse
from app.services.excel_import import ExcelImportService, ExcelValidationError

router = APIRouter(prefix="/imports", tags=["imports"])


async def _read_validated_excel_bytes(file: UploadFile) -> tuple[bytes, str]:
    settings = get_settings()
    filename = file.filename or "upload.xlsx"
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Apenas ficheiros .xlsx são aceites.",
        )
    content = await file.read()
    max_bytes = settings.max_excel_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Ficheiro excede o limite de {settings.max_excel_upload_mb} MB.",
        )
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ficheiro vazio.",
        )
    return content, filename


@router.post("/excel/preview")
async def preview_excel(
    file: UploadFile = File(...),
    sheet_name: str | None = Query(default=None),
    sample_size: int = Query(default=10, ge=1, le=50),
    _: User = Depends(require_permission(Permission.IMPORT_EXCEL)),
) -> dict[str, Any]:
    content, filename = await _read_validated_excel_bytes(file)
    service = ExcelImportService()
    try:
        return service.preview(
            content,
            filename,
            sheet_name=sheet_name,
            sample_size=sample_size,
        )
    except ExcelValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/excel", response_model=ExcelImportResponse)
async def import_excel(
    request: Request,
    file: UploadFile = File(...),
    sheet_name: str | None = Query(default=None),
    user: User = Depends(require_permission(Permission.IMPORT_EXCEL)),
    db: Session = Depends(get_db),
) -> ExcelImportResponse:
    content, filename = await _read_validated_excel_bytes(file)
    service = ExcelImportService()
    try:
        record = service.import_workbook(
            db,
            content,
            filename,
            imported_by=user.id,
            user_role=user.role,
            sheet_name=sheet_name,
            ip_address=request.client.host if request.client else None,
        )
    except ExcelValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return ExcelImportResponse.model_validate(record)


@router.get("/excel", response_model=list[ExcelImportResponse])
def list_excel_imports(
    limit: int = Query(default=20, ge=1, le=100),
    _: User = Depends(require_permission(Permission.IMPORT_EXCEL)),
    db: Session = Depends(get_db),
) -> list[ExcelImportResponse]:
    records = db.scalars(
        select(ExcelImport).order_by(desc(ExcelImport.imported_at)).limit(limit)
    ).all()
    return [ExcelImportResponse.model_validate(r) for r in records]
