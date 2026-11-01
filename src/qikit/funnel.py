"""
funnel.py — funnel(): compare providers on one measure, and flag the unusual ones.

    from qikit import funnel
    r = funnel(df, y="deaths", n="expected", measure="oe", unit="surgeon", worse="higher")
    r.data[r.data.signal != "none"]      # who flagged, and how strongly
    r.summary                            # model, expected chance flags, notes
    r.plot()

The pipeline, per facet, top to bottom: sum each provider's rows; set the centre line
θ₀; estimate the spread between providers τ² (core/dispersion.py); draw the contours at
every provider's denominator (core/contours.py); test each provider against them
(core/pvalues.py); add what each provider could have shown (core/power.py), shrunk
estimates and single-case robustness. docs/methods.md is the canonical account of each
method and every departure from Spiegelhalter (2005).
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, replace
from typing import Any

import numpy as np
import pandas as pd

from .core.contours import DEFAULT_LEVELS, beta_params, funnel_contours
from .core.dispersion import (
    DEFAULT_TAU_METHOD, TAU_METHODS, dispersion_shape, natural_tau2,
    overdispersion, tau2_ml, transform_scale,
)
from .core.dist import beta_tails, gamma_tails
from .core.power import UNDERPOWERED_RATIO, point_power
from .core.pvalues import bh_q_values, funnel_p_values, signal_thresholds
from .results import FunnelResult
from .validate import (
    WORSE, check_choice, check_facet_names, check_levels, check_number, reject_removed,
    split_facets,
)

MEASURES = ("oe", "proportion", "rate")
SIGNALS = ("limits", "fdr")
DEFAULT_FDR_LEVELS = (0.05, 0.10)
_SIDES = {None: "both", "higher": "above", "lower": "below"}

# Column names funnel() writes to result.data; hover= columns must avoid them.
_COLUMNS = (
    "unit", "label", "y", "numerator", "denominator", "effective_denominator", "cl",
    "lower_outlier", "upper_outlier", "lower_alert", "upper_alert",
    "p_value", "q_value", "signal", "direction", "min_detectable", "ci_lower", "ci_upper",
    "excluded", "raw_excess", "reliability", "eb_rate", "eb_excess", "prob_worse",
    "p_value_drop1", "flag_survives_drop1", "fragility",
)

# Internal working columns on the normalized frame.
_UNIT, _Y, _N, _LABEL, _EXCL = "__unit", "__y", "__n", "__label", "__exclude"
_CASES, _SS, _MAXY, _MAXN, _PHI = "__cases", "__sum_sq", "__max_y", "__max_n", "__phi"

# fragility scans at most this many of a unit's worst cases (methods §4.15).
_FRAGILITY_MAX = 50

# How a funnel draws, for the parts of qikit's own engine contract that funnel() keeps
# private: Byar limits on O/E exist for the shared fixtures with the TypeScript engine.
_LIMIT_METHODS = ("exact", "byar")

_RENAMED = {
    "test_min_expected": "fdr_min_denominator=",
    "signal_side": "worse= ('higher', 'lower' or None)",
    "signal_method": "signal=",
    "levels": "limits=",
    "cl": "center=",
    "point_labels": "label=",
    "hover_extra": "hover=",
}
_DISPLAY = (
    "title", "subtitle", "caption", "xlab", "ylab", "label_signals", "styles", "x_log",
    "x_range", "y_range", "show_legend", "width", "height",
)


def funnel(
    data: pd.DataFrame | None = None,
    *,
    y: Any,
    n: Any,
    measure: str,
    unit: Any = None,
    label: Any = None,
    hover: Any = None,
    facets: str | list[str] | None = None,
    exclude: Any = None,
    center: float | None = None,
    overdispersion: bool = True,
    within_dispersion: float | str = 1.0,
    tau_method: str = DEFAULT_TAU_METHOD,
    tau: float | dict | None = None,
    cases: str | None = None,
    sum_sq: str | None = None,
    max_case_y: str | None = None,
    max_case_n: str | None = None,
    fdr_min_denominator: float | None = None,
    worse: str | None = None,
    signal: str = "limits",
    limits: tuple[float, float] = DEFAULT_LEVELS,
    fdr_levels: tuple[float, float] = DEFAULT_FDR_LEVELS,
    multiply: float = 1.0,
    **removed: Any,
) -> FunnelResult:
    """
    Compare providers on one measure with a funnel plot, and flag the unusual ones.
    Returns a FunnelResult; result.data is the table, result.plot() the figure.

    Choosing the settings
    ---------------------
    | You have                                          | Pass                                   |
    |---------------------------------------------------|----------------------------------------|
    | observed events and risk-model expected events     | measure="oe", y=observed, n=expected   |
    | events out of cases (mortality %, H&P in 24 h)     | measure="proportion", y=events, n=cases|
    | events over exposure (infections per line-day)     | measure="rate", y=events, n=exposure   |
    | DAYS or anything where one case adds many units    | stay-level rows (one per case), and    |
    |   (length of stay as observed/expected days)       | within_dispersion="estimate"           |
    | items of a multi-question survey or audit, scored  | one row per survey (y = items "Always",|
    |   per item (HCAHPS composites, top-/bottom-box)    | n = items answered), measure=          |
    |                                                    | "proportion", within_dispersion=       |
    |                                                    | "estimate"                             |
    | the same, but summed per provider in SQL (one row  | y, n, cases=, sum_sq= and              |
    |   per provider) so the stays never leave Snowflake | within_dispersion="estimate"           |
    | stays whose variability differs by DRG / service   | within_dispersion="<column>" holding   |
    |   line (a case-mix-weighted φ per provider)        |   each provider's φᵢ, computed in SQL  |
    | a flag a leader will ask "is it one patient?"      | case-level rows (automatic), or        |
    |   about                                            |   max_case_y=, max_case_n= from SQL    |
    | a measure where only one direction is bad          | worse="higher" (or "lower")            |
    | hundreds of providers, and want few false alarms   | signal="fdr"                           |
    | many very-low-volume providers diluting the        | fdr_min_denominator= (a volume floor   |
    |   signal="fdr" step                                |   for the FDR step only)               |
    | the spread between providers known from earlier    | tau=<that value> (a number, or one per |
    |   periods, or few providers (K < 30)               |   facet): fixed in advance             |
    | to reproduce a CQC or NHS SHMI funnel              | tau_method="cqc" or "shmi"             |
    | to rank flagged providers for action               | sort by eb_excess, not raw_excess      |
    | to say "probably worse than average" (CMS-style)   | read prob_worse; signal is unchanged   |
    | several measures or service lines in one call      | facets=["measure"] (one or more cols)  |

    Two questions, both legitimate (methods §2): the default, overdispersion=True, asks
    "is this provider unusual among its peers?", judging each provider against the
    measured spread between providers as well as chance; when there is no spread the
    chart is identical to the unadjusted one. overdispersion=False with center=1.0 asks
    "does this provider differ from the risk model?". Decide which before looking.

    Reading the result
    ------------------
    result.data has one row per provider (per unit and facet), in plotted order (by
    denominator):

    - signal: "outlier", "alert" or "none". The tiers never overlap; an outlier is
      not also an alert. Under worse= only the worse side is flagged.
    - direction: "higher" or "lower", which side of the centre line the point is on.
    - y: the plotted value (O/E ratio, proportion or rate, after multiply=);
      numerator and denominator: the summed y= and n= inputs, in the caller's units.
    - effective_denominator: only with a per-provider within_dispersion column: the
      denominator ÷ φᵢ the model sees, which is the x axis of the plot.
    - cl: the centre line. lower_outlier / upper_outlier: the outer contour (99.8% by
      default); lower_alert / upper_alert: the inner one (95%). Each contour is the
      boundary of the test, so a point is beyond the upper_outlier line exactly when
      its one-sided p-value is below 0.001.
    - p_value: against the same model the contours are drawn from (one-sided toward
      worse=, or doubled for two-sided); q_value: its Benjamini–Hochberg adjustment
      across the providers in this chart (each facet separately; excluded providers are
      not tested).
    - min_detectable: the smallest true value this provider could have flagged with
      80% power. A provider inside the funnel at physician volumes is often "not
      enough data", not "fine". ci_lower / ci_upper: an exact 95% interval for the
      provider's own value.
    - excluded: dropped from the centre line, the dispersion estimates and testing.
    - raw_excess: (numerator − cl·denominator), signed so positive is worse: the
      excess days or events.
    - reliability: the shrinkage weight, 0 to 1: how much of the provider's difference
      is signal rather than chance (methods §4.14). 0 for every provider when the
      funnel finds no spread (τ̂ = 0) or overdispersion=False. 0.7 is the usual floor
      for high-stakes use of a single score.
    - eb_rate, eb_excess: the shrunk (empirical Bayes) value and its excess, the exact
      posterior mean of the chart's own Poisson–gamma or beta-binomial model. Sort on
      eb_excess to prioritise.
    - prob_worse: the posterior probability that the provider's true value is worse
      than cl ("is this provider truly worse than average?", the CMS question), where
      signal answers "is it unusual among peers?" (methods §4.16). NaN when τ = 0.
    - p_value_drop1, flag_survives_drop1, fragility: single-case robustness (case-level
      rows, or max_case_y=/max_case_n= from SQL). Descriptive, never a test (§4.15).
    - one column per facets= column, and the hover= columns.

    result.summary: n_providers, n_tested, n_outlier, n_alert, expected_false_flags
    (per tier: the chance count under signal="limits", the false discovery bound under
    "fdr"), center, tau (the spread of true values between providers; on the
    transformed scale under "cqc"/"shmi", see tau_scale), phi, tau_method, tau_source,
    tau_estimated, tau_ci ("ml"), count_model, limit_method, p_value_method,
    within_dispersion and its source, dispersion_shape, underpowered, n_underpowered,
    min_detectable_median, n_filtered, n_fragile, and notes (sentences to show readers).
    Faceted: the counts summed, notes prefixed, and each facet's summary in by_facet.
    print(result) summarizes it in words.

    Parameters
    ----------
    data : DataFrame of providers, or of cases (stay- or survey-level rows) to be summed
        per unit. Without data=, y, n, unit, label are sequences and hover a dict.
    y, n : columns (or sequences): the numerator and denominator.
    measure : "oe" (observed / expected: risk-adjusted mortality, readmission, length
        of stay), "proportion" (events / cases) or "rate" (events / exposure).
    unit : provider identifier column; rows are providers when omitted.
    label : display name column (the first value per unit); hover : extra tooltip columns.
    facets : a column, or list of columns: one funnel per value, each with its own
        centre line, dispersion and Benjamini–Hochberg step.
    exclude : a boolean column, or a list of unit ids, left out of the centre line,
        dispersion and testing (still drawn, faded).
    center : a fixed centre line. On measure="oe", center=1.0 benchmarks against the
        risk model itself; the default pooled ΣO/ΣE benchmarks against peers.
    overdispersion : judge each provider against the estimated spread between providers
        (Spiegelhalter's additive τ²) as well as chance. Default True.
    within_dispersion : how much more variable each count is than its model because
        units clump inside cases (patient-days; the items of one survey). 1.0 (default)
        means independent units. "estimate" computes it from case-level rows; a number
        supplies it (e.g. from SQL: SUM(POWER(los - exp, 2) / exp) / (COUNT(*) - COUNT(
        DISTINCT provider))); a column name gives one φᵢ per provider (case-mix
        weighted, methods §4.12). The model then sees y/φ out of n/φ. An estimate below
        1 (binary outcomes, whose variance Σp(1 − p) is below E) is kept and noted.
    tau_method : how τ is estimated (methods §4.16, §4.17). "spiegelhalter" (default):
        Spiegelhalter's 10%-winsorized moment estimator as published, as CQC, NHS and
        FunnelPlotR use it on the natural scale. "winsorized": the same with its Gaussian
        consistency factor (eq. 9), calibrated to the stated false-flag rate at large K
        but less sensitive. "ml": maximum likelihood of the chart's own model, with
        tau_ci; not robust to outliers. "cqc", "shmi": FunnelPlotR's square-root (arcsine
        for proportions) winsorized and log truncated methods, drawn as normal contours
        on that scale, to reproduce CQC and NHS SHMI funnels.
    tau : a τ fixed in advance instead of estimated (a number, or a dict per facet).
        This period's estimate is still reported as tau_estimated.
    cases, sum_sq : per-provider SQL totals (k, and Σ y²/n over the provider's cases) so
        within_dispersion="estimate" needs no case rows. Pass both or neither.
    max_case_y, max_case_n : per-provider SQL worst case toward worse= (MAX_BY), for
        p_value_drop1 and flag_survives_drop1.
    fdr_min_denominator : a volume floor for the false discovery rate step only, on the
        denominator the model sees (expected events, cases or exposure, ÷ φ). Providers
        below it keep their p_value but get no q_value (independent filtering, §4.11).
    worse : "higher" or "lower" when only one direction is bad: flags only that side and
        makes p-values one-sided.
    signal : "limits" (default): outlier beyond the outer contour, alert beyond the
        inner one, so the flags match the drawn lines. "fdr": outlier when
        q < fdr_levels[0], alert when q < fdr_levels[1].
    limits : (outer, inner) contour coverage, default (0.998, 0.95).
    fdr_levels : (outlier, alert) false discovery rates for signal="fdr".
    multiply : scale the plotted y, e.g. 1000 for a rate per 1,000.

    Display options (title, axis labels, styles, x_log, ...) are arguments of
    result.plot(); result.limits() gives the contours at any denominators.
    """
    if removed:
        reject_removed("funnel", removed, _RENAMED, _DISPLAY, other=("chart", "method", "freeze", "part"))
    st = _settings(
        measure=measure, overdispersion=overdispersion, tau_method=tau_method, tau=tau,
        worse=worse, signal=signal, limits=limits, fdr_levels=fdr_levels,
        fdr_min=fdr_min_denominator, multiply=multiply, center=center, facets=facets,
    )
    if (cases is None) != (sum_sq is None):
        raise ValueError(
            "cases= and sum_sq= go together: cases is each provider's number of cases and "
            "sum_sq its SUM(POWER(y, 2) / n) over those cases. Pass both, or neither."
        )
    if (max_case_y is None) != (max_case_n is None):
        raise ValueError(
            "max_case_y= and max_case_n= go together: the numerator and denominator of "
            "each provider's most extreme case. Pass both, or neither."
        )
    phi_column = (
        within_dispersion
        if isinstance(within_dispersion, str) and within_dispersion != "estimate" else None
    )
    if not isinstance(within_dispersion, str):
        check_number("within_dispersion", within_dispersion, 0.0, strict=True)
    extra = {_CASES: cases, _SS: sum_sq, _MAXY: max_case_y, _MAXN: max_case_n,
             _PHI: phi_column}
    frame, hover_names = _normalize(data, y, n, unit, label, hover, st.facets, exclude, extra)
    return _funnel(frame, replace(st, hover=tuple(hover_names)), within_dispersion,
                   aggregated=cases is not None, phi_column=phi_column,
                   names={"y": y, "n": n})


@dataclass(frozen=True)
class _Settings:
    measure: str
    overdispersion: bool
    tau_method: str
    tau_fixed: Any                 # τ² fixed in advance: a number, a dict per facet, or None
    tau: Any                       # tau= as the caller passed it, for the summary
    worse: str | None
    signal: str
    limits: tuple[float, float]
    fdr_levels: tuple[float, float]
    fdr_min: float | None
    multiply: float
    center: float | None
    facets: tuple[str, ...]
    hover: tuple[str, ...] = ()
    limit_method: str = "exact"

    @property
    def family(self) -> str:
        return "binomial" if self.measure == "proportion" else "poisson"

    @property
    def side(self) -> str:
        return _SIDES[self.worse]


def _settings(*, measure, overdispersion, tau_method, tau, worse, signal, limits,
              fdr_levels, fdr_min, multiply, center, facets, limit_method="exact") -> _Settings:
    check_choice("measure", measure, MEASURES)
    check_choice("worse", worse, WORSE)
    check_choice("signal", signal, SIGNALS)
    check_choice("tau_method", tau_method, TAU_METHODS)
    check_choice("limit_method", limit_method, _LIMIT_METHODS)
    if tau_method == "shmi" and measure == "proportion":
        transform_scale("shmi", "binomial")  # raises with the fix
    check_number("multiply", multiply, 0.0, strict=True)
    if fdr_min is not None:
        check_number("fdr_min_denominator", fdr_min)
    if center is not None:
        check_number("center", center, 0.0, strict=True)
        if measure == "proportion" and not center < 1.0:
            raise ValueError(f"center= on a proportion lies strictly between 0 and 1, got {center!r}.")
    check_facet_names(split_facets(facets), _COLUMNS, "funnel")
    return _Settings(
        measure=measure, overdispersion=bool(overdispersion), tau_method=tau_method,
        tau_fixed=_tau_fixed(tau, facets, overdispersion), tau=tau, worse=worse,
        signal=signal, limits=check_levels("limits", limits, outer_wider=True),
        fdr_levels=check_levels("fdr_levels", fdr_levels, outer_wider=False),
        fdr_min=fdr_min, multiply=float(multiply),
        center=None if center is None else float(center),
        facets=tuple(split_facets(facets)), limit_method=limit_method,
    )


def _tau_fixed(tau: Any, facets: Any, overdispersion: bool) -> Any:
    """tau= as τ² (a number, or a dict of τ² per facet), validated."""
    if tau is None:
        return None
    if not overdispersion:
        raise ValueError(
            "tau= needs overdispersion=True: it is the spread the adjusted chart judges "
            "providers against, and the unadjusted chart has none."
        )
    if isinstance(tau, dict):
        if not split_facets(facets):
            raise ValueError("tau= as a dict (one value per facet) needs facets=.")
        return {fv: _tau_number(v, f"[{fv!r}]") ** 2 for fv, v in tau.items()}
    return _tau_number(tau, "") ** 2


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------

def _funnel(frame, st: _Settings, within_dispersion, aggregated: bool, phi_column, names):
    """Every facet's funnel, and the result that holds them."""
    if aggregated:
        _check_aggregated(frame, st.facets)
    keys = list(st.facets)
    if keys:
        groups = [((k if isinstance(k, tuple) else (k,)), rows)
                  for k, rows in frame.groupby(keys, sort=False, dropna=False)]
    else:
        groups = [((), frame)]
    tables, by_facet, models = [], {}, {}
    for key, rows in groups:
        name = " / ".join(str(v) for v in key) if key else None
        within = _within(rows, st, within_dispersion, aggregated, phi_column)
        tau_fixed = _facet_value(st.tau_fixed, key, name)
        table, summary, model = _one_funnel(rows, st, within, tau_fixed, aggregated)
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
    }
    if not keys:
        summary = {**settings, **by_facet[None]}
    else:
        totals = {k: sum(f[k] for f in by_facet.values())
                  for k in ("n_providers", "n_tested", "n_outlier", "n_alert", "n_filtered",
                            "n_fragile")}
        notes = [f"{fv}: {note}" for fv, f in by_facet.items() for note in f["notes"]]
        summary = {**settings, **totals, "by_facet": by_facet, "notes": notes}
    meta = {
        "facets": keys, "hover": list(st.hover), "worse": st.worse, "side": st.side,
        "signal": st.signal, "limits": st.limits, "fdr_levels": st.fdr_levels,
        "measure": st.measure, "y_name": names["y"] if isinstance(names["y"], str) else None,
        "n_name": names["n"] if isinstance(names["n"], str) else None,
        "phi_column": phi_column, "multiply": st.multiply,
    }
    return FunnelResult(data=data, summary=summary, _models=models, _meta=meta)


