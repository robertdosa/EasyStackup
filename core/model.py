from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.units import UNIT_MM, format_length, normalize_unit


# Tolerance type identifiers (used later by the UI dialog)
TOL_SYMMETRIC = "symmetric"
TOL_BILATERAL = "bilateral"
TOL_ISO = "iso_fit"


@dataclass
class Arrow:
    id: int
    nominal: float
    tolerance: float = 0.0    # symmetric ± value (kept for compatibility)
    name: str = ""
    direction: int = 1        # 1 = right (positive), -1 = left (negative)
    start_x: float = 0.0
    start_y: float = 0.0
    end_x: float = 0.0
    end_y: float = 0.0
    is_gap: bool = False      # special closing gap / interference arrow

    # Multi-type tolerance: size = nominal + deviation
    tolerance_type: str = TOL_SYMMETRIC
    upper_dev: float = 0.0    # deviation to max size
    lower_dev: float = 0.0    # deviation to min size
    iso_feature: str = ""     # "hole" | "shaft"
    iso_designation: str = "" # e.g. "H7", "g6"

    def __post_init__(self):
        # Legacy path: only ±tolerance was set → fill upper/lower
        if (
            self.tolerance_type == TOL_SYMMETRIC
            and self.upper_dev == 0.0
            and self.lower_dev == 0.0
            and self.tolerance != 0.0
        ):
            t = abs(self.tolerance)
            self.upper_dev = t
            self.lower_dev = -t

    @property
    def half_range(self) -> float:
        """Half-width of the tolerance band (for RSS / equal-bilateral)."""
        return abs(self.upper_dev - self.lower_dev) / 2.0

    @property
    def mid_dev(self) -> float:
        """Midpoint of the tolerance band relative to nominal."""
        return (self.upper_dev + self.lower_dev) / 2.0

    @property
    def mean_size(self) -> float:
        """Mean dimension (= nominal when tolerance is symmetric)."""
        return self.nominal + self.mid_dev

    def format_tolerance(self, unit: str = UNIT_MM) -> str:
        """As-specified tolerance for tables / hover labels (display unit)."""
        if self.is_gap:
            return "—"
        u = normalize_unit(unit)
        if self.tolerance_type == TOL_SYMMETRIC:
            t = abs(self.tolerance) if self.tolerance else abs(self.upper_dev)
            return f"±{format_length(t, u)}"
        if self.tolerance_type == TOL_ISO and self.iso_designation:
            up = format_length(self.upper_dev, u, signed=True, decimals=4)
            lo = format_length(self.lower_dev, u, signed=True, decimals=4)
            return f"{self.iso_designation} ({up}/{lo})"
        up = format_length(self.upper_dev, u, signed=True)
        lo = format_length(self.lower_dev, u, signed=True)
        return f"{up}/{lo}"

    def format_equal_bilateral(self, unit: str = UNIT_MM) -> str:
        """Equivalent symmetric ± around the mean (display unit)."""
        if self.is_gap:
            return "—"
        return f"±{format_length(self.half_range, unit, decimals=4)}"



class Project:
    def __init__(self):
        self.arrows: List[Arrow] = []
        self.next_id = 1
        self.title = "New Stackup"
        # Display preference only; stored values are always millimetres
        self.display_unit: str = UNIT_MM
        # Last WC/RSS snapshot and last Monte Carlo run (JSON-safe dicts, mm)
        self.calculation: Optional[Dict[str, Any]] = None
        self.monte_carlo: Optional[Dict[str, Any]] = None
        # When True and a Monte Carlo snapshot exists, PDF export includes it.
        self.include_mc_in_pdf: bool = True

    def add_arrow(self, nominal: float, tolerance: float = 0.0, direction: int = 1,
                  name: str = "", start_x: float = 0, start_y: float = 0,
                  end_x: float = 0, end_y: float = 0, is_gap: bool = False,
                  tolerance_type: str = TOL_SYMMETRIC,
                  upper_dev: Optional[float] = None,
                  lower_dev: Optional[float] = None,
                  iso_feature: str = "",
                  iso_designation: str = "") -> Arrow:
        # Existing call sites that only pass tolerance= keep working as symmetric ±
        if upper_dev is None or lower_dev is None:
            if tolerance_type == TOL_SYMMETRIC:
                upper_dev = abs(tolerance)
                lower_dev = -abs(tolerance)
            else:
                upper_dev = 0.0 if upper_dev is None else upper_dev
                lower_dev = 0.0 if lower_dev is None else lower_dev

        arrow = Arrow(
            id=self.next_id,
            nominal=nominal,
            tolerance=tolerance,
            direction=direction,
            name=name,
            start_x=start_x,
            start_y=start_y,
            end_x=end_x,
            end_y=end_y,
            is_gap=is_gap,
            tolerance_type=tolerance_type,
            upper_dev=upper_dev,
            lower_dev=lower_dev,
            iso_feature=iso_feature,
            iso_designation=iso_designation,
        )
        self.arrows.append(arrow)
        self.next_id += 1
        return arrow

    def remove_arrow(self, arrow_id: int):
        idx = next((i for i, a in enumerate(self.arrows) if a.id == arrow_id), None)
        if idx is None:
            return

        deleted = self.arrows[idx]

        # Chain dimensions: close the X gap so later arrows stay continuous.
        # Gap/interference arrows are not part of the length chain — do not shift.
        if not deleted.is_gap:
            delta_x = deleted.end_x - deleted.start_x
            for a in self.arrows[idx + 1:]:
                a.start_x -= delta_x
                a.end_x -= delta_x

        self.arrows.pop(idx)

    def to_dict(self):
        return {
            "title": self.title,
            "next_id": self.next_id,
            "display_unit": normalize_unit(self.display_unit),
            "arrows": [vars(a) for a in self.arrows],
            "calculation": self.calculation,
            "monte_carlo": self.monte_carlo,
            "include_mc_in_pdf": bool(self.include_mc_in_pdf),
        }

    @classmethod
    def from_dict(cls, data: dict):
        proj = cls()
        proj.title = data.get("title", "New Stackup")
        proj.next_id = int(data.get("next_id", 1) or 1)
        proj.display_unit = normalize_unit(data.get("display_unit", UNIT_MM))
        known = set(Arrow.__dataclass_fields__.keys())
        for raw in data.get("arrows", []):
            a = dict(raw)
            # Older saves only had symmetric ±tolerance
            if "upper_dev" not in a or "lower_dev" not in a:
                t = abs(float(a.get("tolerance", 0)))
                a["upper_dev"] = t
                a["lower_dev"] = -t
            a.setdefault("tolerance_type", TOL_SYMMETRIC)
            a.setdefault("iso_feature", "")
            a.setdefault("iso_designation", "")
            # Drop obsolete keys (e.g. legacy "color") so old .eysp files still load
            filtered = {k: v for k, v in a.items() if k in known}
            proj.arrows.append(Arrow(**filtered))
        # Avoid duplicate IDs if the file's next_id is missing, stale, or below max id
        max_id = max((a.id for a in proj.arrows), default=0)
        proj.next_id = max(proj.next_id, max_id + 1, 1)
        calc = data.get("calculation")
        proj.calculation = calc if isinstance(calc, dict) else None
        mc = data.get("monte_carlo")
        proj.monte_carlo = mc if isinstance(mc, dict) else None
        if "include_mc_in_pdf" in data:
            proj.include_mc_in_pdf = bool(data.get("include_mc_in_pdf"))
        return proj
