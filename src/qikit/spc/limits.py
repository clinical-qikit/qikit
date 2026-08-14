"""
limits.py — center-line and control-limit functions per chart type.

Each chart type is a ChartSpec with two functions: center and limits.
No routing, no string dispatch. Adding a chart = two small functions + one dict entry.

References
----------
1. Montgomery DC. Introduction to Statistical Quality Control, 8th ed. Wiley, 2019.
2. Provost LP, Murray SK. The Health Care Data Guide, 2nd ed. Jossey-Bass, 2022. ISBN 978-1-119-69013-9, 978-1-119-69012-2.
5. Laney DB. Improved control charts for attributes. Quality Engineering 14(4), 2002.
6. Spiegelhalter DJ. Funnel plots for comparing institutional performance.
   Statistics in Medicine 2005;24(8):1185-1202.
7. Spiegelhalter DJ. Handling over-dispersion of performance indicators.
   Quality & Safety in Health Care 2005;14:347-351.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .constants import D2, D4, Z_80, Z_95, Z_998, a3, b3, b4, c4
from .dist import (
    _EXACT_MAX_LAMBDA,
    _MEAN_SOLVE_MAX_K,
    byar_quantile,
    poisson_mean_for_cdf,
    poisson_quantile_interp,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _moving_ranges(y: np.ndarray) -> np.ndarray:
    """Absolute successive differences. Length = len(y) - 1."""
    return np.abs(np.diff(y))


def _get_constants(n: np.ndarray, const_fn: Callable[[float], float]) -> np.ndarray:
    """
    Map an array of subgroup sizes to an array of SPC constants.

    const_fn is one of constants.a3 / b3 / b4 / c4, each of which returns NaN for
    sizes below 2. A size-1 subgroup therefore renders as a gap rather than
    breaking the whole chart.
    """
    return np.array([const_fn(float(val)) for val in n])


def _subgroup_sizes(
    n: np.ndarray | None, subgroup_n: int | None, k: int, label: str,
) -> np.ndarray:
    """Per-point subgroup sizes, preferring the n array over the scalar fallback."""
    if n is not None:
        return np.asarray(n, dtype=float)
    if subgroup_n is not None:
        return np.full(k, float(subgroup_n))
    raise ValueError(f"{label} requires subgroup size information.")


def _screened_mean_mr(y: np.ndarray, mask: np.ndarray) -> float:
    """
    Mean moving range with one-pass screening of out-of-control MRs.

    Provost & Murray (2011) p.140: remove MRs > D4 * MR̄ before computing
    the final MR̄ used for sigma estimation on the I chart.
    """
    y_valid = y[mask & ~np.isnan(y)]
    if len(y_valid) < 2:
        return np.nan
    mrs = _moving_ranges(y_valid)
    mr_bar = float(np.nanmean(mrs))
    mrs_screened = mrs[mrs <= D4[2] * mr_bar]
    if len(mrs_screened) == 0:
        return mr_bar

    # Screening drops MRs above D4·MR̄, but where most MRs are zero the
    # threshold falls below the one informative MR and screens it out. The
    # survivors then average to 0, collapsing the limits onto the center line
    # and flagging every point. Fall back to the unscreened mean whenever
    # screening leaves nothing to estimate from.
    screened_mean = float(np.nanmean(mrs_screened))
    if np.isnan(screened_mean) or screened_mean <= 0:
        return mr_bar
    return screened_mean


# ---------------------------------------------------------------------------
# Center-line functions:  (y_base, n_base) → float
# ---------------------------------------------------------------------------

def _cl_median(y_base: np.ndarray, n_base: np.ndarray | None) -> float:
    valid = y_base[~np.isnan(y_base)]
    if len(valid) == 0:
        return np.nan
    return float(np.nanmedian(valid))


def _cl_mean(y_base: np.ndarray, n_base: np.ndarray | None) -> float:
    valid = y_base[~np.isnan(y_base)]
    if len(valid) == 0:
        return np.nan
    return float(np.nanmean(valid))


def _cl_weighted(y_base: np.ndarray, n_base: np.ndarray | None) -> float:
    """Weighted average: sum(y*n) / sum(n) — for p and u charts."""
    if n_base is None:
        raise ValueError("Weighted center line requires denominators (n=).")
    total_events = float(np.nansum(y_base * n_base))
    total_n = float(np.nansum(n_base))
    if total_n == 0:
        return np.nan
    return total_events / total_n


def _cl_grand_mean(y_base: np.ndarray, n_base: np.ndarray | None) -> float:
    """
    Volume-weighted grand mean Σ(nᵢx̄ᵢ)/Σnᵢ — for the Xbar chart.

    Identical to the unweighted mean of subgroup means whenever subgroup sizes are
    constant, and correct when they are not. Falls back to the unweighted mean if
    sizes are unavailable (compute() may be called without n=).
    """
    if n_base is None:
        return _cl_mean(y_base, n_base)
    valid = ~(np.isnan(y_base) | np.isnan(n_base))
    total_n = float(np.sum(n_base[valid]))
    if total_n == 0:
        return np.nan
    return float(np.sum(y_base[valid] * n_base[valid]) / total_n)


# ---------------------------------------------------------------------------
# Limits functions:  (cl_val, y, n, mask, subgroup_n, **_) → (ucl_arr, lcl_arr)
#
# Every function returns two arrays of len(y).
# Charts without limits return NaN arrays.
# All functions accept **_ to silently ignore extra kwargs (e.g. s_bar, sigma_hat).
#
# subgroup_n is a scalar fallback for callers that have no per-point n array; it is
# never a constraint on the range of usable subgroup sizes.
# ---------------------------------------------------------------------------

def _no_limits(
    cl: float, y: np.ndarray, n: np.ndarray | None,
    mask: np.ndarray, subgroup_n: int | None = None, **_,
) -> tuple[np.ndarray, np.ndarray]:
    nans = np.full(len(y), np.nan)
    return nans, nans


def _i_limits(
    cl: float, y: np.ndarray, n: np.ndarray | None,
    mask: np.ndarray, subgroup_n: int | None = None, **_,
) -> tuple[np.ndarray, np.ndarray]:
    """I chart: σ̂ = MR̄/d2 (Montgomery 2019, §6.2; d2 = 1.128 for n = 2)."""
    mr_bar = _screened_mean_mr(y, mask)
    if np.isnan(mr_bar):
        nans = np.full(len(y), np.nan)
        return nans, nans
    sigma = mr_bar / D2[2]
    if sigma <= 0:
        # A perfectly flat series has no variation to estimate a spread from.
        # Zero-width limits would draw three coincident lines and call any
        # departure a signal, so report no limits and let it read as a run chart.
        nans = np.full(len(y), np.nan)
        return nans, nans
    k = len(y)
    return np.full(k, cl + 3 * sigma), np.full(k, cl - 3 * sigma)


def _mr_limits(
    cl: float, y: np.ndarray, n: np.ndarray | None,
    mask: np.ndarray, subgroup_n: int | None = None, **_,
) -> tuple[np.ndarray, np.ndarray]:
    """MR chart: UCL = D4·MR̄, no LCL (D3 = 0 for n = 2). Montgomery (2019), §6.3."""
    k = len(y)
    return np.full(k, D4[2] * cl), np.full(k, np.nan)


def _p_limits(
    cl: float, y: np.ndarray, n: np.ndarray | None,
    mask: np.ndarray, subgroup_n: int | None = None, **_,
) -> tuple[np.ndarray, np.ndarray]:
    """p chart: σ_i = √(p̄(1−p̄)/n_i). Montgomery (2019), §7.2."""
    sigma = np.sqrt(cl * (1.0 - cl) / np.where(n > 0, n, np.nan))
    return cl + 3 * sigma, cl - 3 * sigma


def _u_limits(
    cl: float, y: np.ndarray, n: np.ndarray | None,
    mask: np.ndarray, subgroup_n: int | None = None, **_,
) -> tuple[np.ndarray, np.ndarray]:
    """u chart: σ_i = √(ū/n_i). Montgomery (2019), §7.3."""
    sigma = np.sqrt(cl / np.where(n > 0, n, np.nan))
    return cl + 3 * sigma, cl - 3 * sigma


def _c_limits(
    cl: float, y: np.ndarray, n: np.ndarray | None,
    mask: np.ndarray, subgroup_n: int | None = None, **_,
) -> tuple[np.ndarray, np.ndarray]:
    """c chart: σ = √c̄. Montgomery (2019), §7.3."""
    sigma = math.sqrt(max(cl, 0.0))
    k = len(y)
    return np.full(k, cl + 3 * sigma), np.full(k, cl - 3 * sigma)


def _s_limits(
    cl: float, y: np.ndarray, n: np.ndarray | None,
    mask: np.ndarray, subgroup_n: int | None = None, sigma_hat: float | None = None, **_,
) -> tuple[np.ndarray, np.ndarray] | tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    S chart: UCL = B4(nᵢ)·S̄, LCL = B3(nᵢ)·S̄, CL = S̄. Montgomery (2019), §6.4.

    With unequal subgroup sizes the caller supplies a pooled σ̂ instead, and the whole
    chart is expressed against that unbiased σ̂ rather than against a c4-biased S̄:

        CL  = c4(nᵢ)·σ̂                       (returned as the third element)
        U/L = CL ± 3σ̂·√(1 − c4(nᵢ)²)

    The center line has to vary too. E[sᵢ] = c4(nᵢ)·σ̂ climbs from 0.798σ̂ at n=2 to
    0.991σ̂ at n=30, so a flat CL would park every small subgroup below the line and
    every large one above it — and compute() feeds the CL to the runs detector, which
    is a pure side-of-CL test. Any series whose subgroup size drifts with time would
    manufacture a long run out of nothing but its denominators.
    """
    sizes = _subgroup_sizes(n, subgroup_n, len(y), "S chart")

    if sigma_hat is not None:
        c = _get_constants(sizes, c4)
        cl_i = sigma_hat * c
        half = 3.0 * sigma_hat * np.sqrt(np.maximum(0.0, 1.0 - c * c))
        return cl_i + half, np.maximum(0.0, cl_i - half), cl_i

    return _get_constants(sizes, b4) * cl, _get_constants(sizes, b3) * cl


