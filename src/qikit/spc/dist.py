"""
dist.py — Poisson quantile helpers for O/E (SMR) funnel limits.

Pure Python + numpy, no scipy: the same constraint that makes signals.py compute
its crossings threshold from math.comb rather than a binomial CDF library. Both
functions have line-for-line twins in the TypeScript engine (engine/src/stats.ts),
so the shared fixtures reproduce on either language — keep the two in step, and in
particular keep the CDF summation ascending in k so the float error matches.

References
----------
1. Spiegelhalter DJ. Funnel plots for comparing institutional performance.
   Statistics in Medicine 2005;24(8):1185-1202. (Appendix A.1.1)
2. Breslow NE, Day NE. Statistical Methods in Cancer Research, Vol II. IARC, 1987.
   (Byar's approximation, via the Wilson-Hilferty transform.)
"""

from __future__ import annotations

import math

# Above this mean the exact loop stops earning its cost: Byar agrees with the
# exact quantile to better than 1e-4 relative by λ = 1e5, and the loop would be
# running ~1e5 iterations per point to prove it.
_EXACT_MAX_LAMBDA = 1e5


def byar_quantile(lam: float, z: float, upper: bool) -> float:
    """
    Byar's approximation to a Poisson quantile at normal deviate z.

    q = λ·(1 − 1/(9λ) ± z/(3√λ))³, the Wilson-Hilferty cube-root transform. The
    lower cube root is floored at 0 — for small λ the bracket goes negative, and
    cubing a negative would give a limit below zero rather than at it.
    """
    if not (lam > 0) or math.isnan(lam):  # also catches NaN
        return math.nan
    root = 1.0 - 1.0 / (9.0 * lam)
    half = z / (3.0 * math.sqrt(lam))
    if upper:
        return lam * (root + half) ** 3
    return lam * max(0.0, root - half) ** 3


def poisson_quantile_interp(p: float, lam: float) -> float:
    """
    Continuity-interpolated Poisson quantile (Spiegelhalter 2005, Appendix A.1.1).

    The raw quantile is the smallest integer r with F(r; λ) ≥ p. Taking r itself
    would make the funnel a staircase — the limit only moves when the integer
    quantile jumps. Spiegelhalter interpolates within the jump:

        δ = (F(r) − p) / (F(r) − F(r−1)),   q = max(0, r − δ)

    so q lies in [r−1, r] and varies smoothly with λ. Note this is *not* what R's
    qpois returns (that is r, uninterpolated); an external cross-check should
    bracket our value between r−1 and r.

    Returns NaN for a non-positive or non-finite λ.
    """
    if not (lam > 0) or math.isnan(lam):
        return math.nan
    if lam > _EXACT_MAX_LAMBDA:
        # z is unused by the caller here, so recover it from p via the two levels
        # we actually ship. Guarded by the callers in limits.py, which only ever
        # pass the four tail probabilities below.
        raise ValueError(
            f"poisson_quantile_interp: λ={lam} exceeds the exact-method ceiling "
            f"({_EXACT_MAX_LAMBDA}); the caller should fall back to byar_quantile."
        )

    log_lam = math.log(lam)
    # Far enough above the mode that the remaining mass is below double precision.
    max_k = int(lam + 20.0 * math.sqrt(lam) + 100.0)

    cdf = 0.0
    prev = 0.0
    k = 0
    while k <= max_k:
        prev = cdf
        cdf += math.exp(k * log_lam - lam - math.lgamma(k + 1.0))
        if cdf >= p:
            break
        k += 1

    if k > max_k:
        # p sits in the float plateau at the top of the CDF; the cap is the answer.
        return float(max_k)

    jump = cdf - prev
    delta = (cdf - p) / jump if jump > 0 else 0.0
    return max(0.0, k - delta)
