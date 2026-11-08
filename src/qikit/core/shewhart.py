"""
shewhart.py — center lines and control limits for time-ordered charts.

Every chart here estimates a center line from its baseline points and a one-sigma
spread per point; the limits are cl ± 3σ and the inner band cl ± 2σ, floored at 0
(and capped at 1 for proportions) where the measure is bounded. The g, mr and s charts,
whose limits are not symmetric, compute theirs directly. The t chart is the i chart on
y^(1/3.6), handled by the caller (see T_POWER).

The reference is qicharts2 (Anhøj); docs/qic-methods.md lists each place qikit departs
from it and why. tests/test_reference.py checks the rest against qicharts2's own output.

References
----------
Montgomery DC. Introduction to Statistical Quality Control, 8th ed. Wiley, 2019.
Provost LP, Murray SK. The Health Care Data Guide, 2nd ed. Jossey-Bass, 2022.
Laney DB. Improved control charts for attributes. Quality Engineering 14(4), 2002.
Nelson LS. Control charts for individual measurements. J Qual Technol 1982;14:172-173.
NHS England. Making Data Count: strengthening your decisions. 2019 (the 2.66 XmR constant).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .constants import D2, D4, a3, c4

# Time-ordered chart types qic() draws.
CHARTS = ("run", "i", "mr", "xbar", "s", "t", "p", "pp", "c", "u", "up", "g")
# Charts whose y is events / denominator, so n= is required.
RATE_CHARTS = ("p", "pp", "u", "up")
# Charts drawn from subgroups of raw values: y is each subgroup's mean or SD.
SUBGROUP_CHARTS = ("xbar", "s")
# The t chart transforms time between events to near-normality (Montgomery §7.3).
T_POWER = 3.6
# NHS Making Data Count's XmR constant, 3/d2 rounded as the program publishes it.
MDC_CONSTANT = 2.66


@dataclass(frozen=True)
class Limits:
    """One part of a chart: arrays aligned with y, on the scale y was given in."""
    cl: np.ndarray
    ucl: np.ndarray
    lcl: np.ndarray
    ucl_95: np.ndarray
    lcl_95: np.ndarray
    sigma: np.ndarray            # one sigma per point; NaN where the chart has none
    info: dict[str, Any] = field(default_factory=dict)


def shewhart(
    chart: str,
    y: np.ndarray,
    n: np.ndarray | None,
    mask: np.ndarray,
    center: float | None = None,
    sd: np.ndarray | None = None,
    categorical: bool = False,
    mdc: bool = False,
) -> Limits:
    """
    Center line and limits for one part of a time-ordered chart.

    y is the plotted value (a proportion or rate on p/pp/u/up, the subgroup mean on
    xbar, the subgroup SD on s, the moving range on mr); n the denominator, or the
    subgroup size on xbar/s; mask the baseline the center and spread are estimated
    from; center a fixed center line; sd the subgroup SDs (xbar only); categorical
    makes Laney's σ_z the SD of z rather than its moving range, as qicharts2 does when x
    has no order; mdc uses Making Data Count's 2.66 on the i chart.
    """
    y = np.asarray(y, dtype=float)
    k = len(y)
    nan = np.full(k, np.nan)

    if chart == "run":
        cl = _median(y[mask]) if center is None else float(center)
        return Limits(np.full(k, cl), nan, nan, nan, nan, nan)

    if chart == "g":
        return _g_limits(y, mask, center)
    if chart == "mr":
        return _mr_limits(y, mask, center)
    if chart in SUBGROUP_CHARTS:
        sizes = np.asarray(n, dtype=float)
        if chart == "xbar":
            return _xbar_limits(y, sizes, np.asarray(sd, dtype=float), mask, center)
        return _s_limits(y, sizes, mask, center)

    info: dict[str, Any] = {}
    if chart == "i":
        cl = _mean(y[mask]) if center is None else float(center)
        amr = screened_mean_mr(y[mask])
        constant = MDC_CONSTANT / 3.0 if mdc else 1.0 / D2[2]
        s = amr * constant
        sigma: np.ndarray = np.full(k, s if s > 0 else np.nan)
    elif chart == "c":
        cl = _mean(y[mask]) if center is None else float(center)
        sigma = np.full(k, math.sqrt(cl) if cl >= 0 else np.nan)
    else:  # p, pp, u, up: events over denominators
        n_arr = np.asarray(n, dtype=float)
        nn = np.where(n_arr > 0, n_arr, np.nan)
        cl = _weighted(y[mask], nn[mask]) if center is None else float(center)
        binomial = chart in ("p", "pp")
        var = cl * (1.0 - cl) if binomial else cl
        with np.errstate(invalid="ignore"):
            sigma = np.sqrt(var / nn)
        if chart in ("pp", "up"):
            sigma_z = laney_sigma_z(y, cl, sigma, mask, categorical)
            # A series with no point-to-point variation has no spread to estimate, as on
            # the i chart: no limits rather than limits on the center line.
            sigma = sigma * (sigma_z if sigma_z > 0 else np.nan)
            info["sigma_z"] = sigma_z

    cap = 1.0 if chart in ("p", "pp") else None
    floor = chart != "i"
    return _symmetric(np.full(k, cl), sigma, floor=floor, cap=cap, info=info)


def _symmetric(cl, sigma, floor: bool, cap: float | None, info=None) -> Limits:
    """cl ± 3σ and ± 2σ, floored at 0 and capped where the measure is bounded."""
    ucl, lcl = cl + 3 * sigma, cl - 3 * sigma
    ucl_95, lcl_95 = cl + 2 * sigma, cl - 2 * sigma
    if floor:
        lcl, lcl_95 = np.maximum(lcl, 0.0), np.maximum(lcl_95, 0.0)
    if cap is not None:
        ucl, ucl_95 = np.minimum(ucl, cap), np.minimum(ucl_95, cap)
    return Limits(cl, ucl, lcl, ucl_95, lcl_95, sigma, info or {})


# ---------------------------------------------------------------------------
# Spread estimators
# ---------------------------------------------------------------------------

def screened_mean_mr(y_base: np.ndarray) -> float:
    """
    Mean moving range of the baseline, screened once (Nelson 1982, as qicharts2):
    moving ranges at or above 3.267·MR̄ are dropped and MR̄ recomputed. A missing value
    breaks the series rather than bridging it, as in qicharts2.

    One departure: where most moving ranges are 0 the screen can drop the only
    informative one and leave MR̄ = 0, which would draw limits on the center line and
    flag every point. The unscreened MR̄ is kept then (docs/qic-methods.md).
    """
    mr = np.abs(np.diff(np.asarray(y_base, dtype=float)))
    mr = mr[np.isfinite(mr)]
    if len(mr) == 0:
        return math.nan
    amr = float(np.mean(mr))
    kept = mr[mr < D4[2] * amr]
    screened = float(np.mean(kept)) if len(kept) else math.nan
    return screened if screened > 0 else amr


def laney_sigma_z(
    y: np.ndarray, cl: float, sigma: np.ndarray, mask: np.ndarray, categorical: bool,
) -> float:
    """
    Laney's σ_z: how much the baseline's standardized residuals zᵢ = (yᵢ − cl)/σᵢ vary
    beyond what the binomial or Poisson model predicts. The screened mean moving range
    of z over d2 in time order; the SD of z when x is categorical (qicharts2). Not
    floored at 1: Laney's method narrows the limits of an under-dispersed series too.
    """
    with np.errstate(invalid="ignore", divide="ignore"):
        z = (np.asarray(y, dtype=float) - cl) / sigma
    zb = z[mask]
    if categorical:
        zb = zb[np.isfinite(zb)]
        return float(np.std(zb, ddof=1)) if len(zb) > 1 else math.nan
    return screened_mean_mr(zb) / D2[2]


def subgroup_sigma(
    sd: np.ndarray, sizes: np.ndarray, mask: np.ndarray,
) -> tuple[float | None, float | None]:
    """
    (S̄, σ̂) for xbar/s from the baseline subgroups; exactly one is not None.

    Equal subgroup sizes take S̄ = mean(sᵢ), which pairs with A3/B3/B4. Unequal sizes take
    the pooled σ̂ = Sp/c4(d + 1), Sp = √(Σ(nᵢ − 1)sᵢ²/Σ(nᵢ − 1)), d = Σ(nᵢ − 1): an unbiased σ,
    used as 3σ̂/√nᵢ. qicharts2 uses A3(nᵢ)·Sp there instead (docs/qic-methods.md).
    Whether sizes are equal is judged over every usable subgroup, as in qicharts2.
    """
    usable = (sizes >= 2) & np.isfinite(sd)
    base = usable & mask
    if not base.any():
        return math.nan, None
    if np.unique(sizes[usable]).size == 1:
        return float(np.mean(sd[base])), None
    dof = sizes[base] - 1.0
    total = float(np.sum(dof))
    pooled = math.sqrt(float(np.sum(dof * sd[base] ** 2)) / total)
    return None, pooled / c4(total + 1.0)


# ---------------------------------------------------------------------------
# Charts with their own limits
# ---------------------------------------------------------------------------

def _xbar_limits(y, sizes, sd, mask, center) -> Limits:
    """X̄ chart: CL = Σnᵢx̄ᵢ/Σnᵢ; ±A3(nᵢ)·S̄, or ±3σ̂/√nᵢ with unequal sizes (Montgomery §6.3)."""
    ok = mask & np.isfinite(y) & np.isfinite(sizes)
    if center is not None:
        cl = float(center)
    else:
        total = float(np.sum(sizes[ok]))
        cl = float(np.sum(sizes[ok] * y[ok]) / total) if total > 0 else math.nan
    s_bar, sigma_hat = subgroup_sigma(sd, sizes, mask)
    with np.errstate(invalid="ignore", divide="ignore"):
        if sigma_hat is not None:
            sigma = sigma_hat / np.sqrt(np.where(sizes >= 2, sizes, np.nan))
        else:
            sigma = np.array([a3(float(s)) for s in sizes]) * s_bar / 3.0
    return _symmetric(np.full(len(y), cl), sigma, floor=False, cap=None)


def _s_limits(y, sizes, mask, center) -> Limits:
    """
    S chart. Equal sizes: CL = S̄, limits B3/B4(nᵢ)·S̄ (Montgomery §6.4). Unequal sizes:
    CLᵢ = c4(nᵢ)·σ̂ and CLᵢ ± 3σ̂√(1 − c4(nᵢ)²), so a series whose subgroup size drifts does
    not manufacture a run against a flat center line (docs/qic-methods.md).
    """
    k = len(y)
    c = np.array([c4(float(s)) for s in sizes])
    s_bar, sigma_hat = subgroup_sigma(y, sizes, mask)
    if center is not None:
        s_bar, sigma_hat = float(center), None
    if sigma_hat is not None:
        cl = sigma_hat * c
        sigma = sigma_hat * np.sqrt(np.maximum(0.0, 1.0 - c * c))
    else:
        cl = np.full(k, s_bar)
        with np.errstate(invalid="ignore"):
            sigma = s_bar * np.sqrt(np.maximum(0.0, 1.0 - c * c)) / c
    return _symmetric(cl, sigma, floor=True, cap=None)


def _mr_limits(y, mask, center) -> Limits:
    """
    Moving-range chart: CL = MR̄, UCL = 3.267·MR̄ (D4 for n = 2), LCL = 0 (D3 = 0). The inner
    line is the 2σ point of the moving range, MR̄(1 + 2·d3/d2) = 2.511·MR̄; qicharts2 draws
    2/3 of the UCL there instead (docs/qic-methods.md).
    """
    k = len(y)
    cl = _mean(y[mask]) if center is None else float(center)
    ucl = np.full(k, D4[2] * cl)
    zero = np.zeros(k)
    sigma = np.full(k, (D4[2] - 1.0) * cl / 3.0)
    return Limits(np.full(k, cl), ucl, zero, cl + 2 * sigma, zero.copy(), sigma)


def _g_limits(y, mask, center) -> Limits:
    """
    G chart (opportunities between rare events, geometric): limits m ± 3√(m(m + 1)) from
    the baseline mean m, floored at 0 (Montgomery p. 319); the center line drawn is the
    baseline median, the typical gap, as in qicharts2. A fixed center= is the mean.
    """
    k = len(y)
    m = _mean(y[mask]) if center is None else float(center)
    s = math.sqrt(m * (m + 1.0)) if m >= 0 else math.nan
    cl = _median(y[mask]) if center is None else m
    sigma = np.full(k, s)
    limits = _symmetric(np.full(k, m), sigma, floor=True, cap=None)
    return Limits(np.full(k, cl), limits.ucl, limits.lcl, limits.ucl_95, limits.lcl_95, sigma)


# ---------------------------------------------------------------------------
# Center lines
# ---------------------------------------------------------------------------

def _mean(v: np.ndarray) -> float:
    v = v[np.isfinite(v)]
    return float(np.mean(v)) if len(v) else math.nan


def _median(v: np.ndarray) -> float:
    v = v[np.isfinite(v)]
    return float(np.median(v)) if len(v) else math.nan


def _weighted(y: np.ndarray, n: np.ndarray) -> float:
    """Σyᵢnᵢ/Σnᵢ over points with both: the pooled proportion or rate."""
    ok = np.isfinite(y) & np.isfinite(n)
    total = float(np.sum(n[ok]))
    return float(np.sum(y[ok] * n[ok]) / total) if total > 0 else math.nan
