"""
_funnel/pipeline.py — the pipeline: every facet's funnel, and each facet's fit, limits,
p-values and signals.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from ..core.contours import funnel_contours
from ..core.dispersion import overdispersion, pooled, tau2_ml
from ..core.power import point_power
from ..core.pvalues import bh_q_values, funnel_p_values
from ..core.shrinkage import fit_prior
from ..results import FunnelResult
from ..within import Within, check_aggregated, within
from .constants import _DROP, _EXCL, _LABEL, _MAXN, _MAXY, _N, _UNIT, _Y
from .estimates import _add_estimates, _add_robustness
from .settings import _Fit, _Settings
from .summary import (
    _QUESTION,
    _add_benchmark,
    _center_gap,
    _expected_false_flags,
    _notes,
    _power,
    _shape,
)


def _funnel(frame, st: _Settings, within_dispersion, aggregated: bool, phi_column, names):
    """Every facet's funnel, and the result that holds them."""
    if aggregated:
        check_aggregated(frame, st.facets)
    keys = list(st.facets)
    if keys:
        groups = [((k if isinstance(k, tuple) else (k,)), rows)
                  for k, rows in frame.groupby(keys, sort=False, dropna=False)]
    else:
        groups = [((), frame)]
    tables, by_facet, models = [], {}, {}
    lost: dict[Any, int] = {}
    for key, rows in groups:
        name = " / ".join(str(v) for v in key) if key else None
        dropped = int(rows[_DROP].sum())
        rows = rows[rows[_UNIT].notna()]
        if rows.empty:                       # a facet whose every row lacks a unit
            lost[name] = dropped
            continue
        phi = within(rows, st.measure, within_dispersion, aggregated, phi_column)
        tau_fixed = _facet_value(st.tau_fixed, key, name)
        table, summary, model = _one_funnel(rows, st, phi, tau_fixed, aggregated, dropped)
        model["key"] = key
        for i, (col, val) in enumerate(zip(keys, key)):
            table.insert(i, col, val)
        tables.append(table)
        by_facet[name] = summary
        models[name] = model
    data = pd.concat(tables, ignore_index=True) if len(tables) > 1 else tables[0]
    settings = {
        "measure": st.measure, "overdispersion": st.overdispersion, "worse": st.worse,
        "signal": st.signal, "limits": st.limits, "fdr_levels": st.fdr_levels,
        "tau_method": st.tau_method, "fdr_min_denominator": st.fdr_min,
        "compare_to": st.question,
    }
    if not keys:
        summary = {**settings, **by_facet[None]}
    else:
        totals = {k: sum(f[k] for f in by_facet.values())
                  for k in ("n_providers", "n_tested", "n_outlier", "n_alert", "n_filtered",
                            "n_fragile", "n_rows_dropped")}
        totals["n_rows_dropped"] += sum(lost.values())
        notes = [f"{fv}: {note}" for fv, f in by_facet.items() for note in f["notes"]]
        notes += [f"{fv}: all {k} row(s) are missing unit=, so this facet has no chart."
                  for fv, k in lost.items()]
        summary = {**settings, **totals, "by_facet": by_facet, "notes": notes}
    meta = {
        "facets": keys, "hover": list(st.hover), "worse": st.worse, "side": st.side,
        "signal": st.signal, "limits": st.limits, "fdr_levels": st.fdr_levels,
        "measure": st.measure, "y_name": names["y"] if isinstance(names["y"], str) else None,
        "n_name": names["n"] if isinstance(names["n"], str) else None,
        "phi_column": phi_column, "multiply": st.multiply, "interval": st.interval,
    }
    return FunnelResult(data=data, summary=summary, _models=models, _meta=meta)


def _facet_value(value, key: tuple, name: str | None):
    """A per-facet setting (tau=): the facet's value, keyed by value, tuple or label."""
    if not isinstance(value, dict):
        return value
    for candidate in (key[0] if len(key) == 1 else None, key, name):
        if candidate in value:
            return value[candidate]
    raise ValueError(f"tau= as a dict needs one value per facet; missing {name!r}.")


