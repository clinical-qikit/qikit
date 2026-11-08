"""
rules.py — rules for non-random patterns in time-ordered data.

A point beyond the control limits is the chart's own test (qic()'s signal column); the
rules here find patterns: runs, trends, clusters near a limit. Each method returns which
points form a pattern and a summary of what fired.

| method   | Source                                   | Rules                                       |
|----------|------------------------------------------|---------------------------------------------|
| anhoej   | Anhøj & Olesen 2014; qicharts2 (default) | longest run, number of crossings            |
| ihi      | Provost & Murray 2022                    | run chart: shift 6, trend 5. Shewhart chart:|
|          |                                          | shift 8, trend 6, 2 of 3 beyond 2σ, 15 in 1σ|
| nhs      | NHS England Making Data Count            | shift 7, trend 7, 2 of 3 beyond 2σ          |
| weco     | Western Electric 1956                    | 2 of 3 beyond 2σ, 4 of 5 beyond 1σ, shift 8 |
| nelson   | Nelson 1984                              | the eight Nelson rules, less rule 1         |

References
----------
Anhøj J, Olesen AV. Run charts revisited. PLoS ONE 2014;9(11):e113825.
Anhøj J. Diagnostic value of run chart analysis. PLoS ONE 2015;10(3):e0121349.
Provost LP, Murray SK. The Health Care Data Guide, 2nd ed. Jossey-Bass, 2022.
NHS England. Making Data Count: getting started. 2019; NHSRplotthedots (NHS-R Community).
Nelson LS. The Shewhart control chart — tests for special causes. J Qual Technol 1984;16:237-239.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

METHODS = ("anhoej", "ihi", "nhs", "weco", "nelson")
# Methods whose rules read the 1σ and 2σ zones, so the chart needs control limits.
ZONE_METHODS = ("nhs", "weco", "nelson")


@dataclass(frozen=True)
class RuleResult:
    points: np.ndarray                      # bool: the point is part of a pattern
    summary: dict[str, Any]
    # nhs only: each point's special cause, as Making Data Count names it, and its
    # direction (+1 above / increasing, −1 below / decreasing, 0 common cause).
    cause: np.ndarray | None = field(default=None)
    direction: np.ndarray | None = field(default=None)


def apply_rules(
    method: str, y: np.ndarray, cl: np.ndarray, sigma: np.ndarray,
    ucl: np.ndarray, lcl: np.ndarray, has_limits: bool,
) -> RuleResult:
    """The patterns method finds in y (NaN points are skipped, as missing)."""
    y = np.asarray(y, dtype=float)
    if method == "anhoej":
        return _anhoej(y, cl)
    if method == "ihi":
        return _ihi(y, cl, sigma, has_limits)
    if method == "nhs":
        return _nhs(y, cl, sigma, ucl, lcl)
    if method == "weco":
        return _named({
            "2 of 3 beyond 2 sigma": _zone(y, cl, sigma, 2, 3, 2.0),
            "4 of 5 beyond 1 sigma": _zone(y, cl, sigma, 4, 5, 1.0),
            "8 on one side": _mark_runs(y, cl, 8),
        })
    if method == "nelson":
        return _named({
            "9 on one side": _mark_runs(y, cl, 9),
            "6 increasing or decreasing": _mark_trends(y, 6),
            "14 alternating": _mark_alternating(y, 14),
            "2 of 3 beyond 2 sigma": _zone(y, cl, sigma, 2, 3, 2.0),
            "4 of 5 beyond 1 sigma": _zone(y, cl, sigma, 4, 5, 1.0),
            "15 within 1 sigma": _stretch(y, cl, sigma, 15, inside=True),
            "8 outside 1 sigma": _stretch(y, cl, sigma, 8, inside=False),
        })
    raise ValueError(f"method must be one of {METHODS}, got {method!r}.")


def _named(rules: dict[str, np.ndarray]) -> RuleResult:
    points = np.zeros(len(next(iter(rules.values()))), dtype=bool)
    for marks in rules.values():
        points |= marks
    fired = [name for name, marks in rules.items() if marks.any()]
    return RuleResult(points, {"runs_signal": bool(points.any()), "rules_fired": fired})


# ---------------------------------------------------------------------------
# Anhøj: longest run and crossings (qicharts2)
# ---------------------------------------------------------------------------

def longest_run_max(n_useful: int) -> int:
    """Longest run expected by chance: round(log2 n) + 3 (Schilling 2012; qicharts2)."""
    return round(math.log2(n_useful)) + 3 if n_useful > 0 else 0


def n_crossings_min(n_useful: int) -> int:
    """
    Fewest crossings expected by chance: the 5th percentile of Binomial(n − 1, ½), i.e.
    R's qbinom(0.05, n − 1, 0.5): the smallest k with P(X ≤ k) ≥ 0.05 (Chen 2010).
    Exact, in log space, since math.comb overflows a float past n ≈ 1,030.
    """
    trials = max(n_useful - 1, 0)
    log_pmf = -trials * math.log(2.0)
    cdf = 0.0
    for k in range(trials + 1):
        if k:
            log_pmf += math.log((trials - k + 1) / k)
        cdf += math.exp(log_pmf)
        if cdf >= 0.05:
            return k
    return trials


def _sides(y: np.ndarray, cl: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(indices of useful points, their side): useful means present and off the line."""
    useful = np.flatnonzero(np.isfinite(y) & (y != cl))
    return useful, y[useful] > cl[useful]


