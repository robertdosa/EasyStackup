"""About EasyStackup dialog (Help → About)."""

from __future__ import annotations

import customtkinter as ctk

# Single place to bump the displayed app version
APP_NAME = "EasyStackup"
APP_VERSION = "0.2.0"


class AboutDialog(ctk.CTkToplevel):
    """
    Simple About window: product summary, version, open-source license note,
    and development credits (including AI assistance).
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.title(f"About {APP_NAME}")
        self.geometry("520x420")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() // 2) - 260
        y = parent.winfo_rooty() + (parent.winfo_height() // 2) - 210
        self.geometry(f"+{x}+{y}")

        ctk.CTkLabel(
            self,
            text=APP_NAME,
            font=ctk.CTkFont(size=22, weight="bold"),
        ).pack(anchor="w", padx=28, pady=(24, 4))

        ctk.CTkLabel(
            self,
            text=f"Version {APP_VERSION}",
            text_color="#94a3b8",
            font=ctk.CTkFont(size=13),
        ).pack(anchor="w", padx=28, pady=(0, 14))

        ctk.CTkLabel(
            self,
            text=(
                "A desktop tool for 1D mechanical tolerance stack-up analysis.\n"
                "Build closed dimension loops, evaluate worst-case, RSS, and\n"
                "Monte Carlo results, and export reports and loop diagrams."
            ),
            justify="left",
            font=ctk.CTkFont(size=13),
        ).pack(anchor="w", padx=28, pady=(0, 16))

        ctk.CTkLabel(
            self,
            text="License",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(anchor="w", padx=28, pady=(0, 4))

        ctk.CTkLabel(
            self,
            text=(
                "Released under the MIT License.\n"
                "You may use, modify, and distribute this software under the\n"
                "terms of that license. Full text is in the LICENSE file of the\n"
                "repository: github.com/robertdosa/EasyStackup"
            ),
            text_color="#94a3b8",
            justify="left",
            font=ctk.CTkFont(size=12),
        ).pack(anchor="w", padx=28, pady=(0, 16))

        ctk.CTkLabel(
            self,
            text="Development",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(anchor="w", padx=28, pady=(0, 4))

        ctk.CTkLabel(
            self,
            text=(
                "Developed with AI assistance. Design decisions, engineering\n"
                "logic, and final review remain the responsibility of the author."
            ),
            text_color="#94a3b8",
            justify="left",
            font=ctk.CTkFont(size=12),
        ).pack(anchor="w", padx=28, pady=(0, 20))

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(side="bottom", pady=(8, 20))

        ctk.CTkButton(
            btn_frame,
            text="Close",
            width=110,
            height=36,
            fg_color="#0ea5e9",
            hover_color="#0284c7",
            command=self.destroy,
        ).pack()

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self.destroy())
