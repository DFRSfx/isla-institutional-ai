"""
Harness experimental reprodutível — ISLA Institutional AI Agent (Secção 10).

Compara três configurações sobre o mesmo conjunto de 10 cenários sintéticos:
- Configuração A: Baseline sem fontes (sem Portal API nem Excel)
- Configuração B: Fonte única (apenas Portal Científico, sem Excel de docentes)
- Configuração C: Agente completo (cruzamento Portal API + Excel + validação + RBAC)
"""

from __future__ import annotations

import argparse
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import time
from typing import Any

import openpyxl
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agent.graph import AgentOrchestrator  # noqa: E402
from app.agent.llm_client import OpenAICompatibleLLMClient  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.permissions import UserRole  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.database.session import Base  # noqa: E402
import app.models  # noqa: E402, F401
from app.models.researcher import Researcher  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.excel_import import ExcelImportService  # noqa: E402
from app.services.portal_api import PortalFetchResult, PortalSyncService  # noqa: E402

DATASET_PATH = REPO_ROOT / "research" / "test-dataset" / "benchmark_questions.json"

SYNTHETIC_PORTAL_RECORDS: list[dict[str, Any]] = [
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
        "DOI": "https://doi.org/10.1000/isla.2025.001",
        "DOI/URL": "https://doi.org/10.1000/isla.2025.001",
        "Quartil": "Q1",
        "Estado": "Publicado",
        "APA": "Silva, A., & Costa, B. (2025). Applied AI in Higher Education Analytics.",
        "Indexada Scopus": True,
        "Indexada WoS": True,
        "Indexado": "Scopus; WoS",
        "Numero de Citações": 14,
        "Referencias": 42,
        "Open Access": True,
        "OA Status": "gold",
    },
    {
        "ID": "PUB-002",
        "authors": "",
        "Ciência ID": "",
        "Email": "",
        "Nome": "Carla Duarte",
        "Afiliação": "ISLA Gaia",
        "Escola": "EST",
        "Ano": 2024,
        "Tipo Publicação": "Artigo em Conferência",
        "Title": "Data Governance Models",
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
    {
        "ID": "PUB-2027-STUDENT",
        "authors": "EEEE-3333-FFFF;9999-XXXX-8888",
        "Ciência ID": "EEEE-3333-FFFF;#9999-XXXX-8888",
        "Email": "carla.duarte@isla.test;#eva.externa@isla.test",
        "Nome": "Carla Duarte; Eva Externa",
        "Afiliação": "ISLA Gaia",
        "Escola": "",
        "Ano": 2027,
        "Tipo Publicação": "Book",
        "Title": "Future Year Institutional Publication",
        "Estado": "Aceite",
        "Indexada Scopus": False,
        "Indexada WoS": False,
        "Numero de Citações": 0,
        "Referencias": 10,
        "Open Access": False,
    },
]


