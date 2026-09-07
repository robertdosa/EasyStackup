"""
Build multi-page EasyStackup PDF reports with ReportLab.

Layout:
  Header (title, project, file, date, units, revision, creator)
  1. Loop diagram (embedded image from current canvas)
  2. Dimensions table (flows across pages)
  3. Stack-up results
  4. Tolerance contribution
  5. Monte Carlo (optional — only when a run exists and the user opted in)
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
    Flowable,
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from core.model import Project
from core.monte_carlo import RESULT_PERCENTILES, MonteCarloResult
from core.units import UNIT_IN, format_length, normalize_unit, unit_label


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


_MC_DIST_LABEL = {
    "normal": "Normal",
    "uniform": "Uniform",
    "triangular": "Triangular",
}
_MC_MEAN = colors.HexColor("#16a34a")
_MC_RSS = colors.HexColor("#d97706")
_MC_WC = colors.HexColor("#dc2626")
_MC_ZERO = colors.HexColor("#475569")
_MC_SPEC = colors.HexColor("#7c3aed")
_MC_BAR = colors.HexColor("#0284c7")
_MC_GRID = colors.HexColor("#e2e8f0")
_MC_AXIS = colors.HexColor("#64748b")


class _McHistogram(Flowable):
    """Print-friendly histogram of simulated clearance (from stored bin counts)."""

    def __init__(
        self,
        result: MonteCarloResult,
        unit: str,
        width: float = 170 * mm,
        height: float = 52 * mm,
    ):
        super().__init__()
        self.result = result
        self.unit = unit
        self.width = width
        self.height = height

    def wrap(self, availWidth, availHeight):
        return (self.width, self.height)

    def draw(self):
        r = self.result
        edges = list(r.hist_edges)
        counts = list(r.hist_counts)
        if len(edges) < 2 or not counts:
            return
        c = self.canv
        pad_l, pad_r, pad_t, pad_b = 10, 8, 8, 16
        x0, y0 = pad_l, pad_b
        x1, y1 = self.width - pad_r, self.height - pad_t
        plot_w = x1 - x0
        plot_h = y1 - y0
        if plot_w < 20 or plot_h < 16:
            return

        data_lo, data_hi = edges[0], edges[-1]
        span = data_hi - data_lo
        pad = span * 0.04 if span > 0 else 1e-6
        view_lo, view_hi = data_lo - pad, data_hi + pad
        y_max = max(counts) * 1.12 if max(counts) > 0 else 1.0

        def x_to_px(xv_mm: float) -> float:
            t = (xv_mm - view_lo) / (view_hi - view_lo) if view_hi > view_lo else 0.5
            return x0 + t * plot_w

        def y_to_px(count: float) -> float:
            return y0 + (count / y_max) * plot_h if y_max else y0

        c.setFillColor(colors.HexColor("#f8fafc"))
        c.rect(x0, y0, plot_w, plot_h, fill=1, stroke=0)
        c.setStrokeColor(_MC_GRID)
        c.setLineWidth(0.4)
        for i in range(1, 4):
            yy = y0 + plot_h * i / 4
            c.line(x0, yy, x1, yy)

        c.setFillColor(_MC_BAR)
        c.setStrokeColor(colors.HexColor("#0369a1"))
        c.setLineWidth(0.3)
        n = min(len(counts), len(edges) - 1)
        for i in range(n):
            if counts[i] <= 0:
                continue
            bx0 = x_to_px(edges[i])
            bx1 = x_to_px(edges[i + 1])
            if bx1 <= bx0:
                bx1 = bx0 + 0.6
            top = y_to_px(counts[i])
            c.rect(bx0, y0, bx1 - bx0, max(0.4, top - y0), fill=1, stroke=1)

        def vline(xv_mm: float, color, dash=None, width: float = 0.8):
            if xv_mm < view_lo or xv_mm > view_hi:
                return
            px = x_to_px(xv_mm)
            c.setStrokeColor(color)
            c.setLineWidth(width)
            if dash:
                c.setDash(dash)
            else:
                c.setDash()
            c.line(px, y0, px, y1)
            c.setDash()

        vline(r.mean, _MC_MEAN, width=1.1)
        vline(0.0, _MC_ZERO, dash=[3, 2], width=0.6)
        vline(r.rss_min, _MC_RSS, dash=[4, 2], width=0.7)
        vline(r.rss_max, _MC_RSS, dash=[4, 2], width=0.7)
        vline(r.wc_min, _MC_WC, dash=[2, 2], width=0.7)
        vline(r.wc_max, _MC_WC, dash=[2, 2], width=0.7)
        if r.lsl is not None:
            vline(r.lsl, _MC_SPEC, dash=[5, 2], width=1.0)
        if r.usl is not None:
            vline(r.usl, _MC_SPEC, dash=[5, 2], width=1.0)

        c.setStrokeColor(_SLATE)
        c.setLineWidth(0.7)
        c.rect(x0, y0, plot_w, plot_h, fill=0, stroke=1)

        n_ticks = 5
        c.setFillColor(_MC_AXIS)
        c.setFont("Helvetica", 6)
        for i in range(n_ticks + 1):
            xv = view_lo + (view_hi - view_lo) * i / n_ticks
            px = x_to_px(xv)
            c.setStrokeColor(_MC_AXIS)
            c.setLineWidth(0.5)
            c.line(px, y0, px, y0 - 3)
            label = format_length(xv, self.unit, signed=True)
            if i == 0:
                c.drawString(px, y0 - 11, label)
            elif i == n_ticks:
                c.drawRightString(px, y0 - 11, label)
            else:
                c.drawCentredString(px, y0 - 11, label)

        ul = unit_label(self.unit)
        c.drawCentredString((x0 + x1) / 2, 1, f"Clearance ({ul})")


def parse_monte_carlo(raw: Any) -> Optional[MonteCarloResult]:
    """Accept a MonteCarloResult, a saved dict, or None."""
    if raw is None:
        return None
    if isinstance(raw, MonteCarloResult):
        return raw
    if isinstance(raw, dict):
        try:
            return MonteCarloResult.from_dict(raw)
        except Exception:
            return None
    return None


def _pdf_kv_table(
    rows: List[List[Any]],
    col_widths: List[float],
    header_row: bool = True,
) -> Table:
    table = Table(rows, colWidths=col_widths)
    cmds = [
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, _GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    if header_row:
        cmds.extend(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ]
        )
        start = 1
    else:
        start = 0
    for i in range(start, len(rows)):
        if (i - start) % 2 == 1:
            cmds.append(("BACKGROUND", (0, i), (-1, i), _ROW_ALT))
        cmds.append(("ALIGN", (1, i), (-1, i), "RIGHT"))
    table.setStyle(TableStyle(cmds))
    return table


def _append_monte_carlo_section(
    story: List[Any],
    result: MonteCarloResult,
    unit: str,
    unit_name: str,
    style_h2,
    style_note,
    style_cell,
    style_cell_header,
) -> None:
    dist = _MC_DIST_LABEL.get(result.distribution, result.distribution)
    bits = [f"{result.n_trials:,} trials", dist]
    if result.n_sigma is not None:
        bits.append(f"±{result.n_sigma:g}σ")
        if result.truncate:
            bits.append("truncated to the tolerance band")
    bits.append(f"seed {result.seed}")

    story.append(Paragraph("5. Monte Carlo simulation", style_h2))
    story.append(
        Paragraph(
            "Each contributing dimension is sampled, then stacked with the same "
            "+ gap / − interference sign as Calculate. "
            + "  ·  ".join(bits) + ".",
            style_note,
        )
    )
    story.append(Spacer(1, 2 * mm))

    if result.hist_counts and len(result.hist_edges) >= 2:
        story.append(
            KeepTogether(
                [
                    _McHistogram(result, unit),
                    Paragraph(
                        "Green = mean &nbsp;&nbsp;·&nbsp;&nbsp; Orange dashed = RSS "
                        "&nbsp;&nbsp;·&nbsp;&nbsp; Red dashed = WC "
                        "&nbsp;&nbsp;·&nbsp;&nbsp; Grey dashed = line-to-line (0)"
                        + (
                            " &nbsp;&nbsp;·&nbsp;&nbsp; Purple dashed = spec limits"
                            if (result.lsl is not None or result.usl is not None)
                            else ""
                        ),
                        style_note,
                    ),
                ]
            )
        )
        story.append(Spacer(1, 2.5 * mm))

    def cell(text: str) -> Paragraph:
        return Paragraph(text, style_cell)

    def head(*labels: str) -> List[Paragraph]:
        return [Paragraph(t, style_cell_header) for t in labels]

    fmt = lambda v, signed=True: format_length(v, unit, signed=signed, decimals=4)

    dist_rows = [
        head("Quantity", f"Value [{unit_name}]"),
        [cell("Mean"), cell(fmt(result.mean))],
        [cell("Std dev"), cell(fmt(result.std, signed=False))],
        [cell("Min"), cell(fmt(result.min_val))],
        [cell("Max"), cell(fmt(result.max_val))],
    ]
    story.append(_pdf_kv_table(dist_rows, [50 * mm, 40 * mm]))
    story.append(Spacer(1, 2.5 * mm))

    pct_rows = [head("Percentile", f"Clearance [{unit_name}]")]
    for p in RESULT_PERCENTILES:
        val = result.percentiles.get(p)
        if val is None:
            continue
        label = f"P{p:g}" if p != 50.0 else "P50 (median)"
        pct_rows.append([cell(label), cell(fmt(val))])
    story.append(_pdf_kv_table(pct_rows, [50 * mm, 40 * mm]))
    story.append(Spacer(1, 2.5 * mm))

    assembly = [
        head("Assembly", "Share"),
        [cell("Gap (> 0)"), cell(f"{result.pct_gap:.2f} %")],
        [cell("Interference (< 0)"), cell(f"{result.pct_interference:.2f} %")],
        [cell("Line-to-line"), cell(f"{result.pct_line_to_line:.2f} %")],
    ]
    if result.yield_pct is not None:
        assembly.append([cell("Yield vs spec"), cell(f"{result.yield_pct:.2f} %")])
    if result.pct_below_lsl is not None:
        assembly.append([cell("Below LSL"), cell(f"{result.pct_below_lsl:.2f} %")])
    if result.pct_above_usl is not None:
        assembly.append([cell("Above USL"), cell(f"{result.pct_above_usl:.2f} %")])
    if result.lsl is not None:
        assembly.append([cell(f"LSL [{unit_name}]"), cell(fmt(result.lsl))])
    if result.usl is not None:
        assembly.append([cell(f"USL [{unit_name}]"), cell(fmt(result.usl))])
    story.append(_pdf_kv_table(assembly, [50 * mm, 40 * mm]))
    story.append(Spacer(1, 2.5 * mm))

    p_lo = result.percentiles.get(0.135, result.min_val)
    p_hi = result.percentiles.get(99.865, result.max_val)
    cmp_rows = [
        head("Method", "Min", "Max"),
        [cell("WC"), cell(fmt(result.wc_min)), cell(fmt(result.wc_max))],
        [cell("RSS"), cell(fmt(result.rss_min)), cell(fmt(result.rss_max))],
        [cell("MC ±3σ (P0.135 / P99.865)"), cell(fmt(p_lo)), cell(fmt(p_hi))],
    ]
    story.append(_pdf_kv_table(cmp_rows, [55 * mm, 40 * mm, 40 * mm]))
    story.append(
        Paragraph(
            "MC ±3σ uses the simulated P0.135 / P99.865 percentiles (≈ ±3σ of a normal).",
            style_note,
        )
    )
    story.append(Spacer(1, 2.5 * mm))

    story.append(
        Paragraph(
            "Variance contribution (share of simulated stack variance).",
            style_note,
        )
    )
    story.append(Spacer(1, 1.2 * mm))
    ordered = sorted(
        result.contributions or [],
        key=lambda c: float(c.get("percent", 0)),
        reverse=True,
    )
    if ordered:
        contrib_data: List[List[Any]] = [
            head("Dimension", "Contribution", "%")
        ]
        for i, item in enumerate(ordered):
            cid = item.get("id", "?")
            name = (item.get("name") or "").strip()
            label = f"L{cid}" + (f"  ({name})" if name else "")
            pct = float(item.get("percent", 0))
            bar_color = _CONTRIB_COLORS[i % len(_CONTRIB_COLORS)]
            contrib_data.append(
                [
                    cell(label),
                    _ContributionBar(pct, bar_color, width=95, height=7),
                    cell(f"{pct:.1f}%"),
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
        story.append(Paragraph("No variance contribution data.", style_note))

    for warning in result.warnings or []:
        story.append(Spacer(1, 1.5 * mm))
        story.append(
            Paragraph(
                f"<b>Note:</b> {warning}",
                ParagraphStyle(
                    "McWarnNote",
                    parent=style_note,
                    textColor=colors.HexColor("#b45309"),
                    leading=11,
                ),
            )
        )
    story.append(Spacer(1, 3 * mm))


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
    monte_carlo: Optional[Any] = None,
) -> Path:
    """
    Write a multi-page A4 PDF report.

    results: output of ToleranceCalculator.calculate (mm-based values).
    diagram_image_path: optional PNG/JPEG of the loop diagram at current view.
    project_name: optional override for the report "Project" field (and PDF title).
        If omitted/empty, falls back to project.title, then "New Stackup".
    monte_carlo: optional MonteCarloResult or saved dict; omitted when the user
        did not opt in or no run has been stored.
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

    # ---- 5. Monte Carlo (optional) ----
    mc_result = parse_monte_carlo(monte_carlo)
    if mc_result is not None and mc_result.n_trials > 0:
        _append_monte_carlo_section(
            story,
            mc_result,
            unit,
            unit_name,
            style_h2,
            style_note,
            style_cell,
            style_cell_header,
        )

    # ---- Notes ----
    story.append(Paragraph("Notes", style_h2))
    notes = [
        "• Internal model values are stored in millimetres; displayed units follow the project Options setting.",
        "• ISO 286 deviations use millimetre size ranges.",
        "• The loop diagram (including CL) follows nominal chain geometry, as on technical drawings. "
        "Reported clearance / WC / RSS use mean sizes (mid of each tolerance band).",
        "• Report generated by EasyStackup.",
    ]
    if mc_result is not None and mc_result.n_trials > 0:
        notes.insert(
            3,
            "• Monte Carlo uses assumed distributions (not measured process data); "
            "results vary with trial count and seed.",
        )
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
