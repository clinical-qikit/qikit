"""
contours.py — a funnel's probability contours at any denominator.

Every funnel draws two contours, 99.8% and 95% by default, from the count model its
measure implies: exact binomial or Poisson quantiles with Spiegelhalter's continuity
interpolation [1, A.1.1, A.2.1], the exact Poisson–gamma or beta-binomial quantiles of
the additive random-effects model when τ² > 0 [1, eq. 11; 7], or, for the CQC and SHMI
methods, the normal contours of a transformed scale [13]. The upper exact contour sits
one count further out, at the exact test's boundary, so a point is beyond a line
exactly when its p-value is below that line's tail probability (methods §4.1).

The numbered references are those of docs/methods.md, which records every design choice
made here and each place it departs from the source.

[1]  Spiegelhalter DJ. Funnel plots for comparing institutional performance. Stat Med
     2005;24(8):1185-1202.
[4]  Breslow NE, Day NE. Statistical Methods in Cancer Research, Vol II. IARC, 1987 (Byar).
[7]  Clayton D, Kaldor J. Empirical Bayes estimates of age-standardized relative risks
     for use in disease mapping. Biometrics 1987;43:671-681.
[13] Mainey C. FunnelPlotR (R package).
[16] Korn EL, Graubard BI. Confidence intervals for proportions with small expected
     number of positive counts estimated from survey data. Surv Methodol 1998;24:193-201.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import NormalDist

import numpy as np

from .constants import Z_95, Z_998
from .dist import (
    _BISECT_ITERS,
    _EXACT_MAX_LAMBDA,
    _walk_terms,
    beta_binomial_quantiles,
    binomial_quantiles,
    byar_quantile,
    poisson_gamma_quantiles,
    poisson_quantile_interp,
)

# The two contours every funnel draws [1, §2]: (lower tail, upper tail, normal deviate).
# The outer pair decides outliers, the inner one alerts; funnel(limits=) can move them.
_OUTER = (0.001, 0.999, Z_998)
_INNER = (0.025, 0.975, Z_95)
DEFAULT_LEVELS = (0.998, 0.95)


def contour(coverage: float) -> tuple[float, float, float]:
    """
    (lower tail, upper tail, normal deviate) of a two-sided contour with this coverage:
    0.998 is the 99.8% contour, 0.1% in each tail. The two defaults return the exact
    constants above, so the shared fixtures see the same bits whatever the call path.
    """
    if coverage == 0.998:
        return _OUTER
    if coverage == 0.95:
        return _INNER
    if not (0.5 < coverage < 1.0):
        raise ValueError(f"A funnel contour's coverage must lie in (0.5, 1), got {coverage!r}.")
    tail = (1.0 - coverage) / 2.0
    return tail, 1.0 - tail, NormalDist().inv_cdf(1.0 - tail)


def _upper_boundary(q: float, exact: bool, n: float | None = None) -> float:
    """
    The upper contour on the count scale: the exact one-sided test's boundary.

    q is the continuity-interpolated quantile r − δ of [1, A.1.1], and for an integer
    count O > q holds exactly when P(X > O) < α. The exact test, and the p-value every
    funnel reports, asks for P(X ≥ O) < α, which is one count further out. Drawing the
    contour at q + 1 makes "beyond the line" and "p < α" the same statement on both
    sides (the lower contour already is), and it makes the upper contour monotone in
    volume on the ratio scale: its slope there is proportional to (1 − δ)(λ − r − 1),
    never positive. docs/methods.md §4.1 records this as a departure from the drawn
    contour of [1]; the model and levels are unchanged.

    A normal fallback (exact False) has no discrete count to step past and is left as
    it is, matching its normal p-value. n caps a binomial count at its denominator.
    """
    if not exact or math.isnan(q):
        return q
    q += 1.0
    return q if n is None else min(q, float(n))


def _poisson_funnel_pair(
    cl: float, n: np.ndarray | None, p_lower: float, p_upper: float,
    z: float, limit_method: str, diag: dict | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Poisson funnel limits at one probability contour, on the rate (or O/E) scale.

    With nᵢ the denominator and θ₀ the center line, the count of events is modeled
    Poisson(λᵢ = θ₀·nᵢ); the limit is that distribution's quantile divided back
    through nᵢ [1, A.2.1]. For an O/E chart nᵢ is the expected events Eᵢ; for a u
    funnel it is the exposure, which [1, A.2.3] treats the same way. Dividing by nᵢ is
    what makes the funnel narrow as volume grows while the count distribution widens.

    Unlike the p/u charts these limits are asymmetric about the center line, which is
    the whole point at low volume: a physician with 3 expected deaths has a very
    different amount of room above the line than below it, and the normal
    approximation would give them the same and then clip the lower limit at zero.

    Above λ = _EXACT_MAX_LAMBDA expected events, Byar's approximation stands in [4]; it
    agrees with the exact quantile to 1e-4 relative there, and diag["byar"] records it so
    the p-values follow the same model.
    """
    e = np.asarray(n, dtype=float)
    e = np.where(e > 0, e, np.nan)
    lam = cl * e

    ucl = np.empty(len(e), dtype=float)
    lcl = np.empty(len(e), dtype=float)
    exact = limit_method != "byar"
    for i, lam_i in enumerate(lam):
        if exact and lam_i <= _EXACT_MAX_LAMBDA:
            ucl[i] = poisson_quantile_interp(p_upper, lam_i) + 1.0
            lcl[i] = poisson_quantile_interp(p_lower, lam_i)
        else:
            ucl[i] = byar_quantile(lam_i, z, upper=True)
            lcl[i] = byar_quantile(lam_i, z, upper=False)
            if exact and diag is not None and lam_i > _EXACT_MAX_LAMBDA:
                diag["byar"] = True

    return ucl / e, lcl / e


