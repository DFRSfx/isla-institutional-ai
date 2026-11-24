import hashlib
from collections import Counter
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any
from uuid import UUID

import openpyxl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ingestion import ExcelImport, SourceSnapshot
from app.models.researcher import Researcher
from app.services.audit import record_audit_log
from app.services.data_normalization import (
    clean_str,
    normalize_ciencia_vitae_id,
    normalize_email,
    normalize_text,
    parse_optional_int,
    resolve_school,
)
from app.services.portal_api import relink_publication_authors


class ExcelValidationError(ValueError):
    """Erro de validação estrutural de ficheiro Excel."""


# Mapeamento tolerante a maiúsculas, acentos e erros conhecidos de nomenclatura (ex.: 'Acivo')
HEADER_ALIASES: dict[str, str] = {
    "cienciavitae": "ciencia_vitae_primary",
    "ciencia vitae": "ciencia_vitae_primary",
    "ciencia_vitae": "ciencia_vitae_primary",
    "ciencia id": "ciencia_vitae_primary",
    "cienciavitae2": "ciencia_vitae_secondary",
    "ciencia vitae 2": "ciencia_vitae_secondary",
    "docente": "name",
    "nome": "name",
    "investigador": "name",
    "email": "email",
    "e-mail": "email",
    "acivo": "status_code",  # Typo confirmado no Excel da intranet
    "ativo": "status_code",
    "activo": "status_code",
    "estado": "status_code",
    "grau": "degree_code",
    "grau academico": "degree_code",
    "escola": "school_code",
    "afiliacao": "affiliation",
    "area formacao": "training_area",
    "google scholar": "google_scholar_id",
    "scholar h-index": "scholar_h_index",
    "scopus": "scopus_author_id",
    "scopus h-index": "scopus_h_index",
    "web of science": "wos_researcher_id",
    "wos h-index": "wos_h_index",
    "categoria": "category",
}


@dataclass
class ParsedRow:
    row_number: int
    raw: dict[str, Any]
    name: str | None
    normalized_name: str
    email: str | None
    ciencia_vitae_id: str | None
    ciencia_vitae_id_secondary: str | None
    school_code: str | None
    affiliation: str | None
    training_area: str | None
    degree_code: str | None
    status_code: str | None
    category: str | None
    google_scholar_id: str | None
    scholar_h_index: int | None
    scopus_author_id: str | None
    scopus_h_index: int | None
    wos_researcher_id: str | None
    wos_h_index: int | None
    flags: list[str] = field(default_factory=list)


@dataclass
class ExcelParseResult:
    filename: str
    file_sha256: str
    sheet_names: list[str]
    selected_sheet: str
    detected_headers: list[str]
    column_mapping: dict[str, str]
    inferred_types: dict[str, str]
    rows: list[ParsedRow]
    warnings: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    duplicates: list[dict[str, Any]]
    unconfirmed_code_distributions: dict[str, dict[str, int]]


def _infer_column_type(values: list[Any]) -> str:
    non_empty = [v for v in values if v is not None and str(v).strip() != ""]
    if not non_empty:
        return "empty"
    if all(parse_optional_int(v) is not None for v in non_empty):
        return "integer"
    if all("@" in str(v) for v in non_empty):
        return "email"
    return "string"


def _select_sheet(sheet_names: list[str], requested_sheet: str | None) -> str:
    if not sheet_names:
        raise ExcelValidationError("O ficheiro Excel não contém folhas.")
    if requested_sheet:
        if requested_sheet not in sheet_names:
            raise ExcelValidationError(
                f"Folha '{requested_sheet}' não encontrada. Disponíveis: {', '.join(sheet_names)}"
            )
        return requested_sheet
    for candidate in sheet_names:
        if normalize_text(candidate) in {"docentes", "investigadores", "researchers"}:
            return candidate
    return sheet_names[0]