@dataclass(frozen=True)
class _Within:
    phi: float                      # the scalar φ the model divides by (1 under a column)
    phi_units: dict | None          # {unit: φᵢ} under a within_dispersion column
    source: str                     # default | supplied | estimated | column
    check: tuple | None             # the case-level clustering check (φ̂, p), or None


def _within(rows, st: _Settings, within_dispersion, aggregated, phi_column) -> _Within:
    """Within-case dispersion for one facet; excluded providers never enter the estimate."""
    kept = rows[~rows[_EXCL]] if _EXCL in rows else rows
    if phi_column is not None:
        return _Within(1.0, _unit_phi(rows, phi_column), "column", None)
    if within_dispersion == "estimate":
        return _Within(_estimate_within(kept, st.measure, aggregated), None, "estimated", None)
    phi = float(within_dispersion)
    if phi != 1.0:
        return _Within(phi, None, "supplied", None)
    return _Within(1.0, None, "default", _within_check(kept, st.measure, aggregated))


def _facet_value(value, key: tuple, name: str | None):
    """A per-facet setting (tau=): the facet's value, keyed by value, tuple or label."""
    if not isinstance(value, dict):
        return value
    for candidate in (key[0] if len(key) == 1 else None, key, name):
        if candidate in value:
            return value[candidate]
    raise ValueError(f"tau= as a dict needs one value per facet; missing {name!r}.")


