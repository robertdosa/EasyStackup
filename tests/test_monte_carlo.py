"""Tests for core.monte_carlo: sampler, histogram, percentiles, and stack-up."""

from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.calculator import ToleranceCalculator
from core.model import TOL_BILATERAL, Project
from core.monte_carlo import (
    DEFAULT_N_SIGMA,
    DIST_NORMAL,
    DIST_TRIANGULAR,
    DIST_UNIFORM,
    MAX_N_BINS,
    MAX_N_TRIALS,
    MIN_N_BINS,
    MIN_N_TRIALS,
    RESULT_PERCENTILES,
    MonteCarloResult,
    _histogram,
    _percentile,
    _sample_size,
    run_monte_carlo,
    suggested_bin_count,
)

# Fast enough for a full suite, above the engine's minimum.
_N = MIN_N_TRIALS
_SEED = 42


def _project(*dims, gap: bool = True) -> Project:
    """
    Build a closed loop.

    Each dim is (nominal, tolerance, direction, name) or a dict of add_arrow kwargs.
    A dummy gap arrow is appended by default (ignored by the sampler).
    """
    p = Project()
    for spec in dims:
        if isinstance(spec, dict):
            p.add_arrow(**spec)
            continue
        nominal, tolerance, direction, name = spec
        p.add_arrow(nominal, tolerance=tolerance, direction=direction, name=name)
    if gap:
        p.add_arrow(0.0, is_gap=True, name="CL")
    return p


def _clearance_stack() -> Project:
    """Hole 20±0.1 minus shaft 19.8±0.05 → mean clearance 0.2 mm."""
    return _project(
        (20.0, 0.1, 1, "hole"),
        (19.8, 0.05, -1, "shaft"),
    )


def _line_to_line() -> Project:
    return _project(
        (10.0, 0.1, 1, "A"),
        (10.0, 0.1, -1, "B"),
    )


def _geometric_wc(project: Project) -> tuple[float, float]:
    """Unrounded WC envelope (calculator rounds to 4 decimals)."""
    wc_min = 0.0
    wc_max = 0.0
    for a in project.arrows:
        if a.is_gap:
            continue
        size_max = a.nominal + a.upper_dev
        size_min = a.nominal + a.lower_dev
        c_max = a.direction * size_max
        c_min = a.direction * size_min
        wc_max += max(c_max, c_min)
        wc_min += min(c_max, c_min)
    return wc_min, wc_max


def _run(project: Project, **kwargs):
    kwargs.setdefault("n_trials", _N)
    kwargs.setdefault("seed", _SEED)
    return run_monte_carlo(project, **kwargs)


class TestPercentile(unittest.TestCase):
    def test_empty_is_zero(self):
        self.assertEqual(_percentile([], 50), 0.0)

    def test_single_value(self):
        self.assertEqual(_percentile([7.5], 0), 7.5)
        self.assertEqual(_percentile([7.5], 100), 7.5)

    def test_endpoints_and_median(self):
        data = [1.0, 2.0, 3.0, 4.0]
        self.assertEqual(_percentile(data, 0), 1.0)
        self.assertEqual(_percentile(data, 100), 4.0)
        self.assertEqual(_percentile(data, 50), 2.5)

    def test_linear_interpolation(self):
        data = [0.0, 10.0]
        self.assertAlmostEqual(_percentile(data, 25), 2.5)

    def test_clamps_out_of_range_p(self):
        data = [1.0, 2.0, 3.0]
        self.assertEqual(_percentile(data, -10), 1.0)
        self.assertEqual(_percentile(data, 150), 3.0)


class TestSuggestedBinCount(unittest.TestCase):
    def test_clamped_to_readable_range(self):
        self.assertGreaterEqual(suggested_bin_count(1), MIN_N_BINS)
        self.assertGreaterEqual(suggested_bin_count(MIN_N_TRIALS), MIN_N_BINS)
        self.assertLessEqual(suggested_bin_count(MAX_N_TRIALS), MAX_N_BINS)

    def test_more_trials_does_not_exceed_max(self):
        self.assertEqual(suggested_bin_count(10**9), MAX_N_BINS)

    def test_rice_rule_in_the_middle(self):
        # 2 * 8000^(1/3) ≈ 40
        self.assertEqual(suggested_bin_count(8000), 40)