class ExcelImportService:
    def parse_workbook(
        self,
        file_bytes: bytes,
        filename: str,
        *,
        sheet_name: str | None = None,
    ) -> ExcelParseResult:
        if not filename.lower().endswith(".xlsx"):
            raise ExcelValidationError("Apenas ficheiros .xlsx são suportados.")

        file_sha256 = hashlib.sha256(file_bytes).hexdigest()

        try:
            wb = openpyxl.load_workbook(BytesIO(file_bytes), read_only=True, data_only=True)
        except Exception as exc:
            raise ExcelValidationError(f"Não foi possível ler o ficheiro Excel: {exc}") from exc

        try:
            sheet_names = list(wb.sheetnames)
            selected_sheet = _select_sheet(sheet_names, sheet_name)
            ws = wb[selected_sheet]
            raw_rows = list(ws.iter_rows(values_only=True))
        finally:
            wb.close()

        # Remover linhas totalmente vazias no topo/fim
        non_empty_rows = [
            (idx + 1, row)
            for idx, row in enumerate(raw_rows)
            if any(cell is not None and str(cell).strip() != "" for cell in row)
        ]
        if not non_empty_rows:
            raise ExcelValidationError(f"A folha '{selected_sheet}' está vazia.")

        _, header_tuple = non_empty_rows[0]
        detected_headers = [
            clean_str(col) or f"column_{i + 1}"
            for i, col in enumerate(header_tuple)
        ]

        column_mapping: dict[str, str] = {}
        warnings: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        for idx, header in enumerate(detected_headers):
            norm_h = normalize_text(header)
            canonical = HEADER_ALIASES.get(norm_h)
            if canonical:
                column_mapping[header] = canonical
                if norm_h == "acivo":
                    warnings.append(
                        {
                            "row": 1,
                            "code": "header_typo_detected",
                            "message": "Cabeçalho 'Acivo' mapeado para 'status_code' (possível erro ortográfico de 'Ativo').",
                        }
                    )

        if "name" not in column_mapping.values():
            errors.append(
                {
                    "row": 1,
                    "code": "missing_required_column",
                    "message": "Não foi detetada nenhuma coluna de nome de docente ('Docente' ou 'Nome').",
                }
            )

        data_rows = non_empty_rows[1:]
        col_values: dict[str, list[Any]] = {h: [] for h in detected_headers}
        parsed_rows: list[ParsedRow] = []

        cv_tracker: dict[str, list[int]] = {}
        email_tracker: dict[str, list[int]] = {}
        scholar_tracker: dict[str, list[int]] = {}
        scopus_tracker: dict[str, list[int]] = {}
        wos_tracker: dict[str, list[int]] = {}

        status_codes = Counter()
        degree_codes = Counter()

        for excel_row_num, values in data_rows:
            raw_dict: dict[str, Any] = {}
            canonical_dict: dict[str, Any] = {}
            for i, header in enumerate(detected_headers):
                val = values[i] if i < len(values) else None
                raw_dict[header] = val
                col_values[header].append(val)
                if header in column_mapping:
                    canonical_dict[column_mapping[header]] = val

            flags: list[str] = []
            name = clean_str(canonical_dict.get("name"))
            if not name:
                errors.append(
                    {
                        "row": excel_row_num,
                        "code": "missing_name",
                        "message": "Linha sem nome de docente.",
                    }
                )
                continue

            raw_email = clean_str(canonical_dict.get("email"))
            email = normalize_email(raw_email)
            if raw_email and not email:
                flags.append("invalid_email_format")
                warnings.append(
                    {
                        "row": excel_row_num,
                        "code": "invalid_email_format",
                        "message": f"Email inválido na linha {excel_row_num}.",
                    }
                )

            cv1, cv1_warns = normalize_ciencia_vitae_id(canonical_dict.get("ciencia_vitae_primary"))
            cv2, cv2_warns = normalize_ciencia_vitae_id(canonical_dict.get("ciencia_vitae_secondary"))
            for w in cv1_warns + cv2_warns:
                flags.append(w)
                warnings.append({"row": excel_row_num, "code": "ciencia_vitae_warning", "message": w})

            if cv1 and cv2 and cv1 != cv2:
                flags.append("ciencia_vitae_columns_mismatch")
                warnings.append(
                    {
                        "row": excel_row_num,
                        "code": "ciencia_vitae_columns_mismatch",
                        "message": f"CienciaVitae ({cv1}) difere de CienciaVitae2 ({cv2}). Mantido o primário.",
                    }
                )

            chosen_cv = cv1 or cv2
            if not cv1 and cv2:
                flags.append("used_secondary_ciencia_vitae")

            school_code = clean_str(canonical_dict.get("school_code"))
            if school_code:
                school_code = school_code.upper()

            status_code = clean_str(canonical_dict.get("status_code"))
            if status_code:
                status_code = status_code.upper()
                status_codes[status_code] += 1
            else:
                status_codes["(vazio)"] += 1

            degree_code = clean_str(canonical_dict.get("degree_code"))
            if degree_code:
                degree_code = degree_code.upper()
                degree_codes[degree_code] += 1
            else:
                degree_codes["(vazio)"] += 1

            google_scholar_id = clean_str(canonical_dict.get("google_scholar_id"))
            scopus_author_id = clean_str(canonical_dict.get("scopus_author_id"))
            wos_researcher_id = clean_str(canonical_dict.get("wos_researcher_id"))

            if chosen_cv:
                cv_tracker.setdefault(chosen_cv, []).append(excel_row_num)
            if email:
                email_tracker.setdefault(email, []).append(excel_row_num)
            if google_scholar_id:
                scholar_tracker.setdefault(google_scholar_id, []).append(excel_row_num)
            if scopus_author_id:
                scopus_tracker.setdefault(scopus_author_id, []).append(excel_row_num)
            if wos_researcher_id:
                wos_tracker.setdefault(wos_researcher_id, []).append(excel_row_num)

            parsed_rows.append(
                ParsedRow(
                    row_number=excel_row_num,
                    raw={k: (str(v) if v is not None else None) for k, v in raw_dict.items()},
                    name=name,
                    normalized_name=normalize_text(name),
                    email=email,
                    ciencia_vitae_id=chosen_cv,
                    ciencia_vitae_id_secondary=cv2,
                    school_code=school_code,
                    affiliation=clean_str(canonical_dict.get("affiliation")),
                    training_area=clean_str(canonical_dict.get("training_area")),
                    degree_code=degree_code,
                    status_code=status_code,
                    category=clean_str(canonical_dict.get("category")),
                    google_scholar_id=google_scholar_id,
                    scholar_h_index=parse_optional_int(canonical_dict.get("scholar_h_index")),
                    scopus_author_id=scopus_author_id,
                    scopus_h_index=parse_optional_int(canonical_dict.get("scopus_h_index")),
                    wos_researcher_id=wos_researcher_id,
                    wos_h_index=parse_optional_int(canonical_dict.get("wos_h_index")),
                    flags=flags,
                )
            )

        duplicates: list[dict[str, Any]] = []
        dup_row_flags: dict[int, list[str]] = {}
        for field_name, tracker in [
            ("ciencia_vitae_id", cv_tracker),
            ("email", email_tracker),
            ("google_scholar_id", scholar_tracker),
            ("scopus_author_id", scopus_tracker),
            ("wos_researcher_id", wos_tracker),
        ]:
            for val, row_nums in tracker.items():
                if len(row_nums) > 1:
                    duplicates.append(
                        {"field": field_name, "value": val, "rows": row_nums}
                    )
                    warnings.append(
                        {
                            "row": row_nums[0],
                            "code": f"duplicate_{field_name}",
                            "message": f"Identificador '{field_name}' duplicado nas linhas {row_nums}.",
                        }
                    )
                    for rn in row_nums:
                        dup_row_flags.setdefault(rn, []).append(f"duplicate_{field_name}")

        for prow in parsed_rows:
            if prow.row_number in dup_row_flags:
                prow.flags.extend(dup_row_flags[prow.row_number])

        inferred_types = {h: _infer_column_type(vals) for h, vals in col_values.items()}

        return ExcelParseResult(
            filename=filename,
            file_sha256=file_sha256,
            sheet_names=sheet_names,
            selected_sheet=selected_sheet,
            detected_headers=detected_headers,
            column_mapping=column_mapping,
            inferred_types=inferred_types,
            rows=parsed_rows,
            warnings=warnings,
            errors=errors,
            duplicates=duplicates,
            unconfirmed_code_distributions={
                "status_code": dict(status_codes),
                "degree_code": dict(degree_codes),
            },
        )

    def preview(
        self,
        file_bytes: bytes,
        filename: str,
        *,
        sheet_name: str | None = None,
        sample_size: int = 10,
    ) -> dict[str, Any]:
        parsed = self.parse_workbook(file_bytes, filename, sheet_name=sheet_name)
        sample_rows = [
            {
                "row_number": r.row_number,
                "name": r.name,
                "email": r.email,
                "ciencia_vitae_id": r.ciencia_vitae_id,
                "ciencia_vitae_id_secondary": r.ciencia_vitae_id_secondary,
                "school_code": r.school_code,
                "degree_code": r.degree_code,
                "status_code": r.status_code,
                "category": r.category,
                "flags": r.flags,
            }
            for r in parsed.rows[:sample_size]
        ]
        return {
            "filename": parsed.filename,
            "file_sha256": parsed.file_sha256,
            "sheet_names": parsed.sheet_names,
            "selected_sheet": parsed.selected_sheet,
            "detected_headers": parsed.detected_headers,
            "column_mapping": parsed.column_mapping,
            "inferred_types": parsed.inferred_types,
            "total_rows": len(parsed.rows),
            "with_ciencia_vitae_id": sum(1 for r in parsed.rows if r.ciencia_vitae_id),
            "distinct_ciencia_vitae_ids": len(
                {r.ciencia_vitae_id for r in parsed.rows if r.ciencia_vitae_id}
            ),
            "duplicates": parsed.duplicates,
            "warnings": parsed.warnings,
            "errors": parsed.errors,
            "unconfirmed_code_distributions": parsed.unconfirmed_code_distributions,
            "sample_rows": sample_rows,
        }

    def import_workbook(
        self,
        db: Session,
        file_bytes: bytes,
        filename: str,
        *,
        imported_by: UUID | None = None,
        user_role: str | None = None,
        sheet_name: str | None = None,
        ip_address: str | None = None,
    ) -> ExcelImport:
        parsed = self.parse_workbook(file_bytes, filename, sheet_name=sheet_name)
        if parsed.errors:
            raise ExcelValidationError(
                f"Excel inválido ({len(parsed.errors)} erro(s)): {parsed.errors[0]['message']}"
            )

        snapshot = SourceSnapshot(
            source_type="excel_import",
            source_version=parsed.file_sha256[:12],
            endpoint_or_filename=parsed.filename,
            content_hash=parsed.file_sha256,
            record_count=len(parsed.rows),
            synced_by=imported_by,
            metadata_json={
                "selected_sheet": parsed.selected_sheet,
                "sheet_names": parsed.sheet_names,
                "unconfirmed_code_distributions": parsed.unconfirmed_code_distributions,
            },
        )
        db.add(snapshot)
        db.flush()

        excel_import = ExcelImport(
            filename=parsed.filename,
            file_sha256=parsed.file_sha256,
            sheet_names=parsed.sheet_names,
            selected_sheet=parsed.selected_sheet,
            detected_headers=parsed.detected_headers,
            total_rows=len(parsed.rows),
            duplicate_count=len(parsed.duplicates),
            warning_count=len(parsed.warnings),
            error_count=len(parsed.errors),
            warnings=parsed.warnings,
            errors=parsed.errors,
            status="completed",
            snapshot_id=snapshot.id,
            imported_by=imported_by,
        )
        db.add(excel_import)
        db.flush()

        created_count = 0
        updated_count = 0
        seen_emails_in_batch: set[str] = set()

        for row in parsed.rows:
            school = resolve_school(db, row.school_code)

            existing: Researcher | None = None
            if row.email:
                if row.email in seen_emails_in_batch:
                    # Evita violar constraint UNIQUE(email) em duplicados no mesmo Excel
                    continue
                seen_emails_in_batch.add(row.email)
                existing = db.scalar(select(Researcher).where(Researcher.email == row.email))

            if existing is None and row.ciencia_vitae_id and "duplicate_ciencia_vitae_id" not in row.flags:
                candidates = list(
                    db.scalars(
                        select(Researcher).where(
                            Researcher.ciencia_vitae_id == row.ciencia_vitae_id
                        )
                    ).all()
                )
                if len(candidates) == 1:
                    existing = candidates[0]

            if existing is None:
                researcher = Researcher(
                    ciencia_vitae_id=row.ciencia_vitae_id,
                    ciencia_vitae_id_secondary=row.ciencia_vitae_id_secondary,
                    name=row.name or "",
                    normalized_name=row.normalized_name,
                    email=row.email,
                    school_id=school.id if school else None,
                    school_code_raw=row.school_code,
                    affiliation=row.affiliation,
                    training_area=row.training_area,
                    degree_code=row.degree_code,
                    status_code=row.status_code,
                    category=row.category,
                    google_scholar_id=row.google_scholar_id,
                    scholar_h_index=row.scholar_h_index,
                    scopus_author_id=row.scopus_author_id,
                    scopus_h_index=row.scopus_h_index,
                    wos_researcher_id=row.wos_researcher_id,
                    wos_h_index=row.wos_h_index,
                    last_import_id=excel_import.id,
                    data_quality_flags=row.flags,
                    raw_payload=row.raw,
                )
                db.add(researcher)
                created_count += 1
            else:
                existing.ciencia_vitae_id = row.ciencia_vitae_id
                existing.ciencia_vitae_id_secondary = row.ciencia_vitae_id_secondary
                existing.name = row.name or existing.name
                existing.normalized_name = row.normalized_name
                if row.email:
                    existing.email = row.email
                existing.school_id = school.id if school else None
                existing.school_code_raw = row.school_code
                existing.affiliation = row.affiliation
                existing.training_area = row.training_area
                existing.degree_code = row.degree_code
                existing.status_code = row.status_code
                existing.category = row.category
                existing.google_scholar_id = row.google_scholar_id
                existing.scholar_h_index = row.scholar_h_index
                existing.scopus_author_id = row.scopus_author_id
                existing.scopus_h_index = row.scopus_h_index
                existing.wos_researcher_id = row.wos_researcher_id
                existing.wos_h_index = row.wos_h_index
                existing.last_import_id = excel_import.id
                existing.data_quality_flags = row.flags
                existing.raw_payload = row.raw
                updated_count += 1

        db.flush()
        relink_stats = relink_publication_authors(db)

        excel_import.imported_rows = created_count + updated_count
        excel_import.created_rows = created_count
        excel_import.updated_rows = updated_count

        snapshot.records_created = created_count
        snapshot.records_updated = updated_count
        snapshot.diff_summary = {
            "duplicate_count": len(parsed.duplicates),
            "warning_count": len(parsed.warnings),
            "relinked_publication_authors": relink_stats,
        }

        record_audit_log(
            db,
            action="excel.import",
            resource_type="excel_import",
            resource_id=str(excel_import.id),
            user_id=imported_by,
            user_role=user_role,
            status="success",
            details={
                "filename": parsed.filename,
                "selected_sheet": parsed.selected_sheet,
                "total_rows": excel_import.total_rows,
                "created_rows": created_count,
                "updated_rows": updated_count,
                "duplicate_count": excel_import.duplicate_count,
                "warning_count": excel_import.warning_count,
                "relinked_authors": relink_stats,
            },
            ip_address=ip_address,
        )
        db.commit()
        db.refresh(excel_import)
        return excel_import
