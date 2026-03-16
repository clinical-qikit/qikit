"""
spc.py — SPC chart calculations and signal detection for qikit.

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
import warnings
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


# ---------------------------------------------------------------------------
# Signal detection
# ---------------------------------------------------------------------------

def _sigma_signals(
    y: np.ndarray, ucl: np.ndarray, lcl: np.ndarray,
) -> np.ndarray:
    """Per-point boolean: True if beyond 3-sigma limits. Montgomery (2019), §5.2."""
    above = ~np.isnan(ucl) & (y > ucl)
    below = ~np.isnan(lcl) & (y < lcl)
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


def _mark_trends(y: np.ndarray, threshold: int = 6) -> np.ndarray:
    """
    Mark all points belonging to strictly increasing or decreasing trends
    of length >= threshold.
    """
    signal = np.zeros(len(y), dtype=bool)
    useful = [(i, float(v)) for i, v in enumerate(y) if not np.isnan(v)]
    if len(useful) < threshold:
        return signal

    # One pass per direction, O(n): track where the current run started,
    # mark when it ends or the series finishes.
    for direction in (1, -1):  # 1 = strictly increasing, -1 = strictly decreasing
        run_start = 0
        for j in range(1, len(useful)):
            if direction * (useful[j][1] - useful[j - 1][1]) > 0:
                continue  # run continues
            if j - run_start >= threshold:
                for k in range(run_start, j):
                    signal[useful[k][0]] = True
            run_start = j
        if len(useful) - run_start >= threshold:
            for k in range(run_start, len(useful)):
                signal[useful[k][0]] = True

    return signal


def _mark_oscillation(y: np.ndarray, threshold: int = 14) -> np.ndarray:
    """
    Mark all points belonging to alternating up/down patterns
    of length >= threshold.
    """
    signal = np.zeros(len(y), dtype=bool)
    # Collect non-NaN indices
    useful = np.where(~np.isnan(y))[0]
    if len(useful) < threshold:
        return signal
    
    for i in range(len(useful) - threshold + 1):
        idx_chunk = useful[i : i + threshold]
        val_chunk = y[idx_chunk]
        diffs = np.diff(val_chunk)
        # Check if signs alternate: [+, -, +, -] or [-, +, -, +]
        signs = np.sign(diffs)
        if np.all(signs != 0):
            # Check if consecutive signs are opposite
            if np.all(signs[:-1] == -signs[1:]):
                signal[idx_chunk] = True
            
    return signal


def _mark_zones(
    y: np.ndarray, cl: np.ndarray, ucl: np.ndarray, 
    n_beyond: int, window: int, sigma_multiplier: float
) -> np.ndarray:
    """
    Generic zone-rule marker (e.g., 2 of 3 points > 2 sigma).
    Only applies to points on the SAME side of the center line.
    """
    signal = np.zeros(len(y), dtype=bool)
    # Estimate point-wise sigma from limits
    sigma = (ucl - cl) / 3.0
    
    # Avoid division by zero or NaN sigmas
    valid_sigma = ~np.isnan(sigma) & (sigma > 0)
    
    # Upper side
    upper_beyond = np.where(valid_sigma, y > (cl + sigma_multiplier * sigma), False)
    # Lower side
    lower_beyond = np.where(valid_sigma, y < (cl - sigma_multiplier * sigma), False)
    
    for i in range(len(y)):
        if i < window - 1:
            continue
        # Check upper
        if np.sum(upper_beyond[i - window + 1 : i + 1]) >= n_beyond:
            # Mark all points in this window that are beyond the limit
            for k in range(i - window + 1, i + 1):
                if upper_beyond[k]:
                    signal[k] = True
        # Check lower
        if np.sum(lower_beyond[i - window + 1 : i + 1]) >= n_beyond:
            for k in range(i - window + 1, i + 1):
                if lower_beyond[k]:
                    signal[k] = True
            
    return signal


def _mark_stratification(y: np.ndarray, cl: np.ndarray, ucl: np.ndarray, threshold: int = 15) -> np.ndarray:
    """Rule 7: 15 points in a row within 1 sigma (Zone C)."""
    signal = np.zeros(len(y), dtype=bool)
    sigma = (ucl - cl) / 3.0
    within_1s = (y > cl - sigma) & (y < cl + sigma)
    
    count = 0
    for i in range(len(y)):
        if within_1s[i]:
            count += 1
        else:
            count = 0
        if count >= threshold:
            signal[i - threshold + 1 : i + 1] = True
    return signal


def _mark_mixture(y: np.ndarray, cl: np.ndarray, ucl: np.ndarray, threshold: int = 8) -> np.ndarray:
    """Rule 8: 8 points in a row with none in Zone C (within 1 sigma)."""
    signal = np.zeros(len(y), dtype=bool)
    sigma = (ucl - cl) / 3.0
    outside_1s = (y > cl + sigma) | (y < cl - sigma)
    
    count = 0
    for i in range(len(y)):
        if outside_1s[i]:
            count += 1
        else:
            count = 0
        if count >= threshold:
            signal[i - threshold + 1 : i + 1] = True
    return signal


def _runs_signals(
    y: np.ndarray, cl: np.ndarray, method: str = "anhoej", 
    ucl: np.ndarray | None = None, lcl: np.ndarray | None = None
) -> tuple[np.ndarray, dict[str, Any]]:
    """
    Detect non-random runs patterns. Returns (per_point_signal, summary_dict).

    Methods
    -------
    anhoej (default):
        Long-run signal: marks only the points in runs >= floor(log2(n))+3.
        Too-few-crossings signal: marks all useful points (whole-series pattern).
        Anhoej & Olesen (2014); Anhoej (2015).
    ihi (Provost & Murray):
        Shift signal: 8 or more consecutive points on one side of center line.
        Trend signal: 6 or more consecutive points steadily increasing or decreasing.
        Provost & Murray (2022).
    weco (Western Electric):
        Standard 4 rules using 1, 2, and 3 sigma zones.
    nelson:
        Full 8 rules published by Lloyd Nelson (1984).
    """
    supported = ("anhoej", "ihi", "weco", "nelson")
    if method not in supported:
        raise NotImplementedError(
            f"Run signal method {method!r} is not yet implemented. "
            f"Supported methods: {supported}"
        )

    if method in ("weco", "nelson"):
        if ucl is None:
            raise ValueError(f"{method.upper()} rules require control limits (UCL).")
        # Check for asymmetry warning
        if lcl is not None:
            upper_dist = np.nanmean(ucl - cl)
            lower_dist = np.nanmean(cl - lcl)
            if not math.isclose(upper_dist, lower_dist, rel_tol=0.1) and upper_dist > 0:
                warnings.warn(
                    f"{method.upper()} rules assume symmetry. This chart is asymmetric; "
                    "zones are estimated from the upper limit.",
                    RuntimeWarning
                )

    useful_mask = ~np.isnan(y) & (y != cl)
    n_useful = int(np.sum(useful_mask))
    lcl_safe = lcl if lcl is not None else np.full(len(y), -np.inf)

    if method == "anhoej":
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
    elif method == "ihi":
        # Shift rule (standardized at 8 points for IHI)
        shift_threshold = 8
        shift_signal_arr = _mark_long_runs(y, cl, shift_threshold)
        
        # Trend rule (standardized at 6 points)
        trend_threshold = 6
        trend_signal_arr = _mark_trends(y, trend_threshold)
        
        signal_arr = shift_signal_arr | trend_signal_arr
        
        summary = {
            "n_useful": n_useful,
            "shift_threshold": shift_threshold,
            "trend_threshold": trend_threshold,
            "shift_signal": bool(np.any(shift_signal_arr)),
            "trend_signal": bool(np.any(trend_signal_arr)),
        }
    elif method == "weco":
        if ucl is None:
            raise ValueError("WECO rules require control limits (UCL).")
        # Rule 1: 1 point > 3s (already in sigma_signal, but we mark it here too)
        r1 = _sigma_signals(y, ucl, lcl_safe)
        # Rule 2: 2 of 3 > 2s
        r2 = _mark_zones(y, cl, ucl, 2, 3, 2.0)
        # Rule 3: 4 of 5 > 1s
        r3 = _mark_zones(y, cl, ucl, 4, 5, 1.0)
        # Rule 4: 8 points on one side
        r4 = _mark_long_runs(y, cl, 8)
        
        signal_arr = r1 | r2 | r3 | r4
        summary = {
            "n_useful": n_useful,
            "weco_rules_triggered": [i+1 for i, r in enumerate([r1, r2, r3, r4]) if np.any(r)]
        }
    elif method == "nelson":
        if ucl is None:
            raise ValueError("Nelson rules require control limits (UCL).")
        # Nelson Rules 1-8
        r1 = _sigma_signals(y, ucl, lcl_safe)
        r2 = _mark_long_runs(y, cl, 9) # Nelson uses 9
        r3 = _mark_trends(y, 6)
        r4 = _mark_oscillation(y, 14)
        r5 = _mark_zones(y, cl, ucl, 2, 3, 2.0)
        r6 = _mark_zones(y, cl, ucl, 4, 5, 1.0)
        r7 = _mark_stratification(y, cl, ucl, 15)
        r8 = _mark_mixture(y, cl, ucl, 8)
        
        signal_arr = r1 | r2 | r3 | r4 | r5 | r6 | r7 | r8
        summary = {
            "n_useful": n_useful,
            "nelson_rules_triggered": [i+1 for i, r in enumerate([r1, r2, r3, r4, r5, r6, r7, r8]) if np.any(r)]
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
    method      : run-signal method ("anhoej", "ihi", "weco", "nelson")
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
    runs_sig, runs_summary = _runs_signals(y, cl_arr, method=method, ucl=ucl_arr, lcl=lcl_arr)

    return {
        "y": y,
        "cl": cl_arr,
        "ucl": ucl_arr,
        "lcl": lcl_arr,
        "sigma_signal": sigma_sig,
        "runs_signal": runs_sig,
        "summary": runs_summary,
    }



"""
qikit — SPC charts and quality improvement tools for healthcare.

