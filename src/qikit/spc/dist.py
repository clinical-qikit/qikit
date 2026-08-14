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
3. Garwood F. Fiducial limits for the Poisson distribution. Biometrika 1936;28:437-442.
   (The exact interval this module's mean-inversion produces.)
"""

from __future__ import annotations

import math

# Above this mean the exact loop stops earning its cost: Byar agrees with the
# exact quantile to better than 1e-4 relative by λ = 1e5, and the loop would be
# running ~1e5 iterations per point to prove it.
_EXACT_MAX_LAMBDA = 1e5

# Ceiling for the mean-inversion solves. Distinct from _EXACT_MAX_LAMBDA because
# bisection multiplies the sweep cost by its iteration count: a solve at k = 1e5
# would run 50 sweeps of 1e5 terms. At k = 1e4 the closed-form alternatives are
# already within ~3e-5 relative, which is below anything we display.
_MEAN_SOLVE_MAX_K = 1e4

# Bisection iterations. Fixed rather than tolerance-based so the two language ports
# perform an identical sequence of operations; 50 halvings of a bracket under 2e4
# resolves to ~1e-11.
_BISECT_ITERS = 50


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


def poisson_cdf(k: int, lam: float) -> float:
    """
    Poisson CDF F(k; λ) = P(X ≤ k), summed ascending in k.

    Same term expression as poisson_quantile_interp's loop — kept textually parallel
    so the two stay in step across the Python/TypeScript port.
    """
    if math.isnan(lam) or lam < 0:
        return math.nan
    if k < 0:
        return 0.0
    if lam == 0:
        return 1.0  # all mass at zero

    log_lam = math.log(lam)
    cdf = 0.0
    for j in range(int(k) + 1):
        cdf += math.exp(j * log_lam - lam - math.lgamma(j + 1.0))
    return min(1.0, cdf)


def poisson_mean_for_cdf(k: int, p: float) -> float:
    """
    The Poisson mean μ satisfying F(k; μ) = p, found by bisection.

    F(k; μ) is strictly decreasing in μ for fixed k — more expected events means less
    probability of landing at or below k — so the root is unique and bisection cannot
    be fooled. Inverting in the *mean* rather than searching over ratios is what makes
    both callers exact: the answer is the mean at which the stated probability holds,
    not a value scanned until it looked close.

    The bracket [0, k + 10√(k+1) + 20] holds the root for every p this module uses:
    F(k; hi) < 1e-10 at that upper end, well below the smallest p (0.025).

    Raises ValueError above _MEAN_SOLVE_MAX_K; callers pre-check and fall back to a
    closed form, mirroring how _EXACT_MAX_LAMBDA is handled.
    """
    if math.isnan(p) or not (0.0 < p < 1.0):
        return math.nan
    if k < 0:
        return math.nan
    if k > _MEAN_SOLVE_MAX_K:
        raise ValueError(
            f"poisson_mean_for_cdf: k={k} exceeds the solve ceiling "
            f"({_MEAN_SOLVE_MAX_K}); the caller should use a closed-form approximation."
        )

    lo = 0.0
    hi = k + 10.0 * math.sqrt(k + 1.0) + 20.0
    for _ in range(_BISECT_ITERS):
        mid = 0.5 * (lo + hi)
        if poisson_cdf(k, mid) > p:
            lo = mid  # still too much mass at or below k — the mean must rise
        else:
            hi = mid
    return 0.5 * (lo + hi)


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
