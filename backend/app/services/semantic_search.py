import hashlib
import math
from array import array
from collections import Counter
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.agent.tools.analytics import ToolContext, collect_latest_sources
from app.core.config import Settings, get_settings, is_private_or_local_url
from app.core.permissions import can_view_all_researchers
from app.models.embedding import PublicationEmbedding
from app.models.publication import Publication, PublicationAuthor


class EmbeddingClientError(RuntimeError):
    """Erro ao gerar embeddings no servidor local (Ollama/OpenAI-compatible)."""


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm <= 1e-12:
        return vec
    return [x / norm for x in vec]


def pack_embedding(vec: list[float]) -> bytes:
    normed = _l2_normalize(vec)
    arr = array("f", normed)
    return arr.tobytes()


def unpack_embedding(blob: bytes) -> array:
    arr = array("f")
    arr.frombytes(blob)
    return arr


def cosine_dot(a: array, b: array) -> float:
    return float(sum(x * y for x, y in zip(a, b, strict=False)))


class LocalEmbeddingClient:
    """
    Cliente local para embeddings (`/v1/embeddings` no Ollama ou servidor compatível),
    respeitando a política RGPD/NIS2 de processamento local.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._external_client = http_client

    @property
    def model_name(self) -> str:
        return self.settings.embedding_model.strip()

    @property
    def is_ready(self) -> bool:
        if not self.model_name:
            return False
        is_local = is_private_or_local_url(self.settings.llm_base_url)
        return is_local or self.settings.llm_allow_external_endpoints

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.is_ready:
            raise EmbeddingClientError("Servidor local de embeddings não está configurado.")

        base = self.settings.llm_base_url.rstrip("/")
        url = f"{base}/embeddings"
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.settings.llm_api_key.strip():
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key.strip()}"

        body: dict[str, Any] = {
            "model": self.model_name,
            "input": texts,
        }

        try:
            if self._external_client is not None:
                resp = self._external_client.post(url, headers=headers, json=body)
            else:
                with httpx.Client(timeout=self.settings.embedding_timeout_seconds) as client:
                    resp = client.post(url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise EmbeddingClientError(f"Falha ao contactar o servidor de embeddings: {exc}") from exc

        if resp.status_code >= 400:
            raise EmbeddingClientError(f"Servidor de embeddings devolveu HTTP {resp.status_code}.")

        try:
            payload = resp.json()
            items = sorted(payload["data"], key=lambda x: x.get("index", 0))
            vectors = [list(map(float, item["embedding"])) for item in items]
        except (ValueError, KeyError, TypeError) as exc:
            raise EmbeddingClientError("Resposta inválida do servidor de embeddings.") from exc

        if len(vectors) != len(texts):
            raise EmbeddingClientError("Número de embeddings devolvido não corresponde ao pedido.")
        return vectors


def build_publication_embedding_text(pub: Publication) -> str:
    authors = [
        pa.researcher.name if pa.researcher else (pa.raw_name or "")
        for pa in pub.authors
    ]
    authors_str = ", ".join(a for a in authors if a)
    schools_str = ", ".join(pub.schools_raw or [])
    venue = pub.journal_name or pub.conference_name or pub.venue_name or ""
    parts = [
        f"Título: {pub.title}",
        f"Tipo: {pub.pub_type}" if pub.pub_type else "",
        f"Ano: {pub.year}" if pub.year else "",
        f"Revista/Conferência: {venue}" if venue else "",
        f"Escolas: {schools_str}" if schools_str else "",
        f"Quartil: {pub.quartile}" if pub.quartile else "",
        f"Autores: {authors_str}" if authors_str else "",
        f"Referência: {pub.apa_citation}" if pub.apa_citation else "",
    ]
    return " | ".join(p for p in parts if p)[:1600]


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def get_embedding_index_status(db: Session, *, model_name: str | None = None) -> dict[str, Any]:
    target_model = (model_name or get_settings().embedding_model).strip()
    total_pubs = int(db.scalar(select(func.count(Publication.id))) or 0)
    indexed_pubs = int(
        db.scalar(
            select(func.count(PublicationEmbedding.publication_id)).where(
                PublicationEmbedding.model_name == target_model
            )
        )
        or 0
    )
    pct = round((indexed_pubs / total_pubs) * 100.0, 1) if total_pubs else 0.0
    return {
        "model": target_model,
        "total_publications": total_pubs,
        "indexed_publications": indexed_pubs,
        "coverage_pct": pct,
    }


def index_publication_embeddings(
    db: Session,
    *,
    batch_size: int = 64,
    force: bool = False,
    embedding_client: LocalEmbeddingClient | None = None,
) -> dict[str, Any]:
    """
    Indexa (incrementalmente) embeddings semânticos para todas as publicações na BD.
    """
    client = embedding_client or LocalEmbeddingClient()
    model = client.model_name

    pubs = list(
        db.scalars(
            select(Publication).options(
                selectinload(Publication.authors).selectinload(PublicationAuthor.researcher)
            )
        ).all()
    )
    existing = {
        e.publication_id: e
        for e in db.scalars(select(PublicationEmbedding)).all()
    }

    to_embed: list[tuple[Publication, str, str]] = []
    skipped = 0
    for pub in pubs:
        text = build_publication_embedding_text(pub)
        h = _text_hash(text)
        prev = existing.get(pub.id)
        if not force and prev is not None and prev.model_name == model and prev.content_hash == h:
            skipped += 1
            continue
        to_embed.append((pub, text, h))

    indexed = 0
    for i in range(0, len(to_embed), max(batch_size, 1)):
        chunk = to_embed[i : i + batch_size]
        vectors = client.embed_texts([item[1] for item in chunk])
        for (pub, _text, h), vec in zip(chunk, vectors, strict=True):
            blob = pack_embedding(vec)
            prev = existing.get(pub.id)
            if prev is None:
                db.add(
                    PublicationEmbedding(
                        publication_id=pub.id,
                        model_name=model,
                        content_hash=h,
                        dimensions=len(vec),
                        embedding_bytes=blob,
                    )
                )
            else:
                prev.model_name = model
                prev.content_hash = h
                prev.dimensions = len(vec)
                prev.embedding_bytes = blob
            indexed += 1
        db.commit()

    status = get_embedding_index_status(db, model_name=model)
    return {
        **status,
        "newly_indexed": indexed,
        "skipped_up_to_date": skipped,
    }


def search_publications_semantic(
    ctx: ToolContext,
    query: str,
    *,
    school_code: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    top_k: int = 8,
    embedding_client: LocalEmbeddingClient | None = None,
) -> dict[str, Any]:
    """
    Pesquisa semântica (RAG) nas publicações sincronizadas do ISLA.
    Respeita filtros de escola/ano e RBAC (não expõe dados internos privados a docentes/estudantes).
    """
    client = embedding_client or LocalEmbeddingClient()
    model = client.model_name
    bounded_k = max(1, min(int(top_k), 15))
    sources = collect_latest_sources(ctx.db)

    idx_status = get_embedding_index_status(ctx.db, model_name=model)
    if idx_status["indexed_publications"] == 0:
        return {
            "query": query,
            "indexed_publications": 0,
            "matches": [],
            "top_topic_researchers": [],
            "note": (
                "O índice semântico (RAG) ainda não foi construído. "
                "Um administrador pode indexar as publicações em 'Fontes & Excel'."
            ),
            "sources": sources,
        }

    q_vec = array("f", _l2_normalize(client.embed_texts([query])[0]))

    stmt = (
        select(PublicationEmbedding, Publication)
        .join(Publication, Publication.id == PublicationEmbedding.publication_id)
        .where(PublicationEmbedding.model_name == model)
        .options(selectinload(Publication.authors).selectinload(PublicationAuthor.researcher))
    )
    if year_from is not None:
        stmt = stmt.where(Publication.year >= year_from)
    if year_to is not None:
        stmt = stmt.where(Publication.year <= year_to)

    rows = ctx.db.execute(stmt).all()
    target_school = school_code.strip().upper() if school_code else None

    scored: list[tuple[float, Publication]] = []
    for emb, pub in rows:
        if target_school:
            pub_schools = {s.upper() for s in (pub.schools_raw or [])}
            author_schools = {
                (pa.researcher.school_code_raw or "").upper()
                for pa in pub.authors
                if pa.researcher and pa.researcher.school_code_raw
            }
            if target_school not in pub_schools and target_school not in author_schools:
                continue
        if emb.dimensions != len(q_vec):
            continue
        score = cosine_dot(q_vec, unpack_embedding(emb.embedding_bytes))
        scored.append((score, pub))

    scored.sort(key=lambda item: item[0], reverse=True)
    top_hits = scored[:bounded_k]

    allow_researcher_summary = can_view_all_researchers(ctx.user.role)
    researcher_counts: Counter[str] = Counter()
    results: list[dict[str, Any]] = []

    for score, pub in top_hits:
        authors_display: list[str] = []
        for pa in pub.authors:
            if pa.researcher is not None:
                authors_display.append(pa.researcher.name)
                if allow_researcher_summary and (pa.researcher.category or "").lower() == "teacher":
                    researcher_counts[pa.researcher.name] += 1
            elif pa.raw_name:
                authors_display.append(pa.raw_name)

        results.append(
            {
                "similarity": round(score, 3),
                "title": pub.title,
                "year": pub.year,
                "pub_type": pub.pub_type,
                "venue": pub.journal_name or pub.conference_name or pub.venue_name,
                "quartile": pub.quartile,
                "scopus": pub.is_indexed_scopus,
                "wos": pub.is_indexed_wos,
                "citations": pub.citations_count,
                "doi": pub.doi,
                "authors": authors_display[:6],
            }
        )

    top_topic_researchers = (
        [{"name": name, "matching_publications": cnt} for name, cnt in researcher_counts.most_common(5)]
        if allow_researcher_summary
        else []
    )

    return {
        "query": query,
        "embedding_model": model,
        "indexed_publications": idx_status["indexed_publications"],
        "matches": results,
        "top_topic_researchers": top_topic_researchers,
        "sources": sources,
    }
