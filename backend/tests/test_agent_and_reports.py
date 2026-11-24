import base64
import re
import zlib
from io import BytesIO
from pathlib import Path

import openpyxl
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.graph import AgentOrchestrator
from app.api.routes.agent import get_orchestrator
from app.api.routes.reports import get_reports_dir
from app.core.permissions import UserRole
from app.database.session import get_db
from app.main import create_app
from app.models.researcher import Researcher
from app.services.excel_import import ExcelImportService
from app.services.portal_api import PortalFetchResult, PortalSyncService
from tests.conftest import auth_headers, build_synthetic_researchers_xlsx, make_user
from tests.test_portal_sync import SAMPLE_PORTAL_PAYLOAD_V1


def _seed_cross_source_data(db: Session) -> None:
    ExcelImportService().import_workbook(
        db, build_synthetic_researchers_xlsx(), "docentes.xlsx"
    )
    PortalSyncService().sync_publications(
        db,
        prefetched=PortalFetchResult(
            records=SAMPLE_PORTAL_PAYLOAD_V1,
            source_version="12",
            reported_record_count=2,
            cache_ttl_minutes=1440,
            endpoint="/api/powerbi/publications",
            forced_nocache=False,
        ),
    )


def _build_isolated_client(db_session: Session, tmp_path: Path) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: (yield db_session)
    app.dependency_overrides[get_reports_dir] = lambda: tmp_path
    app.dependency_overrides[get_orchestrator] = lambda: AgentOrchestrator(reports_dir=tmp_path)
    return TestClient(app)