def _anhoej(y: np.ndarray, cl: np.ndarray) -> RuleResult:
    """
    A run is too long when longest_run > longest_run_max, and the series crosses its
    center line too rarely when n_crossings < n_crossings_min; either is a signal
    (Anhøj & Olesen 2014). Points on the line neither break nor extend a run. Only the
    points of a too-long run are marked: too few crossings is a property of the series,
    reported in the summary.
    """
    useful, side = _sides(y, cl)
    n = len(useful)
    run_lengths = _run_lengths(side)
    longest = max(run_lengths, default=0)
    crossings = max(len(run_lengths) - 1, 0)
    run_max, cross_min = longest_run_max(n), n_crossings_min(n)
    long_run = n > 0 and longest > run_max
    few_crossings = n > 0 and crossings < cross_min
    points = _mark_long(useful, run_lengths, run_max + 1, len(y)) if long_run else \
        np.zeros(len(y), dtype=bool)
    return RuleResult(points, {
        "n_useful": n,
        "longest_run": longest,
        "longest_run_max": run_max,
        "n_crossings": crossings,
        "n_crossings_min": cross_min,
        "longest_run_signal": bool(long_run),
        "crossings_signal": bool(few_crossings),
        "runs_signal": bool(long_run or few_crossings),
    })


def _run_lengths(side: np.ndarray) -> list[int]:
    """Lengths of the successive runs in a sequence of sides."""
    lengths: list[int] = []
    for i, s in enumerate(side):
        if i and s == side[i - 1]:
            lengths[-1] += 1
        else:
            lengths.append(1)
    return lengths


def _mark_long(useful, run_lengths, at_least: int, k: int) -> np.ndarray:
    marks = np.zeros(k, dtype=bool)
    start = 0
    for length in run_lengths:
        if length >= at_least:
            marks[useful[start:start + length]] = True
        start += length
    return marks


def _mark_runs(y: np.ndarray, cl: np.ndarray, at_least: int) -> np.ndarray:
    """Points in a run of at_least or more useful points on one side of the line."""
    useful, side = _sides(y, cl)
    return _mark_long(useful, _run_lengths(side), at_least, len(y))


# ---------------------------------------------------------------------------
# Trends and zones
# ---------------------------------------------------------------------------

