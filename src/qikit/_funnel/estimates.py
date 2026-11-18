"""
_funnel/estimates.py — per-provider shrunk estimates and single-case robustness (fragility).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..core.pvalues import funnel_p_values, signal_thresholds
from ..core.shrinkage import Prior, estimate_flag, shrink
from .constants import _FRAGILITY_MAX, _MAXN, _MAXY, _N, _UNIT, _Y
from .settings import _Fit, _Settings


def _add_estimates(table, st: _Settings, fit: _Fit, prior: Prior) -> None:
    """
    raw_excess, reliability, eb_rate, eb_excess, prob_worse, eb_low, eb_high,
    estimate_flag (core/shrinkage.py, methods §4.14). raw_excess stays against the
    center line; eb_excess, prob_worse and estimate_flag are against the prior's
    reference (the center line, or 1.0 under compare_to="model").
    """
    sign = -1.0 if st.worse == "lower" else 1.0
    num = table["numerator"].to_numpy(dtype=float)
    den = table["denominator"].to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        y = num / den
    s = shrink(prior, y, fit.n_model, st.interval, st.worse == "lower")
    m = st.multiply
    table["raw_excess"] = sign * (num - fit.cl * den)
    table["reliability"] = s.reliability
    table["eb_rate"] = s.estimate * m
    table["eb_excess"] = sign * (s.estimate - prior.reference) * den
    table["prob_worse"] = s.prob_worse
    table["eb_low"], table["eb_high"] = s.low * m, s.high * m
    table["estimate_flag"] = estimate_flag(s.low, s.high, prior.reference, st.worse)


def _add_robustness(table, rows, agg, st: _Settings, fit: _Fit, phi_u, aggregated) -> int:
    """
    p_value_drop1, flag_survives_drop1, fragility (methods §4.15); returns how many flagged
    providers have fragility 1. θ₀, τ² and φ stay at their full-data values; only the
    provider's own count and denominator move, so each recomputed p-value is the chart's.
    """
    cl, tau2, scale = fit.cl, fit.tau2, fit.scale
    k = len(table)
    p_drop: np.ndarray = np.full(k, np.nan)
    survives = pd.array([pd.NA] * k, dtype="boolean")
    fragility = pd.array([pd.NA] * k, dtype="Int64")
    groups = rows.groupby(_UNIT, sort=False)
    case_level = not aggregated and bool((groups.size() > 1).any())
    if case_level or (aggregated and _MAXY in agg):
        units = table["unit"].to_numpy()
        excl = table["excluded"].to_numpy(dtype=bool)
        tot_y = table["numerator"].to_numpy(dtype=float)
        tot_n = table["denominator"].to_numpy(dtype=float)
        own = tot_y - cl * tot_n
        dirs: np.ndarray = np.full(k, -1.0 if st.worse == "lower" else 1.0)
        if st.worse is None:
            dirs = np.where(own >= 0, 1.0, -1.0)
        if st.signal == "fdr":
            q, p = table["q_value"].to_numpy(dtype=float), table["p_value"].to_numpy(dtype=float)
            hit = np.isfinite(q) & (q < st.fdr_levels[1])
            cutoff, inclusive = (float(np.max(p[hit])) if hit.any() else -1.0), True
        else:
            cutoff, inclusive = signal_thresholds(st.side, st.limits)[1], False

        def keeps(pv):
            return pv <= cutoff if inclusive else pv < cutoff

        def p_after(j, drop_y, drop_n):
            ny, nn = tot_y[j] - drop_y, tot_n[j] - drop_n
            with np.errstate(divide="ignore", invalid="ignore"):
                ratio = np.where(nn > 0, ny / nn, np.nan)
            pv, _, _ = funnel_p_values(cl, ratio, np.where(nn > 0, nn / phi_u[j], np.nan),
                                       tau2, st.family, st.side, scale)
            return pv, ratio

        cases_of = {}
        worst_y: np.ndarray = np.full(k, np.nan)
        worst_n = np.full(k, np.nan)
        if case_level:
            for j, u in enumerate(units):
                g = rows.loc[groups.groups[u]]
                yy, nn = g[_Y].to_numpy(dtype=float), g[_N].to_numpy(dtype=float)
                order = np.argsort(-dirs[j] * (yy - cl * nn), kind="stable")
                cases_of[u] = (yy[order], nn[order])
                if len(yy) > 1:
                    worst_y[j], worst_n[j] = yy[order[0]], nn[order[0]]
        else:
            worst_y = agg[_MAXY].to_numpy(dtype=float)
            worst_n = agg[_MAXN].to_numpy(dtype=float)
            # The SQL worst case is the most extreme toward worse= (or upward): it says
            # nothing about a provider whose own excess runs the other way.
            with np.errstate(invalid="ignore"):
                toward = np.sign(worst_y - cl * worst_n) == dirs
            worst_y = np.where(toward, worst_y, np.nan)
        ok = np.isfinite(worst_y) & np.isfinite(worst_n) & ~excl
        idx = np.arange(k)
        pv, ratio = p_after(idx, np.where(ok, worst_y, 0.0), np.where(ok, worst_n, 0.0))
        p_drop = np.where(ok, pv, np.nan)
        flagged = (table["signal"].to_numpy() != "none") & ~excl
        same_side = np.sign(ratio - cl) == dirs
        for j in np.flatnonzero(flagged & np.isfinite(p_drop)).tolist():
            survives[j] = bool(keeps(p_drop[j]) and same_side[j])
        if case_level:
            for j in np.flatnonzero(flagged).tolist():
                yy, nn = cases_of[units[j]]
                cap = min(len(yy) - 1, _FRAGILITY_MAX)
                if cap < 1:
                    continue
                cy, cn = np.cumsum(yy)[:cap], np.cumsum(nn)[:cap]
                jj = np.full(cap, j)
                pm, rm = p_after(jj, cy, cn)
                lost = ~(keeps(pm) & (np.sign(rm - cl) == dirs[j]))
                if lost.any():
                    fragility[j] = int(np.argmax(lost)) + 1
    table["p_value_drop1"] = p_drop
    table["flag_survives_drop1"] = survives
    table["fragility"] = fragility
    flagged = table["signal"].to_numpy() != "none"
    return int(((fragility == 1).fillna(False).to_numpy(dtype=bool) & flagged).sum())