def _g_limits(
    cl: float, y: np.ndarray, n: np.ndarray | None,
    mask: np.ndarray, subgroup_n: int | None = None, **_,
) -> tuple[np.ndarray, np.ndarray]:
    """g chart: σ = √(CL·(CL+1)). Provost & Murray (2011), §8."""
    sigma = math.sqrt(max(cl * (cl + 1.0), 0.0))
    k = len(y)
    return np.full(k, cl + 3 * sigma), np.full(k, cl - 3 * sigma)


def _laney_sigma_z(
    y: np.ndarray, cl: float, sigma_base: np.ndarray, mask: np.ndarray,
) -> float:
    """
    Overdispersion factor σ_z for Laney p'/u' charts. Laney (2002).

    σ_z = MR̄(z)/d2 measures how far the point-to-point variation of the
    standardised residuals exceeds what the binomial/Poisson model predicts.
    Floored at 1.0: the method exists to *widen* limits under overdispersion,
    so an underdispersed sample must fall back to the ordinary p/u limits
    rather than tighten below them and manufacture signals.
    """
    z = (y - cl) / np.where(sigma_base > 0, sigma_base, np.nan)
    z_valid = z[mask & ~np.isnan(z)]
    if len(z_valid) > 1:
        return max(1.0, float(np.nanmean(_moving_ranges(z_valid))) / D2[2])
    return 1.0