def _mark_trends(y: np.ndarray, at_least: int, ties_break: bool = True) -> np.ndarray:
    """
    Points in at_least or more consecutive points steadily rising or falling. Missing
    points are skipped. With ties_break=False a repeated value is passed over, neither
    breaking nor extending the trend, as Provost & Murray count it.
    """
    marks = np.zeros(len(y), dtype=bool)
    idx = np.flatnonzero(np.isfinite(y))
    if not ties_break and len(idx):
        keep = [idx[0]]
        for i in idx[1:]:
            if y[i] != y[keep[-1]]:
                keep.append(i)
        idx = np.array(keep)
    if len(idx) < at_least:
        return marks
    steps = np.sign(np.diff(y[idx]))
    for direction in (1.0, -1.0):
        start = 0
        for j in range(len(steps) + 1):
            if j < len(steps) and steps[j] == direction:
                continue
            if j - start + 1 >= at_least:
                marks[idx[start:j + 1]] = True
            start = j + 1
    return marks


def _beyond(y, cl, sigma, k_sigma) -> tuple[np.ndarray, np.ndarray]:
    ok = np.isfinite(sigma) & (sigma > 0) & np.isfinite(y)
    with np.errstate(invalid="ignore"):
        return ok & (y > cl + k_sigma * sigma), ok & (y < cl - k_sigma * sigma)


def _zone(y, cl, sigma, at_least: int, window: int, k_sigma: float) -> np.ndarray:
    """Points beyond k_sigma, at least at_least of any window consecutive, one side."""
    marks = np.zeros(len(y), dtype=bool)
    for side in _beyond(y, cl, sigma, k_sigma):
        for i in range(window - 1, len(y)):
            span = slice(i - window + 1, i + 1)
            if side[span].sum() >= at_least:
                marks[span] |= side[span]
    return marks


def _stretch(y, cl, sigma, at_least: int, inside: bool) -> np.ndarray:
    """at_least consecutive points all within (or all outside) 1σ of the line."""
    up, down = _beyond(y, cl, sigma, 1.0)
    ok = np.isfinite(sigma) & np.isfinite(y)
    hit = ok & ~(up | down) if inside else (up | down)
    marks = np.zeros(len(y), dtype=bool)
    count = 0
    for i, h in enumerate(hit):
        count = count + 1 if h else 0
        if count >= at_least:
            marks[i - at_least + 1:i + 1] = True
    return marks


def _mark_alternating(y: np.ndarray, at_least: int) -> np.ndarray:
    """at_least consecutive points alternating up and down (Nelson rule 4)."""
    marks = np.zeros(len(y), dtype=bool)
    idx = np.flatnonzero(np.isfinite(y))
    for i in range(len(idx) - at_least + 1):
        chunk = idx[i:i + at_least]
        signs = np.sign(np.diff(y[chunk]))
        if np.all(signs != 0) and np.all(signs[:-1] == -signs[1:]):
            marks[chunk] = True
    return marks


# ---------------------------------------------------------------------------
# Provost & Murray (IHI)
# ---------------------------------------------------------------------------

def _ihi(y, cl, sigma, has_limits: bool) -> RuleResult:
    """
    Provost & Murray's rules. On a run chart: a shift of 6 or more on one side of the
    median, a trend of 5 or more rising or falling. On a Shewhart chart: a shift of 8,
    a trend of 6, 2 of 3 in the outer third (beyond 2σ) on one side, and 15 in a row in
    the inner third (within 1σ). Repeated values are passed over in a trend. The run
    chart's runs-count table is not implemented; Anhøj's crossings rule, the default
    method, answers the same question (docs/qic-methods.md).
    """
    if not has_limits:
        return _named({
            "shift of 6": _mark_runs(y, cl, 6),
            "trend of 5": _mark_trends(y, 5, ties_break=False),
        })
    return _named({
        "shift of 8": _mark_runs(y, cl, 8),
        "trend of 6": _mark_trends(y, 6, ties_break=False),
        "2 of 3 beyond 2 sigma": _zone(y, cl, sigma, 2, 3, 2.0),
        "15 within 1 sigma": _stretch(y, cl, sigma, 15, inside=True),
    })


# ---------------------------------------------------------------------------
# NHS Making Data Count
# ---------------------------------------------------------------------------

