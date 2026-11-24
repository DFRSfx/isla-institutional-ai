from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.agent.tools.context import ToolContext, collect_latest_sources
from app.core.permissions import can_view_all_researchers, can_view_sensitive_fields
from app.models.publication import Publication, PublicationAuthor
from app.models.researcher import Researcher
from app.models.school import School
from app.services.audit import record_audit_log
from app.services.data_normalization import (
    compute_canonical_hash,
    normalize_ciencia_vitae_id,
    normalize_email,
    normalize_text,
)


def get_data_sources_status(ctx: ToolContext) -> dict[str, Any]:
    sources = collect_latest_sources(ctx.db)
    return {
        "sources": sources,
        "has_portal_data": any(s["source_type"] == "portal_api" for s in sources),
        "has_excel_data": any(s["source_type"] == "excel_import" for s in sources),
    }


def _format_researcher_for_user(
    researcher: Researcher,
    ctx: ToolContext,
    *,
    include_internal_for_self_only: bool = True,
) -> dict[str, Any]:
    is_self = ctx.user.researcher_id is not None and researcher.id == ctx.user.researcher_id
    allow_internal = can_view_all_researchers(ctx.user.role) or (
        include_internal_for_self_only and is_self
    )
    allow_email = can_view_sensitive_fields(ctx.user.role) or is_self

    return {
        "id": str(researcher.id),
        "name": researcher.name,
        "ciencia_vitae_id": researcher.ciencia_vitae_id,
        "school_code": researcher.school.code if researcher.school else researcher.school_code_raw,
        "affiliation": researcher.affiliation,
        "email": researcher.email if allow_email else None,
        "degree_code": researcher.degree_code if allow_internal else None,
        "status_code": researcher.status_code if allow_internal else None,
        "category": researcher.category if allow_internal else None,
        "training_area": researcher.training_area if allow_internal else None,
        "scholar_h_index": researcher.scholar_h_index if allow_internal else None,
        "scopus_h_index": researcher.scopus_h_index if allow_internal else None,
        "wos_h_index": researcher.wos_h_index if allow_internal else None,
        "data_quality_flags": researcher.data_quality_flags if allow_internal else [],
    }


def find_researcher(ctx: ToolContext, query: str) -> dict[str, Any]:
    """
    Pesquisa docentes por Ciência Vitae ID, email institucional ou nome.
    Aplica RBAC estrito no backend: um docente nunca recebe dados internos de outros docentes.
    """
    raw_query = query.strip()
    if not raw_query:
        return {"matches": [], "hypotheses": [], "access_denied": False, "sources": collect_latest_sources(ctx.db)}

    cv_norm, _ = normalize_ciencia_vitae_id(raw_query)
    email_norm = normalize_email(raw_query)
    name_norm = normalize_text(raw_query)

    stmt = select(Researcher).options(selectinload(Researcher.school))
    all_researchers = list(ctx.db.scalars(stmt).all())

    exact_matches: list[Researcher] = []
    name_matches: list[Researcher] = []

    for r in all_researchers:
        if cv_norm and r.ciencia_vitae_id and r.ciencia_vitae_id.upper() == cv_norm or email_norm and r.email and r.email.lower() == email_norm:
            exact_matches.append(r)
        elif name_norm and name_norm in r.normalized_name:
            name_matches.append(r)

    if not can_view_all_researchers(ctx.user.role):
        # Docente só pode consultar os seus próprios dados internos
        allowed_exact = [r for r in exact_matches if r.id == ctx.user.researcher_id]
        allowed_name = [r for r in name_matches if r.id == ctx.user.researcher_id]
        attempted_others = (len(exact_matches) - len(allowed_exact)) + (
            len(name_matches) - len(allowed_name)
        )
        if attempted_others > 0:
            record_audit_log(
                ctx.db,
                action="agent.tool.find_researcher.denied",
                resource_type="researcher",
                resource_id=raw_query[:120],
                user_id=ctx.user.id,
                user_role=ctx.user.role,
                status="denied",
                details={"reason": "faculty_attempted_other_researcher_lookup"},
                ip_address=ctx.ip_address,
            )
            ctx.db.commit()
            return {
                "matches": [_format_researcher_for_user(r, ctx) for r in allowed_exact],
                "hypotheses": [],
                "access_denied": True,
                "message": "Não tem autorização para consultar dados internos de outros docentes.",
                "sources": collect_latest_sources(ctx.db),
            }
        exact_matches = allowed_exact
        name_matches = allowed_name

    # Quando há correspondência exata por CV/email, devolve em matches; por nome, indica necessidade de validação se múltiplas
    return {
        "matches": [
            {**_format_researcher_for_user(r, ctx), "match_type": "exact_identifier"}
            for r in exact_matches
        ],
        "hypotheses": [
            {
                **_format_researcher_for_user(r, ctx),
                "match_type": "name_search",
                "requires_confirmation": True,
            }
            for r in name_matches
            if r.id not in {m.id for m in exact_matches}
        ],
        "access_denied": False,
        "sources": collect_latest_sources(ctx.db),
    }