def _one_funnel(rows, st: _Settings, within: _Within, tau_fixed, aggregated: bool):
    """One facet: (public table, summary, model for limits())."""
    family, _binomial = st.family, st.measure == "proportion"
    units = rows.groupby(_UNIT, sort=False)
    agg = pd.DataFrame({_Y: units[_Y].sum(), _N: units[_N].sum()})
    for col in (_LABEL, *st.hover, _MAXY, _MAXN):
        if col in rows:
            agg[col] = units[col].first()
    agg[_EXCL] = units[_EXCL].any() if _EXCL in rows else False
    phi_u = (np.array([within.phi_units[u] for u in agg.index], dtype=float)
             if within.phi_units is not None else np.full(len(agg), within.phi))
    num, den = agg[_Y].to_numpy(dtype=float), agg[_N].to_numpy(dtype=float)
    n_model = den if within.phi_units is None and within.phi == 1.0 else den / phi_u
    order = np.argsort(n_model, kind="stable")
    agg, num, den, n_model, phi_u = agg.iloc[order], num[order], den[order], n_model[order], phi_u[order]
    excluded = agg[_EXCL].to_numpy(dtype=bool)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(den > 0, num / den, np.nan)
    _check_counts(st.measure, num, den)
    mask = ~excluded
    tested = np.where(excluded, np.nan, ratio)

    # The centre line and the spread between providers.
    cl = st.center if st.center is not None else _pooled(ratio, n_model, mask)
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

    # Contours, tests and tiers.
    lim = funnel_contours(family, cl, n_model, used, st.limits, st.limit_method, scale)
    p, p_method, model_name = funnel_p_values(
        cl, tested, n_model, used, family, st.side, scale, byar=st.limit_method == "byar",
    )
    filtered = (np.zeros(len(p), dtype=bool) if st.fdr_min is None
                else np.isfinite(p) & (n_model < st.fdr_min))
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
    _add_shrinkage(table, st, cl, natural_tau2(scale, cl, used), n_model)
    fragile = _add_robustness(table, rows, agg, st, cl, used, scale, n_model, phi_u, aggregated)

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
    }
    summary["expected_false_flags"] = _expected_false_flags(st, summary)
    notes: list[str] = []
    summary.update({"dispersion_shape": None, "within_dispersion_hint": None,
                    "within_dispersion_hint_source": None, "underpowered": None,
                    "n_underpowered": None, "min_detectable_median": None})
    summary.update(_shape(cl, ratio, n_model, mask, family, within, st.measure, notes))
    summary.update(_power(st.measure, det, cl, excluded, notes))
    _notes(summary, st, notes)
    summary["notes"] = notes
    model = {
        "family": family, "cl": float(cl), "tau2": used, "scale": scale,
        "levels": st.limits, "limit_method": st.limit_method, "multiply": m,
        "phi": None if within.phi_units is not None else within.phi,
        "axis": table["effective_denominator" if within.phi_units is not None
                      else "denominator"].to_numpy(dtype=float),
    }
    return table, summary, model


