"""Startup main menu view (drawn into an existing CTk root)."""

from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk
from tkinter import filedialog


class MainMenuView:
    """
    Packs the New / Load / Quit UI into the given root.
    Does not create its own CTk() — one root for the whole app avoids CTk multi-root bugs.
    """

    def __init__(
        self,
        root: ctk.CTk,
        on_new: Callable[[], None],
        on_load: Callable[[str], None],
        on_quit: Callable[[], None],
    ):
        self.root = root
        self.on_new = on_new
        self.on_load = on_load
        self.on_quit = on_quit

        self.root.title("EasyStackup")
        self.root.resizable(False, False)

        frame = ctk.CTkFrame(root, fg_color="transparent")
        frame.pack(expand=True, fill="both", padx=40, pady=40)

        ctk.CTkLabel(
            frame,
            text="EasyStackup",
            font=ctk.CTkFont(size=32, weight="bold"),
        ).pack(pady=(10, 6))

        ctk.CTkLabel(
            frame,
            text="Tolerance Stackup Designer",
            text_color="#94a3b8",
            font=ctk.CTkFont(size=14),
        ).pack(pady=(0, 36))

        btn_w, btn_h = 260, 48
        ctk.CTkButton(
            frame,
            text="New project",
            width=btn_w,
            height=btn_h,
            font=ctk.CTkFont(size=15),
            command=self.on_new,
        ).pack(pady=8)

        ctk.CTkButton(
            frame,
            text="Load project",
            width=btn_w,
            height=btn_h,
            font=ctk.CTkFont(size=15),
            fg_color="#334155",
            hover_color="#475569",
            command=self._pick_and_load,
        ).pack(pady=8)

        ctk.CTkButton(
            frame,
            text="Quit",
            width=btn_w,
            height=btn_h,
            font=ctk.CTkFont(size=15),
            fg_color="#555555",
            hover_color="#666666",
            command=self.on_quit,
        ).pack(pady=8)

        # Size + center after widgets exist (CTk scales WxH; x/y must use real pixel size)
        self._place_menu_window(480, 420)

    def _place_menu_window(self, width: int = 480, height: int = 420) -> None:
        try:
            self.root.state("normal")
        except Exception:
            pass
        self.root.geometry(f"{width}x{height}")
        self.root.update_idletasks()
        ww = max(self.root.winfo_width(), 1)
        wh = max(self.root.winfo_height(), 1)
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = max(0, (sw - ww) // 2)
        y = max(0, (sh - wh) // 2)
        self.root.geometry(f"+{x}+{y}")
        self.root.after_idle(lambda: self._recenter_menu(width, height))

    def _recenter_menu(self, width: int, height: int) -> None:
        try:
            self.root.update_idletasks()
            ww = max(self.root.winfo_width(), 1)
            wh = max(self.root.winfo_height(), 1)
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            x = max(0, (sw - ww) // 2)
            y = max(0, (sh - wh) // 2)
            self.root.geometry(f"{width}x{height}+{x}+{y}")
        except Exception:
            pass

    def _pick_and_load(self):
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Load EasyStackup project",
            filetypes=[
                ("EasyStackup project", "*.eysp"),
                ("JSON files", "*.json"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.on_load(path)


# Backwards-compatible name used in docs/imports
MainMenu = MainMenuView
