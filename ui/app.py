"""Main EasyStackup application window and canvas logic."""

from __future__ import annotations

import math
import tempfile
from pathlib import Path
from typing import Callable, Optional, Sequence, Tuple

import customtkinter as ctk
from tkinter import ttk, filedialog, messagebox
import tkinter as tk
from core.model import Project
from core.calculator import ToleranceCalculator
from core.project_io import save_project, DEFAULT_EXTENSION, DEFAULT_ORIGIN_X
from core.units import UNIT_IN, format_length, normalize_unit, unit_label
from core.pdf_report import build_report_filename, export_pdf_report
from ui.about_dialog import AboutDialog
from ui.dimension_dialog import DimensionDialog
from ui.options_dialog import OptionsDialog
from ui.pdf_export_dialog import PdfExportDialog
from ui.monte_carlo_dialog import MonteCarloDialog

# Canvas zoom. Fit-on-open may use the full range; mouse ＋/－ stay inside it.
_MIN_ZOOM = 0.4
_MAX_ZOOM = 8.0
# Fraction of the canvas kept as empty margin when fitting a loaded loop.
_FIT_MARGIN = 0.14


class EasyStackupApp:
    def __init__(
        self,
        root: ctk.CTk,
        project: Project = None,
        original_start_x: float = DEFAULT_ORIGIN_X,
        file_path: str = None,
        on_new: Optional[Callable[[], None]] = None,
        on_open: Optional[Callable[[str], None]] = None,
        on_exit: Optional[Callable[[], None]] = None,
    ):
        """
        Build the workspace into an existing CTk root (do not create a second CTk).
        CustomTkinter breaks if multiple roots are created/destroyed in one process.
        """
        self.root = root
        self.on_new = on_new
        self.on_open = on_open
        self.on_exit = on_exit
        self.root.geometry("1680x860")
        self.root.resizable(True, True)
        # Maximize on open (Windows). Falls back gracefully elsewhere.
        try:
            self.root.state("zoomed")
        except Exception:
            try:
                self.root.attributes("-zoomed", True)
            except Exception:
                pass

        self.project = project if project is not None else Project()
        self.file_path = file_path
        self.calculator = ToleranceCalculator()
        self.start_x = None
        self.start_y = None
        self.temp_line = None
        self.is_drawing = False
        self.zoom = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self._fit_pending = False
        self.is_panning = False
        self.pan_start_x = 0
        self.pan_start_y = 0
        self.snap_points = []
        self.all_faces = []
        self.current_face_x = None
        self.SNAP_TOLERANCE = 25
        self.original_start_x = float(original_start_x)
        self.has_gap = any(a.is_gap for a in self.project.arrows)
        self.selected_id = None  # currently selected arrow id
        self.hover_id = None
        self.hover_text_id = None
        self.edit_mode = False  # True while we are editing an existing arrow
        self._menubar = None
        # Unsaved-changes flag: False for a freshly opened or empty new project
        self._dirty = False
        self.create_ui()
        self._sync_geometry_from_project()
        self._update_window_title()

    def teardown(self):
        """Unbind global keys / clear menubar before the shell destroys workspace widgets."""
        try:
            self.root.unbind("<Delete>")
            self.root.unbind("<BackSpace>")
            self.root.unbind_all("<Control-s>")
            self.root.unbind_all("<Control-S>")
        except Exception:
            pass
        # Native menubar lives on the root, not as a packed child
        try:
            self.root.config(menu="")
        except Exception:
            pass
        self._menubar = None

    def _update_window_title(self):
        name = self.project.title if self.project.title else "New Stackup"
        if self.file_path:
            name = Path(self.file_path).stem
            self.project.title = name
        dirty = " *" if self._dirty else ""
        self.root.title(f"EasyStackup - {name}{dirty}")

    def _mark_dirty(self):
        """Record that the project has unsaved changes."""
        if self._dirty:
            return
        self._dirty = True
        self._update_window_title()

    def _clear_dirty(self):
        """Clear the unsaved-changes flag (after a successful save)."""
        if not self._dirty:
            return
        self._dirty = False
        self._update_window_title()

    def confirm_leave(self) -> bool:
        """
        Public hook for the shell (window X, etc.).
        Returns True if it is OK to leave the workspace.
        """
        return self._confirm_save_before_leave()

    def _create_menubar(self):
        """
        Native Windows-style menu bar (File / Export / Simulation / Help).
        """
        menubar = tk.Menu(self.root)

        # --- File ---
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New project", command=self._menu_new_project)
        file_menu.add_command(label="Open project", command=self._menu_open_project)
        file_menu.add_separator()
        file_menu.add_command(
            label="Save", command=self.save_project_file, accelerator="Ctrl+S"
        )
        file_menu.add_command(label="Save As…", command=self.save_project_as)
        file_menu.add_separator()
        file_menu.add_command(label="Options", command=self._menu_options)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._menu_exit)
        menubar.add_cascade(label="File", menu=file_menu)

        # --- Export ---
        export_menu = tk.Menu(menubar, tearoff=0)
        export_menu.add_command(label="Export PDF report", command=self._menu_export_pdf)
        export_menu.add_command(label="Export loop diagram as PNG", command=self._menu_export_png)
        export_menu.add_command(label="Export loop diagram as SVG", command=self._menu_export_svg)
        menubar.add_cascade(label="Export", menu=export_menu)

        # --- Simulation ---
        sim_menu = tk.Menu(menubar, tearoff=0)
        sim_menu.add_command(
            label="Monte Carlo Simulation",
            command=self._menu_monte_carlo,
        )
        menubar.add_cascade(label="Simulation", menu=sim_menu)

        # --- Help ---
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About EasyStackup", command=self._menu_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)
        self._menubar = menubar

    def _confirm_save_before_leave(self) -> bool:
        """
        If the project has unsaved changes, ask Yes / No / Cancel before leaving.

        Returns True if the caller may proceed (saved, discarded, or nothing to save).
        Returns False if the user cancelled or save failed — stay on the project.
        """
        if not self._dirty:
            return True

        answer = messagebox.askyesnocancel(
            "Unsaved changes",
            "The current project has unsaved changes.\n\n"
            "Do you want to save before continuing?",
            parent=self.root,
        )
        if answer is None:
            # Cancel — stay
            return False
        if answer:
            # Yes — save, then leave only if save succeeded
            return self.save_project_file()
        # No — discard changes and leave
        return True

    def _menu_new_project(self):
        if not self._confirm_save_before_leave():
            return
        if self.on_new is not None:
            self.on_new()

    def _menu_open_project(self):
        if not self._confirm_save_before_leave():
            return
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Open EasyStackup project",
            filetypes=[
                ("EasyStackup project", f"*{DEFAULT_EXTENSION}"),
                ("JSON files", "*.json"),
                ("All files", "*.*"),
            ],
        )
        if path and self.on_open is not None:
            self.on_open(path)

    def _menu_options(self):
        dialog = OptionsDialog(self.root, display_unit=self.project.display_unit)
        self.root.wait_window(dialog)
        if dialog.result is None:
            return
        new_unit = normalize_unit(dialog.result.get("display_unit"))
        if new_unit == normalize_unit(self.project.display_unit):
            return
        self.project.display_unit = new_unit
        self._mark_dirty()
        self._refresh_dimensions_heading()
        self.update_ui()
        # Refresh results if a closed loop already has calculated values
        if self.has_gap and self.result_frame.winfo_children():
            self.calculate()

    def _menu_exit(self):
        if not self._confirm_save_before_leave():
            return
        if self.on_exit is not None:
            self.on_exit()

    def _menu_about(self):
        dialog = AboutDialog(self.root)
        self.root.wait_window(dialog)

    def _menu_monte_carlo(self):
        """Open the Monte Carlo simulation window for the current closed loop."""
        if not self.project.arrows:
            messagebox.showwarning(
                "Nothing to simulate",
                "Add at least one dimension before running a simulation.",
                parent=self.root,
            )
            return

        if not self.has_gap:
            messagebox.showwarning(
                "Loop not closed",
                "Close the loop (Add Clearance) before running a Monte Carlo "
                "simulation.\nStack-up results require a closed loop.",
                parent=self.root,
            )
            return

        dialog = MonteCarloDialog(self.root, project=self.project)
        self.root.wait_window(dialog)
        if getattr(dialog, "saved", False):
            self._mark_dirty()

    def _menu_export_pdf(self):
        """
        Open export dialog, auto-calculate, capture the current canvas view,
        and write a multi-page PDF report into the chosen folder.
        """
        if not self.project.arrows:
            messagebox.showwarning(
                "Nothing to export",
                "Add at least one dimension before exporting a report.",
                parent=self.root,
            )
            return

        if not self.has_gap:
            messagebox.showwarning(
                "Loop not closed",
                "Close the loop (Add Clearance) before exporting a PDF report.\n"
                "Stack-up results require a closed loop.",
                parent=self.root,
            )
            return

        initial_folder = None
        if self.file_path:
            parent = Path(self.file_path).parent
            if parent.is_dir():
                initial_folder = str(parent)

        dialog = PdfExportDialog(self.root, initial_folder=initial_folder)
        self.root.wait_window(dialog)
        if dialog.result is None:
            return

        folder = dialog.result["folder"]
        revision = dialog.result["revision"]
        creator = dialog.result["creator"]
        # Empty project name → use saved file name (stem); else fall back to project title
        project_name = (dialog.result.get("project_name") or "").strip()
        if not project_name:
            if self.file_path:
                project_name = Path(self.file_path).stem or (self.project.title or "stackup")
            else:
                project_name = (self.project.title or "stackup").strip() or "stackup"

        # Auto-calculate so results always match the current project
        try:
            results = self.calculator.calculate(self.project)
            # Refresh on-screen results as well
            self.calculate()
        except Exception as exc:
            messagebox.showerror(
                "Calculate failed",
                f"Could not calculate stack-up results:\n{exc}",
                parent=self.root,
            )
            return

        out_name = build_report_filename(project_name, revision)
        out_path = Path(folder) / out_name

        if out_path.exists():
            overwrite = messagebox.askyesno(
                "Overwrite file?",
                f"A file already exists:\n{out_path}\n\nOverwrite it?",
                parent=self.root,
            )
            if not overwrite:
                return

        diagram_path = None
        try:
            diagram_path = self._capture_canvas_image()
            mc_payload = None
            if getattr(self.project, "include_mc_in_pdf", True) and self.project.monte_carlo:
                mc_payload = self.project.monte_carlo
            export_pdf_report(
                out_path,
                self.project,
                results,
                diagram_image_path=diagram_path,
                file_path=self.file_path,
                project_name=project_name,
                revision=revision,
                creator=creator,
                monte_carlo=mc_payload,
            )
        except Exception as exc:
            messagebox.showerror(
                "Export failed",
                f"Could not export PDF report:\n{exc}",
                parent=self.root,
            )
            return
        finally:
            if diagram_path is not None:
                try:
                    Path(diagram_path).unlink(missing_ok=True)
                except Exception:
                    pass

        messagebox.showinfo(
            "Export complete",
            f"PDF report saved to:\n{out_path}",
            parent=self.root,
        )

    def _capture_canvas_image(self) -> str:
        """
        Capture the loop diagram at the current zoom/pan into a temporary PNG for PDF.

        Does not screen-grab the widget (that would include zoom buttons and other chrome).
        Renders faces/arrows/labels only — same clean content as Export PNG — then
        composites onto white for the report page.
        """
        from PIL import Image

        self._clear_hover_label()
        diagram = self._render_loop_diagram_rgba()

        # White page background (transparent export looks washed out / wrong in some PDF viewers)
        img = Image.new("RGB", diagram.size, (255, 255, 255))
        if diagram.mode == "RGBA":
            img.paste(diagram, mask=diagram.split()[3])
        else:
            img.paste(diagram)

        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp_path = tmp.name
        tmp.close()
        img.save(tmp_path, format="PNG")
        return tmp_path

    @staticmethod
    def _hex_rgba(hex_color: str, alpha: int = 255) -> Tuple[int, int, int, int]:
        h = hex_color.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return (r, g, b, alpha)

    @staticmethod
    def _pil_font(size: int):
        """Load a TTF close to Arial; fall back to PIL default."""
        from PIL import ImageFont

        candidates = (
            "arial.ttf",
            "Arial.ttf",
            "segoeui.ttf",
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\segoeui.ttf",
            r"C:\Windows\Fonts\calibri.ttf",
        )
        for name in candidates:
            try:
                return ImageFont.truetype(name, max(8, int(size)))
            except OSError:
                continue
        return ImageFont.load_default()

    @staticmethod
    def _draw_dashed_line(
        draw,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        fill,
        width: int,
        dash: Sequence[int] = (8, 4),
    ) -> None:
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length < 0.5:
            return
        ux, uy = dx / length, dy / length
        pattern = list(dash) if dash else [8, 4]
        dist = 0.0
        draw_on = True
        pi = 0
        while dist < length:
            seg = max(1.0, float(pattern[pi % len(pattern)]))
            next_dist = min(length, dist + seg)
            if draw_on:
                sx = x1 + ux * dist
                sy = y1 + uy * dist
                ex = x1 + ux * next_dist
                ey = y1 + uy * next_dist
                draw.line([(sx, sy), (ex, ey)], fill=fill, width=max(1, width))
            dist = next_dist
            draw_on = not draw_on
            pi += 1

    @staticmethod
    def _arrow_head_geometry(
        x1: float, y1: float, x2: float, y2: float, width: float
    ) -> Optional[Tuple[float, float, float, float, Tuple[float, float], Tuple[float, float]]]:
        """
        Shaft end + arrow tip polygon for a line from (x1,y1) to (x2,y2).
        Returns (shaft_end_x, shaft_end_y, tip_x, tip_y, left, right) or None if too short.
        """
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length < 1.0:
            return None
        ux, uy = dx / length, dy / length
        head_len = max(10.0, width * 3.5)
        head_w = max(6.0, width * 2.2)
        shaft_end_x = x2 - ux * head_len * 0.85
        shaft_end_y = y2 - uy * head_len * 0.85
        left = (
            x2 - ux * head_len + uy * head_w,
            y2 - uy * head_len - ux * head_w,
        )
        right = (
            x2 - ux * head_len - uy * head_w,
            y2 - uy * head_len + ux * head_w,
        )
        return (shaft_end_x, shaft_end_y, x2, y2, left, right)

    @classmethod
    def _draw_arrowed_line(
        cls,
        draw,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        fill,
        width: int,
        dash: Optional[Sequence[int]] = None,
    ) -> None:
        """Line with a filled arrow head at (x2, y2), matching the canvas style."""
        geom = cls._arrow_head_geometry(x1, y1, x2, y2, width)
        if geom is None:
            return
        shaft_end_x, shaft_end_y, tip_x, tip_y, left, right = geom
        if dash is not None:
            cls._draw_dashed_line(draw, x1, y1, shaft_end_x, shaft_end_y, fill, width, dash)
        else:
            draw.line([(x1, y1), (shaft_end_x, shaft_end_y)], fill=fill, width=max(1, width))
        draw.polygon([(tip_x, tip_y), left, right], fill=fill)

    def _diagram_export_geometry(self):
        """
        Shared layout for PNG/SVG export at current zoom/pan.
        Returns (width, height, faces, arrows) where faces/arrows are draw primitives.
        Omits UI chrome (status, + indicator, selection, hover, hints).
        """
        self.root.update_idletasks()
        w = max(int(self.canvas.winfo_width()), 1)
        h = max(int(self.canvas.winfo_height()), 1)
        z = self.zoom
        ox = self.offset_x
        oy = self.offset_y

        face_ys: dict = {fx: [] for fx in self.all_faces}
        for arrow in self.project.arrows:
            face_ys.setdefault(arrow.start_x, []).append(arrow.start_y)
            face_ys.setdefault(arrow.end_x, []).append(arrow.end_y)

        faces: list = []
        for fx, ys in face_ys.items():
            sx = fx * z + ox
            line_w = max(1, int(2 * z))
            if not ys:
                y1, y2 = 200 * z + oy, 500 * z + oy
            else:
                y1 = (min(ys) - 30) * z + oy
                y2 = (max(ys) + 30) * z + oy
            faces.append(
                {
                    "x1": sx,
                    "y1": y1,
                    "x2": sx,
                    "y2": y2,
                    "width": line_w,
                    "color": "#94a3b8",
                }
            )

        arrows: list = []
        for arrow in self.project.arrows:
            if arrow.is_gap:
                color = "#f97316"
                width = max(3, int(5 * z))
                dash: Optional[Tuple[int, int]] = (8, 4)
            else:
                color = "#00FF88" if arrow.direction > 0 else "#FF5555"
                width = max(2, int(4 * z))
                dash = None

            x1 = arrow.start_x * z + ox
            y1 = arrow.start_y * z + oy
            x2 = arrow.end_x * z + ox
            y2 = arrow.end_y * z + oy
            geom_len = math.hypot(x2 - x1, y2 - y1)
            zero_length = bool(arrow.is_gap and geom_len < 1.0)
            label = "CL = 0" if zero_length else (arrow.name if arrow.is_gap else f"L{arrow.id}")
            font_size = max(9, int(12 * z))
            mid_x = (x1 + x2) / 2
            mid_y = (y1 + y2) / 2
            if arrow.is_gap:
                # Right of shaft so face lines do not cover "CL"
                label_x = (max(x1, x2) if not zero_length else mid_x) + 14 * z
                label_y = mid_y
                label_anchor = "lm"  # left-middle (PIL / SVG start)
            else:
                label_x = mid_x
                label_y = mid_y - 16 * z
                label_anchor = "mm"
            arrows.append(
                {
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "width": width,
                    "color": color,
                    "dash": dash,
                    "label": label,
                    "label_x": label_x,
                    "label_y": label_y,
                    "label_anchor": label_anchor,
                    "font_size": font_size,
                    "zero_length": zero_length,
                }
            )

        return w, h, faces, arrows
    def _render_loop_diagram_rgba(self):
        """
        Render faces + dimension arrows at the current zoom/pan into a transparent
        RGBA image (canvas-sized). Omits UI chrome: zoom controls, + indicator,
        loop-status badge, hints, selection highlight, hover tooltips.
        """
        from PIL import Image, ImageDraw

        w, h, faces, arrows = self._diagram_export_geometry()
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        for face in faces:
            draw.line(
                [(face["x1"], face["y1"]), (face["x2"], face["y2"])],
                fill=self._hex_rgba(face["color"]),
                width=face["width"],
            )

        for ar in arrows:
            color = self._hex_rgba(ar["color"])
            if ar.get("zero_length"):
                # Closed chain: mean/drawn residual is zero — marker instead of a shaft
                cx, cy = ar["x1"], ar["y1"]
                r = max(8.0, float(ar["width"]) * 2.0)
                draw.ellipse(
                    [(cx - r, cy - r), (cx + r, cy + r)],
                    outline=color,
                    width=max(1, ar["width"]),
                )
                draw.line([(cx - r * 0.55, cy), (cx + r * 0.55, cy)], fill=color, width=max(1, ar["width"] - 1))
                draw.line([(cx, cy - r * 0.55), (cx, cy + r * 0.55)], fill=color, width=max(1, ar["width"] - 1))
            else:
                self._draw_arrowed_line(
                    draw,
                    ar["x1"],
                    ar["y1"],
                    ar["x2"],
                    ar["y2"],
                    color,
                    ar["width"],
                    dash=ar["dash"],
                )
            font = self._pil_font(ar["font_size"])
            # Deep blue: readable on white technical drawings, distinct from black geometry
            draw.text(
                (ar["label_x"], ar["label_y"]),
                ar["label"],
                font=font,
                fill=self._hex_rgba("#1d4ed8"),
                anchor=ar.get("label_anchor") or "mm",
            )

        return img

    def _render_loop_diagram_svg(self) -> str:
        """
        Build an SVG string of the loop diagram at current zoom/pan.
        Transparent background; no UI chrome. Labels in deep blue for overlays.
        """
        import html

        w, h, faces, arrows = self._diagram_export_geometry()
        parts: list[str] = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            (
                f'<svg xmlns="http://www.w3.org/2000/svg" '
                f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            ),
            "  <!-- EasyStackup loop diagram (transparent background) -->",
            '  <g stroke-linecap="round" stroke-linejoin="round">',
        ]

        for face in faces:
            parts.append(
                f'    <line x1="{face["x1"]:.2f}" y1="{face["y1"]:.2f}" '
                f'x2="{face["x2"]:.2f}" y2="{face["y2"]:.2f}" '
                f'stroke="{face["color"]}" stroke-width="{face["width"]}" fill="none"/>'
            )

        for ar in arrows:
            color = ar["color"]
            width = ar["width"]
            if ar.get("zero_length"):
                cx, cy = ar["x1"], ar["y1"]
                r = max(8.0, float(width) * 2.0)
                parts.append(
                    f'    <circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" '
                    f'stroke="{color}" stroke-width="{width}" fill="none"/>'
                )
                parts.append(
                    f'    <line x1="{cx - r * 0.55:.2f}" y1="{cy:.2f}" '
                    f'x2="{cx + r * 0.55:.2f}" y2="{cy:.2f}" '
                    f'stroke="{color}" stroke-width="{max(1, width - 1)}" fill="none"/>'
                )
                parts.append(
                    f'    <line x1="{cx:.2f}" y1="{cy - r * 0.55:.2f}" '
                    f'x2="{cx:.2f}" y2="{cy + r * 0.55:.2f}" '
                    f'stroke="{color}" stroke-width="{max(1, width - 1)}" fill="none"/>'
                )
            else:
                geom = self._arrow_head_geometry(ar["x1"], ar["y1"], ar["x2"], ar["y2"], width)
                if geom is not None:
                    sex, sey, tip_x, tip_y, left, right = geom
                    dash_attr = ""
                    if ar["dash"] is not None:
                        d0, d1 = ar["dash"]
                        dash_attr = f' stroke-dasharray="{d0} {d1}"'
                    parts.append(
                        f'    <line x1="{ar["x1"]:.2f}" y1="{ar["y1"]:.2f}" '
                        f'x2="{sex:.2f}" y2="{sey:.2f}" '
                        f'stroke="{color}" stroke-width="{width}" fill="none"{dash_attr}/>'
                    )
                    parts.append(
                        f'    <polygon points="{tip_x:.2f},{tip_y:.2f} '
                        f'{left[0]:.2f},{left[1]:.2f} {right[0]:.2f},{right[1]:.2f}" '
                        f'fill="{color}" stroke="none"/>'
                    )

            label = html.escape(ar["label"])
            # mm → middle; lm → start (label sits to the right of CL)
            svg_anchor = "start" if ar.get("label_anchor") == "lm" else "middle"
            parts.append(
                f'    <text x="{ar["label_x"]:.2f}" y="{ar["label_y"]:.2f}" '
                f'fill="#1d4ed8" font-family="Arial, Helvetica, sans-serif" '
                f'font-size="{ar["font_size"]}" font-weight="bold" '
                f'text-anchor="{svg_anchor}" dominant-baseline="middle">{label}</text>'
            )

        parts.append("  </g>")
        parts.append("</svg>")
        return "\n".join(parts) + "\n"

    def _export_loop_diagram_png(self, path: str | Path) -> Path:
        """Write a transparent PNG of the current loop diagram view."""
        path = Path(path)
        if path.suffix.lower() != ".png":
            path = path.with_suffix(".png")
        path.parent.mkdir(parents=True, exist_ok=True)
        img = self._render_loop_diagram_rgba()
        img.save(path, format="PNG")
        return path

    def _export_loop_diagram_svg(self, path: str | Path) -> Path:
        """Write a transparent SVG of the current loop diagram view."""
        path = Path(path)
        if path.suffix.lower() != ".svg":
            path = path.with_suffix(".svg")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._render_loop_diagram_svg(), encoding="utf-8")
        return path

    def _ask_diagram_export_path(
        self,
        *,
        title: str,
        extension: str,
        filetypes: list,
    ) -> Optional[str]:
        """Shared save dialog for loop-diagram PNG/SVG export. None if cancelled."""
        if not self.project.arrows:
            messagebox.showwarning(
                "Nothing to export",
                "Add at least one dimension before exporting the loop diagram.",
                parent=self.root,
            )
            return None

        if self.file_path:
            initial_dir = str(Path(self.file_path).parent)
            stem = Path(self.file_path).stem or "stackup"
        else:
            initial_dir = str(Path.home() / "Documents")
            stem = (self.project.title or "stackup").strip() or "stackup"

        ext = extension if extension.startswith(".") else f".{extension}"
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title=title,
            defaultextension=ext,
            initialdir=initial_dir,
            initialfile=f"{stem}_diagram{ext}",
            filetypes=filetypes,
        )
        return path or None

    def _menu_export_png(self):
        """
        Export the loop diagram at the current zoom/pan as a transparent PNG
        (faces + arrows + labels only — no canvas UI chrome or solid background).
        """
        path = self._ask_diagram_export_path(
            title="Export loop diagram as PNG",
            extension=".png",
            filetypes=[
                ("PNG image", "*.png"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        try:
            out_path = self._export_loop_diagram_png(path)
        except Exception as exc:
            messagebox.showerror(
                "Export failed",
                f"Could not export PNG:\n{exc}",
                parent=self.root,
            )
            return

        messagebox.showinfo(
            "Export complete",
            f"Loop diagram saved to:\n{out_path}",
            parent=self.root,
        )

    def _menu_export_svg(self):
        """
        Export the loop diagram at the current zoom/pan as a transparent SVG
        (vector faces + arrows + labels — same content rules as PNG export).
        """
        path = self._ask_diagram_export_path(
            title="Export loop diagram as SVG",
            extension=".svg",
            filetypes=[
                ("SVG image", "*.svg"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        try:
            out_path = self._export_loop_diagram_svg(path)
        except Exception as exc:
            messagebox.showerror(
                "Export failed",
                f"Could not export SVG:\n{exc}",
                parent=self.root,
            )
            return

        messagebox.showinfo(
            "Export complete",
            f"Loop diagram saved to:\n{out_path}",
            parent=self.root,
        )

    def create_ui(self):
        # === Native Windows-style menu bar (top of window chrome) ===
        self._create_menubar()

        # === Toolbar ===
        toolbar = ctk.CTkFrame(self.root)
        toolbar.pack(fill="x", padx=10, pady=(10, 5))

        ctk.CTkButton(toolbar, text="🗑 Clear All", width=120, height=40, fg_color="#D22",
                      command=self.clear_all).pack(side="left", padx=5)
        self.calc_btn = ctk.CTkButton(
            toolbar, text="Calculate", width=140, height=40,
            fg_color="green", hover_color="#15803d",
            command=self.calculate,
        )
        self.calc_btn.pack(side="left", padx=5)
        self.calc_btn.configure(state="disabled")  # needs a gap / closed loop

        ctk.CTkButton(toolbar, text="Close Loop / Add Clearance", width=200, height=40,
                      fg_color="#7c3aed", hover_color="#6d28d9",
                      command=self.add_gap).pack(side="left", padx=5)


        # === Main Area ===
        main_frame = ctk.CTkFrame(self.root)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Canvas
        self.canvas_frame = ctk.CTkFrame(main_frame, fg_color="#1e1e1e")
        self.canvas_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))

        self.canvas = tk.Canvas(self.canvas_frame, bg="#1e1e1e", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=5, pady=5)

        # Floating zoom controls (bottom-right of canvas)

        self.zoom_frame = ctk.CTkFrame(self.canvas_frame, fg_color="#2b2b2b", corner_radius=8)
        self.zoom_frame.place(relx=1.0, rely=1.0, anchor="se", x=-15, y=-15)

        ctk.CTkButton(self.zoom_frame, text="＋", width=42, height=36,
                      command=self.zoom_in).pack(side="left", padx=(6, 3), pady=6)
        ctk.CTkButton(self.zoom_frame, text="－", width=42, height=36,
                      command=self.zoom_out).pack(side="left", padx=3, pady=6)
        ctk.CTkButton(self.zoom_frame, text="1:1", width=50, height=36,
                      command=self.reset_zoom).pack(side="left", padx=(3, 6), pady=6)
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<B1-Motion>", self.during_draw)
        self.canvas.bind("<ButtonRelease-1>", self.end_draw)
        self.canvas.bind("<Motion>", self.on_canvas_motion)
        self.canvas.bind("<Leave>", self._on_canvas_leave)
        # Keep fixed overlays pinned when the canvas is resized; also run pending fit-on-open
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        self.draw_positive_indicator()

        # Right Sidebar — wide enough for full column headers without overlap
        right_frame = ctk.CTkFrame(main_frame, width=690)
        right_frame.pack(side="right", fill="y")
        right_frame.pack_propagate(False)

        self.dimensions_label = ctk.CTkLabel(
            right_frame,
            text=self._dimensions_heading(),
            font=ctk.CTkFont(size=20, weight="bold"),
        )
        self.dimensions_label.pack(anchor="w", padx=15, pady=(15, 5))

        # Table + vertical scrollbar only (shorter so Results has more room)
        tree_wrap = ctk.CTkFrame(right_frame, fg_color="transparent")
        tree_wrap.pack(fill="x", expand=False, padx=10, pady=5)

        columns = ("id", "name", "nominal", "mean", "tolerance", "equal_bilateral")
        self.tree = ttk.Treeview(
            tree_wrap,
            columns=columns,
            show="headings",
            height=8,
        )
        self.tree.heading("id", text="ID")
        self.tree.heading("name", text="Name")
        self.tree.heading("nominal", text="Nominal Dim")
        self.tree.heading("mean", text="Mean Dim")
        self.tree.heading("tolerance", text="Tolerance")
        self.tree.heading("equal_bilateral", text="Equal-bilateral Tolerance")

        # Columns stretch across the sidebar; no horizontal scrollbar
        self.tree.column("id", width=48, minwidth=40, anchor="center", stretch=False)
        self.tree.column("name", width=120, minwidth=70, anchor="w", stretch=True)
        self.tree.column("nominal", width=90, minwidth=70, anchor="e", stretch=True)
        self.tree.column("mean", width=90, minwidth=70, anchor="e", stretch=True)
        self.tree.column("tolerance", width=90, minwidth=100, anchor="center", stretch=False)
        self.tree.column("equal_bilateral", width=150, minwidth=110, anchor="center", stretch=True)

        y_scroll = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=y_scroll.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        tree_wrap.grid_columnconfigure(0, weight=1)

        # Tag for italic "(undefined)"
        self.tree.tag_configure("undefined", font=("", 10, "italic"))

        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree.bind("<Double-1>", lambda e: self.edit_selected())

        ctk.CTkLabel(right_frame, text="Results", font=ctk.CTkFont(size=20, weight="bold")).pack(
            anchor="w", padx=15, pady=(12, 5))
        self.result_frame = ctk.CTkFrame(right_frame)
        self.result_frame.pack(fill="both", expand=True, padx=15, pady=(5, 15))

        # Geometry + first paint happen in _sync_geometry_from_project() after create_ui()

        # Zoom function
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)  # Windows
        self.canvas.bind("<Button-4>", self.zoom_in)  # Linux
        self.canvas.bind("<Button-5>", self.zoom_out)  # Linux

        # Drag function
        self.canvas.bind("<Button-2>", self.start_pan)          # Middle button press
        self.canvas.bind("<B2-Motion>", self.during_pan)        # Middle button drag
        self.canvas.bind("<ButtonRelease-2>", self.end_pan)     # Middle button release

        self.root.bind("<Delete>", self._on_delete_key)
        self.root.bind("<BackSpace>", self._on_delete_key)
        self.root.bind_all("<Control-s>", self._on_ctrl_s)
        self.root.bind_all("<Control-S>", self._on_ctrl_s)
        self.canvas.bind("<Double-1>", self.on_canvas_double_click)

    def _sync_geometry_from_project(self):
        """Rebuild faces / active face / gap flag for a new or loaded project."""
        self.has_gap = any(a.is_gap for a in self.project.arrows)
        self.selected_id = None
        if not self.project.arrows:
            self.reset_faces()
        else:
            self._rebuild_faces()
            if self.has_gap:
                self.current_face_x = None
            else:
                self._restore_active_face()
        self.update_ui()
        if self.has_gap and isinstance(self.project.calculation, dict):
            self._render_calculation(self.project.calculation)
        # Loaded files: wait until the canvas has a real size, then fit the loop.
        if self.file_path and self.project.arrows:
            self._fit_pending = True
            self.root.after_idle(self._try_fit_loop_in_view)
            return
        self.redraw_canvas()

    def on_tree_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        self.selected_id = int(sel[0])  # iid is the real arrow.id
        self.redraw_canvas()

    def start_pan(self, event):
        self.is_panning = True
        self.pan_start_x = event.x
        self.pan_start_y = event.y
        self.canvas.config(cursor="fleur")

    def during_pan(self, event):
        if not self.is_panning:
            return
        dx = event.x - self.pan_start_x
        dy = event.y - self.pan_start_y
        self.offset_x += dx
        self.offset_y += dy
        self.pan_start_x = event.x
        self.pan_start_y = event.y
        self.redraw_canvas()

    def end_pan(self, event):
        self.is_panning = False
        self.canvas.config(cursor="")

    def _on_mousewheel(self, event):
        if event.delta > 0:
            self.zoom_in(event)
        else:
            self.zoom_out(event)

    def draw_positive_indicator(self):
        """Fixed screen-space + direction cue (bottom-left); ignores zoom/pan."""
        self.canvas.delete("pos_indicator")
        # Use canvas size so it stays in the corner after resize
        h = max(self.canvas.winfo_height(), 100)
        y = h - 40
        self.canvas.create_line(
            16, y, 85, y,
            arrow=tk.LAST, fill="#FAF5F5", width=3,
            tags="pos_indicator",
        )
        self.canvas.create_text(
            45, y - 18,
            text="+",
            fill="#FAF5F5",
            font=("Arial", 18, "bold"),
            tags="pos_indicator",
        )

    def reset_faces(self):
        """Single starting face at the project origin – also the current active face."""
        origin = self.original_start_x
        self.all_faces = [origin]
        self.current_face_x = origin

    def start_draw(self, event):
        if self.has_gap:
            return

        if self.current_face_x is None:
            return

        # Convert current face to screen space for snapping
        screen_face_x = self.current_face_x * self.zoom + self.offset_x
        if abs(event.x - screen_face_x) > self.SNAP_TOLERANCE:
            return

        # Store in model space
        self.start_x = self.current_face_x
        self.start_y = (event.y - self.offset_y) / self.zoom
        self.is_drawing = True
        self.temp_line = None

    def during_draw(self, event):
        if not self.is_drawing:
            return

        if self.temp_line:
            self.canvas.delete(self.temp_line)

        # Preview entirely in screen coordinates
        sx = self.start_x * self.zoom + self.offset_x
        sy = self.start_y * self.zoom + self.offset_y
        ex = event.x
        ey = sy  # forced horizontal

        self.temp_line = self.canvas.create_line(
            sx, sy, ex, ey,
            fill="#888888", width=3, arrow=tk.LAST, dash=(4, 2)
        )

    def end_draw(self, event):
        if not self.is_drawing or self.has_gap:
            return

        self.is_drawing = False

        if self.temp_line:
            self.canvas.delete(self.temp_line)
            self.temp_line = None

        # Direction from drag
        dx_screen = event.x - (self.start_x * self.zoom + self.offset_x)
        if abs(dx_screen) < 30:
            return

        direction = 1 if dx_screen > 0 else -1

        # Pre-fill dialog with drawn length (model units), nearest whole number
        drawn_length = abs(dx_screen) / self.zoom if self.zoom else abs(dx_screen)
        prefill_nominal = int(round(drawn_length))
        if prefill_nominal < 1:
            prefill_nominal = 1  # dialog requires nominal > 0

        # Temporary preview arrow
        color = "#00FF88" if direction > 0 else "#FF5555"
        sx = self.start_x * self.zoom + self.offset_x
        sy = self.start_y * self.zoom + self.offset_y
        ex = event.x
        ey = sy
        temp_id = self.canvas.create_line(
            sx, sy, ex, ey,
            arrow=tk.LAST, fill=color, width=4, tags="temp_arrow"
        )

        dialog = DimensionDialog(
            self.root,
            direction,
            initial_nominal=float(prefill_nominal),
            display_unit=self.project.display_unit,
        )
        self.root.wait_window(dialog)
        self.canvas.delete(temp_id)

        if dialog.result is None:
            return

        r = dialog.result
        name = r["name"]
        nominal = r["nominal"]

        # Force length = nominal (draw-to-scale)
        end_x_model = self.start_x + direction * nominal
        end_y_model = self.start_y

        # Add the dimension
        self.project.add_arrow(
            nominal=nominal,
            tolerance=r["tolerance"],
            direction=direction,
            name=name,
            start_x=self.start_x,
            start_y=self.start_y,
            end_x=end_x_model,
            end_y=end_y_model,
            tolerance_type=r["tolerance_type"],
            upper_dev=r["upper_dev"],
            lower_dev=r["lower_dev"],
            iso_feature=r["iso_feature"],
            iso_designation=r["iso_designation"],
        )

        # Update the chain
        if end_x_model not in self.all_faces:
            self.all_faces.append(end_x_model)
        self.current_face_x = end_x_model

        self._invalidate_analysis()
        self._mark_dirty()
        self.redraw_canvas()
        self.update_ui()

    def on_canvas_click(self, event):
        """Decide whether we are selecting an existing arrow or starting a new draw."""
        if self.has_gap:
            # Only selection is allowed once the gap exists
            self.try_select_arrow(event)
            return

        # First try to select an existing arrow
        if self.try_select_arrow(event):
            return

        # No arrow was hit → normal drawing start
        self.start_draw(event)

    def on_canvas_double_click(self, event):
        # First try to select the arrow under the mouse
        if self.try_select_arrow(event):
            self.edit_selected()

    def _hit_test_arrow(self, event):
        """Return id of the nearest arrow under the cursor, or None."""
        z = self.zoom
        ox = self.offset_x
        oy = self.offset_y
        mx = (event.x - ox) / z
        my = (event.y - oy) / z
        hit_dist = 12 / z  # roughly constant screen-pixel tolerance

        best_id = None
        best_dist = hit_dist

        for a in self.project.arrows:
            dx = a.end_x - a.start_x
            dy = a.end_y - a.start_y
            length2 = dx * dx + dy * dy
            if length2 == 0:
                # Zero-length CL (closed chain): hit-test as a point
                dist = ((mx - a.start_x) ** 2 + (my - a.start_y) ** 2) ** 0.5
            else:
                t = max(0.0, min(1.0, ((mx - a.start_x) * dx + (my - a.start_y) * dy) / length2))
                proj_x = a.start_x + t * dx
                proj_y = a.start_y + t * dy
                dist = ((mx - proj_x) ** 2 + (my - proj_y) ** 2) ** 0.5
            if dist < best_dist:
                best_dist = dist
                best_id = a.id

        return best_id

    def on_canvas_motion(self, event):
        best_id = self._hit_test_arrow(event)
        if best_id != self.hover_id:
            self.hover_id = best_id
            self._update_hover_label(event)

    def _clear_hover_label(self):
        """Remove hover tooltip and reset hover state."""
        if self.hover_text_id is not None:
            self.canvas.delete(self.hover_text_id)
            self.hover_text_id = None
        self.hover_id = None

    def _on_canvas_leave(self, event):
        # Cursor left the canvas — don't leave a stuck tooltip
        self._clear_hover_label()

    def _update_hover_label(self, event):
        # Remove previous hover label
        if self.hover_text_id is not None:
            self.canvas.delete(self.hover_text_id)
            self.hover_text_id = None

        if self.hover_id is None:
            return

        arrow = next((a for a in self.project.arrows if a.id == self.hover_id), None)
        if arrow is None:
            return

        unit = self.project.display_unit
        nom = format_length(arrow.nominal, unit)
        if arrow.is_gap:
            text = f"{arrow.name}\n{nom}  {arrow.format_tolerance(unit)}"
        else:
            custom = arrow.name if arrow.name and not arrow.name.startswith("L") else ""
            tol_txt = arrow.format_tolerance(unit)
            if custom:
                text = f"L{arrow.id}  ({custom})\n{nom}  {tol_txt}"
            else:
                text = f"L{arrow.id}\n{nom}  {tol_txt}"

        # Place the label slightly above the mouse
        self.hover_text_id = self.canvas.create_text(
            event.x, event.y - 25,
            text=text,
            fill="white",
            font=("Arial", 11, "bold"),
            anchor="s",
            tags="hover"
        )

    def try_select_arrow(self, event) -> bool:
        """Return True if an arrow was selected."""
        best_id = self._hit_test_arrow(event)

        if best_id is not None:
            self.selected_id = best_id
            self.redraw_canvas()
            self.update_ui()  # also highlights the row in the tree
            return True

        # Clicked empty space → deselect
        self.selected_id = None
        self.redraw_canvas()
        self.update_ui()
        return False

    def edit_selected(self):
        if self.selected_id is None:
            return

        arrow = next((a for a in self.project.arrows if a.id == self.selected_id), None)
        if arrow is None or arrow.is_gap:
            return  # gap arrows are not editable for now

        # Open the same dialog, pre-filled (values stored as mm; dialog converts)
        dialog = DimensionDialog(
            self.root,
            arrow.direction,
            initial_name=arrow.name,
            initial_nominal=arrow.nominal,
            initial_tol=arrow.tolerance,
            initial_tol_type=arrow.tolerance_type,
            initial_upper=arrow.upper_dev,
            initial_lower=arrow.lower_dev,
            initial_iso_feature=arrow.iso_feature or "hole",
            initial_iso_designation=arrow.iso_designation or "H7",
            is_edit=True,
            display_unit=self.project.display_unit,
        )
        self.root.wait_window(dialog)

        if dialog.result is None:
            return

        r = dialog.result
        name = r["name"]
        new_nominal = r["nominal"]

        # Calculate how much the length changed
        old_length = arrow.nominal * arrow.direction
        new_length = new_nominal * arrow.direction
        delta = new_length - old_length
        length_changed = abs(delta) > 1e-12

        # Length change invalidates a closed loop — remove gap before shifting
        if length_changed and self.has_gap:
            self._drop_gap()

        # Update the arrow itself
        arrow.name = name
        arrow.nominal = new_nominal
        arrow.tolerance = r["tolerance"]
        arrow.tolerance_type = r["tolerance_type"]
        arrow.upper_dev = r["upper_dev"]
        arrow.lower_dev = r["lower_dev"]
        arrow.iso_feature = r["iso_feature"]
        arrow.iso_designation = r["iso_designation"]
        arrow.end_x = arrow.start_x + new_length

        # Shift every subsequent arrow by the same delta
        idx = next(i for i, a in enumerate(self.project.arrows) if a.id == arrow.id)
        for a in self.project.arrows[idx + 1:]:
            a.start_x += delta
            a.end_x += delta

        self._rebuild_faces()
        if not self.has_gap:
            self._restore_active_face()

        # Closed loop + length unchanged (tolerance / type / name only):
        # keep the gap, refresh its label, and auto-recalculate results.
        if self.has_gap and not length_changed:
            self._sync_gap_arrow()

        self._invalidate_analysis()
        self._mark_dirty()
        self.redraw_canvas()
        self.update_ui()

        if self.has_gap and not length_changed:
            self.calculate()

    def _non_gap_arrows(self):
        return [a for a in self.project.arrows if not a.is_gap]

    def _rebuild_faces(self):
        """Rebuild vertical face X positions from non-gap arrows."""
        self.all_faces = [self.original_start_x]
        for a in self._non_gap_arrows():
            if a.start_x not in self.all_faces:
                self.all_faces.append(a.start_x)
            if a.end_x not in self.all_faces:
                self.all_faces.append(a.end_x)

    def _restore_active_face(self):
        """Set current_face_x after the chain is reopened (no closed clearance)."""
        non_gap = self._non_gap_arrows()
        if non_gap:
            self.current_face_x = non_gap[-1].end_x
        elif not self.project.arrows:
            self.reset_faces()
        else:
            self.current_face_x = None

    def _sync_gap_arrow(self):
        """Update clearance-closing arrow magnitude from current stack."""
        if not self.has_gap:
            return
        results = self.calculator.calculate(self.project)
        stack_value = results["nominal"]
        for a in self.project.arrows:
            if a.is_gap:
                a.nominal = abs(stack_value)
                a.name = "CL"

    def _drop_gap(self):
        """Remove clearance-closing arrow and reopen the chain for drawing."""
        for gap in [a for a in self.project.arrows if a.is_gap]:
            self.project.remove_arrow(gap.id)
        self.has_gap = False
        self._restore_active_face()

    def delete_selected(self):
        if self.selected_id is None:
            return

        was_gap = any(a.id == self.selected_id and a.is_gap for a in self.project.arrows)

        # Closed loop is invalid if any dimension in the chain is removed
        if self.has_gap and not was_gap:
            self._drop_gap()

        self.project.remove_arrow(self.selected_id)
        self.selected_id = None

        # After gap removal (or deleting the gap itself), reopen the chain for drawing
        if was_gap or not self.has_gap:
            self.has_gap = False
            self._restore_active_face()

        self._invalidate_analysis()
        self._mark_dirty()
        self._rebuild_faces()
        self.redraw_canvas()
        self.update_ui()

    def add_gap(self):
        if self.has_gap or not self.project.arrows:
            return

        # Closing face: prefer current_face_x; fall back if state is inconsistent
        start_x = self.current_face_x
        if start_x is None:
            non_gap = self._non_gap_arrows()
            start_x = non_gap[-1].end_x if non_gap else self.original_start_x
            self.current_face_x = start_x

        # Residual stack value (used for closing-arrow length only)
        results = self.calculator.calculate(self.project)
        stack_value = results["nominal"]

        # Place the clearance arrow from current face back to original start
        # Choose a Y a bit below the lowest existing arrow
        all_ys = []
        for a in self.project.arrows:
            all_ys.extend([a.start_y, a.end_y])
        gap_y = (max(all_ys) + 80) if all_ys else 400

        end_x = self.original_start_x
        if end_x > start_x:
            direction = 1
        elif end_x < start_x:
            direction = -1
        else:
            # Zero geometric residual — keep a stable default
            direction = 1

        self.project.add_arrow(
            nominal=abs(stack_value),
            tolerance=0.0,
            direction=direction,
            name="CL",
            start_x=start_x,
            start_y=gap_y,
            end_x=end_x,
            end_y=gap_y,
            is_gap=True
        )

        self.has_gap = True
        self.current_face_x = None
        self._invalidate_analysis()
        self._mark_dirty()
        self.redraw_canvas()
        self.update_ui()

        # Zero mean clearance is valid (line-to-line) but easy to miss — inform once.
        if results.get("warnings"):
            messagebox.showinfo(
                "Zero mean clearance",
                "\n".join(results["warnings"])
                + "\n\nThe loop is closed. Run Calculate to review WC/RSS ranges.",
                parent=self.root,
            )

    def _draw_loop_status(self):
        """Top-right canvas badge: valid (green) / invalid (red) once any arrow exists."""
        self.canvas.delete("loop_status")
        if not self.project.arrows:
            return

        if self.has_gap:
            text = "loop diagram valid"
            color = "#22c55e"
        else:
            text = "loop diagram invalid"
            color = "#ef4444"

        # Screen-space (not zoomed) so it stays readable in the corner
        w = max(self.canvas.winfo_width(), 200)
        self.canvas.create_text(
            w - 18,
            18,
            text=text,
            fill=color,
            font=("Arial", 8, "bold"),
            anchor="ne",
            tags="loop_status",
        )

    def _draw_fixed_overlays(self):
        """Screen-space UI that must not move with zoom/pan."""
        self.draw_positive_indicator()
        self._draw_loop_status()

    def redraw_canvas(self):
        self.canvas.delete("arrow")
        self.canvas.delete("connection")
        self.canvas.delete("hint")
        self.canvas.delete("loop_status")
        self.canvas.delete("pos_indicator")

        z = self.zoom
        ox = self.offset_x
        oy = self.offset_y

        # --- Collect Y values per face ---
        face_ys = {fx: [] for fx in self.all_faces}

        for arrow in self.project.arrows:
            face_ys.setdefault(arrow.start_x, []).append(arrow.start_y)
            face_ys.setdefault(arrow.end_x, []).append(arrow.end_y)

            if arrow.start_x not in self.all_faces:
                self.all_faces.append(arrow.start_x)
            if arrow.end_x not in self.all_faces:
                self.all_faces.append(arrow.end_x)

        # --- Vertical faces ---
        for fx, ys in face_ys.items():
            sx = fx * z + ox
            if not ys:
                self.canvas.create_line(
                    sx, 200 * z + oy, sx, 500 * z + oy,
                    fill="#94a3b8", width=max(1, int(2 * z)), tags="connection"
                )
                continue

            min_y = (min(ys) - 30) * z + oy
            max_y = (max(ys) + 30) * z + oy
            self.canvas.create_line(
                sx, min_y, sx, max_y,
                fill="#94a3b8", width=max(1, int(2 * z)), tags="connection"
            )

        # --- Hint text under the starting face (only when no arrows yet) ---
        if not self.project.arrows:
            sx = self.original_start_x * z + ox
            # Place it a little below the bottom of the empty face (500 * z)
            self.canvas.create_text(
                sx, 530 * z + oy,
                text="Draw first dimension arrow",
                fill="#94a3b8",
                font=("Arial", max(11, int(13 * z))),
                tags="hint"
            )


        # --- Arrows + short name labels ---
        for arrow in self.project.arrows:
            is_selected = (arrow.id == self.selected_id)

            if arrow.is_gap:
                color = "#f97316"
                width = max(3, int(5 * z))
                dash = (8, 4)
            else:
                color = "#00FF88" if arrow.direction > 0 else "#FF5555"
                width = max(2, int(4 * z))
                dash = None

            if is_selected:
                width = max(width + 3, int(7 * z))
                color = "#ffffff"

            x1 = arrow.start_x * z + ox
            y1 = arrow.start_y * z + oy
            x2 = arrow.end_x * z + ox
            y2 = arrow.end_y * z + oy
            geom_len = math.hypot(x2 - x1, y2 - y1)

            # Zero-length CL (chain closes on itself): draw a marker, not a line
            if arrow.is_gap and geom_len < 1.0:
                r = max(8.0, 10.0 * z)
                self.canvas.create_oval(
                    x1 - r, y1 - r, x1 + r, y1 + r,
                    outline=color, width=width, tags="arrow",
                )
                self.canvas.create_line(
                    x1 - r * 0.55, y1, x1 + r * 0.55, y1,
                    fill=color, width=max(1, width - 1), tags="arrow",
                )
                self.canvas.create_line(
                    x1, y1 - r * 0.55, x1, y1 + r * 0.55,
                    fill=color, width=max(1, width - 1), tags="arrow",
                )
                mid_x, mid_y = x1, y1
                label = "CL = 0"
            else:
                if dash is not None:
                    self.canvas.create_line(
                        x1, y1, x2, y2,
                        arrow=tk.LAST, fill=color,
                        width=width, dash=dash, tags="arrow"
                    )
                else:
                    self.canvas.create_line(
                        x1, y1, x2, y2,
                        arrow=tk.LAST, fill=color,
                        width=width, tags="arrow"
                    )
                mid_x = (x1 + x2) / 2
                mid_y = (y1 + y2) / 2
                label = arrow.name if arrow.is_gap else f"L{arrow.id}"

            font_size = max(9, int(12 * z))
            # CL sits to the right of the shaft (clear of vertical faces);
            # normal dimension IDs stay above the arrow mid-point.
            if arrow.is_gap:
                label_x = (max(x1, x2) if geom_len >= 1.0 else mid_x) + 14 * z
                label_y = mid_y
                label_anchor = "w"
            else:
                label_x = mid_x
                label_y = mid_y - 16 * z
                label_anchor = "center"
            self.canvas.create_text(
                label_x, label_y,
                text=label,
                fill="white",
                font=("Arial", font_size, "bold"),
                anchor=label_anchor,
                tags="arrow"
            )

        self._draw_fixed_overlays()

    def zoom_in(self, event=None):
        self._apply_zoom(1.15)

    def zoom_out(self, event=None):
        self._apply_zoom(1 / 1.15)

    def reset_zoom(self):
        """Reset the view: fit the loop if there is one, otherwise 1:1 at the origin."""
        if self.project.arrows:
            self._fit_loop_in_view()
            return
        self.zoom = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.redraw_canvas()

    def _apply_zoom(self, factor):
        if factor > 1 and self.zoom >= _MAX_ZOOM:
            return
        if factor < 1 and self.zoom <= _MIN_ZOOM:
            return
        new_zoom = max(_MIN_ZOOM, min(_MAX_ZOOM, self.zoom * factor))

        # Always zoom toward the current center of the canvas
        cx = self.canvas.winfo_width() / 2
        cy = self.canvas.winfo_height() / 2

        # Keep the model point that is currently under the center fixed
        if self.zoom != 0:
            model_x = (cx - self.offset_x) / self.zoom
            model_y = (cy - self.offset_y) / self.zoom
            self.offset_x = cx - model_x * new_zoom
            self.offset_y = cy - model_y * new_zoom

        self.zoom = new_zoom
        self.redraw_canvas()

    def _on_canvas_configure(self, _event=None):
        if self._try_fit_loop_in_view():
            return
        self._draw_fixed_overlays()

    def _loop_model_bounds(self) -> Optional[Tuple[float, float, float, float]]:
        """Axis-aligned bounds of faces + arrows in model space (including labels)."""
        xs: list[float] = list(self.all_faces)
        ys: list[float] = []
        for a in self.project.arrows:
            xs.extend((a.start_x, a.end_x))
            ys.extend((a.start_y, a.end_y))
            if a.is_gap:
                xs.append(max(a.start_x, a.end_x) + 36.0)
            else:
                ys.append(min(a.start_y, a.end_y) - 18.0)
        if not xs:
            return None
        if not ys:
            ys.extend((200.0, 500.0))
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys) - 30.0, max(ys) + 30.0
        if xmax <= xmin:
            xmax = xmin + 1.0
        if ymax <= ymin:
            ymax = ymin + 1.0
        return xmin, ymin, xmax, ymax

    def _try_fit_loop_in_view(self, _event=None) -> bool:
        """Run a pending fit once the canvas has a real size. Returns True if it ran."""
        if not self._fit_pending:
            return False
        try:
            if not self.root.winfo_exists() or not self.canvas.winfo_exists():
                self._fit_pending = False
                return False
        except Exception:
            self._fit_pending = False
            return False
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w < 50 or h < 50:
            self.root.after(50, self._try_fit_loop_in_view)
            return False
        self._fit_pending = False
        self._fit_loop_in_view()
        return True

    def _fit_loop_in_view(self) -> None:
        """Center the loop on its centroid and zoom so the whole diagram is visible."""
        bounds = self._loop_model_bounds()
        if bounds is None:
            self.redraw_canvas()
            return
        xmin, ymin, xmax, ymax = bounds
        w = max(self.canvas.winfo_width(), 50)
        h = max(self.canvas.winfo_height(), 50)
        usable_w = max(40.0, w * (1.0 - 2.0 * _FIT_MARGIN))
        usable_h = max(40.0, h * (1.0 - 2.0 * _FIT_MARGIN))
        span_x = max(xmax - xmin, 1.0)
        span_y = max(ymax - ymin, 1.0)
        zoom = min(usable_w / span_x, usable_h / span_y)
        self.zoom = max(_MIN_ZOOM, min(_MAX_ZOOM, zoom))
        cx = 0.5 * (xmin + xmax)
        cy = 0.5 * (ymin + ymax)
        self.offset_x = w / 2.0 - cx * self.zoom
        self.offset_y = h / 2.0 - cy * self.zoom
        self.redraw_canvas()

    def clear_all(self):
        had_content = bool(self.project.arrows)
        self.project.arrows.clear()
        self.project.next_id = 1
        self.has_gap = False
        # Fresh empty diagram uses the shared default origin
        self.original_start_x = DEFAULT_ORIGIN_X
        self.reset_faces()
        self.zoom = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self._invalidate_analysis()
        if had_content:
            self._mark_dirty()
        self.redraw_canvas()
        self.update_ui()

    def _on_delete_key(self, _event=None):
        """Delete the selected dimension, but never steal Backspace from a text field."""
        try:
            widget = self.root.focus_get()
            if widget is not None:
                cls = str(widget.winfo_class())
                if cls in ("Entry", "Text", "TEntry") or "entry" in cls.lower():
                    return
        except Exception:
            pass
        self.delete_selected()

    def _on_ctrl_s(self, _event=None):
        # bind_all fires even when a modal has grab. Silent-save is fine;
        # opening Save As under a grabbed dialog is not.
        try:
            grab = self.root.grab_current()
        except Exception:
            grab = None
        if grab is not None and not self.file_path:
            return "break"
        self.save_project_file()
        return "break"

    def save_project_file(self) -> bool:
        """Save to the current path, or open Save As if none yet. Returns True on success."""
        if self.file_path:
            return self._write_project(self.file_path)
        return self.save_project_as()

    def save_project_as(self) -> bool:
        """Save As dialog; default filename is project1 (or current file name). Returns True on success."""
        if self.file_path:
            initial_file = Path(self.file_path).name
        else:
            initial_file = f"project1{DEFAULT_EXTENSION}"

        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save EasyStackup project",
            defaultextension=DEFAULT_EXTENSION,
            initialfile=initial_file,
            filetypes=[
                ("EasyStackup project", f"*{DEFAULT_EXTENSION}"),
                ("JSON files", "*.json"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return False

        path = str(path)
        # Ensure .eysp if user typed a bare name with no extension
        if not Path(path).suffix:
            path = path + DEFAULT_EXTENSION

        return self._write_project(path)

    def _write_project(self, path: str) -> bool:
        try:
            # Keep project title in sync with filename
            title = Path(path).stem or "project1"
            self.project.title = title

            save_project(path, self.project, original_start_x=self.original_start_x)
            self.file_path = path
            self._clear_dirty()
            self._update_window_title()
            return True
        except Exception as exc:
            messagebox.showerror(
                "Save failed",
                f"Could not save project:\n{path}\n\n{exc}",
                parent=self.root,
            )
            return False

    # Distinct bar colors for contribution rows (cycles if many dims)
    _CONTRIB_COLORS = (
        "#3b82f6", "#22c55e", "#f59e0b", "#ef4444",
        "#a855f7", "#06b6d4", "#f97316", "#84cc16",
    )

    def _invalidate_analysis(self):
        """Drop stored WC/RSS and Monte Carlo snapshots (loop no longer matches)."""
        self.project.calculation = None
        self.project.monte_carlo = None
        self._clear_results()

    def calculate(self):
        # Only valid for a closed loop (gap placed)
        if not self.has_gap:
            return

        results = self.calculator.calculate(self.project)
        if self.project.calculation != results:
            self.project.calculation = results
            self._mark_dirty()
        self._render_calculation(results)

    def _render_calculation(self, results: dict):
        if not hasattr(self, "result_frame"):
            return
        for widget in self.result_frame.winfo_children():
            widget.destroy()

        unit = self.project.display_unit
        ul = unit_label(unit)

        # Clearance = stack residual as computed (no sign flip).
        # + = gap / open clearance, − = interference (user interprets the sign).
        data = [
            (f"Clearance ({ul})", format_length(results["nominal"], unit, signed=True, decimals=4)),
            (f"WC Min ({ul})", format_length(results["wc_min"], unit, signed=True, decimals=4)),
            (f"WC Max ({ul})", format_length(results["wc_max"], unit, signed=True, decimals=4)),
            (f"RSS Min ({ul})", format_length(results["rss_min"], unit, signed=True, decimals=4)),
            (f"RSS Max ({ul})", format_length(results["rss_max"], unit, signed=True, decimals=4)),
        ]

        for label, value in data:
            row = ctk.CTkFrame(self.result_frame)
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=label, width=200, anchor="w").pack(side="left", padx=10)
            ctk.CTkLabel(row, text=value, font=ctk.CTkFont(weight="bold")).pack(side="right", padx=10)

        for warning in results.get("warnings") or []:
            note = ctk.CTkFrame(self.result_frame, fg_color="#422006")
            note.pack(fill="x", padx=8, pady=(10, 2))
            ctk.CTkLabel(
                note,
                text="Note",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#fbbf24",
                anchor="w",
            ).pack(fill="x", padx=10, pady=(8, 0))
            ctk.CTkLabel(
                note,
                text=warning,
                text_color="#fde68a",
                font=ctk.CTkFont(size=12),
                anchor="w",
                justify="left",
                wraplength=320,
            ).pack(fill="x", padx=10, pady=(2, 10))

        self._render_contributions(results.get("contributions", []))

    def _render_contributions(self, contributions):
        """
        Tolerance-band contribution as sorted horizontal bars.
        Better than a pie for exact % and many dimensions; no extra library.
        """
        if not contributions:
            return

        ctk.CTkLabel(
            self.result_frame,
            text="Tolerance contribution",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(anchor="w", padx=10, pady=(16, 4))

        ctk.CTkLabel(
            self.result_frame,
            text="Share of total tolerance band width (drives WC spread)",
            text_color="#94a3b8",
            font=ctk.CTkFont(size=11),
        ).pack(anchor="w", padx=10, pady=(0, 8))

        # Largest contributors first
        ordered = sorted(contributions, key=lambda c: c["percent"], reverse=True)

        for i, c in enumerate(ordered):
            color = self._CONTRIB_COLORS[i % len(self._CONTRIB_COLORS)]
            name = (c.get("name") or "").strip()
            title = f"L{c['id']}" + (f"  ({name})" if name else "")
            pct = float(c["percent"])

            block = ctk.CTkFrame(self.result_frame, fg_color="transparent")
            block.pack(fill="x", padx=10, pady=4)

            header = ctk.CTkFrame(block, fg_color="transparent")
            header.pack(fill="x")
            ctk.CTkLabel(header, text=title, anchor="w").pack(side="left")
            ctk.CTkLabel(
                header,
                text=f"{pct:.1f}%",
                font=ctk.CTkFont(weight="bold"),
                text_color=color,
            ).pack(side="right")

            bar = ctk.CTkProgressBar(
                block,
                height=12,
                progress_color=color,
                fg_color="#334155",
            )
            bar.pack(fill="x", pady=(2, 0))
            bar.set(max(0.0, min(1.0, pct / 100.0)))

    def _clear_results(self):
        if hasattr(self, "result_frame"):
            for widget in self.result_frame.winfo_children():
                widget.destroy()

    def _refresh_calc_button(self):
        """Calculate is only available when a closed loop (clearance) exists."""
        if not hasattr(self, "calc_btn"):
            return
        if self.has_gap:
            self.calc_btn.configure(state="normal")
        else:
            self.calc_btn.configure(state="disabled")
            self.project.calculation = None
            self.project.monte_carlo = None
            self._clear_results()

    def _dimensions_heading(self) -> str:
        """Sidebar title with active display unit, e.g. Dimensions [mm]."""
        unit = normalize_unit(self.project.display_unit)
        # User-facing label: "inch" for imperial (not abbreviated "in")
        name = "inch" if unit == UNIT_IN else "mm"
        return f"Dimensions [{name}]"

    def _refresh_dimensions_heading(self):
        if hasattr(self, "dimensions_label") and self.dimensions_label is not None:
            self.dimensions_label.configure(text=self._dimensions_heading())

    def update_ui(self):
        self._refresh_calc_button()
        self._refresh_dimensions_heading()

        for item in self.tree.get_children():
            self.tree.delete(item)

        unit = self.project.display_unit

        for a in self.project.arrows:
            if a.is_gap:
                continue

            id_text = f"L{a.id}"

            if a.name and a.name.strip():
                name_text = a.name
                tags = ()
            else:
                name_text = "(undefined)"
                tags = ("undefined",)

            item = self.tree.insert(
                "", "end",
                iid=str(a.id),
                values=(
                    id_text,
                    name_text,
                    format_length(a.nominal, unit),
                    format_length(a.mean_size, unit),
                    a.format_tolerance(unit),
                    a.format_equal_bilateral(unit),
                ),
                tags=tags
            )

            if a.id == self.selected_id:
                self.tree.selection_set(item)
                self.tree.see(item)