def _pooled(ratio, n_model, mask) -> float:
    """θ₀ = Σyᵢnᵢ/Σnᵢ over the providers tested (ΣO/ΣE on O/E)."""
    y_base = np.where(mask, ratio, np.nan)
    n_base = np.where(mask, n_model, np.nan)
    total_n = float(np.nansum(n_base))
    return float(np.nansum(y_base * n_base)) / total_n if total_n else math.nan


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


def _expected_false_flags(st: _Settings, s: dict) -> dict[str, float]:
    """
    How many of the flags chance alone would explain. Under "limits": K·α per tier, the
    count a chart of K average providers would put there. Under "fdr": the false
    discovery bound, at most q₀ of the outliers and q₁ of outliers and alerts together.
    """
    if st.signal == "limits":
        outer, inner = signal_thresholds(st.side, st.limits)
        k = s["n_tested"]
        return {"outlier": round(k * outer, 2), "alert": round(k * (inner - outer), 2)}
    q0, q1 = st.fdr_levels
    return {"outlier": round(q0 * s["n_outlier"], 2),
            "outlier_or_alert": round(q1 * (s["n_outlier"] + s["n_alert"]), 2)}


# The case-level clustering check (within_check = (φ̂, p) from case rows) warns when the
# rows are clearly more variable than independent cases. The floor matters more than the
# test, which is very powerful on N − K degrees of freedom: at φ = 1.25 the 99.8% limits
# are √1.25 too narrow (docs/methods.md §4.13, §5).
_ROWS_MIN_PHI = 1.25
_ROWS_MAX_P = 0.001


