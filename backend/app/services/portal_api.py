from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.ingestion import SourceSnapshot
from app.models.publication import Publication, PublicationAuthor
from app.models.researcher import Researcher
from app.services.audit import record_audit_log
from app.services.data_normalization import (
    ResearcherMatcher,
    clean_str,
    compute_canonical_hash,
    normalize_alnum,
    normalize_ciencia_vitae_id,
    normalize_doi,
    normalize_email,
    normalize_quartile,
    parse_bool,
    parse_optional_int,
    split_portal_multivalue,
)


class PortalApiError(RuntimeError):
    """Erro de comunicação ou contrato inválido da API do Portal Científico."""


@dataclass(frozen=True)
class PortalFetchResult:
    records: list[dict[str, Any]]
    source_version: str | None
    reported_record_count: int | None
    cache_ttl_minutes: int | None
    endpoint: str
    forced_nocache: bool


class PortalApiClient:
    """
    Cliente HTTP backend-only para `GET /api/powerbi/publications`.
    O Bearer token nunca é registado em logs nem exposto fora deste cliente.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._external_client = http_client

    def fetch_publications(self, *, nocache: bool = False) -> PortalFetchResult:
        if not self.settings.portal_api_token:
            raise PortalApiError(
                "PORTAL_API_TOKEN não está configurado no backend."
            )

        base = self.settings.portal_api_base_url.rstrip("/")
        path = "/" + self.settings.portal_api_publications_path.lstrip("/")
        url = f"{base}{path}"
        params = {"nocache": "1"} if nocache else None
        headers = {
            "Authorization": f"Bearer {self.settings.portal_api_token}",
            "Accept": "application/json",
        }

        try:
            if self._external_client is not None:
                response = self._external_client.get(url, headers=headers, params=params)
            else:
                with httpx.Client(timeout=self.settings.portal_api_timeout_seconds) as client:
                    response = client.get(url, headers=headers, params=params)
        except httpx.HTTPError as exc:
            raise PortalApiError(f"Falha ao contactar o Portal Científico: {exc}") from exc

        if response.status_code == 401:
            raise PortalApiError("Portal Científico rejeitou o token de autenticação (401).")
        if response.status_code >= 400:
            raise PortalApiError(
                f"Portal Científico devolveu erro HTTP {response.status_code}."
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise PortalApiError("Resposta do Portal Científico não é JSON válido.") from exc

        if not isinstance(payload, list):
            raise PortalApiError(
                "Formato inesperado do Portal Científico: esperava-se uma lista JSON de publicações."
            )

        return PortalFetchResult(
            records=payload,
            source_version=response.headers.get("X-PowerBI-Version"),
            reported_record_count=parse_optional_int(response.headers.get("X-PowerBI-Records")),
            cache_ttl_minutes=parse_optional_int(
                response.headers.get("X-PowerBI-Cache-TTL-Minutes")
            ),
            endpoint=path,
            forced_nocache=nocache,
        )


def _extract_portal_authors(record: dict[str, Any]) -> list[dict[str, str | None]]:
    """
    Reconstrói a lista ordenada de autores institucionais a partir dos campos
    agregados devolvidos por PowerBiApiController.php.
    """
    cv_ids = split_portal_multivalue(
        record.get("Ciência ID") or record.get("authors"),
        delimiters=(";#", "; ", ";"),
    )
    emails = split_portal_multivalue(record.get("Email"), delimiters=(";#", "; ", ";"))
    names = split_portal_multivalue(record.get("Nome"), delimiters=("; ", ";#", ";"))
    schools = split_portal_multivalue(record.get("Escola"), delimiters=(";#", "; ", ";"))
    affiliations = split_portal_multivalue(record.get("Afiliação"), delimiters=("; ", ";#", ";"))

    author_count = max(len(cv_ids), len(emails), len(names))
    if author_count == 0:
        return []

    authors: list[dict[str, str | None]] = []
    for idx in range(author_count):
        raw_cv = cv_ids[idx] if idx < len(cv_ids) else None
        norm_cv, _ = normalize_ciencia_vitae_id(raw_cv)
        raw_email = normalize_email(emails[idx]) if idx < len(emails) else None
        raw_name = clean_str(names[idx]) if idx < len(names) else None
        # Escola e Afiliação são deduplicadas no Portal: só atribuir diretamente
        # quando há cardinalidade 1 ou igual ao número de autores.
        raw_school = (
            schools[idx]
            if len(schools) == author_count
            else (schools[0] if len(schools) == 1 else None)
        )
        raw_affiliation = (
            affiliations[idx]
            if len(affiliations) == author_count
            else (affiliations[0] if len(affiliations) == 1 else None)
        )
        authors.append(
            {
                "raw_ciencia_vitae_id": norm_cv or clean_str(raw_cv),
                "raw_email": raw_email,
                "raw_name": raw_name,
                "raw_school": clean_str(raw_school),
                "raw_affiliation": clean_str(raw_affiliation),
            }
        )
    return authors


def _map_publication_fields(record: dict[str, Any]) -> dict[str, Any]:
    portal_id = clean_str(record.get("ID"))
    title = clean_str(record.get("Title")) or "(Sem título)"
    doi_raw = record.get("DOI") or record.get("DOI/URL")
    doi_clean = normalize_doi(doi_raw)
    doi_url = clean_str(record.get("DOI/URL")) or (f"https://doi.org/{doi_clean}" if doi_clean else None)
    quartile = normalize_quartile(record.get("Quartil") or record.get("Classificação Jornal"))
    keywords = split_portal_multivalue(record.get("Keywords"), delimiters=("; ", ";"))
    schools_raw = split_portal_multivalue(record.get("Escola"), delimiters=(";#", "; ", ";"))
    affiliations_raw = split_portal_multivalue(record.get("Afiliação"), delimiters=("; ", ";#", ";"))

    return {
        "portal_id": portal_id,
        "doi": doi_clean,
        "doi_url": doi_url,
        "title": title,
        "normalized_title": normalize_alnum(title)[:512],
        "year": parse_optional_int(record.get("Ano")),
        "pub_type": clean_str(record.get("Tipo Publicação")),
        "status": clean_str(record.get("Estado")),
        "journal_name": clean_str(record.get("Jornal")),
        "conference_name": clean_str(record.get("Conferência")),
        "venue_name": clean_str(record.get("Fonte")),
        "venue_type": clean_str(record.get("Tipo Fonte")),
        "publisher": clean_str(record.get("Editora")),
        "book_title": clean_str(record.get("Livro")),
        "quartile": quartile,
        "is_indexed_scopus": parse_bool(record.get("Indexada Scopus")),
        "is_indexed_wos": parse_bool(record.get("Indexada WoS")),
        "indexed_in": clean_str(record.get("Indexado")),
        "citations_count": parse_optional_int(record.get("Numero de Citações")) or 0,
        "references_count": parse_optional_int(record.get("Referencias")) or 0,
        "is_open_access": parse_bool(record.get("Open Access")),
        "oa_status": clean_str(record.get("OA Status")),
        "oa_url": clean_str(record.get("OA URL")),
        "keywords": keywords,
        "apa_citation": clean_str(record.get("APA")),
        "isbn": clean_str(record.get("ISBN")),
        "issn": clean_str(record.get("ISSN")),
        "handle": clean_str(record.get("Handle")),
        "scopus_id": clean_str(record.get("Scopus ID")),
        "wos_id": clean_str(record.get("WoS ID")),
        "openalex_id": clean_str(record.get("OpenAlex ID")),
        "scholar_user_id": clean_str(record.get("Scholer User_id") or record.get("Scholar User_id")),
        "scholar_article_id": clean_str(record.get("Scholar artigo_id")),
        "schools_raw": schools_raw,
        "affiliations_raw": affiliations_raw,
        "internal_notes": clean_str(record.get("Observações")),
        "evaluation_score": clean_str(record.get("Valor")),
    }


def relink_publication_authors(db: Session) -> dict[str, int]:
    """
    Reavalia a associação entre `publication_authors` e `researchers`.
    Útil após uma nova importação de Excel de docentes.
    """
    researchers = list(db.scalars(select(Researcher)).all())
    matcher = ResearcherMatcher(researchers)

    authors = list(db.scalars(select(PublicationAuthor)).all())
    stats = {
        "total": len(authors),
        "exact": 0,
        "needs_validation": 0,
        "unmatched": 0,
    }
    for pa in authors:
        researcher, method, confidence, needs_review = matcher.match(
            ciencia_vitae_id=pa.raw_ciencia_vitae_id,
            email=pa.raw_email,
            name=pa.raw_name,
        )
        pa.researcher_id = researcher.id if researcher else None
        pa.match_method = method
        pa.match_confidence = confidence
        pa.needs_review = needs_review
        stats[confidence] = stats.get(confidence, 0) + 1

    db.flush()
    return stats


class PortalSyncService:
    def __init__(self, client: PortalApiClient | None = None) -> None:
        self.client = client or PortalApiClient()

    def sync_publications(
        self,
        db: Session,
        *,
        nocache: bool = False,
        synced_by: UUID | None = None,
        user_role: str | None = None,
        ip_address: str | None = None,
        prefetched: PortalFetchResult | None = None,
    ) -> SourceSnapshot:
        fetch_result = prefetched or self.client.fetch_publications(nocache=nocache)
        records = fetch_result.records

        content_hash = compute_canonical_hash(records)
        snapshot = SourceSnapshot(
            source_type="portal_api",
            source_version=fetch_result.source_version,
            endpoint_or_filename=fetch_result.endpoint,
            content_hash=content_hash,
            record_count=len(records),
            cache_ttl_minutes=fetch_result.cache_ttl_minutes,
            forced_nocache=fetch_result.forced_nocache,
            synced_by=synced_by,
            metadata_json={
                "reported_record_count": fetch_result.reported_record_count,
            },
        )
        db.add(snapshot)
        db.flush()

        existing_pubs = {
            pub.portal_id: pub
            for pub in db.scalars(select(Publication)).all()
        }
        researchers = list(db.scalars(select(Researcher)).all())
        matcher = ResearcherMatcher(researchers)

        created_ids: list[str] = []
        updated_ids: list[str] = []
        unchanged_count = 0
        seen_portal_ids: set[str] = set()
        author_match_counts = {"exact": 0, "needs_validation": 0, "unmatched": 0}

        for idx, raw_record in enumerate(records):
            mapped = _map_publication_fields(raw_record)
            portal_id = mapped["portal_id"] or f"fallback-{idx}-{compute_canonical_hash(raw_record)[:12]}"
            mapped["portal_id"] = portal_id
            seen_portal_ids.add(portal_id)

            record_hash = compute_canonical_hash(raw_record)
            existing = existing_pubs.get(portal_id)

            if existing is None:
                pub = Publication(
                    **mapped,
                    record_hash=record_hash,
                    is_active=True,
                    last_snapshot_id=snapshot.id,
                    raw_payload=raw_record,
                )
                db.add(pub)
                db.flush()
                created_ids.append(portal_id)
                self._replace_authors(pub, raw_record, matcher, author_match_counts)
            elif existing.record_hash != record_hash or not existing.is_active:
                for key, val in mapped.items():
                    setattr(existing, key, val)
                existing.record_hash = record_hash
                existing.is_active = True
                existing.last_snapshot_id = snapshot.id
                existing.raw_payload = raw_record
                updated_ids.append(portal_id)
                self._replace_authors(existing, raw_record, matcher, author_match_counts)
            else:
                existing.last_snapshot_id = snapshot.id
                unchanged_count += 1

        removed_ids: list[str] = []
        for portal_id, pub in existing_pubs.items():
            if portal_id not in seen_portal_ids and pub.is_active:
                pub.is_active = False
                removed_ids.append(portal_id)

        snapshot.records_created = len(created_ids)
        snapshot.records_updated = len(updated_ids)
        snapshot.records_unchanged = unchanged_count
        snapshot.records_removed = len(removed_ids)
        snapshot.diff_summary = {
            "created_ids": created_ids[:200],
            "updated_ids": updated_ids[:200],
            "removed_ids": removed_ids[:200],
            "author_matching": author_match_counts,
        }

        record_audit_log(
            db,
            action="portal_api.sync",
            resource_type="source_snapshot",
            resource_id=str(snapshot.id),
            user_id=synced_by,
            user_role=user_role,
            status="success",
            details={
                "source_version": snapshot.source_version,
                "forced_nocache": snapshot.forced_nocache,
                "record_count": snapshot.record_count,
                "created": snapshot.records_created,
                "updated": snapshot.records_updated,
                "unchanged": snapshot.records_unchanged,
                "removed": snapshot.records_removed,
            },
            ip_address=ip_address,
        )
        db.commit()
        db.refresh(snapshot)
        return snapshot

    @staticmethod
    def _replace_authors(
        publication: Publication,
        raw_record: dict[str, Any],
        matcher: ResearcherMatcher,
        counters: dict[str, int],
    ) -> None:
        publication.authors.clear()
        extracted = _extract_portal_authors(raw_record)
        for order, author_data in enumerate(extracted):
            researcher, method, confidence, needs_review = matcher.match(
                ciencia_vitae_id=author_data["raw_ciencia_vitae_id"],
                email=author_data["raw_email"],
                name=author_data["raw_name"],
            )
            counters[confidence] = counters.get(confidence, 0) + 1
            publication.authors.append(
                PublicationAuthor(
                    author_order=order,
                    researcher_id=researcher.id if researcher else None,
                    raw_ciencia_vitae_id=author_data["raw_ciencia_vitae_id"],
                    raw_name=author_data["raw_name"],
                    raw_email=author_data["raw_email"],
                    raw_school=author_data["raw_school"],
                    raw_affiliation=author_data["raw_affiliation"],
                    match_method=method,
                    match_confidence=confidence,
                    needs_review=needs_review,
                )
            )
