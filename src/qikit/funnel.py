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
from .core.dist import beta_quantile, beta_tails, gamma_quantile, gamma_tails
from .core.power import UNDERPOWERED_RATIO, point_power
from .core.pvalues import bh_q_values, funnel_p_values, signal_thresholds
from .results import FunnelResult
from .validate import (
    WORSE, check_choice, check_facet_names, check_levels, check_number, reject_removed,
    split_facets,
)

MEASURES = ("oe", "proportion", "rate", "mean")
SIGNALS = ("limits", "fdr")
BENCHMARKS = (None, "abc", "eb")
COMPARE_TO = (None, "peers", "model")
# A provider holding fewer cases than the minimum sufficient denominator could reach
# 100% by chance at this one-sided level (Kiefe 1998, Table 3; methods §4.18).
_MSD_ALPHA = 0.025
DEFAULT_FDR_LEVELS = (0.05, 0.10)
_SIDES = {None: "both", "higher": "above", "lower": "below"}

# Column names funnel() writes to result.data; hover= columns must avoid them.
_COLUMNS = (
    "unit", "label", "y", "numerator", "denominator", "effective_denominator", "cl",
    "lower_outlier", "upper_outlier", "lower_alert", "upper_alert",
    "p_value", "q_value", "signal", "direction", "min_detectable", "ci_lower", "ci_upper",
    "excluded", "raw_excess", "reliability", "eb_rate", "eb_excess", "prob_worse",
    "p_value_drop1", "flag_survives_drop1", "fragility", "benchmark", "benchmark_group",
    "meets_benchmark", "eb_low", "eb_high", "estimate_flag",
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
    n: Any = None,
    measure: str,
    unit: Any = None,
    label: Any = None,
    hover: Any = None,
    facets: str | list[str] | None = None,
    exclude: Any = None,
    center: float | None = None,
    overdispersion: bool | None = None,
    compare_to: str | None = None,
    within_dispersion: float | str | None = None,
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
    benchmark: str | None = None,
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
    judged against) and estimate_tau (the spread of their prior), count_model, limit_method, p_value_method,
    within_dispersion and its source, dispersion_shape, underpowered, n_underpowered,
    min_detectable_median, n_filtered, n_fragile, notes (sentences to show readers), and
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
    exclude : a boolean column, or a list of unit ids, left out of the center line,
        dispersion and testing (still drawn, faded).
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
    """
    if removed:
        reject_removed("funnel", removed, _RENAMED, _DISPLAY, other=("chart", "method", "freeze", "part"))
    st = _settings(
        measure=measure, overdispersion=overdispersion, tau_method=tau_method, tau=tau,
        worse=worse, signal=signal, limits=limits, fdr_levels=fdr_levels,
        fdr_min=fdr_min_denominator, multiply=multiply, center=center, facets=facets,
        benchmark=benchmark, benchmark_share=benchmark_share, compare_to=compare_to,
        interval=interval,
    )
    mean = measure == "mean"
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


def _mean_inputs(data, n, cases, sum_sq, max_case_y, max_case_n, within_dispersion):
    """
    measure="mean" defaults (methods §4.19): n is the case count (1 per row when
    omitted), cases= is that same n, max_case_n is 1, and φ is always estimated or given
    per provider, never a scalar the caller would have to know in y's units.
    """
    if within_dispersion is None:
        within_dispersion = "estimate"
    elif not isinstance(within_dispersion, str):
        raise ValueError(
            "measure='mean' estimates within_dispersion from the cases (the variance-to-"
            "mean ratio of one case, in y's units), so a number cannot be supplied. Leave "
            "it unset, or pass a column of per-provider phi."
        )
    if max_case_n is not None:
        raise ValueError(
            "measure='mean' takes max_case_y= alone: the worst single case's amount; its "
            "denominator is always one case."
        )
    if sum_sq is not None:
        if n is None:
            raise ValueError(
                "measure='mean' with sum_sq= needs n=: each provider's number of cases "
                "(COUNT(*)), alongside y = SUM(amount) and sum_sq = SUM(amount * amount)."
            )
        if cases is not None and cases != n:
            raise ValueError("Under measure='mean' n= is the case count; leave cases= unset.")
        cases = n
    elif cases is not None:
        raise ValueError(
            "measure='mean' with provider totals takes n= (the case count) and sum_sq= "
            "(SUM(amount * amount)); cases= is implied by n=."
        )
    return n, cases, max_case_n, within_dispersion


def _check_mean_rows(frame: pd.DataFrame, aggregated: bool) -> None:
    """Amounts ≥ 0, and on case rows one case per row."""
    y = frame[_Y].to_numpy(dtype=float)
    if np.any(np.isfinite(y) & (y < 0)):
        raise ValueError(
            "measure='mean' needs amounts of 0 or more (minutes, cost, days): its "
            "variance grows with the mean. Signed values such as change scores are not "
            "supported."
        )
    if aggregated:
        return
    n = frame[_N].to_numpy(dtype=float)
    if np.any(np.isfinite(n) & (n != 1.0)):
        raise ValueError(
            "measure='mean' on case rows takes one case per row (n = 1, or leave n= "
            "unset). With one row per provider, pass y = SUM(amount), n = COUNT(*) and "
            "sum_sq = SUM(amount * amount), so the spread of single cases can be measured."
        )


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
    benchmark: str | None = None
    benchmark_share: float = 0.10
    hover: tuple[str, ...] = ()
    limit_method: str = "exact"
    compare_to: str | None = None   # as the caller passed it
    interval: float = 0.95          # coverage of eb_low / eb_high

    @property
    def question(self) -> str:
        """Which question the settings answer: "peers", "model" or "custom"."""
        if self.center is None and self.overdispersion:
            return "peers"
        if self.measure == "oe" and self.center == 1.0 and not self.overdispersion:
            return "model"
        return "custom"

    @property
    def center_user_fixed(self) -> bool:
        """A center line the caller fixed, other than through compare_to="model"."""
        return self.center is not None and self.compare_to != "model"

    @property
    def family(self) -> str:
        return "binomial" if self.measure == "proportion" else "poisson"

    @property
    def side(self) -> str:
        return _SIDES[self.worse]


def _settings(*, measure, overdispersion, tau_method, tau, worse, signal, limits,
              fdr_levels, fdr_min, multiply, center, facets, benchmark=None,
              benchmark_share=0.10, limit_method="exact", compare_to=None,
              interval=0.95) -> _Settings:
    check_choice("measure", measure, MEASURES)
    center, overdispersion = _compare_to(compare_to, measure, center, overdispersion)
    check_choice("worse", worse, WORSE)
    check_choice("signal", signal, SIGNALS)
    check_choice("tau_method", tau_method, TAU_METHODS)
    check_choice("limit_method", limit_method, _LIMIT_METHODS)
    check_choice("benchmark", benchmark, BENCHMARKS)
    if benchmark is not None and worse is None:
        raise ValueError(
            f"benchmark={benchmark!r} needs worse='higher' or 'lower': the benchmark is what "
            "the best providers achieve, so it needs to know which direction is better."
        )
    if not check_number("benchmark_share", benchmark_share, 0.0, strict=True) < 1.0:
        raise ValueError(f"benchmark_share is a share strictly between 0 and 1, got {benchmark_share!r}.")
    if tau_method == "shmi" and measure == "proportion":
        transform_scale("shmi", "binomial")  # raises with the fix
    check_number("multiply", multiply, 0.0, strict=True)
    if fdr_min is not None:
        check_number("fdr_min_denominator", fdr_min)
    if not check_number("interval", interval, 0.0, strict=True) < 1.0:
        raise ValueError(f"interval is a coverage strictly between 0 and 1, e.g. 0.95; got {interval!r}.")
    if center is not None:
        check_number("center", center, 0.0, strict=True)
        if measure == "proportion" and not center < 1.0:
            raise ValueError(f"center= on a proportion lies strictly between 0 and 1, got {center!r}.")
    check_facet_names(split_facets(facets), _COLUMNS, "funnel")
    return _Settings(
        measure=measure, overdispersion=bool(overdispersion), tau_method=tau_method,
        tau_fixed=_tau_fixed(tau, facets, overdispersion,
                             model=measure == "oe" and center == 1.0 and not overdispersion),
        tau=tau, worse=worse,
        signal=signal, limits=check_levels("limits", limits, outer_wider=True),
        fdr_levels=check_levels("fdr_levels", fdr_levels, outer_wider=False),
        fdr_min=fdr_min, multiply=float(multiply),
        center=None if center is None else float(center),
        facets=tuple(split_facets(facets)), benchmark=benchmark,
        benchmark_share=float(benchmark_share), limit_method=limit_method,
        compare_to=compare_to, interval=float(interval),
    )


def _compare_to(compare_to, measure, center, overdispersion) -> tuple[Any, bool]:
    """
    (center, overdispersion) resolved from compare_to=. Settings that agree with it may be
    passed too; one that contradicts it is an error naming the fix (methods §2, §4.2).
    """
    check_choice("compare_to", compare_to, COMPARE_TO)
    if compare_to is None:
        return center, True if overdispersion is None else bool(overdispersion)
    if compare_to == "peers":
        if center is not None:
            raise ValueError(
                f"compare_to='peers' judges each provider against the pooled value of its "
                f"peers, so it cannot take center={center!r}. Drop center=, or drop "
                f"compare_to= to keep a fixed center line."
            )
        if overdispersion is False:
            raise ValueError(
                "compare_to='peers' allows for the spread between providers "
                "(overdispersion=True). Drop overdispersion=False, or drop compare_to= for "
                "an unadjusted chart around the pooled center."
            )
        return None, True
    if measure != "oe":
        raise ValueError(
            f"compare_to='model' compares observed with a risk model's expected (O/E against "
            f"1.0); measure={measure!r} has no model value. For a fixed target pass "
            f"center=<target> and overdispersion=False instead."
        )
    if center is not None and center != 1.0:
        raise ValueError(
            f"compare_to='model' sets center=1.0 (observed equals expected), so it cannot "
            f"take center={center!r}. Drop center=, or drop compare_to= to use that center."
        )
    if overdispersion is True:
        raise ValueError(
            "compare_to='model' asks whether each provider differs from the risk model, so "
            "it allows no spread between providers (overdispersion=False). Drop "
            "overdispersion=True, or use compare_to='peers' to ask whether a provider is "
            "unusual among its peers."
        )
    return 1.0, False


def _tau_fixed(tau: Any, facets: Any, overdispersion: bool, model: bool = False) -> Any:
    """
    tau= as τ² (a number, or a dict of τ² per facet), validated. Against the risk model
    (model=True) it sets only the spread the shrunk estimates use (methods §4.14).
    """
    if tau is None:
        return None
    if not overdispersion and not model:
        raise ValueError(
            "tau= needs overdispersion=True: it is the spread the adjusted chart judges "
            "providers against, and the unadjusted chart has none. (Against the risk "
            "model, compare_to='model', it sets the spread of the shrunk estimates.)"
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
        "compare_to": st.question,
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
        "phi_column": phi_column, "multiply": st.multiply, "interval": st.interval,
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

    # The center line and the spread between providers.
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
    prior = _prior(st, cl, ratio, n_model, mask, family, used, scale, tau_fixed, disp)
    _add_shrinkage(table, st, cl, prior, n_model)
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
        "reference": prior.reference * m,
    }
    if st.measure == "mean":
        phi_bar = _mean_phi(den, n_model) if within.phi_units is not None else within.phi
        summary["case_sd"] = math.sqrt(phi_bar * cl) * m
    summary["expected_false_flags"] = _expected_false_flags(st, summary)
    notes: list[str] = []
    if st.compare_to is not None:
        notes.append(_QUESTION[st.compare_to])
    summary.update(_center_gap(st, cl, ratio, n_model, mask, family, tau2, source,
                               disp.scale, notes))
    summary["estimate_tau"] = math.sqrt(prior.tau2)
    if (st.overdispersion or prior.model) and not prior.available:
        notes.append(
            "Shrunk estimates with a range are unavailable: the funnel finds no measurable "
            "spread between providers (tau = 0), so eb_low, eb_high and estimate_flag are "
            "empty. Pass tau= estimated from earlier periods, or compare within a larger "
            "peer group."
        )
    if st.benchmark is not None:
        _add_benchmark(table, summary, notes, st, num, den, n_model, ratio, cl, excluded)
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


_QUESTION = {
    "peers": "This chart asks whether each provider is unusual among its peers: the center "
             "line is their pooled value, and the limits allow for the spread between them.",
    "model": "This chart asks whether each provider differs from the risk model: the center "
             "line is 1.0 (observed equals expected), with no allowance for spread between "
             "providers.",
}

# The fixed-center gap guard (methods §4.2.1): warn when the providers' pooled value
# differs from a center= the caller fixed, under overdispersion=True, by enough that τ̂
# absorbs it. Both conditions must hold: the gap is beyond chance and the spread between
# providers (p below _GAP_MAX_P, a sandwich-variance t test), and it widens the limits at
# the median provider's volume by at least _GAP_MIN_WIDEN. scripts/simulate_center_gap.py
# calibrates both: at most 0.4% false warnings in any cell (K 20-1000, tau 0-0.2,
# phi 1-2), and 51-99% warned at a 10% gap on hospital volumes.
_GAP_MAX_P = 0.001
_GAP_MIN_WIDEN = 1.10


def _center_gap(st: _Settings, cl, ratio, n_model, mask, family, tau2, source, scale,
                notes) -> dict:
    """
    center_gap, center_gap_p, tau_pooled; and the warning when a fixed center line under
    overdispersion=True has τ̂ absorbing a system-wide gap (methods §4.2.1).
    """
    out: dict[str, Any] = {"center_gap": None, "center_gap_p": None, "tau_pooled": None}
    if not (st.center_user_fixed and st.overdispersion and source == "estimated"):
        return out
    ok = mask & np.isfinite(ratio) & (n_model > 0)
    if ok.sum() < 2:
        return out
    pooled = _pooled(ratio, n_model, ok)
    if st.tau_method == "ml":
        tau2_p, _ = tau2_ml(pooled, ratio, n_model, ok, family)
    else:
        tau2_p = overdispersion(st.tau_method, family, pooled, ratio, n_model, ok).tau2
    nat_fixed = natural_tau2(scale, cl, tau2)
    nat_pooled = natural_tau2(scale, pooled, tau2_p)
    binomial = family == "binomial"

    def var(theta):
        return theta * (1.0 - theta) if binomial else theta

    p = _gap_p_value(pooled, cl, ratio[ok], n_model[ok])
    v_med = var(cl) / float(np.median(n_model[ok]))
    widen = math.sqrt((v_med + nat_fixed) / (v_med + nat_pooled))
    gap = pooled / cl - 1.0
    out.update({"center_gap": gap, "center_gap_p": p, "tau_pooled": math.sqrt(tau2_p)})
    if p < _GAP_MAX_P and widen >= _GAP_MIN_WIDEN:
        fix = ("for 'worse than the risk model?' use compare_to='model'"
               if st.measure == "oe" else
               f"for 'different from the target?' pass overdispersion=False with "
               f"center={cl:g}")
        note = (f"The spread between providers is absorbing a {gap:+.0%} system-wide gap "
                f"between the providers' pooled value ({pooled:.3g}) and center={cl:g}, "
                f"which widens every limit (by about {widen - 1:.0%} at the median "
                f"volume). For 'unusual among peers?' leave center unset; {fix}.")
        notes.append(note)
        warnings.warn(note, UserWarning, stacklevel=4)
    return out


def _gap_p_value(pooled: float, cl: float, y: np.ndarray, n: np.ndarray) -> float:
    """
    Two-sided p-value for the pooled value Σnᵢyᵢ/Σnᵢ against a fixed center: a weighted
    mean with its robust (sandwich) variance K/(K − 1)·Σnᵢ²(yᵢ − ȳ)²/(Σnᵢ)², referred to
    t on K − 1 degrees of freedom. The observed scatter carries chance, within-case
    clumping and real spread between providers alike, so no τ̂ (biased low at small K
    under the published estimator) enters the test (methods §4.2.1).
    """
    k = len(y)
    total = float(n.sum())
    se2 = k / (k - 1) * float(np.sum(n * n * (y - pooled) ** 2)) / total ** 2
    if not se2 > 0:
        return 1.0 if pooled == cl else 0.0
    t2 = (pooled - cl) ** 2 / se2
    df = k - 1
    return beta_tails(df / (df + t2), df / 2.0, 0.5)[0]


def _add_benchmark(table, summary, notes, st: _Settings, num, den, n_model, ratio, cl,
                   excluded) -> None:
    """The benchmark= columns, summary keys and notes for one facet (methods §4.18)."""
    m, share = st.multiply, st.benchmark_share
    eligible = ~excluded & np.isfinite(num) & (den > 0)
    if st.benchmark == "eb":
        eb = table["eb_rate"].to_numpy(dtype=float) / m
        q = 1.0 - share if st.worse == "lower" else share
        value = float(np.quantile(eb[eligible], q)) if eligible.any() else math.nan
        bench = {"method": "eb", "share": share, "value": value * m}
        if not (table["reliability"].to_numpy(dtype=float) > 0).any():
            notes.append("The funnel finds no spread between providers, so every shrunk "
                         "estimate equals the center line and so does the benchmark.")
    else:
        value, group = _abc(st, share, num, den, n_model, cl, eligible)
        msd = _msd(st, cl)
        small = eligible & (n_model < msd)
        without, _ = _abc(st, share, num, den, n_model, cl, eligible & ~small)
        held = den[group]
        table["benchmark_group"] = group
        bench = {
            "method": "abc", "share": share, "value": value * m,
            "providers": int(group.sum()),
            "coverage": float(held.sum() / den[eligible].sum()) if group.any() else 0.0,
            "group_denominator": (
                {"median": float(np.median(held)), "min": float(held.min()),
                 "max": float(held.max())} if group.any() else None),
            "msd": msd if math.isfinite(msd) else None,
            "n_below_msd": int(small.sum()),
            "without_small": without * m,
        }
        if st.measure != "proportion":
            notes.append(
                "The achievable benchmark was designed for process-of-care proportions; its "
                "authors urge that it be applied to outcome measures with extreme caution, if "
                "at all. benchmark=\"eb\" is the outcome alternative."
            )
        if 0 < group.sum() < 3:
            notes.append(
                f"The achievable benchmark rests on {int(group.sum())} provider(s): one or "
                f"two high-volume providers hold {share:.0%} of the denominator, so treat it "
                "as provisional."
            )
        if small.any() and math.isfinite(without) and abs(without - value) > 0.05 * abs(value):
            notes.append(
                f"Without the {int(small.sum())} providers below the minimum sufficient "
                f"denominator ({msd:.3g}) the achievable benchmark would be "
                f"{_two_sig(without * m)} rather than {_two_sig(value * m)}: it leans on "
                "low-volume providers."
            )
    summary["benchmark"] = bench
    table["benchmark"] = np.full(len(table), bench["value"])
    with np.errstate(invalid="ignore"):
        meets = ratio >= value if st.worse == "lower" else ratio <= value
    table["meets_benchmark"] = meets & np.isfinite(ratio)


def _abc(st: _Settings, share: float, num, den, n_model, cl, eligible) -> tuple[float, np.ndarray]:
    """
    Kiefe's achievable benchmark of care (methods §4.18): (ABC, which providers it pools).
    The eligible providers are ranked best first by an adjusted rate that keeps one with
    few cases from topping the list on luck, taken in that order until they hold the
    share of the eligible denominator, together with every provider tied with the one
    that reaches it (Weissman et al. 1999). The ABC is their pooled raw rate Σy/Σn.
    """
    group = np.zeros(len(num), dtype=bool)
    if not eligible.any():
        return math.nan, group
    # Counts on the scale the model sees (y/φ out of n/φ under within_dispersion).
    with np.errstate(divide="ignore", invalid="ignore"):
        y_eff = np.where(den > 0, num * n_model / den, np.nan)
    if st.measure == "proportion":
        adjusted = (y_eff + 1.0) / (n_model + 2.0)          # Kiefe's APF, Beta(1, 1) prior
    else:
        prior_n = 1.0 / cl if cl > 0 else math.inf          # one event at the center line
        adjusted = (y_eff + 1.0) / (n_model + prior_n)
    rank = -adjusted if st.worse == "lower" else adjusted   # ascending: best first
    idx = np.flatnonzero(eligible)
    idx = idx[np.argsort(rank[idx], kind="stable")]
    reached = np.cumsum(den[idx]) >= share * float(den[idx].sum()) * (1 - 1e-12)
    breakpoint = rank[idx[int(np.argmax(reached))]]
    # Everyone tied at the breakpoint joins, so the share held can run past the target.
    chosen = idx[rank[idx] <= breakpoint + 1e-12 * abs(breakpoint)]
    group[chosen] = True
    return float(num[chosen].sum() / den[chosen].sum()), group


def _msd(st: _Settings, cl: float) -> float:
    """
    The minimum sufficient denominator (methods §4.18): the fewest cases at which perfect
    performance would be a one-sided 2.5% event if the provider's true rate were the
    center line. On a proportion, the smallest N with p̄ᴺ < 0.025, p̄ the rate in the good
    direction; it reproduces every row of Kiefe et al.'s Table 3. On a count with
    worse="higher", the exposure at which zero events has probability e^(−θ₀n) < 0.025.
    """
    if st.measure == "proportion":
        good = cl if st.worse == "lower" else 1.0 - cl
        if good <= 0:
            return 1.0
        if good >= 1:
            return math.inf
        return float(math.floor(math.log(_MSD_ALPHA) / math.log(good)) + 1)
    if st.worse == "higher" and cl > 0:
        return -math.log(_MSD_ALPHA) / cl
    return math.inf


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
    if within.source == "estimated" and within.phi < 1.0 and measure != "mean":
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
        noun = {"proportion": "proportion", "mean": "mean"}.get(measure, "rate")
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
           "rate": ("chance", "rates"), "mean": ("chance", "means")}


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

@dataclass(frozen=True)
class _Prior:
    """The prior the estimate columns shrink toward, and what they are judged against."""
    center: float        # θ₀ of the prior (the chart's center line, or the pooled value)
    tau2: float          # its variance, on the natural scale
    reference: float     # what prob_worse and estimate_flag compare with
    model: bool          # compare_to="model": pooled prior, judged against 1.0
    params: tuple | None  # (α, β) of the beta prior on a proportion, else None
    binomial: bool = False

    @property
    def available(self) -> bool:
        """Whether the posterior intervals exist: a spread, and on a proportion a beta."""
        return self.tau2 > 0 and not (self.binomial and self.params is None)


# Below this reliability at the largest provider, an estimated τ counts as no spread.
_MIN_RELIABILITY = 0.01


def _prior(st: _Settings, cl, ratio, n_model, mask, family, used, scale, tau_fixed,
           disp) -> _Prior:
    """
    The estimate columns' prior (methods §4.14): its center, its spread τ², and the
    reference the estimates are judged against.

    τ² is the maximum-likelihood estimate of the chart's own mixture model around the
    prior's center, or tau= when given. The limits keep the chart's tau_method: the
    published estimator understates τ, which suits a screen whose flags are reviewed,
    but would over-shrink the estimates and leave their intervals short (95% intervals
    cover 56-89% of true values under it, 91-95% under ML; methods §5).

    The center is the chart's center line, judged against itself. Against the risk
    model (compare_to="model", which has no spread allowance) the limits stay at 1.0
    with no τ, but the prior is centered on the providers' pooled value, with τ̂ around
    it; each provider is then judged against 1.0. Estimating τ around 1.0 would absorb
    any system-wide gap into it (§4.2.1), and the pooled value is the best guess for a
    low-volume provider in this system. A chart with neither (overdispersion=False on
    a custom center) has no prior: nothing to shrink toward.
    """
    binomial = family == "binomial"
    model = st.question == "model"
    ok = mask & np.isfinite(ratio) & (n_model > 0)
    if model:
        center, reference = _pooled(ratio, n_model, ok), 1.0
    else:
        center, reference = cl, cl
    if tau_fixed is not None:
        tau2 = float(tau_fixed) if model else natural_tau2(scale, cl, used)
    elif not (st.overdispersion or model) or ok.sum() < 2:
        tau2 = 0.0
    else:
        tau2 = tau2_ml(center, ratio, n_model, ok, family)[0]
        # An estimate that would leave every provider's reliability below
        # _MIN_RELIABILITY is no measurable spread: ML returns such values from the
        # numerical noise beside τ = 0, and their priors (a + b in the millions on a
        # proportion) carry nothing but cost.
        n_max = float(np.max(n_model[ok]))
        v = center * (1.0 - center) if binomial else center
        if tau2 > 0 and tau2 / (tau2 + v / n_max) < _MIN_RELIABILITY:
            tau2 = 0.0
    params = beta_params(center, tau2) if binomial and tau2 > 0 else None
    return _Prior(float(center), float(tau2), float(reference), model, params, binomial)


def _add_shrinkage(table, st: _Settings, cl: float, prior: _Prior, n_model) -> None:
    """
    raw_excess, reliability, eb_rate, eb_excess, prob_worse, eb_low, eb_high,
    estimate_flag (methods §4.14). The weight is the exact conjugate posterior mean of
    the chart's own mixture model: Poisson–gamma, B = τ²/(τ² + θ₀/n); beta-binomial,
    B = n/(n + s), s = θ₀(1 − θ₀)/τ² − 1; both on the model's n (÷ φ). B = 0 when
    τ² = 0: no measured spread, nothing to shrink toward. On a transformed-scale chart
    (cqc, shmi) τ² is carried back by the delta method. θ₀ is the prior's center (the
    center line, or under compare_to="model" the pooled value); raw_excess stays
    against the center line, and eb_excess, prob_worse and estimate_flag against the
    reference (the center line, or 1.0 under compare_to="model").
    """
    sign = -1.0 if st.worse == "lower" else 1.0
    binomial = st.measure == "proportion"
    c, tau2, ref, params = prior.center, prior.tau2, prior.reference, prior.params
    num = table["numerator"].to_numpy(dtype=float)
    den = table["denominator"].to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        y = num / den
        if not (tau2 > 0):
            b = np.zeros(len(table))
        elif params is not None:
            b = n_model / (n_model + params[0] + params[1])
        else:
            b = tau2 / (tau2 + (c * (1.0 - c) if binomial else c) / n_model)
        eb = b * y + (1.0 - b) * c
    m = st.multiply
    table["raw_excess"] = sign * (num - cl * den)
    table["reliability"] = b
    table["eb_rate"] = eb * m
    table["eb_excess"] = sign * (eb - ref) * den
    o_eff = y * n_model
    table["prob_worse"] = _prob_worse(o_eff, n_model, c, tau2, binomial,
                                      st.worse == "lower", params, ref)
    low, high = _posterior_interval(o_eff, n_model, c, tau2, binomial, params, st.interval)
    table["eb_low"], table["eb_high"] = low * m, high * m
    table["estimate_flag"] = _estimate_flag(low, high, ref, st.worse)


def _posterior_interval(o_eff, n_eff, c, tau2, binomial, params, coverage):
    """
    Equal-tailed interval for each provider's true value from its own posterior:
    Gamma(c²/τ² + O, rate c/τ² + E) for counts, Beta(α + Y, β + n − Y) for proportions,
    on effective counts (y/φ out of n/φ). NaN everywhere when τ² = 0 (methods §4.14).
    """
    k = len(o_eff)
    low, high = np.full(k, np.nan), np.full(k, np.nan)
    if not (tau2 > 0) or (binomial and params is None):
        return low, high
    lo_p, hi_p = (1.0 - coverage) / 2.0, (1.0 + coverage) / 2.0
    for i, (o, n) in enumerate(zip(o_eff, n_eff)):
        if not (np.isfinite(o) and np.isfinite(n) and n > 0):
            continue
        if binomial:
            a, b = params[0] + o, params[1] + n - o
            low[i], high[i] = beta_quantile(lo_p, a, b), beta_quantile(hi_p, a, b)
        else:
            shape, rate = c * c / tau2 + o, c / tau2 + n
            low[i] = gamma_quantile(lo_p, shape) / rate
            high[i] = gamma_quantile(hi_p, shape) / rate
    return low, high


def _estimate_flag(low, high, ref, worse) -> np.ndarray:
    """
    Where the interval lies against the reference: wholly above or below it, or
    across it ("no different"). With worse= the sides are "worse" and "better";
    without it, "higher" and "lower". None where there is no interval.
    """
    up, down = ("worse", "better") if worse == "higher" else (
        ("better", "worse") if worse == "lower" else ("higher", "lower"))
    out = np.full(len(low), None, dtype=object)
    ok = np.isfinite(low) & np.isfinite(high)
    out[ok] = "no different"
    out[ok & (low > ref)] = up
    out[ok & (high < ref)] = down
    return out


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
    runs = {f"signal_{m}": funnel(data, tau_method=m, **kwargs) for m in tau_methods}
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
        yv = np.asarray(y, dtype=float)
        frame = pd.DataFrame({_Y: yv, _N: np.ones(len(yv)) if n is None else np.asarray(n, dtype=float)})
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
        frame = pd.DataFrame({_Y: data[y].to_numpy(dtype=float),
                              _N: 1.0 if n is None else data[n].to_numpy(dtype=float)},
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


def _prob_worse(o_eff, n_eff, cl, tau2, binomial, lower, params, ref=None) -> np.ndarray:
    """
    P(true value worse than the reference | data) under the posterior (methods §4.16):
    Gamma(a + O, rate b + E) with a = cl²/τ², b = cl/τ² for counts, Beta(α + Y,
    β + n − Y) for proportions, on effective counts, cl the prior's center. The
    reference is cl, or 1.0 under compare_to="model". NaN when τ = 0 or no beta has the
    spread.
    """
    ref = cl if ref is None else ref
    out = np.full(len(o_eff), np.nan)
    if not (tau2 > 0) or (binomial and params is None):
        return out
    for i, (o, n) in enumerate(zip(o_eff, n_eff)):
        if not (np.isfinite(o) and np.isfinite(n) and n > 0):
            continue
        if binomial:
            below, above = beta_tails(ref, params[0] + o, params[1] + n - o)
        else:
            below, above = gamma_tails(cl * cl / tau2 + o, (cl / tau2 + n) * ref)
        out[i] = below if lower else above
    return out