def _publication_matches_school(pub: Publication, school_code: str) -> bool:
    target = school_code.upper()
    for pa in pub.authors:
        if pa.researcher is not None:
            r_school = (
                pa.researcher.school.code
                if pa.researcher.school
                else (pa.researcher.school_code_raw or "")
            )
            if r_school.upper() == target:
                return True
        if pa.raw_school and pa.raw_school.upper() == target:
            return True
    return any(s.upper() == target for s in (pub.schools_raw or []))


def _serialize_pub_row(pub: Publication, ctx: ToolContext) -> dict[str, Any]:
    allow_sensitive = can_view_sensitive_fields(ctx.user.role)
    author_names = [
        pa.researcher.name if pa.researcher else (pa.raw_name or pa.raw_ciencia_vitae_id or "Desconhecido")
        for pa in pub.authors
    ]
    return {
        "portal_id": pub.portal_id,
        "title": pub.title,
        "year": pub.year,
        "pub_type": pub.pub_type,
        "status": pub.status,
        "journal_name": pub.journal_name,
        "conference_name": pub.conference_name,
        "venue_name": pub.venue_name,
        "quartile": pub.quartile,
        "is_indexed_scopus": pub.is_indexed_scopus,
        "is_indexed_wos": pub.is_indexed_wos,
        "indexed_in": pub.indexed_in,
        "citations_count": pub.citations_count,
        "references_count": pub.references_count,
        "is_open_access": pub.is_open_access,
        "oa_status": pub.oa_status,
        "doi": pub.doi,
        "doi_url": pub.doi_url,
        "apa_citation": pub.apa_citation,
        "authors": "; ".join(author_names),
        "schools": "; ".join(pub.schools_raw or []),
        "internal_notes": pub.internal_notes if allow_sensitive else None,
        "evaluation_score": pub.evaluation_score if allow_sensitive else None,
    }


def _compute_year_bucket_metrics(pubs: list[Publication]) -> dict[str, Any]:
    total = len(pubs)
    scopus = sum(1 for p in pubs if p.is_indexed_scopus)
    wos = sum(1 for p in pubs if p.is_indexed_wos)
    indexed_any = sum(1 for p in pubs if p.is_indexed_scopus or p.is_indexed_wos)
    oa = sum(1 for p in pubs if p.is_open_access)
    citations = sum(p.citations_count for p in pubs)
    q1 = sum(1 for p in pubs if p.quartile == "Q1")
    q2 = sum(1 for p in pubs if p.quartile == "Q2")
    q3 = sum(1 for p in pubs if p.quartile == "Q3")
    q4 = sum(1 for p in pubs if p.quartile == "Q4")
    return {
        "publications": total,
        "scopus": scopus,
        "wos": wos,
        "indexed_scopus_or_wos": indexed_any,
        "q1": q1,
        "q2": q2,
        "q3": q3,
        "q4": q4,
        "citations": citations,
        "open_access": oa,
    }


