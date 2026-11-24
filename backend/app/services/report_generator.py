import json
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.core.config import get_settings

NAVY = colors.HexColor("#0F2A4A")
SLATE = colors.HexColor("#2B547E")
LIGHT_BG = colors.HexColor("#F2F5F9")
BORDER_GREY = colors.HexColor("#CBD5E1")
ACCENT_TEAL = colors.HexColor("#0D9488")


def _safe_xml(text: Any) -> str:
    s = "" if text is None else str(text)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_scope_description(scope: dict[str, Any]) -> str:
    parts: list[str] = []
    if scope.get("school_code"):
        parts.append(f"Escola: {scope['school_code']}")
    else:
        parts.append("Âmbito: Institucional (todas as escolas)")
    if scope.get("year_from") and scope.get("year_to"):
        parts.append(f"Período: {scope['year_from']}–{scope['year_to']}")
    elif scope.get("year_from"):
        parts.append(f"A partir de: {scope['year_from']}")
    elif scope.get("year_to"):
        parts.append(f"Até: {scope['year_to']}")
    if scope.get("compare_years"):
        y1, y2 = scope["compare_years"]
        parts.append(f"Comparação: {y1} vs {y2}")
    return " | ".join(parts)


def _build_annual_bar_chart(annual_evolution: list[dict[str, Any]]) -> Drawing | None:
    if not annual_evolution:
        return None
    drawing = Drawing(450, 190)
    drawing.add(
        String(
            225,
            175,
            "Evolução Anual: Total de Publicações vs Indexadas (Scopus/WoS)",
            textAnchor="middle",
            fontSize=10,
            fontName="Helvetica-Bold",
            fillColor=NAVY,
        )
    )
    chart = VerticalBarChart()
    chart.x = 40
    chart.y = 30
    chart.height = 125
    chart.width = 380
    chart.data = [
        [row["publications"] for row in annual_evolution],
        [row["indexed_scopus_or_wos"] for row in annual_evolution],
    ]
    chart.categoryAxis.categoryNames = [str(row["year"]) for row in annual_evolution]
    chart.valueAxis.valueMin = 0
    max_val = max((row["publications"] for row in annual_evolution), default=1)
    chart.valueAxis.valueMax = max(max_val + 1, 2)
    chart.bars[0].fillColor = NAVY
    chart.bars[1].fillColor = ACCENT_TEAL
    chart.barSpacing = 2
    chart.groupSpacing = 12
    drawing.add(chart)
    return drawing


def _build_quartile_chart(quartile_distribution: dict[str, int]) -> Drawing:
    labels = ["Q1", "Q2", "Q3", "Q4", "Sem quartil"]
    values = [quartile_distribution.get(k, 0) for k in labels]
    drawing = Drawing(450, 175)
    drawing.add(
        String(
            225,
            160,
            "Distribuição de Publicações por Quartil",
            textAnchor="middle",
            fontSize=10,
            fontName="Helvetica-Bold",
            fillColor=NAVY,
        )
    )
    chart = VerticalBarChart()
    chart.x = 40
    chart.y = 25
    chart.height = 115
    chart.width = 380
    chart.data = [values]
    chart.categoryAxis.categoryNames = labels
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = max(max(values, default=1) + 1, 2)
    chart.bars[0].fillColor = SLATE
    drawing.add(chart)
    return drawing


