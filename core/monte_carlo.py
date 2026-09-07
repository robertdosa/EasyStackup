"""
Monte Carlo tolerance stack-up.

Each contributing dimension is sampled from a distribution spanning its
tolerance band, then combined with the same direction convention as
worst-case / RSS (positive residual = gap, negative = interference).

Distributions
-------------
normal
    Centered on mean size. The band is treated as ±nσ (default n=3), so
    σ = half_range / n_sigma. With truncate=True (default), samples outside
    the band are rejected — a 100% inspection model. Untruncated normals
    can fall outside the drawing limits and the stack can exceed WC.
uniform
    Every size in [min, max] equally likely (no process knowledge).
triangular
    Mode at mean size, density zero at the band edges.

Percentiles are linear-interpolated on the sorted sample (inclusive).
Variance contribution is the share of each dimension's contribution
variance (direction applied) among independent dimensions.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.calculator import ToleranceCalculator
from core.model import Arrow

DIST_NORMAL = "normal"
DIST_UNIFORM = "uniform"
DIST_TRIANGULAR = "triangular"

VALID_DISTRIBUTIONS = (DIST_NORMAL, DIST_UNIFORM, DIST_TRIANGULAR)

DEFAULT_N_TRIALS = 50_000
MIN_N_TRIALS = 1_000
MAX_N_TRIALS = 500_000
DEFAULT_N_SIGMA = 3.0
DEFAULT_N_BINS = 40
MIN_N_BINS = 24
MAX_N_BINS = 60

# Percentiles shown in the results panel (P0.135 / P99.865 ≈ ±3σ of a normal)
RESULT_PERCENTILES = (0.135, 2.5, 50.0, 97.5, 99.865)

_ZERO_EPS_MM = 1e-6
_EMPTY_WC = {
    "nominal": 0.0,
    "wc_min": 0.0,
    "wc_max": 0.0,
    "rss_min": 0.0,
    "rss_max": 0.0,
}


@dataclass
class MonteCarloResult:
    n_trials: int
    n_dims: int
    distribution: str
    n_sigma: Optional[float]
    truncate: bool
    seed: int
    mean: float
    std: float
    min_val: float
    max_val: float
    percentiles: Dict[float, float]
    hist_edges: List[float]
    hist_counts: List[int]
    pct_gap: float
    pct_interference: float
    pct_line_to_line: float
    lsl: Optional[float]
    usl: Optional[float]
    yield_pct: Optional[float]
    pct_below_lsl: Optional[float]
    pct_above_usl: Optional[float]
    wc_nominal: float
    wc_min: float
    wc_max: float
    rss_min: float
    rss_max: float
    contributions: List[Dict]
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["percentiles"] = {
            str(k): float(v) for k, v in self.percentiles.items()
        }
        return payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MonteCarloResult":
        if not isinstance(data, dict):
            raise TypeError("Monte Carlo result must be an object.")
        pct_raw = data.get("percentiles") or {}
        if not isinstance(pct_raw, dict):
            raise TypeError("percentiles must be an object.")
        percentiles = {float(k): float(v) for k, v in pct_raw.items()}

        def _opt_float(key: str) -> Optional[float]:
            value = data.get(key)
            return None if value is None else float(value)

        contrib = data.get("contributions") or []
        if not isinstance(contrib, list):
            contrib = []
        warnings = data.get("warnings") or []
        if not isinstance(warnings, list):
            warnings = []
        return cls(
            n_trials=int(data["n_trials"]),
            n_dims=int(data.get("n_dims", 0)),
            distribution=str(data.get("distribution") or DIST_NORMAL),
            n_sigma=_opt_float("n_sigma"),
            truncate=bool(data.get("truncate", False)),
            seed=int(data.get("seed", 0)),
            mean=float(data.get("mean", 0.0)),
            std=float(data.get("std", 0.0)),
            min_val=float(data.get("min_val", 0.0)),
            max_val=float(data.get("max_val", 0.0)),
            percentiles=percentiles,
            hist_edges=[float(x) for x in (data.get("hist_edges") or [])],
            hist_counts=[int(x) for x in (data.get("hist_counts") or [])],
            pct_gap=float(data.get("pct_gap", 0.0)),
            pct_interference=float(data.get("pct_interference", 0.0)),
            pct_line_to_line=float(data.get("pct_line_to_line", 0.0)),
            lsl=_opt_float("lsl"),
            usl=_opt_float("usl"),
            yield_pct=_opt_float("yield_pct"),
            pct_below_lsl=_opt_float("pct_below_lsl"),
            pct_above_usl=_opt_float("pct_above_usl"),
            wc_nominal=float(data.get("wc_nominal", 0.0)),
            wc_min=float(data.get("wc_min", 0.0)),
            wc_max=float(data.get("wc_max", 0.0)),
            rss_min=float(data.get("rss_min", 0.0)),
            rss_max=float(data.get("rss_max", 0.0)),
            contributions=list(contrib),
            warnings=[str(w) for w in warnings],
        )


def _empty_result(
    *,
    n_trials: int = 0,
    distribution: str = DIST_NORMAL,
    n_sigma: Optional[float] = DEFAULT_N_SIGMA,
    truncate: bool = True,
    seed: int = 0,
    warnings: Optional[Sequence[str]] = None,
) -> MonteCarloResult:
    return MonteCarloResult(
        n_trials=n_trials,
        n_dims=0,
        distribution=distribution,
        n_sigma=n_sigma if distribution == DIST_NORMAL else None,
        truncate=bool(truncate) and distribution == DIST_NORMAL,
        seed=seed,
        mean=0.0,
        std=0.0,
        min_val=0.0,
        max_val=0.0,
        percentiles={p: 0.0 for p in RESULT_PERCENTILES},
        hist_edges=[],
        hist_counts=[],
        pct_gap=0.0,
        pct_interference=0.0,
        pct_line_to_line=0.0,
        lsl=None,
        usl=None,
        yield_pct=None,
        pct_below_lsl=None,
        pct_above_usl=None,
        wc_nominal=0.0,
        wc_min=0.0,
        wc_max=0.0,
        rss_min=0.0,
        rss_max=0.0,
        contributions=[],
        warnings=list(warnings or []),
    )


def _percentile(sorted_samples: Sequence[float], p: float) -> float:
    """Linear-interpolated percentile, p in [0, 100]."""
    n = len(sorted_samples)
    if n == 0:
        return 0.0
    if n == 1:
        return float(sorted_samples[0])
    p = max(0.0, min(100.0, float(p)))
    k = (p / 100.0) * (n - 1)
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return float(sorted_samples[lo])
    w = k - lo
    return float(sorted_samples[lo]) * (1.0 - w) + float(sorted_samples[hi]) * w


def suggested_bin_count(n_trials: int) -> int:
    """
    Number of histogram bins from the iteration count (Rice's rule: 2 n^(1/3)).

    More iterations → finer bins. Clamped so the plot stays readable.
    """
    k = int(round(2.0 * (max(int(n_trials), 1) ** (1.0 / 3.0))))
    return max(MIN_N_BINS, min(MAX_N_BINS, k))


def _histogram(
    samples: Sequence[float],
    n_bins: int = DEFAULT_N_BINS,
) -> Tuple[List[float], List[int]]:
    if not samples:
        return [], []
    lo = min(samples)
    hi = max(samples)
    if hi <= lo:
        pad = max(abs(lo) * 1e-6, 1e-9)
        lo -= pad
        hi += pad
    n_bins = max(8, int(n_bins))
    width = (hi - lo) / n_bins
    counts = [0] * n_bins
    for x in samples:
        idx = int((x - lo) / width)
        if idx >= n_bins:
            idx = n_bins - 1
        elif idx < 0:
            idx = 0
        counts[idx] += 1
    edges = [lo + i * width for i in range(n_bins + 1)]
    return edges, counts


def _sample_size(
    rng: random.Random,
    lo: float,
    hi: float,
    mean: float,
    distribution: str,
    n_sigma: float,
    truncate: bool,
) -> float:
    if hi < lo:
        lo, hi = hi, lo
    if hi - lo <= 1e-15:
        return mean

    if distribution == DIST_UNIFORM:
        return rng.uniform(lo, hi)

    if distribution == DIST_TRIANGULAR:
        mode = min(max(mean, lo), hi)
        return rng.triangular(lo, hi, mode)

    # normal
    half = 0.5 * (hi - lo)
    sigma = half / n_sigma if n_sigma > 0 else half / DEFAULT_N_SIGMA
    if sigma <= 0:
        return mean
    if not truncate:
        return rng.gauss(mean, sigma)
    # Rejection sampling; ±3σ truncated rejects ~0.27% so this is cheap.
    for _ in range(64):
        x = rng.gauss(mean, sigma)
        if lo <= x <= hi:
            return x
    return min(hi, max(lo, rng.gauss(mean, sigma)))


def run_monte_carlo(
    project,
    *,
    n_trials: int = DEFAULT_N_TRIALS,
    distribution: str = DIST_NORMAL,
    n_sigma: float = DEFAULT_N_SIGMA,
    truncate: bool = True,
    seed: Optional[int] = None,
    lsl: Optional[float] = None,
    usl: Optional[float] = None,
    n_bins: Optional[int] = None,
) -> MonteCarloResult:
    """
    Run a Monte Carlo stack-up on `project`.

    All lengths (including optional LSL/USL) are millimetres, matching
    stored project values.
    """
    dist = str(distribution or DIST_NORMAL).strip().lower()
    if dist not in VALID_DISTRIBUTIONS:
        raise ValueError(
            f"Unknown distribution {distribution!r}. "
            f"Expected one of {VALID_DISTRIBUTIONS}."
        )

    n_trials = int(n_trials)
    if n_trials < MIN_N_TRIALS or n_trials > MAX_N_TRIALS:
        raise ValueError(
            f"Number of trials must be between {MIN_N_TRIALS:,} and {MAX_N_TRIALS:,}."
        )

    n_sigma_val = float(n_sigma) if n_sigma is not None else DEFAULT_N_SIGMA
    if dist == DIST_NORMAL and not (0.5 <= n_sigma_val <= 8.0):
        raise ValueError("nσ must be between 0.5 and 8.")

    if lsl is not None and usl is not None and float(lsl) >= float(usl):
        raise ValueError("Lower spec limit must be less than the upper spec limit.")

    used_seed = int(seed) if seed is not None else random.SystemRandom().randint(0, 2**31 - 1)
    rng = random.Random(used_seed)
    truncate = bool(truncate) and dist == DIST_NORMAL

    dims: List[Arrow] = [a for a in project.arrows if not a.is_gap]
    if not dims:
        return _empty_result(
            n_trials=n_trials,
            distribution=dist,
            n_sigma=n_sigma_val,
            truncate=truncate,
            seed=used_seed,
            warnings=["No contributing dimensions to simulate."],
        )

    # Precompute band for each dimension (mm)
    bands: List[Tuple[Arrow, float, float, float]] = []
    for a in dims:
        size_max = a.nominal + a.upper_dev
        size_min = a.nominal + a.lower_dev
        if size_max < size_min:
            size_min, size_max = size_max, size_min
        bands.append((a, size_min, size_max, a.mean_size))

    n_dims = len(bands)
    samples: List[float] = []
    sum_c = [0.0] * n_dims
    sum_c2 = [0.0] * n_dims
    n_gap = 0
    n_intf = 0
    n_zero = 0
    n_below_lsl = 0
    n_above_usl = 0
    n_in_spec = 0
    have_spec = lsl is not None or usl is not None

    for _ in range(n_trials):
        total = 0.0
        for i, (a, lo, hi, mean) in enumerate(bands):
            size = _sample_size(rng, lo, hi, mean, dist, n_sigma_val, truncate)
            contrib = a.direction * size
            total += contrib
            sum_c[i] += contrib
            sum_c2[i] += contrib * contrib
        samples.append(total)

        if total > _ZERO_EPS_MM:
            n_gap += 1
        elif total < -_ZERO_EPS_MM:
            n_intf += 1
        else:
            n_zero += 1

        if have_spec:
            ok = True
            if lsl is not None and total < float(lsl):
                n_below_lsl += 1
                ok = False
            if usl is not None and total > float(usl):
                n_above_usl += 1
                ok = False
            if ok:
                n_in_spec += 1

    mean = statistics.fmean(samples)
    std = statistics.pstdev(samples) if n_trials > 1 else 0.0
    min_val = min(samples)
    max_val = max(samples)
    ordered = sorted(samples)
    percentiles = {p: _percentile(ordered, p) for p in RESULT_PERCENTILES}
    if n_bins is None:
        n_bins = suggested_bin_count(n_trials)
    else:
        n_bins = max(MIN_N_BINS, min(MAX_N_BINS, int(n_bins)))
    hist_edges, hist_counts = _histogram(samples, n_bins=n_bins)

    inv_n = 1.0 / n_trials
    variances = []
    for i in range(n_dims):
        mu = sum_c[i] * inv_n
        var = max(0.0, sum_c2[i] * inv_n - mu * mu)
        variances.append(var)
    var_sum = sum(variances)
    contributions = []
    for a, var in zip(dims, variances):
        pct = (var / var_sum * 100.0) if var_sum > 0 else 0.0
        contributions.append({
            "id": a.id,
            "name": a.name,
            "percent": round(pct, 1),
        })

    try:
        wc = ToleranceCalculator.calculate(project)
    except Exception:
        wc = dict(_EMPTY_WC)

    warnings: List[str] = []
    if abs(mean) <= _ZERO_EPS_MM:
        warnings.append(
            "Mean simulated clearance is zero (line-to-line). Confirm loop "
            "directions and nominals."
        )
    if dist == DIST_NORMAL and not truncate and (min_val < wc.get("wc_min", min_val) - 1e-9
                                                 or max_val > wc.get("wc_max", max_val) + 1e-9):
        warnings.append(
            "Untruncated normal samples can fall outside the drawing limits, "
            "so the simulated stack can exceed worst-case."
        )

    inv_pct = 100.0 / n_trials
    return MonteCarloResult(
        n_trials=n_trials,
        n_dims=n_dims,
        distribution=dist,
        n_sigma=n_sigma_val if dist == DIST_NORMAL else None,
        truncate=truncate,
        seed=used_seed,
        mean=mean,
        std=std,
        min_val=min_val,
        max_val=max_val,
        percentiles=percentiles,
        hist_edges=hist_edges,
        hist_counts=hist_counts,
        pct_gap=n_gap * inv_pct,
        pct_interference=n_intf * inv_pct,
        pct_line_to_line=n_zero * inv_pct,
        lsl=float(lsl) if lsl is not None else None,
        usl=float(usl) if usl is not None else None,
        yield_pct=(n_in_spec * inv_pct) if have_spec else None,
        pct_below_lsl=(n_below_lsl * inv_pct) if lsl is not None else None,
        pct_above_usl=(n_above_usl * inv_pct) if usl is not None else None,
        wc_nominal=float(wc.get("nominal", 0.0)),
        wc_min=float(wc.get("wc_min", 0.0)),
        wc_max=float(wc.get("wc_max", 0.0)),
        rss_min=float(wc.get("rss_min", 0.0)),
        rss_max=float(wc.get("rss_max", 0.0)),
        contributions=contributions,
        warnings=warnings,
    )