def _shape(cl, ratio, n_model, mask, family, within: _Within, measure, notes) -> dict:
    """dispersion_shape, its φ hint, and the clustered-counts warning (methods §4.12)."""
    out = dispersion_shape(cl, ratio, n_model, mask, family)
    if "within_dispersion_hint" in out:
        out["within_dispersion_hint_source"] = "totals"
    check = within.check
    if check is not None and check[0] >= _ROWS_MIN_PHI and check[1] < _ROWS_MAX_P:
        shape = out.get("dispersion_shape")
        out["dispersion_shape"] = "both" if shape in ("between", "both") else "within"
        out["within_dispersion_hint"] = round(float(check[0]), 2)
        out["within_dispersion_hint_source"] = "rows"
    if out.get("dispersion_shape") in ("within", "both") and within.source == "default":
        hint = out["within_dispersion_hint"]
        if measure == "proportion":
            example = "the questions of one survey, which one patient answers alike"
            fix = ("Pass one row per case (per survey: y = items meeting the measure, n = "
                   "items answered) with within_dispersion='estimate', or a known "
                   f"within_dispersion= (the spread here suggests about {hint:.1f}).")
        else:
            example = "patient-days, where one stay adds many days"
            fix = ("Pass stay-level rows (one per case) with within_dispersion='estimate', "
                   f"or a known within_dispersion= (the spread here suggests about {hint:.1f}).")
        note = (f"Counts look clustered within providers (e.g. {example}): the spread is "
                f"about {hint:.1f} times what the count model allows at every volume, so "
                f"small providers are over-flagged and p- and q-values are too small. {fix}")
        notes.append(note)
        warnings.warn(note, UserWarning, stacklevel=4)
    if within.source == "estimated" and within.phi < 1.0:
        notes.append(
            f"within_dispersion was estimated at {within.phi:.2f}, below 1: single cases vary "
            f"less than a Poisson count, as binary outcomes do (the variance, the sum of "
            f"p(1 - p), is below E). The limits use it, which narrows them; pass within_dispersion=1 to keep "
            f"the Poisson model."
        )
    return out


def _power(measure: str, det, cl, excluded, notes) -> dict:
    """
    Whether the typical provider could detect a doubling (methods §4.8). On O/E the test
    is min_detectable > 2; on a proportion or rate, min_detectable / cl > 2, with points
    that cannot flag at all counted as underpowered.
    """
    counted = det[~excluded]
    if measure == "oe":
        finite = counted[np.isfinite(counted)]
        if len(finite) == 0:
            return {}
        median = float(np.median(finite))
        n_under = int(np.sum(finite > UNDERPOWERED_RATIO))
        out = {"min_detectable_median": median, "n_underpowered": n_under,
               "underpowered": median > UNDERPOWERED_RATIO}
        if out["underpowered"]:
            notes.append(
                f"{n_under} of {len(finite)} points have too few expected events to detect "
                f"even a doubling of risk (smallest detectable O/E, median: {median:.1f}). "
                f"Absence of a signal is not evidence of acceptable performance; aggregate "
                f"more time periods or compare at a higher level before drawing conclusions."
            )
        return out
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = counted / (cl if cl > 0 else np.nan)
    ratio = ratio[~np.isnan(ratio)]
    if len(ratio) == 0:
        return {}
    median = float(np.median(ratio))
    n_under = int(np.sum(ratio > UNDERPOWERED_RATIO))
    out = {"min_detectable_median": median if math.isfinite(median) else math.nan,
           "n_underpowered": n_under, "underpowered": median > UNDERPOWERED_RATIO}
    if out["underpowered"]:
        noun = "proportion" if measure == "proportion" else "rate"
        reach = (f"median: {median:.1f}× the center line" if math.isfinite(median)
                 else "median: none, most points cannot flag at all")
        notes.append(
            f"{n_under} of {len(ratio)} points have too few cases to detect even a "
            f"doubling of the center-line {noun} (smallest detectable {noun}, {reach}). "
            f"Absence of a signal is not evidence of acceptable performance; aggregate "
            f"more time periods or compare at a higher level before drawing conclusions."
        )
    return out


_SPREAD = {"oe": ("the risk model and chance", "O/E"), "proportion": ("chance", "proportions"),
           "rate": ("chance", "rates")}


