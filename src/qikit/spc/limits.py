"""
limits.py — center-line and control-limit functions per chart type.

Each chart type is a ChartSpec with two functions: center and limits.
No routing, no string dispatch. Adding a chart = two small functions + one dict entry.

References
----------
1. Montgomery DC. Introduction to Statistical Quality Control, 8th ed. Wiley, 2019.
2. Provost LP, Murray SK. The Health Care Data Guide, 2nd ed. Jossey-Bass, 2022. ISBN 978-1-119-69013-9, 978-1-119-69012-2.
5. Laney DB. Improved control charts for attributes. Quality Engineering 14(4), 2002.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .constants import D2, D4, a3, b3, b4, c4

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
    return float(np.nanmean(mrs_screened)) if len(mrs_screened) > 0 else mr_bar


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
}

VALID_CHARTS = set(CHARTS) | {"t"}
