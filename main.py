"""EasyStackup entry point — single CTk root for menu and workspace."""

from pathlib import Path

import customtkinter as ctk
from tkinter import messagebox

from core.project_io import load_project, DEFAULT_ORIGIN_X
from ui.main_menu import MainMenuView
from ui.app import EasyStackupApp

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Project root (folder that contains main.py) — works when run as a script
_APP_DIR = Path(__file__).resolve().parent
_ASSETS_DIR = _APP_DIR / "assets"
_ICON_ICO = _ASSETS_DIR / "app_icon.ico"
_ICON_PNG = _ASSETS_DIR / "app_icon.png"


def _apply_window_icon(root: ctk.CTk) -> None:
    """
    Set the title-bar / taskbar icon.

    On Windows + CustomTkinter, a multi-size .ico via iconbitmap is preferred: it
    also marks the window so CTk does not replace it with its default icon after
    ~200 ms. iconphoto is a cross-platform supplement when a PNG is available.
    """
    try:
        if _ICON_ICO.is_file():
            # Marks CTk's _iconbitmap_method_called so the default icon is not applied
            root.iconbitmap(default=str(_ICON_ICO))
        elif _ICON_PNG.is_file():
            from PIL import Image, ImageTk

            img = Image.open(_ICON_PNG).convert("RGBA")
            # Center-crop 16:9 → square so the title bar is not stretched
            w, h = img.size
            side = min(w, h)
            left, top = (w - side) // 2, (h - side) // 2
            square = img.crop((left, top, left + side, top + side)).resize(
                (32, 32), Image.Resampling.LANCZOS
            )
            # Strong ref required — PhotoImage is GC'd otherwise and the icon vanishes
            root._app_icon_photo = ImageTk.PhotoImage(square)
            root.iconphoto(True, root._app_icon_photo)
    except Exception:
        # Missing asset or Tk/platform quirk — keep running with the default icon
        pass


class EasyStackupShell:
    """
    Owns the only CTk() instance.
    Switches between main menu and calculation workspace without creating new roots
    (avoids broken buttons / missing widgets after close).
    """

    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("EasyStackup")
        _apply_window_icon(self.root)
        self.workspace: EasyStackupApp | None = None
        self.mode = "menu"  # "menu" | "app"

        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)
        self.show_menu()
        self.root.mainloop()

    def _clear_root(self):
        if self.workspace is not None:
            self.workspace.teardown()
            self.workspace = None
        for child in self.root.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass

    def show_menu(self):
        self._clear_root()
        self.mode = "menu"
        try:
            self.root.state("normal")
        except Exception:
            pass
        MainMenuView(
            self.root,
            on_new=self.open_new_project,
            on_load=self.open_load_project,
            on_quit=self.quit_app,
        )

    def open_new_project(self):
        self._clear_root()
        self.mode = "app"
        self.workspace = EasyStackupApp(
            self.root,
            on_new=self.open_new_project,
            on_open=self.open_load_project,
            on_exit=self.quit_app,
        )

    def open_load_project(self, path: str):
        try:
            project, meta = load_project(path)
        except Exception as exc:
            messagebox.showerror(
                "Load failed",
                f"Could not load project:\n{path}\n\n{exc}",
                parent=self.root,
            )
            return

        self._clear_root()
        self.mode = "app"
        self.workspace = EasyStackupApp(
            self.root,
            project=project,
            original_start_x=meta.get("original_start_x", DEFAULT_ORIGIN_X),
            file_path=path,
            on_new=self.open_new_project,
            on_open=self.open_load_project,
            on_exit=self.quit_app,
        )

    def quit_app(self):
        self._clear_root()
        try:
            self.root.destroy()
        except Exception:
            pass

    def _on_window_close(self):
        # X on workspace → prompt for unsaved changes, then back to menu
        # X on menu → quit
        if self.mode == "app":
            if self.workspace is not None and not self.workspace.confirm_leave():
                return
            self.show_menu()
        else:
            self.quit_app()


def main():
    EasyStackupShell()


if __name__ == "__main__":
    main()
