"""
extras.py — paretochart() and bchart(): two charts that are neither a series nor a funnel.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .results import BChartResult, ParetoResult


def paretochart(x: Any, data: pd.DataFrame | None = None, use_na: bool = False) -> ParetoResult:
    """
    Categories by frequency, largest first, with the cumulative share: the "vital few"
    behind most of a problem. x is a column of data or a sequence of categories.
    Returns columns category, count, cum_sum, cum_percent.
    """
    if data is not None and isinstance(x, str):
        if x not in data.columns:
            raise ValueError(f"x={x!r} is not a column of data.")
        vals = data[x]
    else:
        vals = pd.Series(x)
    counts = vals.value_counts(dropna=not use_na).sort_values(ascending=False)
    df = counts.reset_index()
    df.columns = ["category", "count"]
    df["cum_sum"] = df["count"].cumsum()
    df["cum_percent"] = df["cum_sum"] / df["count"].sum() * 100
    return ParetoResult(df, {"n": int(df["count"].sum()), "x_name": x if isinstance(x, str) else None})


def bchart(
    x: Any, target: float | None = None, baseline: int | None = None,
    or_ratio: float = 2.0, limit: float = 3.5,
) -> BChartResult:
    """
    Bernoulli CUSUM for case-by-case binary outcomes (Neuburger et al. 2017; qicharts2's
    bchart): one cumulative sum looking for the odds of failure rising by or_ratio,
    another for it falling by the same factor, each signalling at limit.

    x : 0/1 outcomes in time order (1 = the event, e.g. a complication).
    target : the expected event probability p0. Or baseline=k: p0 is the event rate of
        the first k cases. With neither, p0 is the rate over all cases.
    Returns columns x (case number), y, cusum_up, cusum_down, signal_up, signal_down,
    limit; summary target, or_ratio, limit, signal_up, signal_down.
    """
    x_arr = np.asarray(x, dtype=float)
    n = len(x_arr)
    if target is not None and baseline is not None:
        raise ValueError("Pass target= (a probability) or baseline= (a number of cases), not both.")
    if baseline is not None:
        p0 = float(np.nanmean(x_arr[:int(baseline)]))
    elif target is not None:
        p0 = float(target)
    else:
        p0 = float(np.nanmean(x_arr))
    if not (0 < p0 < 1):
        raise ValueError(f"The baseline event probability must lie between 0 and 1, got {p0!r}.")

    def shifted(p, odds):
        return (p * odds) / (1 - p + p * odds)

    p1, p2 = shifted(p0, or_ratio), shifted(p0, 1.0 / or_ratio)
    with np.errstate(divide="ignore", invalid="ignore"):
        s1 = x_arr * np.log(p1 / p0) + (1 - x_arr) * np.log((1 - p1) / (1 - p0))
        s2 = x_arr * np.log(p2 / p0) + (1 - x_arr) * np.log((1 - p2) / (1 - p0))
    c1, c2 = np.zeros(n), np.zeros(n)
    sig1, sig2 = np.zeros(n, dtype=bool), np.zeros(n, dtype=bool)
    z1 = z2 = 0.0
    for i in range(n):
        if np.isnan(s1[i]):
            c1[i], c2[i] = z1, z2
            continue
        up = z1 + s1[i]
        sig1[i] = up >= limit
        c1[i] = z1 = up * (up > 0) * (up <= limit)
        down = z2 - s2[i]
        sig2[i] = down <= -limit
        c2[i] = z2 = down * (down < 0) * (down >= -limit)
    df = pd.DataFrame({
        "x": np.arange(1, n + 1), "y": x_arr, "cusum_up": c1, "cusum_down": c2,
        "signal_up": sig1, "signal_down": sig2, "limit": limit,
    })
    return BChartResult(df, {
        "target": p0, "or_ratio": or_ratio, "limit": limit,
        "signal_up": bool(sig1.any()), "signal_down": bool(sig2.any()),
    })
