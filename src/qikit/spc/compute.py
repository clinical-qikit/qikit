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
    exclude_mask: np.ndarray | None = None,
    sigma_hat: float | None = None,
) -> dict[str, Any]:
    """
    Compute SPC limits and signals for a single chart.

    Parameters
    ----------
    chart        : chart type key (must be in CHARTS)
    y            : numeric values, may contain NaN
    n            : denominators for p/u/pp/up charts
    mask         : True = include in baseline; None = all included. Also
                   covers freeze/part boundaries, so points outside the
                   baseline window still get checked against its limits.
    cl_override  : user-specified fixed center line
    subgroup_n   : fallback scalar subgroup size for s/xbar charts, used only
                   when n is not supplied. Not a constraint — any size >= 2 is
                   valid.
    method       : run-signal method ("anhoej", "ihi", "weco", "nelson")
    s_bar        : arithmetic mean of subgroup SDs — equal-n s/xbar charts
    sigma_hat    : pooled σ̂ — s/xbar charts with unequal subgroup sizes.
                   Mutually exclusive with s_bar; see _xbar_limits for why.
    exclude_mask : True = ghost this point out of signal detection entirely
                   (exclude=); None = no ghosting. Unlike `mask`, this does
                   not include freeze/part boundaries.

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

    # Limits. A chart whose center line varies per point (S chart with unequal
    # subgroup sizes, where CL = c4(nᵢ)·σ̂) returns it as an optional third element
    # rather than through spec.center, which is scalar by contract. An explicit
    # cl_override always wins — the user asked for a fixed line.
    ucl_arr, lcl_arr, *cl_var = spec.limits(
        cl_val, y, n, mask, subgroup_n, s_bar=s_bar, sigma_hat=sigma_hat
    )
    if cl_override is None and cl_var and cl_var[0] is not None:
        cl_arr = np.asarray(cl_var[0], dtype=float)

    if spec.floor_lcl:
        lcl_arr = np.where(lcl_arr < 0, 0.0, lcl_arr)

    # Signals — ghosted (exclude=) points are hidden from detection entirely.
    # Note this uses exclude_mask, not the baseline `mask`: freeze/part boundary
    # points are outside the baseline but must still be checked against it.
    if exclude_mask is None:
        y_signal = y
    else:
        y_signal = np.where(np.asarray(exclude_mask, dtype=bool), np.nan, y)
    sigma_sig = _sigma_signals(y_signal, ucl_arr, lcl_arr)
    runs_sig, runs_loc, runs_summary = _runs_signals(y_signal, cl_arr, method=method, ucl=ucl_arr, lcl=lcl_arr)

    return {
        "y": y,
        "cl": cl_arr,
        "ucl": ucl_arr,
        "lcl": lcl_arr,
        "sigma_signal": sigma_sig,
        "runs_signal": runs_sig,
        "runs_signal_localized": runs_loc,
        "summary": runs_summary,
    }