def _one_funnel(rows, st: _Settings, within: Within, tau_fixed, aggregated: bool,
                dropped: int = 0):
    """One facet: (public table, summary, model for limits())."""
    family, _binomial = st.family, st.measure == "proportion"
    units = rows.groupby(_UNIT, sort=False)
    # min_count=1: a provider with no complete row sums to missing, not to zero.
    agg = pd.DataFrame({_Y: units[_Y].sum(min_count=1), _N: units[_N].sum(min_count=1)})
    for col in (_LABEL, *st.hover, _MAXY, _MAXN):
        if col in rows:
            agg[col] = units[col].first()
    agg[_EXCL] = units[_EXCL].any() if _EXCL in rows else False
    phi_u = (np.array([within.phi_units[u] for u in agg.index], dtype=float)
             if within.phi_units is not None else np.full(len(agg), within.phi))
    num, den = agg[_Y].to_numpy(dtype=float), agg[_N].to_numpy(dtype=float)
    empty = np.isnan(den)                    # no complete row: drawn nowhere, untested
    volume = np.where(empty, 0.0, den)
    n_model = volume if within.phi_units is None and within.phi == 1.0 else volume / phi_u
    order = np.argsort(n_model, kind="stable")
    agg, num, den, n_model, phi_u = agg.iloc[order], num[order], den[order], n_model[order], phi_u[order]
    excluded = agg[_EXCL].to_numpy(dtype=bool)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(den > 0, num / den, np.nan)
    _check_counts(st.measure, num, den)
    mask = ~excluded
    tested = np.where(excluded, np.nan, ratio)

    # The center line and the spread between providers.
    cl = st.center if st.center is not None else pooled(ratio, n_model, mask)
    estimator = "winsorized" if st.tau_method == "ml" else st.tau_method
    disp = overdispersion(estimator, family, cl, ratio, n_model, mask, st.center is not None)
    tau_ci = None
    if tau_fixed is not None:
        tau2, source = float(tau_fixed), "pre-specified"
    elif st.tau_method == "ml":
        tau2, tau_ci = tau2_ml(cl, ratio, n_model, mask, family)
        source = "estimated"
    else:
        tau2, source = disp.tau2, "estimated"
    used = tau2 if st.overdispersion else 0.0
    scale = disp.scale if used > 0 else "natural"
    fit = _Fit(family, float(cl), ratio, n_model, mask, used, scale)

    # Contours, tests and tiers.
    lim = funnel_contours(family, cl, n_model, used, st.limits, st.limit_method, scale)
    p, p_method, model_name = funnel_p_values(
        cl, tested, n_model, used, family, st.side, scale, byar=st.limit_method == "byar",
    )
    filtered = (np.zeros(len(p), dtype=bool) if st.fdr_min is None
                else np.isfinite(p) & ((den if st.measure == "mean" else n_model) < st.fdr_min))
    q = bh_q_values(np.where(filtered, np.nan, p))
    if st.signal == "limits":
        outlier = _beyond(tested, lim.ucl, lim.lcl, st.side)
        alert = _beyond(tested, lim.ucl_95, lim.lcl_95, st.side) & ~outlier
    else:
        with np.errstate(invalid="ignore"):
            outlier = q < st.fdr_levels[0]
            alert = (q < st.fdr_levels[1]) & ~outlier

    det, ci_lo, ci_hi = point_power(family, ratio, n_model, lim.ucl)
    m = st.multiply
    table = pd.DataFrame({"unit": agg.index.to_numpy()})
    if _LABEL in agg:
        table["label"] = agg[_LABEL].to_numpy()
    table["y"] = ratio * m
    table["numerator"] = num
    table["denominator"] = den
    if within.phi_units is not None:
        table["effective_denominator"] = n_model
    table["cl"] = np.full(len(table), cl * m)
    table["lower_outlier"], table["upper_outlier"] = lim.lcl * m, lim.ucl * m
    table["lower_alert"], table["upper_alert"] = lim.lcl_95 * m, lim.ucl_95 * m
    table["p_value"], table["q_value"] = p, q
    table["signal"] = np.where(outlier, "outlier", np.where(alert, "alert", "none"))
    table["direction"] = np.where(ratio >= cl, "higher", "lower")
    table["min_detectable"] = np.where(np.isinf(det), np.nan, det) * m
    table["ci_lower"], table["ci_upper"] = ci_lo * m, ci_hi * m
    table["excluded"] = excluded
    for col in st.hover:
        table[col] = agg[col].to_numpy()
    model_question = st.question == "model"
    prior = fit_prior(cl, ratio, n_model, mask, family, model=model_question,
                      spread=st.overdispersion or model_question, tau_fixed=tau_fixed,
                      tau2_chart=used, scale=scale)
    _add_estimates(table, st, fit, prior)
    fragile = _add_robustness(table, rows, agg, st, fit, phi_u, aggregated)

    summary = {
        "n_providers": int(len(table)),
        "n_tested": int(np.sum(np.isfinite(p))),
        "n_outlier": int(np.sum(outlier & mask)),
        "n_alert": int(np.sum(alert & mask)),
        "center": float(cl),
        "tau": math.sqrt(tau2),
        "tau_scale": disp.scale,
        "tau_method": st.tau_method,
        "tau_source": source,
        "tau_estimated": math.sqrt(disp.tau2),
        "tau_ci": None if tau_ci is None else tuple(float(c) for c in tau_ci),
        "phi": disp.phi,
        "count_model": model_name,
        "limit_method": lim.method,
        "p_value_method": p_method,
        "within_dispersion": _mean_phi(den, n_model) if within.phi_units is not None else within.phi,
        "within_dispersion_source": within.source,
        "n_filtered": int(np.sum(filtered)),
        "n_fragile": fragile,
        "n_rows_dropped": dropped,
        "reference": prior.reference * m,
    }
    if st.measure == "mean":
        phi_bar = _mean_phi(den, n_model) if within.phi_units is not None else within.phi
        summary["case_sd"] = math.sqrt(phi_bar * cl) * m
    summary["expected_false_flags"] = _expected_false_flags(st, summary)
    notes: list[str] = []
    if st.compare_to is not None:
        notes.append(_QUESTION[st.compare_to])
    if dropped:
        note = (f"{dropped} row(s) were missing y=, n= or unit= and were left out: they "
                f"are not counted as zero.")
        if empty.any():
            note += (f" {int(empty.sum())} provider(s) have no complete row and are listed "
                     f"untested, with no value.")
        notes.append(note)
    summary.update(_center_gap(st, fit, source, disp.scale, notes))
    summary["estimate_tau"] = math.sqrt(prior.tau2)
    summary["estimate_tau_ci"] = prior.tau_ci
    if (st.overdispersion or prior.model) and not prior.available:
        notes.append(
            "Shrunk estimates with a range are unavailable: the funnel finds no measurable "
            "spread between providers (tau = 0), so eb_low, eb_high and estimate_flag are "
            "empty. Pass tau= estimated from earlier periods, or compare within a larger "
            "peer group."
        )
    if st.benchmark is not None:
        _add_benchmark(table, summary, notes, st, fit, num, den, excluded)
    summary.update({"dispersion_shape": None, "within_dispersion_hint": None,
                    "within_dispersion_hint_source": None, "underpowered": None,
                    "n_underpowered": None, "min_detectable_median": None})
    summary.update(_shape(fit, within, st.measure, notes))
    summary.update(_power(st.measure, det, cl, excluded, notes))
    _notes(summary, st, notes)
    summary["notes"] = notes
    model = {
        "family": family, "cl": float(cl), "tau2": used, "scale": scale,
        "levels": st.limits, "limit_method": st.limit_method, "multiply": m,
        "prior": prior,
        "phi": None if within.phi_units is not None else within.phi,
        "axis": table["effective_denominator" if within.phi_units is not None
                      else "denominator"].to_numpy(dtype=float),
    }
    return table, summary, model


def _beyond(y, upper, lower, side: str) -> np.ndarray:
    """Strictly beyond a contour, on the flagged side; a missing value never is."""
    with np.errstate(invalid="ignore"):
        above = ~np.isnan(upper) & (y > upper)
        below = ~np.isnan(lower) & (y < lower)
    return above if side == "above" else below if side == "below" else above | below


def _check_counts(measure: str, num: np.ndarray, den: np.ndarray) -> None:
    ok = np.isfinite(num) & np.isfinite(den)
    if np.any(ok & ((num < 0) | (den < 0))):
        raise ValueError("y= and n= must be 0 or more: counts of events and their denominators.")
    if measure == "proportion" and np.any(ok & (num > den)):
        raise ValueError("measure='proportion' counts events out of cases, so y cannot exceed n.")
    if np.any(ok & (den == 0) & (num > 0)):
        raise ValueError("Some providers have events but a zero denominator. Exclude them or "
                         "correct n=.")


def _mean_phi(den, n_model) -> float:
    """The volume-weighted φ̄ = Σn / Σ(n/φᵢ) behind a within_dispersion column."""
    eff = float(np.nansum(n_model))
    return float(np.nansum(den)) / eff if eff > 0 else math.nan
