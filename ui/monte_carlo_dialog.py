"""Monte Carlo simulation window (Simulation → Monte Carlo Simulation)."""

from __future__ import annotations

import tkinter as tk
from typing import Optional

import customtkinter as ctk
from tkinter import messagebox

from core.monte_carlo import (
    DEFAULT_N_SIGMA,
    DIST_NORMAL,
    DIST_TRIANGULAR,
    DIST_UNIFORM,
    MonteCarloResult,
    run_monte_carlo,
)
from core.units import (
    format_length,
    from_display,
    length_decimals,
    normalize_unit,
    unit_label,
)

_DIST_LABELS = {
    "Normal": DIST_NORMAL,
    "Uniform": DIST_UNIFORM,
    "Triangular": DIST_TRIANGULAR,
}
_DIST_BY_KEY = {key: label for label, key in _DIST_LABELS.items()}
_TRIAL_PRESETS = (10_000, 50_000, 100_000)
_DEFAULT_TRIALS = 50_000

_CONTRIB_COLORS = (
    "#3b82f6", "#22c55e", "#f59e0b", "#ef4444",
    "#a855f7", "#06b6d4", "#f97316", "#84cc16",
)

_PLOT_BG = "#1e1e1e"
_GRID = "#334155"
_AXIS = "#94a3b8"
_BAR = "#0ea5e9"
_BAR_OUTLINE = "#0c4a6e"
_PDF_LINE = "#e879f9"
_PDF_FILL = "#581c87"
_CDF_LINE = "#38bdf8"
_CDF_FILL = "#164e63"
_MEAN = "#22c55e"
_RSS = "#f59e0b"
_WC = "#ef4444"
_ZERO = "#e2e8f0"
_SPEC = "#a855f7"

# Histogram X-axis zoom. 1.0 = sample distribution fills the plot.
# 0.5 = twice that span, so WC / RSS / spec lines just outside the
# samples stay in view. Same step as the loop canvas.
_ZOOM_STEP = 1.15
_MIN_ZOOM = 0.5
_MAX_ZOOM = 25.0


def _parse_int(text: str) -> Optional[int]:
    raw = (text or "").strip().replace(",", "").replace(" ", "")
    if not raw:
        return None
    return int(raw)


def _parse_float(text: str) -> Optional[float]:
    raw = (text or "").strip().replace(" ", "").replace(",", ".")
    if not raw:
        return None
    return float(raw)


class _SharedView:
    """Linked X-axis window shared by the left plot and the CDF."""

    __slots__ = ("view",)

    def __init__(self) -> None:
        self.view: Optional[tuple[float, float]] = None


