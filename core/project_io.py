"""Save / load EasyStackup projects as JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Tuple

from core.model import Project

FILE_VERSION = 2
DEFAULT_EXTENSION = ".eysp"

# Model-space X of the datum face for a new / empty loop diagram.
# Canvas drawing, save/load, and face reset all share this default.
DEFAULT_ORIGIN_X = 520.0


def project_to_file_dict(
    project: Project,
    original_start_x: float = DEFAULT_ORIGIN_X,
) -> Dict[str, Any]:
    data = project.to_dict()
    data["version"] = FILE_VERSION
    data["original_start_x"] = float(original_start_x)
    return data


def save_project(
    path: str | Path,
    project: Project,
    original_start_x: float = DEFAULT_ORIGIN_X,
) -> None:
    path = Path(path)
    payload = project_to_file_dict(project, original_start_x=original_start_x)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_project(path: str | Path) -> Tuple[Project, Dict[str, Any]]:
    """
    Load a project file.
    Returns (Project, meta) where meta includes original_start_x and version.
    """
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Invalid project file: expected a JSON object.")

    project = Project.from_dict(raw)
    if project.monte_carlo is not None:
        try:
            from core.monte_carlo import MonteCarloResult

            project.monte_carlo = MonteCarloResult.from_dict(project.monte_carlo).to_dict()
        except Exception:
            project.monte_carlo = None
    if project.calculation is not None and "nominal" not in project.calculation:
        project.calculation = None
    meta = {
        "version": raw.get("version", 1),
        "original_start_x": float(raw.get("original_start_x", DEFAULT_ORIGIN_X)),
        "path": str(path),
    }
    return project, meta