def _notes(s: dict, st: _Settings, notes: list[str]) -> None:
    """The reader-facing sentences, in order of how much they change the reading."""
    if not st.overdispersion and s["tau_estimated"] > 0:
        basis, quantity = _SPREAD[st.measure]
        notes.append(
            f"Providers vary more than {basis} can explain: the estimated spread of true "
            f"{quantity} between them is tau = {_two_sig(s['tau_estimated'])}. Some signals "
            f"here may reflect that spread (unmeasured case mix, data differences, or real "
            f"variation in practice) rather than an individually unusual provider. Compare "
            f"with overdispersion=True, which judges each provider against that spread, and "
            f"look for its cause: an adjustment is a temporary measure, not a fix."
        )
    if s["n_fragile"]:
        note = (f"{s['n_fragile']} flagged provider(s) stop flagging when their single most "
                f"extreme case is removed (fragility = 1): review that case before acting.")
        if st.measure != "proportion" and s["within_dispersion"] == 1.0:
            note += (" On event counts every event is one patient, so at low volume this is "
                     "expected and is not by itself a data problem.")
        notes.append(note)
    k = s["n_tested"]
    if st.overdispersion and s["tau_source"] == "estimated" and 0 < k < 30:
        notes.append(
            f"With {k} providers the spread between them (tau = {s['tau']:.3g}) is "
            f"imprecise. Consider a pre-specified tau= estimated from earlier periods."
        )
    est, fixed = s["tau_estimated"], s["tau"]
    if (st.overdispersion and s["tau_source"] == "pre-specified" and fixed
            and not (fixed / 1.5 <= est <= fixed * 1.5)):
        notes.append(
            f"The pre-specified tau = {fixed:.3g} differs from this period's estimate, "
            f"{est:.3g}, by more than 1.5-fold: the spread between providers may have "
            f"changed since tau was set. Review it before relying on these limits."
        )
    if s["n_filtered"]:
        notes.append(
            f"{s['n_filtered']} provider(s) below fdr_min_denominator = {st.fdr_min:g} were "
            f"left out of the false discovery rate step: they keep a p-value but have no "
            f"q-value."
        )


def _two_sig(x: float) -> str:
    """x to two significant figures in fixed notation."""
    if not (x > 0) or not math.isfinite(x):
        return f"{x:.2f}"
    return f"{x:.{max(0, 1 - math.floor(math.log10(x)))}f}"


# ---------------------------------------------------------------------------
# Shrinkage and robustness
# ---------------------------------------------------------------------------

def _add_shrinkage(table, st: _Settings, cl, tau2, n_model) -> None:
    """
    raw_excess, reliability, eb_rate, eb_excess, prob_worse (methods §4.14). The weight is
    the exact conjugate posterior mean of the chart's own mixture model: Poisson–gamma,
    B = τ²/(τ² + θ₀/n); beta-binomial, B = n/(n + s), s = θ₀(1 − θ₀)/τ² − 1; both on the
    model's n (÷ φ). B = 0 when τ² = 0: no measured spread, nothing to shrink toward.
    On a transformed-scale chart (cqc, shmi) τ² is carried back by the delta method.
    """
    sign = -1.0 if st.worse == "lower" else 1.0
    binomial = st.measure == "proportion"
    num = table["numerator"].to_numpy(dtype=float)
    den = table["denominator"].to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        y = num / den
        params = beta_params(cl, tau2) if binomial and tau2 > 0 else None
        if not (tau2 > 0):
            b = np.zeros(len(table))
        elif params is not None:
            b = n_model / (n_model + params[0] + params[1])
        else:
            b = tau2 / (tau2 + (cl * (1.0 - cl) if binomial else cl) / n_model)
        eb = b * y + (1.0 - b) * cl
    table["raw_excess"] = sign * (num - cl * den)
    table["reliability"] = b
    table["eb_rate"] = eb * st.multiply
    table["eb_excess"] = sign * (eb - cl) * den
    table["prob_worse"] = _prob_worse(y * n_model, n_model, cl, tau2, binomial,
                                      st.worse == "lower", params)


def _add_robustness(table, rows, agg, st: _Settings, cl, tau2, scale, n_model, phi_u,
                    aggregated) -> int:
    """
    p_value_drop1, flag_survives_drop1, fragility (methods §4.15); returns how many flagged
    providers have fragility 1. θ₀, τ² and φ stay at their full-data values; only the
    provider's own count and denominator move, so each recomputed p-value is the chart's.
    """
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


# ---------------------------------------------------------------------------
# Sensitivity to the model
# ---------------------------------------------------------------------------

def funnel_sensitivity(
    data: pd.DataFrame | None = None,
    *,
    tau_methods: tuple[str, ...] = ("spiegelhalter", "winsorized", "ml"),
    unadjusted: bool = True,
    **kwargs: Any,
) -> pd.DataFrame:
    """
    Does a provider's flag depend on how the spread between providers was modelled?

    Runs funnel(data, **kwargs) once per tau_method (and once with overdispersion=False
    when unadjusted=True) and returns one row per provider: unit, label (if given), y,
    denominator, the facet columns, one signal_<method> column per run, and consistent,
    True when every run gives the same tier. A provider flagged under one model and not
    another is a judgement call to make explicitly, not a finding (methods §4.16).
    """
    if "tau_method" in kwargs or "overdispersion" in kwargs:
        raise ValueError("funnel_sensitivity() sets tau_method= and overdispersion= itself; "
                         "choose them with tau_methods= and unadjusted=.")
    runs = {f"signal_{m}": funnel(data, tau_method=m, **kwargs) for m in tau_methods}
    if unadjusted:
        runs["signal_unadjusted"] = funnel(data, overdispersion=False, **kwargs)
    first = next(iter(runs.values())).data
    facets = split_facets(kwargs.get("facets"))
    keep = [c for c in (*facets, "unit", "label", "y", "denominator") if c in first]
    out = first[keep].copy()
    key = [*facets, "unit"]
    for name, result in runs.items():
        tiers = result.data.set_index(key)["signal"]
        out[name] = tiers.loc[pd.MultiIndex.from_frame(out[key]) if len(key) > 1
                              else out["unit"]].to_numpy()
    cols = list(runs)
    out["consistent"] = out[cols].nunique(axis=1) == 1
    return out


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def _tau_number(value: Any, where: str) -> float:
    ok = (isinstance(value, (int, float)) and not isinstance(value, bool)
          and math.isfinite(value) and value >= 0)
    if not ok:
        raise ValueError(f"tau={where} must be a number >= 0, got {value!r}.")
    return float(value)


