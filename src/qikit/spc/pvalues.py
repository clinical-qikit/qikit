"""
pvalues.py — exact per-point p-values and Benjamini–Hochberg q-values for funnels.

Each p-value tests one point against the same null model its funnel limits are drawn
from: the count is Poisson or binomial at the center line, or the Poisson–gamma or
beta-binomial mixture with the τ² the adjusted limits use. They are conventional exact
tail probabilities, P(X ≥ O) above and P(X ≤ O) below, which is not quite what the
interpolated limits test: at small counts a point just beyond the upper 99.8% line can
have P(X ≥ O) above 0.001. docs/methods.md §4.11 records why, with a worked example.

Numbered references are those of docs/methods.md.

References
----------
[1]  Spiegelhalter DJ. Funnel plots for comparing institutional performance.
     Statistics in Medicine 2005;24(8):1185-1202.
[12] Jones HE, Ohlssen DI, Spiegelhalter DJ. Use of the false discovery rate when
     comparing multiple health care providers. J Clin Epidemiol 2008;61(3):232-240.
[15] Benjamini Y, Hochberg Y. Controlling the false discovery rate: a practical and
     powerful approach to multiple testing. JRSS B 1995;57(1):289-300.
"""

from __future__ import annotations

import math

import numpy as np

from .dist import beta_binomial_tails, binomial_tails, poisson_gamma_tails, poisson_tails
from .limits import DEFAULT_LEVELS, _integer_count, beta_params, contour, gamma_size


def signal_thresholds(side: str, levels: tuple = DEFAULT_LEVELS) -> tuple[float, float]:
    """
    (outer, inner) significance levels matching the funnel's own contours.

    A one-sided test takes each contour's tail probability as it is (0.001, 0.025 at
    the default 99.8% and 95%); a two-sided p-value is doubled, so it is held to twice
    that (0.002, 0.05). Either way a point's p-value is below the outer level exactly
    when it is beyond the outer contour on its side (limits._upper_boundary), so these
    are also the levels behind expected_false_flags in "limits" mode.
    """
    mult = 2.0 if side == "both" else 1.0
    return contour(levels[0])[0] * mult, contour(levels[1])[0] * mult


def count_model(family: str, tau2: float) -> str:
    """The count distribution a funnel's limits and p-values actually used."""
    if family == "poisson":
        return "poisson_gamma" if tau2 > 0 else "poisson"
    return "beta_binomial" if tau2 > 0 else "binomial"


def _normal_tails(o: float, mu: float, var: float) -> tuple[float, float]:
    """
    (P(X ≤ o), P(X ≥ o)) under N(μ, V), with no continuity correction — the model the
    limits fall back to in the same cases ([1] eq. 3 / eq. 11, dist._normal_quantiles).
    """
    if not (var > 0) or math.isnan(o) or math.isnan(mu):
        return math.nan, math.nan
    z = (o - mu) / math.sqrt(2.0 * var)
    return 0.5 * math.erfc(z), 0.5 * math.erfc(-z)


def _point_tails(
    o: float, n: float, cl: float, tau2: float, family: str,
) -> tuple[tuple[float, float], str]:
    """
    ((P(X ≤ O), P(X ≥ O)), method) for one point's count O at denominator n.

    method is "exact" for a whole-number count. A count between whole numbers (an
    averaged aggregate, or an effective count O/φ under within_dispersion) takes each
    tail linearly interpolated between its two integer neighbours: "interpolated".
    That is the inverse of Spiegelhalter's interpolated quantile, so the point is
    beyond a contour exactly when this p-value is below its tail probability, as for
    a whole count. "normal" where the normal model stood in: a non-integer binomial
    denominator, a pp spread no beta distribution can have, or a walk past
    dist._MAX_TERMS. Its mean and variance are those of the exact model in each case.
    """
    if _integer_count(o) is None and not math.isnan(o) and o >= 0:
        k0 = math.floor(o)
        w = o - k0
        (lo0, up0), m0 = _point_tails(float(k0), n, cl, tau2, family)
        (lo1, up1), m1 = _point_tails(float(k0 + 1), n, cl, tau2, family)
        if m0 == "normal" or m1 == "normal":
            return _point_tails_normal(o, n, cl, tau2, family), "normal"
        return ((1.0 - w) * lo0 + w * lo1, (1.0 - w) * up0 + w * up1), "interpolated"
    k = _integer_count(o)
    if family == "poisson":
        lam = cl * n
        if tau2 > 0:
            size = gamma_size(cl, tau2)
            var = lam + lam * lam / size
            tails = poisson_gamma_tails(k, lam, size) if k is not None else None
        else:
            var = lam
            tails = poisson_tails(k, lam) if k is not None else None
        if tails is not None:
            return tails, "exact"
        return _normal_tails(o, lam, var), "normal"

    m = _integer_count(n)
    mu = n * cl
    tails = None
    if tau2 > 0:
        params = beta_params(cl, tau2)
        if params is None:
            var = n * cl * (1.0 - cl) + n * n * tau2
        else:
            alpha, beta = params
            var = n * cl * (1.0 - cl) * (alpha + beta + n) / (alpha + beta + 1.0)
            if k is not None and m is not None:
                tails = beta_binomial_tails(k, m, alpha, beta)
    else:
        var = n * cl * (1.0 - cl)
        if k is not None and m is not None:
            tails = binomial_tails(k, m, cl)
    if tails is not None:
        return tails, "exact"
    return _normal_tails(o, mu, var), "normal"


