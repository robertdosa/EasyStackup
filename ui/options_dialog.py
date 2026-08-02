"""Project Options dialog (display units, etc.)."""

from __future__ import annotations

import customtkinter as ctk

from core.units import UNIT_IN, UNIT_MM, normalize_unit, unit_label


class OptionsDialog(ctk.CTkToplevel):
    """
    Simple options window.
    Currently: display unit (Metric mm / US Imperial inch).
    Stored project values remain millimetres; this only affects UI display/entry.
    """

    def __init__(self, parent, display_unit: str = UNIT_MM):
        super().__init__(parent)
        self.title("Options")
        self.geometry("420x280")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result = None  # None = cancelled; dict on OK

        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() // 2) - 210
        y = parent.winfo_rooty() + (parent.winfo_height() // 2) - 140
        self.geometry(f"+{x}+{y}")

        unit = normalize_unit(display_unit)

        ctk.CTkLabel(
            self,
            text="Display units",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(anchor="w", padx=28, pady=(22, 6))

        ctk.CTkLabel(
            self,
            text=(
                "Project data is stored in millimetres.\n"
                "This setting only changes how values are shown and entered."
            ),
            text_color="#94a3b8",
            font=ctk.CTkFont(size=12),
            justify="left",
        ).pack(anchor="w", padx=28, pady=(0, 14))

        self.unit_var = ctk.StringVar(value=unit)

        radio_frame = ctk.CTkFrame(self, fg_color="transparent")
        radio_frame.pack(fill="x", padx=28, pady=(0, 10))

        ctk.CTkRadioButton(
            radio_frame,
            text="Metric (mm)",
            variable=self.unit_var,
            value=UNIT_MM,
        ).pack(anchor="w", pady=4)

        ctk.CTkRadioButton(
            radio_frame,
            text="US Imperial (in)",
            variable=self.unit_var,
            value=UNIT_IN,
        ).pack(anchor="w", pady=4)

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(side="bottom", pady=16)

        ctk.CTkButton(
            btn_frame,
            text="Cancel",
            width=110,
            height=36,
            fg_color="#555555",
            hover_color="#666666",
            command=self._cancel,
        ).pack(side="left", padx=8)

        ctk.CTkButton(
            btn_frame,
            text="OK",
            width=110,
            height=36,
            fg_color="#0ea5e9",
            hover_color="#0284c7",
            command=self._ok,
        ).pack(side="left", padx=8)

        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self._cancel())

    def _ok(self):
        unit = normalize_unit(self.unit_var.get())
        self.result = {
            "display_unit": unit,
            "unit_label": unit_label(unit),
        }
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()