def _build_synthetic_excel_bytes() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Docentes"
    ws.append(
        [
            "CienciaVitae",
            "Docente",
            "Email",
            "Acivo",
            "CienciaVitae2",
            "Grau",
            "Escola",
            "Afiliação",
            "Área Formação",
            "Categoria",
        ]
    )
    rows = [
        ["AAAA-1111-BBBB", "Ana Silva", "ana.silva@isla.test", "Y", "AAAA-1111-BBBB", "D", "EST", "CIDI", "Informática", "Teacher"],
        ["CCCC-2222-DDDD", "Bruno Costa", "bruno.costa@isla.test", "A", "CCCC-2222-DDDD)", "M", "ESG", "CEOS", "Gestão", "Teacher"],
        ["EEEE-3333-FFFF", "Carla Duarte", "carla.duarte@isla.test", "N", "EEEE-3333-9999", "L", "EST", None, "Engenharia", "Student"],
        ["AAAA-1111-BBBB", "Diogo Ferreira", "diogo.ferreira@isla.test", "O", "AAAA-1111-BBBB", "N", "ESG", None, None, "Teacher"],
        ["9999-XXXX-8888", "Eva Externa", "eva.externa@isla.test", "Y", "9999-XXXX-8888", "D", "ESG", None, None, "Convidado"],
        ["MMMM-9999-NNNN", "Miguel Costa", "miguel.costa@isla.test", "Y", "MMMM-9999-NNNN", "D", "EST", None, "Gestão", "Teacher"],
    ]
    for r in rows:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _create_session_for_config(config_name: str) -> tuple[Session, dict[str, User]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)()

    if config_name == "C":
        ExcelImportService().import_workbook(
            db, _build_synthetic_excel_bytes(), "synthetic_docentes.xlsx"
        )
    if config_name in {"B", "C"}:
        PortalSyncService().sync_publications(
            db,
            prefetched=PortalFetchResult(
                records=SYNTHETIC_PORTAL_RECORDS,
                source_version="100",
                reported_record_count=len(SYNTHETIC_PORTAL_RECORDS),
                cache_ttl_minutes=1440,
                endpoint="/api/powerbi/publications",
                forced_nocache=False,
            ),
        )

    ana = db.scalar(select(Researcher).where(Researcher.email == "ana.silva@isla.test"))
    direction = User(
        email="direcao@islagaia.pt",
        full_name="Direção ISLA",
        password_hash=hash_password("Bench123!"),
        role=UserRole.DIRECTION.value,
        is_active=True,
    )
    faculty = User(
        email="ana.silva@islagaia.pt",
        full_name="Ana Silva",
        password_hash=hash_password("Bench123!"),
        role=UserRole.FACULTY.value,
        is_active=True,
        researcher_id=ana.id if ana else None,
    )
    db.add_all([direction, faculty])
    db.commit()
    db.refresh(direction)
    db.refresh(faculty)
    return db, {"direction": direction, "faculty": faculty}


