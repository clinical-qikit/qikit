"""
constants.py — SPC constant tables for qikit.

References
----------
1. Montgomery DC. Introduction to Statistical Quality Control, 8th ed. Wiley, 2019.
2. Spiegelhalter DJ. Funnel plots for comparing institutional performance.
   Statistics in Medicine 2005;24(8):1185-1202.
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# Normal deviates for the funnel probability contours (Spiegelhalter 2005).
#
# Funnel plots are drawn at 95% and 99.8% rather than at 2σ/3σ: 99.8% keeps the
# expected number of false alarms near one even across a few hundred providers.
# Only Byar's approximation consumes these — the exact method inverts the Poisson
# CDF directly, so no Φ⁻¹ implementation is needed anywhere.
# ---------------------------------------------------------------------------

Z_95 = 1.959963984540054   # Φ⁻¹(0.975)
Z_998 = 3.090232306167813  # Φ⁻¹(0.999)

# Power convention for the detectability column, not a limit: Φ⁻¹(0.8). Used only
# by the large-count normal fallback in oe_detectable_ratio.
Z_80 = 0.8416212335729143  # Φ⁻¹(0.8)

# ---------------------------------------------------------------------------
# SPC constants  (Montgomery 2019, Appendix VI, Table VI)
# ---------------------------------------------------------------------------

D2 = {2: 1.128}
D4 = {2: 3.267}

# B3, B4 for S charts (n = subgroup size, 2..25)
B3 = {
    2: 0.000, 3: 0.000, 4: 0.000, 5: 0.000, 6: 0.030, 7: 0.118, 8: 0.185,
    9: 0.239, 10: 0.284, 11: 0.321, 12: 0.354, 13: 0.382, 14: 0.406,
    15: 0.428, 16: 0.448, 17: 0.466, 18: 0.482, 19: 0.497, 20: 0.510,
    21: 0.523, 22: 0.534, 23: 0.545, 24: 0.555, 25: 0.565,
}
B4 = {
    2: 3.267, 3: 2.568, 4: 2.266, 5: 2.089, 6: 1.970, 7: 1.882, 8: 1.815,
    9: 1.761, 10: 1.716, 11: 1.679, 12: 1.646, 13: 1.618, 14: 1.594,
    15: 1.572, 16: 1.552, 17: 1.534, 18: 1.518, 19: 1.503, 20: 1.490,
    21: 1.477, 22: 1.466, 23: 1.455, 24: 1.445, 25: 1.435,
}

# A3 for Xbar charts (n = subgroup size, 2..25)  Montgomery (2019), Table VI
A3 = {
    2: 2.659, 3: 1.954, 4: 1.628, 5: 1.427, 6: 1.287, 7: 1.182, 8: 1.099,
    9: 1.032, 10: 0.975, 11: 0.927, 12: 0.886, 13: 0.850, 14: 0.817,
    15: 0.789, 16: 0.763, 17: 0.739, 18: 0.718, 19: 0.698, 20: 0.680,
    21: 0.663, 22: 0.647, 23: 0.633, 24: 0.619, 25: 0.606,
}

# c4 unbiasing constant (n = subgroup size, 2..25)  Montgomery (2019), Table VI
C4 = {
    2: 0.7979, 3: 0.8862, 4: 0.9213, 5: 0.9400, 6: 0.9515, 7: 0.9594,
    8: 0.9650, 9: 0.9693, 10: 0.9727, 11: 0.9754, 12: 0.9776, 13: 0.9794,
    14: 0.9810, 15: 0.9823, 16: 0.9835, 17: 0.9845, 18: 0.9854, 19: 0.9862,
    20: 0.9869, 21: 0.9876, 22: 0.9882, 23: 0.9887, 24: 0.9892, 25: 0.9896,
}


# ---------------------------------------------------------------------------
# Constant accessors — tabulated for n = 2..25, analytic above
#
# The tables above stay authoritative below n = 26. The series form for c4 is a
# poor substitute at small n: it puts c4(2) at 0.8203 vs the tabulated 0.7979
# (+2.8%), which in turn skews A3(2) to 2.586 vs 2.659 (-2.7%) and B4(2) to
# 3.092 vs 3.267 (-5.4%). By n = 25 the two agree to four decimals, so the seam
# is smooth and the series takes over from there (relative error in c4 is
# 8.6e-06 at n = 26, 1.5e-07 at n = 100, below 1e-09 past n = 500).
#
# Do not "simplify" the tables away — small-n charts would move.
# ---------------------------------------------------------------------------

def _tabulated(n: float, table: dict[int, float]) -> float | None:
    """Exact tabulated value when n is a whole number in 2..25, else None."""
    if 2 <= n <= 25 and float(n).is_integer():
        return table[int(n)]
    return None


def c4(n: float) -> float:
    """
    Unbiasing constant: E[s] = c4(n)·σ.  c4 ≈ 1 - 1/(4n) - 7/(32n²).

    NaN for n < 2 — a subgroup of one has no defined standard deviation.
    """
    if not n >= 2:  # also catches NaN
        return math.nan
    hit = _tabulated(n, C4)
    if hit is not None:
        return hit
    return 1.0 - 1.0 / (4.0 * n) - 7.0 / (32.0 * n * n)


def _b_spread(n: float) -> float:
    """3·√(1 − c4²)/c4 — the half-width shared by B3 and B4."""
    c = c4(n)
    if math.isnan(c):
        return math.nan
    return 3.0 * math.sqrt(max(0.0, 1.0 - c * c)) / c


def a3(n: float) -> float:
    """A3 = 3/(c4·√n) for the Xbar chart. NaN for n < 2."""
    hit = _tabulated(n, A3)
    if hit is not None:
        return hit
    c = c4(n)
    return math.nan if math.isnan(c) else 3.0 / (c * math.sqrt(n))


def b3(n: float) -> float:
    """B3 = max(0, 1 − 3√(1 − c4²)/c4) for the S chart. NaN for n < 2."""
    hit = _tabulated(n, B3)
    if hit is not None:
        return hit
    spread = _b_spread(n)
    return math.nan if math.isnan(spread) else max(0.0, 1.0 - spread)


def b4(n: float) -> float:
    """B4 = 1 + 3√(1 − c4²)/c4 for the S chart. NaN for n < 2."""
    hit = _tabulated(n, B4)
    if hit is not None:
        return hit
    spread = _b_spread(n)
    return math.nan if math.isnan(spread) else 1.0 + spread
