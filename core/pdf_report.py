"""
Build multi-page EasyStackup PDF reports with ReportLab.

Layout:
  Header (title, project, file, date, units, revision, creator)
  1. Loop diagram (embedded image from current canvas)
  2. Dimensions table (flows across pages)
  3. Stack-up results
  4. Tolerance contribution
  Notes + footer with page numbers
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
    Flowable,
)

from core.model import Project
from core.units import UNIT_IN, format_length, normalize_unit


# Engineering-report palette
_SLATE = colors.HexColor("#0f172a")
_HEADER_BG = colors.HexColor("#1e293b")
_ROW_ALT = colors.HexColor("#f1f5f9")
_GRID = colors.HexColor("#cbd5e1")
_ACCENT = colors.HexColor("#0ea5e9")
_MUTED = colors.HexColor("#64748b")

_CONTRIB_COLORS = (
    colors.HexColor("#3b82f6"),
    colors.HexColor("#22c55e"),
    colors.HexColor("#f59e0b"),
    colors.HexColor("#ef4444"),
    colors.HexColor("#a855f7"),
    colors.HexColor("#06b6d4"),
    colors.HexColor("#f97316"),
    colors.HexColor("#84cc16"),
)


class _ContributionBar(Flowable):
    """Simple horizontal bar (0–100%) for contribution rows."""

    def __init__(self, percent: float, bar_color, width: float = 120, height: float = 8):
        super().__init__()
        self.percent = max(0.0, min(100.0, float(percent)))
        self.bar_color = bar_color
        self.bar_width = width
        self.bar_height = height
        self.width = width
        self.height = height + 2

    def draw(self):
        self.canv.setFillColor(colors.HexColor("#e2e8f0"))
        self.canv.roundRect(0, 1, self.bar_width, self.bar_height, 2, fill=1, stroke=0)
        fill_w = self.bar_width * (self.percent / 100.0)
        if fill_w > 0.5:
            self.canv.setFillColor(self.bar_color)
            self.canv.roundRect(0, 1, fill_w, self.bar_height, 2, fill=1, stroke=0)


def _display_unit_name(unit: str | None) -> str:
    """User-facing unit word for report headings: mm | inch."""
    return "inch" if normalize_unit(unit) == UNIT_IN else "mm"


def _dir_label(direction: int) -> str:
    return "+" if direction >= 0 else "−"


def _safe_filename(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in ("-", "_", " ") else "_" for c in name)
    cleaned = "_".join(cleaned.split())
    return cleaned or "EasyStackup_report"


def build_report_filename(project_title: str, revision: str) -> str:
    base = _safe_filename(project_title or "stackup")
    raw = (revision or "-").strip()
    # Initial rev is "-"; letter revs are uppercase A, B, …
    rev = raw if raw == "-" else (raw.upper() or "-")
    return f"{base}_Rev{rev}.pdf"


def export_pdf_report(
    path: str | Path,
    project: Project,
    results: Dict[str, Any],
    *,
    diagram_image_path: Optional[str | Path] = None,
    file_path: Optional[str] = None,
    project_name: Optional[str] = None,
    revision: str = "-",
    creator: str = "",
) -> Path:
    """
    Write a multi-page A4 PDF report.

    results: output of ToleranceCalculator.calculate (mm-based values).
    diagram_image_path: optional PNG/JPEG of the loop diagram at current view.
    project_name: optional override for the report "Project" field (and PDF title).
        If omitted/empty, falls back to project.title, then "New Stackup".
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    unit = normalize_unit(project.display_unit)
    unit_name = _display_unit_name(unit)
    # Prefer explicit export name; otherwise project title
    title = (project_name or "").strip() or (project.title or "New Stackup").strip()
    file_name = Path(file_path).name if file_path else "—"
    raw_rev = (revision or "-").strip()
    rev = raw_rev if raw_rev == "-" else raw_rev.upper()
    creator_text = (creator or "").strip() or "—"
    generated = datetime.now().strftime("%Y-%m-%d  %H:%M")

    styles = getSampleStyleSheet()
    style_title = ParagraphStyle(
        "ESTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=16,
        textColor=_SLATE,
        spaceAfter=2 * mm,
        leading=20,
    )
    style_subtitle = ParagraphStyle(
        "ESSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        textColor=_MUTED,
        spaceAfter=4 * mm,
    )
    style_h2 = ParagraphStyle(
        "ESH2",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        textColor=_SLATE,
        spaceBefore=4 * mm,
        spaceAfter=2.5 * mm,
        leading=15,
    )
    style_note = ParagraphStyle(
        "ESNote",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        textColor=_MUTED,
        leading=11,
        spaceBefore=1 * mm,
    )
    style_meta_label = ParagraphStyle(
        "ESMetaLabel",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        textColor=_MUTED,
        leading=12,
    )
    style_meta_value = ParagraphStyle(
        "ESMetaValue",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        textColor=_SLATE,
        leading=12,
    )
    style_cell = ParagraphStyle(
        "ESCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        textColor=_SLATE,
        leading=10,
    )
    style_cell_header = ParagraphStyle(
        "ESCellHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        textColor=colors.white,
        leading=10,
        alignment=TA_CENTER,
    )

    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"{title} — Tolerance Stack-up Report",
        author=creator_text if creator_text != "—" else "EasyStackup",
        subject=f"Revision {rev}",
        creator="EasyStackup",
    )

    story: List[Any] = []

    # ---- Title block ----
    story.append(Paragraph("EasyStackup", style_title))
    story.append(Paragraph("Tolerance Stack-up Report", style_subtitle))

    meta_rows = [
        [
            Paragraph("Project", style_meta_label),
            Paragraph(title, style_meta_value),
            Paragraph("Revision", style_meta_label),
            Paragraph(rev, style_meta_value),
        ],
        [
            Paragraph("File", style_meta_label),
            Paragraph(file_name, style_meta_value),
            Paragraph("Creator", style_meta_label),
            Paragraph(creator_text, style_meta_value),
        ],
        [
            Paragraph("Date", style_meta_label),
            Paragraph(generated, style_meta_value),
            Paragraph("Units", style_meta_label),
            Paragraph(unit_name, style_meta_value),
        ],
    ]
    meta_table = Table(meta_rows, colWidths=[22 * mm, 68 * mm, 22 * mm, 58 * mm])
    meta_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                ("LINEBELOW", (0, -1), (-1, -1), 0.6, _ACCENT),
            ]
        )
    )
    story.append(meta_table)
    story.append(Spacer(1, 5 * mm))

    # ---- 1. Loop diagram ----
    story.append(Paragraph("1. Loop diagram", style_h2))
    if diagram_image_path and Path(diagram_image_path).is_file():
        max_w = A4[0] - 30 * mm
        max_h = 85 * mm
        img = Image(str(diagram_image_path))
        # Scale to fit width / height box while keeping aspect ratio
        iw, ih = float(img.imageWidth), float(img.imageHeight)
        if iw > 0 and ih > 0:
            scale = min(max_w / iw, max_h / ih, 1.0)
            img.drawWidth = iw * scale
            img.drawHeight = ih * scale
        story.append(img)
        story.append(
            Paragraph(
                "Diagram captured from the current canvas view (zoom and pan as set by the user).",
                style_note,
            )
        )
    else:
        story.append(
            Paragraph(
                "<i>Loop diagram image was not available for this export.</i>",
                style_note,
            )
        )
    story.append(
        Paragraph(
            "Green → positive direction &nbsp;&nbsp;·&nbsp;&nbsp; Red → negative direction "
            "&nbsp;&nbsp;·&nbsp;&nbsp; Orange dashed (CL) → clearance closing dimension",
            style_note,
        )
    )
    story.append(
        Paragraph(
            "Loop geometry (including CL) is drawn from <b>nominal</b> dimensions, matching "
            "typical technical drawings. Stack-up results below use each dimension’s "
            "<b>mean size</b> (mid of the tolerance band). With symmetric ± tolerances these "
            "agree; with bilateral or ISO fits that shift the mean, reported clearance can "
            "differ from the drawn nominal CL.",
            style_note,
        )
    )
    story.append(Spacer(1, 3 * mm))

    # ---- 2. Dimensions table ----
    story.append(Paragraph(f"2. Dimensions [{unit_name}]", style_h2))

    headers = [
        Paragraph("ID", style_cell_header),
        Paragraph("Name", style_cell_header),
        Paragraph("Dir", style_cell_header),
        Paragraph("Nominal", style_cell_header),
        Paragraph("Mean", style_cell_header),
        Paragraph("Tolerance", style_cell_header),
        Paragraph("Eq. ±", style_cell_header),
    ]
    table_data: List[List[Any]] = [headers]

    dims = [a for a in project.arrows if not a.is_gap]
    for a in dims:
        name = (a.name or "").strip() or "—"
        table_data.append(
            [
                Paragraph(f"L{a.id}", style_cell),
                Paragraph(name, style_cell),
                Paragraph(_dir_label(a.direction), style_cell),
                Paragraph(format_length(a.nominal, unit), style_cell),
                Paragraph(format_length(a.mean_size, unit), style_cell),
                Paragraph(a.format_tolerance(unit), style_cell),
                Paragraph(a.format_equal_bilateral(unit), style_cell),
            ]
        )

    if len(table_data) == 1:
        table_data.append(
            [Paragraph("—", style_cell)] * 7
        )

    col_widths = [14 * mm, 38 * mm, 12 * mm, 22 * mm, 22 * mm, 42 * mm, 20 * mm]
    dim_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("ALIGN", (2, 1), (2, -1), "CENTER"),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, _GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    for i in range(1, len(table_data)):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), _ROW_ALT))
    dim_table.setStyle(TableStyle(style_cmds))
    story.append(dim_table)
    story.append(
        Paragraph(
            "Dir: + = positive (→), − = negative (←). Mean uses mid of tolerance band; "
            "Eq. ± is the equal-bilateral equivalent around the mean.",
            style_note,
        )
    )
    story.append(Spacer(1, 3 * mm))

    # ---- 3. Results ----
    story.append(Paragraph(f"3. Stack-up results [{unit_name}]", style_h2))

    result_rows = [
        [
            Paragraph("Quantity", style_cell_header),
            Paragraph(f"Value [{unit_name}]", style_cell_header),
        ],
        [
            Paragraph("Clearance (mean)", style_cell),
            Paragraph(format_length(results.get("nominal", 0), unit, signed=True, decimals=4), style_cell),
        ],
        [
            Paragraph("WC Min", style_cell),
            Paragraph(format_length(results.get("wc_min", 0), unit, signed=True, decimals=4), style_cell),
        ],
        [
            Paragraph("WC Max", style_cell),
            Paragraph(format_length(results.get("wc_max", 0), unit, signed=True, decimals=4), style_cell),
        ],
        [
            Paragraph("RSS Min", style_cell),
            Paragraph(format_length(results.get("rss_min", 0), unit, signed=True, decimals=4), style_cell),
        ],
        [
            Paragraph("RSS Max", style_cell),
            Paragraph(format_length(results.get("rss_max", 0), unit, signed=True, decimals=4), style_cell),
        ],
    ]
    res_table = Table(result_rows, colWidths=[55 * mm, 40 * mm])
    res_style = [
        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, _GRID),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("ALIGN", (1, 1), (1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#e0f2fe")),
    ]
    for i in range(2, len(result_rows)):
        if i % 2 == 0:
            res_style.append(("BACKGROUND", (0, i), (-1, i), _ROW_ALT))
    res_table.setStyle(TableStyle(res_style))
    story.append(res_table)
    story.append(
        Paragraph(
            "Sign convention: + = clearance (gap) &nbsp;&nbsp;·&nbsp;&nbsp; − = interference. "
            "WC = worst-case; RSS = root-sum-square. "
            "Clearance (mean) is the residual of directed mean sizes, not the drawn nominal CL length.",
            style_note,
        )
    )
    for warning in results.get("warnings") or []:
        story.append(Spacer(1, 1.5 * mm))
        story.append(
            Paragraph(
                f"<b>Note:</b> {warning}",
                ParagraphStyle(
                    "WarnNote",
                    parent=style_note,
                    textColor=colors.HexColor("#b45309"),
                    leading=11,
                ),
            )
        )
    story.append(Spacer(1, 3 * mm))

    # ---- 4. Contributions ----
    story.append(Paragraph("4. Tolerance contribution", style_h2))
    story.append(
        Paragraph(
            "Share of total tolerance band width (drives WC spread).",
            style_note,
        )
    )
    story.append(Spacer(1, 1.5 * mm))

    contributions: Sequence[Dict[str, Any]] = results.get("contributions") or []
    ordered = sorted(contributions, key=lambda c: float(c.get("percent", 0)), reverse=True)

    if ordered:
        contrib_header = [
            Paragraph("Dimension", style_cell_header),
            Paragraph("Contribution", style_cell_header),
            Paragraph("%", style_cell_header),
        ]
        contrib_data: List[List[Any]] = [contrib_header]
        for i, c in enumerate(ordered):
            cid = c.get("id", "?")
            name = (c.get("name") or "").strip()
            label = f"L{cid}" + (f"  ({name})" if name else "")
            pct = float(c.get("percent", 0))
            bar_color = _CONTRIB_COLORS[i % len(_CONTRIB_COLORS)]
            contrib_data.append(
                [
                    Paragraph(label, style_cell),
                    _ContributionBar(pct, bar_color, width=95, height=7),
                    Paragraph(f"{pct:.1f}%", style_cell),
                ]
            )
        contrib_table = Table(contrib_data, colWidths=[70 * mm, 100 * mm, 18 * mm])
        c_style = [
            ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.35, _GRID),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("ALIGN", (2, 1), (2, -1), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]
        for i in range(1, len(contrib_data)):
            if i % 2 == 0:
                c_style.append(("BACKGROUND", (0, i), (-1, i), _ROW_ALT))
        contrib_table.setStyle(TableStyle(c_style))
        story.append(contrib_table)
    else:
        story.append(Paragraph("No contribution data.", style_note))

    story.append(Spacer(1, 5 * mm))

    # ---- Notes ----
    story.append(Paragraph("Notes", style_h2))
    notes = [
        "• Internal model values are stored in millimetres; displayed units follow the project Options setting.",
        "• ISO 286 deviations use millimetre size ranges.",
        "• The loop diagram (including CL) follows nominal chain geometry, as on technical drawings. "
        "Reported clearance / WC / RSS use mean sizes (mid of each tolerance band).",
        "• Report generated by EasyStackup.",
    ]
    for line in notes:
        story.append(Paragraph(line, style_note))

    def _on_page(canvas, doc_):
        canvas.saveState()
        page_w, page_h = A4
        # Top thin accent line
        canvas.setStrokeColor(_ACCENT)
        canvas.setLineWidth(1.2)
        canvas.line(15 * mm, page_h - 10 * mm, page_w - 15 * mm, page_h - 10 * mm)

        # Footer
        canvas.setStrokeColor(_GRID)
        canvas.setLineWidth(0.5)
        canvas.line(15 * mm, 11 * mm, page_w - 15 * mm, 11 * mm)

        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(_MUTED)
        canvas.drawString(15 * mm, 6 * mm, "Generated with EasyStackup")
        canvas.drawRightString(
            page_w - 15 * mm,
            6 * mm,
            f"Rev {rev}  ·  Page {doc_.page}",
        )
        canvas.restoreState()

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return path
