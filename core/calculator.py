import math
from typing import Dict, List

# Stored values are millimetres. Treat residuals below this as zero for warnings.
_ZERO_CLEARANCE_EPS_MM = 1e-6

_EMPTY_RESULT = {
    "nominal": 0.0,
    "wc_min": 0.0,
    "wc_max": 0.0,
    "rss_min": 0.0,
    "rss_max": 0.0,
    "contributions": [],
    "warnings": [],
}


class ToleranceCalculator:
    @staticmethod
    def calculate(project) -> Dict:
        if not project.arrows:
            return dict(_EMPTY_RESULT)

        # Only normal dimensions contribute to the stackup
        dims = [a for a in project.arrows if not a.is_gap]

        if not dims:
            return dict(_EMPTY_RESULT)

        # Bilateral / ISO are converted to equivalent symmetric form:
        #   mean_size = nominal + mid_dev
        #   ±tol_eq   = half_range
        # so the stack center shifts when the band is not centered on nominal.
        nominal_gap = 0.0
        wc_min = 0.0
        wc_max = 0.0
        rss_sq = 0.0
        band_sum = 0.0

        for a in dims:
            size_max = a.nominal + a.upper_dev
            size_min = a.nominal + a.lower_dev
            mean_size = a.nominal + a.mid_dev
            half = a.half_range

            # Direction-aware extremes (direction = -1 flips min/max for the stack)
            c_at_max = a.direction * size_max
            c_at_min = a.direction * size_min

            wc_max += max(c_at_max, c_at_min)
            wc_min += min(c_at_max, c_at_min)
            nominal_gap += a.direction * mean_size
            rss_sq += half ** 2
            band_sum += abs(a.upper_dev - a.lower_dev)

        rss_tol = math.sqrt(rss_sq)
        rss_max = nominal_gap + rss_tol
        rss_min = nominal_gap - rss_tol

        # Contribution by full band width
        contributions = []
        for a in dims:
            band = abs(a.upper_dev - a.lower_dev)
            contrib = (band / band_sum * 100) if band_sum > 0 else 0
            contributions.append({
                "id": a.id,
                "name": a.name,
                "percent": round(contrib, 1)
            })

        warnings: List[str] = []
        # Zero mean clearance is a valid line-to-line / transition case, but
        # easy to miss — surface it so the user can confirm intent.
        if abs(nominal_gap) <= _ZERO_CLEARANCE_EPS_MM:
            warnings.append(
                "Mean clearance is zero (line-to-line). This can be valid, but "
                "confirm the loop directions and nominals. Use WC/RSS to see "
                "whether tolerances still allow gap or interference."
            )

        return {
            "nominal": round(nominal_gap, 4),
            "wc_min": round(wc_min, 4),
            "wc_max": round(wc_max, 4),
            "rss_min": round(rss_min, 4),
            "rss_max": round(rss_max, 4),
            "contributions": contributions,
            "warnings": warnings,
        }