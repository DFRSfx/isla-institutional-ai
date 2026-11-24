from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import UserRole
from app.models.publication import PublicationAuthor
from app.models.researcher import Researcher
from app.services.excel_import import ExcelImportService
from app.services.portal_api import PortalFetchResult, PortalSyncService
from tests.conftest import auth_headers, build_synthetic_researchers_xlsx, make_user
from tests.test_portal_sync import SAMPLE_PORTAL_PAYLOAD_V1


def test_admin_user_management_and_rbac(client: TestClient, db_session: Session) -> None:
    admin = make_user(db_session, email="admin@islagaia.pt", role=UserRole.ADMIN)
    direction = make_user(db_session, email="direcao@islagaia.pt", role=UserRole.DIRECTION)
    faculty = make_user(db_session, email="docente@islagaia.pt", role=UserRole.FACULTY)

    # Direção e Docente não podem gerir utilizadores
    for u in (direction, faculty):
        assert client.get("/api/v1/users", headers=auth_headers(u)).status_code == 403
        assert (
            client.post(
                "/api/v1/users",
                json={
                    "email": "novo@islagaia.pt",
                    "full_name": "Novo",
                    "password": "Password123!",
                    "role": "faculty",
                },
                headers=auth_headers(u),
            ).status_code
            == 403
        )

    # Admin cria novo utilizador
    create_resp = client.post(
        "/api/v1/users",
        json={
            "email": "novo.docente@islagaia.pt",
            "full_name": "Novo Docente",
            "password": "Password123!",
            "role": "faculty",
        },
        headers=auth_headers(admin),
    )
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["email"] == "novo.docente@islagaia.pt"
    assert created["role"] == "faculty"

    # Admin promove para direction e desativa
    patch_resp = client.patch(
        f"/api/v1/users/{created['id']}",
        json={"role": "direction", "is_active": False},
        headers=auth_headers(admin),
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["role"] == "direction"
    assert patch_resp.json()["is_active"] is False

    # Admin não pode desativar ou rebaixar a própria conta
    assert (
        client.patch(
            f"/api/v1/users/{admin.id}",
            json={"is_active": False},
            headers=auth_headers(admin),
        ).status_code
        == 400
    )
    assert (
        client.patch(
            f"/api/v1/users/{admin.id}",
            json={"role": "faculty"},
            headers=auth_headers(admin),
        ).status_code
        == 400
    )


def test_admin_review_pending_author_matches_approve_and_reject(
    client: TestClient, db_session: Session
) -> None:
    ExcelImportService().import_workbook(
        db_session, build_synthetic_researchers_xlsx(), "docentes.xlsx"
    )
    PortalSyncService().sync_publications(
        db_session,
        prefetched=PortalFetchResult(
            records=SAMPLE_PORTAL_PAYLOAD_V1,
            source_version="50",
            reported_record_count=2,
            cache_ttl_minutes=1440,
            endpoint="/api/powerbi/publications",
            forced_nocache=False,
        ),
    )

    admin = make_user(db_session, email="admin@islagaia.pt", role=UserRole.ADMIN)
    faculty = make_user(db_session, email="docente@islagaia.pt", role=UserRole.FACULTY)
    carla = db_session.scalar(select(Researcher).where(Researcher.email == "carla.duarte@isla.test"))
    assert carla is not None

    # Docente não tem acesso à fila de revisão
    assert client.get("/api/v1/review/author-matches", headers=auth_headers(faculty)).status_code == 403

    # Admin vê a hipótese por nome ('Carla Duarte' em PUB-002) com candidato sugerido
    pending_resp = client.get("/api/v1/review/author-matches", headers=auth_headers(admin))
    assert pending_resp.status_code == 200
    pending = pending_resp.json()
    carla_item = next(p for p in pending if p["raw_name"] == "Carla Duarte")
    assert carla_item["match_method"] == "name_hypothesis"
    assert any(c["id"] == str(carla.id) for c in carla_item["candidates"])

    # Admin aprova correspondência -> passa a manual_verified e sai da fila
    approve_resp = client.post(
        f"/api/v1/review/author-matches/{carla_item['authorship_id']}",
        json={"action": "approve", "researcher_id": str(carla.id)},
        headers=auth_headers(admin),
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["match_method"] == "manual_verified"
    assert approve_resp.json()["needs_review"] is False

    # Rejeitar outra entrada pendente (ex.: Ana Silva com CV duplicado marcado para revisão)
    remaining = client.get("/api/v1/review/author-matches", headers=auth_headers(admin)).json()
    if remaining:
        rej_id = remaining[0]["authorship_id"]
        rej_resp = client.post(
            f"/api/v1/review/author-matches/{rej_id}",
            json={"action": "reject"},
            headers=auth_headers(admin),
        )
        assert rej_resp.status_code == 200
        assert rej_resp.json()["match_method"] == "unmatched"
        assert rej_resp.json()["needs_review"] is False

    # Confirma na BD que Carla está ligada
    db_session.expire_all()
    pa = db_session.scalar(
        select(PublicationAuthor).where(PublicationAuthor.raw_name == "Carla Duarte")
    )
    assert pa is not None
    assert pa.researcher_id == carla.id
    assert pa.match_method == "manual_verified"
