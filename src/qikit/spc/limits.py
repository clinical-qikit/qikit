"""
limits.py — center-line and control-limit functions per chart type.

Each chart type is a ChartSpec with two functions: center and limits.
No routing, no string dispatch. Adding a chart = two small functions + one dict entry.

Funnel charts (p/pp/u/up with funnel=True, and oe/oep) follow Spiegelhalter [1]. The
numbered references below are those of docs/methods.md, which records every design
choice made here and each place it departs from the source.

References
----------
    Montgomery DC. Introduction to Statistical Quality Control, 8th ed. Wiley, 2019.
    Provost LP, Murray SK. The Health Care Data Guide, 2nd ed. Jossey-Bass, 2022.
[1] Spiegelhalter DJ. Funnel plots for comparing institutional performance.
    Statistics in Medicine 2005;24(8):1185-1202.
[2] Spiegelhalter DJ. Handling over-dispersion of performance indicators.
    Quality & Safety in Health Care 2005;14:347-351.
[3] DerSimonian R, Laird N. Meta-analysis in clinical trials. Controlled Clinical
    Trials 1986;7:177-188.
[6] Laney DB. Improved control charts for attributes. Quality Engineering 14(4), 2002.
[7] Clayton D, Kaldor J. Empirical Bayes estimates of age-standardized relative risks
    for use in disease mapping. Biometrics 1987;43:671-681.
[16] Korn EL, Graubard BI. Confidence intervals for proportions with small expected
    number of positive counts estimated from survey data. Survey Methodology
    1998;24(2):193-201.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist
from typing import Callable

import numpy as np

from .constants import D2, D4, Z_80, Z_95, Z_998, a3, b3, b4, c4
from .dist import (
    _BISECT_ITERS,
    _EXACT_MAX_LAMBDA,
    _MEAN_SOLVE_MAX_K,
    _walk_terms,
    beta_binomial_quantiles,
    binomial_cdf,
    binomial_quantiles,
    binomial_theta_for_cdf,
    byar_quantile,
    poisson_gamma_quantiles,
    poisson_mean_for_cdf,
    poisson_quantile_interp,
)

# The two contours every funnel draws [1, §2]: (lower tail, upper tail, normal deviate).
# The outer pair drives sigma_signal; the inner one is the 95% warn band. Both are
# the defaults of funnel(limits=), which can move them (e.g. to 99.7%).
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


def _poisson_funnel_pair(
    cl: float, n: np.ndarray | None, p_lower: float, p_upper: float,
    z: float, limit_method: str,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Poisson funnel limits at one probability contour, on the rate (or O/E) scale.

    With nᵢ the denominator and θ₀ the center line, the count of events is modelled
    Poisson(λᵢ = θ₀·nᵢ); the limit is that distribution's quantile divided back
    through nᵢ [1, A.2.1]. For an O/E chart nᵢ is the expected events Eᵢ; for a u
    funnel it is the exposure, which [1, A.2.3] treats the same way. Dividing by nᵢ is
    what makes the funnel narrow as volume grows while the count distribution widens.

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
            ucl[i] = poisson_quantile_interp(p_upper, lam_i) + 1.0
            lcl[i] = poisson_quantile_interp(p_lower, lam_i)
        else:
            ucl[i] = byar_quantile(lam_i, z, upper=True)
            lcl[i] = byar_quantile(lam_i, z, upper=False)

    return ucl / e, lcl / e


def _poisson_funnel_limits(
    cl: float, y: np.ndarray, n: np.ndarray | None,
    mask: np.ndarray, subgroup_n: int | None = None,
    limit_method: str = "exact", levels: tuple = DEFAULT_LEVELS, **_,
) -> tuple[np.ndarray, np.ndarray]:
    """O/E chart and u funnel: outer (99.8%) exact Poisson limits [1, A.2.1]."""
    return _poisson_funnel_pair(cl, n, *contour(levels[0]), limit_method)


def _poisson_funnel_limits_95(
    cl: float, y: np.ndarray, n: np.ndarray | None,
    mask: np.ndarray, subgroup_n: int | None = None,
    limit_method: str = "exact", levels: tuple = DEFAULT_LEVELS, **_,
) -> tuple[np.ndarray, np.ndarray]:
    """O/E chart and u funnel: inner (95%) exact Poisson limits [1, A.2.1]."""
    return _poisson_funnel_pair(cl, n, *contour(levels[1]), limit_method)


def _binomial_funnel_pair(
    cl: float, n: np.ndarray | None, p_lower: float, p_upper: float, z: float,
    diag: dict | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Exact binomial funnel limits at one contour, on the proportion scale [1, A.1.1].

    Asymmetric about the center line, as the Poisson pair is, and for the same reason:
    a physician with 30 patients at a 10% event rate has room for 9 events above
    expected but only 3 below. A non-integer denominator (ν = n/φ under
    within_dispersion) is interpolated between its whole neighbours
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


def _p_funnel_limits(
    cl: float, y: np.ndarray, n: np.ndarray | None,
    mask: np.ndarray, subgroup_n: int | None = None, diag: dict | None = None,
    levels: tuple = DEFAULT_LEVELS, **_,
) -> tuple[np.ndarray, np.ndarray]:
    """p funnel: outer (99.8%) exact binomial limits [1, A.1.1]."""
    return _binomial_funnel_pair(cl, n, *contour(levels[0]), diag)


def _p_funnel_limits_95(
    cl: float, y: np.ndarray, n: np.ndarray | None,
    mask: np.ndarray, subgroup_n: int | None = None, diag: dict | None = None,
    levels: tuple = DEFAULT_LEVELS, **_,
) -> tuple[np.ndarray, np.ndarray]:
    """p funnel: inner (95%) exact binomial limits [1, A.1.1]."""
    return _binomial_funnel_pair(cl, n, *contour(levels[1]), diag)


# Spiegelhalter winsorizes 10% from each tail [1, eq. 6].
_WINSOR_P = 0.10


def winsor_consistency(p: float = _WINSOR_P) -> float:
    """
    c(p) = 1 / E[Z_W²] for Z ~ N(0, 1) winsorized at its p and 1 − p quantiles [1, eq. 9]:
    E[Z_W²] = (1 − 2p) − 2z·φ(z) + 2p·z², z = Φ⁻¹(1 − p). c(0.10) = 1.4735.
    """
    z = NormalDist().inv_cdf(1.0 - p)
    pdf = math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
    return 1.0 / ((1.0 - 2.0 * p) - 2.0 * z * pdf + 2.0 * p * z * z)


_WINSOR_CONSISTENCY = winsor_consistency(_WINSOR_P)

# τ estimators of funnel(tau_method=) and qic(tau_method=); methods §4.16.
TAU_METHODS = ("winsorized", "spiegelhalter", "ml")


def funnel_dispersion(
    cl: float, y: np.ndarray, n: np.ndarray | None, mask: np.ndarray, family: str,
    method: str = "winsorized",
) -> tuple[float, float]:
    """
    Spiegelhalter's over-dispersion estimate for a funnel: returns (φ̂, τ̂²).

    method="winsorized" (the default everywhere) multiplies mean(z_W²) by the Gaussian
    consistency factor c(0.10) = 1.4735 of [1, eq. 9] before the τ² = 0 gate, so φ̂
    averages 1 rather than 0.68 under pure chance (methods §4.3). method="spiegelhalter"
    leaves it out, exactly as published [1, §5] and as FunnelPlotR and CQC compute it;
    the shared fixtures that check the published numbers pin it. Each choice is recorded
    in docs/methods.md:

    - Pearson residuals on the natural scale, zᵢ = (yᵢ − θ₀)/√V₀ᵢ [1, eq. 4], where
      V₀ᵢ = θ₀/nᵢ for counts ("poisson": u, oe) and θ₀(1 − θ₀)/nᵢ for proportions
      ("binomial": p). The natural scale is what makes τ² slot straight into the
      variance V₀ᵢ + τ² of [1, eq. 11].
    - 10% winsorizing, φ̂ = mean(z_W²) [1, eqs. 6, 8], so the outliers being screened
      for cannot widen the limits past themselves.
    - The debiasing factor. Winsorizing shrinks the variance of a normal sample to 0.68
      of its value, and [1, eq. 9] gives the correction w(0.10) = 1.47. [1] found it
      gave "somewhat wide limits" at its dozen-provider example and did not adopt it;
      without it φ̂ averages about 0.68 under pure chance and τ̂ is 0 at a true τ = 0.10
      across 1,000 physicians (methods §4.3), which is why it is the default.
    - The additive random-effects variance by the method of moments [1, eq. 10; 3],
      τ̂² = (Kφ̂ − (K−1)) / (Σwᵢ − Σwᵢ²/Σwᵢ) with wᵢ = 1/V₀ᵢ, and τ̂² = 0 whenever
      φ̂ < (K−1)/K: no evidence of heterogeneity means none is assumed. It never goes
      negative, so an under-dispersed sample keeps its unadjusted limits.

    τ̂ is the standard deviation of providers' true rates (or true O/E) around θ₀ that
    the null model does not explain, on the raw, pre-multiply scale.

    Caveat on small cohorts: winsorizing protects φ̂ from an outlier's own residual,
    but the pooled center line is not itself robust. Across a dozen providers one
    extreme performer drags it toward itself, leaving every other provider to one side
    and inflating φ̂ anyway. Passing cl= (for O/E typically 1.0, the risk model's own
    benchmark) anchors the line and removes the effect.

    φ̂ is NaN when fewer than two points carry a usable residual.
    """
    if n is None:
        raise ValueError("Over-dispersion estimation requires denominators (n=).")

    e = np.asarray(n, dtype=float)
    v0 = cl / e if family == "poisson" else cl * (1.0 - cl) / e
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (np.asarray(y, dtype=float) - cl) / np.sqrt(v0)
        w = 1.0 / v0

    valid = mask & np.isfinite(z) & np.isfinite(w)
    z_valid = z[valid]
    k = len(z_valid)
    if k < 2:
        return math.nan, 0.0

    lo, hi = np.percentile(z_valid, [100.0 * _WINSOR_P, 100.0 * (1.0 - _WINSOR_P)])
    phi = float(np.mean(np.clip(z_valid, lo, hi) ** 2))
    if method == "winsorized":
        phi *= _WINSOR_CONSISTENCY

    if k * phi <= k - 1:
        return phi, 0.0
    wv = w[valid]
    sw = float(np.sum(wv))
    tau2 = (k * phi - (k - 1)) / (sw - float(np.sum(wv * wv)) / sw)
    return phi, max(0.0, tau2)


# Profile-likelihood 95% interval: the χ²₁ 0.95 point halved.
_ML_CI_DROP = 0.5 * 3.841458820694124
_ML_GRID = 80
_ML_ITERS = 60


_LGAMMA = np.frompyfunc(math.lgamma, 1, 1)


def _lgamma(x: np.ndarray) -> np.ndarray:
    """math.lgamma elementwise, on real arguments (numpy has no lgamma)."""
    return np.asarray(_LGAMMA(x), dtype=float)


def _mixture_loglik(tau: float, cl: float, o: np.ndarray, e: np.ndarray, family: str) -> float:
    """
    The marginal log-likelihood of counts o at denominators e under the chart's own
    random-effects model with spread tau around cl: Poisson–gamma (size cl²/τ²) for
    counts, beta-binomial (α + β = cl(1 − cl)/τ² − 1) for proportions; τ = 0 is the plain
    Poisson or binomial. Terms that do not involve τ are dropped. Real (effective)
    counts are allowed, through lgamma. −inf where no beta has that spread.
    """
    if family == "poisson":
        mu = cl * e
        if tau <= 0:
            return float(np.sum(o * np.log(mu) - mu))
        r = cl * cl / (tau * tau)
        return float(np.sum(
            _lgamma(o + r) - math.lgamma(r) + r * np.log(r / (r + mu))
            + o * np.log(mu / (r + mu))
        ))
    if tau <= 0:
        return float(np.sum(o * math.log(cl) + (e - o) * math.log1p(-cl)))
    params = beta_params(cl, tau * tau)
    if params is None:
        return -math.inf
    a, b = params
    s = a + b
    return float(np.sum(
        _lgamma(o + a) + _lgamma(e - o + b) - _lgamma(e + s)
    ) + len(o) * (math.lgamma(s) - math.lgamma(a) - math.lgamma(b)))


def tau2_ml(
    cl: float, y: np.ndarray, n: np.ndarray, mask: np.ndarray, family: str,
) -> tuple[float, tuple[float, float]]:
    """
    τ̂² by maximum likelihood, with its profile-likelihood 95% interval for τ:
    returns (τ̂², (lo, hi)) (methods §4.16).

    The likelihood is the one the adjusted limits are drawn from (_mixture_loglik), with
    θ₀ = cl held fixed, as the moment estimator holds it. It uses every provider's whole
    count, needs no consistency factor, and on clean data returns exactly 0 when chance
    explains the spread best. It is not robust: nothing limits an outlier's pull, so a
    single gross outlier among 30 providers, or 3% among 150, inflates τ̂ and widens the
    limits it would have crossed (methods §4.16, §5). Searched on log τ (a grid, then
    golden section), with τ = 0 compared explicitly as the boundary. (0, (nan, nan))
    when fewer than two points carry a usable count.
    """
    e = np.asarray(n, dtype=float)
    yy = np.asarray(y, dtype=float)
    ok = mask & np.isfinite(yy) & np.isfinite(e) & (e > 0)
    o, e = yy[ok] * e[ok], e[ok]
    if family == "binomial":
        o = np.clip(o, 0.0, e)
    if len(o) < 2 or not (cl > 0) or (family == "binomial" and not (cl < 1)):
        return 0.0, (math.nan, math.nan)

    def ll(t):
        return _mixture_loglik(t, cl, o, e, family)

    top = 3.0 * cl if family == "poisson" else 0.999 * math.sqrt(cl * (1.0 - cl))
    grid = np.geomspace(1e-4 * top, top, _ML_GRID)
    vals = np.array([ll(t) for t in grid])
    j = int(np.argmax(vals))
    lo_t, hi_t = grid[max(j - 1, 0)], grid[min(j + 1, len(grid) - 1)]
    g = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = math.log(lo_t), math.log(hi_t)
    for _ in range(_ML_ITERS):
        c, d = b - g * (b - a), a + g * (b - a)
        if ll(math.exp(c)) >= ll(math.exp(d)):
            b = d
        else:
            a = c
    t_hat = math.exp(0.5 * (a + b))
    l_hat = ll(t_hat)
    l_zero = ll(0.0)
    if l_zero >= l_hat:
        t_hat, l_hat = 0.0, l_zero
    target = l_hat - _ML_CI_DROP

    def crossing(inside, outside):
        # Bisection on log τ between a point above the target and one below it.
        lo, hi = math.log(inside), math.log(outside)
        for _ in range(_ML_ITERS):
            mid = 0.5 * (lo + hi)
            if ll(math.exp(mid)) >= target:
                lo = mid
            else:
                hi = mid
        return math.exp(0.5 * (lo + hi))

    anchor = t_hat if t_hat > 0 else grid[0]
    if l_zero >= target:
        ci_lo = 0.0
    else:
        below = [t for t in grid if t < anchor and ll(t) < target]
        ci_lo = crossing(anchor, below[-1]) if below else 0.0
    above = [t for t in grid if t > anchor and ll(t) < target]
    ci_hi = crossing(anchor, above[0]) if above else math.inf
    return t_hat * t_hat, (ci_lo, ci_hi)


# The dispersion-shape test (dispersion_shape below) calls clumping "within" when the
# likelihood ratio for an intercept above 1 clears the 0.1% χ²₁ point and the
# intercept itself, an estimate of φ, is at least 2. Set by simulation (methods §5):
# no false calls in 1,000+ runs of Poisson, binary-outcome and between-provider-only
# data (including heavy-tailed, lognormal provider effects) at K = 40, 200 and 1000,
# and every call on aggregated length-of-stay data with φ = 3 at K = 1000 (90% at 200).
_SHAPE_LR = 10.827566170662733  # χ²₁ 0.999 quantile
_SHAPE_MIN_PHI = 2.0
_SHAPE_MIN_K = 30
_SHAPE_CAP = 9.0               # a residual is capped at 3 of its own SDs


def _variance_line(z2: np.ndarray, e: np.ndarray, a_fixed: float | None,
                   b_free: bool = True) -> tuple[float, float, float]:
    """
    Fit Var(z) = a + b·e by iteratively reweighted least squares on z², the normal
    likelihood's own scoring step, with each z² capped at _SHAPE_CAP of its fitted
    variance so a genuine outlier cannot pose as spread. Returns (a, b, −2 log L up to
    a constant). a_fixed pins the intercept; b_free=False pins the slope at 0.
    """
    a = 1.0 if a_fixed is None else a_fixed
    b = 0.0
    for _ in range(60):
        v = a + b * e
        w = 1.0 / (v * v)
        zc = np.minimum(z2, _SHAPE_CAP * v)
        if a_fixed is None and b_free:
            x = np.column_stack([np.ones_like(e), e])
            xw = x * w[:, None]
            a, b = np.linalg.lstsq(x.T @ xw, xw.T @ zc, rcond=None)[0]
            a, b = max(float(a), 1e-3), max(float(b), 0.0)
        elif a_fixed is None:
            a = max(float(np.sum(w * zc) / np.sum(w)), 1e-3)
        else:
            b = max(0.0, float(np.sum(w * e * (zc - a)) / np.sum(w * e * e)))
    v = a + b * e
    zc = np.minimum(z2, _SHAPE_CAP * v)
    return a, b, float(np.sum(np.log(v) + zc / v))


def dispersion_shape(
    cl: float, y: np.ndarray, n: np.ndarray, mask: np.ndarray, family: str,
) -> dict:
    """
    Where a funnel's extra spread comes from, read off how it grows with volume.

    The Pearson residual zᵢ (as funnel_dispersion forms it) has variance
    a + b·nᵢ/… in two separable parts:

    - **within** — counts that clump inside each unit (patient-days: one stay adds
      many days at once) inflate every provider's variance by the same factor φ,
      whatever its volume: a = φ.
    - **between** — real differences between providers add τ² on the rate scale,
      which is nᵢτ²/V₀ on the z scale: it grows with volume, b > 0.

    The additive τ² of funnel_dispersion only models the second, so the first passes
    straight through to over-flag small providers. Fitting both by maximum likelihood
    (each residual capped at 3 of its own SDs) separates them: "within" when an
    intercept above 1 is significant (likelihood ratio > χ²₁ 0.999) and estimates
    φ ≥ 2, "between" when a slope above 0 is significant at the same level. Returns
    {"dispersion_shape": "none" | "between" | "within" | "both" | "unknown",
     "within_dispersion_hint": â}: "unknown" when the largest volume is under 1.5 times
    the smallest, too narrow a range to separate the two; {} with fewer than 30
    usable points, below the K the thresholds were calibrated at.
    """
    e = np.asarray(n, dtype=float)
    v0 = cl / e if family == "poisson" else cl * (1.0 - cl) / e
    with np.errstate(divide="ignore", invalid="ignore"):
        z2 = (np.asarray(y, dtype=float) - cl) ** 2 / v0
        scale = e / np.nanmedian(np.where(mask & (e > 0), e, np.nan))
    ok = mask & np.isfinite(z2) & np.isfinite(scale) & (scale > 0)
    if int(np.sum(ok)) < _SHAPE_MIN_K:
        return {}
    z2, scale = z2[ok], scale[ok]
    if float(scale.max()) < 1.5 * float(scale.min()):
        # Too little spread in volume to tell a constant factor from a slope.
        a_flat, _, _ = _variance_line(z2, scale, None, b_free=False)
        return {"dispersion_shape": "unknown", "within_dispersion_hint": round(a_flat, 2)}
    a1, b1, full = _variance_line(z2, scale, None)
    _, _, unit_a = _variance_line(z2, scale, 1.0)
    _, _, flat = _variance_line(z2, scale, None, b_free=False)
    within = (unit_a - full) > _SHAPE_LR and a1 >= _SHAPE_MIN_PHI
    between = (flat - full) > _SHAPE_LR
    shape = {(False, False): "none", (False, True): "between",
             (True, False): "within", (True, True): "both"}[(within, between)]
    return {"dispersion_shape": shape, "within_dispersion_hint": round(a1, 2)}


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


def _integer_count(x: float) -> int | None:
    """x as an int when it is one to within float noise, else None."""
    r = round(x)
    return int(r) if abs(x - r) <= 1e-9 * max(1.0, abs(x)) else None


def binomial_detectable_rate(t_count: float, n: float) -> float:
    """
    Smallest true proportion this point has an 80% chance of flagging on a p funnel.

    The binomial twin of oe_detectable_ratio, and exact in the same way: an integer
    count flags iff X ≥ floor(t_count) + 1, so the answer is the θ at which
    F(floor(t_count); n, θ) = 0.2, found by inverting the CDF in θ. A u funnel needs
    no twin: its counts are Poisson, and oe_detectable_ratio(ucl·n, n) is already the
    detectable rate.

    Returns inf when no count can flag at all — the upper limit sits at or above n,
    which happens at a handful of cases against a high center line — and NaN when the
    point has no usable denominator. A non-integer n (ν = n/φ under within_dispersion)
    interpolates the chance of flagging in ν between its whole neighbours, as the
    limits do (§4.13).
    """
    if not (n > 0) or math.isnan(t_count) or math.isinf(t_count):
        return math.nan
    m = _integer_count(n)
    if m is None:
        return _fractional_detectable_rate(t_count / n, n)
    thr = math.floor(t_count)
    if thr < 0:
        return math.nan
    if thr >= m:
        return math.inf
    return binomial_theta_for_cdf(int(thr), m, 0.2)


def binomial_point_ci(x: float, n: float) -> tuple[float, float]:
    """
    Exact (Clopper–Pearson) 95% confidence interval for this point's own proportion.

    The binomial counterpart of oe_point_ci's Garwood interval, and the same
    construction: the lower bound is the θ at which x or more events has probability
    0.025, the upper the θ at which x or fewer does. x = 0 gives a lower bound of
    exactly 0 and x = n an upper bound of exactly 1. A non-integer count or
    denominator (an effective count under within_dispersion) takes the same
    construction on the interpolated tails (_fractional_point_ci).
    """
    if not (n > 0) or math.isnan(x) or x < 0 or x > n:
        return (math.nan, math.nan)
    m = _integer_count(n)
    k = _integer_count(x)
    if m is None or k is None:
        return _fractional_point_ci(x, n)
    lo = 0.0 if k == 0 else binomial_theta_for_cdf(k - 1, m, 0.975)
    hi = 1.0 if k == m else binomial_theta_for_cdf(k, m, 0.025)
    return (lo, hi)


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
# interpolated linearly in ν between the whole neighbours m₀ = ⌊ν⌋ and m₁ = m₀ + 1, at
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


def _fractional_detectable_rate(ucl: float, nu: float) -> float:
    """
    binomial_detectable_rate at a fractional ν: the θ at which the chance of landing
    beyond the drawn upper contour ucl, interpolated in ν between m₀ and m₁ as the
    tails are, is 80%. inf when it never reaches 80%.
    """
    m0 = int(math.floor(nu))
    w = nu - m0
    thr0 = math.floor(ucl * m0)
    thr1 = math.floor(ucl * (m0 + 1))

    def miss(theta):
        return (1.0 - w) * binomial_cdf(thr0, m0, theta) + w * binomial_cdf(thr1, m0 + 1, theta)

    if miss(1.0) > 0.2:
        return math.inf
    lo, hi = 0.0, 1.0
    for _ in range(_BISECT_ITERS):
        mid = 0.5 * (lo + hi)
        if miss(mid) > 0.2:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _fractional_point_ci(x: float, nu: float) -> tuple[float, float]:
    """
    The 95% interval of binomial_point_ci at a fractional count or denominator, built
    the same way from the interpolated binomial tails: the effective-sample-size
    Clopper–Pearson interval of Korn and Graubard for clustered data [16].
    """
    def tails(theta):
        return fractional_binomial_tails(x, nu, theta, 0.0)

    if tails(0.5) is None:
        return math.nan, math.nan
    lo = 0.0
    if x > 0:
        a, b = 0.0, 1.0
        for _ in range(_BISECT_ITERS):
            mid = 0.5 * (a + b)
            if tails(mid)[1] < 0.025:
                a = mid
            else:
                b = mid
        lo = 0.5 * (a + b)
    hi = 1.0
    if x < nu:
        a, b = 0.0, 1.0
        for _ in range(_BISECT_ITERS):
            mid = 0.5 * (a + b)
            if tails(mid)[0] > 0.025:
                a = mid
            else:
                b = mid
        hi = 0.5 * (a + b)
    return lo, hi


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
        return _poisson_funnel_pair(cl, n, p_lower, p_upper, z, "exact")

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


def _counts_adjusted_limits(
    cl: float, y: np.ndarray, n: np.ndarray | None, mask: np.ndarray,
    subgroup_n: int | None = None, tau2: float = 0.0, diag: dict | None = None,
    levels: tuple = DEFAULT_LEVELS, **_,
) -> tuple[np.ndarray, np.ndarray]:
    """oep, and up with funnel=True: 99.8% Poisson–gamma limits [1, eq. 11; 7]."""
    return _mixture_funnel_pair(cl, n, tau2, "poisson", *contour(levels[0]), diag)


def _counts_adjusted_limits_95(
    cl: float, y: np.ndarray, n: np.ndarray | None, mask: np.ndarray,
    subgroup_n: int | None = None, tau2: float = 0.0, diag: dict | None = None,
    levels: tuple = DEFAULT_LEVELS, **_,
) -> tuple[np.ndarray, np.ndarray]:
    """oep, and up with funnel=True: 95% Poisson–gamma limits [1, eq. 11; 7]."""
    return _mixture_funnel_pair(cl, n, tau2, "poisson", *contour(levels[1]), diag)


def _proportions_adjusted_limits(
    cl: float, y: np.ndarray, n: np.ndarray | None, mask: np.ndarray,
    subgroup_n: int | None = None, tau2: float = 0.0, diag: dict | None = None,
    levels: tuple = DEFAULT_LEVELS, **_,
) -> tuple[np.ndarray, np.ndarray]:
    """pp with funnel=True: 99.8% beta-binomial limits [1, eq. 11]."""
    return _mixture_funnel_pair(cl, n, tau2, "binomial", *contour(levels[0]), diag)


def _proportions_adjusted_limits_95(
    cl: float, y: np.ndarray, n: np.ndarray | None, mask: np.ndarray,
    subgroup_n: int | None = None, tau2: float = 0.0, diag: dict | None = None,
    levels: tuple = DEFAULT_LEVELS, **_,
) -> tuple[np.ndarray, np.ndarray]:
    """pp with funnel=True: 95% beta-binomial limits [1, eq. 11]."""
    return _mixture_funnel_pair(cl, n, tau2, "binomial", *contour(levels[1]), diag)


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
                        # outer one — every funnel, and oe/oep. None means the caller
                        # derives the 95% band arithmetically as before.
    family: str | None = None
                        # The count model behind a funnel: "poisson" (u, oe) or
                        # "binomial" (p). When set, compute() estimates over-dispersion
                        # with funnel_dispersion() and reports it; None for every
                        # time-ordered chart.
    adjusted: bool = False
                        # Whether the limits take the estimated τ² (pp/up funnels, oep).


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
    "oe":   ChartSpec(_cl_weighted, _poisson_funnel_limits, needs_n=True, is_attribute=True,
                      floor_lcl=True, limits_95=_poisson_funnel_limits_95, family="poisson"),
    "oep":  ChartSpec(_cl_weighted, _counts_adjusted_limits, needs_n=True, is_attribute=True,
                      floor_lcl=True, limits_95=_counts_adjusted_limits_95, family="poisson",
                      adjusted=True),
}

# What p, pp, u and up become with funnel=True. A funnel is a cross-sectional comparison,
# so it takes Spiegelhalter's probability contours [1] rather than Shewhart's 3σ, and pp/up
# take his additive over-dispersion adjustment rather than Laney's: Laney's σ_z is built
# from moving ranges between consecutive points, which only means something in time
# order [6]. The time-ordered entries in CHARTS above are untouched.
FUNNEL_CHARTS: dict[str, ChartSpec] = {
    "p":  ChartSpec(_cl_weighted, _p_funnel_limits, needs_n=True, is_attribute=True,
                    floor_lcl=True, limits_95=_p_funnel_limits_95, family="binomial"),
    "pp": ChartSpec(_cl_weighted, _proportions_adjusted_limits, needs_n=True,
                    is_attribute=True, floor_lcl=True,
                    limits_95=_proportions_adjusted_limits_95, family="binomial",
                    adjusted=True),
    "u":  ChartSpec(_cl_weighted, _poisson_funnel_limits, needs_n=True, is_attribute=True,
                    floor_lcl=True, limits_95=_poisson_funnel_limits_95, family="poisson"),
    "up": ChartSpec(_cl_weighted, _counts_adjusted_limits, needs_n=True, is_attribute=True,
                    floor_lcl=True, limits_95=_counts_adjusted_limits_95, family="poisson",
                    adjusted=True),
}

VALID_CHARTS = set(CHARTS) | {"t"}
