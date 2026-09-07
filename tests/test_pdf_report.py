"""Tests for PDF report export, including optional Monte Carlo pages."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.calculator import ToleranceCalculator
from core.model import Project
from core.monte_carlo import run_monte_carlo
from core.pdf_report import export_pdf_report, parse_monte_carlo


def _closed_project() -> Project:
    p = Project()
    p.title = "pdf-stack"
    p.add_arrow(20.0, tolerance=0.1, direction=1, name="hole")
    p.add_arrow(19.8, tolerance=0.05, direction=-1, name="shaft")
    p.add_arrow(0.2, is_gap=True, name="CL")
    return p


class TestParseMonteCarlo(unittest.TestCase):
    def test_none_and_garbage(self):
        self.assertIsNone(parse_monte_carlo(None))
        self.assertIsNone(parse_monte_carlo({"not": "valid"}))
        self.assertIsNone(parse_monte_carlo("x"))

    def test_dict_and_object(self):
        p = _closed_project()
        result = run_monte_carlo(p, n_trials=1000, seed=1)
        self.assertEqual(parse_monte_carlo(result).seed, 1)
        self.assertEqual(parse_monte_carlo(result.to_dict()).n_trials, 1000)


class TestExportPdf(unittest.TestCase):
    def test_export_without_monte_carlo(self):
        p = _closed_project()
        results = ToleranceCalculator.calculate(p)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "no_mc.pdf"
            export_pdf_report(path, p, results, monte_carlo=None)
            data = path.read_bytes()
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertGreater(len(data), 1000)

    def test_export_with_monte_carlo_is_larger(self):
        p = _closed_project()
        results = ToleranceCalculator.calculate(p)
        mc = run_monte_carlo(p, n_trials=1000, seed=3, lsl=0.0)
        with tempfile.TemporaryDirectory() as tmp:
            without = Path(tmp) / "without.pdf"
            with_mc = Path(tmp) / "with.pdf"
            export_pdf_report(without, p, results, monte_carlo=None)
            export_pdf_report(with_mc, p, results, monte_carlo=mc)
            a = without.read_bytes()
            b = with_mc.read_bytes()
        self.assertTrue(a.startswith(b"%PDF"))
        self.assertTrue(b.startswith(b"%PDF"))
        self.assertGreater(len(b), len(a))


if __name__ == "__main__":
    unittest.main()