class TestHistogram(unittest.TestCase):
    def test_empty(self):
        edges, counts = _histogram([])
        self.assertEqual(edges, [])
        self.assertEqual(counts, [])

    def test_counts_sum_to_sample_size(self):
        samples = [0.0, 0.1, 0.2, 0.2, 0.9]
        edges, counts = _histogram(samples, n_bins=10)
        self.assertEqual(sum(counts), len(samples))
        self.assertEqual(len(edges), 11)
        self.assertEqual(len(counts), 10)

    def test_constant_samples_still_make_bins(self):
        edges, counts = _histogram([3.0, 3.0, 3.0], n_bins=8)
        self.assertEqual(sum(counts), 3)
        self.assertGreater(edges[-1], edges[0])

    def test_n_bins_floor(self):
        _edges, counts = _histogram([0.0, 1.0], n_bins=2)
        self.assertEqual(len(counts), 8)


class TestSampleSize(unittest.TestCase):
    def test_zero_width_returns_mean(self):
        rng = random.Random(1)
        self.assertEqual(
            _sample_size(rng, 5.0, 5.0, 7.0, DIST_UNIFORM, 3.0, True),
            7.0,
        )

    def test_swaps_inverted_bounds(self):
        rng = random.Random(1)
        x = _sample_size(rng, 2.0, 1.0, 1.5, DIST_UNIFORM, 3.0, True)
        self.assertGreaterEqual(x, 1.0)
        self.assertLessEqual(x, 2.0)

    def test_uniform_stays_in_band(self):
        rng = random.Random(0)
        for _ in range(400):
            x = _sample_size(rng, 1.0, 2.0, 1.5, DIST_UNIFORM, 3.0, True)
            self.assertGreaterEqual(x, 1.0)
            self.assertLessEqual(x, 2.0)

    def test_triangular_stays_in_band(self):
        rng = random.Random(0)
        for _ in range(400):
            x = _sample_size(rng, 1.0, 2.0, 1.5, DIST_TRIANGULAR, 3.0, True)
            self.assertGreaterEqual(x, 1.0)
            self.assertLessEqual(x, 2.0)

    def test_truncated_normal_stays_in_band(self):
        rng = random.Random(0)
        for _ in range(400):
            x = _sample_size(rng, 1.0, 2.0, 1.5, DIST_NORMAL, 3.0, True)
            self.assertGreaterEqual(x, 1.0)
            self.assertLessEqual(x, 2.0)

    def test_untruncated_normal_can_leave_the_band(self):
        rng = random.Random(0)
        outside = 0
        for _ in range(4000):
            x = _sample_size(rng, 1.0, 2.0, 1.5, DIST_NORMAL, 3.0, False)
            if x < 1.0 or x > 2.0:
                outside += 1
        self.assertGreater(outside, 0)


class TestRunValidation(unittest.TestCase):
    def test_unknown_distribution(self):
        with self.assertRaises(ValueError) as ctx:
            _run(_clearance_stack(), distribution="lognormal")
        self.assertIn("Unknown distribution", str(ctx.exception))

    def test_distribution_is_case_insensitive(self):
        r = _run(_clearance_stack(), distribution=" Normal ")
        self.assertEqual(r.distribution, DIST_NORMAL)

    def test_trial_count_bounds(self):
        p = _clearance_stack()
        with self.assertRaises(ValueError):
            run_monte_carlo(p, n_trials=MIN_N_TRIALS - 1, seed=_SEED)
        with self.assertRaises(ValueError):
            run_monte_carlo(p, n_trials=MAX_N_TRIALS + 1, seed=_SEED)

    def test_n_sigma_bounds_only_for_normal(self):
        p = _clearance_stack()
        with self.assertRaises(ValueError):
            _run(p, n_sigma=0.4)
        with self.assertRaises(ValueError):
            _run(p, n_sigma=8.1)
        r = _run(p, distribution=DIST_UNIFORM, n_sigma=0.4)
        self.assertEqual(r.distribution, DIST_UNIFORM)
        self.assertIsNone(r.n_sigma)

    def test_spec_limits_must_be_ordered(self):
        p = _clearance_stack()
        with self.assertRaises(ValueError):
            _run(p, lsl=0.2, usl=0.2)
        with self.assertRaises(ValueError):
            _run(p, lsl=0.3, usl=0.1)

    def test_uniform_and_triangular_are_not_truncated(self):
        for dist in (DIST_UNIFORM, DIST_TRIANGULAR):
            with self.subTest(dist=dist):
                r = _run(_clearance_stack(), distribution=dist, truncate=True)
                self.assertFalse(r.truncate)
                self.assertIsNone(r.n_sigma)


