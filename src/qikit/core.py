"""
core.py — SPC chart calculations and signal detection for qikit.

Each chart type is a ChartSpec with two functions: center and limits.
No routing, no string dispatch. Adding a chart = two small functions + one dict entry.

References
----------
1. Montgomery DC. Introduction to Statistical Quality Control, 8th ed. Wiley, 2019.
2. Provost LP, Murray SK. The Health Care Data Guide, 2nd ed. Jossey-Bass, 2022. ISBN 978-1-119-69013-9, 978-1-119-69012-2.
3. Anhoej J, Olesen AV. Run charts revisited. PLoS ONE 9(11), 2014.
4. Anhoej J. Diagnostic value of run chart analysis. PLoS ONE 10(3), 2015.
5. Laney DB. Improved control charts for attributes. Quality Engineering 14(4), 2002.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

# ---------------------------------------------------------------------------
# SPC constants  (Montgomery 2019, Appendix VI, Table VI)
# ---------------------------------------------------------------------------

D2 = {2: 1.128}
D4 = {2: 3.267}

# B3, B4 for S charts (n = subgroup size, 2..25)
B3 = {
    2: 0.000, 3: 0.000, 4: 0.000, 5: 0.000, 6: 0.030, 7: 0.118, 8: 0.185,
    9: 0.239, 10: 0.284, 11: 0.321, 12: 0.354, 13: 0.382, 14: 0.406,
    15: 0.428, 16: 0.448, 17: 0.466, 18: 0.482, 19: 0.497, 20: 0.510,
    21: 0.523, 22: 0.534, 23: 0.545, 24: 0.555, 25: 0.565,
}
B4 = {
    2: 3.267, 3: 2.568, 4: 2.266, 5: 2.089, 6: 1.970, 7: 1.882, 8: 1.815,
    9: 1.761, 10: 1.716, 11: 1.679, 12: 1.646, 13: 1.618, 14: 1.594,
    15: 1.572, 16: 1.552, 17: 1.534, 18: 1.518, 19: 1.503, 20: 1.490,
    21: 1.477, 22: 1.466, 23: 1.455, 24: 1.445, 25: 1.435,
}

# A3 for Xbar charts (n = subgroup size, 2..25)  Montgomery (2019), Table VI
A3 = {
    2: 2.659, 3: 1.954, 4: 1.628, 5: 1.427, 6: 1.287, 7: 1.182, 8: 1.099,
    9: 1.032, 10: 0.975, 11: 0.927, 12: 0.886, 13: 0.850, 14: 0.817,
    15: 0.789, 16: 0.763, 17: 0.739, 18: 0.718, 19: 0.698, 20: 0.680,
    21: 0.663, 22: 0.647, 23: 0.633, 24: 0.619, 25: 0.606,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _moving_ranges(y: np.ndarray) -> np.ndarray:
    """Absolute successive differences. Length = len(y) - 1."""
    return np.abs(np.diff(y))


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
    return float(np.nanmedian(y_base))


def _cl_mean(y_base: np.ndarray, n_base: np.ndarray | None) -> float:
    return float(np.nanmean(y_base))


def _cl_weighted(y_base: np.ndarray, n_base: np.ndarray | None) -> float:
    """Weighted average: sum(y*n) / sum(n) — for p and u charts."""
    if n_base is None:
        raise ValueError("Weighted center line requires denominators (n=).")
    total_events = float(np.nansum(y_base * n_base))
    total_n = float(np.nansum(n_base))
    if total_n == 0:
        raise ValueError("All denominators are zero — cannot compute center line.")
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
    if subgroup_n is None or subgroup_n < 2:
        raise ValueError("S chart requires subgroup_n >= 2.")
    if subgroup_n not in B4:
        raise ValueError(f"S chart constants not available for subgroup size n={subgroup_n}.")
    k = len(y)
    return np.full(k, B4[subgroup_n] * cl), np.full(k, B3[subgroup_n] * cl)


def _g_limits(
    cl: float, y: np.ndarray, n: np.ndarray | None,
    mask: np.ndarray, subgroup_n: int | None = None, **_,
) -> tuple[np.ndarray, np.ndarray]:
    """g chart: σ = √(CL·(CL+1)). Provost & Murray (2011), §8."""
    sigma = math.sqrt(max(cl * (cl + 1.0), 0.0))
    k = len(y)
    return np.full(k, cl + 3 * sigma), np.full(k, cl - 3 * sigma)


def _pp_limits(
    cl: float, y: np.ndarray, n: np.ndarray | None,
    mask: np.ndarray, subgroup_n: int | None = None, **_,
) -> tuple[np.ndarray, np.ndarray]:
    """Laney p' chart: σ'_i = √(p̄(1−p̄)/n_i) · σ_z. Laney (2002)."""
    sigma_base = np.sqrt(cl * (1.0 - cl) / np.where(n > 0, n, np.nan))
    z = (y - cl) / np.where(sigma_base > 0, sigma_base, np.nan)
    z_valid = z[mask & ~np.isnan(z)]
    if len(z_valid) > 1:
        mrs = _moving_ranges(z_valid)
        sigma_z = float(np.nanmean(mrs)) / D2[2]
    else:
        sigma_z = 1.0
    sigma = sigma_base * sigma_z
    return cl + 3 * sigma, cl - 3 * sigma


def _up_limits(
    cl: float, y: np.ndarray, n: np.ndarray | None,
    mask: np.ndarray, subgroup_n: int | None = None, **_,
) -> tuple[np.ndarray, np.ndarray]:
    """Laney u' chart: σ'_i = √(ū/n_i) · σ_z. Laney (2002)."""
    sigma_base = np.sqrt(cl / np.where(n > 0, n, np.nan))
    z = (y - cl) / np.where(sigma_base > 0, sigma_base, np.nan)
    z_valid = z[mask & ~np.isnan(z)]
    if len(z_valid) > 1:
        mrs = _moving_ranges(z_valid)
        sigma_z = float(np.nanmean(mrs)) / D2[2]
    else:
        sigma_z = 1.0
    sigma = sigma_base * sigma_z
    return cl + 3 * sigma, cl - 3 * sigma


def _xbar_limits(
    cl: float, y: np.ndarray, n: np.ndarray | None,
    mask: np.ndarray, subgroup_n: int | None = None, s_bar: float | None = None, **_,
) -> tuple[np.ndarray, np.ndarray]:
    """Xbar chart: UCL = X̄̄ + A3·S̄, LCL = X̄̄ - A3·S̄. Montgomery (2019), §6.4."""
    if subgroup_n is None or subgroup_n not in A3:
        raise ValueError(f"xbar chart requires subgroup_n in 2..25, got {subgroup_n}")
    if s_bar is None:
        raise ValueError("xbar chart requires s_bar (mean of subgroup SDs)")
    k = len(y)
    return np.full(k, cl + A3[subgroup_n] * s_bar), np.full(k, cl - A3[subgroup_n] * s_bar)


# ---------------------------------------------------------------------------
# Chart spec + dispatch table
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChartSpec:
    """Everything needed to compute one chart type."""
    center: Callable    # (y_base, n_base) → float
    limits: Callable    # (cl, y, n, mask, subgroup_n, **_) → (ucl_arr, lcl_arr)
    needs_n: bool = False
    floor_lcl: bool = False


CHARTS: dict[str, ChartSpec] = {
    "run":  ChartSpec(_cl_median, _no_limits),
    "i":    ChartSpec(_cl_mean,   _i_limits),
    "ip":   ChartSpec(_cl_weighted, _i_limits, needs_n=True),
    "mr":   ChartSpec(_cl_mean,   _mr_limits),
    "s":    ChartSpec(_cl_mean,   _s_limits),
    "p":    ChartSpec(_cl_weighted, _p_limits,  needs_n=True, floor_lcl=True),
    "u":    ChartSpec(_cl_weighted, _u_limits,  needs_n=True, floor_lcl=True),
    "c":    ChartSpec(_cl_mean,   _c_limits,  floor_lcl=True),
    "g":    ChartSpec(_cl_median, _g_limits,  floor_lcl=True),
    "pp":   ChartSpec(_cl_weighted, _pp_limits, needs_n=True, floor_lcl=True),
    "up":   ChartSpec(_cl_weighted, _up_limits, needs_n=True, floor_lcl=True),
    "xbar": ChartSpec(_cl_mean,   _xbar_limits),
}

VALID_CHARTS = set(CHARTS) | {"t"}


# ---------------------------------------------------------------------------
# Signal detection
# ---------------------------------------------------------------------------

def _sigma_signals(
    y: np.ndarray, ucl: np.ndarray, lcl: np.ndarray,
) -> np.ndarray:
    """Per-point boolean: True if beyond 3-sigma limits. Montgomery (2019), §5.2."""
    above = np.where(~np.isnan(ucl), y > ucl, False)
    below = np.where(~np.isnan(lcl), y < lcl, False)
    return above | below


def _longest_run_threshold(n: int) -> int:
    """
    Minimum run length signalling non-randomness (p < 0.05).
    floor(log2(n)) + 3 — Anhoej & Olesen (2014), eq. 1.
    """
    if n < 10:
        return n + 1  # effectively impossible
    return math.floor(math.log2(n)) + 3


def _crossings_threshold(n: int) -> int:
    """
    Maximum crossing count signalling non-randomness (p < 0.05).
    Lower 5th percentile of Binomial(n−1, 0.5) — Anhoej & Olesen (2014), eq. 2.
    Pure Python; no scipy dependency.
    """
    if n < 10:
        return -1
    trials = n - 1
    cumprob = 0.0
    for k in range(trials + 1):
        cumprob += math.comb(trials, k) * 0.5 ** trials
        if cumprob > 0.05:
            return k - 1
    return 0


def _count_crossings(y: np.ndarray, cl: np.ndarray) -> int:
    """
    Count median crossings. A crossing occurs when consecutive useful values
    lie on opposite sides of CL. Values on CL or NaN are skipped.
    Anhoej & Olesen (2014), definition 2.
    """
    sides: list[bool] = []
    for i in range(len(y)):
        if np.isnan(y[i]) or y[i] == cl[i]:
            continue
        sides.append(y[i] > cl[i])
    return sum(1 for i in range(1, len(sides)) if sides[i] != sides[i - 1])


def _longest_run(y: np.ndarray, cl: np.ndarray) -> int:
    """
    Length of the longest run on one side of CL.
    Values on CL reset the run. NaN values are skipped (don't break or extend).
    Anhoej & Olesen (2014), definition 1.
    """
    max_run = 0
    current = 0
    last_side: bool | None = None
    for i in range(len(y)):
        if np.isnan(y[i]):
            continue
        if y[i] == cl[i]:
            continue
        side = y[i] > cl[i]
        if side == last_side:
            current += 1
        else:
            current = 1
            last_side = side
        max_run = max(max_run, current)
    return max_run


def _mark_long_runs(y: np.ndarray, cl: np.ndarray, threshold: int) -> np.ndarray:
    """
    Mark all points belonging to runs >= threshold length.

    Only marks "useful" points (non-NaN, not on CL). Points on CL or NaN
    within a long run are not marked.
    """
    signal = np.zeros(len(y), dtype=bool)

    # Collect useful points: (original_index, side_of_cl)
    useful: list[tuple[int, bool]] = []
    for i in range(len(y)):
        if not np.isnan(y[i]) and y[i] != cl[i]:
            useful.append((i, y[i] > cl[i]))

    if not useful:
        return signal

    # Walk through useful points finding runs
    run_start = 0
    for j in range(1, len(useful) + 1):
        # End of run: side changed or end of list
        if j == len(useful) or useful[j][1] != useful[run_start][1]:
            run_len = j - run_start
            if run_len >= threshold:
                for k in range(run_start, j):
                    signal[useful[k][0]] = True
            run_start = j

    return signal


def _runs_signals(
    y: np.ndarray, cl: np.ndarray, method: str = "anhoej",
) -> tuple[np.ndarray, dict[str, Any]]:
    """
    Detect non-random runs patterns. Returns (per_point_signal, summary_dict).

    Long-run signal: marks only the points in runs >= threshold.
    Too-few-crossings signal: marks all useful points (whole-series pattern).
    Anhoej & Olesen (2014); Anhoej (2015).
    """
    if method != "anhoej":
        raise NotImplementedError(
            f"Run signal method {method!r} is not yet implemented. "
            "Only 'anhoej' is supported in this phase."
        )

    useful_mask = ~np.isnan(y) & (y != cl)
    n_useful = int(np.sum(useful_mask))

    longest = _longest_run(y, cl)
    crossings = _count_crossings(y, cl)

    run_threshold = _longest_run_threshold(n_useful)
    cross_threshold = _crossings_threshold(n_useful)

    run_signal = longest >= run_threshold
    cross_signal = crossings <= cross_threshold

    signal_arr = np.zeros(len(y), dtype=bool)
    if cross_signal:
        # Whole-series pattern — mark all useful points
        signal_arr[useful_mask] = True
    elif run_signal:
        # Localized pattern — mark only the long runs
        signal_arr = _mark_long_runs(y, cl, run_threshold)

    summary: dict[str, Any] = {
        "n_useful": n_useful,
        "longest_run": longest,
        "n_crossings": crossings,
        "run_threshold": run_threshold,
        "crossings_threshold": cross_threshold,
        "run_signal": run_signal,
        "crossings_signal": cross_signal,
    }
    return signal_arr, summary


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def compute(
    chart: str,
    y: np.ndarray,
    n: np.ndarray | None = None,
    mask: np.ndarray | None = None,
    cl_override: float | None = None,
    subgroup_n: int | None = None,
    method: str = "anhoej",
    s_bar: float | None = None,
) -> dict[str, Any]:
    """
    Compute SPC limits and signals for a single chart.

    Parameters
    ----------
    chart       : chart type key (must be in CHARTS)
    y           : numeric values, may contain NaN
    n           : denominators for p/u/pp/up charts
    mask        : True = include in baseline; None = all included
    cl_override : user-specified fixed center line
    subgroup_n  : subgroup size for s/xbar charts
    method      : run-signal method ("anhoej")
    s_bar       : mean of subgroup SDs for xbar chart

    Returns
    -------
    dict with keys: y, cl, ucl, lcl, sigma_signal, runs_signal, summary
    """
    if chart not in CHARTS:
        raise ValueError(
            f"Unknown chart type: {chart!r}. "
            f"Valid types: {sorted(VALID_CHARTS)}"
        )

    spec = CHARTS[chart]
    y = np.asarray(y, dtype=float)

    if mask is None:
        mask = np.ones(len(y), dtype=bool)
    else:
        mask = np.asarray(mask, dtype=bool)

    if n is not None:
        n = np.asarray(n, dtype=float)
        # We only care if denominator is zero where y > 0.
        # If y == 0 and n == 0, it transforms to NaN in __init__.py anyway.
        if np.any((n == 0) & mask & ~np.isnan(y) & (y > 0)):
            raise ValueError(
                "Zero denominators found in the baseline. "
                "Exclude these points or supply non-zero denominators."
            )

    # Center line
    y_base = np.where(mask, y, np.nan)
    n_base = np.where(mask, n, np.nan) if n is not None else None

    if cl_override is not None:
        cl_val = float(cl_override)
    else:
        cl_val = spec.center(y_base, n_base)

    cl_arr = np.full(len(y), cl_val, dtype=float)

    # Limits
    ucl_arr, lcl_arr = spec.limits(cl_val, y, n, mask, subgroup_n, s_bar=s_bar)

    if spec.floor_lcl:
        lcl_arr = np.where(lcl_arr < 0, 0.0, lcl_arr)

    # Signals
    sigma_sig = _sigma_signals(y, ucl_arr, lcl_arr)
    runs_sig, runs_summary = _runs_signals(y, cl_arr, method=method)

    return {
        "y": y,
        "cl": cl_arr,
        "ucl": ucl_arr,
        "lcl": lcl_arr,
        "sigma_signal": sigma_sig,
        "runs_signal": runs_sig,
        "summary": runs_summary,
    }