def _binomial_funnel_pair(
    cl: float, n: np.ndarray | None, p_lower: float, p_upper: float, z: float,
    diag: dict | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Exact binomial funnel limits at one contour, on the proportion scale [1, A.1.1].

    Asymmetric about the center line, as the Poisson pair is, and for the same reason:
    a physician with 30 patients at a 10% event rate has room for 9 events above
    expected but only 3 below. A non-integer denominator (ν = n/φ under
    within_dispersion) is interpolated between its whole neighbors
    (fractional_binomial_pair).
    """
    e = np.asarray(n, dtype=float)
    ucl = np.full(len(e), np.nan)
    lcl = np.full(len(e), np.nan)
    for i, ni in enumerate(e):
        if not (ni > 0):
            continue
        if _integer_count(float(ni)) is None:
            pair = fractional_binomial_pair(cl, float(ni), 0.0, p_lower, p_upper)
            if not math.isnan(pair[0]):
                ucl[i], lcl[i] = pair
                if diag is not None:
                    diag["interpolated"] = True
                continue
        (lo, hi), exact = binomial_quantiles((p_lower, p_upper), float(ni), cl, (-z, z))
        if not exact and diag is not None:
            diag["normal"] = True
        ucl[i], lcl[i] = _upper_boundary(hi, exact, ni) / ni, lo / ni
    return ucl, lcl



def _integer_count(x: float) -> int | None:
    """x as an int when it is one to within float noise, else None."""
    r = round(x)
    return int(r) if abs(x - r) <= 1e-9 * max(1.0, abs(x)) else None


def gamma_size(cl: float, tau2: float) -> float:
    """
    Size r of the gamma mixing distribution behind the adjusted count funnels: true
    rates (or O/E) with mean θ₀ and variance τ² give r = θ₀²/τ². Shared by the limits
    and the p-values (pvalues.py), so the two always describe one model.
    """
    return cl * cl / tau2


def beta_params(cl: float, tau2: float) -> tuple[float, float] | None:
    """
    (α, β) of the beta mixing distribution behind the adjusted proportion funnels:
    mean θ₀ and variance τ² give α + β = s = θ₀(1 − θ₀)/τ² − 1. None when s ≤ 0, where
    no beta distribution has that mean and variance and both the limits and the
    p-values fall back to [1, eq. 11]'s normal model.
    """
    s = cl * (1.0 - cl) / tau2 - 1.0
    if not (s > 0):
        return None
    return cl * s, (1.0 - cl) * s


# ---------------------------------------------------------------------------
# Fractional binomial denominators (docs/methods.md §4.13)
# ---------------------------------------------------------------------------
#
# Under within_dispersion=φ a proportion's model sees ν = n/φ effective cases, which is
# rarely a whole number, and no binomial has a fractional size. Each quantity below is
# interpolated linearly in ν between the whole neighbors m₀ = ⌊ν⌋ and m₁ = m₀ + 1, at
# the same proportion p:
#
#     T(p; ν) = (1 − w)·T_m₀(p·m₀) + w·T_m₁(p·m₁),   w = ν − m₀,
#
# each T_m being the exact tail at a whole m, itself interpolated between whole counts
# as every funnel p-value is (§4.11). The contours are this test's boundaries, found by
# bisection, so "beyond the line" and "p < α" stay one statement; at w = 0 everything
# is the exact tail. The same holds for the binomial and the beta-binomial, so τ̂ = 0
# still reproduces the unadjusted chart to the bit.

def _tail_table(m: int, cl: float, tau2: float):
    """
    (k_lo, lower, upper) over the kept support of Binomial(m, cl), or of the
    beta-binomial with between-provider variance tau2 > 0: lower[j] = P(X ≤ k_lo + j)
    and upper[j] = P(X ≥ k_lo + j), summed in the order dist._walk_tails sums them, so
    each entry is that function's value bit for bit. None where the exact model is
    unavailable (no beta distribution has that spread, or the walk ran out), for the
    caller's normal fallback.
    """
    if m == 0 or cl <= 0.0:
        return 0, [1.0], [1.0]
    if cl >= 1.0:
        return m, [1.0], [1.0]
    if tau2 > 0:
        params = beta_params(cl, tau2)
        if params is None:
            return None
        a, b = params

        def ratio(j):
            return (m - j) * (a + j) / ((j + 1) * (b + m - j - 1))

        start = min(m, int(math.floor(m * cl)))
    else:
        odds = cl / (1.0 - cl)

        def ratio(j):
            return (m - j) / (j + 1) * odds

        start = min(m, int(math.floor((m + 1) * cl)))
    walk = _walk_terms(ratio, start, m, ("tail_table", m, cl, tau2))
    if walk is None:
        return None
    k_lo, terms, total = walk
    if isinstance(terms, np.ndarray):
        lower = np.minimum(1.0, np.cumsum(terms) / total).tolist()
        upper = np.minimum(1.0, np.cumsum(terms[::-1]) / total)[::-1].tolist()
        return k_lo, lower, upper
    lower = []
    acc = 0.0
    for t in terms:
        acc += t
        lower.append(min(1.0, acc / total))
    upper = []
    acc = 0.0
    for t in reversed(terms):
        acc += t
        upper.append(min(1.0, acc / total))
    upper.reverse()
    return k_lo, lower, upper


def _table_tails(table, o: float) -> tuple[float, float]:
    """(P(X ≤ o), P(X ≥ o)) from a _tail_table, linear between whole counts."""
    k_lo, lower, upper = table

    def at(k):
        j = k - k_lo
        if j < 0:
            return 0.0, 1.0
        if j >= len(lower):
            return 1.0, 0.0
        return lower[j], upper[j]

    k0 = math.floor(o)
    w = o - k0
    lo0, up0 = at(k0)
    if w == 0.0:
        return lo0, up0
    lo1, up1 = at(k0 + 1)
    return (1.0 - w) * lo0 + w * lo1, (1.0 - w) * up0 + w * up1


def _mixed_tails(tables, m0: int, w: float, p: float) -> tuple[float, float]:
    """T(p; ν) above: both tails at proportion p, interpolated in ν."""
    lo0, up0 = _table_tails(tables[0], min(p * m0, float(m0)))
    lo1, up1 = _table_tails(tables[1], min(p * (m0 + 1), float(m0 + 1)))
    return (1.0 - w) * lo0 + w * lo1, (1.0 - w) * up0 + w * up1


def _fractional_tables(nu: float, cl: float, tau2: float):
    m0 = int(math.floor(nu))
    tables = (_tail_table(m0, cl, tau2), _tail_table(m0 + 1, cl, tau2))
    if tables[0] is None or tables[1] is None:
        return None
    return tables, m0, nu - m0


def fractional_binomial_tails(o: float, nu: float, cl: float, tau2: float):
    """
    (P(X ≤ o), P(X ≥ o)) for a count o out of a fractional ν, by the interpolation
    above; None where the exact model is unavailable. pvalues._point_tails uses this
    for every non-integer binomial denominator.
    """
    found = _fractional_tables(nu, cl, tau2)
    if found is None:
        return None
    tables, m0, w = found
    return _mixed_tails(tables, m0, w, o / nu)


def fractional_binomial_pair(
    cl: float, nu: float, tau2: float, p_lower: float, p_upper: float,
) -> tuple[float, float]:
    """
    (ucl, lcl) on the proportion scale at a fractional denominator ν: the proportions
    at which the interpolated test's upper tail reaches 1 − p_upper and its lower tail
    reaches p_lower, by _BISECT_ITERS halvings of [0, 1]. At a whole ν these are the
    exact contours (the interpolated quantile, with the upper one a count further out,
    _upper_boundary), so the contour is continuous through whole numbers. The upper
    contour is 1 when even an all-events provider could not flag, and the lower one 0
    when a no-event provider could not. (NaN, NaN) where the exact model is
    unavailable, for the caller's normal fallback.
    """
    found = _fractional_tables(nu, cl, tau2)
    if found is None:
        return math.nan, math.nan
    tables, m0, w = found
    a_up = 1.0 - p_upper

    if _mixed_tails(tables, m0, w, 1.0)[1] > a_up:
        ucl = 1.0
    else:
        lo, hi = 0.0, 1.0
        for _ in range(_BISECT_ITERS):
            mid = 0.5 * (lo + hi)
            if _mixed_tails(tables, m0, w, mid)[1] > a_up:
                lo = mid
            else:
                hi = mid
        ucl = 0.5 * (lo + hi)

    if _mixed_tails(tables, m0, w, 0.0)[0] >= p_lower:
        lcl = 0.0
    else:
        lo, hi = 0.0, 1.0
        for _ in range(_BISECT_ITERS):
            mid = 0.5 * (lo + hi)
            if _mixed_tails(tables, m0, w, mid)[0] < p_lower:
                lo = mid
            else:
                hi = mid
        lcl = 0.5 * (lo + hi)
    return ucl, lcl


def _mixture_funnel_pair(
    cl: float, n: np.ndarray | None, tau2: float, family: str,
    p_lower: float, p_upper: float, z: float, diag: dict | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Over-dispersed funnel limits at one contour: the additive random-effects model.

    [1, eq. 11] draws θ₀ ± z·√(V₀ᵢ + τ²), a normal approximation. Here the same
    model is drawn exactly, from the distribution it describes: each provider's true
    rate is spread around θ₀ with variance τ², gamma-distributed for counts and
    beta-distributed for proportions, and the observed count is Poisson or binomial
    given that rate. Both mixtures have variance V₀ᵢ + τ² (the beta-binomial up to a
    factor (nᵢ − 1)/nᵢ on τ²), so the only departure from [1] is exact quantiles in
    place of normal ones — the substitution [1, Appendix A] itself makes for the
    unadjusted limits. See docs/methods.md, "Adjusted limits".

    Two consequences of the additive model are the reason for choosing it [1, §5; 2]:
    at small volume, where V₀ᵢ dominates, the limits barely move from the unadjusted
    ones; at large volume they level off at roughly θ₀ ± z·τ instead of closing onto
    θ₀, so a high-volume provider is not flagged for a difference smaller than the
    spread between providers.

    τ² = 0 delegates to the unadjusted limits, so the two charts agree exactly when
    there is no evidence of over-dispersion.
    """
    if not (tau2 > 0):
        if family == "binomial":
            return _binomial_funnel_pair(cl, n, p_lower, p_upper, z, diag)
        return _poisson_funnel_pair(cl, n, p_lower, p_upper, z, "exact", diag)

    e = np.asarray(n, dtype=float)
    ucl = np.full(len(e), np.nan)
    lcl = np.full(len(e), np.nan)

    if family == "poisson":
        size = gamma_size(cl, tau2)
        for i, ei in enumerate(e):
            if not (ei > 0):
                continue
            (lo, hi), exact = poisson_gamma_quantiles((p_lower, p_upper), cl * ei, size, (-z, z))
            if not exact and diag is not None:
                diag["normal"] = True
            ucl[i], lcl[i] = _upper_boundary(hi, exact) / ei, lo / ei
        return ucl, lcl

    params = beta_params(cl, tau2)
    if params is None:
        # No beta distribution has this mean and variance: the providers spread wider
        # than a proportion can. Fall back to [1, eq. 11] exactly as published.
        if diag is not None:
            diag["normal"] = True
        with np.errstate(divide="ignore", invalid="ignore"):
            half = z * np.sqrt(cl * (1.0 - cl) / np.where(e > 0, e, np.nan) + tau2)
        return cl + half, cl - half

    alpha, beta = params
    for i, ei in enumerate(e):
        if not (ei > 0):
            continue
        if _integer_count(float(ei)) is None:
            pair = fractional_binomial_pair(cl, float(ei), tau2, p_lower, p_upper)
            if not math.isnan(pair[0]):
                ucl[i], lcl[i] = pair
                if diag is not None:
                    diag["interpolated"] = True
                continue
        (lo, hi), exact = beta_binomial_quantiles((p_lower, p_upper), float(ei), alpha, beta, (-z, z))
        if not exact and diag is not None:
            diag["normal"] = True
        ucl[i], lcl[i] = _upper_boundary(hi, exact, ei) / ei, lo / ei
    return ucl, lcl



def _transformed_pair(
    cl: float, n: np.ndarray, tau2: float, scale: str, z: float,
) -> tuple[np.ndarray, np.ndarray]:
    """
    The CQC and SHMI contours: T(θ₀) ± z·√(sᵢ² + τ²) on the transformed scale T, mapped back
    (FunnelPlotR's limits, with one correction): √ and arcsine limits are squared back to
    the y scale, as the method intends; FunnelPlotR's CQC limits for a standardized ratio
    are drawn on the √ scale itself and are about half as wide (docs/methods.md §4.17).
    """
    from .dispersion import from_scale, scale_sd, to_scale

    e = np.asarray(n, dtype=float)
    s = scale_sd(scale, cl, np.where(e > 0, e, np.nan))
    center = float(to_scale(scale, cl))
    half = z * np.sqrt(s * s + tau2)
    return from_scale(scale, center + half), from_scale(scale, center - half)


@dataclass(frozen=True)
class Contours:
    """Both contour pairs on the y scale, aligned with n, and how they were drawn."""
    ucl: np.ndarray
    lcl: np.ndarray
    ucl_95: np.ndarray
    lcl_95: np.ndarray
    method: str                              # exact | interpolated | normal | byar | transformed_normal
    diag: dict = field(default_factory=dict)


def funnel_contours(
    family: str, cl: float, n, tau2: float = 0.0, levels: tuple = DEFAULT_LEVELS,
    limit_method: str = "exact", scale: str = "natural",
) -> Contours:
    """
    The outer and inner contours at denominators n (already n/φ under within_dispersion).

    family is "poisson" (O/E, rates) or "binomial" (proportions); tau2 the between-provider
    variance (0 for an unadjusted funnel); scale "natural" for the exact models, or the
    transformed scale of tau_method="cqc"/"shmi", on which tau2 is measured. With τ² = 0
    every method draws the exact contours, so an adjusted funnel with no measured spread
    is the unadjusted one to the bit. limit_method="byar" (O/E only, kept for the shared
    fixtures) draws Byar's approximation everywhere.
    """
    n = np.asarray(n, dtype=float)
    diag: dict = {}
    pairs = []
    for coverage in levels:
        p_lower, p_upper, z = contour(coverage)
        if scale != "natural" and tau2 > 0:
            pairs.append(_transformed_pair(cl, n, tau2, scale, z))
        elif family == "poisson" and not (tau2 > 0):
            pairs.append(_poisson_funnel_pair(cl, n, p_lower, p_upper, z, limit_method, diag))
        else:
            pairs.append(_mixture_funnel_pair(cl, n, tau2, family, p_lower, p_upper, z, diag))
    (ucl, lcl), (ucl_95, lcl_95) = pairs
    lcl, lcl_95 = np.maximum(lcl, 0.0), np.maximum(lcl_95, 0.0)
    if scale != "natural" and tau2 > 0:
        method = "transformed_normal"
    elif limit_method == "byar" or diag.get("byar"):
        method = "byar"
    elif diag.get("normal"):
        method = "normal"
    elif diag.get("interpolated"):
        method = "interpolated"
    else:
        method = "exact"
    return Contours(ucl, lcl, ucl_95, lcl_95, method, diag)