class TestRunEmpty(unittest.TestCase):
    def test_no_arrows(self):
        r = _run(Project())
        self.assertEqual(r.n_dims, 0)
        self.assertEqual(r.hist_counts, [])
        self.assertTrue(any("No contributing" in w for w in r.warnings))

    def test_gap_only_is_empty(self):
        r = _run(_project(gap=True))
        self.assertEqual(r.n_dims, 0)
        self.assertTrue(r.warnings)

    def test_empty_uniform_drops_n_sigma(self):
        r = _run(Project(), distribution=DIST_UNIFORM)
        self.assertIsNone(r.n_sigma)
        self.assertFalse(r.truncate)


class TestRunReproducible(unittest.TestCase):
    def test_same_seed_same_result(self):
        p = _clearance_stack()
        a = _run(p, seed=99)
        b = _run(p, seed=99)
        self.assertEqual(a.mean, b.mean)
        self.assertEqual(a.std, b.std)
        self.assertEqual(a.min_val, b.min_val)
        self.assertEqual(a.max_val, b.max_val)
        self.assertEqual(a.percentiles, b.percentiles)
        self.assertEqual(a.hist_counts, b.hist_counts)
        self.assertEqual(a.seed, 99)

    def test_different_seed_changes_sample(self):
        p = _clearance_stack()
        a = _run(p, seed=1)
        b = _run(p, seed=2)
        self.assertNotEqual((a.min_val, a.max_val, a.mean), (b.min_val, b.max_val, b.mean))

    def test_auto_seed_is_recorded(self):
        r = run_monte_carlo(_clearance_stack(), n_trials=_N, seed=None)
        self.assertIsInstance(r.seed, int)


class TestRunStack(unittest.TestCase):
    def test_gap_arrow_is_ignored(self):
        r = _run(_clearance_stack())
        self.assertEqual(r.n_dims, 2)
        self.assertEqual(r.n_trials, _N)

    def test_mean_matches_symmetric_clearance(self):
        r = _run(_clearance_stack())
        self.assertAlmostEqual(r.mean, 0.2, delta=0.01)

    def test_line_to_line_mean_is_near_zero(self):
        r = _run(_line_to_line())
        self.assertAlmostEqual(r.mean, 0.0, delta=0.01)

    def test_exact_zero_mean_warns_line_to_line(self):
        r = _run(_project((10.0, 0.0, 1, "A"), (10.0, 0.0, -1, "B")))
        self.assertEqual(r.mean, 0.0)
        self.assertTrue(any("line-to-line" in w.lower() for w in r.warnings))

    def test_wc_rss_match_calculator(self):
        p = _clearance_stack()
        wc = ToleranceCalculator.calculate(p)
        r = _run(p)
        self.assertEqual(r.wc_min, wc["wc_min"])
        self.assertEqual(r.wc_max, wc["wc_max"])
        self.assertEqual(r.rss_min, wc["rss_min"])
        self.assertEqual(r.rss_max, wc["rss_max"])
        self.assertEqual(r.wc_nominal, wc["nominal"])

    def test_percentiles_are_ordered(self):
        r = _run(_clearance_stack())
        self.assertEqual(tuple(r.percentiles), RESULT_PERCENTILES)
        vals = [r.percentiles[p] for p in RESULT_PERCENTILES]
        self.assertEqual(vals, sorted(vals))
        self.assertLessEqual(r.min_val, r.percentiles[0.135])
        self.assertGreaterEqual(r.max_val, r.percentiles[99.865])

    def test_assembly_percents_sum_to_100(self):
        r = _run(_clearance_stack())
        total = r.pct_gap + r.pct_interference + r.pct_line_to_line
        self.assertAlmostEqual(total, 100.0, places=6)
        self.assertGreater(r.pct_gap, 99.0)

    def test_bilateral_mean_shift(self):
        p = Project()
        p.add_arrow(
            10.0,
            direction=1,
            name="plus",
            tolerance_type=TOL_BILATERAL,
            upper_dev=0.2,
            lower_dev=0.0,
        )
        p.add_arrow(10.0, tolerance=0.0, direction=-1, name="fixed")
        r = _run(p)
        # Mean size of plus is 10.1; minus is 10.0 → stack 0.1
        self.assertAlmostEqual(r.mean, 0.1, delta=0.01)

    def test_zero_width_dimensions_are_deterministic(self):
        p = _project((10.0, 0.0, 1, "A"), (4.0, 0.0, -1, "B"))
        r = _run(p)
        self.assertAlmostEqual(r.mean, 6.0, places=9)
        self.assertAlmostEqual(r.min_val, 6.0, places=9)
        self.assertAlmostEqual(r.max_val, 6.0, places=9)
        self.assertAlmostEqual(r.std, 0.0, places=9)