def _normalize(data, y, n, unit, label, hover, facets, exclude, extra=None):
    """
    One DataFrame with working columns for unit, y, n, label and exclude, whatever
    form the caller used. Rows sharing a unit (and facet) are summed per provider.
    extra maps working column → caller column name (cases=, sum_sq=, max_case_y=,
    max_case_n=, a within_dispersion column), each numeric and requiring data=.
    """
    extra = {k: v for k, v in (extra or {}).items() if v is not None}
    if extra and data is None:
        raise ValueError(
            "cases=, sum_sq=, max_case_y=, max_case_n= and a within_dispersion column "
            "name columns of data=; pass data= as a DataFrame."
        )
    if data is None:
        if isinstance(y, str) or isinstance(n, str):
            raise ValueError("Without data=, y= and n= must be sequences, not column names.")
        frame = pd.DataFrame({_Y: np.asarray(y, dtype=float), _N: np.asarray(n, dtype=float)})
        k = len(frame)
        for col, values in ((_UNIT, unit), (_LABEL, label)):
            if values is not None:
                if len(values) != k:
                    raise ValueError(f"unit=/label= must have one value per y, got {len(values)}.")
                frame[col] = list(values)
        if facets:
            raise ValueError("facets= needs data= (it names columns).")
        hover_names: list[str] = []
        if hover is not None:
            if not isinstance(hover, dict):
                raise ValueError("Without data=, hover= must be a dict of per-point sequences.")
            for name, values in hover.items():
                frame[str(name)] = list(values)
                hover_names.append(str(name))
    else:
        if not isinstance(data, pd.DataFrame):
            raise TypeError("data= must be a pandas DataFrame.")
        for name, col in (("y", y), ("n", n), ("unit", unit), ("label", label),
                          *(("facets", f) for f in facets)):
            if col is not None and (not isinstance(col, str) or col not in data.columns):
                raise ValueError(f"{name}= must name a column of data, got {col!r}.")
        frame = pd.DataFrame({_Y: data[y].to_numpy(dtype=float), _N: data[n].to_numpy(dtype=float)},
                             index=data.index)
        if unit is not None:
            frame[_UNIT] = data[unit].to_numpy()
        if label is not None:
            frame[_LABEL] = data[label].to_numpy()
        for col in facets:
            frame[col] = data[col].to_numpy()
        hover_names = [hover] if isinstance(hover, str) else list(hover or [])
        for name in hover_names:
            if name not in data.columns:
                raise ValueError(f"hover= column {name!r} not found in data.")
            if name in _COLUMNS:
                raise ValueError(f"hover= column {name!r} collides with a column funnel() writes.")
            frame[name] = data[name].to_numpy()
        for key, col in extra.items():
            if not isinstance(col, str) or col not in data.columns:
                what = "within_dispersion" if key == _PHI else {
                    _CASES: "cases", _SS: "sum_sq", _MAXY: "max_case_y", _MAXN: "max_case_n",
                }[key]
                raise ValueError(
                    f"{what}= must name a column of data, got {col!r}."
                    + (" A number, or 'estimate', is also accepted." if key == _PHI else "")
                )
            frame[key] = pd.to_numeric(data[col], errors="coerce").to_numpy(dtype=float)
        frame = frame.reset_index(drop=True)

    if _UNIT not in frame.columns:
        frame[_UNIT] = np.arange(1, len(frame) + 1)

    if exclude is not None:
        if isinstance(exclude, str):
            if data is None or exclude not in data.columns:
                raise ValueError("exclude= as a string must name a boolean column of data.")
            frame[_EXCL] = data[exclude].fillna(False).to_numpy(dtype=bool)
        else:
            ids = set(exclude)
            unknown = ids - set(frame[_UNIT])
            if unknown:
                raise ValueError(f"exclude= lists unit(s) not in the data: {sorted(map(str, unknown))}.")
            frame[_EXCL] = frame[_UNIT].isin(ids).to_numpy()
    return frame, hover_names


def _row_phi(rows: pd.DataFrame, binomial: bool) -> tuple[float, int] | None:
    """
    (φ̂, N − K) from case-level rows, around each provider's own rate θ̂ⱼ = Σy/Σn, so
    real differences between providers stay out of φ̂; those are τ²'s job.

    Counts (oe, rate): φ̂ = Σⱼ Σᵢ (yᵢⱼ − θ̂ⱼnᵢⱼ)² / (θ̂ⱼnᵢⱼ) / (N − K).

    Proportions: φ̂ = Σⱼ Σᵢ (yᵢⱼ − θ̂ⱼnᵢⱼ)² / nᵢⱼ / [θ̄(1 − θ̄)(N − K)], the design
    effect of items clustered in cases, with the pooled θ̄ in the variance. Each
    provider's own θ̂ⱼ(1 − θ̂ⱼ) there would drop every provider at 0% or 100%, common
    at a few surveys each, and would read N/(N − K) rather than 1 on yes/no rows.

    None when no unit has a second row.
    """
    rows = rows[(rows[_N] > 0) & np.isfinite(rows[_Y]) & np.isfinite(rows[_N])]
    theta = rows.groupby(_UNIT)[_Y].transform("sum") / rows.groupby(_UNIT)[_N].transform("sum")
    if not binomial:
        usable = theta > 0
        rows, theta = rows[usable], theta[usable]
    df = len(rows) - rows[_UNIT].nunique()
    if df < 1:
        return None
    if not binomial:
        mu = theta * rows[_N]
        return float(np.sum((rows[_Y] - mu) ** 2 / mu) / df), df
    pooled = float(rows[_Y].sum() / rows[_N].sum())
    if not (0.0 < pooled < 1.0):
        return 1.0, df
    resid = (rows[_Y] - theta * rows[_N]) ** 2 / rows[_N]
    return float(np.sum(resid) / (pooled * (1.0 - pooled) * df)), df


def _agg_phi(rows: pd.DataFrame, binomial: bool) -> tuple[float, int] | None:
    """
    _row_phi from one row per provider aggregated in SQL (cases=, sum_sq=). With
    θ̂ⱼ = Yⱼ/Nⱼ the Pearson sum over a provider's cases expands to its sufficient
    statistics, so the stays never need to leave the database:

      counts:      Σᵢ (yᵢ − θ̂nᵢ)²/(θ̂nᵢ) = Σᵢ yᵢ²/nᵢ / θ̂ − Y
      proportions: Σᵢ (yᵢ − θ̂nᵢ)²/nᵢ   = Σᵢ yᵢ²/nᵢ − θ̂·Y

    on Σkⱼ − K degrees of freedom, so it equals the case-row estimate to rounding
    (methods §4.12). None when no provider has a second case.
    """
    rows = rows[(rows[_N] > 0) & np.isfinite(rows[_Y]) & np.isfinite(rows[_N])]
    theta = rows[_Y] / rows[_N]
    if not binomial:
        usable = theta > 0
        rows, theta = rows[usable], theta[usable]
    df = int(round(float(rows[_CASES].sum()))) - len(rows)
    if df < 1:
        return None
    if not binomial:
        return float(np.sum(rows[_SS] / theta - rows[_Y]) / df), df
    pooled = float(rows[_Y].sum() / rows[_N].sum())
    if not (0.0 < pooled < 1.0):
        return 1.0, df
    return float(np.sum(rows[_SS] - theta * rows[_Y]) / (pooled * (1.0 - pooled) * df)), df


