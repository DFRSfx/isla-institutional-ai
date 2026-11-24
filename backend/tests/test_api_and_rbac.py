import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.permissions import UserRole
from app.models.audit import AuditLog
from app.models.conversation import Conversation
from app.models.researcher import Researcher
from app.services.excel_import import ExcelImportService
from app.services.maintenance import cleanup_expired_data
from app.services.portal_api import PortalFetchResult, PortalSyncService
from tests.conftest import auth_headers, build_synthetic_researchers_xlsx, make_user
from tests.test_portal_sync import SAMPLE_PORTAL_PAYLOAD_V1


def test_login_and_profile_permissions(client: TestClient, db_session: Session) -> None:
    make_user(
        db_session,
        email="admin@islagaia.pt",
        role=UserRole.ADMIN,
        password="AdminPassword123!",
    )

    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@islagaia.pt", "password": "AdminPassword123!"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["role"] == "admin"
    assert "sync_portal_api" in body["user"]["permissions"]

    me_resp = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == "admin@islagaia.pt"


def test_rbac_blocks_faculty_from_admin_ops_and_other_researchers(
    client: TestClient, db_session: Session
) -> None:
    # Preparar dados: importar docentes + sincronizar publicações
    ExcelImportService().import_workbook(
        db_session, build_synthetic_researchers_xlsx(), "docentes.xlsx"
    )
    PortalSyncService().sync_publications(
        db_session,
        prefetched=PortalFetchResult(
            records=SAMPLE_PORTAL_PAYLOAD_V1,
            source_version="1",
            reported_record_count=2,
            cache_ttl_minutes=1440,
            endpoint="/api/powerbi/publications",
            forced_nocache=False,
        ),
    )

    ana = db_session.scalar(select(Researcher).where(Researcher.email == "ana.silva@isla.test"))
    bruno = db_session.scalar(select(Researcher).where(Researcher.email == "bruno.costa@isla.test"))

    admin_user = make_user(db_session, email="admin@isla.test", role=UserRole.ADMIN)
    direction_user = make_user(db_session, email="direcao@isla.test", role=UserRole.DIRECTION)
    faculty_user = make_user(
        db_session,
        email="ana.silva@isla.test",
        role=UserRole.FACULTY,
        researcher_id=ana.id,
    )

    # 1. Docente e Direção não podem acionar sincronização API nem importação Excel
    for u in (faculty_user, direction_user):
        assert client.post("/api/v1/sync/portal", json={}, headers=auth_headers(u)).status_code == 403
        assert (
            client.post(
                "/api/v1/imports/excel/preview",
                files={"file": ("test.xlsx", build_synthetic_researchers_xlsx())},
                headers=auth_headers(u),
            ).status_code
            == 403
        )

    # 2. Admin consegue pré-visualizar Excel via API
    prev_resp = client.post(
        "/api/v1/imports/excel/preview",
        files={"file": ("test.xlsx", build_synthetic_researchers_xlsx())},
        headers=auth_headers(admin_user),
    )
    assert prev_resp.status_code == 200
    assert prev_resp.json()["total_rows"] == 4

    # 3. Docente só vê o próprio registo em /researchers e recebe 403 ao tentar aceder a outro docente
    fac_list = client.get("/api/v1/researchers", headers=auth_headers(faculty_user))
    assert fac_list.status_code == 200
    assert len(fac_list.json()) == 1
    assert fac_list.json()[0]["id"] == str(ana.id)

    own_resp = client.get(f"/api/v1/researchers/{ana.id}", headers=auth_headers(faculty_user))
    assert own_resp.status_code == 200

    other_resp = client.get(f"/api/v1/researchers/{bruno.id}", headers=auth_headers(faculty_user))
    assert other_resp.status_code == 403

    # Tentativa negada registada em audit_logs
    denied_logs = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "researcher.read.denied")
    ).all()
    assert len(denied_logs) == 1

    # Direção consegue listar todos os docentes
    dir_list = client.get("/api/v1/researchers", headers=auth_headers(direction_user))
    assert dir_list.status_code == 200
    assert len(dir_list.json()) == 4

    # 4. Filtragem de campos sensíveis em /publications
    fac_pubs = client.get("/api/v1/publications", headers=auth_headers(faculty_user)).json()
    pub1_fac = next(p for p in fac_pubs if p["portal_id"] == "PUB-001")
    assert pub1_fac["internal_notes"] is None
    assert pub1_fac["evaluation_score"] is None
    # Email do próprio autor (Ana) pode aparecer, mas o do coautor (Bruno) é ocultado
    assert pub1_fac["authors"][0]["raw_email"] == "ana.silva@isla.test"
    assert pub1_fac["authors"][1]["raw_email"] is None

    dir_pubs = client.get("/api/v1/publications", headers=auth_headers(direction_user)).json()
    pub1_dir = next(p for p in dir_pubs if p["portal_id"] == "PUB-001")
    assert pub1_dir["internal_notes"] == "Nota interna confidencial"
    assert pub1_dir["evaluation_score"] == "9.5"
    assert pub1_dir["authors"][1]["raw_email"] == "bruno.costa@isla.test"