def _point_tails_normal(o: float, n: float, cl: float, tau2: float, family: str):
    """The normal-model tails at the exact model's mean and variance, for a fallback."""
    if family == "poisson":
        lam = cl * n
        var = lam + (lam * lam / gamma_size(cl, tau2) if tau2 > 0 else 0.0)
        return _normal_tails(o, lam, var)
    var = n * cl * (1.0 - cl)
    if tau2 > 0:
        params = beta_params(cl, tau2)
        if params is None:
            var += n * n * tau2
        else:
            var *= (sum(params) + n) / (sum(params) + 1.0)
    return _normal_tails(o, n * cl, var)


def funnel_p_values(
    cl: float, y: np.ndarray, n: np.ndarray, tau2: float, family: str, side: str,
) -> tuple[np.ndarray, str, str]:
    """
    Per-point exact p-values for a funnel, on the raw (pre-multiply) scale.

    y is the proportion, rate or O/E ratio with excluded points already NaN; n the
    denominator; tau2 the τ² the limits were drawn with (0.0 on an unadjusted chart,
    never the diagnostic estimate). side picks P(X ≥ O) ("above"), P(X ≤ O) ("below"),
    or min(1, 2·min of the two) ("both"). NaN where y is NaN or n is not positive.

    Returns (p_value, p_value_method, count_model): p_value_method is "normal" if any
    point fell back to the normal model, else "interpolated" if any count was not a
    whole number, else "exact".
    """
    y = np.asarray(y, dtype=float)
    n = np.asarray(n, dtype=float)
    p = np.full(len(y), np.nan)
    methods: set[str] = set()
    for i in range(len(y)):
        yi, ni = float(y[i]), float(n[i])
        if math.isnan(yi) or not (ni > 0):
            continue
        (lower, upper), method = _point_tails(yi * ni, ni, cl, tau2, family)
        if math.isnan(lower):
            continue
        methods.add(method)
        if side == "above":
            p[i] = upper
        elif side == "below":
            p[i] = lower
        else:
            p[i] = min(1.0, 2.0 * min(lower, upper))
    overall = next((m for m in ("normal", "interpolated") if m in methods), "exact")
    return p, overall, count_model(family, tau2)


def bh_q_values(p: np.ndarray) -> np.ndarray:
    """
    Benjamini–Hochberg adjusted p-values (q-values) [15], as [12] applies them to
    provider comparisons.

    Over the finite p only (K of them; excluded points carry NaN and are not tested):
    sorted ascending, q at rank i is min over ranks j ≥ i of p₍ⱼ₎·K/j, capped at 1. A
    point is significant at false discovery rate α exactly when q < α. NaN stays NaN.
    """
    p = np.asarray(p, dtype=float)
    q = np.full(len(p), np.nan)
    idx = np.flatnonzero(np.isfinite(p))
    k = len(idx)
    if k == 0:
        return q
    order = idx[np.argsort(p[idx], kind="stable")]
    running = 1.0
    for rank in range(k, 0, -1):
        i = order[rank - 1]
        running = min(running, float(p[i]) * k / rank)
        q[i] = running
    return q