class TestRunTruncation(unittest.TestCase):
    def test_truncated_normal_stays_inside_wc(self):
        p = _clearance_stack()
        r = _run(p, distribution=DIST_NORMAL, truncate=True)
        lo, hi = _geometric_wc(p)
        self.assertGreaterEqual(r.min_val, lo - 1e-12)
        self.assertLessEqual(r.max_val, hi + 1e-12)
        self.assertTrue(r.truncate)
        self.assertEqual(r.n_sigma, DEFAULT_N_SIGMA)

    def test_uniform_stays_inside_wc(self):
        p = _clearance_stack()
        r = _run(p, distribution=DIST_UNIFORM)
        lo, hi = _geometric_wc(p)
        self.assertGreaterEqual(r.min_val, lo - 1e-12)
        self.assertLessEqual(r.max_val, hi + 1e-12)

    def test_triangular_stays_inside_wc(self):
        p = _clearance_stack()
        r = _run(p, distribution=DIST_TRIANGULAR)
        lo, hi = _geometric_wc(p)
        self.assertGreaterEqual(r.min_val, lo - 1e-12)
        self.assertLessEqual(r.max_val, hi + 1e-12)

    def test_untruncated_normal_can_exceed_wc(self):
        # ±1σ band so tails regularly fall outside the drawing limits.
        p = _clearance_stack()
        r = _run(p, distribution=DIST_NORMAL, truncate=False, n_sigma=1.0, n_trials=2000)
        lo, hi = _geometric_wc(p)
        exceeded = r.min_val < lo - 1e-12 or r.max_val > hi + 1e-12
        self.assertTrue(exceeded)
        self.assertTrue(any("Untruncated" in w for w in r.warnings))
        self.assertFalse(r.truncate)


class TestRunYield(unittest.TestCase):
    def test_no_spec_skips_yield(self):
        r = _run(_clearance_stack())
        self.assertIsNone(r.yield_pct)
        self.assertIsNone(r.pct_below_lsl)
        self.assertIsNone(r.pct_above_usl)
        self.assertIsNone(r.lsl)
        self.assertIsNone(r.usl)

    def test_limits_wide_open_are_full_yield(self):
        r = _run(_clearance_stack(), lsl=-10.0, usl=10.0)
        self.assertAlmostEqual(r.yield_pct, 100.0, places=6)
        self.assertAlmostEqual(r.pct_below_lsl, 0.0, places=6)
        self.assertAlmostEqual(r.pct_above_usl, 0.0, places=6)

    def test_lsl_above_all_samples(self):
        r = _run(_clearance_stack(), lsl=10.0)
        self.assertAlmostEqual(r.yield_pct, 0.0, places=6)
        self.assertAlmostEqual(r.pct_below_lsl, 100.0, places=6)
        self.assertIsNone(r.pct_above_usl)

    def test_usl_below_all_samples(self):
        r = _run(_clearance_stack(), usl=-10.0)
        self.assertAlmostEqual(r.yield_pct, 0.0, places=6)
        self.assertAlmostEqual(r.pct_above_usl, 100.0, places=6)

    def test_lsl_zero_flags_interference(self):
        # Mean 0 ± ~0.14 → some gap, some interference.
        r = _run(_line_to_line(), lsl=0.0, n_trials=4000)
        self.assertIsNotNone(r.yield_pct)
        self.assertAlmostEqual(r.pct_below_lsl + r.yield_pct, 100.0, delta=0.05)
        self.assertGreater(r.pct_below_lsl, 5.0)
        self.assertGreater(r.yield_pct, 5.0)

    def test_yield_parts_sum_when_both_limits_set(self):
        r = _run(_clearance_stack(), lsl=0.15, usl=0.25, n_trials=4000)
        parts = r.yield_pct + r.pct_below_lsl + r.pct_above_usl
        self.assertAlmostEqual(parts, 100.0, places=6)


