from sqlalchemy.orm import Session

from app.agent.tools import ToolContext
from app.core.config import Settings
from app.core.permissions import UserRole
from app.services.excel_import import ExcelImportService
from app.services.portal_api import PortalFetchResult, PortalSyncService
from app.services.semantic_search import (
    LocalEmbeddingClient,
    index_publication_embeddings,
    search_publications_semantic,
)
from tests.conftest import build_synthetic_researchers_xlsx, make_user
from tests.test_portal_sync import SAMPLE_PORTAL_PAYLOAD_V1


class _FakeEmbeddingClient(LocalEmbeddingClient):
    """Cliente sintético determinístico para testar RAG sem depender de rede/Ollama."""

    def __init__(self) -> None:
        super().__init__(
            settings=Settings(
                _env_file=None,
                llm_base_url="http://localhost:11434/v1",
                embedding_model="nomic-embed-text",
            )
        )

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for t in texts:
            low = t.lower()
            ai_score = 1.0 if ("ai" in low or "inteligencia" in low or "education" in low) else 0.05
            gov_score = 1.0 if ("governance" in low or "data" in low or "governanca" in low) else 0.05
            vectors.append([ai_score, gov_score, 0.1, 0.2])
        return vectors


def test_semantic_rag_indexing_search_and_rbac(db_session: Session) -> None:
    ExcelImportService().import_workbook(
        db_session, build_synthetic_researchers_xlsx(), "docentes.xlsx"
    )
    PortalSyncService().sync_publications(
        db_session,
        prefetched=PortalFetchResult(
            records=SAMPLE_PORTAL_PAYLOAD_V1,
            source_version="50",
            reported_record_count=len(SAMPLE_PORTAL_PAYLOAD_V1),
            cache_ttl_minutes=720,
            endpoint="/api/powerbi/publications",
            forced_nocache=False,
        ),
    )

    fake_emb = _FakeEmbeddingClient()
    # 1. Primeira indexação indexa todas as publicações
    first = index_publication_embeddings(db_session, embedding_client=fake_emb)
    assert first["indexed_publications"] == 2
    assert first["newly_indexed"] == 2
    assert first["coverage_pct"] == 100.0

    # 2. Segunda indexação é incremental (salta registos inalterados)
    second = index_publication_embeddings(db_session, embedding_client=fake_emb)
    assert second["newly_indexed"] == 0
    assert second["skipped_up_to_date"] == 2

    # 3. Pesquisa semântica por IA devolve o artigo de IA em 1.º lugar
    direction = make_user(db_session, email="dir.rag@islagaia.pt", role=UserRole.DIRECTION)
    faculty = make_user(db_session, email="fac.rag@islagaia.pt", role=UserRole.FACULTY)

    res_dir = search_publications_semantic(
        ToolContext(db=db_session, user=direction),
        "inteligencia artificial na educacao",
        top_k=2,
        embedding_client=fake_emb,
    )
    assert len(res_dir["matches"]) == 2
    assert "AI" in res_dir["matches"][0]["title"]
    assert res_dir["matches"][0]["similarity"] > res_dir["matches"][1]["similarity"]
    assert len(res_dir["top_topic_researchers"]) >= 1

    # 4. RBAC: docente vê publicações públicas, mas não recebe ranking interno de outros docentes
    res_fac = search_publications_semantic(
        ToolContext(db=db_session, user=faculty),
        "governanca de dados",
        top_k=2,
        embedding_client=fake_emb,
    )
    assert len(res_fac["matches"]) == 2
    assert res_fac["top_topic_researchers"] == []