def _nhs(y, cl, sigma, ucl, lcl) -> RuleResult:
    """
    Making Data Count's four rules, as NHSRplotthedots implements them: a point beyond
    the limits; 7 in a row on one side of the mean (a point on the mean breaks it); 7 in
    a row rising or falling (a repeated value breaks it); 2 of 3 in a row between the 2σ
    and 3σ lines with all three on one side. Each point takes the first of these it is
    part of, in that order, as its special cause.
    """
    k = len(y)
    with np.errstate(invalid="ignore"):
        outside = (y > ucl) | (y < lcl)
        rel = np.sign(y - cl)
        near = ~outside & ((y > cl + 2 * sigma) | (y < cl - 2 * sigma))
    rel = np.where(np.isfinite(rel), rel, 0.0)
    trend = _nhs_trend(y)
    shift = _part_of_seven(_seven_one_side(rel))
    two3 = _two_in_three(near, rel)
    in_trend = _part_of_seven(trend) != 0

    # A point inside a trend takes the trend's direction; at the join of two trends,
    # the one it starts (NHSRplotthedots' "right side").
    step = np.sign(np.diff(y))
    left = np.concatenate([[0.0], step])
    right = np.concatenate([step, step[-1:]]) if k > 1 else left
    nxt = np.concatenate([in_trend[1:], [False]])
    trend_dir = np.where(nxt & in_trend, right, left)

    cause = np.full(k, "common cause", dtype=object)
    direction = np.zeros(k)
    side_word = np.where(rel > 0, "above", "below")
    for i in range(k):
        if outside[i]:
            cause[i], direction[i] = "beyond limits", rel[i]
        elif in_trend[i]:
            cause[i], direction[i] = "7 point trend", trend_dir[i]
        elif two3[i]:
            cause[i], direction[i] = f"2 of 3 near limit ({side_word[i]})", rel[i]
        elif shift[i]:
            cause[i], direction[i] = f"7 points {side_word[i]} mean", rel[i]
    points = (in_trend | two3 | (shift != 0)) & ~outside
    fired = [name for name, marks in (
        ("7 point trend", in_trend), ("2 of 3 near limit", two3), ("7 on one side", shift != 0),
    ) if np.any(marks)]
    return RuleResult(
        points, {"runs_signal": bool(points.any()), "rules_fired": fired},
        cause=cause, direction=direction,
    )


def _seven_one_side(rel: np.ndarray) -> np.ndarray:
    """1 at a point that is the 7th in a row on one side (rel: sign of y − mean)."""
    padded = np.concatenate([np.zeros(6), rel])
    return np.array([
        float(padded[i] != 0 and np.all(padded[i - 6:i] == padded[i]))
        for i in range(6, len(padded))
    ])


def _nhs_trend(y: np.ndarray) -> np.ndarray:
    """±1 at a point that ends 7 strictly rising (falling) points, else 0."""
    out = np.zeros(len(y))
    for i in range(6, len(y)):
        d = np.sign(np.diff(y[i - 6:i + 1]))
        if np.all(d == 1):
            out[i] = 1
        elif np.all(d == -1):
            out[i] = -1
    return out


def _part_of_seven(v: np.ndarray) -> np.ndarray:
    """Nonzero at every point of a 7-point pattern whose last point v marks."""
    padded = np.concatenate([v, np.zeros(6)])
    return np.array([float(np.any(np.abs(padded[i:i + 7]) == 1)) for i in range(len(v))])


def _two_in_three(near: np.ndarray, rel: np.ndarray) -> np.ndarray:
    """Near-limit points in a window of 3 with 2 or more near the limit, all one side."""
    k = len(near)
    vp = np.concatenate([[0, 0], near.astype(float), [0, 0]])
    rp = np.concatenate([[0, 0], rel, [0, 0]])
    hit = np.zeros(k, dtype=bool)
    for i in range(k):
        for a in (i, i + 1, i + 2):
            if vp[a:a + 3].sum() >= 2 and abs(rp[a:a + 3].sum()) == 3:
                hit[i] = True
                break
    return hit & near
