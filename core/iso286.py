"""
ISO 286 limit deviations for common hole/shaft designations.

Values are based on ISO 286-1 / ISO 286-2 tables (sizes ≤ 500 mm).
Returned deviations are in millimetres relative to the nominal size:
    size_max = nominal + upper_dev
    size_min = nominal + lower_dev
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

# Nominal size range upper bounds (mm). Index 0 = "up to and including 3 mm".
SIZE_LIMITS: List[float] = [
    3, 6, 10, 18, 30, 50, 80, 120, 180, 250, 315, 400, 500
]

# Standard tolerance grades IT5–IT12 in micrometres, keyed by grade number.
# Each list has one value per SIZE_LIMITS entry.
IT_TABLE: Dict[int, List[int]] = {
    5:  [4, 5, 6, 8, 9, 11, 13, 15, 18, 20, 23, 25, 27],
    6:  [6, 8, 9, 11, 13, 16, 19, 22, 25, 29, 32, 36, 40],
    7:  [10, 12, 15, 18, 21, 25, 30, 35, 40, 46, 52, 57, 63],
    8:  [14, 18, 22, 27, 33, 39, 46, 54, 63, 72, 81, 89, 97],
    9:  [25, 30, 36, 43, 52, 62, 74, 87, 100, 115, 130, 140, 155],
    10: [40, 48, 58, 70, 84, 100, 120, 140, 160, 185, 210, 230, 250],
    11: [60, 75, 90, 110, 130, 160, 190, 220, 250, 290, 320, 360, 400],
    12: [100, 120, 150, 180, 210, 250, 300, 350, 400, 460, 520, 570, 630],
}

# Shaft fundamental deviation (µm). For letters a–h this is es (upper);
# for letters k–zc this is ei (lower). js is handled separately.
# Values per SIZE_LIMITS entry.
SHAFT_FUND: Dict[str, List[int]] = {
    "a":  [-270, -270, -280, -290, -300, -310, -320, -340, -360, -380, -410, -460, -520],
    "b":  [-140, -140, -150, -150, -160, -170, -180, -200, -210, -230, -240, -260, -280],
    "c":  [-60, -70, -80, -95, -110, -120, -130, -140, -150, -170, -180, -200, -210],
    "d":  [-20, -30, -40, -50, -65, -80, -100, -120, -145, -170, -190, -210, -230],
    "e":  [-14, -20, -25, -32, -40, -50, -60, -72, -85, -100, -110, -125, -135],
    "f":  [-6, -10, -13, -16, -20, -25, -30, -36, -43, -50, -56, -62, -68],
    "g":  [-2, -4, -5, -6, -7, -9, -10, -12, -14, -15, -17, -18, -20],
    "h":  [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    # k–u: lower deviation ei (µm)
    "k":  [0, 1, 1, 1, 2, 2, 2, 3, 3, 4, 4, 4, 5],
    "m":  [2, 4, 6, 7, 8, 9, 11, 13, 15, 17, 20, 21, 23],
    "n":  [4, 8, 10, 12, 15, 17, 20, 23, 27, 31, 34, 37, 40],
    "p":  [6, 12, 15, 18, 22, 26, 32, 37, 43, 50, 56, 62, 68],
    "r":  [10, 15, 19, 23, 28, 34, 41, 49, 58, 68, 77, 85, 95],
    "s":  [14, 19, 23, 28, 35, 43, 53, 66, 79, 93, 106, 119, 134],
    "t":  [None, None, None, None, 41, 48, 64, 80, 94, 112, 130, 144, 162],  # type: ignore
    "u":  [18, 23, 28, 33, 41, 48, 60, 75, 94, 117, 134, 154, 175],
}

# Hole fundamental deviation (µm). For A–H this is EI (lower);
# for K–ZC this is ES (upper). JS handled separately.
# Hole letters are inverses of shaft letters: hole_fund ≈ -shaft_fund for A–H / a–h.
HOLE_FUND: Dict[str, List[Optional[int]]] = {
    "A":  [270, 270, 280, 290, 300, 310, 320, 340, 360, 380, 410, 460, 520],
    "B":  [140, 140, 150, 150, 160, 170, 180, 200, 210, 230, 240, 260, 280],
    "C":  [60, 70, 80, 95, 110, 120, 130, 140, 150, 170, 180, 200, 210],
    "D":  [20, 30, 40, 50, 65, 80, 100, 120, 145, 170, 190, 210, 230],
    "E":  [14, 20, 25, 32, 40, 50, 60, 72, 85, 100, 110, 125, 135],
    "F":  [6, 10, 13, 16, 20, 25, 30, 36, 43, 50, 56, 62, 68],
    "G":  [2, 4, 5, 6, 7, 9, 10, 12, 14, 15, 17, 18, 20],
    "H":  [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    # K–U: upper deviation ES (µm) – simplified common values (ISO special deltas omitted for K–N ≤ IT8)
    "K":  [0, 0, -1, -1, -2, -2, -2, -3, -3, -4, -4, -4, -5],
    "M":  [-2, -4, -6, -7, -8, -9, -11, -13, -15, -17, -20, -21, -23],
    "N":  [-4, -8, -10, -12, -15, -17, -20, -23, -27, -31, -34, -37, -40],
    "P":  [-6, -12, -15, -18, -22, -26, -32, -37, -43, -50, -56, -62, -68],
    "R":  [-10, -15, -19, -23, -28, -34, -41, -49, -58, -68, -77, -85, -95],
    "S":  [-14, -19, -23, -28, -35, -43, -53, -66, -79, -93, -106, -119, -134],
    "T":  [None, None, None, None, -41, -48, -64, -80, -94, -112, -130, -144, -162],
    "U":  [-18, -23, -28, -33, -41, -48, -60, -75, -94, -117, -134, -154, -175],
}

# Letters where the fundamental is the "inner" side of the zone (a–h / A–H)
_SHAFT_UPPER_LETTERS = {"a", "b", "c", "cd", "d", "e", "ef", "f", "fg", "g", "h"}
_HOLE_LOWER_LETTERS = {"A", "B", "C", "CD", "D", "E", "EF", "F", "FG", "G", "H"}

# Grades offered in the UI for each letter family
_COMMON_GRADES = (5, 6, 7, 8, 9, 10, 11, 12)

# Preferred presentation order in dropdowns
HOLE_LETTERS_ORDER = ["A", "B", "C", "D", "E", "F", "G", "H", "JS", "K", "M", "N", "P", "R", "S", "T", "U"]
SHAFT_LETTERS_ORDER = ["a", "b", "c", "d", "e", "f", "g", "h", "js", "k", "m", "n", "p", "r", "s", "t", "u"]


def size_range_index(nominal_mm: float) -> int:
    if nominal_mm <= 0:
        raise ValueError("Nominal size must be greater than 0.")
    for i, limit in enumerate(SIZE_LIMITS):
        if nominal_mm <= limit:
            return i
    raise ValueError(
        f"Nominal size {nominal_mm} mm is outside the supported range "
        f"(0 – {SIZE_LIMITS[-1]} mm)."
    )


def get_it(grade: int, nominal_mm: float) -> int:
    if grade not in IT_TABLE:
        raise ValueError(f"IT grade {grade} is not supported (supported: {sorted(IT_TABLE)}).")
    idx = size_range_index(nominal_mm)
    return IT_TABLE[grade][idx]


def parse_designation(designation: str) -> Tuple[str, int]:
    """Parse 'H7', 'g6', 'JS7', 'js6' into (letter, grade)."""
    text = designation.strip()
    if not text:
        raise ValueError("Empty ISO designation.")

    # Multi-letter prefixes first
    for prefix in ("JS", "js", "CD", "cd", "EF", "ef", "FG", "fg"):
        if text.startswith(prefix):
            grade_str = text[len(prefix):]
            if not grade_str.isdigit():
                raise ValueError(f"Invalid ISO designation: {designation!r}")
            return prefix, int(grade_str)

    letter = text[0]
    grade_str = text[1:]
    if not grade_str.isdigit():
        raise ValueError(f"Invalid ISO designation: {designation!r}")
    return letter, int(grade_str)


def _um_to_mm(value_um: float) -> float:
    return round(value_um / 1000.0, 6)


def deviations_for(designation: str, nominal_mm: float) -> Tuple[float, float]:
    """
    Return (lower_dev_mm, upper_dev_mm) for a hole or shaft designation.
    """
    letter, grade = parse_designation(designation)
    it = get_it(grade, nominal_mm)
    idx = size_range_index(nominal_mm)

    # Symmetric JS / js
    if letter.lower() == "js":
        half = it / 2.0
        return _um_to_mm(-half), _um_to_mm(half)

    is_hole = letter.isupper() or letter in ("JS", "CD", "EF", "FG")
    # Single-letter case: H is hole, h is shaft
    if len(letter) == 1:
        is_hole = letter.isupper()

    if is_hole:
        key = letter.upper() if len(letter) == 1 else letter.upper()
        if key not in HOLE_FUND and key != "JS":
            # map multi-letter
            if key not in HOLE_FUND:
                raise ValueError(f"Unsupported hole letter: {letter}")
        fund_list = HOLE_FUND.get(key)
        if fund_list is None:
            raise ValueError(f"Unsupported hole letter: {letter}")
        fund = fund_list[idx]
        if fund is None:
            raise ValueError(
                f"Designation {designation} is not defined for nominal {nominal_mm} mm."
            )
        if key in _HOLE_LOWER_LETTERS or key in ("A", "B", "C", "D", "E", "F", "G", "H"):
            ei = fund
            es = fund + it
        else:
            # K–U style: fund is ES
            es = fund
            ei = fund - it
        return _um_to_mm(ei), _um_to_mm(es)

    # Shaft
    key = letter.lower()
    fund_list = SHAFT_FUND.get(key)
    if fund_list is None:
        raise ValueError(f"Unsupported shaft letter: {letter}")
    fund = fund_list[idx]
    if fund is None:
        raise ValueError(
            f"Designation {designation} is not defined for nominal {nominal_mm} mm."
        )
    if key in _SHAFT_UPPER_LETTERS:
        es = fund
        ei = fund - it
    else:
        ei = fund
        es = fund + it
    return _um_to_mm(ei), _um_to_mm(es)


def list_hole_designations() -> List[str]:
    """Common hole designations for the dropdown."""
    grades = (6, 7, 8, 9, 10, 11)
    items: List[str] = []
    for letter in HOLE_LETTERS_ORDER:
        for g in grades:
            if letter == "JS":
                items.append(f"JS{g}")
            else:
                items.append(f"{letter}{g}")
    return items


def list_shaft_designations() -> List[str]:
    """Common shaft (stem) designations for the dropdown."""
    grades = (5, 6, 7, 8, 9, 10, 11)
    items: List[str] = []
    for letter in SHAFT_LETTERS_ORDER:
        for g in grades:
            if letter == "js":
                items.append(f"js{g}")
            else:
                items.append(f"{letter}{g}")
    return items


def format_deviations(lower_dev: float, upper_dev: float) -> str:
    return f"{upper_dev:+.4f} / {lower_dev:+.4f}"