def _one_item_per_case(rows: pd.DataFrame, aggregated: bool) -> bool:
    """Every case is a single yes/no item: n = 1 per row, or cases = n per provider."""
    if not len(rows):
        return False
    if aggregated:
        return bool(np.all(rows[_CASES] == rows[_N]))
    return bool(np.all(rows[_N] == 1))


def _check_aggregated(frame: pd.DataFrame, facets) -> None:
    """cases=/sum_sq= rows must be providers: one row each, k ≥ 1, Σy²/n ≥ 0."""
    if frame.groupby([*facets, _UNIT]).size().max() > 1:
        raise ValueError(
            "cases= and sum_sq= describe one provider per row, but some unit appears in "
            "several rows. Aggregate to one row per provider (per facet) in SQL, or drop "
            "cases=/sum_sq= and pass the case-level rows instead."
        )
    k = frame[_CASES].to_numpy(dtype=float)
    if not (np.all(np.isfinite(k)) and np.all(k >= 1)):
        raise ValueError("cases= must be a whole number of cases >= 1 on every row.")
    ss = frame[_SS].to_numpy(dtype=float)
    if not (np.all(np.isfinite(ss)) and np.all(ss >= 0)):
        raise ValueError(
            "sum_sq= must be finite and >= 0: SUM(POWER(y, 2) / n) over each provider's cases."
        )


def _unit_phi(frame: pd.DataFrame, column: str) -> dict:
    """{unit: φᵢ} from a within_dispersion column (one facet's rows), validated."""
    phi = frame[_PHI].to_numpy(dtype=float)
    if not (np.all(np.isfinite(phi)) and np.all(phi > 0)):
        raise ValueError(
            f"within_dispersion column {column!r} must be a positive, finite number on every "
            "row (each provider's phi_i; 1 means independent counts)."
        )
    if (frame.groupby(_UNIT)[_PHI].nunique() > 1).any():
        raise ValueError(
            f"within_dispersion column {column!r} varies within a provider. It is one phi_i "
            "per provider (SUM(phi_g * e) / SUM(e) over its cases); repeat that value on "
            "each row."
        )
    first = frame.groupby(_UNIT, sort=False)[_PHI].first()
    return {u: float(v) for u, v in first.items()}


def _estimate_within(rows: pd.DataFrame, measure: str, aggregated: bool = False) -> float:
    """
    within_dispersion="estimate" for one facet: φ̂ of _row_phi (or _agg_phi from
    cases=/sum_sq=), from the providers that are not excluded.
    """
    binomial = measure == "proportion"
    if binomial and _one_item_per_case(rows, aggregated):
        raise ValueError(
            "within_dispersion='estimate' found one item per row (every n is 1). A "
            "row that is a single yes/no cannot show clustering, so there is nothing "
            "to estimate. If several rows belong to one case (the questions of one "
            "survey), sum them to one row per case: y = items meeting the measure, "
            "n = items answered. If each row really is one independent case, leave "
            "within_dispersion at 1."
        )
    found = _agg_phi(rows, binomial) if aggregated else _row_phi(rows, binomial)
    if found is None and aggregated:
        raise ValueError(
            "within_dispersion='estimate' found no provider with more than one case "
            "(cases= is 1 everywhere), so it cannot measure how much single cases "
            "vary. Pass a known within_dispersion= number instead."
        )
    if found is None:
        raise ValueError(
            "within_dispersion='estimate' needs several rows per unit: one per case "
            "(stay-level data, or one row per survey), so it can measure how much "
            "single cases vary. Every unit here has one row. Pass case-level rows, "
            "or a known within_dispersion= number instead."
        )
    return found[0]


# Fewer residual degrees of freedom than this and the rows say little about clumping.
_ROWS_MIN_DF = 30


def _within_check(rows: pd.DataFrame, measure: str, aggregated: bool = False):
    """
    (φ̂, p) from one facet's case-level rows for the clustering warning, with p the
    Pearson χ² test of φ = 1 on N − K degrees of freedom (Wilson–Hilferty); None where the
    rows are providers, carry fewer than _ROWS_MIN_DF residual degrees of freedom, or are
    single yes/no items, which cannot show clustering.
    """
    binomial = measure == "proportion"
    if binomial and _one_item_per_case(rows, aggregated):
        return None
    found = _agg_phi(rows, binomial) if aggregated else _row_phi(rows, binomial)
    if found is None or found[1] < _ROWS_MIN_DF:
        return None
    phi, df = found
    h = 2.0 / (9.0 * df)
    z = ((max(phi, 0.0)) ** (1.0 / 3.0) - (1.0 - h)) / math.sqrt(h)
    return phi, 0.5 * math.erfc(z / math.sqrt(2.0))


def _prob_worse(o_eff, n_eff, cl, tau2, binomial, lower, params) -> np.ndarray:
    """
    P(true value worse than cl | data) under the chart's posterior (methods §4.16):
    Gamma(a + O, rate b + E) with a = cl²/τ², b = cl/τ² for counts, Beta(α + Y,
    β + n − Y) for proportions, on effective counts. NaN when τ = 0 or no beta has the
    spread.
    """
    out = np.full(len(o_eff), np.nan)
    if not (tau2 > 0) or (binomial and params is None):
        return out
    for i, (o, n) in enumerate(zip(o_eff, n_eff)):
        if not (np.isfinite(o) and np.isfinite(n) and n > 0):
            continue
        if binomial:
            below, above = beta_tails(cl, params[0] + o, params[1] + n - o)
        else:
            below, above = gamma_tails(cl * cl / tau2 + o, (cl / tau2 + n) * cl)
        out[i] = below if lower else above
    return out
