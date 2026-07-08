"""
signals.py — non-random variation detection for SPC charts.

References
----------
1. Montgomery DC. Introduction to Statistical Quality Control, 8th ed. Wiley, 2019.
3. Anhoej J, Olesen AV. Run charts revisited. PLoS ONE 9(11), 2014.
4. Anhoej J. Diagnostic value of run chart analysis. PLoS ONE 10(3), 2015.
"""

from __future__ import annotations

import math
import warnings
from typing import Any

import numpy as np


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
