import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.publication import Publication
from app.models.researcher import Researcher
from app.services.excel_import import ExcelImportService
from app.services.portal_api import PortalApiClient, PortalSyncService
from tests.conftest import build_synthetic_researchers_xlsx

SAMPLE_PORTAL_PAYLOAD_V1 = [
    {
        "ID": "PUB-001",
        "authors": "AAAA-1111-BBBB;CCCC-2222-DDDD",
        "Ciência ID": "AAAA-1111-BBBB;#CCCC-2222-DDDD",
        "Email": "ana.silva@isla.test;#bruno.costa@isla.test",
        "Nome": "Ana Silva; Bruno Costa",
        "Afiliação": "ISLA Gaia",
        "Escola": "EST;#ESG",
        "Ano": 2025,
        "Tipo Publicação": "Artigo em Jornal - SCOPUS/WOS(ISI)",
        "Title": "Applied AI in Higher Education Analytics",
        "Jornal": "Journal of Educational AI",
        "Conferência": "",
        "DOI": "https://doi.org/10.1000/isla.2025.001",
        "DOI/URL": "https://doi.org/10.1000/isla.2025.001",
        "Quartil": "Q1",
        "Estado": "Publicado",
        "APA": "Silva, A., & Costa, B. (2025). Applied AI in Higher Education Analytics.",
        "Observações": "Nota interna confidencial",
        "Valor": "9.5",
        "Indexada Scopus": True,
        "Indexada WoS": True,
        "Indexado": "Scopus; WoS",
        "Numero de Citações": 14,
        "Referencias": 42,
        "Open Access": True,
        "OA Status": "gold",
        "OA URL": "https://oa.example.org/pub1",
        "Keywords": "AI; Higher Education; Analytics",
    },
    {
        "ID": "PUB-002",
        "authors": "",
        "Ciência ID": "",
        "Email": "",
        "Nome": "Carla Duarte",  # Apenas nome (sem CV ID nem email) -> hipótese, nunca link automático
        "Afiliação": "ISLA Gaia",
        "Escola": "EST",
        "Ano": 2024,
        "Tipo Publicação": "Artigo em Conferência",
        "Title": "Data Governance Models",
        "Jornal": "",
        "Conferência": "ICIS 2024",
        "DOI": "10.1000/isla.2024.002",
        "Quartil": "",
        "Estado": "Publicado",
        "Indexada Scopus": True,
        "Indexada WoS": False,
        "Numero de Citações": 3,
        "Referencias": 20,
        "Open Access": False,
    },
]


def _make_mock_sync_service(
    payload: list[dict],
    *,
    version: str = "7",
    expected_token: str = "secret-portal-token",
) -> tuple[PortalSyncService, dict]:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        if request.headers.get("Authorization") != f"Bearer {expected_token}":
            return httpx.Response(401, json={"error": "unauthorized"})
        return httpx.Response(
            200,
            json=payload,
            headers={
                "X-PowerBI-Version": version,
                "X-PowerBI-Records": str(len(payload)),
                "X-PowerBI-Cache-TTL-Minutes": "1440",
            },
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    settings = Settings(
        portal_api_base_url="https://portal.isla.test",
        portal_api_token=expected_token,
    )
    return PortalSyncService(PortalApiClient(settings=settings, http_client=http_client)), captured


def test_portal_sync_links_authors_respects_name_rule_and_tracks_diffs(db_session: Session) -> None:
    # 1. Importar Excel de docentes primeiro
    ExcelImportService().import_workbook(
        db_session, build_synthetic_researchers_xlsx(), "docentes.xlsx"
    )

    # 2. Sincronizar API v1 (com nocache=True)
    sync_service, captured = _make_mock_sync_service(SAMPLE_PORTAL_PAYLOAD_V1, version="7")
    snap1 = sync_service.sync_publications(db_session, nocache=True)

    assert captured["auth"] == "Bearer secret-portal-token"
    assert "nocache=1" in captured["url"]
    assert snap1.source_version == "7"
    assert snap1.cache_ttl_minutes == 1440
    assert snap1.forced_nocache is True
    assert snap1.records_created == 2
    assert snap1.records_updated == 0
    assert snap1.records_removed == 0

    pub1 = db_session.scalar(select(Publication).where(Publication.portal_id == "PUB-001"))
    assert pub1 is not None
    assert pub1.doi == "10.1000/isla.2025.001"
    assert pub1.quartile == "Q1"
    assert pub1.keywords == ["AI", "Higher Education", "Analytics"]
    assert len(pub1.authors) == 2

    # Ana tem CV ID duplicado no Excel, mas o email desambigua com exact + needs_review=True
    ana = db_session.scalar(select(Researcher).where(Researcher.email == "ana.silva@isla.test"))
    bruno = db_session.scalar(select(Researcher).where(Researcher.email == "bruno.costa@isla.test"))
    assert pub1.authors[0].researcher_id == ana.id
    assert pub1.authors[0].match_method == "ciencia_vitae_id"
    assert pub1.authors[0].needs_review is True
    assert pub1.authors[1].researcher_id == bruno.id
    assert pub1.authors[1].match_method == "ciencia_vitae_id"
    assert pub1.authors[1].needs_review is False

    # PUB-002 só tem nome ("Carla Duarte") -> NUNCA associar automaticamente!
    pub2 = db_session.scalar(select(Publication).where(Publication.portal_id == "PUB-002"))
    assert pub2 is not None
    assert len(pub2.authors) == 1
    assert pub2.authors[0].researcher_id is None
    assert pub2.authors[0].match_method == "name_hypothesis"
    assert pub2.authors[0].match_confidence == "needs_validation"
    assert pub2.authors[0].needs_review is True

    # 3. Segunda sincronização: PUB-001 atualizada (mais citações), PUB-002 removida
    payload_v2 = [
        {**SAMPLE_PORTAL_PAYLOAD_V1[0], "Numero de Citações": 21},
    ]
    sync_service_v2, _ = _make_mock_sync_service(payload_v2, version="8")
    snap2 = sync_service_v2.sync_publications(db_session, nocache=False)

    assert snap2.source_version == "8"
    assert snap2.records_created == 0
    assert snap2.records_updated == 1
    assert snap2.records_removed == 1
    assert "PUB-001" in snap2.diff_summary["updated_ids"]
    assert "PUB-002" in snap2.diff_summary["removed_ids"]

    db_session.refresh(pub1)
    db_session.refresh(pub2)
    assert pub1.citations_count == 21
    assert pub2.is_active is False


def test_excel_import_after_portal_sync_relinks_authors(db_session: Session) -> None:
    # Sincroniza API antes de existir qualquer docente importado
    sync_service, _ = _make_mock_sync_service(SAMPLE_PORTAL_PAYLOAD_V1, version="1")
    sync_service.sync_publications(db_session)

    pub1 = db_session.scalar(select(Publication).where(Publication.portal_id == "PUB-001"))
    assert all(a.researcher_id is None for a in pub1.authors)

    # Importa Excel posteriormente -> autores devem ficar automaticamente ligados
    ExcelImportService().import_workbook(
        db_session, build_synthetic_researchers_xlsx(), "docentes.xlsx"
    )
    db_session.expire_all()

    pub1_reloaded = db_session.scalar(select(Publication).where(Publication.portal_id == "PUB-001"))
    assert pub1_reloaded.authors[0].researcher_id is not None
    assert pub1_reloaded.authors[1].researcher_id is not None