def _pp_limits(
    cl: float, y: np.ndarray, n: np.ndarray | None,
    mask: np.ndarray, subgroup_n: int | None = None, **_,
) -> tuple[np.ndarray, np.ndarray]:
    """Laney p' chart: σ'_i = √(p̄(1−p̄)/n_i) · σ_z, σ_z floored at 1.0. Laney (2002)."""
    sigma_base = np.sqrt(cl * (1.0 - cl) / np.where(n > 0, n, np.nan))
    sigma = sigma_base * _laney_sigma_z(y, cl, sigma_base, mask)
    return cl + 3 * sigma, cl - 3 * sigma


def _up_limits(
    cl: float, y: np.ndarray, n: np.ndarray | None,
    mask: np.ndarray, subgroup_n: int | None = None, **_,
) -> tuple[np.ndarray, np.ndarray]:
    """Laney u' chart: σ'_i = √(ū/n_i) · σ_z, σ_z floored at 1.0. Laney (2002)."""
    sigma_base = np.sqrt(cl / np.where(n > 0, n, np.nan))
    sigma = sigma_base * _laney_sigma_z(y, cl, sigma_base, mask)
    return cl + 3 * sigma, cl - 3 * sigma


def _oe_limit_pair(
    cl: float, n: np.ndarray | None, p_lower: float, p_upper: float,
    z: float, limit_method: str,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Funnel limits for an O/E chart at one probability contour, on the O/E scale.

    With Eᵢ expected events and θ₀ the center line, the count of observed events is
    modelled Poisson(λᵢ = θ₀·Eᵢ); the limit is that distribution's quantile divided
    back through Eᵢ. Dividing by Eᵢ is what makes the funnel narrow as volume grows
    while the underlying count distribution widens.

    Unlike the p/u charts these limits are asymmetric about the center line, which is
    the whole point at low volume: a physician with 3 expected deaths has a very
    different amount of room above the line than below it, and the normal
    approximation would give them the same and then clip the lower limit at zero.
    """
    e = np.asarray(n, dtype=float)
    e = np.where(e > 0, e, np.nan)
    lam = cl * e

    ucl = np.empty(len(e), dtype=float)
    lcl = np.empty(len(e), dtype=float)
    exact = limit_method != "byar"
    for i, lam_i in enumerate(lam):
        if exact and lam_i <= _EXACT_MAX_LAMBDA:
            ucl[i] = poisson_quantile_interp(p_upper, lam_i)
            lcl[i] = poisson_quantile_interp(p_lower, lam_i)
        else:
            ucl[i] = byar_quantile(lam_i, z, upper=True)
            lcl[i] = byar_quantile(lam_i, z, upper=False)

    return ucl / e, lcl / e


def _oe_limits(
    cl: float, y: np.ndarray, n: np.ndarray | None,
    mask: np.ndarray, subgroup_n: int | None = None,
    limit_method: str = "exact", **_,
) -> tuple[np.ndarray, np.ndarray]:
    """O/E (SMR) chart: 99.8% Poisson funnel limits. Spiegelhalter (2005), §3.2."""
    return _oe_limit_pair(cl, n, 0.001, 0.999, Z_998, limit_method)


def _oe_limits_95(
    cl: float, y: np.ndarray, n: np.ndarray | None,
    mask: np.ndarray, subgroup_n: int | None = None,
    limit_method: str = "exact", **_,
) -> tuple[np.ndarray, np.ndarray]:
    """O/E (SMR) chart: 95% Poisson funnel limits. Spiegelhalter (2005), §3.2."""
    return _oe_limit_pair(cl, n, 0.025, 0.975, Z_95, limit_method)


def oe_dispersion_phi(
    cl: float, y: np.ndarray, n: np.ndarray | None, mask: np.ndarray,
) -> float:
    """
    Winsorized multiplicative over-dispersion factor φ̂. Spiegelhalter, Quality &
    Safety in Health Care 2005;14:347-351.

    Across a few hundred providers, exact Poisson limits routinely flag far more than
    the nominal 0.2%: real providers differ from one another for reasons the risk
    model does not capture, so the counts are over-dispersed relative to Poisson.
    φ̂ measures that excess and widens the limits by √φ̂.

    Standardised residuals use the Poisson variance-stabilising transform
    z = 2(√O − √(θ₀E)), which is far closer to standard normal at small expected
    counts than the Pearson residual (O − θ₀E)/√(θ₀E). Since the whole reason this
    chart type exists is small-volume providers, a residual that is skewed exactly
    there would inflate φ̂ on distributional shape rather than on real dispersion.

    The z's are winsorized at the 10th and 90th percentiles before squaring. Without
    that, the genuine outliers being screened for would inflate φ̂ enough to widen the
    limits past themselves — the estimate has to describe the background variation,
    not the exceptions.

    Returns 1.0 (no adjustment) when φ̂ is within 2 standard errors of 1 under the
    null, i.e. φ̂ ≤ 1 + 2√(2/K). Like Laney's σ_z, this only ever widens: an
    under-dispersed sample falls back to the unadjusted limits rather than tightening
    below them and manufacturing signals.

    Caveat on small cohorts: winsorizing protects φ̂ from an outlier's own residual,
    but the pooled ΣO/ΣE center line is not itself robust. Across a dozen providers
    one extreme performer drags that line toward itself, which leaves every other
    provider sitting systematically to one side of it and inflates φ̂ anyway. Passing
    cl= (typically 1.0, the risk model's own benchmark) anchors the center line and
    removes the effect. With a few hundred providers it is negligible.
    """
    if n is None:
        raise ValueError("Over-dispersion adjustment requires expected events (n=).")

    e = np.asarray(n, dtype=float)
    observed = np.asarray(y, dtype=float) * e  # y arrives as the O/E ratio
    with np.errstate(invalid="ignore"):
        z = 2.0 * (np.sqrt(observed) - np.sqrt(cl * e))

    z_valid = z[mask & np.isfinite(z)]
    k = len(z_valid)
    if k < 2:
        return 1.0

    lo, hi = np.percentile(z_valid, [10.0, 90.0])
    phi = float(np.mean(np.clip(z_valid, lo, hi) ** 2))

    return phi if phi > 1.0 + 2.0 * math.sqrt(2.0 / k) else 1.0


def oe_detectable_ratio(t_count: float, e: float) -> float:
    """
    Smallest true O/E this point has an 80% chance of flagging.

    A funnel at physician volumes is mostly a test with no power. A physician with
    5 expected deaths who is genuinely twice as deadly as predicted is flagged about
    a fifth of the time; the other four fifths the chart says nothing and a reader
    concludes the performance was acceptable. This function makes that limit visible
    per point, so "no signal" can be read against what a signal would have required.

    t_count is the drawn upper limit on the *count* scale (ucl · E). _sigma_signals
    flags strictly y > ucl, so an integer count flags iff O ≥ floor(t_count) + 1, and
    the power at true ratio ρ is P(X > floor(t_count); ρE). Setting that to 0.8 and
    inverting the CDF in its mean gives the answer exactly — no search over ratios.

    80% is the conventional power target and is deliberately not a parameter: on a
    chart that feeds credentialing, a tunable detectability threshold is an invitation
    to report whichever number reads best.

    Returns NaN when the point has no usable expected count.
    """
    if not (e > 0) or math.isnan(e) or math.isnan(t_count) or math.isinf(t_count):
        return math.nan

    m = math.floor(t_count)
    if m < 0:
        return math.nan

    if m <= _MEAN_SOLVE_MAX_K:
        lam_star = poisson_mean_for_cdf(int(m), 0.2)
    else:
        # Normal approximation with a continuity correction, solving
        # λ − Z_80·√λ = m + 0.5 as a quadratic in √λ. Only reachable at counts where
        # the two agree to ~1e-5 relative, and where power is ~1 for any ratio a
        # reader would care about.
        s = (Z_80 + math.sqrt(Z_80 * Z_80 + 4.0 * (m + 0.5))) / 2.0
        lam_star = s * s

    return lam_star / e


def oe_point_ci(o: float, e: float) -> tuple[float, float]:
    """
    Exact (Garwood) 95% confidence interval for this point's own O/E ratio.

    Distinct from the funnel band, and the distinction matters: the band answers
    "where would this point fall if the risk model were right and this provider were
    average", while this interval answers "given what this provider actually did, what
    range of true O/E is consistent with it". The band is a property of the null; the
    interval is a property of the point, and does not move when θ₀ does.

    Garwood's construction inverts the exact Poisson test: the lower bound is the mean
    at which observing this many events or more has probability 0.025, the upper bound
    the mean at which observing this many or fewer has probability 0.025. Zero observed
    events gives a lower bound of exactly 0 and an upper bound of −ln(0.025)/E.

    Falls back to Byar's closed form when the count is not an integer (an aggregate
    that has been averaged rather than summed) or is large enough that the bisection
    stops being worth its cost; both are outside the small-count regime where exactness
    is the whole point.
    """
    if not (e > 0) or math.isnan(e) or math.isnan(o) or o < 0:
        return (math.nan, math.nan)

    o_r = round(o)
    integral = abs(o - o_r) <= 1e-9 * max(1.0, abs(o))

    if integral and o_r <= _MEAN_SOLVE_MAX_K:
        mu_lower = 0.0 if o_r == 0 else poisson_mean_for_cdf(int(o_r) - 1, 0.975)
        mu_upper = poisson_mean_for_cdf(int(o_r), 0.025)
    else:
        mu_lower = (
            0.0 if o <= 0
            else o * max(0.0, 1.0 - 1.0 / (9.0 * o) - Z_95 / (3.0 * math.sqrt(o))) ** 3
        )
        mu_upper = (o + 1.0) * (
            1.0 - 1.0 / (9.0 * (o + 1.0)) + Z_95 / (3.0 * math.sqrt(o + 1.0))
        ) ** 3

    return (mu_lower / e, mu_upper / e)


def _oep_limit_pair(
    cl: float, n: np.ndarray | None, phi: float, z: float,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Over-dispersed O/E limits: θ₀ ± z·√(φ̂·θ₀/Eᵢ).

    Necessarily a normal approximation — a multiplicative variance factor has no
    counterpart in an exact Poisson quantile, so the two do not compose. This is the
    same trade the Laney p′/u′ charts make, and the same one FunnelPlotR makes.
    """
    e = np.asarray(n, dtype=float)
    e = np.where(e > 0, e, np.nan)
    half = z * np.sqrt(phi * cl / e)
    return cl + half, cl - half


def _oep_limits(
    cl: float, y: np.ndarray, n: np.ndarray | None,
    mask: np.ndarray, subgroup_n: int | None = None, **_,
) -> tuple[np.ndarray, np.ndarray]:
    """Over-dispersed O/E chart: 99.8% limits. Spiegelhalter (2005), QSHC 14:347-351."""
    return _oep_limit_pair(cl, n, oe_dispersion_phi(cl, y, n, mask), Z_998)


def _oep_limits_95(
    cl: float, y: np.ndarray, n: np.ndarray | None,
    mask: np.ndarray, subgroup_n: int | None = None, **_,
) -> tuple[np.ndarray, np.ndarray]:
    """Over-dispersed O/E chart: 95% limits. Spiegelhalter (2005), QSHC 14:347-351."""
    return _oep_limit_pair(cl, n, oe_dispersion_phi(cl, y, n, mask), Z_95)


def _xbar_limits(
    cl: float, y: np.ndarray, n: np.ndarray | None,
    mask: np.ndarray, subgroup_n: int | None = None, s_bar: float | None = None,
    sigma_hat: float | None = None, **_,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Xbar chart: UCL = X̄̄ + A3(nᵢ)·S̄, LCL = X̄̄ − A3(nᵢ)·S̄. Montgomery (2019), §6.4.

    With unequal subgroup sizes the caller supplies a pooled σ̂ instead of S̄, and
    limits become X̄̄ ± 3σ̂/√nᵢ. The two estimators must not be mixed: A3 = 3/(c4√n)
    already embeds the correction for the bias of an *arithmetic* mean of subgroup
    SDs, so A3·σ̂ would over-correct and widen the limits by 1/c4(n).
    """
    sizes = _subgroup_sizes(n, subgroup_n, len(y), "xbar chart")

    if sigma_hat is not None:
        half = 3.0 * sigma_hat / np.sqrt(np.where(sizes >= 2, sizes, np.nan))
        return cl + half, cl - half

    if s_bar is None:
        raise ValueError("xbar chart requires s_bar (mean of subgroup SDs)")

    a3_vals = _get_constants(sizes, a3)
    return cl + a3_vals * s_bar, cl - a3_vals * s_bar


# ---------------------------------------------------------------------------
# Chart spec + dispatch table
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChartSpec:
    """Everything needed to compute one chart type."""
    center: Callable    # (y_base, n_base) → float
    limits: Callable    # (cl, y, n, mask, subgroup_n, **_) → (ucl_arr, lcl_arr[, cl_arr])
                        # An optional third element overrides the scalar center line
                        # per point — see _s_limits and compute().
    needs_n: bool = False
    is_attribute: bool = False
    floor_lcl: bool = False
    limits_95: Callable | None = None
                        # Same signature as limits. Only for charts whose inner band
                        # is a genuine probability contour rather than 2/3 of the
                        # outer one — see compute() and _oe_limits_95. None means the
                        # caller derives the 95% band arithmetically as before.


CHARTS: dict[str, ChartSpec] = {
    "run":  ChartSpec(_cl_median, _no_limits),
    "i":    ChartSpec(_cl_mean,   _i_limits),
    "ip":   ChartSpec(_cl_weighted, _i_limits, needs_n=True, is_attribute=True),
    "mr":   ChartSpec(_cl_mean,   _mr_limits),
    "s":    ChartSpec(_cl_mean,   _s_limits,  floor_lcl=True),
    "p":    ChartSpec(_cl_weighted, _p_limits,  needs_n=True, is_attribute=True, floor_lcl=True),
    "u":    ChartSpec(_cl_weighted, _u_limits,  needs_n=True, is_attribute=True, floor_lcl=True),
    "c":    ChartSpec(_cl_mean,   _c_limits,  floor_lcl=True),
    "g":    ChartSpec(_cl_median, _g_limits,  floor_lcl=True),
    "pp":   ChartSpec(_cl_weighted, _pp_limits, needs_n=True, is_attribute=True, floor_lcl=True),
    "up":   ChartSpec(_cl_weighted, _up_limits, needs_n=True, is_attribute=True, floor_lcl=True),
    "xbar": ChartSpec(_cl_grand_mean, _xbar_limits),
    "oe":   ChartSpec(_cl_weighted, _oe_limits, needs_n=True, is_attribute=True,
                      floor_lcl=True, limits_95=_oe_limits_95),
    "oep":  ChartSpec(_cl_weighted, _oep_limits, needs_n=True, is_attribute=True,
                      floor_lcl=True, limits_95=_oep_limits_95),
}

VALID_CHARTS = set(CHARTS) | {"t"}
