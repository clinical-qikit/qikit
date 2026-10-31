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

import functools
import math

import numpy as np

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


def poisson_mean_for_cdf(k: int, p: float) -> float:
    """
    The Poisson mean μ satisfying F(k; μ) = p.

    F(k; μ) is strictly decreasing in μ for fixed k — more expected events means less
    probability of landing at or below k — so the root is unique. Inverting in the
    *mean* rather than searching over ratios is what makes both callers exact: the
    answer is the mean at which the stated probability holds, not a value scanned
    until it looked close.

    Solved by safeguarded Newton steps on log F, bisecting whenever a step would leave
    the bracket [0, k + 10√(k+1) + 20] (F(k; hi) < 1e-10 there, below every p this
    module uses). log F(k; μ) = log f(k; μ) + log S with S = F/f, a sum of running
    products of j/μ that numpy evaluates in one pass, and d log F / dμ = −1/S. Six to
    ten steps replace the fifty full CDF sweeps a plain bisection costs, which is what
    keeps a thousand-provider funnel at hospital volumes (k in the thousands) fast.
    The TypeScript twin (poissonMeanForCdf) bisects; the two agree far inside the
    quantization below.

    The result is quantized to _QUANTIZE_DECIMALS. math.lgamma is a libm function whose
    last ulp differs between platforms, so the unrounded root lands ~1e-13 apart on
    different machines; rounding to 1e-9 erases that while staying four orders of
    magnitude tighter than the fixture check tolerance and seven beyond anything
    displayed. Callers divide this by a bit-identical expected count, and IEEE division
    is exactly rounded, so quantizing here makes every value derived from it portable
    too.

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
    return _poisson_mean_solve(int(k), float(p))


@functools.lru_cache(maxsize=8192)
def _poisson_mean_solve(k: int, p: float) -> float:
    """poisson_mean_for_cdf after validation, memoized: a funnel solves the same few
    (k, p) pairs for many providers (intervals at p = 0.025/0.975, detectability at
    0.2), and the solve is a pure function of them."""
    if k == 0:
        return round(-math.log(p), _QUANTIZE_DECIMALS)  # F(0; μ) = e^(−μ)

    log_p = math.log(p)
    log_k_fact = math.lgamma(k + 1.0)
    steps = np.log(np.arange(k, 0, -1, dtype=float))  # log j for j = k, k−1, …, 1
    logs = np.zeros(k + 1)

    def log_cdf(mu: float) -> tuple[float, float]:
        # Running products (k/μ)(k−1)/μ… are f(k−i)/f(k); summed, S = F(k)/f(k).
        # logs[0] stays 0; the rest is rewritten in place, the same cumsum as before.
        np.cumsum(steps - math.log(mu), out=logs[1:])
        top = float(logs.max())
        log_s = top + math.log(float(np.sum(np.exp(logs - top))))
        return k * math.log(mu) - mu - log_k_fact + log_s, math.exp(log_s)

    lo = 0.0
    hi = k + 10.0 * math.sqrt(k + 1.0) + 20.0
    mu = k + 1.0  # F(k; k + 1) sits near one half: the middle of every bracket used
    for _ in range(_BISECT_ITERS):
        h, s = log_cdf(mu)
        h -= log_p
        if h > 0:
            lo = mu  # still too much mass at or below k — the mean must rise
        else:
            hi = mu
        step = h * s
        nxt = mu + step
        if not (lo < nxt < hi):
            nxt = 0.5 * (lo + hi)
        if abs(nxt - mu) <= 1e-13 * max(1.0, mu):
            mu = nxt
            break
        mu = nxt
    return round(mu, _QUANTIZE_DECIMALS)


def poisson_quantile_interp(p: float, lam: float) -> float:
    """
    Continuity-interpolated Poisson quantile (Spiegelhalter 2005, Appendix A.1.1).

    The raw quantile is the smallest integer r with F(r; λ) ≥ p. Taking r itself
    would make the funnel a staircase — the limit only moves when the integer
    quantile jumps. Spiegelhalter interpolates within the jump:

        δ = (F(r) − p) / (F(r) − F(r−1)),   q = max(0, r − δ)

    so q lies in [r−1, r] and varies smoothly with λ. Note this is *not* what R's
    qpois returns (that is r, uninterpolated); an external cross-check should
    bracket our value between r−1 and r. (limits._upper_boundary draws the upper
    contour one count beyond this, at the exact test's boundary.)

    Built on the lgamma-free walk the other families use (below), so it costs
    O(√λ) terms rather than O(λ) and is bit-identical across platforms. The result is
    quantized to _QUANTIZE_DECIMALS like every quantile here.

    Returns NaN for a non-positive or non-finite λ.
    """
    if not (lam > 0) or math.isnan(lam):
        return math.nan
    if lam > _EXACT_MAX_LAMBDA:
        raise ValueError(
            f"poisson_quantile_interp: lambda={lam} exceeds the exact-method ceiling "
            f"({_EXACT_MAX_LAMBDA}); the caller should fall back to byar_quantile."
        )

    def ratio(k):
        return lam / (k + 1)

    out = _walk_quantiles((p,), ratio, int(math.floor(lam)), None, ("poisson", lam))
    # The walk cannot run out: a Poisson's spread is √λ ≤ 317 terms at the ceiling.
    return out[0]


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
# The Poisson quantile uses the same walk (poisson_quantile_interp, above).

# Terms below this fraction of the largest are dropped. The neglected tail mass is
# below 1e-16 of the total even for the slowest-decaying case reachable here.
_TAIL_EPS = 1e-20

# Safety net against a distribution so wide the walk would not finish, reachable only
# for absurd between-provider variance (a gamma with shape far below 1 at a very large
# mean). The caller then falls back to the normal approximation of [1, eq. 11].
_MAX_TERMS = 100_000


# Walks already taken, by distribution. A funnel point's two contours and its
# p-value all walk the same pmf; caching it walks once. Entries are read-only arrays.
_WALK_CACHE: dict = {}
_WALK_CACHE_MAX = 4096


def _walk_terms(ratio, start, upper, key=None):
    """
    Unnormalised pmf terms of a unimodal distribution given only its term ratio.

    ratio(k) = f(k+1)/f(k), evaluated on a float array of k (every ratio here is
    plain + − × ÷, so the array call rounds exactly as a scalar call would); start is
    a point near the mode; upper is the last support point (None when unbounded).
    Returns (k_lo, terms, total): terms is a float array, terms[j] proportional to
    f(k_lo + j), and total their plain left-to-right sum. None when the walk exceeds
    _MAX_TERMS.

    Vectorised in blocks: the upward walk is a running product and the downward one
    a running quotient (np.multiply/np.divide.accumulate, which are strictly
    sequential), and the stopping rule is the running peak's, so every term, the
    point the walk stops and the total are bit-identical to the scalar loop the
    TypeScript twin keeps (methods §4.5). A walk that ends inside the scalar phase
    returns its terms as a tuple of floats instead. key, when given, names the
    distribution for _WALK_CACHE.
    """
    if key is not None:
        hit = _WALK_CACHE.get(key)
        if hit is not None or key in _WALK_CACHE:
            return hit
        walk = _walk_terms(ratio, start, upper)
        if len(_WALK_CACHE) >= _WALK_CACHE_MAX:
            _WALK_CACHE.clear()
        if walk is not None and isinstance(walk[1], np.ndarray):
            walk[1].flags.writeable = False
        _WALK_CACHE[key] = walk
        return walk
    up = _walk_side(ratio, start, upper, 1, peak=1.0)
    if up is None:
        return None
    up_terms, peak = up
    if len(up_terms) + 1 > _MAX_TERMS:
        return None
    down = _walk_side(ratio, start, 0, -1, peak=peak)
    if down is None:
        return None
    down_terms, _ = down
    if len(down_terms) > _MAX_TERMS:
        return None
    k_lo = start - len(down_terms)
    if isinstance(down_terms, list) and isinstance(up_terms, list):
        # A short walk stays a tuple of floats, summed by plain loops downstream.
        terms = tuple(down_terms[::-1]) + (1.0,) + tuple(up_terms)
        total = 0.0
        for t in terms:
            total += t
        return k_lo, terms, total
    terms = np.concatenate((down_terms[::-1], [1.0], up_terms))
    # np.cumsum accumulates left to right, unlike sum() (compensated from Python 3.12)
    # or np.sum (pairwise), and so matches the TypeScript twin's plain loop.
    total = float(np.cumsum(terms)[-1])
    return k_lo, terms, total


# The first _WALK_SCALAR terms of each side are taken one at a time, which is faster
# than numpy for the short walks of physician-level counts; past that, blocks of
# _WALK_BLOCK (doubling) carry the long walks of hospital volumes. Both phases do the
# same sequential arithmetic, so where the switch falls changes no bit.
_WALK_SCALAR = 64
_WALK_BLOCK = 256


def _walk_side(ratio, start, stop, step, peak):
    """
    One side of _walk_terms: the terms after f(start) = 1 going up (step 1, to stop =
    upper or unbounded) or down (step −1, to 0), and the running peak. Stops before
    the first term below _TAIL_EPS of the peak so far. None past _MAX_TERMS.
    """
    head = []
    u = 1.0
    k = start
    while len(head) < _WALK_SCALAR and (stop is None or (k < stop if step > 0 else k > stop)):
        u = u * ratio(k) if step > 0 else u / ratio(k - 1)
        k += step
        if u > peak:
            peak = u
        if u < _TAIL_EPS * peak:
            return head, peak
        head.append(u)
    if not (stop is None or (k < stop if step > 0 else k > stop)):
        return head, peak
    out = [np.array(head)]
    n_kept = len(head)
    block = _WALK_BLOCK
    while stop is None or (k < stop if step > 0 else k > stop):
        room = block if stop is None else min(block, abs(stop - k))
        if step > 0:
            ks = np.arange(k, k + room, dtype=float)
            vals = np.multiply.accumulate(np.concatenate(([u], ratio(ks))))[1:]
        else:
            ks = np.arange(k - 1, k - 1 - room, -1, dtype=float)
            vals = np.divide.accumulate(np.concatenate(([u], ratio(ks))))[1:]
        peaks = np.maximum.accumulate(np.concatenate(([peak], vals)))[1:]
        low = np.flatnonzero(vals < _TAIL_EPS * peaks)
        if len(low):
            cut = int(low[0])
            out.append(vals[:cut])
            peak = float(peaks[cut])
            break
        out.append(vals)
        n_kept += room
        if n_kept > _MAX_TERMS:
            return None
        peak = float(peaks[-1])
        u = float(vals[-1])
        k += step * room
        block *= 2
    terms = np.concatenate(out)
    if len(terms) > _MAX_TERMS:
        return None
    return terms, peak


def _walk_quantiles(probs, ratio, start, upper, key=None):
    """
    Continuity-interpolated quantiles of a unimodal pmf given only its term ratio.

    Arguments as _walk_terms. Returns one quantile per p in probs, each
    max(0, r − δ) with δ = (F(r) − p)/f(r) exactly as poisson_quantile_interp
    ([1] A.1.1), or None when the walk exceeds _MAX_TERMS.
    """
    walk = _walk_terms(ratio, start, upper, key)
    if walk is None:
        return None
    k_lo, terms, total = walk
    if not isinstance(terms, np.ndarray):
        return _scalar_quantiles(probs, k_lo, terms, total)
    cdf = np.cumsum(terms / total)

    out = []
    for p in probs:
        hit = np.flatnonzero(cdf >= p)
        if not len(hit):
            # p sits in the float plateau at the top of the CDF; the support's last
            # kept point is the answer.
            out.append(float(k_lo + len(terms) - 1))
            continue
        j = int(hit[0])
        prev = float(cdf[j - 1]) if j > 0 else 0.0
        jump = float(cdf[j]) - prev
        delta = (float(cdf[j]) - p) / jump if jump > 0 else 0.0
        out.append(round(max(0.0, k_lo + j - delta), _QUANTIZE_DECIMALS))
    return out


def _scalar_quantiles(probs, k_lo, terms, total):
    """_walk_quantiles on a short walk's tuple of terms, one term at a time."""
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
            out.append(float(k_lo + len(terms) - 1))
            continue
        jump = cdf - prev
        delta = (cdf - p) / jump if jump > 0 else 0.0
        out.append(round(max(0.0, r - delta), _QUANTIZE_DECIMALS))
    return out


def _seq_sum(terms) -> float:
    """Left-to-right sum of a walk's terms (a tuple or an array slice), as stats.ts sums."""
    if isinstance(terms, np.ndarray):
        return float(np.cumsum(terms)[-1]) if len(terms) else 0.0
    total = 0.0
    for t in terms:
        total += t
    return total


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
    out = _walk_quantiles(probs, ratio, start, m, ("binomial", m, theta))
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
    walk = _walk_terms(ratio, start, m, ("binomial", m, theta))
    if walk is None:
        return math.nan
    k_lo, terms, total = walk
    j = min(k - k_lo + 1, len(terms))
    cdf = _seq_sum(terms[:j]) if j > 0 else 0.0
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
    out = _walk_quantiles(probs, ratio, start, None, ("poisson_gamma", lam, size))
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
    out = _walk_quantiles(probs, ratio, start, m, ("beta_binomial", m, alpha, beta))
    if out is None:
        var = m * theta * (1.0 - theta) * (alpha + beta + m) / (alpha + beta + 1.0)
        return _normal_quantiles(probs, m * theta, var, zs), False
    return out, True


# ---------------------------------------------------------------------------
# Tail probabilities, for exact p-values (docs/methods.md §4.11)
# ---------------------------------------------------------------------------
#
# The same lgamma-free walk as the quantiles above, so a p-value is bit-identical
# across platforms and between this file and stats.ts. Each tail is summed directly
# from its own terms, never as 1 − (the other tail): a p-value of 1e-12 taken as a
# complement keeps only four significant digits. Terms dropped by the walk's
# _TAIL_EPS cut sit below 1e-16 of the mass, so a p-value smaller than that reads 0.


def _walk_tails(k, ratio, start, upper, key=None):
    """
    (P(X ≤ k), P(X ≥ k)) for a unimodal pmf given only its term ratio.

    Arguments as _walk_terms, plus the integer k. The lower tail is summed ascending
    from the first kept term and the upper tail descending from the last, so each
    accumulates its smallest terms first; the TypeScript twin must keep that order.
    A k outside the kept support gives (0, 1) below it and (1, 0) above it. None when
    the walk exceeds _MAX_TERMS, for the caller's normal fallback.
    """
    walk = _walk_terms(ratio, start, upper, key)
    if walk is None:
        return None
    k_lo, terms, total = walk
    j = k - k_lo
    last = len(terms) - 1
    if j < 0:
        return 0.0, 1.0
    if j > last:
        return 1.0, 0.0
    lower = _seq_sum(terms[: j + 1])
    upper_sum = _seq_sum(terms[j:][::-1])
    return min(1.0, lower / total), min(1.0, upper_sum / total)


def poisson_tails(k: int, lam: float):
    """
    (P(X ≤ k), P(X ≥ k)) for X ~ Poisson(λ), from the lgamma-free walk.

    It never calls lgamma, so it is bit-identical across platforms. (NaN, NaN) for a
    NaN or non-positive λ, where the limits are NaN too.
    """
    if math.isnan(lam) or not (lam > 0):
        return math.nan, math.nan

    def ratio(j):
        return lam / (j + 1)

    return _walk_tails(int(k), ratio, int(math.floor(lam)), None, ("poisson", lam))


def binomial_tails(k: int, m: int, theta: float):
    """
    (P(X ≤ k), P(X ≥ k)) for X ~ Binomial(m, θ), from the walk binomial_cdf uses.

    θ at 0 or 1 is a point mass at 0 or m, as binomial_quantiles treats it.
    """
    if math.isnan(theta) or not (m > 0):
        return math.nan, math.nan
    k = int(k)
    if theta <= 0.0:
        return 1.0, (1.0 if k <= 0 else 0.0)
    if theta >= 1.0:
        return (1.0 if k >= m else 0.0), (1.0 if k <= m else 0.0)
    odds = theta / (1.0 - theta)

    def ratio(j):
        return (m - j) / (j + 1) * odds

    start = min(m, int(math.floor((m + 1) * theta)))
    return _walk_tails(k, ratio, start, m, ("binomial", m, theta))


def poisson_gamma_tails(k: int, lam: float, size: float):
    """
    (P(X ≤ k), P(X ≥ k)) for the Poisson–gamma count of poisson_gamma_quantiles:
    mean λ, size r, variance λ + λ²/r.
    """
    if math.isnan(lam) or not (lam > 0) or not (size > 0):
        return math.nan, math.nan
    q = lam / (size + lam)

    def ratio(j):
        return (j + size) / (j + 1) * q

    start = int(math.floor((size - 1.0) * lam / size)) if size > 1.0 else 0
    return _walk_tails(int(k), ratio, start, None, ("poisson_gamma", lam, size))


def beta_binomial_tails(k: int, m: int, alpha: float, beta: float):
    """
    (P(X ≤ k), P(X ≥ k)) for the beta-binomial count of beta_binomial_quantiles:
    Binomial(m, θ) with θ ~ Beta(α, β).
    """
    if not (m > 0) or not (alpha > 0) or not (beta > 0):
        return math.nan, math.nan
    theta = alpha / (alpha + beta)

    def ratio(j):
        return (m - j) * (alpha + j) / ((j + 1) * (beta + m - j - 1))

    start = min(m, int(math.floor(m * theta)))
    return _walk_tails(int(k), ratio, start, m, ("beta_binomial", m, alpha, beta))


# ---------------------------------------------------------------------------
# Posterior tails for funnel()'s prob_worse (docs/methods.md §4.14)
# ---------------------------------------------------------------------------
#
# The shrunk estimate's posterior is a gamma (counts) or a beta (proportions) with real
# parameters, so its tail is a regularized incomplete gamma or beta function. Both are
# the standard series / continued-fraction pair (Numerical Recipes §6.2, §6.4) on
# lgamma, accurate to ~1e-14 relative and used only for a reported probability, never
# for a limit or a signal, so the lgamma platform noise that the funnel's own walk
# avoids does not matter here.

_INC_EPS = 1e-15
_INC_MAX_ITER = 100_000
_INC_TINY = 1e-300


def _gamma_series(a: float, x: float) -> float:
    """Regularized lower incomplete gamma P(a, x) by its series, for x < a + 1."""
    term = total = 1.0 / a
    ap = a
    for _ in range(_INC_MAX_ITER):
        ap += 1.0
        term *= x / ap
        total += term
        if abs(term) < abs(total) * _INC_EPS:
            break
    return total * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gamma_cf(a: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(a, x) by Lentz's continued fraction."""
    b = x + 1.0 - a
    c = 1.0 / _INC_TINY
    d = 1.0 / b
    h = d
    for i in range(1, _INC_MAX_ITER):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        d = _INC_TINY if abs(d) < _INC_TINY else d
        c = b + an / c
        c = _INC_TINY if abs(c) < _INC_TINY else c
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _INC_EPS:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def gamma_tails(a: float, x: float) -> tuple[float, float]:
    """
    (P(X ≤ x), P(X > x)) for X ~ Gamma(shape a, rate 1): the regularized incomplete
    gamma pair P(a, x), Q(a, x), each computed directly rather than as 1 minus the
    other. For a rate β pass x·β. NaN for a ≤ 0 or a NaN argument.
    """
    if not (a > 0) or math.isnan(x):
        return math.nan, math.nan
    if x <= 0:
        return 0.0, 1.0
    if x < a + 1.0:
        p = _gamma_series(a, x)
        return p, 1.0 - p if p < 0.5 else _gamma_cf(a, x)
    q = _gamma_cf(a, x)
    return (1.0 - q if q < 0.5 else _gamma_series(a, x)), q


def _beta_cf(a: float, b: float, x: float) -> float:
    """The continued fraction of the regularized incomplete beta (Lentz)."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    d = _INC_TINY if abs(d) < _INC_TINY else d
    d = 1.0 / d
    h = d
    for m in range(1, _INC_MAX_ITER):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = _INC_TINY if abs(d) < _INC_TINY else d
        c = 1.0 + aa / c
        c = _INC_TINY if abs(c) < _INC_TINY else c
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = _INC_TINY if abs(d) < _INC_TINY else d
        c = 1.0 + aa / c
        c = _INC_TINY if abs(c) < _INC_TINY else c
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _INC_EPS:
            break
    return h


def beta_tails(x: float, a: float, b: float) -> tuple[float, float]:
    """
    (P(X ≤ x), P(X > x)) for X ~ Beta(a, b): the regularized incomplete beta I_x(a, b)
    and its complement, the smaller of the two always taken from its own continued
    fraction. NaN for non-positive parameters or a NaN argument.
    """
    if not (a > 0) or not (b > 0) or math.isnan(x):
        return math.nan, math.nan
    if x <= 0:
        return 0.0, 1.0
    if x >= 1:
        return 1.0, 0.0
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        lower = front * _beta_cf(a, b, x) / a
        return lower, 1.0 - lower if lower < 0.5 else front * _beta_cf(b, a, 1.0 - x) / b
    upper = front * _beta_cf(b, a, 1.0 - x) / b
    return (1.0 - upper if upper < 0.5 else front * _beta_cf(a, b, x) / a), upper
