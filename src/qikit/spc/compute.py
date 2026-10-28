"""
compute.py — public, pure-numpy entry point for SPC limits and signal detection.

Bracketed references ([1] is Spiegelhalter 2005, Stat Med) are those of
docs/methods.md, as in limits.py.
"""

from __future__ import annotations

from typing import Any

import numpy as np

import math

from .limits import CHARTS, FUNNEL_CHARTS, VALID_CHARTS, funnel_dispersion
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
    limit_method: str = "exact",
    funnel: bool = False,
    signal_side: str = "both",
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
    limit_method : quantile method for charts with probability-based limits
                   ("exact" | "byar"). Ignored by every other chart type.
    funnel       : take the funnel version of p/pp/u/up (FUNNEL_CHARTS): exact
                   probability contours, and for pp/up the additive over-dispersion
                   adjustment. No effect on other charts. This does not sort — the
                   caller (qic) owns the ordering.
    signal_side  : which side sigma_signal flags — "both" (default), "above" (y > ucl
                   only) or "below" (y < lcl only). Runs rules are unaffected.

    Returns
    -------
    dict with keys: y, cl, ucl, lcl, sigma_signal, runs_signal, summary.
    Charts defining spec.limits_95 (funnels and oe/oep) also return ucl_95/lcl_95;
    every other chart leaves the caller to derive that band from the 3σ spread.
    Those charts also add to summary: limit_method, and where the chart has a count
    model (spec.family) the over-dispersion keys dispersion_phi, dispersion_tau and
    overdispersed, plus dispersion_method and dispersion_adjusted when the limits use
    the estimate. A time-ordered pp/up reports dispersion_method = "laney".
    """
    if chart not in CHARTS:
        raise ValueError(
            f"Unknown chart type: {chart!r}. "
            f"Valid types: {sorted(VALID_CHARTS)}"
        )

    spec = FUNNEL_CHARTS.get(chart, CHARTS[chart]) if funnel else CHARTS[chart]
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

    # Over-dispersion, estimated once per chart against the center line it is drawn
    # around [1, §5]. An unadjusted funnel reports it as a diagnostic; an adjusted one
    # also draws its limits from it. Baseline points only, as for the center line.
    dispersion: dict[str, Any] = {}
    tau2 = 0.0
    if spec.family is not None and n is not None:
        phi, tau2 = funnel_dispersion(cl_val, y, n, mask, spec.family)
        dispersion = {
            "dispersion_phi": phi,
            "dispersion_tau": math.sqrt(tau2),
            "overdispersed": tau2 > 0,
        }
        if spec.adjusted:
            dispersion["dispersion_method"] = "additive"
            dispersion["dispersion_adjusted"] = tau2 > 0
    elif chart in ("pp", "up"):
        # The same chart code means a different method in time order; say which.
        dispersion = {"dispersion_method": "laney"}

    # Limits. A chart whose center line varies per point (S chart with unequal
    # subgroup sizes, where CL = c4(nᵢ)·σ̂) returns it as an optional third element
    # rather than through spec.center, which is scalar by contract. An explicit
    # cl_override always wins — the user asked for a fixed line. diag collects any
    # point whose exact limits had to fall back to the normal approximation.
    diag: dict[str, Any] = {}
    limit_kw = dict(
        s_bar=s_bar, sigma_hat=sigma_hat, limit_method=limit_method,
        tau2=tau2 if spec.adjusted else 0.0, diag=diag,
    )
    ucl_arr, lcl_arr, *cl_var = spec.limits(cl_val, y, n, mask, subgroup_n, **limit_kw)
    if cl_override is None and cl_var and cl_var[0] is not None:
        cl_arr = np.asarray(cl_var[0], dtype=float)

    if spec.floor_lcl:
        lcl_arr = np.where(lcl_arr < 0, 0.0, lcl_arr)

    # Inner band. For most charts the caller scales the 3σ spread by 2/3, which is
    # exact when the limits are symmetric and normal. A funnel's limits are neither,
    # so its 95% contour has to be computed from the distribution in its own right.
    extra: dict[str, Any] = {}
    if spec.limits_95 is not None:
        ucl_95, lcl_95 = spec.limits_95(cl_val, y, n, mask, subgroup_n, **limit_kw)
        if spec.floor_lcl:
            lcl_95 = np.where(lcl_95 < 0, 0.0, lcl_95)
        extra["ucl_95"], extra["lcl_95"] = ucl_95, lcl_95

    # Signals — ghosted (exclude=) points are hidden from detection entirely.
    # Note this uses exclude_mask, not the baseline `mask`: freeze/part boundary
    # points are outside the baseline but must still be checked against it.
    if exclude_mask is None:
        y_signal = y
    else:
        y_signal = np.where(np.asarray(exclude_mask, dtype=bool), np.nan, y)
    sigma_sig = _sigma_signals(y_signal, ucl_arr, lcl_arr, signal_side)
    runs_sig, runs_loc, runs_summary = _runs_signals(y_signal, cl_arr, method=method, ucl=ucl_arr, lcl=lcl_arr)

    if spec.limits_95 is not None:
        # Which method drew the limits is not recoverable from the numbers alone, and a
        # funnel is the kind of chart that ends up in a credentialing file. Record it.
        runs_summary = {
            **runs_summary,
            "limit_method": (
                "normal" if diag.get("normal")
                else limit_method if chart == "oe" else "exact"
            ),
        }
    runs_summary = {**runs_summary, **dispersion}

    return {
        "y": y,
        "cl": cl_arr,
        "ucl": ucl_arr,
        "lcl": lcl_arr,
        "sigma_signal": sigma_sig,
        "runs_signal": runs_sig,
        "runs_signal_localized": runs_loc,
        "summary": runs_summary,
        # The τ² the limits were drawn with, unrounded. summary carries only √τ², and
        # squaring that back can miss these limits by an ulp when funnel_limits()
        # redraws them on a grid.
        "tau2": tau2 if spec.adjusted else 0.0,
        **extra,
    }


def funnel_limits(
    chart: str,
    cl: float,
    n: np.ndarray,
    tau2: float = 0.0,
    limit_method: str = "exact",
) -> dict[str, np.ndarray]:
    """
    A funnel's limits at arbitrary denominators, for drawing its contours.

    The same limit functions compute() uses, on the same call path, so a contour
    drawn through a point's own n passes exactly through the limit that decided its
    signal. chart is one of p, pp, u, up (their funnel versions) or oe, oep; cl and
    tau2 are on the raw scale, as compute() drew them; limit_method is the oe
    chart's input ("exact" | "byar"). The funnel limit functions read neither y nor
    the baseline mask, so neither is needed.

    Returns ucl, lcl, ucl_95, lcl_95 aligned with n.
    """
    spec = FUNNEL_CHARTS.get(chart, CHARTS[chart])
    if spec.limits_95 is None:
        raise ValueError(f"chart={chart!r} has no funnel limits.")
    n = np.asarray(n, dtype=float)
    placeholder = np.full(len(n), np.nan)
    mask = np.ones(len(n), dtype=bool)
    limit_kw = dict(
        limit_method=limit_method, tau2=tau2 if spec.adjusted else 0.0, diag={},
    )
    ucl, lcl = spec.limits(cl, placeholder, n, mask, None, **limit_kw)
    ucl_95, lcl_95 = spec.limits_95(cl, placeholder, n, mask, None, **limit_kw)
    if spec.floor_lcl:
        lcl = np.where(lcl < 0, 0.0, lcl)
        lcl_95 = np.where(lcl_95 < 0, 0.0, lcl_95)
    return {"ucl": ucl, "lcl": lcl, "ucl_95": ucl_95, "lcl_95": lcl_95}
