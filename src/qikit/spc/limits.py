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

from .constants import A3, B3, B4, D2, D4

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _moving_ranges(y: np.ndarray) -> np.ndarray:
    """Absolute successive differences. Length = len(y) - 1."""
    return np.abs(np.diff(y))


def _get_constants(n: np.ndarray, table: dict[int, float]) -> np.ndarray:
    """Map an array of subgroup sizes to an array of SPC constants."""
    return np.array([table.get(int(val), np.nan) for val in n])


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


# ---------------------------------------------------------------------------
# Limits functions:  (cl_val, y, n, mask, subgroup_n, **_) → (ucl_arr, lcl_arr)
#
# Every function returns two arrays of len(y).
# Charts without limits return NaN arrays.
# All functions accept **_ to silently ignore extra kwargs (e.g. s_bar).
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
    mask: np.ndarray, subgroup_n: int | None = None, **_,
) -> tuple[np.ndarray, np.ndarray]:
    """S chart: UCL = B4·S̄, LCL = B3·S̄. Montgomery (2019), §6.4."""
    if n is not None:
        b4_vals = _get_constants(n, B4)
        b3_vals = _get_constants(n, B3)
    elif subgroup_n is not None:
        b4_vals = np.full(len(y), B4.get(subgroup_n, np.nan))
        b3_vals = np.full(len(y), B3.get(subgroup_n, np.nan))
    else:
        raise ValueError("S chart requires subgroup size information.")

    return b4_vals * cl, b3_vals * cl


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
    """Overdispersion factor σ_z for Laney p'/u' charts. Laney (2002)."""
    z = (y - cl) / np.where(sigma_base > 0, sigma_base, np.nan)
    z_valid = z[mask & ~np.isnan(z)]
    if len(z_valid) > 1:
        return float(np.nanmean(_moving_ranges(z_valid))) / D2[2]
    return 1.0


def _pp_limits(
    cl: float, y: np.ndarray, n: np.ndarray | None,
    mask: np.ndarray, subgroup_n: int | None = None, **_,
) -> tuple[np.ndarray, np.ndarray]:
    """Laney p' chart: σ'_i = √(p̄(1−p̄)/n_i) · σ_z. Laney (2002)."""
    sigma_base = np.sqrt(cl * (1.0 - cl) / np.where(n > 0, n, np.nan))
    sigma = sigma_base * _laney_sigma_z(y, cl, sigma_base, mask)
    return cl + 3 * sigma, cl - 3 * sigma


def _up_limits(
    cl: float, y: np.ndarray, n: np.ndarray | None,
    mask: np.ndarray, subgroup_n: int | None = None, **_,
) -> tuple[np.ndarray, np.ndarray]:
    """Laney u' chart: σ'_i = √(ū/n_i) · σ_z. Laney (2002)."""
    sigma_base = np.sqrt(cl / np.where(n > 0, n, np.nan))
    sigma = sigma_base * _laney_sigma_z(y, cl, sigma_base, mask)
    return cl + 3 * sigma, cl - 3 * sigma


def _xbar_limits(
    cl: float, y: np.ndarray, n: np.ndarray | None,
    mask: np.ndarray, subgroup_n: int | None = None, s_bar: float | None = None, **_,
) -> tuple[np.ndarray, np.ndarray]:
    """Xbar chart: UCL = X̄̄ + A3·S̄, LCL = X̄̄ - A3·S̄. Montgomery (2019), §6.4."""
    if s_bar is None:
        raise ValueError("xbar chart requires s_bar (mean of subgroup SDs)")

    if n is not None:
        a3_vals = _get_constants(n, A3)
    elif subgroup_n is not None:
        a3_vals = np.full(len(y), A3.get(subgroup_n, np.nan))
    else:
        raise ValueError("xbar chart requires subgroup size information.")

    return cl + a3_vals * s_bar, cl - a3_vals * s_bar


# ---------------------------------------------------------------------------
# Chart spec + dispatch table
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChartSpec:
    """Everything needed to compute one chart type."""
    center: Callable    # (y_base, n_base) → float
    limits: Callable    # (cl, y, n, mask, subgroup_n, **_) → (ucl_arr, lcl_arr)
    needs_n: bool = False
    is_attribute: bool = False
    floor_lcl: bool = False


CHARTS: dict[str, ChartSpec] = {
    "run":  ChartSpec(_cl_median, _no_limits),
    "i":    ChartSpec(_cl_mean,   _i_limits),
    "ip":   ChartSpec(_cl_weighted, _i_limits, needs_n=True, is_attribute=True),
    "mr":   ChartSpec(_cl_mean,   _mr_limits),
    "s":    ChartSpec(_cl_mean,   _s_limits),
    "p":    ChartSpec(_cl_weighted, _p_limits,  needs_n=True, is_attribute=True, floor_lcl=True),
    "u":    ChartSpec(_cl_weighted, _u_limits,  needs_n=True, is_attribute=True, floor_lcl=True),
    "c":    ChartSpec(_cl_mean,   _c_limits,  floor_lcl=True),
    "g":    ChartSpec(_cl_median, _g_limits,  floor_lcl=True),
    "pp":   ChartSpec(_cl_weighted, _pp_limits, needs_n=True, is_attribute=True, floor_lcl=True),
    "up":   ChartSpec(_cl_weighted, _up_limits, needs_n=True, is_attribute=True, floor_lcl=True),
    "xbar": ChartSpec(_cl_mean,   _xbar_limits),
}

VALID_CHARTS = set(CHARTS) | {"t"}
