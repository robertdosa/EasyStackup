"""
Display unit helpers.

Internal project values are always millimetres. Display unit only affects
how numbers are shown and entered in the UI (Options → Metric / Imperial).
"""

from __future__ import annotations

# 1 inch = 25.4 mm (exact)
MM_PER_INCH = 25.4

UNIT_MM = "mm"
UNIT_IN = "in"

VALID_UNITS = (UNIT_MM, UNIT_IN)


def normalize_unit(unit: str | None) -> str:
    if not unit:
        return UNIT_MM
    u = str(unit).strip().lower()
    if u in ("in", "inch", "inches", "imperial"):
        return UNIT_IN
    return UNIT_MM


def unit_label(unit: str | None) -> str:
    return "in" if normalize_unit(unit) == UNIT_IN else "mm"


def to_display(value_mm: float, unit: str | None) -> float:
    """Convert a stored mm value to the active display unit."""
    if normalize_unit(unit) == UNIT_IN:
        return float(value_mm) / MM_PER_INCH
    return float(value_mm)


def from_display(value_display: float, unit: str | None) -> float:
    """Convert a UI entry (display unit) back to stored mm."""
    if normalize_unit(unit) == UNIT_IN:
        return float(value_display) * MM_PER_INCH
    return float(value_display)


def length_decimals(unit: str | None) -> int:
    """Default decimal places for lengths in the active unit."""
    return 4 if normalize_unit(unit) == UNIT_IN else 3


def format_length(
    value_mm: float,
    unit: str | None = UNIT_MM,
    *,
    signed: bool = False,
    decimals: int | None = None,
    with_unit: bool = False,
) -> str:
    """Format a mm-stored length for display."""
    u = normalize_unit(unit)
    v = to_display(value_mm, u)
    d = length_decimals(u) if decimals is None else decimals
    text = f"{v:+.{d}f}" if signed else f"{v:.{d}f}"
    if with_unit:
        text = f"{text} {unit_label(u)}"
    return text