class TestRunContributions(unittest.TestCase):
    def test_single_dimension_is_100_percent(self):
        p = _project((10.0, 0.1, 1, "only"))
        r = _run(p)
        self.assertEqual(len(r.contributions), 1)
        self.assertEqual(r.contributions[0]["percent"], 100.0)
        self.assertEqual(r.contributions[0]["name"], "only")
        self.assertEqual(r.contributions[0]["id"], 1)

    def test_wider_band_dominates_variance(self):
        p = _project(
            (10.0, 0.4, 1, "wide"),
            (10.0, 0.05, -1, "narrow"),
        )
        r = _run(p)
        by_name = {c["name"]: c["percent"] for c in r.contributions}
        self.assertGreater(by_name["wide"], 80.0)
        self.assertLess(by_name["narrow"], 20.0)
        self.assertAlmostEqual(sum(c["percent"] for c in r.contributions), 100.0, delta=0.2)

    def test_zero_tolerance_contributions_are_zero(self):
        p = _project((10.0, 0.0, 1, "A"), (4.0, 0.0, -1, "B"))
        r = _run(p)
        self.assertTrue(all(c["percent"] == 0.0 for c in r.contributions))


class TestRunHistogram(unittest.TestCase):
    def test_counts_cover_every_trial(self):
        r = _run(_clearance_stack())
        self.assertEqual(sum(r.hist_counts), r.n_trials)
        self.assertEqual(len(r.hist_edges), len(r.hist_counts) + 1)
        self.assertEqual(len(r.hist_counts), suggested_bin_count(_N))

    def test_n_bins_override_is_clamped(self):
        r_lo = _run(_clearance_stack(), n_bins=4)
        r_hi = _run(_clearance_stack(), n_bins=400)
        self.assertEqual(len(r_lo.hist_counts), MIN_N_BINS)
        self.assertEqual(len(r_hi.hist_counts), MAX_N_BINS)


class TestResultSerialization(unittest.TestCase):
    def test_round_trip_preserves_percentiles_and_histogram(self):
        original = _run(_clearance_stack(), lsl=0.0, usl=0.4)
        restored = MonteCarloResult.from_dict(original.to_dict())
        self.assertEqual(restored.n_trials, original.n_trials)
        self.assertEqual(restored.distribution, original.distribution)
        self.assertEqual(restored.seed, original.seed)
        self.assertEqual(restored.hist_counts, original.hist_counts)
        self.assertEqual(list(restored.percentiles), list(original.percentiles))
        for p in RESULT_PERCENTILES:
            self.assertAlmostEqual(restored.percentiles[p], original.percentiles[p])
        self.assertEqual(restored.lsl, original.lsl)
        self.assertEqual(restored.usl, original.usl)
        self.assertEqual(restored.contributions, original.contributions)

    def test_json_string_percentile_keys(self):
        original = _run(_clearance_stack())
        payload = original.to_dict()
        self.assertTrue(all(isinstance(k, str) for k in payload["percentiles"]))
        restored = MonteCarloResult.from_dict(payload)
        self.assertIn(50.0, restored.percentiles)


if __name__ == "__main__":
    unittest.main()
