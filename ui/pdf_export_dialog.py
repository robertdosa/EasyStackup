"""Dialog for Export → PDF report options."""

from __future__ import annotations

import re
from pathlib import Path

import customtkinter as ctk
from tkinter import filedialog, messagebox


# Initial revision is "-", then user typically moves to A, B, C… (still free choice)
_REVISION_RE = re.compile(r"^(-|[A-Z]+)$")


class PdfExportDialog(ctk.CTkToplevel):
    """
    Collect export destination and report metadata.
    result = None on cancel, else:
      { "folder": str, "project_name": str, "revision": str, "creator": str }

    project_name may be empty; the caller then uses the project file name
    for the PDF "Project" field.
    """

    def __init__(
        self,
        parent,
        *,
        initial_folder: str | None = None,
        initial_project_name: str = "",
        initial_revision: str = "-",
        initial_creator: str = "",
    ):
        super().__init__(parent)
        self.title("Export PDF report")
        # Tall enough for form + action buttons (CTk widgets are larger on Windows/DPI)
        self.geometry("560x480")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result = None

        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() // 2) - 280
        y = parent.winfo_rooty() + (parent.winfo_height() // 2) - 240
        self.geometry(f"+{x}+{y}")

        default_folder = initial_folder or str(Path.home() / "Documents")

        # Pack buttons first (side=bottom) so they always reserve space and are not
        # clipped when form fields + padding exceed the window height.
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(side="bottom", pady=(8, 20))

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
            text="Export to PDF",
            width=140,
            height=36,
            fg_color="#0ea5e9",
            hover_color="#0284c7",
            command=self._export,
        ).pack(side="left", padx=8)

        ctk.CTkLabel(
            self,
            text="Export PDF report",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(anchor="w", padx=28, pady=(20, 14))

        # --- Folder ---
        ctk.CTkLabel(self, text="Folder:").pack(anchor="w", padx=28)
        folder_row = ctk.CTkFrame(self, fg_color="transparent")
        folder_row.pack(fill="x", padx=28, pady=(4, 12))

        self.folder_var = ctk.StringVar(value=default_folder)
        self.folder_entry = ctk.CTkEntry(folder_row, textvariable=self.folder_var)
        self.folder_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(
            folder_row,
            text="Browse…",
            width=100,
            command=self._browse_folder,
        ).pack(side="right")

        # --- Project name (optional; empty → use file name in PDF) ---
        ctk.CTkLabel(self, text="Project name (optional):").pack(anchor="w", padx=28)
        self.project_name_entry = ctk.CTkEntry(
            self,
            placeholder_text="Leave empty to use the file name",
        )
        self.project_name_entry.pack(fill="x", padx=28, pady=(4, 12))
        if initial_project_name:
            self.project_name_entry.insert(0, initial_project_name)

        # --- Revision ---
        ctk.CTkLabel(
            self,
            text='Revision (initial "-", then A, B, C… — capital letters only):',
        ).pack(anchor="w", padx=28)
        self.revision_entry = ctk.CTkEntry(self, placeholder_text="-")
        self.revision_entry.pack(fill="x", padx=28, pady=(4, 12))
        self.revision_entry.insert(0, initial_revision if initial_revision else "-")
        # Force uppercase as user types (keeps "-" as-is)
        self.revision_entry.bind("<KeyRelease>", self._on_revision_key)

        # --- Creator ---
        ctk.CTkLabel(self, text="Creator (optional):").pack(anchor="w", padx=28)
        self.creator_entry = ctk.CTkEntry(self, placeholder_text="Name or initials")
        self.creator_entry.pack(fill="x", padx=28, pady=(4, 8))
        if initial_creator:
            self.creator_entry.insert(0, initial_creator)

        self.bind("<Return>", lambda e: self._export())
        self.bind("<Escape>", lambda e: self._cancel())
        self.project_name_entry.focus()

    def _on_revision_key(self, _event=None):
        """Keep letter revisions uppercase; leave "-" alone."""
        text = self.revision_entry.get()
        if text == "-":
            return
        upper = text.upper()
        if text != upper:
            pos = self.revision_entry.index("insert")
            self.revision_entry.delete(0, "end")
            self.revision_entry.insert(0, upper)
            try:
                self.revision_entry.icursor(pos)
            except Exception:
                pass

    def _browse_folder(self):
        current = self.folder_var.get().strip()
        initial = current if current and Path(current).is_dir() else str(Path.home())
        path = filedialog.askdirectory(
            parent=self,
            title="Select export folder",
            initialdir=initial,
        )
        if path:
            self.folder_var.set(path)

    def _export(self):
        folder = self.folder_var.get().strip()
        project_name = self.project_name_entry.get().strip()
        raw = self.revision_entry.get().strip()
        # Preserve solitary dash; uppercase letter revisions
        revision = raw if raw == "-" else raw.upper()
        creator = self.creator_entry.get().strip()

        if not folder:
            messagebox.showwarning("Missing folder", "Please select an export folder.", parent=self)
            return
        folder_path = Path(folder)
        if not folder_path.is_dir():
            messagebox.showwarning(
                "Invalid folder",
                f"Folder does not exist:\n{folder}",
                parent=self,
            )
            return

        if not revision:
            messagebox.showwarning(
                "Missing revision",
                'Please enter a revision ("-" for initial, or A, B, C, …).',
                parent=self,
            )
            return
        if not _REVISION_RE.fullmatch(revision):
            messagebox.showwarning(
                "Invalid revision",
                'Revision must be "-" (initial) or capital letters A–Z\n'
                "(e.g. A, B, C or AA).",
                parent=self,
            )
            return

        self.result = {
            "folder": str(folder_path.resolve()),
            "project_name": project_name,  # may be "" → caller uses file name
            "revision": revision,
            "creator": creator,
        }
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()