def evaluate_configuration(
    config_name: str,
    dataset: dict[str, Any],
    *,
    llm_model: str | None = None,
    llm_base_url: str = "http://localhost:11434/v1",
    label: str | None = None,
) -> dict[str, Any]:
    ref_year = int(dataset.get("reference_year", 2026))
    db, users = _create_session_for_config(config_name)
    numeric_checks = 0
    numeric_passed = 0
    citation_checks = 0
    citation_passed = 0
    cross_checks = 0
    cross_passed = 0
    ambiguity_checks = 0
    ambiguity_passed = 0
    report_checks = 0
    report_passed = 0
    completeness_passed = 0
    ungrounded_count = 0
    unauthorized_disclosures = 0
    tool_calls_used = 0
    latencies: list[float] = []
    scenario_results: list[dict[str, Any]] = []

    if llm_model:
        llm_client = OpenAICompatibleLLMClient(
            Settings(
                _env_file=None,
                llm_provider="openai_compatible",
                llm_base_url=llm_base_url,
                llm_model=llm_model,
                llm_reasoning_effort="none",
                llm_timeout_seconds=60.0,
            )
        )
    else:
        llm_client = OpenAICompatibleLLMClient(Settings(_env_file=None, llm_provider="deterministic"))

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        orchestrator = AgentOrchestrator(reports_dir=tmp_path, llm_client=llm_client)

        for sc in dataset["scenarios"]:
            user = users[sc["role"]]
            conv_id = None
            if sc.get("setup_prompt"):
                setup_res = orchestrator.handle_message(
                    db,
                    user=user,
                    message_text=sc["setup_prompt"],
                    reference_year=ref_year,
                )
                conv_id = setup_res.conversation_id

            t0 = time.perf_counter()
            res = orchestrator.handle_message(
                db,
                user=user,
                message_text=sc["prompt"],
                conversation_id=conv_id,
                reference_year=ref_year,
            )
            elapsed = time.perf_counter() - t0
            latencies.append(elapsed)
            if res.tool_calls:
                tool_calls_used += 1
            exp = sc["expected"]
            summary = res.analytics_summary or {}
            kpis = summary.get("kpis") or {}
            comp = summary.get("year_comparison") or {}
            quality = summary.get("data_quality") or {}

            sc_ok = True

            # 1. Ambiguidade / confirmação de identidade
            if "needs_clarification" in exp:
                if exp["needs_clarification"]:
                    ambiguity_checks += 1
                    if res.needs_clarification and res.report_bundle is None:
                        ambiguity_passed += 1
                    else:
                        sc_ok = False
                elif res.needs_clarification:
                    sc_ok = False

            # 2. Exatidão numérica
            for kpi_key in ("publications", "scopus", "wos", "citations", "published_count", "non_published_count"):
                if kpi_key in exp:
                    numeric_checks += 1
                    if kpis.get(kpi_key) == exp[kpi_key]:
                        numeric_passed += 1
                    else:
                        sc_ok = False

            if "citations_year_a" in exp:
                numeric_checks += 2
                deltas = comp.get("deltas") or {}
                cit_d = deltas.get("citations") or {}
                if cit_d.get("year_a") == exp["citations_year_a"]:
                    numeric_passed += 1
                else:
                    sc_ok = False
                if cit_d.get("year_b") == exp["citations_year_b"]:
                    numeric_passed += 1
                else:
                    sc_ok = False

            if "future_year_publications_count" in exp:
                numeric_checks += 1
                if quality.get("future_year_publications_count") == exp["future_year_publications_count"]:
                    numeric_passed += 1
                else:
                    sc_ok = False

            # 3. Fontes citadas
            if exp.get("requires_sources") or "min_sources" in exp:
                citation_checks += 1
                min_s = exp.get("min_sources", 1)
                if len(res.sources) >= min_s and "Fontes utilizadas" in res.answer:
                    citation_passed += 1
                else:
                    sc_ok = False
                    if kpis.get("publications", 0) > 0:
                        ungrounded_count += 1

            # 4. Cruzamento de dados (Teacher vs Student + escolas)
            if "expected_teachers" in exp or "expected_students" in exp:
                cross_checks += 1
                got_teachers = {r["name"] for r in summary.get("top_researchers") or []}
                got_students = {r["name"] for r in summary.get("top_students") or []}
                teachers_ok = all(t in got_teachers for t in exp.get("expected_teachers", []))
                students_ok = all(s in got_students for s in exp.get("expected_students", []))
                forbidden_ok = all(f not in got_teachers for f in exp.get("forbidden_in_teachers", []))
                if teachers_ok and students_ok and forbidden_ok:
                    cross_passed += 1
                else:
                    sc_ok = False

            # 5. Qualidade de relatórios PDF & Excel
            if exp.get("requires_reports"):
                report_checks += 1
                if res.report_bundle is not None:
                    pdf_p = tmp_path / f"{res.report_bundle['report_id']}.pdf"
                    xlsx_p = tmp_path / f"{res.report_bundle['report_id']}.xlsx"
                    if pdf_p.exists() and xlsx_p.exists() and pdf_p.read_bytes().startswith(b"%PDF-"):
                        wb = openpyxl.load_workbook(xlsx_p)
                        if len(wb.sheetnames) == 7:
                            report_passed += 1
                        else:
                            sc_ok = False
                    else:
                        sc_ok = False
                else:
                    sc_ok = False

            # 6. Segurança RBAC (zero divulgações não autorizadas)
            if exp.get("must_deny"):
                if res.analytics_summary is not None:
                    unauthorized_disclosures += 1
                    sc_ok = False
            for forbidden in exp.get("forbidden_names", []):
                if forbidden in res.answer:
                    unauthorized_disclosures += 1
                    sc_ok = False
                if res.report_bundle is not None:
                    xlsx_p = tmp_path / f"{res.report_bundle['report_id']}.xlsx"
                    if xlsx_p.exists():
                        wb = openpyxl.load_workbook(xlsx_p)
                        for sheet_name in ("Docentes", "Estudantes", "Dados Detalhados"):
                            names = [
                                row[0]
                                for row in wb[sheet_name].iter_rows(min_row=2, values_only=True)
                                if row[0]
                            ]
                            if forbidden in names:
                                unauthorized_disclosures += 1
                                sc_ok = False

            if sc_ok:
                completeness_passed += 1
            scenario_results.append(
                {
                    "id": sc["id"],
                    "passed": sc_ok,
                    "latency_s": round(elapsed, 2),
                    "tools": [tc.get("tool") for tc in res.tool_calls],
                }
            )

    db.close()
    total_sc = len(dataset["scenarios"])
    sorted_lat = sorted(latencies)
    avg_lat = round(sum(sorted_lat) / len(sorted_lat), 2) if sorted_lat else 0.0
    p95_lat = round(sorted_lat[min(len(sorted_lat) - 1, int(len(sorted_lat) * 0.95))], 2) if sorted_lat else 0.0

    def pct(num: int, den: int) -> float:
        return round((num / den) * 100.0, 1) if den else 100.0

    return {
        "configuration": label or config_name,
        "llm_model": llm_model or "deterministic",
        "scenarios_passed": completeness_passed,
        "scenarios_total": total_sc,
        "avg_latency_s": avg_lat,
        "p95_latency_s": p95_lat,
        "tool_usage_pct": pct(tool_calls_used, total_sc),
        "numeric_accuracy_pct": pct(numeric_passed, numeric_checks),
        "completeness_pct": pct(completeness_passed, total_sc),
        "source_citation_accuracy_pct": pct(citation_passed, citation_checks),
        "cross_source_accuracy_pct": pct(cross_passed, cross_checks),
        "ambiguity_handling_pct": pct(ambiguity_passed, ambiguity_checks),
        "report_generation_success_pct": pct(report_passed, report_checks),
        "ungrounded_claim_rate_pct": pct(ungrounded_count, total_sc),
        "unauthorized_disclosure_count": unauthorized_disclosures,
        "scenario_results": scenario_results,
    }


