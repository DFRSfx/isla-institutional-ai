import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.auth import get_institutional_auth_client
from app.core.config import Settings
from app.core.permissions import UserRole
from app.database.session import get_db
from app.main import create_app
from app.models.audit import AuditLog
from app.models.researcher import Researcher
from app.models.user import User
from app.services.excel_import import ExcelImportService
from app.services.institutional_auth import InstitutionalAuthClient
from tests.conftest import build_synthetic_researchers_xlsx, make_user


def _make_mock_auth_client(
    responses_by_user: dict[str, tuple[int, dict]],
    *,
    api_key: str = "iag_live_test_token",
    origin: str = "https://app.islagaia.pt",
) -> tuple[InstitutionalAuthClient, list[dict]]:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode("utf-8")
        captured.append(
            {
                "url": str(request.url),
                "api_key": request.headers.get("X-API-Key"),
                "origin": request.headers.get("Origin"),
                "body": body,
            }
        )
        if request.headers.get("X-API-Key") != api_key:
            return httpx.Response(401, json={"error": "invalid api key"})
        payload = request.json() if hasattr(request, "json") else None
        import json as _json

        parsed = payload if payload is not None else _json.loads(body)
        uname = parsed.get("username", "")
        if uname in responses_by_user:
            code, resp_json = responses_by_user[uname]
            return httpx.Response(code, json=resp_json)
        return httpx.Response(401, json={"success": False, "error": "Invalid credentials"})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    settings = Settings(
        auth_mode="hybrid",
        institutional_auth_base_url="https://cksi-dev.islagaia.pt",
        institutional_auth_api_key=api_key,
        institutional_auth_origin=origin,
    )
    return InstitutionalAuthClient(settings=settings, http_client=http_client), captured


def _build_client(db_session: Session, auth_client: InstitutionalAuthClient) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: (yield db_session)
    app.dependency_overrides[get_institutional_auth_client] = lambda: auth_client
    return TestClient(app)


def test_institutional_ldap_login_provisions_teacher_and_links_researcher(
    db_session: Session,
) -> None:
    # Importar docentes sintéticos (inclui ana.silva@isla.test)
    ExcelImportService().import_workbook(
        db_session, build_synthetic_researchers_xlsx(), "docentes.xlsx"
    )
    ana_res = db_session.scalar(select(Researcher).where(Researcher.email == "ana.silva@isla.test"))
    assert ana_res is not None

    auth_client, captured = _make_mock_auth_client(
        {
            "asilva": (
                200,
                {
                    "success": True,
                    "user": {
                        "username": "asilva",
                        "displayName": "Ana Silva",
                        "email": "ana.silva@isla.test",
                    },
                    "token": "eyJhbGciOiJSUzI1NiJ9.mock",
                    "role": "teacher",
                },
            )
        }
    )

    with _build_client(db_session, auth_client) as client:
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": "asilva", "password": "ldap-password"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["user"]["email"] == "ana.silva@isla.test"
        assert body["user"]["role"] == "faculty"
        assert body["user"]["researcher_id"] == str(ana_res.id)

        # Verifica cabeçalhos X-API-Key e Origin enviados ao endpoint /v1/token
        assert len(captured) == 1
        assert captured[0]["url"] == "https://cksi-dev.islagaia.pt/v1/token"
        assert captured[0]["api_key"] == "iag_live_test_token"
        assert captured[0]["origin"] == "https://app.islagaia.pt"

        # Promove localmente para 'direction' -> próximo login LDAP não deve rebaixar para 'faculty'
        db_user = db_session.scalar(select(User).where(User.email == "ana.silva@isla.test"))
        assert db_user is not None
        db_user.role = UserRole.DIRECTION.value
        db_session.commit()

        resp2 = client.post(
            "/api/v1/auth/login",
            json={"username": "asilva", "password": "ldap-password"},
        )
        assert resp2.status_code == 200
        assert resp2.json()["user"]["role"] == "direction"


def test_institutional_ldap_rejects_student_role_by_default_and_logs_audit(
    db_session: Session,
) -> None:
    auth_client, _ = _make_mock_auth_client(
        {
            "a22307370": (
                200,
                {
                    "success": True,
                    "user": {
                        "username": "a22307370",
                        "displayName": "Aluno Exemplo",
                        "email": "a22307370@mail.islagaia.pt",
                    },
                    "token": "eyJhbGciOiJSUzI1NiJ9.mock",
                    "role": "student",
                },
            )
        }
    )

    with _build_client(db_session, auth_client) as client:
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": "a22307370", "password": "secret"},
        )
        assert resp.status_code == 403

    denied = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "auth.login.forbidden_role")
    ).all()
    assert len(denied) == 1


def test_hybrid_mode_falls_back_to_local_admin_when_ldap_rejects(db_session: Session) -> None:
    make_user(
        db_session,
        email="local.admin@islagaia.pt",
        role=UserRole.ADMIN,
        password="LocalPassword123!",
    )
    auth_client, _ = _make_mock_auth_client({})

    with _build_client(db_session, auth_client) as client:
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": "local.admin@islagaia.pt", "password": "LocalPassword123!"},
        )
        assert resp.status_code == 200
        assert resp.json()["user"]["role"] == "admin"


def test_institutional_mode_never_falls_back_to_local_when_unconfigured(
    db_session: Session, monkeypatch
) -> None:
    make_user(
        db_session,
        email="local.admin@islagaia.pt",
        role=UserRole.ADMIN,
        password="LocalPassword123!",
    )
    # Simula AUTH_MODE=institutional com API key vazia ou placeholder
    for bad_key in ("", "iag_live_CHANGE_ME_APP_TOKEN"):
        unconfigured_settings = Settings(
            auth_mode="institutional",
            institutional_auth_api_key=bad_key,
        )
        monkeypatch.setattr("app.api.routes.auth.get_settings", lambda s=unconfigured_settings: s)
        auth_client = InstitutionalAuthClient(settings=unconfigured_settings)
        assert auth_client.is_configured is False

        with _build_client(db_session, auth_client) as client:
            resp = client.post(
                "/api/v1/auth/login",
                json={"username": "local.admin@islagaia.pt", "password": "LocalPassword123!"},
            )
            assert resp.status_code == 503


def test_institutional_ldap_rejects_unknown_or_missing_roles(db_session: Session) -> None:
    auth_client, _ = _make_mock_auth_client(
        {
            "guest_user": (
                200,
                {
                    "success": True,
                    "user": {
                        "username": "guest_user",
                        "displayName": "Externo",
                        "email": "guest@islagaia.pt",
                    },
                    "role": "guest",
                },
            ),
            "no_role_user": (
                200,
                {
                    "success": True,
                    "user": {
                        "username": "no_role_user",
                        "displayName": "Sem Perfil",
                        "email": "norole@islagaia.pt",
                    },
                },
            ),
        }
    )

    with _build_client(db_session, auth_client) as client:
        for uname in ("guest_user", "no_role_user"):
            resp = client.post(
                "/api/v1/auth/login",
                json={"username": uname, "password": "secret"},
            )
            assert resp.status_code == 403


def test_settings_rejects_invalid_auth_mode_typos() -> None:
    for invalid in ("instutional", "ldap", "", "none"):
        with pytest.raises(ValidationError):
            Settings(auth_mode=invalid)  # type: ignore[arg-type]

    for valid in ("local", "hybrid", "institutional", "  INSTITUTIONAL  "):
        cfg = Settings(auth_mode=valid)  # type: ignore[arg-type]
        assert cfg.auth_mode in {"local", "hybrid", "institutional"}