def _styled_table(data: list[list[Any]], col_widths: list[float] | None = None) -> Table:
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8.5),
                ("FONTSIZE", (0, 1), (-1, -1), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
                ("GRID", (0, 0), (-1, -1), 0.4, BORDER_GREY),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


class ReportGeneratorService:
    """
    Gera relatórios PDF (ReportLab) e Excel (OpenPyXL) a partir de resultados
    analíticos determinísticos já filtrados por RBAC.
    """

    def generate_pdf_bytes(
        self,
        report_data: dict[str, Any],
        *,
        title: str = "Relatório de Produção Científica — ISLA",
    ) -> bytes:
        buf = BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=1.8 * cm,
            rightMargin=1.8 * cm,
            topMargin=1.8 * cm,
            bottomMargin=1.8 * cm,
            title=title,
            author="ISLA Institutional AI Agent",
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "ReportCoverTitle",
            parent=styles["Title"],
            fontSize=20,
            leading=24,
            textColor=NAVY,
            spaceAfter=12,
        )
        h2 = ParagraphStyle(
            "SectionHeading",
            parent=styles["Heading2"],
            fontSize=12.5,
            leading=16,
            textColor=NAVY,
            spaceBefore=12,
            spaceAfter=6,
        )
        body = ParagraphStyle(
            "BodyTextPT",
            parent=styles["BodyText"],
            fontSize=9.5,
            leading=13.5,
            spaceAfter=6,
        )
        small = ParagraphStyle(
            "SmallNote",
            parent=styles["BodyText"],
            fontSize=8.2,
            leading=11.5,
            textColor=colors.HexColor("#475569"),
        )

        scope = report_data["scope"]
        kpis = report_data["kpis"]
        status_dist = report_data.get("status_distribution") or {}
        annual = report_data["annual_evolution"]
        quartiles = report_data["quartile_distribution"]
        top_researchers = report_data["top_researchers"]
        top_students = report_data.get("top_students") or []
        comparison = report_data.get("year_comparison")
        quality = report_data["data_quality"]
        sources = report_data["sources"]
        repro_id = report_data["reproducibility_id"]
        generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

        story: list[Any] = []

        # 1. Capa e identificação do relatório
        story.append(Spacer(1, 2.2 * cm))
        story.append(Paragraph("ISLA — Instituto Politécnico de Gestão e Tecnologia", small))
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph(_safe_xml(title), title_style))
        story.append(Paragraph(_safe_xml(_format_scope_description(scope)), body))
        story.append(Spacer(1, 0.8 * cm))
        meta_table = _styled_table(
            [
                ["Campo", "Valor"],
                ["Data de geração", generated_at],
                ["ID de reprodutibilidade", repro_id],
                ["Perfil solicitante", scope.get("requested_by_role", "N/A")],
                ["Fontes utilizadas", str(len(sources))],
            ],
            col_widths=[5.5 * cm, 11.5 * cm],
        )
        story.append(meta_table)
        story.append(PageBreak())

        # 2. Resumo executivo
        story.append(Paragraph("1. Resumo Executivo", h2))
        exec_summary = (
            f"No âmbito analisado ({_format_scope_description(scope)}), foram identificadas "
            f"<b>{kpis['publications']}</b> publicações científicas ativas, das quais "
            f"<b>{kpis['indexed_scopus_or_wos']}</b> ({kpis['indexed_pct']}%) estão indexadas "
            f"em Scopus ({kpis['scopus']}) e/ou Web of Science ({kpis['wos']}). "
            f"O total acumulado de citações é de <b>{kpis['citations']}</b> "
            f"(média de {kpis['avg_citations']} citações/publicação), com "
            f"<b>{kpis['open_access']}</b> publicações em Open Access ({kpis['open_access_pct']}%)."
        )
        story.append(Paragraph(exec_summary, body))

        # 3. Objetivos e âmbito
        story.append(Paragraph("2. Objetivos e Âmbito", h2))
        story.append(
            Paragraph(
                "Este relatório consolida de forma determinística os registos bibliográficos "
                "sincronizados do Portal Científico do ISLA com os dados institucionais de docentes "
                "importados da intranet, assegurando rastreabilidade das fontes e cumprimento das "
                "regras de controlo de acesso (RBAC).",
                body,
            )
        )

        # 4. Indicadores principais
        story.append(Paragraph("3. Indicadores Principais", h2))
        kpi_rows = [
            ["Indicador", "Valor"],
            ["Total de publicações", str(kpis["publications"])],
            ["Indexadas em Scopus", f"{kpis['scopus']} ({kpis['scopus_pct']}%)"],
            ["Indexadas em Web of Science", f"{kpis['wos']} ({kpis['wos_pct']}%)"],
            ["Indexadas (Scopus ou WoS)", f"{kpis['indexed_scopus_or_wos']} ({kpis['indexed_pct']}%)"],
            ["Publicações Q1 / Q2 / Q3 / Q4", f"{kpis['q1']} / {kpis['q2']} / {kpis['q3']} / {kpis['q4']}"],
            ["Total de citações (média)", f"{kpis['citations']} ({kpis['avg_citations']})"],
            ["Open Access", f"{kpis['open_access']} ({kpis['open_access_pct']}%)"],
            [
                "Publicações por estado",
                ", ".join(f"{k}: {v}" for k, v in status_dist.items()) or "N/D",
            ],
            [
                "Investigadores no âmbito (Docentes / Estudantes)",
                f"{kpis.get('scoped_teachers_count', kpis['scoped_researchers_count'])} / {kpis.get('scoped_students_count', 0)}",
            ],
        ]
        story.append(_styled_table(kpi_rows, col_widths=[9.5 * cm, 7.5 * cm]))
        story.append(Spacer(1, 0.4 * cm))

        # 5. Gráficos e tabelas
        story.append(Paragraph("4. Gráficos e Tabelas", h2))
        annual_chart = _build_annual_bar_chart(annual)
        if annual_chart:
            story.append(annual_chart)
            story.append(Spacer(1, 0.3 * cm))

        if annual:
            ann_rows = [
                ["Ano", "Total", "Scopus", "WoS", "Q1", "Q2", "Q3", "Q4", "Citações", "OA"]
            ]
            for r in annual:
                ann_rows.append(
                    [
                        str(r["year"]),
                        str(r["publications"]),
                        str(r["scopus"]),
                        str(r["wos"]),
                        str(r["q1"]),
                        str(r["q2"]),
                        str(r["q3"]),
                        str(r["q4"]),
                        str(r["citations"]),
                        str(r["open_access"]),
                    ]
                )
            story.append(_styled_table(ann_rows, col_widths=[1.7 * cm] * 10))
            story.append(Spacer(1, 0.4 * cm))

        story.append(_build_quartile_chart(quartiles))
        story.append(Spacer(1, 0.4 * cm))

        if top_researchers:
            story.append(Paragraph("Docentes Mais Produtivos (Categoria: Teacher)", h2))
            res_rows = [["Docente", "Escola", "Pubs", "Scopus", "WoS", "Q1", "Citações"]]
            for r in top_researchers:
                res_rows.append(
                    [
                        _safe_xml(r["name"]),
                        r.get("school_code") or "-",
                        str(r["publications"]),
                        str(r["scopus"]),
                        str(r["wos"]),
                        str(r["q1"]),
                        str(r["citations"]),
                    ]
                )
            story.append(
                _styled_table(
                    res_rows,
                    col_widths=[6.8 * cm, 1.8 * cm, 1.6 * cm, 1.7 * cm, 1.5 * cm, 1.4 * cm, 2.2 * cm],
                )
            )
            story.append(Spacer(1, 0.4 * cm))

        if top_students:
            story.append(Paragraph("Produção Científica de Estudantes (Categoria: Student)", h2))
            stu_rows = [["Estudante", "Escola", "Pubs", "Scopus", "WoS", "Q1", "Citações"]]
            for r in top_students:
                stu_rows.append(
                    [
                        _safe_xml(r["name"]),
                        r.get("school_code") or "-",
                        str(r["publications"]),
                        str(r["scopus"]),
                        str(r["wos"]),
                        str(r["q1"]),
                        str(r["citations"]),
                    ]
                )
            story.append(
                _styled_table(
                    stu_rows,
                    col_widths=[6.8 * cm, 1.8 * cm, 1.6 * cm, 1.7 * cm, 1.5 * cm, 1.4 * cm, 2.2 * cm],
                )
            )
            story.append(Spacer(1, 0.4 * cm))

        if comparison:
            ya, yb = comparison["year_a"], comparison["year_b"]
            story.append(Paragraph(f"Comparação Direta: {ya} vs {yb}", h2))
            comp_rows = [["Métrica", str(ya), str(yb), "Variação", "Variação (%)"]]
            labels = [
                ("publications", "Publicações"),
                ("scopus", "Scopus"),
                ("wos", "Web of Science"),
                ("q1", "Quartil Q1"),
                ("citations", "Citações"),
                ("open_access", "Open Access"),
            ]
            for key, label in labels:
                d = comparison["deltas"][key]
                sign = "+" if d["delta"] > 0 else ""
                comp_rows.append(
                    [label, str(d["year_a"]), str(d["year_b"]), f"{sign}{d['delta']}", f"{sign}{d['delta_pct']}%"]
                )
            story.append(
                _styled_table(comp_rows, col_widths=[5.5 * cm, 2.8 * cm, 2.8 * cm, 2.9 * cm, 3.0 * cm])
            )
            story.append(Spacer(1, 0.4 * cm))

        # 6. Análise dos resultados e Conclusões
        story.append(Paragraph("5. Análise dos Resultados e Conclusões", h2))
        if annual:
            peak = max(annual, key=lambda r: r["publications"])
            story.append(
                Paragraph(
                    f"O pico anual de produção ocorreu em <b>{peak['year']}</b> com "
                    f"<b>{peak['publications']}</b> publicações ({peak['indexed_scopus_or_wos']} indexadas). "
                    f"Do total analisado, <b>{kpis['q1']}</b> publicações situam-se em Q1 e "
                    f"<b>{quality['missing_quartile_count']}</b> não possuem quartil atribuído.",
                    body,
                )
            )
        else:
            story.append(
                Paragraph(
                    "Não foram encontradas publicações ativas para os critérios selecionados.",
                    body,
                )
            )

        # 7. Fontes de informação e data de atualização
        story.append(Paragraph("6. Fontes de Informação e Data de Atualização", h2))
        if sources:
            src_rows = [["Fonte", "Origem", "Versão", "Registos", "Atualização (UTC)"]]
            for s in sources:
                src_rows.append(
                    [
                        _safe_xml(s["label"]),
                        _safe_xml(s["endpoint_or_filename"]),
                        str(s["version"]),
                        str(s["record_count"]),
                        str(s["synced_at"])[:19],
                    ]
                )
            story.append(
                _styled_table(src_rows, col_widths=[4.2 * cm, 4.3 * cm, 2.2 * cm, 2.0 * cm, 4.3 * cm])
            )
        else:
            story.append(Paragraph("Nenhuma fonte sincronizada registada.", small))

        # 8. Metodologia e limitações
        story.append(Paragraph("7. Metodologia e Limitações", h2))
        lim_lines = [
            f"Publicações com ano editorial futuro (> {quality.get('reference_year', 'atual')}): {quality.get('future_year_publications_count', 0)}.",
            f"Publicações sem DOI normalizado: {quality['missing_doi_count']}.",
            f"Publicações sem quartil (Q1–Q4): {quality['missing_quartile_count']}.",
            f"Ligações de autoria sem correspondência exata na intranet: {quality['unmatched_author_links_count']}.",
            f"Hipóteses de correspondência apenas por nome pendentes de validação: {quality['name_hypotheses_pending_validation']}.",
            f"Docentes com identificador Ciência Vitae duplicado na intranet: {quality['duplicate_cv_researchers_count']}.",
            *quality["unconfirmed_dictionary_notes"],
        ]
        for line in lim_lines:
            story.append(Paragraph(f"• {_safe_xml(line)}", small))

        doc.build(story)
        return buf.getvalue()

    def generate_excel_bytes(
        self,
        report_data: dict[str, Any],
        *,
        title: str = "Relatório de Produção Científica — ISLA",
    ) -> bytes:
        wb = openpyxl.Workbook()
        header_fill = PatternFill(start_color="0F2A4A", end_color="0F2A4A", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True)
        title_font = Font(color="0F2A4A", bold=True, size=13)

        def style_header_row(ws, row_idx: int) -> None:
            for cell in ws[row_idx]:
                if cell.value is not None:
                    cell.fill = header_fill
                    cell.font = header_font
                    cell.alignment = Alignment(vertical="center")

        def autosize(ws) -> None:
            for col in ws.columns:
                max_len = 0
                col_letter = get_column_letter(col[0].column)
                for cell in col:
                    val = str(cell.value or "")
                    max_len = max(max_len, len(val))
                ws.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 48)

        scope = report_data["scope"]
        kpis = report_data["kpis"]
        status_dist = report_data.get("status_distribution") or {}
        annual = report_data["annual_evolution"]
        quartiles = report_data["quartile_distribution"]
        top_researchers = report_data["top_researchers"]
        comparison = report_data.get("year_comparison")
        publications = report_data["publications"]
        researchers = report_data["researchers"]
        quality = report_data["data_quality"]
        sources = report_data["sources"]

        # Folha 1: Resumo
        ws_resumo = wb.active
        ws_resumo.title = "Resumo"
        ws_resumo.append([title])
        ws_resumo["A1"].font = title_font
        ws_resumo.append(["Âmbito", _format_scope_description(scope)])
        ws_resumo.append(["Data de geração (UTC)", datetime.now(UTC).isoformat(timespec="seconds")])
        ws_resumo.append(["ID de reprodutibilidade", report_data["reproducibility_id"]])
        ws_resumo.append([])
        ws_resumo.append(["Indicador", "Valor"])
        style_header_row(ws_resumo, 6)
        for label, val in [
            ("Total de publicações", kpis["publications"]),
            ("Indexadas Scopus", kpis["scopus"]),
            ("Indexadas Scopus (%)", kpis["scopus_pct"]),
            ("Indexadas WoS", kpis["wos"]),
            ("Indexadas WoS (%)", kpis["wos_pct"]),
            ("Indexadas (Scopus ou WoS)", kpis["indexed_scopus_or_wos"]),
            ("Quartil Q1", kpis["q1"]),
            ("Quartil Q2", kpis["q2"]),
            ("Quartil Q3", kpis["q3"]),
            ("Quartil Q4", kpis["q4"]),
            ("Total de citações", kpis["citations"]),
            ("Média de citações", kpis["avg_citations"]),
            ("Open Access", kpis["open_access"]),
            ("Open Access (%)", kpis["open_access_pct"]),
            ("Docentes no âmbito", kpis["scoped_researchers_count"]),
        ]:
            ws_resumo.append([label, val])
        autosize(ws_resumo)

        # Folha 2: Indicadores
        ws_ind = wb.create_sheet("Indicadores")
        ws_ind.append(["Ano", "Publicações", "Scopus", "WoS", "Scopus ou WoS", "Q1", "Q2", "Q3", "Q4", "Citações", "Open Access"])
        style_header_row(ws_ind, 1)
        for row in annual:
            ws_ind.append(
                [
                    row["year"],
                    row["publications"],
                    row["scopus"],
                    row["wos"],
                    row["indexed_scopus_or_wos"],
                    row["q1"],
                    row["q2"],
                    row["q3"],
                    row["q4"],
                    row["citations"],
                    row["open_access"],
                ]
            )
        ws_ind.append([])
        q_start = ws_ind.max_row + 1
        ws_ind.append(["Quartil", "Publicações"])
        style_header_row(ws_ind, q_start)
        for k, v in quartiles.items():
            ws_ind.append([k, v])

        if status_dist:
            ws_ind.append([])
            s_start = ws_ind.max_row + 1
            ws_ind.append(["Estado da Publicação", "Publicações"])
            style_header_row(ws_ind, s_start)
            for st_label, st_count in status_dist.items():
                ws_ind.append([st_label, st_count])

        if comparison:
            ws_ind.append([])
            c_start = ws_ind.max_row + 1
            ws_ind.append(
                ["Métrica", str(comparison["year_a"]), str(comparison["year_b"]), "Variação", "Variação (%)"]
            )
            style_header_row(ws_ind, c_start)
            for metric_key, d in comparison["deltas"].items():
                ws_ind.append([metric_key, d["year_a"], d["year_b"], d["delta"], d["delta_pct"]])
        ws_ind.freeze_panes = "A2"
        autosize(ws_ind)

        # Folha 3: Publicações
        ws_pubs = wb.create_sheet("Publicações")
        ws_pubs.append(
            [
                "Portal ID",
                "Ano",
                "Título",
                "Tipo",
                "Estado",
                "Autores",
                "Escolas",
                "Revista / Conferência",
                "Quartil",
                "Scopus",
                "WoS",
                "Citações",
                "Open Access",
                "DOI",
                "Referência APA",
            ]
        )
        style_header_row(ws_pubs, 1)
        for p in publications:
            venue = p["journal_name"] or p["conference_name"] or p["venue_name"] or ""
            ws_pubs.append(
                [
                    p["portal_id"],
                    p["year"],
                    p["title"],
                    p["pub_type"],
                    p["status"],
                    p["authors"],
                    p["schools"],
                    venue,
                    p["quartile"],
                    "Sim" if p["is_indexed_scopus"] else "Não",
                    "Sim" if p["is_indexed_wos"] else "Não",
                    p["citations_count"],
                    "Sim" if p["is_open_access"] else "Não",
                    p["doi"],
                    p["apa_citation"],
                ]
            )
        ws_pubs.freeze_panes = "A2"
        autosize(ws_pubs)

        # Folha 4: Docentes
        ws_doc = wb.create_sheet("Docentes")
        ws_doc.append(
            [
                "Docente",
                "Ciência Vitae ID",
                "Escola",
                "Grau (código bruto)",
                "Estado (código bruto)",
                "Categoria",
                "Publicações",
                "Scopus",
                "WoS",
                "Q1",
                "Citações",
            ]
        )
        style_header_row(ws_doc, 1)
        for r in top_researchers:
            ws_doc.append(
                [
                    r["name"],
                    r["ciencia_vitae_id"],
                    r["school_code"],
                    r["degree_code"],
                    r["status_code"],
                    r["category"],
                    r["publications"],
                    r["scopus"],
                    r["wos"],
                    r["q1"],
                    r["citations"],
                ]
            )
        ws_doc.freeze_panes = "A2"
        autosize(ws_doc)

        # Folha 5: Dados Detalhados
        ws_det = wb.create_sheet("Dados Detalhados")
        ws_det.append(
            [
                "Docente (Intranet)",
                "Ciência Vitae ID",
                "Email (RBAC)",
                "Escola",
                "Afiliação",
                "Área Formação",
                "Grau (bruto)",
                "Estado (bruto)",
                "Categoria",
                "Scholar h-index",
                "Scopus h-index",
                "WoS h-index",
                "Alertas Qualidade",
            ]
        )
        style_header_row(ws_det, 1)
        for r in researchers:
            ws_det.append(
                [
                    r["name"],
                    r["ciencia_vitae_id"],
                    r["email"],
                    r["school_code"],
                    r["affiliation"],
                    r["training_area"],
                    r["degree_code"],
                    r["status_code"],
                    r["category"],
                    r["scholar_h_index"],
                    r["scopus_h_index"],
                    r["wos_h_index"],
                    "; ".join(r.get("data_quality_flags") or []),
                ]
            )
        ws_det.freeze_panes = "A2"
        autosize(ws_det)

        # Folha 6: Fontes e Critérios
        ws_src = wb.create_sheet("Fontes e Critérios")
        ws_src.append(["Fonte", "Origem", "Versão", "SHA-256", "Registos", "Atualização (UTC)"])
        style_header_row(ws_src, 1)
        for s in sources:
            ws_src.append(
                [
                    s["label"],
                    s["endpoint_or_filename"],
                    s["version"],
                    s["content_hash"],
                    s["record_count"],
                    s["synced_at"],
                ]
            )
        ws_src.append([])
        crit_row = ws_src.max_row + 1
        ws_src.append(["Critério / Qualidade", "Valor"])
        style_header_row(ws_src, crit_row)
        ws_src.append(["ID de reprodutibilidade", report_data["reproducibility_id"]])
        ws_src.append(["Critérios (JSON)", json.dumps(scope, ensure_ascii=False)])
        ws_src.append(
            [
                f"Publicações com ano editorial futuro (> {quality.get('reference_year', 'atual')})",
                quality.get("future_year_publications_count", 0),
            ]
        )
        ws_src.append(["Publicações sem DOI", quality["missing_doi_count"]])
        ws_src.append(["Publicações sem quartil", quality["missing_quartile_count"]])
        ws_src.append(["Autores sem correspondência exata", quality["unmatched_author_links_count"]])
        ws_src.append(["Hipóteses por nome pendentes", quality["name_hypotheses_pending_validation"]])
        for note in quality["unconfirmed_dictionary_notes"]:
            ws_src.append(["Nota metodológica", note])
        autosize(ws_src)

        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def save_report_bundle(
        self,
        report_data: dict[str, Any],
        *,
        owner_id: UUID,
        title: str,
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        base_dir = output_dir or Path(get_settings().reports_output_dir)
        base_dir.mkdir(parents=True, exist_ok=True)

        report_id = str(uuid4())
        pdf_bytes = self.generate_pdf_bytes(report_data, title=title)
        xlsx_bytes = self.generate_excel_bytes(report_data, title=title)

        pdf_path = base_dir / f"{report_id}.pdf"
        xlsx_path = base_dir / f"{report_id}.xlsx"
        meta_path = base_dir / f"{report_id}.meta.json"

        pdf_path.write_bytes(pdf_bytes)
        xlsx_path.write_bytes(xlsx_bytes)
        meta_path.write_text(
            json.dumps(
                {
                    "report_id": report_id,
                    "owner_id": str(owner_id),
                    "title": title,
                    "reproducibility_id": report_data["reproducibility_id"],
                    "scope": report_data["scope"],
                    "created_at": datetime.now(UTC).isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        return {
            "report_id": report_id,
            "title": title,
            "reproducibility_id": report_data["reproducibility_id"],
            "pdf_url": f"/api/v1/reports/{report_id}/pdf",
            "excel_url": f"/api/v1/reports/{report_id}/excel",
            "pdf_size_bytes": len(pdf_bytes),
            "excel_size_bytes": len(xlsx_bytes),
        }
