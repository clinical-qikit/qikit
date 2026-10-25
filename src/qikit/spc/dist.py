"""
dist.py — exact quantile helpers for funnel limits.

Pure Python + numpy, no scipy: the same constraint that makes signals.py compute
its crossings threshold from math.comb rather than a binomial CDF library. Every
function has a line-for-line twin in the TypeScript engine (engine/src/stats.ts),
so the shared fixtures reproduce on either language — keep the two in step, and in
particular keep each summation in the same order so the float error matches.

Numbered references are those of docs/methods.md, which records why each method
was chosen and where it departs from the source.

References
----------
[1] Spiegelhalter DJ. Funnel plots for comparing institutional performance.
    Statistics in Medicine 2005;24(8):1185-1202. (Appendix A.1.1, A.2.1)
[4] Breslow NE, Day NE. Statistical Methods in Cancer Research, Vol II. IARC, 1987.
    (Byar's approximation, via the Wilson-Hilferty transform.)
[5] Garwood F. Fiducial limits for the Poisson distribution. Biometrika 1936;28:437-442.
    (The exact interval this module's mean-inversion produces.)
[7] Clayton D, Kaldor J. Empirical Bayes estimates of age-standardized relative risks
    for use in disease mapping. Biometrics 1987;43:671-681. (The Poisson–gamma model.)
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

# Grid every lgamma-derived result is quantized to.
#
# math.lgamma is a libm function whose last ulp differs between platforms (macOS/arm64
# vs linux/x86_64 disagree around the 14th significant digit). Both routines below
# accumulate many lgamma terms, so both inherit that: the quantile lands ~1e-13 away
# and the bisection, which can flip a comparison near a decision boundary and take a
# different path, lands ~1e-13 away too. The committed fixture snapshots require byte
# equality, so unrounded results reproduce only on the machine that generated them.
#
# 1e-9 is four orders of magnitude tighter than the fixture check tolerances and seven
# beyond anything displayed, while sitting far above the noise it erases. Callers
# divide these by bit-identical denominators and IEEE division is exactly rounded, so
# quantizing at the source makes every derived column portable too.
_QUANTIZE_DECIMALS = 9


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

    The result is quantized to _QUANTIZE_DECIMALS. math.lgamma is a libm function whose
    last ulp differs between platforms, and bisection amplifies that: a 1-ulp
    difference in the CDF near a decision boundary flips a comparison, sends the
    bracket down a different path, and lands ~1e-13 away. The committed fixture
    snapshots require byte equality, so an unrounded result makes them reproduce only
    on the machine that generated them. Rounding to 1e-9 is four orders of magnitude
    tighter than the fixture check tolerance and seven beyond anything displayed,
    while sitting far above the platform noise it erases. Callers divide this by a
    bit-identical expected count, and IEEE division is exactly rounded, so quantizing
    here makes every value derived from it portable too.

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
    return round(0.5 * (lo + hi), _QUANTIZE_DECIMALS)


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

    The result is quantized to _QUANTIZE_DECIMALS, for the reason given there: the
    accumulated lgamma terms differ in their last ulp between platforms, and the
    fixture snapshots are compared byte for byte.

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
    return round(max(0.0, k - delta), _QUANTIZE_DECIMALS)


# ---------------------------------------------------------------------------
# Binomial, Poisson–gamma and beta-binomial quantiles
# ---------------------------------------------------------------------------
#
# These three serve the p funnel (binomial, [1] A.1.1) and the over-dispersed funnels,
# whose additive random-effects model [1, eq. 11] has an exact counterpart: true
# provider rates drawn from a gamma (counts) or beta (proportions) distribution with
# the estimated between-provider variance τ². See docs/methods.md, "Adjusted limits".
#
# Unlike poisson_quantile_interp they never call lgamma. Each pmf is built from its
# term ratio f(k+1)/f(k) outward from the mode, starting at 1 and normalised at the
# end. That has three properties worth keeping:
#   - only + − × ÷, which IEEE rounds exactly, so the result is bit-identical across
#     platforms and between this file and stats.ts (no libm last-ulp trap);
#   - no catastrophic cancellation as τ² → 0, where the mixing parameter r or α+β
#     grows without bound and a difference of lgammas loses every digit;
#   - cost proportional to the distribution's spread, not to its mean, so a hospital
#     with 100,000 discharges costs a few thousand terms, not a hundred thousand.
# Poisson keeps its original loop so every existing O/E fixture is untouched.

# Terms below this fraction of the largest are dropped. The neglected tail mass is
# below 1e-16 of the total even for the slowest-decaying case reachable here.
_TAIL_EPS = 1e-20

# Safety net against a distribution so wide the walk would not finish, reachable only
# for absurd between-provider variance (a gamma with shape far below 1 at a very large
# mean). The caller then falls back to the normal approximation of [1, eq. 11].
_MAX_TERMS = 100_000


def _walk_terms(ratio, start, upper):
    """
    Unnormalised pmf terms of a unimodal distribution given only its term ratio.

    ratio(k) = f(k+1)/f(k); start is a point near the mode; upper is the last
    support point (None when unbounded). Returns (k_lo, terms, total): terms[j] is
    proportional to f(k_lo + j), and total is their plain left-to-right sum. None
    when the walk exceeds _MAX_TERMS.
    """
    # Upward from start, then downward; terms are relative to f(start) = 1.
    up = [1.0]
    peak = 1.0
    u = 1.0
    k = start
    while upper is None or k < upper:
        u = u * ratio(k)
        k += 1
        if u > peak:
            peak = u
        if u < _TAIL_EPS * peak:
            break
        up.append(u)
        if len(up) > _MAX_TERMS:
            return None
    down = []
    u = 1.0
    k = start
    while k > 0:
        u = u / ratio(k - 1)
        k -= 1
        if u > peak:
            peak = u
        if u < _TAIL_EPS * peak:
            break
        down.append(u)
        if len(down) > _MAX_TERMS:
            return None

    terms = down[::-1] + up
    k_lo = start - len(down)
    # Plain left-to-right accumulation, not sum(): from Python 3.12 the builtin uses
    # compensated summation, which the TypeScript twin does not.
    total = 0.0
    for t in terms:
        total += t
    return k_lo, terms, total


def _walk_quantiles(probs, ratio, start, upper):
    """
    Continuity-interpolated quantiles of a unimodal pmf given only its term ratio.

    Arguments as _walk_terms. Returns one quantile per p in probs, each
    max(0, r − δ) with δ = (F(r) − p)/f(r) exactly as poisson_quantile_interp
    ([1] A.1.1), or None when the walk exceeds _MAX_TERMS.
    """
    walk = _walk_terms(ratio, start, upper)
    if walk is None:
        return None
    k_lo, terms, total = walk

    out = []
    for p in probs:
        cdf = 0.0
        prev = 0.0
        r = k_lo
        for t in terms:
            prev = cdf
            cdf += t / total
            if cdf >= p:
                break
            r += 1
        else:
            # p sits in the float plateau at the top of the CDF; the support's last
            # kept point is the answer.
            out.append(float(k_lo + len(terms) - 1))
            continue
        jump = cdf - prev
        delta = (cdf - p) / jump if jump > 0 else 0.0
        out.append(round(max(0.0, r - delta), _QUANTIZE_DECIMALS))
    return out


def _normal_quantiles(probs, mean, var, zs):
    """[1] eq. 3 / eq. 11 on the count scale, for the fallbacks above."""
    sd = math.sqrt(var)
    return [max(0.0, mean + z * sd) for z in zs]


def binomial_quantiles(probs, n, theta, zs):
    """
    Continuity-interpolated Binomial(n, θ) quantiles on the count scale, [1] A.1.1.

    Returns (quantiles, exact). zs are the normal deviates matching probs, used only
    by the fallback, which reports exact=False: a non-integer n (an averaged or
    weighted denominator, which no binomial describes) and the _MAX_TERMS safety net
    both take the normal approximation of [1] eq. 3.
    """
    if not (n > 0) or math.isnan(n) or math.isnan(theta):
        return [math.nan] * len(probs), True
    if theta <= 0.0:
        return [0.0] * len(probs), True
    if theta >= 1.0:
        return [float(n)] * len(probs), True
    if abs(n - round(n)) > 1e-9 * max(1.0, n):
        return _normal_quantiles(probs, n * theta, n * theta * (1.0 - theta), zs), False
    m = int(round(n))
    odds = theta / (1.0 - theta)

    def ratio(k):
        return (m - k) / (k + 1) * odds

    start = min(m, int(math.floor((m + 1) * theta)))
    out = _walk_quantiles(probs, ratio, start, m)
    if out is None:
        return _normal_quantiles(probs, m * theta, m * theta * (1.0 - theta), zs), False
    return out, True


def binomial_cdf(k: int, m: int, theta: float) -> float:
    """
    Binomial CDF F(k; m, θ) = P(X ≤ k), from the same lgamma-free walk as
    binomial_quantiles.

    The terms are normalised by their own total, so (1 − θ)^m, which underflows
    for any denominator a hospital produces, is never formed. Terms dropped by the
    walk's _TAIL_EPS cut sit below 1e-16 of the mass, so a k beyond the kept support
    returns 0 or 1. NaN when the walk exceeds _MAX_TERMS.
    """
    if math.isnan(theta) or not (0.0 <= theta <= 1.0):
        return math.nan
    if k < 0:
        return 0.0
    if k >= m or theta <= 0.0:
        return 1.0
    if theta >= 1.0:
        return 0.0
    odds = theta / (1.0 - theta)

    def ratio(j):
        return (m - j) / (j + 1) * odds

    start = min(m, int(math.floor((m + 1) * theta)))
    walk = _walk_terms(ratio, start, m)
    if walk is None:
        return math.nan
    k_lo, terms, total = walk
    cdf = 0.0
    for j in range(min(k - k_lo + 1, len(terms))):
        cdf += terms[j]
    return min(1.0, cdf / total)


def binomial_theta_for_cdf(k: int, m: int, p: float) -> float:
    """
    The success probability θ satisfying F(k; m, θ) = p, found by bisection.

    The binomial twin of poisson_mean_for_cdf, and exact in the same sense: F(k; m, θ)
    is strictly decreasing in θ for 0 ≤ k < m, so the root in [0, 1] is unique.
    Bisection runs _BISECT_ITERS halvings of [0, 1], resolving θ to ~1e-15.

    No quantizing, unlike poisson_mean_for_cdf: binomial_cdf uses only + − × ÷,
    which IEEE rounds exactly, so every comparison and therefore the whole bisection
    path is identical across platforms and between this file and stats.ts.

    NaN outside 0 ≤ k < m or for p outside (0, 1); at k ≥ m no θ moves the CDF off 1.
    """
    if math.isnan(p) or not (0.0 < p < 1.0) or k < 0 or k >= m:
        return math.nan
    lo = 0.0
    hi = 1.0
    for _ in range(_BISECT_ITERS):
        mid = 0.5 * (lo + hi)
        if binomial_cdf(k, m, mid) > p:
            lo = mid  # still too much mass at or below k — θ must rise
        else:
            hi = mid
    return 0.5 * (lo + hi)


def poisson_gamma_quantiles(probs, lam, size, zs):
    """
    Continuity-interpolated Poisson–gamma (negative binomial) quantiles [7].

    The count is Poisson(θᵢE) with θᵢ ~ Gamma(mean θ₀, variance τ²), so with
    λ = θ₀E and size r = θ₀²/τ² it has mean λ and variance λ + λ²/r: on the ratio
    scale θ₀/E + τ², exactly the variance of [1] eq. 11. size = inf is the plain
    Poisson, which callers route to poisson_quantile_interp instead. Returns
    (quantiles, exact), as binomial_quantiles does.
    """
    if not (lam > 0) or math.isnan(lam) or not (size > 0):
        return [math.nan] * len(probs), True
    q = lam / (size + lam)

    def ratio(k):
        return (k + size) / (k + 1) * q

    start = int(math.floor((size - 1.0) * lam / size)) if size > 1.0 else 0
    out = _walk_quantiles(probs, ratio, start, None)
    if out is None:
        return _normal_quantiles(probs, lam, lam + lam * lam / size, zs), False
    return out, True


def beta_binomial_quantiles(probs, n, alpha, beta, zs):
    """
    Continuity-interpolated beta-binomial quantiles on the count scale.

    The count is Binomial(n, θᵢ) with θᵢ ~ Beta(α, β); α = θ₀s, β = (1 − θ₀)s and
    s = θ₀(1 − θ₀)/τ² − 1 give the beta mean θ₀ and variance τ², so the proportion
    has variance θ₀(1 − θ₀)/n + τ²(n − 1)/n — [1] eq. 11 up to the (n − 1)/n on τ².
    Returns (quantiles, exact); a non-integer n takes the normal approximation.
    """
    if not (n > 0) or math.isnan(n) or not (alpha > 0) or not (beta > 0):
        return [math.nan] * len(probs), True
    m = int(round(n))
    theta = alpha / (alpha + beta)
    if abs(n - m) > 1e-9 * max(1.0, n):
        var = n * theta * (1.0 - theta) * (alpha + beta + n) / (alpha + beta + 1.0)
        return _normal_quantiles(probs, n * theta, var, zs), False

    def ratio(k):
        return (m - k) * (alpha + k) / ((k + 1) * (beta + m - k - 1))

    start = min(m, int(math.floor(m * theta)))
    out = _walk_quantiles(probs, ratio, start, m)
    if out is None:
        var = m * theta * (1.0 - theta) * (alpha + beta + m) / (alpha + beta + 1.0)
        return _normal_quantiles(probs, m * theta, var, zs), False
    return out, True