def run_all_configurations() -> list[dict[str, Any]]:
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    return [evaluate_configuration(cfg, dataset) for cfg in ("A", "B", "C")]


def run_model_comparison(
    models: list[str],
    *,
    ollama_url: str = "http://localhost:11434/v1",
) -> list[dict[str, Any]]:
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    results = [evaluate_configuration("C", dataset, label="C (Determinístico)")]
    for model in models:
        m = model.strip()
        if not m:
            continue
        results.append(
            evaluate_configuration(
                "C",
                dataset,
                llm_model=m,
                llm_base_url=ollama_url,
                label=f"C + {m}",
            )
        )
    return results


def format_markdown_table(results: list[dict[str, Any]]) -> str:
    header = (
        "| Config / Modelo | Cenários OK | Latência Média | P95 | Exatidão Numérica | Fontes | "
        "Cruzamento | Ambiguidade | Relatórios | Não Fundamentadas | Fugas RBAC |\n"
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |"
    )
    rows = []
    for r in results:
        rows.append(
            f"| **{r['configuration']}** | {r['scenarios_passed']}/{r['scenarios_total']} | "
            f"{r.get('avg_latency_s', 0.0)}s | {r.get('p95_latency_s', 0.0)}s | "
            f"{r['numeric_accuracy_pct']}% | {r['source_citation_accuracy_pct']}% | "
            f"{r['cross_source_accuracy_pct']}% | {r['ambiguity_handling_pct']}% | "
            f"{r['report_generation_success_pct']}% | {r['ungrounded_claim_rate_pct']}% | "
            f"{r['unauthorized_disclosure_count']} |"
        )
    return "\n".join([header, *rows])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark científico ISLA Institutional AI Agent")
    parser.add_argument(
        "--models",
        default="",
        help="Lista de modelos locais separados por vírgula (ex.: qwen3:4b,qwen2.5:7b,qwen3:8b)",
    )
    parser.add_argument(
        "--ollama-url",
        default="http://localhost:11434/v1",
        help="Endpoint OpenAI-compatible local (Ollama/vLLM)",
    )
    parser.add_argument(
        "--output-md",
        default="",
        help="Caminho opcional para gravar relatório Markdown + JSON",
    )
    args = parser.parse_args()

    if args.models.strip():
        model_list = [m.strip() for m in args.models.split(",") if m.strip()]
        all_results = run_model_comparison(model_list, ollama_url=args.ollama_url)
    else:
        all_results = run_all_configurations()

    md = format_markdown_table(all_results)
    print(md)
    if args.output_md:
        out_path = Path(args.output_md)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md + "\n", encoding="utf-8")
        out_path.with_suffix(".json").write_text(
            json.dumps(all_results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
