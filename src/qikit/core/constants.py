"""
constants.py — SPC constants and normal deviates.

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
# SPC constants (Montgomery 2019, Appendix VI). d2 and D4 for moving ranges of two are
# the published values qicharts2 also uses; c4 and the constants built from it are
# computed exactly below.
# ---------------------------------------------------------------------------

D2 = {2: 1.128}
D4 = {2: 3.267}



def c4(n: float) -> float:
    """
    Unbiasing constant, E[s] = c4(n)·σ: c4 = √(2/(n − 1))·Γ(n/2)/Γ((n − 1)/2), exactly, as
    qicharts2 computes it (the textbook tables are this value rounded). Defined for
    non-integer n too; NaN for n < 2, where a subgroup has no standard deviation.
    """
    if not n >= 2:  # also catches NaN
        return math.nan
    return math.sqrt(2.0 / (n - 1.0)) * math.exp(math.lgamma(n / 2.0) - math.lgamma((n - 1.0) / 2.0))


def _b_spread(n: float) -> float:
    """3·√(1 − c4²)/c4, the half-width shared by B3 and B4."""
    c = c4(n)
    return math.nan if math.isnan(c) else 3.0 * math.sqrt(max(0.0, 1.0 - c * c)) / c


def a3(n: float) -> float:
    """A3 = 3/(c4·√n) for the X̄ chart. NaN for n < 2."""
    c = c4(n)
    return math.nan if math.isnan(c) else 3.0 / (c * math.sqrt(n))


def b3(n: float) -> float:
    """B3 = max(0, 1 − 3√(1 − c4²)/c4) for the S chart. NaN for n < 2."""
    spread = _b_spread(n)
    return math.nan if math.isnan(spread) else max(0.0, 1.0 - spread)


def b4(n: float) -> float:
    """B4 = 1 + 3√(1 − c4²)/c4 for the S chart. NaN for n < 2."""
    spread = _b_spread(n)
    return math.nan if math.isnan(spread) else 1.0 + spread