def test_production_config_rejects_weak_jwt_secret_and_debug() -> None:
    strong_secret = secrets.token_hex(32)

    with pytest.raises(ValidationError):
        Settings(app_env="production")

    with pytest.raises(ValidationError):
        Settings(app_env="production", jwt_secret_key="too-short")

    # Segredo longo mas de baixa entropia deve ser recusado
    with pytest.raises(ValidationError):
        Settings(app_env="production", jwt_secret_key="x" * 40, debug=False)

    with pytest.raises(ValidationError):
        Settings(app_env="production", jwt_secret_key=strong_secret, debug=True)

    valid = Settings(app_env="production", jwt_secret_key=strong_secret, debug=False)
    assert valid.app_env == "production"


def test_httponly_cookie_session_and_logout(client: TestClient, db_session: Session) -> None:
    make_user(
        db_session,
        email="cookie.user@islagaia.pt",
        role=UserRole.DIRECTION,
        password="CookiePassword123!",
    )

    login_resp = client.post(
        "/api/v1/auth/login",
        json={"username": "cookie.user@islagaia.pt", "password": "CookiePassword123!"},
    )
    assert login_resp.status_code == 200
    assert "isla_ai_session=" in login_resp.headers.get("set-cookie", "")
    assert "httponly" in login_resp.headers.get("set-cookie", "").lower()

    # Autenticação via cookie sem cabeçalho Authorization
    me_resp = client.get("/api/v1/auth/me")
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == "cookie.user@islagaia.pt"

    logout_resp = client.post("/api/v1/auth/logout")
    assert logout_resp.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_retention_cleanup_deletes_expired_conversations_and_reports(
    db_session: Session, tmp_path: Path
) -> None:
    user = make_user(db_session, email="ret@islagaia.pt", role=UserRole.ADMIN)
    now = datetime.now(UTC)

    old_conv = Conversation(
        user_id=user.id,
        title="Antiga",
        created_at=now - timedelta(days=400),
        updated_at=now - timedelta(days=400),
    )
    fresh_conv = Conversation(user_id=user.id, title="Recente", created_at=now, updated_at=now)
    db_session.add_all([old_conv, fresh_conv])
    db_session.commit()

    # Criar 1 relatório expirado e 1 recente
    (tmp_path / "old-rep.pdf").write_bytes(b"%PDF-old")
    (tmp_path / "old-rep.xlsx").write_bytes(b"xlsx-old")
    (tmp_path / "old-rep.meta.json").write_text(
        json.dumps({"created_at": (now - timedelta(days=400)).isoformat()}),
        encoding="utf-8",
    )
    (tmp_path / "new-rep.pdf").write_bytes(b"%PDF-new")
    (tmp_path / "new-rep.meta.json").write_text(
        json.dumps({"created_at": now.isoformat()}),
        encoding="utf-8",
    )

    stats = cleanup_expired_data(db_session, retention_days=365, reports_dir=tmp_path, now=now)
    assert stats == {"deleted_conversations": 1, "deleted_reports": 1}
    assert not (tmp_path / "old-rep.pdf").exists()
    assert not (tmp_path / "old-rep.xlsx").exists()
    assert (tmp_path / "new-rep.pdf").exists()
    remaining_convs = db_session.scalars(select(Conversation)).all()
    assert [c.title for c in remaining_convs] == ["Recente"]
