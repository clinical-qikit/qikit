"""
funnel.py — funnel(): compare providers on one measure, and flag the unusual ones.

    from qikit import funnel
    r = funnel(df, y="deaths", n="expected", measure="oe", unit="surgeon", worse="higher")
    r.data[r.data.signal != "none"]      # who flagged, and how strongly
    r.summary                            # model, expected chance flags, notes
    r.plot()

The pipeline, per facet, top to bottom: sum each provider's rows; set the center line
θ₀; estimate the spread between providers τ² (core/dispersion.py); draw the contours at
every provider's denominator (core/contours.py); test each provider against them
(core/pvalues.py); add what each provider could have shown (core/power.py), shrunk
estimates and single-case robustness. docs/methods.md is the canonical account of each
method and every departure from Spiegelhalter (2005).
"""

from __future__ import annotations

import inspect
from dataclasses import replace
from typing import Any, Literal

import pandas as pd

# BENCHMARKS, COMPARE_TO, MEASURES and SIGNALS are re-exported: the choices are part of
# the documented surface (tests/test_docs.py, tests/test_agent_surface.py).
from ._funnel.constants import (  # noqa: F401
    _CASES,
    _DISPLAY,
    _MAXN,
    _MAXY,
    _PHI,
    _RENAMED,
    _SS,
    BENCHMARKS,
    COMPARE_TO,
    DEFAULT_FDR_LEVELS,
    MEASURES,
    SIGNALS,
)
from ._funnel.inputs import _check_mean_rows, _mean_inputs, _normalize
from ._funnel.pipeline import _funnel
from ._funnel.settings import _settings
from .core.contours import DEFAULT_LEVELS
from .core.dispersion import DEFAULT_TAU_METHOD
from .results import FunnelResult
from .validate import check_column, check_number, reject_removed, split_facets