One function. One result object. One .plot() call.

    from qikit import qic
    result = qic(y=values, chart="i")
    result.plot()
    result.data
    result.signals

References
----------
1. Montgomery DC. Introduction to Statistical Quality Control, 8th ed. Wiley, 2019.
2. Provost LP, Murray SK. The Health Care Data Guide, 2nd ed. Jossey-Bass, 2022. ISBN 978-1-119-69013-9, 978-1-119-69012-2.
3. Anhoej J, Olesen AV. Run charts revisited. PLoS ONE 9(11), 2014.
4. Anhoej J. Diagnostic value of run chart analysis. PLoS ONE 10(3), 2015.
5. Laney DB. Improved control charts for attributes. Quality Engineering 14(4), 2002.
"""

import json
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go




# ---------------------------------------------------------------------------
# Result objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SPCResult:
    """
    Immutable result of a qic() call.

    Fields
    ------
    data       : DataFrame with columns x, y, cl, ucl, lcl, sigma_signal,
                 runs_signal, baseline
    chart_type : "run", "i", "mr", "p", "u", "c", etc.
    method     : run-signal detection method ("anhoej", "ihi", "weco", "nelson")
    summary    : audit dict — n_obs, longest_run, n_crossings, thresholds, etc.
    signals    : True if any non-random variation detected
    title      : chart title
    subtitle   : optional subtitle
    caption    : optional caption
    ylab       : y-axis label
    xlab       : x-axis label
    """

    data: pd.DataFrame
    chart_type: str
    method: str
    summary: dict[str, Any]
    signals: bool
    title: str
    subtitle: str | None = None
    caption: str | None = None
    ylab: str = ""
    xlab: str = ""
    _plot_opts: dict[str, Any] = field(default_factory=dict, repr=False)

    def plot(self, **overrides: Any) -> go.Figure:
        """Render as a Plotly Figure. Keyword args override stored display options."""
        from qikit.render.spc_plots import plot_result

        opts = {**self._plot_opts, **overrides}
        return plot_result(self, **opts)

    def show_summary(self) -> None:
        """Print a text summary of the SPC analysis."""
        _print_summary(self.chart_type, self.summary)

    def summary_table(self) -> pd.DataFrame:
        """Return a formatted DataFrame of the SPC results."""
        df = self.data.copy()
        
        # Determine signals
        signals = []
        for s, r in zip(df["sigma_signal"], df["runs_signal"]):
            if s and r:
                signals.append("Both")
            elif s:
                signals.append("Sigma")
            elif r:
                signals.append("Run")
            else:
                signals.append("")
        
        df["signal_type"] = signals
        
        # Reorder and pick key columns
        cols = ["x", "y", "cl", "ucl", "lcl", "signal_type"]
        if "part" in df.columns:
            cols.insert(1, "part")
        if "notes" in df.columns:
            cols.append("notes")
            
        return df[cols]

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize to a plain dict suitable for JSON, MCP, or API responses.
        NaN values become None (JSON-safe).
        """
        def _safe(v: Any) -> Any:
            if isinstance(v, float) and np.isnan(v):
                return None
            if isinstance(v, np.bool_):
                return bool(v)
            if isinstance(v, np.integer):
                return int(v)
            if isinstance(v, np.floating):
                return None if np.isnan(v) else float(v)
            return v

        rows = []
        for _, row in self.data.iterrows():
            rows.append({k: _safe(v) for k, v in row.items()})

        return {
            "chart_type": self.chart_type,
            "method": self.method,
            "signals": self.signals,
            "title": self.title,
            "subtitle": self.subtitle,
            "caption": self.caption,
            "ylab": self.ylab,
            "xlab": self.xlab,
            "summary": {k: _safe(v) for k, v in self.summary.items()},
            "data": rows,
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        n = len(self.data)
        sig = "SIGNAL" if self.signals else "no signal"
        return f"SPCResult(chart={self.chart_type!r}, n={n}, method={self.method!r}, {sig})"


@dataclass(frozen=True)
class ParetoResult:
    """Result of a paretochart() call."""
    data: pd.DataFrame
    title: str
    subtitle: str | None = None
    caption: str | None = None
    ylab: str = ""
    xlab: str = ""
    _plot_opts: dict[str, Any] = field(default_factory=dict, repr=False)

    def plot(self, **overrides: Any) -> go.Figure:
        from qikit.render.spc_plots import plot_pareto
        opts = {**self._plot_opts, **overrides}
        return plot_pareto(self, **opts)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        rows = []
        for _, row in self.data.iterrows():
            rows.append({k: (None if (isinstance(v, float) and np.isnan(v)) else v) for k, v in row.items()})
        return {
            "title": self.title,
            "subtitle": self.subtitle,
            "caption": self.caption,
            "ylab": self.ylab,
            "xlab": self.xlab,
            "data": rows,
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        return f"ParetoResult(n_categories={len(self.data)})"


@dataclass(frozen=True)
class BChartResult:
    """Result of a bchart() call."""
    data: pd.DataFrame
    target: float
    or_ratio: float
    limit: float
    title: str
    subtitle: str | None = None
    caption: str | None = None
    ylab: str = ""
    xlab: str = ""
    _plot_opts: dict[str, Any] = field(default_factory=dict, repr=False)

    def plot(self, **overrides: Any) -> go.Figure:
        from qikit.render.spc_plots import plot_bchart
        opts = {**self._plot_opts, **overrides}
        return plot_bchart(self, **opts)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        rows = []
        for _, row in self.data.iterrows():
            rows.append({k: (None if (isinstance(v, float) and np.isnan(v)) else v) for k, v in row.items()})
        return {
            "title": self.title,
            "subtitle": self.subtitle,
            "caption": self.caption,
            "ylab": self.ylab,
            "xlab": self.xlab,
            "target": self.target,
            "or_ratio": self.or_ratio,
            "limit": self.limit,
            "data": rows,
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        return f"BChartResult(n_obs={len(self.data)}, target={self.target:.3f})"


# ---------------------------------------------------------------------------
# qic() — main entry point
# ---------------------------------------------------------------------------

# Display-only params that travel with the result via _plot_opts
_PLOT_OPT_KEYS = frozenset({
    "show_labels", "show_95", "show_grid",
    "decimals", "point_size",
    "x_angle", "x_pad", "x_period", "x_format", "x_order",
    "y_neg", "y_percent", "y_percent_accuracy", "y_expand",
    "flip", "strip_horizontal",
    "nrow", "ncol", "scales",
    "part_labels", "part_indices",
    "height", "width",
})


def qic(
    x: Any = None,
    y: Any = None,
    n: Any = None,
    data: pd.DataFrame | None = None,
    facets: str | None = None,
    notes: Any = None,
    chart: str = "run",
    agg_fun: str = "mean",
    method: str = "anhoej",
    multiply: float = 1.0,
    freeze: int | None = None,
    part: list[int] | int | str | None = None,
    exclude: list[int] | str | None = None,
    target: float | list[float] | str | None = None,
    cl: float | None = None,
    # Layout
    nrow: int | None = None,
    ncol: int | None = None,
    scales: str = "fixed",
    # Labels
    title: str = "",
    ylab: str = "Value",
    xlab: str = "Subgroup",
    subtitle: str | None = None,
    caption: str | None = None,
    part_labels: list[str] | None = None,
    # Display toggles
    show_labels: bool = True,
    show_95: bool = False,
    show_grid: bool = False,
    # Formatting
    decimals: int = 1,
    point_size: float = 1.5,
    x_period: str | None = None,
    x_format: str | None = None,
    x_angle: int | None = None,
    x_pad: float = 1.0,
    x_order: list | str | None = None,
    y_expand: float | None = None,
    height: int | None = None,
    width: int | None = None,
    y_neg: bool = True,
    y_percent: bool | None = None,
    y_percent_accuracy: int | None = None,
    flip: bool = False,
    strip_horizontal: bool = False,
    print_summary: bool = False,
) -> SPCResult:
    """
    Compute an SPC chart and return an SPCResult.

    Parameters
    ----------
    x      : x-axis values, or column name if data= supplied
    y      : numeric values, or column name if data= supplied
    n      : denominators for p/u/pp/up charts
    data   : optional DataFrame
    facets : column name to split into faceted subplots
    notes  : list of annotations, or column name
    chart  : chart type — run|i|mr|s|t|xbar|p|pp|c|u|up|g
    method : run-signal detection — anhoej (default), ihi, weco, nelson
    freeze : baseline ends at this index (1-based)
    part   : index (or list) where new phases begin (1-based), or column name
    exclude: list of indices to ghost from baseline (1-based), or column name
    cl     : user-supplied fixed center line
    multiply : multiply y values by this factor

    Returns
    -------
    SPCResult (frozen dataclass)
    """
    chart = chart.lower().strip()

    # Default y_percent for proportion charts
    if y_percent is None:
        y_percent = chart in ("p", "pp")

    if chart not in VALID_CHARTS:
        raise ValueError(
            f"Unknown chart type: {chart!r}. "
            f"Valid types: {sorted(VALID_CHARTS)}"
        )

    # ------------------------------------------------------------------
    # Resolve spec early
    # ------------------------------------------------------------------
    chart_for_compute = "i" if chart == "t" else chart
    spec = CHARTS.get(chart_for_compute)

    # ------------------------------------------------------------------
    # Facets: recursive call per facet value
    # ------------------------------------------------------------------
    if facets is not None:
        if data is None or not isinstance(data, pd.DataFrame):
            raise ValueError("facets= requires data= to be a DataFrame.")
        if not isinstance(facets, str) or facets not in data.columns:
            raise ValueError(f"facets= must be a column name string. Got {facets!r}.")

        # Warn if using list indices with facets
        if isinstance(part, (list, np.ndarray)) or isinstance(exclude, (list, np.ndarray)):
            import warnings
            warnings.warn(
                "Using integer indices for 'part' or 'exclude' with facets is risky as indices "
                "often differ per group. Using column names is recommended.",
                UserWarning
            )

        facet_vals = list(data[facets].unique())

        # Build display opts to pass through (excluding facets itself)
        display_kwargs: dict[str, Any] = {
            "nrow": nrow, "ncol": ncol, "scales": scales,
            "show_labels": show_labels, "show_95": show_95, "show_grid": show_grid,
            "decimals": decimals, "point_size": point_size,
            "x_angle": x_angle, "x_pad": x_pad, "x_period": x_period,
            "x_format": x_format, "x_order": x_order,
            "height": height, "width": width,
            "y_expand": y_expand, "y_neg": y_neg,
            "y_percent": y_percent, "y_percent_accuracy": y_percent_accuracy,
            "flip": flip, "strip_horizontal": strip_horizontal,
            "part_labels": part_labels,
        }

        sub_results = []
        for fv in facet_vals:
            sub_df = data[data[facets] == fv].copy()
            sub_result = qic(
                data=sub_df,
                x=x, y=y, n=n,
                chart=chart, method=method,
                freeze=freeze, part=part, exclude=exclude,
                cl=cl, multiply=multiply,
                title=str(fv), ylab=ylab, xlab=xlab,
                agg_fun=agg_fun,
                print_summary=False,
                **display_kwargs,
            )
            sub_df_copy = sub_result.data.copy()
            sub_df_copy["facet"] = fv
            sub_results.append((fv, sub_result, sub_df_copy))

        combined_df = pd.concat([r[2] for r in sub_results], ignore_index=True)
        total_n_obs = sum(r[1].summary.get("n_obs", 0) for r in sub_results)
        any_signals = any(r[1].signals for r in sub_results)
        by_facet = {str(r[0]): r[1].summary for r in sub_results}
        combined_summary: dict[str, Any] = {
            "n_obs": total_n_obs,
            "signals": any_signals,
            "by_facet": by_facet,
        }

        local_vars = locals()
        plot_opts: dict[str, Any] = {k: local_vars[k] for k in _PLOT_OPT_KEYS if k in local_vars}
        plot_opts["part_indices"] = []

        return SPCResult(
            data=combined_df,
            chart_type=chart,
            method=method,
            summary=combined_summary,
            signals=any_signals,
            title=title,
            ylab=ylab,
            xlab=xlab,
            _plot_opts=plot_opts,
        )

    # ------------------------------------------------------------------
    # 1. Resolve and Aggregate Data
    # ------------------------------------------------------------------
    (
        x_vals, y_arr, n_vals, notes, part, exclude, part_labels, s_bar_val, subgroup_n_val
    ) = _resolve_and_aggregate(
        data, x, y, n, notes, part, exclude, part_labels, chart, agg_fun, x_period, spec
    )

    if len(y_arr) == 0:
        raise ValueError("y= contains no values.")

    # ------------------------------------------------------------------
    # 3. Build baseline mask
    # ------------------------------------------------------------------
    n_pts_orig = len(y_arr)
    mask = np.ones(n_pts_orig, dtype=bool)

    if exclude:
        for idx in exclude:
            i = idx - 1
            if 0 <= i < n_pts_orig:
                mask[i] = False

    if freeze is not None and part is not None:
        raise ValueError("Cannot use both freeze= and part= simultaneously.")

    freeze_idx: int | None = None
    if freeze is not None:
        freeze_idx = int(freeze)
        mask[freeze_idx:] = False

    part_indices: list[int] = []
    if part is not None:
        if isinstance(part, int):
            part_indices = [part]
        else:
            part_indices = [int(p) for p in part]

    # ------------------------------------------------------------------
    # 4. MR transform
    # ------------------------------------------------------------------
    if chart == "mr":
        if len(y_arr) < 2:
            raise ValueError("MR chart requires at least 2 data points.")
        y_arr = np.abs(np.diff(y_arr))
        x_vals = x_vals[1:]
        mask = mask[1:] & mask[:-1]
        if part_indices:
            part_indices = [max(1, p - 1) for p in part_indices]
        n_vals = None

    n_pts = len(y_arr)

    # ------------------------------------------------------------------
    # 5. Validate & transform to proportion
    # ------------------------------------------------------------------
    if spec and spec.needs_n and n_vals is None:
        raise ValueError(f"Chart type {chart!r} requires denominators (n=).")

    if spec and spec.is_attribute:
        if n_vals is not None and np.any((n_vals == 0) & (y_arr > 0) & mask):
             raise ValueError(
                "Zero denominators found in the baseline with non-zero events. "
                "Exclude these points or supply non-zero denominators."
            )
        with np.errstate(divide="ignore", invalid="ignore"):
            y_arr = np.where(n_vals > 0, y_arr / n_vals, np.nan)

    # ------------------------------------------------------------------
    # 6. t chart transform
    # ------------------------------------------------------------------
    y_plot = y_arr
    if chart == "t":
        if np.any(y_arr[~np.isnan(y_arr)] < 0):
            raise ValueError("t chart requires non-negative values.")
        y_calc = np.where(np.isnan(y_arr), np.nan, y_arr ** (1.0 / 3.6))
    else:
        y_calc = y_arr

    # ------------------------------------------------------------------
    # 7. Compute limits and signals
    # ------------------------------------------------------------------
    (
        cl_arr, ucl_arr, lcl_arr, ucl_95_arr, lcl_95_arr, sigma_sig, runs_sig, runs_summary
    ) = _compute_spc_arrays(
        chart, chart_for_compute, y_calc, y_plot, n_vals, mask, cl, method, 
        s_bar_val, subgroup_n_val, part_indices, freeze_idx, spec
    )

    # ------------------------------------------------------------------
    # 8. Assemble DataFrame
    # ------------------------------------------------------------------
    df = _assemble_final_df(
        x_vals, y_plot, cl_arr, ucl_arr, lcl_arr, ucl_95_arr, lcl_95_arr, 
        sigma_sig, runs_sig, mask, notes, target, multiply, chart, part_indices, part_labels
    )

    # ------------------------------------------------------------------
    # 9. Summary
    # ------------------------------------------------------------------
    any_signals = bool(np.any(sigma_sig) or np.any(runs_sig))
    exclude_list = [int(i + 1) for i in range(n_pts) if not mask[i]]
    if freeze_idx:
        exclude_list = [idx for idx in (exclude or [])]

    summary: dict[str, Any] = {
        "n_obs": int(np.sum(~np.isnan(df["y"]))),
        "n_baseline": int(np.sum(mask & ~np.isnan(df["y"]))),
        "signals": any_signals,
        "limit_basis": "baseline" if (freeze_idx or part_indices) else "all",
        "freeze": freeze_idx,
        "excluded": exclude_list,
        **runs_summary,
    }

    if print_summary:
        _print_summary(chart, summary)

    # ------------------------------------------------------------------
    # 10. Collect display params
    # ------------------------------------------------------------------
    local_vars = locals()
    plot_opts = {k: local_vars[k] for k in _PLOT_OPT_KEYS if k in local_vars}
    plot_opts["part_indices"] = part_indices

    return SPCResult(
        data=df,
        chart_type=chart,
        method=method,
        summary=summary,
        signals=any_signals,
        title=title,
        subtitle=subtitle,
        caption=caption,
        ylab=ylab,
        xlab=xlab,
        _plot_opts=plot_opts,
    )


def _resolve_and_aggregate(
    data, x, y, n, notes, part, exclude, part_labels, chart, agg_fun, x_period, spec
) -> tuple:
    """Helper to resolve columns and aggregate data if needed."""
    s_bar_val = None
    subgroup_n_val = None
    n_vals = None

    if data is not None:
        if not isinstance(data, pd.DataFrame):
            raise TypeError("data= must be a pandas DataFrame.")
        if not isinstance(y, str):
            raise ValueError("When data= is supplied, y= must be a column name string.")
        if y not in data.columns:
            raise ValueError(f"Column {y!r} not found in data.")
            
        y_col = y
        n_col = n if (n is not None and isinstance(n, str)) else None
        if n is not None and n_col is None:
             raise ValueError("When data= is supplied, n= must be a column name string.")
        if n_col and n_col not in data.columns:
            raise ValueError(f"Column {n_col!r} not found in data.")
            
        # Grouping
        if isinstance(x, str):
            if x not in data.columns:
                raise ValueError(f"Column {x!r} not found in data.")
            x_col = x
            
            if x_period is not None:
                if not pd.api.types.is_datetime64_any_dtype(data[x_col]):
                    data = data.copy()
                    data[x_col] = pd.to_datetime(data[x_col])
                period_map = {"day": "D", "week": "W", "month": "MS", "quarter": "QS", "year": "YS"}
                freq = period_map.get(x_period.lower(), x_period)
                grouped = data.groupby(pd.Grouper(key=x_col, freq=freq))
            else:
                grouped = data.groupby(x_col, sort=False)
                
            group_sizes = grouped[y_col].count()
            x_vals = list(group_sizes.index)
            
            if isinstance(notes, str) and notes in data.columns:
                notes = grouped[notes].apply(lambda x: " | ".join(x.dropna().unique().astype(str))).tolist()
            if isinstance(exclude, str) and exclude in data.columns:
                exclude = (np.where(grouped[exclude].any().values)[0] + 1).tolist()
            if isinstance(part, str) and part in data.columns:
                part_col_vals = grouped[part].first()
                if part_labels is None:
                    vals = part_col_vals.values
                    labels = [str(vals[0])]
                    for v_prev, v_curr in zip(vals[:-1], vals[1:]):
                        if v_prev != v_curr: labels.append(str(v_curr))
                    part_labels = labels
                changes = np.where(part_col_vals.values[1:] != part_col_vals.values[:-1])[0]
                part = (changes + 2).tolist()
            
            if chart in ("xbar", "s"):
                subgroup_n_val = int(np.median(group_sizes.to_numpy()))
                group_sds = grouped[y_col].std(ddof=1)
                if chart == "xbar" and subgroup_n_val not in A3:
                    raise ValueError(f"xbar chart requires subgroup_n in 2..25, got {subgroup_n_val}.")
                if chart == "s" and subgroup_n_val not in B4:
                    raise ValueError(f"s chart requires subgroup_n in 2..25, got {subgroup_n_val}.")
                sds_arr = group_sds.to_numpy(dtype=float)
                s_bar_val = float(np.mean(sds_arr[~np.isnan(sds_arr)])) if np.any(~np.isnan(sds_arr)) else np.nan
                y_arr = sds_arr if chart == "s" else _agg(grouped[y_col], agg_fun)
                n_vals = group_sizes.to_numpy(dtype=float)
            elif spec and spec.is_attribute:
                y_arr = grouped[y_col].sum().to_numpy(dtype=float)
                n_vals = grouped[n_col].sum().to_numpy(dtype=float) if n_col else None
            else:
                y_arr = _agg(grouped[y_col], agg_fun)
                n_vals = grouped[n_col].sum().to_numpy(dtype=float) if n_col else None
        else:
            # No implicit grouping
            if chart in ("xbar", "s"):
                raise ValueError(f"{chart} chart requires x= to be a column name string for subgroup grouping.")
            y_arr = data[y_col].to_numpy(dtype=float)
            x_vals = list(x) if x is not None else list(range(1, len(y_arr) + 1))
            n_vals = data[n_col].to_numpy(dtype=float) if n_col else None
            if isinstance(notes, str) and notes in data.columns: notes = data[notes].tolist()
            if isinstance(exclude, str) and exclude in data.columns:
                exclude = (np.where(data[exclude].values)[0] + 1).tolist()
            if isinstance(part, str) and part in data.columns:
                part_vals = data[part]
                if part_labels is None:
                    vals = part_vals.values
                    labels = [str(vals[0])]
                    for v_prev, v_curr in zip(vals[:-1], vals[1:]):
                        if v_prev != v_curr: labels.append(str(v_curr))
                    part_labels = labels
                changes = np.where(part_vals.values[1:] != part_vals.values[:-1])[0]
                part = (changes + 2).tolist()
    else:
        if chart in ("xbar", "s"):
            raise ValueError(f"{chart} chart requires data= as a DataFrame.")
        y_arr = np.asarray(y, dtype=float) if y is not None else np.array([])
        x_vals = list(x) if x is not None else list(range(1, len(y_arr) + 1))
        
        if len(x_vals) != len(y_arr):
            raise ValueError(f"Length of x ({len(x_vals)}) must match length of y ({len(y_arr)}).")
            
        n_vals = np.asarray(n, dtype=float) if n is not None else None

    return x_vals, y_arr, n_vals, notes, part, exclude, part_labels, s_bar_val, subgroup_n_val


def _agg(series_grouped, agg_fun):
    if agg_fun == "mean": return series_grouped.mean().to_numpy(dtype=float)
    if agg_fun == "median": return series_grouped.median().to_numpy(dtype=float)
    if agg_fun == "sum": return series_grouped.sum().to_numpy(dtype=float)
    raise ValueError(f"agg_fun must be 'mean', 'median', or 'sum', got {agg_fun!r}.")


def _compute_spc_arrays(
    chart, chart_for_compute, y_calc, y_plot, n_vals, mask, cl, method, 
    s_bar_val, subgroup_n_val, part_indices, freeze_idx, spec
):
    n_pts = len(y_calc)
    if part_indices and freeze_idx is None:
        boundaries = [0] + [p - 1 for p in part_indices] + [n_pts]
        cl_arr, ucl_arr, lcl_arr, ucl_95_arr, lcl_95_arr = [np.empty(n_pts) for _ in range(5)]
        sigma_sig, runs_sig = [np.zeros(n_pts, dtype=bool) for _ in range(2)]
        per_part_summaries = []
        for seg_i in range(len(boundaries) - 1):
            start, end = boundaries[seg_i], boundaries[seg_i + 1]
            seg_mask = mask[start:end] # Preserve global exclusions in segments
            seg_raw = compute(
                chart=chart_for_compute, y=y_calc[start:end], n=n_vals[start:end] if n_vals is not None else None,
                mask=seg_mask, cl_override=cl, method=method, s_bar=s_bar_val, subgroup_n=subgroup_n_val,
            )
            cl_arr[start:end], ucl_arr[start:end], lcl_arr[start:end] = seg_raw["cl"], seg_raw["ucl"], seg_raw["lcl"]
            s3 = seg_raw["ucl"] - seg_raw["cl"]
            ucl_95_arr[start:end] = seg_raw["cl"] + s3 * (2/3)
            l95 = seg_raw["cl"] - s3 * (2/3)
            lcl_95_arr[start:end] = np.where(l95 < 0, 0.0, l95) if spec.floor_lcl else l95
            sigma_sig[start:end], runs_sig[start:end] = seg_raw["sigma_signal"], seg_raw["runs_signal"]
            per_part_summaries.append({"part": seg_i + 1, **seg_raw["summary"]})
        
        runs_summary = {**per_part_summaries[-1], "parts": per_part_summaries}
        if chart == "t":
            cl_arr, ucl_arr, lcl_arr, ucl_95_arr, lcl_95_arr = [
                np.where(np.isnan(a), np.nan, np.where(a < 0, 0.0, a) ** 3.6) 
                for a in [cl_arr, ucl_arr, lcl_arr, ucl_95_arr, lcl_95_arr]
            ]
            sigma_sig = _sigma_signals(y_plot, ucl_arr, lcl_arr)
            new_summaries = []
            for seg_i in range(len(boundaries) - 1):
                s, e = boundaries[seg_i], boundaries[seg_i + 1]
                sig, summ = _runs_signals(y_plot[s:e], cl_arr[s:e], method=method)
                runs_sig[s:e], new_summaries.append({"part": seg_i + 1, **summ})
            runs_summary = {**new_summaries[-1], "parts": new_summaries}
    else:
        res = compute(chart_for_compute, y_calc, n_vals, mask, cl, subgroup_n_val, method, s_bar_val)
        cl_arr, ucl_arr, lcl_arr = res["cl"], res["ucl"], res["lcl"]
        s3 = ucl_arr - cl_arr
        ucl_95_arr = cl_arr + s3 * (2/3)
        l95 = cl_arr - s3 * (2/3)
        lcl_95_arr = np.where(l95 < 0, 0.0, l95) if spec.floor_lcl else l95
        if chart == "t":
            cl_arr, ucl_arr, lcl_arr, ucl_95_arr, lcl_95_arr = [
                np.where(np.isnan(a), np.nan, np.where(a < 0, 0.0, a) ** 3.6) 
                for a in [cl_arr, ucl_arr, lcl_arr, ucl_95_arr, lcl_95_arr]
            ]
            sigma_sig = _sigma_signals(y_plot, ucl_arr, lcl_arr)
            runs_sig, runs_summary = _runs_signals(y_plot, cl_arr, method=method)
        else:
            sigma_sig, runs_sig, runs_summary = res["sigma_signal"], res["runs_signal"], res["summary"]
            
    return cl_arr, ucl_arr, lcl_arr, ucl_95_arr, lcl_95_arr, sigma_sig, runs_sig, runs_summary


def _assemble_final_df(
    x_vals, y_plot, cl_arr, ucl_arr, lcl_arr, ucl_95_arr, lcl_95_arr, 
    sigma_sig, runs_sig, mask, notes, target, multiply, chart, part_indices, part_labels
):
    if multiply != 1.0:
        y_plot, cl_arr, ucl_arr, lcl_arr, ucl_95_arr, lcl_95_arr = [
            a * multiply for a in [y_plot, cl_arr, ucl_arr, lcl_arr, ucl_95_arr, lcl_95_arr]
        ]
    
    df_dict = {
        "x": x_vals, "y": y_plot, "cl": cl_arr, "ucl": ucl_arr, "lcl": lcl_arr,
        "ucl_95": ucl_95_arr, "lcl_95": lcl_95_arr, 
        "sigma_signal": sigma_sig, "runs_signal": runs_sig, "baseline": mask,
    }
    
    if notes is not None:
        if isinstance(notes, (list, np.ndarray, pd.Series)): notes_vals = list(notes)
        else: notes_vals = [str(notes)] * len(x_vals)
        if chart == "mr": notes_vals = notes_vals[1:]
        
        if len(notes_vals) != len(x_vals):
            raise ValueError(f"Length of notes ({len(notes_vals)}) must match length of x-axis ({len(x_vals)}).")
            
        df_dict["notes"] = ["" if (v is None or (isinstance(v, float) and np.isnan(v))) else str(v) for v in notes_vals]

    if target is not None:
        if isinstance(target, (list, np.ndarray, pd.Series)):
            t_vals = np.asarray(target, dtype=float)
            if chart == "mr": t_vals = t_vals[1:]
        else: t_vals = np.full(len(x_vals), float(target))
        df_dict["target"] = t_vals * multiply if multiply != 1.0 else t_vals

    if part_indices:
        n_pts = len(y_plot)
        boundaries = [0] + [p - 1 for p in part_indices] + [n_pts]
        part_col = np.empty(n_pts, dtype=int)
        for i in range(len(boundaries) - 1):
            part_col[boundaries[i]:boundaries[i+1]] = i + 1
        if part_labels and len(part_labels) == (len(boundaries) - 1):
            df_dict["part"] = [part_labels[i-1] for i in part_col]
        else:
            df_dict["part"] = part_col
            
    return pd.DataFrame(df_dict)


def _print_summary(chart: str, summary: dict[str, Any]) -> None:
    print(f"\nChart: {chart.upper()}")
    print(f"  n observations : {summary['n_obs']}")
    print(f"  n baseline     : {summary['n_baseline']}")
    print(f"  Signals        : {'YES' if summary['signals'] else 'none'}")
    if "weco_rules_triggered" in summary: print(f"  WECO Rules     : {summary['weco_rules_triggered']}")
    if "nelson_rules_triggered" in summary: print(f"  Nelson Rules   : {summary['nelson_rules_triggered']}")
    if "longest_run" in summary:
        print(f"  Longest run    : {summary['longest_run']} (threshold: {summary['run_threshold']})")
        print(f"  Crossings      : {summary['n_crossings']} (threshold: {summary['crossings_threshold']})")


def paretochart(
    x: Any, data: pd.DataFrame | None = None, title: str = "", subtitle: str | None = None,
    caption: str | None = None, ylab: str = "Frequency", xlab: str = "", use_na: bool = False, x_angle: int | None = None,
) -> ParetoResult:
    """Compute a Pareto chart."""
    vals = data[x] if (data is not None and isinstance(x, str)) else pd.Series(x)
    counts = vals.value_counts(dropna=not use_na).sort_values(ascending=False)
    df = counts.reset_index()
    df.columns = ["category", "count"]
    df["cum_sum"] = df["count"].cumsum()
    df["cum_percent"] = (df["cum_sum"] / df["count"].sum()) * 100
    return ParetoResult(df, title, subtitle, caption, ylab, xlab, {"x_angle": x_angle})


def bchart(
    x: Any, target: float | int | None = None, or_ratio: float = 2.0, limit: float = 3.5,
    title: str = "", subtitle: str | None = None, caption: str | None = None, ylab: str = "CUSUM", xlab: str = "Case #",
) -> BChartResult:
    """Compute a Bernoulli CUSUM chart for binary data."""
    x_arr = np.asarray(x, dtype=float)
    n = len(x_arr)
    if target is None: p0 = float(np.nanmean(x_arr))
    elif target > 1: p0 = float(np.nanmean(x_arr[:int(target)]))
    else: p0 = float(target)
    if not (0 < p0 < 1): raise ValueError("Target (baseline risk) must be between 0 and 1.")
    def getp(p, o): return (p * o) / (1 - p + p * o)
    p1, p2 = getp(p0, or_ratio), getp(p0, 1.0 / or_ratio)
    with np.errstate(divide="ignore", invalid="ignore"):
        s1 = x_arr * np.log(p1 / p0) + (1 - x_arr) * np.log((1 - p1) / (1 - p0))
        s2 = x_arr * np.log(p2 / p0) + (1 - x_arr) * np.log((1 - p2) / (1 - p0))
    c1, c2, sig1, sig2 = np.zeros(n), np.zeros(n), np.zeros(n, dtype=bool), np.zeros(n, dtype=bool)
    z1, z2, l2 = 0.0, 0.0, -limit
    for i in range(n):
        if np.isnan(s1[i]): c1[i], c2[i] = z1, z2; continue
        z1i = z1 + s1[i]; sig1[i] = (z1i >= limit); c1[i] = z1i * (z1i > 0) * (z1i <= limit); z1 = c1[i]
        z2i = z2 - s2[i]; sig2[i] = (z2i <= l2); c2[i] = z2i * (z2i < 0) * (z2i >= l2); z2 = c2[i]
    df = pd.DataFrame({"x": np.arange(1, n + 1), "y": x_arr, "cusum_up": c1, "cusum_down": c2, "signal_up": sig1, "signal_down": sig2, "limit": limit})
    return BChartResult(df, p0, or_ratio, limit, title or f"Bernoulli CUSUM (p0={p0:.3f}, OR={or_ratio})", subtitle, caption, ylab, xlab)