def _build_year_comparison(
    all_scoped_pubs: list[Publication],
    year_a: int,
    year_b: int,
) -> dict[str, Any]:
    pubs_a = [p for p in all_scoped_pubs if p.year == year_a]
    pubs_b = [p for p in all_scoped_pubs if p.year == year_b]
    metrics_a = _compute_year_bucket_metrics(pubs_a)
    metrics_b = _compute_year_bucket_metrics(pubs_b)

    deltas: dict[str, dict[str, Any]] = {}
    for key in metrics_a:
        val_a = metrics_a[key]
        val_b = metrics_b[key]
        diff = val_b - val_a
        pct = round((diff / val_a) * 100, 1) if val_a > 0 else (100.0 if val_b > 0 else 0.0)
        deltas[key] = {"year_a": val_a, "year_b": val_b, "delta": diff, "delta_pct": pct}

    return {
        "year_a": year_a,
        "year_b": year_b,
        "metrics_year_a": metrics_a,
        "metrics_year_b": metrics_b,
        "deltas": deltas,
    }


def _is_student_category(category: str | None) -> bool:
    return normalize_text(category) in {"student", "estudante", "aluno", "aluna"}


def get_scientific_production_report_data(
    ctx: ToolContext,
    *,
    school_code: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    researcher_id: UUID | None = None,
    compare_years: tuple[int, int] | None = None,
    top_n: int = 10,
    reference_year: int | None = None,
) -> dict[str, Any]:
    """
    Executa análise determinística cruzada entre Portal Científico e Excel de docentes.
    Todos os cálculos são feitos em Python/SQL e respeitam RBAC antes de devolver dados ao agente.
    """
    normalized_school = school_code.strip().upper() if school_code else None

    # Controlo RBAC para consulta focada num docente específico
    if (
        researcher_id is not None
        and not can_view_all_researchers(ctx.user.role)
        and ctx.user.researcher_id != researcher_id
    ):
        record_audit_log(
            ctx.db,
            action="agent.tool.researcher_production.denied",
            resource_type="researcher",
            resource_id=str(researcher_id),
            user_id=ctx.user.id,
            user_role=ctx.user.role,
            status="denied",
            ip_address=ctx.ip_address,
        )
        ctx.db.commit()
        return {
            "access_denied": True,
            "message": "Um docente não pode consultar relatórios internos individuais de outros docentes.",
            "sources": collect_latest_sources(ctx.db),
        }

    pub_stmt = (
        select(Publication)
        .options(
            selectinload(Publication.authors)
            .selectinload(PublicationAuthor.researcher)
            .selectinload(Researcher.school)
        )
        .where(Publication.is_active.is_(True))
    )
    all_active_pubs = list(ctx.db.scalars(pub_stmt).unique().all())

    # Filtro espacial/entidade (antes do filtro temporal para permitir comparações entre anos)
    entity_scoped_pubs: list[Publication] = []
    for pub in all_active_pubs:
        if normalized_school and not _publication_matches_school(pub, normalized_school):
            continue
        if researcher_id is not None and not any(
            pa.researcher_id == researcher_id for pa in pub.authors
        ):
            continue
        entity_scoped_pubs.append(pub)

    # Filtro temporal
    scoped_pubs: list[Publication] = []
    for pub in entity_scoped_pubs:
        if year_from is not None and (pub.year is None or pub.year < year_from):
            continue
        if year_to is not None and (pub.year is None or pub.year > year_to):
            continue
        scoped_pubs.append(pub)

    # Docentes no âmbito (com RBAC)
    res_stmt = select(Researcher).options(selectinload(Researcher.school))
    if normalized_school:
        res_stmt = res_stmt.join(School, Researcher.school_id == School.id).where(
            School.code == normalized_school
        )
    if researcher_id is not None:
        res_stmt = res_stmt.where(Researcher.id == researcher_id)
    scoped_researchers = list(ctx.db.scalars(res_stmt).all())

    # Indicadores globais e distribuição por estado
    ref_year = reference_year or datetime.now(UTC).year
    status_counter: Counter[str] = Counter()
    published_count = 0
    for pub in scoped_pubs:
        label = (pub.status or "Sem estado").strip() or "Sem estado"
        status_counter[label] += 1
        if normalize_text(label) in {"publicado", "published"}:
            published_count += 1
    status_distribution = dict(status_counter)

    scoped_teachers_count = sum(1 for r in scoped_researchers if not _is_student_category(r.category))
    scoped_students_count = sum(1 for r in scoped_researchers if _is_student_category(r.category))

    base_metrics = _compute_year_bucket_metrics(scoped_pubs)
    total_pubs = base_metrics["publications"]
    kpis = {
        **base_metrics,
        "published_count": published_count,
        "non_published_count": total_pubs - published_count,
        "scopus_pct": round((base_metrics["scopus"] / total_pubs) * 100, 1) if total_pubs else 0.0,
        "wos_pct": round((base_metrics["wos"] / total_pubs) * 100, 1) if total_pubs else 0.0,
        "indexed_pct": round((base_metrics["indexed_scopus_or_wos"] / total_pubs) * 100, 1)
        if total_pubs
        else 0.0,
        "open_access_pct": round((base_metrics["open_access"] / total_pubs) * 100, 1)
        if total_pubs
        else 0.0,
        "avg_citations": round(base_metrics["citations"] / total_pubs, 2) if total_pubs else 0.0,
        "scoped_researchers_count": len(scoped_researchers),
        "scoped_teachers_count": scoped_teachers_count,
        "scoped_students_count": scoped_students_count,
    }

    # Evolução anual
    pubs_by_year: dict[int, list[Publication]] = defaultdict(list)
    missing_year_count = 0
    for pub in scoped_pubs:
        if pub.year is None:
            missing_year_count += 1
        else:
            pubs_by_year[pub.year].append(pub)

    years_axis: list[int] = sorted(pubs_by_year.keys())
    if year_from is not None and year_to is not None and year_from <= year_to:
        years_axis = list(range(year_from, year_to + 1))

    annual_evolution = [
        {"year": y, **_compute_year_bucket_metrics(pubs_by_year.get(y, []))}
        for y in years_axis
    ]

    # Distribuição por quartil
    quartile_distribution = {
        "Q1": base_metrics["q1"],
        "Q2": base_metrics["q2"],
        "Q3": base_metrics["q3"],
        "Q4": base_metrics["q4"],
        "Sem quartil": sum(1 for p in scoped_pubs if p.quartile not in {"Q1", "Q2", "Q3", "Q4"}),
    }

    # Docentes e estudantes mais produtivos (separados por categoria; RBAC aplicado)
    allow_internal_all = can_view_all_researchers(ctx.user.role)
    prod_by_teacher: dict[UUID, dict[str, Any]] = {}
    prod_by_student: dict[UUID, dict[str, Any]] = {}
    unmatched_authors_count = 0
    name_hypotheses_count = 0

    for pub in scoped_pubs:
        seen_in_pub: set[UUID] = set()
        for pa in pub.authors:
            if pa.match_method == "name_hypothesis":
                name_hypotheses_count += 1
            if pa.researcher is None:
                unmatched_authors_count += 1
                continue
            r = pa.researcher
            r_school = r.school.code if r.school else r.school_code_raw
            if normalized_school and (r_school or "").upper() != normalized_school:
                continue
            if r.id in seen_in_pub:
                continue
            seen_in_pub.add(r.id)

            # Regra P0 de segurança: perfil docente não pode receber ranking/indicadores
            # individuais de outros docentes.
            if not allow_internal_all and r.id != ctx.user.researcher_id:
                continue

            is_self = ctx.user.researcher_id == r.id
            target_bucket = prod_by_student if _is_student_category(r.category) else prod_by_teacher
            if r.id not in target_bucket:
                target_bucket[r.id] = {
                    "researcher_id": str(r.id),
                    "name": r.name,
                    "ciencia_vitae_id": r.ciencia_vitae_id,
                    "school_code": r_school,
                    # Campos internos da intranet só visíveis a admin/direction ou ao próprio docente
                    "degree_code": r.degree_code if (allow_internal_all or is_self) else None,
                    "status_code": r.status_code if (allow_internal_all or is_self) else None,
                    "category": r.category if (allow_internal_all or is_self) else None,
                    "publications": 0,
                    "scopus": 0,
                    "wos": 0,
                    "q1": 0,
                    "citations": 0,
                }
            row = target_bucket[r.id]
            row["publications"] += 1
            if pub.is_indexed_scopus:
                row["scopus"] += 1
            if pub.is_indexed_wos:
                row["wos"] += 1
            if pub.quartile == "Q1":
                row["q1"] += 1
            row["citations"] += pub.citations_count

    top_researchers = sorted(
        prod_by_teacher.values(),
        key=lambda x: (-x["publications"], -x["citations"], x["name"]),
    )[:top_n]
    top_students = sorted(
        prod_by_student.values(),
        key=lambda x: (-x["publications"], -x["citations"], x["name"]),
    )[:top_n]

    # Comparação entre dois anos (ex.: 2024 vs 2025)
    year_comparison = (
        _build_year_comparison(entity_scoped_pubs, compare_years[0], compare_years[1])
        if compare_years is not None
        else None
    )

    # Qualidade e lacunas de dados
    missing_doi_count = sum(1 for p in scoped_pubs if not p.doi)
    missing_quartile_count = quartile_distribution["Sem quartil"]
    future_year_publications_count = sum(
        1 for p in scoped_pubs if p.year is not None and p.year > ref_year
    )
    duplicate_cv_researchers_count = sum(
        1 for r in scoped_researchers if "duplicate_ciencia_vitae_id" in (r.data_quality_flags or [])
    )
    dictionary_notes = [
        "Os códigos da coluna 'Acivo' (Y, N, A, O) e 'Grau' (D, M, L, N) são apresentados no formato bruto até confirmação oficial do dicionário de dados pelo ISLA.",
        "Correspondências apenas por nome não são associadas automaticamente sem validação humana.",
        "O ranking de docentes inclui apenas registos classificados como Teacher; estudantes (Student) são apresentados separadamente.",
    ]
    if future_year_publications_count > 0:
        dictionary_notes.append(
            f"Foram mantidas {future_year_publications_count} publicação(ões) com ano editorial posterior a {ref_year} (sinalizadas para transparência)."
        )

    data_quality = {
        "reference_year": ref_year,
        "missing_year_count": missing_year_count,
        "future_year_publications_count": future_year_publications_count,
        "missing_doi_count": missing_doi_count,
        "missing_quartile_count": missing_quartile_count,
        "unmatched_author_links_count": unmatched_authors_count,
        "name_hypotheses_pending_validation": name_hypotheses_count,
        "duplicate_cv_researchers_count": duplicate_cv_researchers_count,
        "unconfirmed_dictionary_notes": dictionary_notes,
    }

    sources = collect_latest_sources(ctx.db)
    scope = {
        "school_code": normalized_school,
        "year_from": year_from,
        "year_to": year_to,
        "researcher_id": str(researcher_id) if researcher_id else None,
        "compare_years": list(compare_years) if compare_years else None,
        "requested_by_role": ctx.user.role,
    }
    reproducibility_hash = compute_canonical_hash(
        {
            "scope": scope,
            "snapshot_hashes": [s["content_hash"] for s in sources],
        }
    )[:16]

    # Lista de docentes visíveis no relatório Excel (RBAC aplicado)
    visible_researchers = (
        scoped_researchers
        if allow_internal_all
        else [r for r in scoped_researchers if r.id == ctx.user.researcher_id]
    )

    return {
        "access_denied": False,
        "scope": scope,
        "reproducibility_id": reproducibility_hash,
        "kpis": kpis,
        "status_distribution": status_distribution,
        "annual_evolution": annual_evolution,
        "quartile_distribution": quartile_distribution,
        "top_researchers": top_researchers,
        "top_students": top_students,
        "year_comparison": year_comparison,
        "publications": [_serialize_pub_row(p, ctx) for p in scoped_pubs],
        "researchers": [_format_researcher_for_user(r, ctx) for r in visible_researchers],
        "data_quality": data_quality,
        "sources": sources,
    }