def funnel(
    data: pd.DataFrame | None = None,
    *,
    y: Any,
    n: Any = None,
    measure: Literal["oe", "proportion", "rate", "mean"],
    unit: Any = None,
    label: Any = None,
    hover: Any = None,
    facets: str | list[str] | None = None,
    exclude: Any = None,
    center: float | None = None,
    overdispersion: bool | None = None,
    compare_to: Literal["peers", "model"] | None = None,
    within_dispersion: float | str | None = None,
    tau_method: Literal["spiegelhalter", "winsorized", "ml", "cqc", "shmi"] = DEFAULT_TAU_METHOD,
    tau: float | dict | None = None,
    cases: str | None = None,
    sum_sq: str | None = None,
    max_case_y: str | None = None,
    max_case_n: str | None = None,
    fdr_min_denominator: float | None = None,
    worse: Literal["higher", "lower"] | None = None,
    signal: Literal["limits", "fdr"] = "limits",
    limits: tuple[float, float] = DEFAULT_LEVELS,
    fdr_levels: tuple[float, float] = DEFAULT_FDR_LEVELS,
    benchmark: Literal["abc", "eb"] | None = None,
    benchmark_share: float = 0.10,
    multiply: float = 1.0,
    interval: float = 0.95,
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
    | a per-case amount: minutes, cost or days per stay  | measure="mean", y=the amount, one row  |
    |   (EHR minutes per discharge, cost per case)       |   per case (n optional), or SQL totals |
    |                                                    |   y=SUM, n=COUNT, sum_sq=SUM(y*y)      |
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
    | expected from an external risk model (Vizient,     | compare_to="model" (O/E against 1.0,   |
    |   CMS), asking "worse than expected?"              |   no allowance for spread)             |
    | "unusual among peers?" (the default question)      | compare_to="peers", or nothing         |
    | a fixed target on a proportion or rate             | center=<target>, overdispersion=False  |
    | a measure where only one direction is bad          | worse="higher" (or "lower")            |
    | hundreds of providers, and want few false alarms   | signal="fdr"                           |
    | flags from the lines, figure showing the q tiers   | .plot(color_by="fdr")                  |
    | many very-low-volume providers diluting the        | fdr_min_denominator= (a volume floor   |
    |   signal="fdr" step                                |   for the FDR step only)               |
    | the spread between providers known from earlier    | tau=<that value> (a number, or one per |
    |   periods, or few providers (K < 30)               |   facet): fixed in advance             |
    | to reproduce a CQC or NHS SHMI funnel              | tau_method="cqc" or "shmi"             |
    | to rank flagged providers for action               | sort by eb_excess, not raw_excess      |
    | to say "probably worse than average" (CMS-style)   | read prob_worse; signal is unchanged   |
    | an estimate with a range per provider (scorecard)  | eb_rate, eb_low, eb_high,              |
    |                                                    |   estimate_flag; plot(kind=            |
    |                                                    |   "caterpillar")                       |
    | several measures or service lines in one call      | facets=["measure"] (one or more cols)  |
    | a goal the best providers already reach (ABC)      | benchmark="abc" with worse=            |
    | the same goal for an outcome (O/E mortality, LOS)  | benchmark="eb" with worse=             |

    Two questions, both legitimate (methods §2), named by compare_to=: "peers" (the
    default) asks "is this provider unusual among its peers?", judging each provider
    against the pooled value and the measured spread between providers as well as
    chance; "model" asks "does this provider differ from the risk model?" (center=1.0,
    overdispersion=False). Decide which before looking. A fixed center= with
    overdispersion=True answers neither: any system-wide gap between the providers and
    that center is absorbed into tau, widening every limit, and a warning says so
    (methods §4.2.1).

    Reading the result
    ------------------
    result.data has one row per provider (per unit and facet), in plotted order (by
    denominator):

    - signal: "outlier", "alert" or "none". The tiers never overlap; an outlier is
      not also an alert. Under worse= only the worse side is flagged.
    - direction: "higher" or "lower", which side of the center line the point is on.
    - y: the plotted value (O/E ratio, proportion, rate or mean, after multiply=);
      numerator and denominator: the summed y= and n= inputs, in the caller's units.
    - effective_denominator: only with a per-provider within_dispersion column: the
      denominator ÷ φᵢ the model sees, which is the x axis of the plot.
    - cl: the center line. lower_outlier / upper_outlier: the outer contour (99.8% by
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
    - excluded: dropped from the center line, the dispersion estimates and testing.
    - raw_excess: (numerator − cl·denominator), signed so positive is worse: the
      excess days or events.
    Shrunk estimates (methods §4.14). Each provider's true value has an exact
    posterior: gamma for counts (O/E, rate, mean), beta for proportions, on effective
    counts. Its prior is centered on the center line (under compare_to="model", the
    pooled value) with the spread estimated by maximum likelihood (or tau=), whatever
    tau_method the limits use. The columns:
    - reliability: the shrinkage weight, 0 to 1: how much of the provider's difference
      is signal rather than chance. 0 for every provider when there is no measurable
      spread, and on an unadjusted chart with a custom center. 0.7 is the usual floor
      for high-stakes use of a single score (Adams et al. 2010).
    - eb_rate, eb_excess: the shrunk (empirical Bayes) value, the posterior mean, and
      its excess over the reference. Sort on eb_excess to prioritize.
    - eb_low, eb_high: an equal-tailed interval= (95%) interval for the provider's true
      value from the same posterior, on the plotted scale. NaN when there is no
      measurable spread (a note says so). With within_dispersion it runs about 5 points
      short of nominal (methods §5).
    - prob_worse: the posterior probability that the provider's true value is worse
      than the reference ("is this provider truly worse?", the CMS question), where
      signal answers "is it unusual?" (methods §4.16). NaN when there is no spread.
    - estimate_flag: where [eb_low, eb_high] lies against the reference: "worse" or
      "better" with worse= ("higher" or "lower" without it) when wholly on one side,
      else "no different"; None with no interval. It answers a different question from
      signal and has no multiplicity control: about 5% of average providers' intervals
      miss their true value. The reference is summary["reference"]: the center line,
      or 1.0 under compare_to="model".
    - p_value_drop1, flag_survives_drop1, fragility: single-case robustness (case-level
      rows, or max_case_y=/max_case_n= from SQL). Descriptive, never a test (§4.15).
    - benchmark, meets_benchmark: with benchmark=, the goal (the same value on every row
      of a facet) and whether the provider's own value is at it or better.
      benchmark_group (benchmark="abc"): the best performers the ABC pools. A goal, not a
      test: signal is unchanged (methods §4.18).
    - one column per facets= column, and the hover= columns.

    result.summary: n_providers, n_tested, n_outlier, n_alert, expected_false_flags
    (per tier: the chance count under signal="limits", the false discovery bound under
    "fdr"), center, tau (the spread of true values between providers; on the
    transformed scale under "cqc"/"shmi", see tau_scale), phi, tau_method, tau_source,
    tau_estimated, tau_ci ("ml"), compare_to, center_gap, center_gap_p and tau_pooled
    (the fixed-center gap check, methods §4.2.1; None unless center= is fixed with
    overdispersion=True and tau estimated), reference (what the estimate columns are
    judged against), estimate_tau (the spread of their prior) and estimate_tau_ci (its
    95% interval, None when tau= is given), count_model, limit_method, p_value_method,
    within_dispersion and its source, dispersion_shape, underpowered, n_underpowered,
    min_detectable_median, n_filtered, n_fragile, n_rows_dropped (rows missing y, n or
    unit, left out of the sums), notes (sentences to show readers), and
    with benchmark=, benchmark: a dict of method, share and value, and under "abc" also
    providers, coverage (their share of the denominator), group_denominator (median,
    min, max), msd (minimum sufficient denominator), n_below_msd and without_small.
    Under measure="mean", case_sd: the spread of a single case, √(φ·center), in y's units.
    Faceted: the counts summed, notes prefixed, and each facet's summary in by_facet.
    print(result) summarizes it in words.

    Parameters
    ----------
    data : DataFrame of providers, or of cases (stay- or survey-level rows) to be summed
        per unit. Without data=, y, n, unit, label are sequences and hover a dict.
        A row missing y, n or unit is left out of the sums and counted in
        summary["n_rows_dropped"], never read as zero; a provider with no complete row
        is listed with no value and not tested. Text that is not a number is an error.
    y, n : columns (or sequences): the numerator and denominator. Under measure="mean",
        y is the amount and n the case count: 1 per row (the default when n is
        omitted) or each provider's COUNT(*) alongside sum_sq=.
    measure : "oe" (observed / expected: risk-adjusted mortality, readmission, length
        of stay), "proportion" (events / cases), "rate" (events / exposure) or "mean"
        (a per-case amount ≥ 0 such as minutes or cost, averaged per provider; the
        quasi-Poisson model with φ estimated, in y's own units, methods §4.19).
    unit : provider identifier column; rows are providers when omitted.
    label : display name column (the first value per unit); hover : extra tooltip columns.
    facets : a column, or list of columns: one funnel per value, each with its own
        center line, dispersion and Benjamini–Hochberg step.
    exclude : a boolean column, or a unit id or list of unit ids, left out of the center
        line, dispersion and testing (still drawn, faded).
    center : a fixed center line (a target). Pair it with overdispersion=False: with the
        spread allowance on, a gap between the providers' pooled value and the center
        widens every limit, and a UserWarning says so (methods §4.2.1). For O/E against
        the risk model use compare_to="model".
    overdispersion : judge each provider against the estimated spread between providers
        (Spiegelhalter's additive τ²) as well as chance. Default True (unless
        compare_to="model").
    interval : coverage of eb_low / eb_high, 0.95 by default.
    compare_to : which question the chart answers. "peers": the pooled center line and
        overdispersion=True (the default settings). "model": O/E against the risk
        model's expected, center=1.0 and overdispersion=False; measure="oe" only. A
        center= or overdispersion= that contradicts it is an error. None (default):
        center= and overdispersion= as given. Recorded in summary["compare_to"]
        ("peers", "model" or "custom"). Under "model" the limits and signal use 1.0
        with no spread, but the shrunk estimates use a prior centered on the pooled
        value (methods §4.14), and tau= sets only their spread.
    within_dispersion : how much more variable each count is than its model because
        units clump inside cases (patient-days; the items of one survey). 1.0 (default)
        means independent units; under measure="mean" the default, and the only
        scalar, is "estimate" (a column of φᵢ is also accepted). "estimate" computes it from case-level rows; a number
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
        within_dispersion="estimate" needs no case rows. Pass both or neither. Under
        measure="mean" n is the case count, so pass sum_sq= = SUM(y * y) alone.
    max_case_y, max_case_n : per-provider SQL worst case toward worse= (MAX_BY), for
        p_value_drop1 and flag_survives_drop1. Under measure="mean" max_case_y alone
        (max_case_n is 1).
    fdr_min_denominator : a volume floor for the false discovery rate step only, on the
        denominator the model sees (expected events, cases or exposure, ÷ φ; under
        measure="mean", the case count). Providers
        below it keep their p_value but get no q_value (independent filtering, §4.11).
    worse : "higher" or "lower" when only one direction is bad: flags only that side and
        makes p-values one-sided.
    signal : "limits" (default): outlier beyond the outer contour, alert beyond the
        inner one, so the flags match the drawn lines. "fdr": outlier when
        q < fdr_levels[0], alert when q < fdr_levels[1]. Under "limits" a point beyond
        the 95% line can still have a large q_value; .plot(color_by="fdr") draws the
        q tiers without changing the signal column.
    limits : (outer, inner) contour coverage, default (0.998, 0.95).
    fdr_levels : (outlier, alert) false discovery rates for signal="fdr".
    benchmark : a goal drawn beside the funnel; needs worse= (methods §4.18).
        "abc": Kiefe and Weissman's achievable benchmark of care. Providers are ranked best
        first by (x + 1)/(n + 2), taken until they hold benchmark_share of the
        denominator (ties at that point included), and their raw counts pooled. Designed
        for process proportions; on "oe", "rate" and "mean" the ranking adds one event
        at the center line instead, an extension its authors would caution against
        (a note says so).
        "eb": the (1 − benchmark_share) quantile of the shrunk eb_rate across providers,
        toward the better side (O'Brien et al. 2008): the 90th percentile by default.
        The choice for "oe", "rate" and "mean" (O/E mortality, LOS, minutes or cost
        per case); equals the center line when the funnel finds no spread.
    benchmark_share : the share defining "best", 0.10 by default. Choose it before
        looking at who the best providers are.
    multiply : scale the plotted y, e.g. 1000 for a rate per 1,000.

    Display options (title, axis labels, styles, x_log, ...) are arguments of
    result.plot(); result.plot(kind="caterpillar") draws the shrunk estimates with
    their intervals instead; result.limits() gives the contours at any denominators.
    result.to_table() is .data with every possible column in a fixed order (see
    qikit.schema("funnel")), for a database table; result.brief() is the counts, the
    notes and only the flagged providers; result.facet_summary() is one summary row per
    facet.
    """
    if removed:
        reject_removed("funnel", removed, _RENAMED, _DISPLAY,
                       other=("chart", "method", "freeze", "part"),
                       known=tuple(inspect.signature(funnel).parameters))
    st = _settings(
        measure=measure, overdispersion=overdispersion, tau_method=tau_method, tau=tau,
        worse=worse, signal=signal, limits=limits, fdr_levels=fdr_levels,
        fdr_min=fdr_min_denominator, multiply=multiply, center=center, facets=facets,
        benchmark=benchmark, benchmark_share=benchmark_share, compare_to=compare_to,
        interval=interval,
    )
    mean = st.measure == "mean"            # as check_choice read it ("Mean" is "mean")
    if mean:
        n, cases, max_case_n, within_dispersion = _mean_inputs(
            data, n, cases, sum_sq, max_case_y, max_case_n, within_dispersion)
    elif n is None:
        raise ValueError(f"n= is required for measure={measure!r}: the denominator.")
    elif within_dispersion is None:
        within_dispersion = 1.0
    if (cases is None) != (sum_sq is None):
        raise ValueError(
            "cases= and sum_sq= go together: cases is each provider's number of cases and "
            "sum_sq its SUM(POWER(y, 2) / n) over those cases. Pass both, or neither."
        )
    if not mean and (max_case_y is None) != (max_case_n is None):
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
    if mean:
        _check_mean_rows(frame, aggregated=cases is not None)
        if max_case_y is not None:
            frame[_MAXN] = 1.0
    return _funnel(frame, replace(st, hover=tuple(hover_names)), within_dispersion,
                   aggregated=cases is not None, phi_column=phi_column,
                   names={"y": y, "n": n})


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
    Does a provider's flag depend on how the spread between providers was modeled?

    Runs funnel(data, **kwargs) once per tau_method (and once with overdispersion=False
    when unadjusted=True) and returns one row per provider: unit, label (if given), y,
    denominator, the facet columns, one signal_<method> column per run, and consistent,
    True when every run gives the same tier. A provider flagged under one model and not
    another is a judgment call to make explicitly, not a finding (methods §4.16).
    """
    if "tau_method" in kwargs or "overdispersion" in kwargs:
        raise ValueError("funnel_sensitivity() sets tau_method= and overdispersion= itself; "
                         "choose them with tau_methods= and unadjusted=.")
    if kwargs.get("compare_to") == "model":
        raise ValueError(
            "funnel_sensitivity() varies how the spread between providers is modeled, and "
            "compare_to='model' allows no spread, so every run would be the same chart. Run "
            "funnel(..., compare_to='model') alone, or use compare_to='peers' here."
        )
    runs = {f"signal_{m}": funnel(data, **{"tau_method": m, **kwargs}) for m in tau_methods}
    if unadjusted:
        plain = {k: v for k, v in kwargs.items() if k != "compare_to"}
        runs["signal_unadjusted"] = funnel(data, overdispersion=False, **plain)
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
# Minimum denominators by reporting level
# ---------------------------------------------------------------------------

def funnel_rollup(
    data: pd.DataFrame | None = None,
    *,
    units: Any = None,
    reliability: Any = 0.7,
    **kwargs: Any,
) -> pd.DataFrame:
    """
    At which level of a hierarchy can this measure be reported reliably?

    Runs funnel(data, unit=<level>, **kwargs) once per column in units (for example
    ["physician", "group", "department", "hospital"], finest first) and returns each
    level's result.min_denominator(reliability) rows under a leading `level` column:
    the minimum denominator at that level, its range, and how many units are above and
    below it (n_above, n_below) with the volume they hold. Read down the table for the
    finest level at which enough units, and enough of the volume, clear the floor; units
    below it are the ones to roll up.

    Each level is its own fit, because the spread between groups is not the spread
    between physicians: a coarser level has more volume per unit but usually less
    spread, so its floor is often higher. A level where the data show no spread has no
    floor at all (note says so), however large its units.

    data must have one row per case, or per unit of the finest level or finer; funnel()
    sums the rows within each unit. For days, means and surveys pass case-level rows, as
    for funnel(). reliability is one target or several (see
    FunnelResult.min_denominator). label= and hover= are left out: they describe one
    level. .attrs["notes"] holds every level's cautions, prefixed with the level.
    """
    if "unit" in kwargs:
        raise ValueError("funnel_rollup() sets unit= itself, once per level; name the "
                         "levels to compare with units=, e.g. units=['physician', 'group'].")
    if not isinstance(data, pd.DataFrame):
        raise ValueError("funnel_rollup() needs data= as a DataFrame whose columns name "
                         "each level, e.g. units=['physician', 'group'].")
    levels = [units] if isinstance(units, str) else list(units or [])
    if not levels:
        raise ValueError("units= needs the columns naming each level to compare, finest "
                         "first, e.g. units=['physician', 'group', 'hospital'].")
    for level in levels:
        check_column(data, "units", level, required=True)
    options = {k: v for k, v in kwargs.items() if k not in ("label", "hover")}
    frames, notes = [], []
    for level in levels:
        table = funnel(data, unit=level, **options).min_denominator(reliability)
        notes += [f"{level}: {note}" for note in table.attrs["notes"]]
        table.insert(0, "level", level)
        frames.append(table)
    out = pd.concat(frames, ignore_index=True)
    out.attrs["notes"] = notes
    return out
