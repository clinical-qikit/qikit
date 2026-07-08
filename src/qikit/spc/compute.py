"""
compute.py — public, pure-numpy entry point for SPC limits and signal detection.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .limits import CHARTS, VALID_CHARTS
from .signals import _runs_signals, _sigma_signals


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
