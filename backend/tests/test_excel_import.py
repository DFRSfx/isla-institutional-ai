from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.ingestion import ExcelImport, SourceSnapshot
from app.models.researcher import Researcher
from app.models.school import School
from app.services.excel_import import ExcelImportService
from tests.conftest import build_synthetic_researchers_xlsx


def test_excel_preview_detects_anomalies_without_db_writes(db_session: Session) -> None:
    xlsx_bytes = build_synthetic_researchers_xlsx()
    service = ExcelImportService()

    preview = service.preview(xlsx_bytes, "docentes_teste.xlsx")

    assert preview["sheet_names"] == ["Docentes"]
    assert preview["selected_sheet"] == "Docentes"
    assert preview["total_rows"] == 4
    assert preview["with_ciencia_vitae_id"] == 4
    assert preview["distinct_ciencia_vitae_ids"] == 3
    assert preview["errors"] == []

    # Deve detetar o typo 'Acivo', o parêntese extra, a divergência CV vs CV2 e o duplicado
    warning_codes = {w["code"] for w in preview["warnings"]}
    assert "header_typo_detected" in warning_codes
    assert "ciencia_vitae_warning" in warning_codes
    assert "ciencia_vitae_columns_mismatch" in warning_codes
    assert "duplicate_ciencia_vitae_id" in warning_codes

    # Códigos brutos preservados sem tradução presumida
    assert preview["unconfirmed_code_distributions"]["status_code"] == {
        "Y": 1,
        "A": 1,
        "N": 1,
        "O": 1,
    }
    assert preview["unconfirmed_code_distributions"]["degree_code"] == {
        "D": 1,
        "M": 1,
        "L": 1,
        "N": 1,
    }

    # Pré-visualização não grava nada na BD
    assert db_session.scalars(select(Researcher)).all() == []


def test_excel_import_persists_normalized_records_and_is_idempotent(db_session: Session) -> None:
    xlsx_bytes = build_synthetic_researchers_xlsx()
    service = ExcelImportService()

    first_import = service.import_workbook(db_session, xlsx_bytes, "docentes_teste.xlsx")
    assert first_import.total_rows == 4
    assert first_import.created_rows == 4
    assert first_import.updated_rows == 0
    assert first_import.duplicate_count == 1

    schools = {s.code: s for s in db_session.scalars(select(School)).all()}
    assert set(schools.keys()) == {"EST", "ESG"}

    researchers = {r.email: r for r in db_session.scalars(select(Researcher)).all()}
    assert len(researchers) == 4
    assert researchers["ana.silva@isla.test"].status_code == "Y"
    assert researchers["ana.silva@isla.test"].degree_code == "D"
    assert "duplicate_ciencia_vitae_id" in researchers["ana.silva@isla.test"].data_quality_flags
    assert researchers["bruno.costa@isla.test"].ciencia_vitae_id_secondary == "CCCC-2222-DDDD"
    assert any(
        f.startswith("malformed_ciencia_vitae_sanitized")
        for f in researchers["bruno.costa@isla.test"].data_quality_flags
    )
    assert (
        "ciencia_vitae_columns_mismatch"
        in researchers["carla.duarte@isla.test"].data_quality_flags
    )

    # Histórico de importação, snapshot e auditoria criados
    assert len(db_session.scalars(select(ExcelImport)).all()) == 1
    assert len(db_session.scalars(select(SourceSnapshot)).all()) == 1
    assert len(db_session.scalars(select(AuditLog)).all()) == 1

    # Reimportação atualiza em vez de duplicar linhas
    second_import = service.import_workbook(db_session, xlsx_bytes, "docentes_teste.xlsx")
    assert second_import.created_rows == 0
    assert second_import.updated_rows == 4
    assert len(db_session.scalars(select(Researcher)).all()) == 4
