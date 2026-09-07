"""Tests for .eysp save/load, including calculation and Monte Carlo snapshots."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.calculator import ToleranceCalculator
from core.model import Project
from core.monte_carlo import MonteCarloResult, run_monte_carlo
from core.project_io import DEFAULT_ORIGIN_X, load_project, save_project


def _closed_project() -> Project:
    p = Project()
    p.title = "stack"
    p.add_arrow(20.0, tolerance=0.1, direction=1, name="hole")
    p.add_arrow(19.8, tolerance=0.05, direction=-1, name="shaft")
    p.add_arrow(0.2, is_gap=True, name="CL")
    return p


class TestProjectIo(unittest.TestCase):
    def test_legacy_file_without_results_still_loads(self):
        p = _closed_project()
        raw = p.to_dict()
        raw.pop("calculation", None)
        raw.pop("monte_carlo", None)
        raw["version"] = 1
        raw["original_start_x"] = DEFAULT_ORIGIN_X
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.eysp"
            path.write_text(json.dumps(raw), encoding="utf-8")
            loaded, meta = load_project(path)
        self.assertEqual(len(loaded.arrows), 3)
        self.assertIsNone(loaded.calculation)
        self.assertIsNone(loaded.monte_carlo)
        self.assertEqual(meta["original_start_x"], DEFAULT_ORIGIN_X)

    def test_save_load_round_trip_includes_calculation_and_mc(self):
        p = _closed_project()
        p.calculation = ToleranceCalculator.calculate(p)
        mc = run_monte_carlo(p, n_trials=1000, seed=7, lsl=0.0)
        p.monte_carlo = mc.to_dict()

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "with_results.eysp"
            save_project(path, p, original_start_x=480.0)
            loaded, meta = load_project(path)

        self.assertEqual(meta["original_start_x"], 480.0)
        self.assertIsInstance(loaded.calculation, dict)
        self.assertAlmostEqual(loaded.calculation["nominal"], p.calculation["nominal"])
        self.assertEqual(
            loaded.calculation["contributions"], p.calculation["contributions"]
        )
        self.assertIsInstance(loaded.monte_carlo, dict)
        restored = MonteCarloResult.from_dict(loaded.monte_carlo)
        self.assertEqual(restored.seed, 7)
        self.assertEqual(restored.n_trials, 1000)
        self.assertEqual(restored.hist_counts, mc.hist_counts)
        self.assertEqual(restored.mean, mc.mean)
        self.assertEqual(restored.lsl, 0.0)
        self.assertTrue(loaded.include_mc_in_pdf)

    def test_include_mc_in_pdf_round_trip(self):
        p = _closed_project()
        p.include_mc_in_pdf = False
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "no_mc_pdf.eysp"
            save_project(path, p)
            loaded, _meta = load_project(path)
        self.assertFalse(loaded.include_mc_in_pdf)

    def test_legacy_file_defaults_include_mc_in_pdf(self):
        p = _closed_project()
        raw = p.to_dict()
        raw.pop("include_mc_in_pdf", None)
        raw["version"] = 1
        raw["original_start_x"] = DEFAULT_ORIGIN_X
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy_flag.eysp"
            path.write_text(json.dumps(raw), encoding="utf-8")
            loaded, _meta = load_project(path)
        self.assertTrue(loaded.include_mc_in_pdf)

    def test_corrupt_monte_carlo_is_dropped(self):
        p = _closed_project()
        raw = p.to_dict()
        raw["version"] = 2
        raw["original_start_x"] = DEFAULT_ORIGIN_X
        raw["monte_carlo"] = {"not": "a result"}
        raw["calculation"] = {"wc_min": 0.0}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.eysp"
            path.write_text(json.dumps(raw), encoding="utf-8")
            loaded, _meta = load_project(path)
        self.assertIsNone(loaded.monte_carlo)
        self.assertIsNone(loaded.calculation)


if __name__ == "__main__":
    unittest.main()