def test_agent_clarifies_ambiguous_prompt_before_executing(
    db_session: Session, tmp_path: Path
) -> None:
    _seed_cross_source_data(db_session)
    direction = make_user(db_session, email="direcao@islagaia.pt", role=UserRole.DIRECTION)

    with _build_isolated_client(db_session, tmp_path) as client:
        resp = client.post(
            "/api/v1/chat",
            json={"message": "Preciso de um relatório"},
            headers=auth_headers(direction),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["needs_clarification"] is True
        assert body["report_bundle"] is None
        assert "EST" in body["answer"] or "âmbito" in body["answer"].lower()


def test_agent_est_report_followup_comparison_and_pdf_excel_downloads(
    db_session: Session, tmp_path: Path
) -> None:
    _seed_cross_source_data(db_session)
    direction = make_user(db_session, email="direcao@islagaia.pt", role=UserRole.DIRECTION)
    other_faculty = make_user(db_session, email="outro@islagaia.pt", role=UserRole.FACULTY)

    with _build_isolated_client(db_session, tmp_path) as client:
        # 1. Pedido emblemático da secção 5
        resp1 = client.post(
            "/api/v1/chat",
            json={
                "message": (
                    "Preciso de um relatório da produção científica da EST nos últimos cinco anos, "
                    "com os docentes mais produtivos, publicações indexadas e evolução anual."
                )
            },
            headers=auth_headers(direction),
        )
        assert resp1.status_code == 200
        body1 = resp1.json()
        assert body1["needs_clarification"] is False
        assert body1["analytics_summary"]["kpis"]["publications"] == 2
        assert body1["analytics_summary"]["kpis"]["scopus"] == 2
        assert body1["analytics_summary"]["kpis"]["wos"] == 1
        assert len(body1["sources"]) == 2
        assert body1["report_bundle"] is not None

        conv_id = body1["conversation_id"]
        first_report_id = body1["report_bundle"]["report_id"]

        # 2. Refinamento iterativo na mesma conversação (secção 7: memória contextual)
        resp2 = client.post(
            "/api/v1/chat",
            json={
                "conversation_id": conv_id,
                "message": "Acrescenta uma comparação entre 2024 e 2025.",
            },
            headers=auth_headers(direction),
        )
        assert resp2.status_code == 200
        body2 = resp2.json()
        assert body2["conversation_id"] == conv_id
        assert body2["needs_clarification"] is False
        comp = body2["analytics_summary"]["year_comparison"]
        assert comp is not None
        assert comp["year_a"] == 2024
        assert comp["year_b"] == 2025
        assert comp["deltas"]["publications"]["year_a"] == 1
        assert comp["deltas"]["publications"]["year_b"] == 1
        assert comp["deltas"]["citations"]["year_a"] == 3
        assert comp["deltas"]["citations"]["year_b"] == 14
        assert body2["report_bundle"]["report_id"] != first_report_id

        # 3. Download do PDF (verificar assinatura %PDF-)
        pdf_resp = client.get(
            body2["report_bundle"]["pdf_url"],
            headers=auth_headers(direction),
        )
        assert pdf_resp.status_code == 200
        assert pdf_resp.headers["content-type"] == "application/pdf"
        assert pdf_resp.content.startswith(b"%PDF-")
        assert len(pdf_resp.content) > 2000

        # 4. Download do Excel (verificar as 7 folhas estruturadas incluindo Estudantes)
        xlsx_resp = client.get(
            body2["report_bundle"]["excel_url"],
            headers=auth_headers(direction),
        )
        assert xlsx_resp.status_code == 200
        wb = openpyxl.load_workbook(BytesIO(xlsx_resp.content))
        assert wb.sheetnames == [
            "Resumo",
            "Indicadores",
            "Publicações",
            "Docentes",
            "Estudantes",
            "Dados Detalhados",
            "Fontes e Critérios",
        ]
        # Verificar integridade dos cálculos na folha Resumo
        resumo_vals = {row[0]: row[1] for row in wb["Resumo"].iter_rows(values_only=True) if row[0]}
        assert resumo_vals["Total de publicações"] == 2
        assert resumo_vals["Indexadas Scopus"] == 2
        assert resumo_vals["Total de citações"] == 17

        # 5. Outro utilizador não-admin não pode descarregar relatório alheio (403)
        denied_dl = client.get(
            body2["report_bundle"]["pdf_url"],
            headers=auth_headers(other_faculty),
        )
        assert denied_dl.status_code == 403

        # 6. Histórico de conversações e mensagens persistido
        convs = client.get("/api/v1/conversations", headers=auth_headers(direction)).json()
        assert len(convs) == 1
        msgs = client.get(
            f"/api/v1/conversations/{conv_id}/messages",
            headers=auth_headers(direction),
        ).json()
        assert len(msgs) == 4  # 2 user + 2 assistant
        # Botões PDF/Excel reconstruídos no histórico ao recarregar a conversa
        assert msgs[1]["report_bundle"]["report_id"] == first_report_id
        assert msgs[3]["report_bundle"]["report_id"] == body2["report_bundle"]["report_id"]


def test_agent_enforces_rbac_when_faculty_queries_other_researcher_and_audit_logs(
    db_session: Session, tmp_path: Path
) -> None:
    _seed_cross_source_data(db_session)
    ana = db_session.scalar(select(Researcher).where(Researcher.email == "ana.silva@isla.test"))

    admin_user = make_user(db_session, email="admin@islagaia.pt", role=UserRole.ADMIN)
    direction_user = make_user(db_session, email="direcao@islagaia.pt", role=UserRole.DIRECTION)
    faculty_user = make_user(
        db_session,
        email="ana.silva@islagaia.pt",
        role=UserRole.FACULTY,
        full_name="Ana Silva",
        researcher_id=ana.id,
    )

    with _build_isolated_client(db_session, tmp_path) as client:
        # 1. Docente tenta perguntar ao agente pelos dados de outro docente (Bruno Costa / CV ID)
        blocked_resp = client.post(
            "/api/v1/chat",
            json={"message": "Mostra-me as publicações e dados do docente CCCC-2222-DDDD"},
            headers=auth_headers(faculty_user),
        )
        assert blocked_resp.status_code == 200
        body = blocked_resp.json()
        assert "não tem autorização" in body["answer"].lower()
        assert "Bruno Costa" not in body["answer"]
        assert body["analytics_summary"] is None

        # 2. Docente consegue consultar os seus próprios dados e publicações
        own_resp = client.post(
            "/api/v1/chat",
            json={"message": "Mostra-me as minhas publicações"},
            headers=auth_headers(faculty_user),
        )
        assert own_resp.status_code == 200
        assert own_resp.json()["analytics_summary"]["kpis"]["publications"] == 1

        # 3. Auditoria: docente recebe 403; direção vê sem IP; admin vê tudo
        assert client.get("/api/v1/audit/logs", headers=auth_headers(faculty_user)).status_code == 403

        dir_logs = client.get("/api/v1/audit/logs", headers=auth_headers(direction_user))
        assert dir_logs.status_code == 200
        assert all(item["ip_address"] is None for item in dir_logs.json())

        admin_logs = client.get("/api/v1/audit/logs", headers=auth_headers(admin_user))
        assert admin_logs.status_code == 200
        actions = {item["action"] for item in admin_logs.json()}
        assert "agent.tool.find_researcher.denied" in actions
        assert "agent.chat.turn" in actions


def _extract_pdf_text_streams(pdf_bytes: bytes) -> str:
    chunks: list[str] = [pdf_bytes.decode("latin-1", errors="ignore")]
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", pdf_bytes, flags=re.DOTALL):
        raw_stream = match.group(1)
        try:
            compact = re.sub(rb"\s+", b"", raw_stream).removesuffix(b"~>")
            decoded = base64.a85decode(compact)
            chunks.append(zlib.decompress(decoded).decode("latin-1", errors="ignore"))
            continue
        except (ValueError, zlib.error):
            pass
        try:
            chunks.append(zlib.decompress(raw_stream).decode("latin-1", errors="ignore"))
        except zlib.error:
            pass
    return "\n".join(chunks)


def test_faculty_cannot_see_other_researchers_in_ranking_pdf_or_excel(
    db_session: Session, tmp_path: Path
) -> None:
    _seed_cross_source_data(db_session)
    ana = db_session.scalar(select(Researcher).where(Researcher.email == "ana.silva@isla.test"))
    assert ana is not None

    faculty_user = make_user(
        db_session,
        email="ana.silva@islagaia.pt",
        role=UserRole.FACULTY,
        full_name="Ana Silva",
        researcher_id=ana.id,
    )

    with _build_isolated_client(db_session, tmp_path) as client:
        resp = client.post(
            "/api/v1/chat",
            json={
                "message": (
                    "Preciso de um relatório institucional do ISLA nos últimos cinco anos "
                    "com os docentes mais produtivos em PDF e Excel."
                )
            },
            headers=auth_headers(faculty_user),
        )
        assert resp.status_code == 200
        body = resp.json()

        # 1. Resposta do agente e ranking não podem expor outros docentes
        assert "Bruno Costa" not in body["answer"]
        assert "Diogo Ferreira" not in body["answer"]
        top_names = [r["name"] for r in body["analytics_summary"]["top_researchers"]]
        assert top_names == ["Ana Silva"]

        # 2. PDF gerado não pode incluir outros docentes na tabela de produtividade
        pdf_resp = client.get(
            body["report_bundle"]["pdf_url"],
            headers=auth_headers(faculty_user),
        )
        assert pdf_resp.status_code == 200
        pdf_text = _extract_pdf_text_streams(pdf_resp.content)
        assert "Ana Silva" in pdf_text
        assert "Bruno Costa" not in pdf_text
        assert "Diogo Ferreira" not in pdf_text

        # 3. Folhas 'Docentes' e 'Dados Detalhados' do Excel não podem incluir outros docentes
        xlsx_resp = client.get(
            body["report_bundle"]["excel_url"],
            headers=auth_headers(faculty_user),
        )
        assert xlsx_resp.status_code == 200
        wb = openpyxl.load_workbook(BytesIO(xlsx_resp.content))
        docentes_names = [
            row[0] for row in wb["Docentes"].iter_rows(min_row=2, values_only=True) if row[0]
        ]
        detalhes_names = [
            row[0]
            for row in wb["Dados Detalhados"].iter_rows(min_row=2, values_only=True)
            if row[0]
        ]
        estudantes_names = [
            row[0]
            for row in wb["Estudantes"].iter_rows(min_row=2, values_only=True)
            if row[0]
        ]
        assert docentes_names == ["Ana Silva"]
        assert detalhes_names == ["Ana Silva"]
        assert estudantes_names == []


def test_agent_requires_identity_confirmation_for_single_name_match(
    db_session: Session, tmp_path: Path
) -> None:
    _seed_cross_source_data(db_session)
    direction = make_user(db_session, email="direcao@islagaia.pt", role=UserRole.DIRECTION)

    with _build_isolated_client(db_session, tmp_path) as client:
        # Mesmo existindo apenas um candidato chamado 'Bruno Costa', não deve gerar relatório sem validação
        name_resp = client.post(
            "/api/v1/chat",
            json={"message": "Gera um relatório sobre o docente Bruno Costa"},
            headers=auth_headers(direction),
        )
        assert name_resp.status_code == 200
        body = name_resp.json()
        assert body["needs_clarification"] is True
        assert body["report_bundle"] is None
        assert body["analytics_summary"] is None
        assert "Bruno Costa" in body["answer"]
        assert "Ciência Vitae" in body["answer"]

        # Com identificador exato (Ciência Vitae ID), o agente avança e gera o relatório
        id_resp = client.post(
            "/api/v1/chat",
            json={"message": "Gera um relatório sobre o docente CCCC-2222-DDDD"},
            headers=auth_headers(direction),
        )
        assert id_resp.status_code == 200
        id_body = id_resp.json()
        assert id_body["needs_clarification"] is False
        assert id_body["analytics_summary"]["kpis"]["publications"] == 1
        assert id_body["report_bundle"] is not None


def test_category_separation_status_distribution_and_future_year_flag(
    db_session: Session, tmp_path: Path
) -> None:
    ExcelImportService().import_workbook(
        db_session, build_synthetic_researchers_xlsx(), "docentes.xlsx"
    )
    # Acrescentar investigador com categoria desconhecida/vazia (não pode entrar em Docentes nem Estudantes)
    unknown_cat_researcher = Researcher(
        ciencia_vitae_id="9999-XXXX-8888",
        name="Eva Externa",
        normalized_name="eva externa",
        email="eva.externa@isla.test",
        category="Convidado",
    )
    db_session.add(unknown_cat_researcher)
    db_session.commit()

    payload = [
        *SAMPLE_PORTAL_PAYLOAD_V1,
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
    PortalSyncService().sync_publications(
        db_session,
        prefetched=PortalFetchResult(
            records=payload,
            source_version="30",
            reported_record_count=3,
            cache_ttl_minutes=1440,
            endpoint="/api/powerbi/publications",
            forced_nocache=False,
        ),
    )

    direction = make_user(db_session, email="direcao@islagaia.pt", role=UserRole.DIRECTION)
    orchestrator = AgentOrchestrator(reports_dir=tmp_path)
    result = orchestrator.handle_message(
        db_session,
        user=direction,
        message_text="Gera um relatório institucional do ISLA com PDF e Excel.",
        reference_year=2026,
    )

    summary = result.analytics_summary
    assert summary is not None
    # Estudante (Carla) e categoria desconhecida (Eva) não entram no ranking de docentes
    teacher_names = [r["name"] for r in summary["top_researchers"]]
    student_names = [r["name"] for r in summary["top_students"]]
    assert "Carla Duarte" not in teacher_names
    assert "Eva Externa" not in teacher_names
    assert "Eva Externa" not in student_names
    assert student_names == ["Carla Duarte"]
    assert "Ana Silva" in teacher_names
    assert summary["kpis"]["scoped_unknown_category_count"] == 1

    # Distribuição por estado e sinalização de ano editorial futuro (2027 > 2026)
    assert summary["status_distribution"]["Publicado"] == 2
    assert summary["status_distribution"]["Aceite"] == 1
    assert summary["kpis"]["published_count"] == 2
    assert summary["kpis"]["non_published_count"] == 1
    assert summary["data_quality"]["future_year_publications_count"] == 1

    # Verificar folhas 'Indicadores', 'Docentes', 'Estudantes' e 'Fontes e Critérios' do Excel gerado
    assert result.report_bundle is not None
    xlsx_path = tmp_path / f"{result.report_bundle['report_id']}.xlsx"
    wb = openpyxl.load_workbook(xlsx_path)
    ind_pairs = [r[:2] for r in wb["Indicadores"].iter_rows(values_only=True)]
    assert ("Aceite", 1) in ind_pairs
    docentes_names = [
        row[0] for row in wb["Docentes"].iter_rows(min_row=2, values_only=True) if row[0]
    ]
    estudantes_names = [
        row[0] for row in wb["Estudantes"].iter_rows(min_row=2, values_only=True) if row[0]
    ]
    assert "Carla Duarte" not in docentes_names
    assert "Eva Externa" not in docentes_names
    assert estudantes_names == ["Carla Duarte"]
    src_rows = {row[0]: row[1] for row in wb["Fontes e Critérios"].iter_rows(values_only=True) if row[0]}
    assert src_rows["Publicações com ano editorial futuro (> 2026)"] == 1
