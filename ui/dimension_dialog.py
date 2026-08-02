"""Add / edit dimension dialog (tolerance type UI)."""

import customtkinter as ctk
from tkinter import messagebox

from core.model import (
    TOL_SYMMETRIC,
    TOL_BILATERAL,
    TOL_ISO,
)
from core.iso286 import (
    deviations_for,
    list_hole_designations,
    list_shaft_designations,
)
from core.units import (
    UNIT_MM,
    format_length,
    from_display,
    length_decimals,
    normalize_unit,
    to_display,
    unit_label,
)

# Labels shown in the tolerance-type dropdown
TOL_TYPE_OPTIONS = {
    "Symmetric (±)": TOL_SYMMETRIC,
    "Bilateral": TOL_BILATERAL,
    "ISO fit": TOL_ISO,
}
TOL_TYPE_LABELS = {v: k for k, v in TOL_TYPE_OPTIONS.items()}


class DimensionDialog(ctk.CTkToplevel):
    def __init__(
        self,
        parent,
        direction: int,
        initial_name: str = "",
        initial_nominal: float = None,
        initial_tol: float = None,
        initial_tol_type: str = TOL_SYMMETRIC,
        initial_upper: float = None,
        initial_lower: float = None,
        initial_iso_feature: str = "hole",
        initial_iso_designation: str = "H7",
        is_edit: bool = False,
        display_unit: str = UNIT_MM,
    ):
        super().__init__(parent)
        # is_edit (not initial_nominal) decides Add vs Edit — drawing pre-fills nominal too
        self._editing = is_edit
        self.display_unit = normalize_unit(display_unit)
        self._unit = unit_label(self.display_unit)
        self._dec = length_decimals(self.display_unit)
        self.title("Edit Dimension" if is_edit else "Add Dimension")
        self.geometry("420x600")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result = None

        # Center the dialog
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() // 2) - 200
        y = parent.winfo_rooty() + (parent.winfo_height() // 2) - 280
        self.geometry(f"+{x}+{y}")

        dir_text = "Positive  (+  →)" if direction == 1 else "Negative  (−  ←)"
        color = "#22c55e" if direction == 1 else "#ef4444"

        ctk.CTkLabel(
            self,
            text=f"Direction:  {dir_text}",
            text_color=color,
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(pady=(16, 10))

        ctk.CTkLabel(
            self,
            text=f"Values in {self._unit}  (stored as mm)",
            text_color="#94a3b8",
            font=ctk.CTkFont(size=12),
        ).pack(pady=(0, 8))

        # Name
        ctk.CTkLabel(self, text="Name (optional):").pack(anchor="w", padx=30)
        self.name_entry = ctk.CTkEntry(self, placeholder_text="e.g. Shaft, Housing...")
        self.name_entry.pack(fill="x", padx=30, pady=(0, 8))
        if initial_name:
            self.name_entry.insert(0, initial_name)

        # Nominal (display unit)
        ctk.CTkLabel(self, text=f"Nominal value ({self._unit}):").pack(anchor="w", padx=30)
        self.nominal_entry = ctk.CTkEntry(self, placeholder_text=f"e.g. {25.0 if self.display_unit == UNIT_MM else 1.0}")
        self.nominal_entry.pack(fill="x", padx=30, pady=(0, 8))
        if initial_nominal is not None:
            # initial_* are always mm-stored
            self.nominal_entry.insert(0, f"{to_display(initial_nominal, self.display_unit):.{self._dec}f}")
        self.nominal_entry.focus()
        self.nominal_entry.bind("<KeyRelease>", lambda e: self._refresh_iso_preview())

        # Tolerance type
        ctk.CTkLabel(self, text="Tolerance type:").pack(anchor="w", padx=30)
        start_label = TOL_TYPE_LABELS.get(initial_tol_type, "Symmetric (±)")
        self.type_menu = ctk.CTkOptionMenu(
            self,
            values=list(TOL_TYPE_OPTIONS.keys()),
            command=self._on_type_changed,
        )
        self.type_menu.set(start_label)
        self.type_menu.pack(fill="x", padx=30, pady=(0, 10))

        # Buttons first (side=bottom) so they never get pushed off-screen
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(side="bottom", pady=12)

        ctk.CTkButton(
            btn_frame,
            text="Cancel",
            width=110,
            height=36,
            fg_color="#555555",
            hover_color="#666666",
            command=self.cancel,
        ).pack(side="left", padx=8)

        ok_text = "Save Changes" if self._editing else "Add Dimension"
        ctk.CTkButton(
            btn_frame,
            text=ok_text,
            width=140,
            height=36,
            fg_color="#22c55e",
            hover_color="#16a34a",
            command=self.ok,
        ).pack(side="left", padx=8)

        # Host for type-specific fields (children toggle with pack / pack_forget)
        self.fields_host = ctk.CTkFrame(self, fg_color="transparent")
        self.fields_host.pack(fill="both", expand=True, padx=30, pady=(0, 8))

        # --- Symmetric fields ---
        self.sym_frame = ctk.CTkFrame(self.fields_host, fg_color="transparent")
        ctk.CTkLabel(self.sym_frame, text=f"Tolerance (± {self._unit}):").pack(anchor="w")
        self.tol_entry = ctk.CTkEntry(self.sym_frame, placeholder_text="e.g. 0.10")
        self.tol_entry.pack(fill="x", pady=(0, 4))
        if initial_tol is not None:
            self.tol_entry.insert(0, f"{to_display(abs(initial_tol), self.display_unit):.{self._dec}f}")

        # --- Bilateral fields ---
        self.bil_frame = ctk.CTkFrame(self.fields_host, fg_color="transparent")
        ctk.CTkLabel(self.bil_frame, text=f"Upper limit (deviation, {self._unit}):").pack(anchor="w")
        self.upper_entry = ctk.CTkEntry(self.bil_frame, placeholder_text="e.g. 0.05 or -0.01")
        self.upper_entry.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(self.bil_frame, text=f"Lower limit (deviation, {self._unit}):").pack(anchor="w")
        self.lower_entry = ctk.CTkEntry(self.bil_frame, placeholder_text="e.g. -0.02 or 0.0")
        self.lower_entry.pack(fill="x", pady=(0, 4))
        if initial_upper is not None:
            self.upper_entry.insert(0, f"{to_display(initial_upper, self.display_unit):.{self._dec + 1}f}")
        if initial_lower is not None:
            self.lower_entry.insert(0, f"{to_display(initial_lower, self.display_unit):.{self._dec + 1}f}")
        ctk.CTkLabel(
            self.bil_frame,
            text="Lower must not exceed upper. Mean shifts if not ±symmetric.",
            text_color="#94a3b8",
            font=ctk.CTkFont(size=11),
        ).pack(anchor="w", pady=(2, 0))

        # --- ISO fit fields ---
        self.iso_frame = ctk.CTkFrame(self.fields_host, fg_color="transparent")
        ctk.CTkLabel(self.iso_frame, text="Feature:").pack(anchor="w")
        self.iso_feature_menu = ctk.CTkOptionMenu(
            self.iso_frame,
            values=["Hole", "Shaft (stem)"],
            command=self._on_iso_feature_changed,
        )
        feat = (initial_iso_feature or "hole").lower()
        self.iso_feature_menu.set("Shaft (stem)" if feat == "shaft" else "Hole")
        self.iso_feature_menu.pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(self.iso_frame, text="ISO designation:").pack(anchor="w")
        self._hole_list = list_hole_designations()
        self._shaft_list = list_shaft_designations()
        self.iso_desig_menu = ctk.CTkOptionMenu(
            self.iso_frame,
            values=self._hole_list,
            command=lambda _v: self._refresh_iso_preview(),
        )
        self.iso_desig_menu.pack(fill="x", pady=(0, 6))

        self.iso_preview = ctk.CTkLabel(
            self.iso_frame,
            text="",
            text_color="#94a3b8",
            font=ctk.CTkFont(size=12),
            justify="left",
        )
        self.iso_preview.pack(anchor="w", pady=(2, 0))

        # Apply feature list / designation after widgets exist
        self._on_iso_feature_changed(self.iso_feature_menu.get())
        if initial_iso_designation:
            values = list(self.iso_desig_menu.cget("values"))
            if initial_iso_designation in values:
                self.iso_desig_menu.set(initial_iso_designation)
        self._refresh_iso_preview()

        self.bind("<Return>", lambda e: self.ok())
        self.bind("<Escape>", lambda e: self.cancel())

        self._on_type_changed(start_label)

    def _on_type_changed(self, label: str):
        # Simple show/hide — no pack(in_=...), which breaks CustomTkinter layouts
        self.sym_frame.pack_forget()
        self.bil_frame.pack_forget()
        self.iso_frame.pack_forget()

        tol_type = TOL_TYPE_OPTIONS[label]
        if tol_type == TOL_SYMMETRIC:
            self.sym_frame.pack(fill="x")
        elif tol_type == TOL_BILATERAL:
            self.bil_frame.pack(fill="x")
        else:
            self.iso_frame.pack(fill="x")
            self._refresh_iso_preview()

    def _on_iso_feature_changed(self, label: str):
        if "Shaft" in label:
            values = self._shaft_list
            default = "g6" if "g6" in values else values[0]
        else:
            values = self._hole_list
            default = "H7" if "H7" in values else values[0]
        self.iso_desig_menu.configure(values=values)
        current = self.iso_desig_menu.get()
        if current not in values:
            self.iso_desig_menu.set(default)
        self._refresh_iso_preview()

    def _refresh_iso_preview(self):
        if not hasattr(self, "iso_preview"):
            return
        try:
            nom_str = self.nominal_entry.get().strip()
            if not nom_str:
                self.iso_preview.configure(text="Enter nominal to preview ISO limits.")
                return
            # ISO tables are millimetre-based; convert entry → mm for lookup
            nominal_mm = from_display(float(nom_str), self.display_unit)
            desig = self.iso_desig_menu.get()
            lower, upper = deviations_for(desig, nominal_mm)
            mean = (upper + lower) / 2.0
            half = abs(upper - lower) / 2.0
            limits = (
                f"{format_length(upper, self.display_unit, signed=True, decimals=4)} / "
                f"{format_length(lower, self.display_unit, signed=True, decimals=4)} "
                f"{self._unit}"
            )
            self.iso_preview.configure(
                text=(
                    f"Limits: {limits}\n"
                    f"→ mean shift {format_length(mean, self.display_unit, signed=True, decimals=4)}, "
                    f"equiv. ±{format_length(half, self.display_unit, decimals=4)}"
                )
            )
        except Exception as exc:
            self.iso_preview.configure(text=f"ISO lookup: {exc}")

    def ok(self):
        try:
            nominal_str = self.nominal_entry.get().strip()
            if not nominal_str:
                messagebox.showwarning("Missing values", "Please enter Nominal.", parent=self)
                return

            # Convert display entry → stored mm
            nominal = from_display(float(nominal_str), self.display_unit)
            if nominal <= 0:
                messagebox.showwarning("Invalid Nominal", "Nominal must be greater than 0.", parent=self)
                return

            name = self.name_entry.get().strip()
            tol_type = TOL_TYPE_OPTIONS[self.type_menu.get()]

            if tol_type == TOL_SYMMETRIC:
                tol_str = self.tol_entry.get().strip()
                if not tol_str:
                    messagebox.showwarning("Missing values", "Please enter Tolerance (±).", parent=self)
                    return
                tol = from_display(float(tol_str), self.display_unit)
                if tol < 0:
                    messagebox.showwarning("Invalid Tolerance", "Tolerance cannot be negative.", parent=self)
                    return
                self.result = {
                    "name": name,
                    "nominal": nominal,
                    "tolerance_type": TOL_SYMMETRIC,
                    "tolerance": abs(tol),
                    "upper_dev": abs(tol),
                    "lower_dev": -abs(tol),
                    "iso_feature": "",
                    "iso_designation": "",
                }

            elif tol_type == TOL_BILATERAL:
                up_str = self.upper_entry.get().strip()
                lo_str = self.lower_entry.get().strip()
                if not up_str or not lo_str:
                    messagebox.showwarning(
                        "Missing values",
                        "Please enter both Upper and Lower limits.",
                        parent=self,
                    )
                    return
                upper = from_display(float(up_str), self.display_unit)
                lower = from_display(float(lo_str), self.display_unit)
                if lower > upper:
                    messagebox.showwarning(
                        "Invalid limits",
                        "Lower limit cannot be greater than upper limit.",
                        parent=self,
                    )
                    return
                half = abs(upper - lower) / 2.0
                self.result = {
                    "name": name,
                    "nominal": nominal,
                    "tolerance_type": TOL_BILATERAL,
                    "tolerance": half,
                    "upper_dev": upper,
                    "lower_dev": lower,
                    "iso_feature": "",
                    "iso_designation": "",
                }

            else:  # ISO fit — deviations always from mm tables
                feature_label = self.iso_feature_menu.get()
                feature = "shaft" if "Shaft" in feature_label else "hole"
                designation = self.iso_desig_menu.get()
                lower, upper = deviations_for(designation, nominal)
                half = abs(upper - lower) / 2.0
                self.result = {
                    "name": name,
                    "nominal": nominal,
                    "tolerance_type": TOL_ISO,
                    "tolerance": half,
                    "upper_dev": upper,
                    "lower_dev": lower,
                    "iso_feature": feature,
                    "iso_designation": designation,
                }

            self.destroy()

        except ValueError:
            messagebox.showerror(
                "Invalid input",
                "Please enter valid numbers for the numeric fields.",
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("Error", str(exc), parent=self)

    def cancel(self):
        self.result = None
        self.destroy()