class _HistogramCanvas(ctk.CTkFrame):
    """Dark-theme clearance plot: histogram, empirical PDF, or CDF.

    mode='hist'  — bar chart of iterations per bin (Y = count).
    mode='pdf'   — empirical probability density from the same bins (Y = 1/unit).
    mode='cdf'   — empirical cumulative distribution (Y = 0…1).

    X-axis zoom is shared when `shared_view` is passed. Mouse-wheel binding is
    owned by the dialog so two plots cannot steal each other's bind_all handler.
    """

    def __init__(
        self,
        master,
        *,
        mode: str = "hist",
        shared_view: Optional[_SharedView] = None,
        on_view_changed=None,
        on_hover_change=None,
        **kwargs,
    ):
        super().__init__(master, fg_color=_PLOT_BG, **kwargs)
        self._mode = mode if mode in ("hist", "pdf", "cdf") else "hist"
        self._shared_view = shared_view if shared_view is not None else _SharedView()
        self._on_view_changed = on_view_changed
        self._on_hover_change = on_hover_change

        self.canvas = tk.Canvas(self, bg=_PLOT_BG, highlightthickness=0, cursor="crosshair")
        # Inset so rounded CTkFrame corners do not clip axis labels at the edges.
        self.canvas.pack(fill="both", expand=True, padx=4, pady=4)
        self._zoom_bar = None
        self._pad_b = 46
        self._pad_r = 22
        if self._mode == "cdf":
            self._build_zoom_bar()

        self.canvas.bind("<Configure>", lambda _e: self._redraw())
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", self._on_canvas_leave)
        self.canvas.bind("<Enter>", self._on_canvas_enter)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", self._on_double_click)
        self.bind("<Destroy>", self._on_destroy)

        self._result: Optional[MonteCarloResult] = None
        self._unit = "mm"
        self._x_range = (0.0, 1.0)
        self._full_range = (0.0, 1.0)  # 1.0×: sample distribution + pad
        self._world_range = (0.0, 1.0)  # 0.5× extent used to clamp pan / zoom-out
        self._plot = (0, 0, 0, 0)
        self._bins_px = []  # (x0, x1, lo, hi, count_or_density)
        self._panning = False
        self._pan_start_x = 0
        self._pan_view = (0.0, 1.0)

    @property
    def _view(self) -> Optional[tuple[float, float]]:
        return self._shared_view.view

    @_view.setter
    def _view(self, value: Optional[tuple[float, float]]) -> None:
        self._shared_view.view = value

    def _is_pdf(self) -> bool:
        return self._mode == "pdf"

    def _is_cdf(self) -> bool:
        return self._mode == "cdf"

    def set_mode(self, mode: str) -> None:
        """Switch hist/pdf/cdf without resetting zoom or data."""
        new_mode = mode if mode in ("hist", "pdf", "cdf") else "hist"
        if new_mode == self._mode:
            return
        self._mode = new_mode
        self._redraw()

    def _notify_view_changed(self) -> None:
        cb = self._on_view_changed
        if cb is None:
            return
        try:
            cb(self)
        except Exception:
            pass

    def _build_zoom_bar(self) -> None:
        """Vertical ＋ / － / 1:1 overlay on the CDF, bottom-right of the plot."""
        self._zoom_bar = ctk.CTkFrame(self, fg_color="#2b2b2b", corner_radius=8)
        self._btn_in = ctk.CTkButton(
            self._zoom_bar,
            text="＋",
            width=36,
            height=28,
            command=self.zoom_in,
        )
        self._btn_in.pack(side="top", padx=6, pady=(6, 3))
        self._btn_out = ctk.CTkButton(
            self._zoom_bar,
            text="－",
            width=36,
            height=28,
            command=self.zoom_out,
        )
        self._btn_out.pack(side="top", padx=6, pady=3)
        self._btn_reset = ctk.CTkButton(
            self._zoom_bar,
            text="1:1",
            width=36,
            height=28,
            command=self.reset_zoom,
        )
        self._btn_reset.pack(side="top", padx=6, pady=3)
        self._zoom_label = ctk.CTkLabel(
            self._zoom_bar,
            text="1.0×",
            text_color=_AXIS,
            font=ctk.CTkFont(size=11),
            width=36,
        )
        self._zoom_label.pack(side="top", padx=6, pady=(2, 6))
        # Shown after a run; kept off the empty-state placeholder
        self._zoom_bar.place_forget()

    def set_data(self, result: Optional[MonteCarloResult], unit: str) -> None:
        self._result = result
        self._unit = normalize_unit(unit)
        self._view = None
        self._panning = False
        self.canvas.configure(cursor="crosshair")
        self._redraw()

    def zoom_in(self) -> None:
        self._zoom_at(self._plot_center_px(), _ZOOM_STEP)

    def zoom_out(self) -> None:
        self._zoom_at(self._plot_center_px(), 1.0 / _ZOOM_STEP)

    def reset_zoom(self) -> None:
        self._panning = False
        self.canvas.configure(cursor="crosshair")
        if self._view is None:
            return
        self._view = None
        self._redraw()
        self._notify_view_changed()

    def _has_data(self) -> bool:
        return self._result is not None and bool(self._result.hist_counts)

    def _text_size(self, c, text: str, font, *, angle: int = 0) -> tuple[int, int]:
        tid = c.create_text(-2000, -2000, text=text, font=font, angle=angle, anchor="nw")
        bbox = c.bbox(tid)
        c.delete(tid)
        if bbox is None:
            return 0, 0
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def _plot_center_px(self) -> float:
        x0, _y0, x1, _y1 = self._plot
        return (x0 + x1) / 2.0

    def _current_zoom(self) -> float:
        full_lo, full_hi = self._full_range
        lo, hi = self._x_range
        view = hi - lo
        full = full_hi - full_lo
        if view <= 0 or full <= 0:
            return 1.0
        return max(0.05, min(_MAX_ZOOM, full / view))

    def _min_zoom(self) -> float:
        full = self._full_range[1] - self._full_range[0]
        world = self._world_range[1] - self._world_range[0]
        if full <= 0 or world <= 0:
            return _MIN_ZOOM
        return max(0.05, full / world)

    def _sync_zoom_controls(self) -> None:
        bar = self._zoom_bar
        if bar is None:
            return
        has = self._has_data()
        z = self._current_zoom() if has else 1.0
        min_z = self._min_zoom() if has else _MIN_ZOOM
        self._zoom_label.configure(text=f"{z:.1f}×")
        in_state = "normal" if has and z < _MAX_ZOOM - 0.02 else "disabled"
        out_state = "normal" if has and z > min_z + 0.02 else "disabled"
        reset_state = "normal" if has and self._view is not None else "disabled"
        self._btn_in.configure(state=in_state)
        self._btn_out.configure(state=out_state)
        self._btn_reset.configure(state=reset_state)
        if has:
            # Bottom-right, above the X-axis labels, inset from the frame edge.
            bar.place(
                relx=1.0,
                rely=1.0,
                anchor="se",
                x=-(self._pad_r),
                y=-(self._pad_b + 8),
            )
            bar.lift()
        else:
            bar.place_forget()

    def _redraw(self) -> None:
        c = self.canvas
        c.delete("all")
        self._bins_px = []
        w = max(c.winfo_width(), 40)
        h = max(c.winfo_height(), 40)

        result = self._result
        if result is None or not result.hist_counts:
            if self._is_cdf():
                empty = (
                    "Run a simulation to see the cumulative distribution.\n"
                    "Then scroll to zoom, drag to pan, or use ＋ － 1:1."
                )
            elif self._is_pdf():
                empty = (
                    "Run a simulation to see the probability density.\n"
                    "Then scroll to zoom or drag to pan."
                )
            else:
                empty = (
                    "Run a simulation to see the clearance distribution.\n"
                    "Then scroll to zoom or drag to pan."
                )
            c.create_text(
                w / 2,
                h / 2,
                text=empty,
                fill=_AXIS,
                font=("Segoe UI", 13),
                justify="center",
            )
            self._sync_zoom_controls()
            return

        is_pdf = self._is_pdf()
        is_cdf = self._is_cdf()
        ul = unit_label(self._unit)
        font_tick = ("Segoe UI", 8)
        font_caption = ("Segoe UI", 9)

        edges = result.hist_edges
        counts = result.hist_counts
        data_lo, data_hi = edges[0], edges[-1]
        span = data_hi - data_lo
        pad = span * 0.04 if span > 0 else 1e-6
        full_lo, full_hi = data_lo - pad, data_hi + pad
        self._full_range = (full_lo, full_hi)
        self._world_range = self._compute_world_range(full_lo, full_hi)
        self._x_range = self._clamped_view(full_lo, full_hi)
        view_lo, view_hi = self._x_range

        densities = self._density_display() if is_pdf else []
        cdf_vals = self._cdf_right_edges() if is_cdf else []
        if is_cdf:
            # CDF is always 0…1 so P(X ≤ x) can be read off the axis.
            y_max = 1.0
        else:
            # Y-axis follows bins that intersect the current X view so tails stay readable.
            visible_max = 0.0
            series = densities if is_pdf else counts
            for i, value in enumerate(series):
                a, b = edges[i], edges[i + 1]
                if b < view_lo or a > view_hi:
                    continue
                if value > visible_max:
                    visible_max = value
            if visible_max <= 0:
                visible_max = max(series) if series else 1.0
            y_max = visible_max * 1.12 if visible_max > 0 else 1.0

        if is_cdf:
            y_labels = ("0%", "25%", "50%", "75%", "100%")
            y_caption = "F(x)"
        elif is_pdf:
            y_labels = tuple(f"{y_max * i / 4:.3g}" for i in range(1, 4))
            y_caption = f"Density (1/{ul})"
        else:
            y_labels = tuple(f"{int(round(y_max * i / 4)):,}" for i in range(1, 4))
            y_caption = "Iterations"

        y_tick_w = max(self._text_size(c, lab, font_tick)[0] for lab in y_labels)
        cap_w, _cap_h = self._text_size(c, y_caption, font_caption, angle=90)
        tick_h = self._text_size(c, "+0.000", font_tick)[1]
        axis_cap_h = self._text_size(c, "Clearance (mm)", font_caption)[1]
        pad_l = max(56, 10 + cap_w + 6 + y_tick_w + 8)
        pad_r = 22
        pad_t = max(14, tick_h // 2 + 8)
        pad_b = tick_h + 10 + axis_cap_h + 10
        self._pad_r = pad_r
        self._pad_b = pad_b
        x0, y0 = pad_l, pad_t
        x1, y1 = w - pad_r, h - pad_b
        if x1 - x0 < 40 or y1 - y0 < 40:
            self._sync_zoom_controls()
            return
        self._plot = (x0, y0, x1, y1)

        # Plot frame + grid.
        c.create_rectangle(x0, y0, x1, y1, outline=_GRID, width=1)
        if is_cdf:
            # 0% sits above the X-axis so it does not collide with the first X tick.
            c.create_text(
                x0 - 8, y1, text="0%", fill=_AXIS, font=font_tick, anchor="se"
            )
            for frac, label in ((0.25, "25%"), (0.5, "50%"), (0.75, "75%"), (1.0, "100%")):
                yy = y1 - (y1 - y0) * frac
                if frac < 1.0:
                    c.create_line(x0, yy, x1, yy, fill=_GRID, width=1)
                c.create_text(
                    x0 - 8, yy, text=label, fill=_AXIS, font=font_tick, anchor="e"
                )
        else:
            for i in range(1, 4):
                yy = y1 - (y1 - y0) * i / 4
                c.create_line(x0, yy, x1, yy, fill=_GRID, width=1)
                c.create_text(
                    x0 - 8,
                    yy,
                    text=y_labels[i - 1],
                    fill=_AXIS,
                    font=font_tick,
                    anchor="e",
                )

        if is_cdf:
            self._draw_cdf_curve(
                c, edges, cdf_vals, view_lo, view_hi, x0, y0, x1, y1, y_max
            )
        elif is_pdf:
            self._draw_pdf_curve(
                c, edges, densities, view_lo, view_hi, x0, y0, x1, y1, y_max
            )
        else:
            self._draw_hist_bars(
                c, edges, counts, view_lo, view_hi, x0, x1, y1, y_max
            )

        # Overlays
        self._vline(result.mean, _MEAN, width=2)
        self._vline(0.0, _ZERO, dash=(4, 3), width=1)
        self._vline(result.rss_min, _RSS, dash=(5, 3), width=1)
        self._vline(result.rss_max, _RSS, dash=(5, 3), width=1)
        self._vline(result.wc_min, _WC, dash=(2, 3), width=1)
        self._vline(result.wc_max, _WC, dash=(2, 3), width=1)
        if result.lsl is not None:
            self._vline(result.lsl, _SPEC, dash=(6, 2), width=2)
        if result.usl is not None:
            self._vline(result.usl, _SPEC, dash=(6, 2), width=2)

        # X ticks — extra decimals when the view is a narrow slice.
        # First/last labels sit inside the plot so they are not clipped by the frame.
        plot_w = x1 - x0
        if plot_w >= 480:
            n_ticks = 6
        elif plot_w >= 320:
            n_ticks = 5
        elif plot_w >= 220:
            n_ticks = 4
        else:
            n_ticks = 3
        x_lo, x_hi = self._x_range
        tick_span = abs(x_hi - x_lo)
        dec = length_decimals(self._unit)
        if tick_span < 0.02:
            dec = max(dec, 5)
        elif tick_span < 0.2:
            dec = max(dec, 4)
        for i in range(n_ticks + 1):
            xv = x_lo + (x_hi - x_lo) * i / n_ticks
            px = self._x_to_px(xv)
            c.create_line(px, y1, px, y1 + 5, fill=_AXIS)
            label = format_length(xv, self._unit, signed=True, decimals=dec)
            if i == 0:
                tx, anchor = px + 1, "nw"
            elif i == n_ticks:
                tx, anchor = px - 1, "ne"
            else:
                tx, anchor = px, "n"
            c.create_text(
                tx, y1 + 8, text=label, fill=_AXIS, font=font_tick, anchor=anchor
            )

        axis_caption = f"Clearance ({ul})"
        if self._view is not None:
            axis_caption += "  ·  scroll to zoom, drag to pan"
        c.create_text(
            (x0 + x1) / 2,
            h - 8,
            text=axis_caption,
            fill=_AXIS,
            font=font_caption,
            anchor="s",
        )
        c.create_text(
            8 + cap_w / 2.0,
            (y0 + y1) / 2,
            text=y_caption,
            fill=_AXIS,
            font=font_caption,
            angle=90,
        )
        self._sync_zoom_controls()

    def _density_display(self) -> list[float]:
        """Empirical PDF per bin, in 1/(display unit). Area ≈ 1."""
        result = self._result
        if result is None or not result.hist_counts:
            return []
        n = max(int(result.n_trials), 1)
        scale = from_display(1.0, self._unit)
        edges = result.hist_edges
        out: list[float] = []
        for i, count in enumerate(result.hist_counts):
            width = edges[i + 1] - edges[i]
            dens_mm = (count / (n * width)) if width > 1e-15 else 0.0
            out.append(dens_mm * scale)
        return out

    def _draw_hist_bars(
        self, c, edges, counts, view_lo, view_hi, x0, x1, y1, y_max
    ) -> None:
        """Bars sit flush; clip to the plot so zoomed bins do not cover the axes."""
        y0 = self._plot[1]
        for i, count in enumerate(counts):
            a, b = edges[i], edges[i + 1]
            if b < view_lo or a > view_hi:
                continue
            px0 = max(x0, min(x1, self._x_to_px(a)))
            px1 = max(x0, min(x1, self._x_to_px(b)))
            bh = 0.0 if y_max <= 0 else (count / y_max) * (y1 - y0)
            ix0 = int(round(px0))
            ix1 = int(round(px1))
            if ix1 <= ix0:
                ix1 = ix0 + 1
            iy_top = int(round(y1 - bh))
            iy_bot = int(round(y1))
            if count > 0 and iy_bot > iy_top:
                c.create_rectangle(
                    ix0,
                    iy_top,
                    ix1,
                    iy_bot,
                    fill=_BAR,
                    outline=_BAR_OUTLINE,
                    width=1,
                )
            self._bins_px.append((ix0, ix1, a, b, count))

    def _draw_pdf_curve(
        self, c, edges, densities, view_lo, view_hi, x0, y0, x1, y1, y_max
    ) -> None:
        """Filled polyline through bin centers (empirical density)."""
        n = len(densities)
        first = None
        last = None
        for i in range(n):
            a, b = edges[i], edges[i + 1]
            if b < view_lo or a > view_hi:
                continue
            if first is None:
                first = i
            last = i
        if first is None:
            return
        first = max(0, first - 1)
        last = min(n - 1, last + 1)

        pts: list[tuple[float, float]] = []
        for i in range(first, last + 1):
            a, b = edges[i], edges[i + 1]
            dens = densities[i]
            mid = 0.5 * (a + b)
            px = max(x0, min(x1, self._x_to_px(mid)))
            py = y1 if y_max <= 0 else y1 - (dens / y_max) * (y1 - y0)
            py = max(y0, min(y1, py))
            pts.append((px, py))
            if not (b < view_lo or a > view_hi):
                ix0 = int(round(max(x0, min(x1, self._x_to_px(a)))))
                ix1 = int(round(max(x0, min(x1, self._x_to_px(b)))))
                if ix1 <= ix0:
                    ix1 = ix0 + 1
                self._bins_px.append((ix0, ix1, a, b, dens))

        if len(pts) >= 2:
            fill = [pts[0][0], y1]
            for px, py in pts:
                fill.extend((px, py))
            fill.extend((pts[-1][0], y1))
            c.create_polygon(*fill, fill=_PDF_FILL, outline="", smooth=False)
            line = [coord for p in pts for coord in p]
            c.create_line(*line, fill=_PDF_LINE, width=2, smooth=True)
        elif len(pts) == 1:
            px, py = pts[0]
            c.create_line(px, y1, px, py, fill=_PDF_LINE, width=2)

    def _cdf_right_edges(self) -> list[float]:
        """Empirical CDF at each bin's right edge: F = P(X ≤ edge)."""
        result = self._result
        if result is None or not result.hist_counts:
            return []
        n = max(int(result.n_trials), 1)
        out: list[float] = []
        acc = 0
        for count in result.hist_counts:
            acc += count
            out.append(acc / n)
        return out

    def _draw_cdf_curve(
        self, c, edges, cdf_vals, view_lo, view_hi, x0, y0, x1, y1, y_max
    ) -> None:
        """Step CDF: horizontal to the right edge, then jump to F(x)."""
        n = len(cdf_vals)
        first = None
        last = None
        for i in range(n):
            a, b = edges[i], edges[i + 1]
            if b < view_lo or a > view_hi:
                continue
            if first is None:
                first = i
            last = i
        if first is None:
            return
        first = max(0, first - 1)
        last = min(n - 1, last + 1)

        def py_of(f: float) -> float:
            f = min(max(float(f), 0.0), 1.0)
            yy = y1 if y_max <= 0 else y1 - (f / y_max) * (y1 - y0)
            return max(y0, min(y1, yy))

        f_prev = 0.0 if first == 0 else cdf_vals[first - 1]
        pts: list[tuple[float, float]] = []
        start_x = edges[first]
        pts.append((max(x0, min(x1, self._x_to_px(start_x))), py_of(f_prev)))
        for i in range(first, last + 1):
            a, b = edges[i], edges[i + 1]
            f = cdf_vals[i]
            px_b = max(x0, min(x1, self._x_to_px(b)))
            pts.append((px_b, py_of(f_prev)))
            pts.append((px_b, py_of(f)))
            f_prev = f
            if not (b < view_lo or a > view_hi):
                ix0 = int(round(max(x0, min(x1, self._x_to_px(a)))))
                ix1 = int(round(max(x0, min(x1, self._x_to_px(b)))))
                if ix1 <= ix0:
                    ix1 = ix0 + 1
                self._bins_px.append((ix0, ix1, a, b, f))

        if len(pts) >= 2:
            fill = [pts[0][0], y1]
            for px, py in pts:
                fill.extend((px, py))
            fill.extend((pts[-1][0], y1))
            c.create_polygon(*fill, fill=_CDF_FILL, outline="", smooth=False)
            line = [coord for p in pts for coord in p]
            c.create_line(*line, fill=_CDF_LINE, width=2, smooth=False)
        elif len(pts) == 1:
            px, py = pts[0]
            c.create_line(px, y1, px, py, fill=_CDF_LINE, width=2)

    def _envelope_values(self) -> list[float]:
        """WC / RSS edges — zoom-out should be able to show these."""
        r = self._result
        if r is None:
            return []
        return [r.wc_min, r.wc_max, r.rss_min, r.rss_max]

    def _compute_world_range(self, full_lo: float, full_hi: float) -> tuple[float, float]:
        """Extent allowed when zoomed out (0.5×), large enough for WC lines."""
        data_span = full_hi - full_lo
        if data_span <= 0:
            return full_lo, full_hi
        max_span = data_span / _MIN_ZOOM
        mid = 0.5 * (full_lo + full_hi)
        world_lo = mid - max_span / 2.0
        world_hi = mid + max_span / 2.0
        envelopes = self._envelope_values()
        if envelopes:
            pad = max_span * 0.04
            world_lo = min(world_lo, min(envelopes) - pad)
            world_hi = max(world_hi, max(envelopes) + pad)
        return world_lo, world_hi

    def _clamp_window(
        self, lo: float, hi: float, world_lo: float, world_hi: float
    ) -> tuple[float, float]:
        span = hi - lo
        world_span = world_hi - world_lo
        if span <= 0 or world_span <= 0:
            return world_lo, world_hi
        if span >= world_span:
            return world_lo, world_hi
        if lo < world_lo:
            lo = world_lo
            hi = world_lo + span
        if hi > world_hi:
            hi = world_hi
            lo = world_hi - span
        return lo, hi

    def _clamped_view(self, full_lo: float, full_hi: float) -> tuple[float, float]:
        if self._view is None:
            return full_lo, full_hi
        lo, hi = self._view
        span = hi - lo
        full_span = full_hi - full_lo
        if span <= 0 or full_span <= 0:
            self._view = None
            return full_lo, full_hi
        min_span = full_span / _MAX_ZOOM
        world_lo, world_hi = self._world_range
        max_span = world_hi - world_lo
        if span < min_span:
            mid = 0.5 * (lo + hi)
            span = min_span
            lo, hi = mid - span / 2.0, mid + span / 2.0
        if span > max_span:
            self._view = (world_lo, world_hi)
            return world_lo, world_hi
        lo, hi = self._clamp_window(lo, hi, world_lo, world_hi)
        if hi <= lo:
            self._view = None
            return full_lo, full_hi
        self._view = (lo, hi)
        return lo, hi

    def _zoom_at(self, px: float, factor: float) -> None:
        if not self._has_data():
            return
        x0, _y0, x1, _y1 = self._plot
        if x1 - x0 < 40:
            return
        px = min(max(float(px), x0), x1)
        full_lo, full_hi = self._full_range
        full_span = full_hi - full_lo
        cur_lo, cur_hi = self._x_range
        cur_span = cur_hi - cur_lo
        world_lo, world_hi = self._world_range
        max_span = world_hi - world_lo
        if full_span <= 0 or cur_span <= 0 or max_span <= 0:
            return

        anchor = self._px_to_x(px)
        new_span = cur_span / factor
        min_span = full_span / _MAX_ZOOM
        new_span = max(min_span, min(max_span, new_span))
        t = (anchor - cur_lo) / cur_span
        t = min(max(t, 0.0), 1.0)
        new_lo = anchor - t * new_span
        new_hi = new_lo + new_span
        new_lo, new_hi = self._clamp_window(new_lo, new_hi, world_lo, world_hi)
        self._view = (new_lo, new_hi)
        self._redraw()
        self._notify_view_changed()

    def _x_to_px(self, x: float) -> float:
        x0, _y0, x1, _y1 = self._plot
        lo, hi = self._x_range
        if hi <= lo:
            return (x0 + x1) / 2
        t = (x - lo) / (hi - lo)
        return x0 + t * (x1 - x0)

    def _px_to_x(self, px: float) -> float:
        x0, _y0, x1, _y1 = self._plot
        lo, hi = self._x_range
        if x1 <= x0:
            return (lo + hi) / 2
        t = (px - x0) / (x1 - x0)
        return lo + t * (hi - lo)

    def _vline(self, x: float, color: str, *, dash=None, width: int = 1) -> None:
        lo, hi = self._x_range
        if x < lo or x > hi:
            return
        x0, y0, _x1, y1 = self._plot
        px = self._x_to_px(x)
        kwargs = {"fill": color, "width": width}
        if dash is not None:
            kwargs["dash"] = dash
        self.canvas.create_line(px, y0, px, y1, **kwargs)

    def _on_press(self, event) -> None:
        if not self._has_data() or self._view is None:
            return
        x0, y0, x1, y1 = self._plot
        if not (x0 <= event.x <= x1 and y0 <= event.y <= y1):
            return
        self._panning = True
        self._pan_start_x = event.x
        self._pan_view = self._x_range
        self.canvas.configure(cursor="fleur")
        self._clear_hover()

    def _on_drag(self, event) -> None:
        if not self._panning:
            return
        x0, _y0, x1, _y1 = self._plot
        if x1 <= x0:
            return
        lo, hi = self._pan_view
        span = hi - lo
        dx_data = -(event.x - self._pan_start_x) / (x1 - x0) * span
        new_lo = lo + dx_data
        new_hi = hi + dx_data
        world_lo, world_hi = self._world_range
        new_lo, new_hi = self._clamp_window(new_lo, new_hi, world_lo, world_hi)
        self._view = (new_lo, new_hi)
        self._redraw()
        self._notify_view_changed()

    def _on_release(self, _event) -> None:
        if not self._panning:
            return
        self._panning = False
        self.canvas.configure(cursor="crosshair")

    def _on_double_click(self, _event) -> None:
        self.reset_zoom()

    def handle_wheel(self, event) -> bool:
        """Zoom toward the cursor. Returns True if this plot handled the event."""
        if not self._has_data():
            return False
        try:
            widget = self.winfo_containing(event.x_root, event.y_root)
        except tk.TclError:
            return False
        if widget is not self.canvas:
            return False
        # Windows: event.delta; Linux: event.num 4 (up) / 5 (down)
        delta = getattr(event, "delta", 0)
        num = getattr(event, "num", 0)
        if num == 5 or delta < 0:
            factor = 1.0 / _ZOOM_STEP
        else:
            factor = _ZOOM_STEP
        px = event.x_root - self.canvas.winfo_rootx()
        self._zoom_at(px, factor)
        return True

    def _on_canvas_enter(self, _event) -> None:
        cb = self._on_hover_change
        if cb is not None:
            cb(self)

    def _on_canvas_leave(self, _event) -> None:
        self._clear_hover()
        cb = self._on_hover_change
        if cb is not None:
            cb(None)

    def _on_destroy(self, event) -> None:
        if event.widget is self:
            self._clear_hover()

    def _on_motion(self, event) -> None:
        if self._panning:
            return
        self.canvas.delete("hover")
        for px0, px1, lo, hi, count in self._bins_px:
            if px0 <= event.x <= px1:
                ul = unit_label(self._unit)
                a = format_length(lo, self._unit, signed=True)
                b = format_length(hi, self._unit, signed=True)
                if self._is_cdf():
                    text = f"{a} … {b} {ul}   ·   F(x) = {100.0 * count:.1f}%"
                elif self._is_pdf():
                    text = f"{a} … {b} {ul}   ·   f(x) = {count:.4g} / {ul}"
                else:
                    n_trials = max(int(self._result.n_trials), 1) if self._result else 1
                    pct = 100.0 * count / n_trials
                    text = f"{a} … {b} {ul}   ·   {count:,} / {n_trials:,} ({pct:.1f}%)"
                text_id = self.canvas.create_text(
                    -2000,
                    -2000,
                    text=text,
                    fill="#e2e8f0",
                    font=("Segoe UI", 9),
                    anchor="w",
                    tags="hover",
                )
                bbox = self.canvas.bbox(text_id)
                tw = (bbox[2] - bbox[0]) if bbox else 80
                th = (bbox[3] - bbox[1]) if bbox else 14
                pad = 6
                box_w = tw + pad * 2
                box_h = th + pad
                cw = max(self.canvas.winfo_width(), 40)
                ch = max(self.canvas.winfo_height(), 40)
                margin = 10
                box_x = event.x + 12
                box_y = event.y - box_h - 8
                if box_x + box_w > cw - margin:
                    box_x = event.x - box_w - 12
                box_x = min(max(margin, box_x), max(margin, cw - box_w - margin))
                box_y = min(max(margin, box_y), max(margin, ch - box_h - margin))
                self.canvas.coords(text_id, box_x + pad, box_y + box_h / 2.0)
                self.canvas.create_rectangle(
                    box_x,
                    box_y,
                    box_x + box_w,
                    box_y + box_h,
                    fill="#0f172a",
                    outline="#334155",
                    tags="hover",
                )
                self.canvas.tag_raise(text_id)
                return

    def _clear_hover(self) -> None:
        self.canvas.delete("hover")


class MonteCarloDialog(ctk.CTkToplevel):
    """
    Run a Monte Carlo stack-up on the current closed loop.
    Stays open so settings can be changed and re-run.
    """

    def __init__(self, parent, project):
        super().__init__(parent)
        self.title("Monte Carlo Simulation")
        self.geometry("1680x900")
        self.minsize(1360, 760)
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()
        self.project = project
        self.saved = False
        self._result: Optional[MonteCarloResult] = None
        self._shared_view = _SharedView()
        self._hovered_plot = None
        self._plot_wheel_bound = False
        self._syncing_plots = False
        self._unbind_after_id = None

        self.update_idletasks()
        x = parent.winfo_rootx() + max(20, (parent.winfo_width() // 2) - 840)
        y = parent.winfo_rooty() + max(20, (parent.winfo_height() // 2) - 450)
        self.geometry(f"+{x}+{y}")

        unit = normalize_unit(project.display_unit)
        self._unit = unit
        self._ul = unit_label(unit)

        n_dims = sum(1 for a in project.arrows if not a.is_gap)

        # --- layout ---
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=22, pady=(16, 8))

        ctk.CTkLabel(
            header,
            text="Monte Carlo Simulation",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(anchor="w")
        self._header_sub = ctk.CTkLabel(
            header,
            text=(
                f"Each of {n_dims} dimension(s) is sampled, then stacked with the same "
                f"+ gap / − interference sign as Calculate. Values in {self._ul}."
            ),
            text_color="#94a3b8",
            font=ctk.CTkFont(size=12),
            wraplength=1200,
            justify="left",
        )
        self._header_sub.pack(anchor="w", pady=(2, 0))
        header.bind("<Configure>", self._on_header_configure, add="+")

        # Left: settings (fixed panel — content fits, no scrollbar)
        left = ctk.CTkFrame(self, width=300)
        left.grid(row=1, column=0, sticky="nsw", padx=(18, 8), pady=(0, 8))

        ctk.CTkLabel(
            left, text="Settings", font=ctk.CTkFont(size=15, weight="bold")
        ).pack(anchor="w", padx=16, pady=(14, 8))

        ctk.CTkLabel(left, text="Distribution").pack(anchor="w", padx=16)
        self.dist_var = ctk.StringVar(value="Normal")
        self.dist_menu = ctk.CTkOptionMenu(
            left,
            values=list(_DIST_LABELS.keys()),
            variable=self.dist_var,
            command=self._on_dist_change,
            width=260,
        )
        self.dist_menu.pack(anchor="w", padx=16, pady=(4, 6))

        # Kept as one block so show/hide does not scramble pack order
        self._normal_opts = ctk.CTkFrame(left, fg_color="transparent")
        self._sigma_label = ctk.CTkLabel(
            self._normal_opts,
            text="Tolerance band = ± n σ  (typical: 3)",
            wraplength=248,
            justify="left",
        )
        self._sigma_label.pack(anchor="w")
        self.sigma_entry = ctk.CTkEntry(self._normal_opts, width=260)
        self.sigma_entry.insert(0, "3")
        self.sigma_entry.pack(anchor="w", pady=(4, 8))
        self.truncate_var = ctk.BooleanVar(value=True)
        self.truncate_chk = ctk.CTkCheckBox(
            self._normal_opts,
            text="Keep samples inside the band",
            variable=self.truncate_var,
            width=260,
        )
        self.truncate_chk.pack(anchor="w", pady=(0, 4))

        self._trials_label = ctk.CTkLabel(left, text="Number of iterations")
        self._trials_label.pack(anchor="w", padx=16)
        self.trials_var = ctk.StringVar(value=str(_DEFAULT_TRIALS))
        self.trials_entry = ctk.CTkEntry(left, width=260, textvariable=self.trials_var)
        self.trials_entry.pack(anchor="w", padx=16, pady=(4, 6))
        self.trials_entry.bind("<KeyRelease>", self._on_trials_typed)

        self.trials_preset_var = ctk.StringVar(value=str(_DEFAULT_TRIALS))
        trials_radios = ctk.CTkFrame(left, fg_color="transparent")
        trials_radios.pack(anchor="w", padx=16, pady=(0, 10))
        for n in _TRIAL_PRESETS:
            ctk.CTkRadioButton(
                trials_radios,
                text=f"{n:,}",
                variable=self.trials_preset_var,
                value=str(n),
                command=self._on_trials_preset,
                width=160,
            ).pack(anchor="w", pady=2)

        ctk.CTkLabel(left, text="Random seed (optional)").pack(anchor="w", padx=16)
        self.seed_entry = ctk.CTkEntry(left, width=260, placeholder_text="auto")
        self.seed_entry.pack(anchor="w", padx=16, pady=(4, 14))

        ctk.CTkLabel(
            left, text="Spec limits (optional, for yield)", font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=16, pady=(4, 4))
        ctk.CTkLabel(
            left,
            text="Leave empty to skip. LSL 0 = no interference.",
            text_color="#94a3b8",
            font=ctk.CTkFont(size=11),
            wraplength=260,
            justify="left",
        ).pack(anchor="w", padx=16)

        spec_row = ctk.CTkFrame(left, fg_color="transparent")
        spec_row.pack(fill="x", padx=16, pady=(6, 4))
        lsl_col = ctk.CTkFrame(spec_row, fg_color="transparent")
        lsl_col.pack(side="left", fill="x", expand=True, padx=(0, 6))
        usl_col = ctk.CTkFrame(spec_row, fg_color="transparent")
        usl_col.pack(side="left", fill="x", expand=True, padx=(6, 0))
        ctk.CTkLabel(lsl_col, text=f"LSL ({self._ul})").pack(anchor="w")
        self.lsl_entry = ctk.CTkEntry(lsl_col, placeholder_text="none")
        self.lsl_entry.pack(fill="x", pady=(2, 0))
        ctk.CTkLabel(usl_col, text=f"USL ({self._ul})").pack(anchor="w")
        self.usl_entry = ctk.CTkEntry(usl_col, placeholder_text="none")
        self.usl_entry.pack(fill="x", pady=(2, 0))

        self.note = ctk.CTkLabel(
            left,
            text=(
                "Normal: process centered on mean size. Truncation models "
                "100% inspection. Uniform / triangular use only the band."
            ),
            text_color="#94a3b8",
            font=ctk.CTkFont(size=11),
            wraplength=248,
            justify="left",
        )
        self.note.pack(anchor="w", padx=16, pady=(14, 8))

        self.include_pdf_var = ctk.BooleanVar(
            value=bool(getattr(project, "include_mc_in_pdf", True))
        )
        self.include_pdf_chk = ctk.CTkCheckBox(
            left,
            text="Include in PDF report",
            variable=self.include_pdf_var,
            command=self._on_include_pdf,
            width=260,
        )
        self.include_pdf_chk.pack(anchor="w", padx=16, pady=(4, 4))

        self.run_btn = ctk.CTkButton(
            left,
            text="Run simulation",
            width=260,
            height=38,
            fg_color="#0ea5e9",
            hover_color="#0284c7",
            command=self._run,
        )
        self.run_btn.pack(anchor="w", padx=16, pady=(8, 16))

        # Right: histogram/PDF (switchable) + CDF (always) + results
        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=1, column=1, sticky="nsew", padx=(8, 18), pady=(0, 8))
        right.grid_columnconfigure(0, weight=1, uniform="mc_col")
        right.grid_columnconfigure(1, weight=1, uniform="mc_col")
        # Uniform group: empty and filled states keep the same pane sizes (no jump).
        right.grid_rowconfigure(1, weight=5, uniform="mc_row")
        right.grid_rowconfigure(3, weight=3, uniform="mc_row")

        left_hdr = ctk.CTkFrame(right, fg_color="transparent")
        left_hdr.grid(row=0, column=0, sticky="ew", padx=(0, 5), pady=(0, 4))
        self._left_mode_btn = ctk.CTkSegmentedButton(
            left_hdr,
            values=["Histogram", "PDF"],
            command=self._on_left_plot_mode,
            width=220,
            height=28,
        )
        self._left_mode_btn.set("Histogram")
        self._left_mode_btn.pack(side="left")

        right_hdr = ctk.CTkFrame(right, fg_color="transparent")
        right_hdr.grid(row=0, column=1, sticky="ew", padx=(5, 0), pady=(0, 4))
        ctk.CTkLabel(
            right_hdr,
            text="Cumulative probability",
            text_color="#94a3b8",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(side="left")

        self.histogram = _HistogramCanvas(
            right,
            corner_radius=8,
            mode="hist",
            shared_view=self._shared_view,
            on_view_changed=self._on_plot_view_changed,
            on_hover_change=self._on_plot_hover,
        )
        self.histogram.grid(row=1, column=0, sticky="nsew", padx=(0, 5))

        self.cdf_plot = _HistogramCanvas(
            right,
            corner_radius=8,
            mode="cdf",
            shared_view=self._shared_view,
            on_view_changed=self._on_plot_view_changed,
            on_hover_change=self._on_plot_hover,
        )
        self.cdf_plot.grid(row=1, column=1, sticky="nsew", padx=(5, 0))

        legend = ctk.CTkFrame(right, fg_color="transparent")
        legend.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 4))
        for color, label in (
            (_MEAN, "Mean"),
            (_RSS, "RSS min/max"),
            (_WC, "WC min/max"),
            (_ZERO, "Line-to-line (0)"),
            (_SPEC, "Spec limits"),
        ):
            swatch = ctk.CTkFrame(legend, width=12, height=12, fg_color=color, corner_radius=2)
            swatch.pack(side="left", padx=(0, 4))
            swatch.pack_propagate(False)
            ctk.CTkLabel(
                legend, text=label, text_color="#94a3b8", font=ctk.CTkFont(size=11)
            ).pack(side="left", padx=(0, 14))

        self.stats_host = ctk.CTkFrame(right, fg_color=_PLOT_BG, corner_radius=8)
        self.stats_host.grid(row=3, column=0, sticky="nsew", padx=(0, 5), pady=(4, 0))
        self.contrib_host = ctk.CTkFrame(right, fg_color=_PLOT_BG, corner_radius=8)
        self.contrib_host.grid(row=3, column=1, sticky="nsew", padx=(5, 0), pady=(4, 0))
        self._placeholder_results()

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=2, column=0, columnspan=2, pady=(0, 14))
        ctk.CTkButton(
            btn_row,
            text="Close",
            width=110,
            height=36,
            fg_color="#555555",
            hover_color="#666666",
            command=self.destroy,
        ).pack()

        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Return>", lambda _e: self._run())
        self.bind("<Destroy>", self._on_dialog_destroy)
        self._on_dist_change(self.dist_var.get())
        self._restore_from_project()
        self.after(50, self.run_btn.focus)

    def _on_header_configure(self, event) -> None:
        if event.width < 40:
            return
        try:
            self._header_sub.configure(wraplength=max(400, event.width - 4))
        except Exception:
            pass

    def _restore_from_project(self) -> None:
        """Prefill settings and plots from the last saved Monte Carlo run."""
        raw = self.project.monte_carlo
        if not isinstance(raw, dict):
            return
        try:
            result = MonteCarloResult.from_dict(raw)
        except Exception:
            return
        self._result = result
        label = _DIST_BY_KEY.get(result.distribution, "Normal")
        self.dist_var.set(label)
        self._on_dist_change(label)
        if result.n_sigma is not None:
            self.sigma_entry.delete(0, "end")
            self.sigma_entry.insert(0, f"{result.n_sigma:g}")
        self.truncate_var.set(bool(result.truncate))
        self.trials_var.set(str(int(result.n_trials)))
        if int(result.n_trials) in _TRIAL_PRESETS:
            self.trials_preset_var.set(str(int(result.n_trials)))
        else:
            self.trials_preset_var.set("")
        self.seed_entry.delete(0, "end")
        self.seed_entry.insert(0, str(int(result.seed)))
        self.lsl_entry.delete(0, "end")
        self.usl_entry.delete(0, "end")
        if result.lsl is not None:
            self.lsl_entry.insert(
                0, format_length(result.lsl, self._unit, signed=result.lsl < 0)
            )
        if result.usl is not None:
            self.usl_entry.insert(
                0, format_length(result.usl, self._unit, signed=result.usl < 0)
            )
        if result.hist_counts:
            self.histogram.set_data(result, self._unit)
            self.cdf_plot.set_data(result, self._unit)
            self._render_results(result)

    def _on_include_pdf(self) -> None:
        value = bool(self.include_pdf_var.get())
        if bool(getattr(self.project, "include_mc_in_pdf", True)) != value:
            self.project.include_mc_in_pdf = value
            self.saved = True

    def _on_left_plot_mode(self, value: str) -> None:
        """Histogram ↔ PDF on the left plot only. CDF on the right is unchanged."""
        self.histogram.set_mode("pdf" if value == "PDF" else "hist")

    def _cancel_unbind_after(self) -> None:
        after_id = self._unbind_after_id
        if after_id is None:
            return
        self._unbind_after_id = None
        try:
            self.after_cancel(after_id)
        except Exception:
            pass

    def _on_plot_hover(self, plot) -> None:
        self._cancel_unbind_after()
        self._hovered_plot = plot
        if plot is not None:
            self._bind_plot_wheel()
            return
        # Leave: wait so a Leave→Enter hop between the two plots keeps the handler.
        try:
            if self.winfo_exists():
                self._unbind_after_id = self.after(20, self._maybe_unbind_plot_wheel)
        except Exception:
            self._unbind_plot_wheel()

    def _maybe_unbind_plot_wheel(self) -> None:
        self._unbind_after_id = None
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        if self._hovered_plot is None:
            self._unbind_plot_wheel()

    def _bind_plot_wheel(self) -> None:
        if self._plot_wheel_bound:
            return
        self.bind_all("<MouseWheel>", self._on_plot_wheel)
        self.bind_all("<Button-4>", self._on_plot_wheel)
        self.bind_all("<Button-5>", self._on_plot_wheel)
        self._plot_wheel_bound = True

    def _unbind_plot_wheel(self) -> None:
        if not self._plot_wheel_bound:
            return
        try:
            self.unbind_all("<MouseWheel>")
            self.unbind_all("<Button-4>")
            self.unbind_all("<Button-5>")
        except Exception:
            pass
        self._plot_wheel_bound = False

    def _on_plot_wheel(self, event):
        plot = self._hovered_plot
        if plot is None:
            return None
        try:
            if plot.handle_wheel(event):
                return "break"
        except Exception:
            return None
        return None

    def _on_plot_view_changed(self, origin) -> None:
        if self._syncing_plots:
            return
        if not hasattr(self, "histogram") or not hasattr(self, "cdf_plot"):
            return
        other = self.cdf_plot if origin is self.histogram else self.histogram
        self._syncing_plots = True
        try:
            other._redraw()
        except Exception:
            pass
        finally:
            self._syncing_plots = False

    def _on_dialog_destroy(self, event) -> None:
        if event.widget is self:
            self._cancel_unbind_after()
            self._unbind_plot_wheel()

    def _on_trials_preset(self) -> None:
        self.trials_var.set(self.trials_preset_var.get())

    def _on_trials_typed(self, _event=None) -> None:
        n = _parse_int(self.trials_var.get())
        if n in _TRIAL_PRESETS:
            self.trials_preset_var.set(str(n))
        else:
            # Unmatched value: no preset selected
            self.trials_preset_var.set("")

    def _on_dist_change(self, _value=None) -> None:
        dist = _DIST_LABELS.get(self.dist_var.get(), DIST_NORMAL)
        if dist == DIST_NORMAL:
            self._normal_opts.pack(
                anchor="w", padx=16, pady=(0, 8), before=self._trials_label
            )
        else:
            self._normal_opts.pack_forget()

    def _clear_host(self, host) -> None:
        for w in host.winfo_children():
            w.destroy()

    def _placeholder_results(self) -> None:
        self._clear_host(self.contrib_host)
        self._clear_host(self.stats_host)
        for host, text in (
            (self.stats_host, "Statistics and yield will appear here."),
            (self.contrib_host, "Variance contribution will appear here."),
        ):
            ctk.CTkLabel(
                host,
                text=text,
                text_color="#94a3b8",
                font=ctk.CTkFont(size=11),
                anchor="center",
            ).pack(expand=True, fill="both", padx=10, pady=8)

    def _run(self) -> None:
        try:
            n_trials = _parse_int(self.trials_var.get())
            if n_trials is None:
                raise ValueError("Enter the number of iterations (1,000–500,000).")
            dist = _DIST_LABELS.get(self.dist_var.get(), DIST_NORMAL)
            n_sigma = DEFAULT_N_SIGMA
            if dist == DIST_NORMAL:
                parsed = _parse_float(self.sigma_entry.get())
                if parsed is None:
                    raise ValueError("Enter nσ (e.g. 3).")
                n_sigma = parsed
            seed_raw = self.seed_entry.get().strip()
            seed = None
            if seed_raw:
                seed = _parse_int(seed_raw)
                if seed is None:
                    raise ValueError("Seed must be an integer.")
            lsl = self._spec_mm(self.lsl_entry.get())
            usl = self._spec_mm(self.usl_entry.get())
        except ValueError as exc:
            messagebox.showwarning("Invalid input", str(exc), parent=self)
            return

        self.run_btn.configure(state="disabled", text="Running…")
        self.configure(cursor="watch")
        self.update_idletasks()
        try:
            result = run_monte_carlo(
                self.project,
                n_trials=n_trials,
                distribution=dist,
                n_sigma=n_sigma,
                truncate=bool(self.truncate_var.get()),
                seed=seed,
                lsl=lsl,
                usl=usl,
            )
        except Exception as exc:
            messagebox.showerror(
                "Simulation failed",
                f"Could not run Monte Carlo simulation:\n{exc}",
                parent=self,
            )
            return
        finally:
            self.run_btn.configure(state="normal", text="Run simulation")
            self.configure(cursor="")

        self._result = result
        self.project.monte_carlo = result.to_dict()
        self.saved = True
        self.histogram.set_data(result, self._unit)
        self.cdf_plot.set_data(result, self._unit)
        self._render_results(result)

    def _spec_mm(self, text: str) -> Optional[float]:
        raw = (text or "").strip()
        if not raw:
            return None
        value = _parse_float(raw)
        if value is None:
            raise ValueError("Spec limits must be numbers (or empty).")
        return from_display(value, self._unit)

    def _fmt(self, value_mm: float, *, signed: bool = True, decimals: int = 4) -> str:
        return format_length(value_mm, self._unit, signed=signed, decimals=decimals)

    def _render_results(self, r: MonteCarloResult) -> None:
        self._render_contrib(r)
        self._render_stats(r)

    def _render_contrib(self, r: MonteCarloResult) -> None:
        host = self.contrib_host
        self._clear_host(host)
        ctk.CTkLabel(
            host,
            text="Variance contribution",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=20,
            anchor="w",
        ).pack(fill="x", padx=10, pady=(8, 0))
        ctk.CTkLabel(
            host,
            text="Share of simulated stack variance",
            text_color="#94a3b8",
            font=ctk.CTkFont(size=10),
            height=16,
            anchor="w",
        ).pack(fill="x", padx=10, pady=(0, 4))
        if not r.contributions:
            ctk.CTkLabel(
                host,
                text="No independent dimensions.",
                text_color="#94a3b8",
                font=ctk.CTkFont(size=11),
                height=18,
                anchor="w",
            ).pack(anchor="w", padx=10)
            return

        ordered = sorted(r.contributions, key=lambda c: c["percent"], reverse=True)
        min_row = 26
        body = ctk.CTkFrame(host, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)

        canvas = tk.Canvas(body, bg=_PLOT_BG, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ctk.CTkScrollbar(body, orientation="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        def redraw(_event=None) -> None:
            canvas.delete("all")
            width = max(canvas.winfo_width(), 40)
            view_h = max(canvas.winfo_height(), 40)
            n = max(len(ordered), 1)
            need_scroll = n * min_row > view_h + 1
            row_h = float(min_row) if need_scroll else view_h / n
            content_h = n * row_h
            font_size = 9 if row_h >= 16 else 8
            name_w = min(120, max(64, int(width * 0.28)))
            pct_w = 52
            bar_x0 = name_w
            bar_x1 = max(bar_x0 + 40, width - pct_w)
            for i, item in enumerate(ordered):
                y = i * row_h
                color = _CONTRIB_COLORS[i % len(_CONTRIB_COLORS)]
                name = (item.get("name") or "").strip()
                title = f"L{item['id']}" + (f"  {name}" if name else "")
                if len(title) > 18:
                    title = title[:17] + "…"
                pct = float(item["percent"])
                cy = y + row_h / 2.0
                canvas.create_text(
                    8,
                    cy,
                    text=title,
                    fill="#cbd5e1",
                    font=("Segoe UI", font_size),
                    anchor="w",
                )
                bh = max(5.0, min(12.0, row_h - 8))
                by0 = cy - bh / 2.0
                canvas.create_rectangle(
                    bar_x0, by0, bar_x1, by0 + bh, fill="#334155", outline=""
                )
                bw = (bar_x1 - bar_x0) * max(0.0, min(1.0, pct / 100.0))
                if bw > 1:
                    canvas.create_rectangle(
                        bar_x0, by0, bar_x0 + bw, by0 + bh, fill=color, outline=""
                    )
                canvas.create_text(
                    width - 10,
                    cy,
                    text=f"{pct:.1f}%",
                    fill=color,
                    font=("Segoe UI", font_size, "bold"),
                    anchor="e",
                )
            canvas.configure(scrollregion=(0, 0, width, int(round(content_h))))
            if need_scroll:
                if not scrollbar.winfo_ismapped():
                    scrollbar.grid(row=0, column=1, sticky="ns", padx=(4, 0))
            else:
                if scrollbar.winfo_ismapped():
                    scrollbar.grid_forget()
                canvas.yview_moveto(0)

        def on_wheel(event) -> str | None:
            bbox = canvas.bbox("all")
            if bbox is None:
                return None
            content_h = bbox[3] - bbox[1]
            view_h = max(canvas.winfo_height(), 1)
            if content_h <= view_h + 1:
                return None
            delta = getattr(event, "delta", 0)
            num = getattr(event, "num", 0)
            if num == 5 or delta < 0:
                canvas.yview_scroll(1, "units")
            else:
                canvas.yview_scroll(-1, "units")
            return "break"

        canvas.bind("<Configure>", redraw)
        canvas.bind("<Enter>", lambda _e: canvas.focus_set())
        canvas.bind("<MouseWheel>", on_wheel)
        canvas.bind("<Button-4>", on_wheel)
        canvas.bind("<Button-5>", on_wheel)

    def _render_stats(self, r: MonteCarloResult) -> None:
        host = self.stats_host
        self._clear_host(host)
        ul = self._ul
        host.grid_columnconfigure(0, weight=1)
        host.grid_columnconfigure(1, weight=1)

        dist_name = next(
            (label for label, key in _DIST_LABELS.items() if key == r.distribution),
            r.distribution,
        )
        bits = [f"{r.n_trials:,} trials", dist_name]
        if r.n_sigma is not None:
            bits.append(f"±{r.n_sigma:g}σ")
            if r.truncate:
                bits.append("truncated")
        bits.append(f"seed {r.seed}")
        ctk.CTkLabel(
            host,
            text="  ·  ".join(bits),
            text_color="#94a3b8",
            font=ctk.CTkFont(size=10),
            height=18,
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(8, 2))

        self._kv_group(
            host,
            f"Distribution ({ul})",
            [
                ("Mean", self._fmt(r.mean)),
                ("Std dev", self._fmt(r.std, signed=False)),
                ("Min", self._fmt(r.min_val)),
                ("Max", self._fmt(r.max_val)),
            ],
            row=1,
            column=0,
        )

        assembly = [
            ("Gap (> 0)", f"{r.pct_gap:.2f} %"),
            ("Interference (< 0)", f"{r.pct_interference:.2f} %"),
            ("Line-to-line", f"{r.pct_line_to_line:.2f} %"),
        ]
        if r.yield_pct is not None:
            assembly.append(("Yield vs spec", f"{r.yield_pct:.2f} %"))
        if r.pct_below_lsl is not None:
            assembly.append(("Below LSL", f"{r.pct_below_lsl:.2f} %"))
        if r.pct_above_usl is not None:
            assembly.append(("Above USL", f"{r.pct_above_usl:.2f} %"))
        self._kv_group(host, "Assembly", assembly, row=1, column=1)

        self._kv_group(
            host,
            f"Percentiles ({ul})",
            [
                ("P0.135", self._fmt(r.percentiles[0.135])),
                ("P2.5", self._fmt(r.percentiles[2.5])),
                ("P50", self._fmt(r.percentiles[50.0])),
                ("P97.5", self._fmt(r.percentiles[97.5])),
                ("P99.865", self._fmt(r.percentiles[99.865])),
            ],
            row=2,
            column=0,
        )
        self._cmp_group(host, r, row=2, column=1)

        if r.warnings:
            warn_box = ctk.CTkFrame(host, fg_color="#422006", corner_radius=6)
            warn_box.grid(
                row=3, column=0, columnspan=2, sticky="ew", padx=8, pady=(4, 8)
            )
            warn_labels = []
            for warning in r.warnings:
                lab = ctk.CTkLabel(
                    warn_box,
                    text=warning,
                    text_color="#fde68a",
                    font=ctk.CTkFont(size=10),
                    height=16,
                    anchor="w",
                    justify="left",
                    wraplength=360,
                )
                lab.pack(fill="x", padx=8, pady=4)
                warn_labels.append(lab)

            def _fit_warn(event, labels=warn_labels):
                wrap = max(180, event.width - 24)
                for lab in labels:
                    lab.configure(wraplength=wrap)

            warn_box.bind("<Configure>", _fit_warn, add="+")

    def _kv_group(self, parent, title, rows, *, row: int, column: int) -> None:
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=row, column=column, sticky="nsew", padx=10, pady=4)
        ctk.CTkLabel(
            box,
            text=title,
            font=ctk.CTkFont(size=12, weight="bold"),
            height=18,
            anchor="w",
        ).pack(fill="x", pady=(0, 2))
        for label, value in rows:
            line = ctk.CTkFrame(box, fg_color="transparent")
            line.pack(fill="x")
            ctk.CTkLabel(
                line,
                text=label,
                text_color="#94a3b8",
                font=ctk.CTkFont(size=11),
                height=18,
                anchor="w",
            ).pack(side="left")
            ctk.CTkLabel(
                line,
                text=value,
                font=ctk.CTkFont(size=12, weight="bold"),
                height=18,
                anchor="e",
            ).pack(side="right")

    def _cmp_group(self, parent, r: MonteCarloResult, *, row: int, column: int) -> None:
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=row, column=column, sticky="nsew", padx=10, pady=4)
        ctk.CTkLabel(
            box,
            text=f"WC / RSS / MC ({self._ul})",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=18,
            anchor="w",
        ).pack(fill="x", pady=(0, 2))
        grid = ctk.CTkFrame(box, fg_color="transparent")
        grid.pack(fill="x")
        grid.grid_columnconfigure(1, weight=1)
        grid.grid_columnconfigure(2, weight=1)
        head = ctk.CTkFont(size=10)
        val = ctk.CTkFont(size=12, weight="bold")
        ctk.CTkLabel(grid, text="", height=16).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            grid, text="Min", text_color="#94a3b8", font=head, height=16, anchor="e"
        ).grid(row=0, column=1, sticky="e", padx=4)
        ctk.CTkLabel(
            grid, text="Max", text_color="#94a3b8", font=head, height=16, anchor="e"
        ).grid(row=0, column=2, sticky="e", padx=4)
        rows = (
            ("WC", self._fmt(r.wc_min), self._fmt(r.wc_max)),
            ("RSS", self._fmt(r.rss_min), self._fmt(r.rss_max)),
            ("MC ±3σ", self._fmt(r.percentiles[0.135]), self._fmt(r.percentiles[99.865])),
        )
        for i, (name, lo, hi) in enumerate(rows, start=1):
            ctk.CTkLabel(
                grid,
                text=name,
                text_color="#94a3b8",
                font=ctk.CTkFont(size=11),
                height=18,
                anchor="w",
            ).grid(row=i, column=0, sticky="w")
            ctk.CTkLabel(grid, text=lo, font=val, height=18, anchor="e").grid(
                row=i, column=1, sticky="e", padx=4
            )
            ctk.CTkLabel(grid, text=hi, font=val, height=18, anchor="e").grid(
                row=i, column=2, sticky="e", padx=4
            )
