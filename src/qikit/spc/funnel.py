"""
funnel.py — funnel(): compare providers against each other or a benchmark.

    from qikit import funnel
    r = funnel(df, y="deaths", n="expected", measure="oe", unit="surgeon", worse="higher")
    r.data[r.data.signal != "none"]      # who flagged, and how strongly
    r.summary                            # model, expected chance flags, notes
    r.plot()

A thin, validated front door to the same engine qic() uses: every number comes from
compute(), pvalues.py and limits.py, and docs/methods.md is the canonical account of
each method and every departure from Spiegelhalter (2005).
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .dist import beta_tails, gamma_tails
from .limits import DEFAULT_LEVELS, TAU_METHODS, beta_params
from .pvalues import funnel_p_values, signal_thresholds
from .results import SPCResult

VALID_MEASURES = ("oe", "proportion", "rate")
VALID_WORSE = (None, "higher", "lower")
VALID_SIGNALS = ("limits", "fdr")
DEFAULT_FDR_LEVELS = (0.05, 0.10)

# measure → (unadjusted chart, over-dispersion-adjusted chart) in the engine.
_CHARTS = {"oe": ("oe", "oep"), "proportion": ("p", "pp"), "rate": ("u", "up")}
_SIDES = {None: "both", "higher": "above", "lower": "below"}

# Column names funnel() writes to result.data; hover= columns must avoid them.
_COLUMNS = (
    "unit", "label", "y", "numerator", "denominator", "cl",
    "lower_outlier", "upper_outlier", "lower_alert", "upper_alert",
    "p_value", "q_value", "signal", "direction",
    "min_detectable", "ci_lower", "ci_upper", "excluded", "facet",
    "effective_denominator", "raw_excess", "reliability", "eb_rate", "eb_excess",
    "prob_worse", "p_value_drop1", "flag_survives_drop1", "fragility",
)

# Internal working columns on the normalized frame.
_UNIT, _Y, _N, _LABEL, _EXCL = "__unit", "__y", "__n", "__label", "__exclude"
_CASES, _SS, _MAXY, _MAXN, _PHI = "__cases", "__sum_sq", "__max_y", "__max_n", "__phi"

# fragility scans at most this many of a unit's worst cases (methods §4.15).
_FRAGILITY_MAX = 50


def funnel(
    data: pd.DataFrame | None = None,
    *,
    y: Any,
    n: Any,
    measure: str,
    unit: Any = None,
    label: Any = None,
    hover: Any = None,
    facets: str | None = None,
    exclude: Any = None,
    center: float | None = None,
    overdispersion: bool = True,
    within_dispersion: float | str = 1.0,
    tau_method: str = "winsorized",
    tau: float | dict | None = None,
    cases: str | None = None,
    sum_sq: str | None = None,
    max_case_y: str | None = None,
    max_case_n: str | None = None,
    test_min_expected: float | None = None,
    worse: str | None = None,
    signal: str = "limits",
    limits: tuple[float, float] = DEFAULT_LEVELS,
    fdr_levels: tuple[float, float] = DEFAULT_FDR_LEVELS,
    multiply: float = 1.0,
    title: str = "",
    subtitle: str | None = None,
    caption: str | None = None,
    xlab: str | None = None,
    ylab: str | None = None,
    label_signals: str | None = None,
    styles: dict | list | None = None,
    x_log: bool = False,
    x_range: tuple | None = None,
    y_range: tuple | None = None,
    show_legend: bool = True,
    width: int | None = None,
    height: int | None = None,
) -> FunnelResult:
    """
    Compare providers on one measure with a funnel plot, and flag the unusual ones.

    Choosing the settings
    ---------------------
    | You have                                          | Pass                                   |
    |---------------------------------------------------|----------------------------------------|
    | observed events and risk-model expected events     | measure="oe", y=observed, n=expected   |
    | events out of cases (mortality %, top-box %)       | measure="proportion", y=events, n=cases|
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
    | many very-low-volume providers diluting the        | test_min_expected= (a volume floor     |
    |   signal="fdr" step                                |   for the FDR step only)               |
    | the spread between providers known from earlier    | tau=<that value> (a number, or one per |
    |   periods, or few providers (K < 30)               |   facet): fixed in advance             |
    | to reproduce a published funnel (FunnelPlotR, CQC) | tau_method="spiegelhalter"             |
    | to rank flagged providers for action               | sort by eb_excess, not raw_excess      |
    | to say "probably worse than average" (CMS-style)   | read prob_worse; signal is unchanged   |

    Leave overdispersion=True (the default) for provider comparison: real differences
    between providers always add spread, and when there is none the chart is
    identical to the unadjusted one.

    Reading the result
    ------------------
    result.data has one row per provider (per unit and facet), in plotted order:

    - signal: "outlier", "alert" or "none". The tiers never overlap; an outlier is
      not also an alert. Under worse= only the worse side is flagged.
    - direction: "higher" or "lower", which side of the center line the point is on.
    - y: the plotted value (O/E ratio, proportion or rate, after multiply=);
      numerator and denominator: the summed y= and n= inputs (observed and
      expected, events and cases, events and exposure).
    - cl: the center line. lower_outlier / upper_outlier: the outer contour (99.8% by
      default); lower_alert / upper_alert: the inner one (95%). Each contour is the
      boundary of an exact test, so a point is beyond the upper_outlier line exactly
      when its one-sided p-value is below 0.001.
    - p_value: the exact p-value against the same model the contours are drawn from
      (one-sided toward worse=, or doubled for two-sided); q_value: its
      Benjamini–Hochberg adjustment across the providers in this chart (each facet
      separately; excluded providers are not tested; x_range= only trims the view).
    - min_detectable: the smallest true value this provider could have flagged with
      80% power. A provider inside the funnel at physician volumes is often "not
      enough data", not "fine". ci_lower / ci_upper: an exact 95% interval for the
      provider's own value.
    - excluded: dropped from the center line, the dispersion estimate and testing.
    - raw_excess: (y − cl)·denominator in the caller's units (days, events, cases),
      signed so positive is worse (toward "higher" when worse=None).
    - reliability: τ²/(τ² + V₀), the share of a provider's observed difference that is
      signal rather than chance, 0 to 1 (methods §4.14). 0 for every provider when the
      funnel finds no spread between providers (τ̂ = 0) or overdispersion=False.
      Reliability ≥ 0.7 is the usual floor for high-stakes use of a single score.
    - eb_rate: the provider's shrunk (empirical Bayes) value, reliability·y +
      (1 − reliability)·cl, on the plotted scale: the exact posterior mean of the
      chart's own Poisson–gamma or beta-binomial model.
    - eb_excess: (eb_rate − cl)·denominator, signed as raw_excess. The expected excess
      days or events once chance is discounted: sort on this to prioritise, because
      raw_excess lets high-volume providers with small, noisy differences lead.
    - prob_worse: the posterior probability that the provider's true value is worse
      than cl (above it for worse="higher" or None, below for "lower"), under the same
      model as eb_rate. It answers "is this provider truly worse than average?", the
      question of CMS's hierarchical models, where signal answers "is it unusual among
      peers?" (methods §4.16). The two can disagree, and both are right: with a large
      real spread many providers are truly worse than average yet not unusual. NaN
      when τ = 0 (no spread to shrink against). It never changes signal.
    - p_value_drop1: the p-value with the provider's single most extreme case removed
      (worst toward worse=, or toward its own side when worse=None), against the same
      cl, τ² and within_dispersion. NaN without case-level information (case rows,
      or max_case_y=/max_case_n=). Descriptive only: it has no q-value, because
      choosing the worst case is a selection no false discovery rate survives.
    - flag_survives_drop1: for flagged providers, whether they would still flag at the
      alert tier with that case removed (under signal="fdr", at the same p-value
      cutoff the false discovery rate step used); <NA> for unflagged providers or
      without case information.
    - fragility: case-level rows only: the fewest worst cases that must be removed
      before a flagged provider stops flagging, scanning up to min(cases − 1, 50);
      <NA> when unflagged or when the flag outlasts the scan. The provider-profiling
      analogue of a trial's Fragility Index. On event counts (deaths, readmissions)
      every event is one patient, so fragility 1 at low volume is the expected
      discreteness of counts, not a sign of a data problem; it is most informative
      for days (length of stay).
    - effective_denominator: only with a per-provider within_dispersion column: the
      denominator ÷ φᵢ the model sees, which is the x axis of the plot.

    result.summary holds the model and how to read the counts:
    n_outlier, n_alert, expected_false_flags (per tier; see signal=), tau (the spread
    of true values between providers), count_model, within_dispersion and its source,
    dispersion_shape with within_dispersion_hint (and its source: the case "rows" or the
    provider "totals"), underpowered, tau_method, tau_source ("estimated" or
    "pre-specified"), tau_estimated (this period's winsorized τ̂, reported even when tau=
    fixes the τ used), tau_ci (a 95% profile-likelihood interval, tau_method="ml"
    only), phi_raw and phi_debiased (the winsorized over-dispersion estimate before and
    after the consistency factor; phi_debiased is NaN under tau_method="spiegelhalter"),
    test_min_expected with n_filtered (left out
    of the FDR step), n_fragile (flagged providers with fragility 1), and notes (a list
    of sentences to show readers: power, over-dispersion, clustered counts, fragile
    flags, filtering). print(result) summarizes it in words.

    Parameters
    ----------
    data : DataFrame of providers, or of cases (stay-level rows) to be summed per unit.
        Without data=, y, n, unit, label are sequences and hover a dict of sequences.
    y, n : column names (or sequences): the numerator and denominator. Rows sharing a
        unit are summed, so stay-level data aggregates itself.
    measure : "oe" (observed / expected, e.g. risk-adjusted mortality, readmission or
        length of stay), "proportion" (events / cases) or "rate" (events / exposure).
    unit : provider identifier column; rows are providers when omitted.
    label : display name column (the first value per unit is used).
    hover : extra tooltip columns (a name or list of names).
    facets : column to split into separate funnels (e.g. measure or service line).
        Each facet has its own center line, dispersion and Benjamini–Hochberg step.
    exclude : a boolean column name, or a list of unit ids, to leave out of the
        center line, dispersion and testing (they are still drawn, ghosted).
    center : a fixed center line. On measure="oe", center=1.0 benchmarks against the
        risk model itself ("who differs from expected?"); the default pooled ΣO/ΣE asks
        "who differs from their peers?".
    overdispersion : judge each provider against the estimated spread between
        providers (Spiegelhalter's additive τ²), as well as chance. Default True.
    within_dispersion : how much more variable each count is than its model because
        units clump inside cases: patient-days (one stay adds many days), or the items
        of one survey (one patient answers the doctor questions alike, so 12 items
        from 4 surveys carry about 5 items' worth of information). 1.0 (default)
        means independent units. "estimate" computes it from case-level rows (several
        rows per unit: one per stay, or one per survey), from each row's residual
        around its own provider's rate. A number supplies it, e.g. from SQL over
        stay-level data:
            SUM(POWER(los - exp_los, 2) / exp_los) / (COUNT(*) - COUNT(DISTINCT provider))
        The model then sees y/φ out of n/φ (Rao–Scott effective counts); the plotted
        values and the numerator/denominator columns stay in the caller's units. Leave
        it at 1 for event counts (deaths, readmissions) and for one yes/no per case.
        Never pass one row per item: a single yes/no cannot show clustering. When the
        spread (or the case-level rows) looks clustered and this is left at 1, a
        UserWarning says so and summary["dispersion_shape"] is "within" or "both".
        A column name gives one φᵢ per provider instead (constant within a provider),
        for variability that differs with case mix: compute each DRG's (or service
        line's) φ_g in SQL as for the single number above, then per provider
        φᵢ = Σⱼ φ_g(j)·eⱼ / Σⱼ eⱼ over its stays. Each provider is then judged on
        y/φᵢ out of n/φᵢ, and the plot's x axis (and limits()) is that effective
        denominator, so every point still sits against its own exact test (methods
        §4.12). "estimate" always means the estimate, never a column of that name.
    tau_method : how τ, the spread of true values between providers, is estimated from
        this period's data (methods §4.16). "winsorized" (default): Spiegelhalter's 10%
        winsorized moment estimator times its Gaussian consistency factor 1.47 (his
        eq. 9). Robust to the outliers being screened for and accurate from about 50
        providers; with few providers and no real spread it overstates τ slightly.
        "spiegelhalter": the same without the factor, exactly as published and as
        FunnelPlotR and CQC compute it, for reproducing those; it understates τ (0 for a
        true 0.10 across 1,000 physicians) and so over-flags. "ml": maximum likelihood
        under the chart's own Poisson–gamma or beta-binomial model, the estimator of
        random-effects models (Pavlou 2023; CMS), with a 95% interval in tau_ci. Use it
        only on data known to be free of gross outliers: it is not robust, and a single
        extreme provider among 30 inflates τ̂ badly enough to hide itself and others
        (methods §4.16). Only the adjusted chart (overdispersion=True) draws its limits
        from τ.
    tau : a τ fixed in advance instead of estimated: a number >= 0 on the scale of
        summary["tau"] (O/E, proportion or rate), or a dict {facet value: number} with
        one entry per facet. Use it when the spread is known from earlier periods
        (estimate it there, review it, then fix it), when there are too few providers
        to estimate it (K < 30), or to hold every period to the same yardstick. This
        period's own estimate is still reported as summary["tau_estimated"], and a note
        says when it has moved more than 1.5-fold. tau=0 gives the unadjusted chart.
        Needs overdispersion=True.
    cases, sum_sq : column names that let within_dispersion="estimate" (and the
        clustering check) work on one row per provider aggregated in SQL rather than
        on stay- or survey-level rows. Pass both or neither. cases is the number of
        cases kᵢ (stays, surveys); sum_sq is Σⱼ yⱼ²/nⱼ over the provider's cases (O/E
        and rate: SUM(POWER(obs, 2) / exp); proportion: SUM(POWER(items_met, 2) /
        items_answered)), raw sums, not residuals, so they cannot be computed around
        the wrong center. Leave out zero-denominator cases in SQL, as the row path
        does. The result equals the case-row estimate to rounding.
    max_case_y, max_case_n : column names, both or neither, for provider rows from SQL:
        the numerator and denominator of the provider's most extreme case toward
        worse=, e.g. MAX_BY(los_days, los_days - exp_los_days) and MAX_BY(exp_los_days,
        los_days - exp_los_days) (the benchmark ratio 1.0 stands in for the center
        line, which is not known until the funnel is drawn). They give p_value_drop1 and
        flag_survives_drop1; ignored when case-level rows are passed, where qikit finds
        the case itself.
    test_min_expected : a volume floor for the false discovery rate step only (methods
        §4.11). Providers whose denominator (as the model sees it, so ÷ φ under
        within_dispersion) is below it keep their p_value but get no q_value, so they
        cannot flag under signal="fdr" and do not count in its K. They still count
        toward the center line and τ², are still drawn, and still flag under
        signal="limits". A rule on volume alone keeps the false discovery rate
        guarantee (independent filtering); never derive it from outcomes. None
        (default) tests every provider.
    worse : "higher" or "lower" when only one direction is bad (mortality: "higher";
        top-box satisfaction: "lower"). Flags only that side, makes p-values
        one-sided, and words the legend "worse than expected". None (default) flags
        both sides.
    signal : what decides the tiers. "limits" (default): outlier beyond the outer
        contour, alert beyond the inner one; about (1 − coverage)/2 of average
        providers land beyond each line by chance, which expected_false_flags counts.
        "fdr": outlier when q_value < fdr_levels[0], alert when q_value <
        fdr_levels[1]; at most that share of each tier's flags is expected to be
        false. With hundreds of providers "limits" puts many average providers in the
        alert tier by chance; "fdr" does not, but its flags no longer match the drawn
        lines, and the caption says so. One test decides both tiers; there is no
        "either test" mode.
    limits : (outer, inner) contour coverage, default (0.998, 0.95). E.g. (0.997, 0.95).
    fdr_levels : (outlier, alert) false discovery rates for signal="fdr", default
        (0.05, 0.10).
    multiply : scale the plotted y (e.g. 1000 for a rate per 1,000).
    title, subtitle, caption, xlab, ylab : text. An unset caption states the flag rule;
        unset axis titles come from the column names.
    label_signals : write labels on "outlier", "alert" or "both" tiers.
    styles : restyle by role ({role: {attribute: value}}), or a list of such dicts
        merged in order, so a house style is styles=[HOUSE, {...}]. See SPCResult.plot.
    x_log, x_range, y_range, show_legend, width, height : display; also overridable
        per call in result.plot(...).

    Returns
    -------
    FunnelResult with .data, .summary, .plot(), and .limits() (the contours at any
    denominators, for drawing elsewhere).

    Example: length of stay from stay-level rows
    --------------------------------------------
        stays = session.sql(
            "SELECT provider_id, provider_name, los_days, expected_los_days "
            "FROM inpatient_stays WHERE discharge_date >= '2026-01-01'"
        ).to_pandas()
        r = funnel(stays, y="LOS_DAYS", n="EXPECTED_LOS_DAYS", measure="oe",
                   unit="PROVIDER_ID", label="PROVIDER_NAME",
                   within_dispersion="estimate", worse="higher")
        r.summary["within_dispersion"]       # φ̂, e.g. 6.8
        flagged = r.data[r.data.signal != "none"]

    Example: an HCAHPS composite from survey-level rows
    ---------------------------------------------------
        surveys = session.sql(
            "SELECT survey_id, physician_id, "
            "SUM(IFF(answer = 'Always', 1, 0)) AS always, COUNT(answer) AS answered "
            "FROM hcahps_doctor_items GROUP BY survey_id, physician_id"
        ).to_pandas()
        r = funnel(surveys, y="ALWAYS", n="ANSWERED", measure="proportion",
                   unit="PHYSICIAN_ID", within_dispersion="estimate",
                   worse="lower", signal="fdr")
        r.summary["within_dispersion"]       # design effect, e.g. 2.4
    """
    _check_choice("measure", measure, VALID_MEASURES)
    _check_choice("worse", worse, VALID_WORSE)
    _check_choice("signal", signal, VALID_SIGNALS)
    if label_signals not in (None, "outlier", "alert", "both"):
        raise ValueError(
            f"label_signals must be None, 'outlier', 'alert' or 'both', got {label_signals!r}."
        )
    _check_choice("tau_method", tau_method, TAU_METHODS)
    tau_fixed = _tau_fixed(tau, facets, overdispersion)
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
    if test_min_expected is not None and not (
        isinstance(test_min_expected, (int, float)) and not isinstance(test_min_expected, bool)
        and math.isfinite(test_min_expected) and test_min_expected >= 0
    ):
        raise ValueError(
            f"test_min_expected must be None or a number >= 0, got {test_min_expected!r}."
        )
    extra = {_CASES: cases, _SS: sum_sq, _MAXY: max_case_y, _MAXN: max_case_n}
    phi_column = (
        within_dispersion
        if isinstance(within_dispersion, str) and within_dispersion != "estimate" else None
    )
    if phi_column is not None:
        extra[_PHI] = phi_column
    frame, hover_names = _normalize(data, y, n, unit, label, hover, facets, exclude, extra)
    if isinstance(tau_fixed, dict):
        missing = [fv for fv in frame[facets].unique() if fv not in tau_fixed]
        if missing:
            raise ValueError(
                f"tau= as a dict needs one value per facet; missing {missing!r}."
            )
    aggregated = cases is not None
    if aggregated:
        _check_aggregated(frame, facets)

    source = "default"
    phi: Any = within_dispersion
    if phi_column is not None:
        phi_i = _unit_phi(frame, facets, phi_column)
        # The model sees y/φᵢ out of n/φᵢ; the public columns are restored below.
        for col in (_Y, _N, _MAXY, _MAXN):
            if col in frame.columns:
                frame[col] = frame[col] / frame[_PHI]
        phi, source = 1.0, "column"
    elif isinstance(within_dispersion, str):
        phi = _estimate_within(frame, facets, measure, aggregated)
        source = "estimated"
    elif within_dispersion != 1.0:
        source = "supplied"
    check = _within_check(frame, facets, measure, aggregated) if source == "default" else None

    from .api import _qic

    chart = _CHARTS[measure][1 if overdispersion else 0]
    if xlab is None:
        xlab = _default_xlab(measure, n)
        if phi_column is not None:
            xlab = f"Effective {xlab} ({xlab} / {phi_column})"
    spc = _qic(
        data=frame, x=_UNIT, y=_Y, n=_N, chart=chart, funnel=True, facets=facets,
        point_labels=_LABEL if _LABEL in frame.columns else None,
        hover_extra=hover_names or None,
        exclude=_EXCL if _EXCL in frame.columns else None,
        cl=center, multiply=multiply,
        signal_side=_SIDES[worse], signal_method=signal,
        levels=tuple(limits), fdr_levels=tuple(fdr_levels), within_dispersion=phi,
        within_check=check, tau_method=tau_method, tau_fixed=tau_fixed,
        test_min_expected=test_min_expected,
        title=title, subtitle=subtitle, caption=caption,
        ylab=ylab if ylab is not None else _default_ylab(measure, y, n, multiply),
        xlab=xlab,
        label_signals={"alert": "warn"}.get(label_signals, label_signals),
        styles=styles, x_log=x_log, x_range=x_range, y_range=y_range,
        show_legend=show_legend, width=width, height=height,
        show_95=True, show_labels=False,
        y_percent=measure == "proportion" and multiply == 1.0,
    )
    settings = {
        "measure": measure, "overdispersion": bool(overdispersion), "worse": worse,
        "signal": signal, "limits": tuple(limits), "fdr_levels": tuple(fdr_levels),
        "within_dispersion_source": source, "tau_method": tau_method, "tau": tau,
        "test_min_expected": test_min_expected,
    }
    out = _public_data(spc.data, hover_names, multiply)
    if phi_column is not None:
        out = _restore_units(out, phi_i, facets)
    out = _add_shrinkage(out, spc, settings, phi if phi_column is None else None, multiply)
    out = _add_robustness(out, spc, settings, frame, facets, aggregated, phi_column)
    summary = _public_summary(spc, settings, facets, out)
    if phi_column is not None:
        _column_phi_summary(summary, out, facets)
    return FunnelResult(data=out, summary=summary, _spc=spc)


@dataclass(frozen=True)
class FunnelResult:
    """
    What funnel() returns. data: one row per provider (see funnel's docstring for
    every column). summary: the model, tier counts, expected_false_flags and notes.
    plot(**overrides) draws it; limits(n=None) gives the contours at any denominators.
    print(result) describes it in a few sentences.
    """

    data: pd.DataFrame
    summary: dict[str, Any]
    _spc: SPCResult = field(repr=False)

    def plot(self, **overrides: Any) -> go.Figure:
        """
        A Plotly figure. Any display argument of funnel() can be overridden here
        (title, xlab, ylab, styles, x_log, x_range, y_range, show_legend, label_signals,
        width, height, ...); an unknown name raises TypeError.
        """
        if "label_signals" in overrides:
            overrides["label_signals"] = {"alert": "warn"}.get(
                overrides["label_signals"], overrides["label_signals"]
            )
        text = {k: overrides.pop(k) for k in ("title", "subtitle", "caption", "xlab", "ylab")
                if k in overrides}
        spc = dataclasses.replace(self._spc, **text) if text else self._spc
        return spc.plot(**overrides)

    def limits(self, n: Any = None) -> pd.DataFrame:
        """
        The contours at any denominators: columns denominator, cl, lower_outlier,
        upper_outlier, lower_alert, upper_alert (on the plotted y scale), plus facet on a
        faceted result. n=None gives the grid the plot draws, which passes through
        every provider's own limits.
        """
        frame = self._spc.funnel_limits(n).rename(columns={
            "n": "denominator", "lcl": "lower_outlier", "ucl": "upper_outlier",
            "lcl_95": "lower_alert", "ucl_95": "upper_alert",
        })
        order = ["denominator", "cl", "lower_outlier", "upper_outlier", "lower_alert",
                 "upper_alert"]
        return frame[order + [c for c in frame.columns if c not in order]]

    def __str__(self) -> str:
        return _describe(self.summary)


# ---------------------------------------------------------------------------
# Input normalization
# ---------------------------------------------------------------------------

def _check_choice(name: str, value: Any, valid: tuple) -> None:
    if value not in valid:
        raise ValueError(f"{name} must be one of {valid}, got {value!r}.")


def _tau_number(value: Any, where: str) -> float:
    ok = (isinstance(value, (int, float)) and not isinstance(value, bool)
          and math.isfinite(value) and value >= 0)
    if not ok:
        raise ValueError(f"tau={where} must be a number >= 0, got {value!r}.")
    return float(value)


def _tau_fixed(tau: Any, facets: str | None, overdispersion: bool) -> Any:
    """tau= as the engine's τ² (a number, or a dict of τ² per facet), validated."""
    if tau is None:
        return None
    if not overdispersion:
        raise ValueError(
            "tau= needs overdispersion=True: it is the spread the adjusted chart judges "
            "providers against, and the unadjusted chart has none."
        )
    if isinstance(tau, dict):
        if facets is None:
            raise ValueError("tau= as a dict (one value per facet) needs facets=.")
        return {fv: _tau_number(v, f"[{fv!r}]") ** 2 for fv, v in tau.items()}
    return _tau_number(tau, "") ** 2


def _normalize(data, y, n, unit, label, hover, facets, exclude, extra=None):
    """
    One DataFrame with working columns for unit, y, n, label and exclude, whatever
    form the caller used. Rows sharing a unit (and facet) are summed by the engine.
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
        if facets is not None:
            raise ValueError("facets= needs data= (it names a column).")
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
        for name, col in (("y", y), ("n", n), ("unit", unit), ("label", label), ("facets", facets)):
            if col is not None and (not isinstance(col, str) or col not in data.columns):
                raise ValueError(f"{name}= must name a column of data, got {col!r}.")
        frame = pd.DataFrame({_Y: data[y].to_numpy(dtype=float), _N: data[n].to_numpy(dtype=float)},
                             index=data.index)
        if unit is not None:
            frame[_UNIT] = data[unit].to_numpy()
        if label is not None:
            frame[_LABEL] = data[label].to_numpy()
        if facets is not None:
            frame[facets] = data[facets].to_numpy()
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
            frame[_EXCL] = data[exclude].to_numpy(dtype=bool)
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


def _facet_keys(frame: pd.DataFrame, facets: str | None) -> list:
    return [frame[facets], frame[_UNIT]] if facets is not None else [frame[_UNIT]]


def _check_aggregated(frame: pd.DataFrame, facets: str | None) -> None:
    """cases=/sum_sq= rows must be providers: one row each, k ≥ 1, Σy²/n ≥ 0."""
    if frame.groupby(_facet_keys(frame, facets)).size().max() > 1:
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


def _unit_phi(frame: pd.DataFrame, facets: str | None, column: str) -> dict:
    """{(facet value or None, unit): φᵢ} from a within_dispersion column, validated."""
    phi = frame[_PHI].to_numpy(dtype=float)
    if not (np.all(np.isfinite(phi)) and np.all(phi > 0)):
        raise ValueError(
            f"within_dispersion column {column!r} must be a positive, finite number on every "
            "row (each provider's phi_i; 1 means independent counts)."
        )
    keys = _facet_keys(frame, facets)
    if (frame.groupby(keys)[_PHI].nunique() > 1).any():
        raise ValueError(
            f"within_dispersion column {column!r} varies within a provider. It is one phi_i "
            "per provider (SUM(phi_g * e) / SUM(e) over its cases); repeat that value on "
            "each row."
        )
    first = frame.groupby(keys, sort=False)[_PHI].first()
    if facets is None:
        return {(None, u): float(v) for u, v in first.items()}
    return {(fv, u): float(v) for (fv, u), v in first.items()}


def _by_facet(frame: pd.DataFrame, facets: str | None, fn):
    if facets is None:
        return fn(frame)
    return {fv: fn(rows) for fv, rows in frame.groupby(facets, sort=False)}


def _estimate_within(
    frame: pd.DataFrame, facets: str | None, measure: str, aggregated: bool = False,
) -> float | dict:
    """
    within_dispersion="estimate": φ̂ of _row_phi (or _agg_phi from cases=/sum_sq=), one
    value per facet on a faceted call.
    """
    binomial = measure == "proportion"

    def one(rows: pd.DataFrame) -> float:
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

    return _by_facet(frame, facets, one)


# Fewer residual degrees of freedom than this and the rows say little about clumping.
_ROWS_MIN_DF = 30


def _within_check(
    frame: pd.DataFrame, facets: str | None, measure: str, aggregated: bool = False,
):
    """
    (φ̂, p) from case-level rows for the clustering warning, with p the Pearson χ² test
    of φ = 1 on N − K degrees of freedom (Wilson–Hilferty); None where the rows are
    providers, carry fewer than _ROWS_MIN_DF residual degrees of freedom, or are single
    yes/no items, which cannot show clustering. A dict per facet on a faceted call.
    """
    binomial = measure == "proportion"

    def one(rows: pd.DataFrame):
        if binomial and _one_item_per_case(rows, aggregated):
            return None
        found = _agg_phi(rows, binomial) if aggregated else _row_phi(rows, binomial)
        if found is None or found[1] < _ROWS_MIN_DF:
            return None
        phi, df = found
        h = 2.0 / (9.0 * df)
        z = ((max(phi, 0.0)) ** (1.0 / 3.0) - (1.0 - h)) / math.sqrt(h)
        return phi, 0.5 * math.erfc(z / math.sqrt(2.0))

    return _by_facet(frame, facets, one)


def _default_ylab(measure: str, y: Any, n: Any, multiply: float) -> str:
    """"Observed / expected"; else the ratio the columns form, e.g. "deaths / cases"."""
    if measure == "oe":
        return "Observed / expected"
    if not (isinstance(y, str) and isinstance(n, str)):
        return "Proportion" if measure == "proportion" else "Rate"
    if measure == "proportion":
        return f"{y} / {n}"
    per = f"{multiply:g} " if multiply != 1.0 else ""
    return f"{y} per {per}{n}"


def _default_xlab(measure: str, n: Any) -> str:
    if isinstance(n, str):
        return n
    return {"oe": "Expected", "proportion": "Cases", "rate": "Exposure"}[measure]


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _public_data(df: pd.DataFrame, hover_names: list[str], multiply: float) -> pd.DataFrame:
    """The engine's columns, renamed to say what they are and trimmed to what applies."""
    out = pd.DataFrame({"unit": df["x"].to_numpy()})
    if "label" in df.columns:
        out["label"] = df["label"].to_numpy()
    out["y"] = df["y"].to_numpy()
    if "observed" in df.columns:
        out["numerator"] = df["observed"].to_numpy()
        out["denominator"] = df["expected"].to_numpy()
    else:
        out["denominator"] = df["n"].to_numpy()
        out["numerator"] = df["y"].to_numpy() / multiply * out["denominator"].to_numpy()
        out = out[[c for c in out.columns if c != "denominator"] + ["denominator"]]
    # Recovered as y·n, so a whole count can come back a float-noise away from itself.
    num = out["numerator"].to_numpy(dtype=float)
    whole = np.abs(num - np.round(num)) <= 1e-9 * np.maximum(1.0, np.abs(num))
    out["numerator"] = np.where(whole, np.round(num), num)
    out["cl"] = df["cl"].to_numpy()
    out["lower_outlier"] = df["lcl"].to_numpy()
    out["upper_outlier"] = df["ucl"].to_numpy()
    out["lower_alert"] = df["lcl_95"].to_numpy()
    out["upper_alert"] = df["ucl_95"].to_numpy()
    out["p_value"] = df["p_value"].to_numpy()
    out["q_value"] = df["q_value"].to_numpy()
    sigma = df["sigma_signal"].to_numpy(dtype=bool)
    warn = df["warn_signal"].to_numpy(dtype=bool)
    out["signal"] = np.where(sigma, "outlier", np.where(warn, "alert", "none"))
    out["direction"] = np.where(df["y"].to_numpy() >= df["cl"].to_numpy(), "higher", "lower")
    det = "min_detectable_oe" if "min_detectable_oe" in df.columns else "min_detectable"
    out["min_detectable"] = df[det].to_numpy()
    out["ci_lower"] = df["ci_95_lower"].to_numpy()
    out["ci_upper"] = df["ci_95_upper"].to_numpy()
    out["excluded"] = df["excluded"].to_numpy(dtype=bool)
    if "facet" in df.columns:
        out["facet"] = df["facet"].to_numpy()
    for name in hover_names:
        out[name] = df[name].to_numpy()
    return out


def _facet_params(spc: SPCResult) -> dict:
    """{facet value or None: (θ₀, τ², φ)} on the raw scale, as the engine drew them."""
    return {
        fv: (float(p["cl"]), float(p["tau2"]), float(p["within_dispersion"]))
        for fv, p in (spc._funnel or {}).items()
    }


def _rows_of(out: pd.DataFrame, fv) -> np.ndarray:
    if fv is None or "facet" not in out.columns:
        return np.ones(len(out), dtype=bool)
    return (out["facet"] == fv).to_numpy()


def _restore_units(out: pd.DataFrame, phi_i: dict, facets: str | None) -> pd.DataFrame:
    """
    Under a within_dispersion column the engine saw y/φᵢ and n/φᵢ: put numerator and
    denominator back in the caller's units and keep the model's as
    effective_denominator (the plot's x axis).
    """
    fac = out["facet"] if facets is not None else [None] * len(out)
    phi = np.array([phi_i[(fv, u)] for fv, u in zip(fac, out["unit"])], dtype=float)
    out = out.copy()
    eff = out["denominator"].to_numpy(dtype=float)
    num = out["numerator"].to_numpy(dtype=float) * phi
    whole = np.abs(num - np.round(num)) <= 1e-9 * np.maximum(1.0, np.abs(num))
    out["numerator"] = np.where(whole, np.round(num), num)
    out["denominator"] = eff * phi
    out.insert(out.columns.get_loc("denominator") + 1, "effective_denominator", eff)
    return out


def _model_denominator(out: pd.DataFrame, phi: float) -> np.ndarray:
    """The denominator the count model sees: effective_denominator, or n/φ."""
    if "effective_denominator" in out.columns:
        return out["effective_denominator"].to_numpy(dtype=float)
    return out["denominator"].to_numpy(dtype=float) / phi


def _add_shrinkage(out, spc, settings, phi, multiply) -> pd.DataFrame:
    """
    raw_excess, reliability, eb_rate, eb_excess (methods §4.14). The shrinkage weight is
    the exact conjugate posterior mean of the chart's own mixture model, a linear
    (credibility) estimator: Poisson–gamma, B = τ²/(τ² + θ₀/n); beta-binomial,
    B = n/(n + s), s = θ₀(1 − θ₀)/τ² − 1; both on the effective n under
    within_dispersion. B = 0 when τ² = 0: no measured spread, nothing to keep.
    """
    out = out.copy()
    sign = -1.0 if settings["worse"] == "lower" else 1.0
    binomial = settings["measure"] == "proportion"
    cols = {k: np.full(len(out), np.nan) for k in ("raw_excess", "reliability", "eb_rate",
                                                   "eb_excess", "prob_worse")}
    lower = settings["worse"] == "lower"
    for fv, (cl, tau2, phi_f) in _facet_params(spc).items():
        rows = _rows_of(out, fv)
        sub = out[rows]
        num = sub["numerator"].to_numpy(dtype=float)
        den = sub["denominator"].to_numpy(dtype=float)
        n_eff = _model_denominator(sub, phi_f if phi is not None else 1.0)
        with np.errstate(divide="ignore", invalid="ignore"):
            y_raw = num / den
            params = beta_params(cl, tau2) if binomial and tau2 > 0 else None
            if not (tau2 > 0):
                b = np.zeros(len(sub))
            elif params is not None:
                b = n_eff / (n_eff + params[0] + params[1])
            else:
                v0 = (cl * (1.0 - cl) if binomial else cl) / n_eff
                b = tau2 / (tau2 + v0)
            eb = b * y_raw + (1.0 - b) * cl
        cols["raw_excess"][rows] = sign * (num - cl * den)
        cols["reliability"][rows] = b
        cols["eb_rate"][rows] = eb * multiply
        cols["eb_excess"][rows] = sign * (eb - cl) * den
        cols["prob_worse"][rows] = _prob_worse(
            num * n_eff / den, n_eff, cl, tau2, binomial, lower, params,
        )
    for k, v in cols.items():
        out[k] = v
    return out


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


def _worst_order(r: np.ndarray, d: float) -> np.ndarray:
    """Case indices from most to least extreme toward direction d (+1 up, −1 down)."""
    return np.argsort(-d * r, kind="stable")


def _add_robustness(out, spc, settings, frame, facets, aggregated, phi_column) -> pd.DataFrame:
    """
    p_value_drop1, flag_survives_drop1, fragility (methods §4.15). θ₀, τ² and φ stay at
    their full-data values; only the provider's own count and denominator move. Worked
    in the frame's units (already ÷ φᵢ under a within_dispersion column), ÷ the
    chart's scalar φ otherwise, so each recomputed p-value is the engine's own.
    """
    out = out.copy()
    k_out = len(out)
    p_drop = np.full(k_out, np.nan)
    survives = pd.array([pd.NA] * k_out, dtype="boolean")
    fragility = pd.array([pd.NA] * k_out, dtype="Int64")
    family = "binomial" if settings["measure"] == "proportion" else "poisson"
    side = _SIDES[settings["worse"]]
    worse = settings["worse"]
    inner = signal_thresholds(side, settings["limits"])[1]

    for fv, (cl, tau2, phi_f) in _facet_params(spc).items():
        rows = _rows_of(out, fv)
        sub = out[rows]
        fr = frame if fv is None or facets is None else frame[frame[facets] == fv]
        groups = fr.groupby(_UNIT, sort=False)
        case_level = not aggregated and bool((groups.size() > 1).any())
        has_max = aggregated and _MAXY in fr.columns
        if not (case_level or has_max):
            continue
        scale = 1.0 if phi_column is not None else phi_f
        tot_y = groups[_Y].sum()
        tot_n = groups[_N].sum()

        # Still flagged at the alert tier: p below the inner contour's level, or under
        # "fdr" at or below the largest p the Benjamini-Hochberg step accepted.
        fdr = settings["signal"] == "fdr"
        if fdr:
            q = sub["q_value"].to_numpy(dtype=float)
            p = sub["p_value"].to_numpy(dtype=float)
            hit = np.isfinite(q) & (q < settings["fdr_levels"][1])
            cutoff = float(np.max(p[hit])) if hit.any() else -1.0
        else:
            cutoff = inner

        def keeps(pv, cutoff=cutoff, fdr=fdr):
            return pv <= cutoff if fdr else pv < cutoff

        def p_after(units, drop_y, drop_n, cl=cl, tau2=tau2, scale=scale):
            ny = tot_y.loc[units].to_numpy(dtype=float) - drop_y
            nn = tot_n.loc[units].to_numpy(dtype=float) - drop_n
            with np.errstate(divide="ignore", invalid="ignore"):
                ratio = np.where(nn > 0, ny / nn, np.nan)
            pv, _, _ = funnel_p_values(cl, ratio, np.where(nn > 0, nn / scale, np.nan),
                                       tau2, family, side)
            return pv, ratio

        units = sub["unit"].to_numpy()
        excl = sub["excluded"].to_numpy(dtype=bool)
        own = (sub["numerator"].to_numpy(dtype=float)
               - cl * sub["denominator"].to_numpy(dtype=float))
        dirs = np.where(worse == "lower", -1.0, np.where(worse == "higher", 1.0,
                                                         np.where(own >= 0, 1.0, -1.0)))
        if case_level:
            worst_y = np.full(len(sub), np.nan)
            worst_n = np.full(len(sub), np.nan)
            cases_of = {}
            for j, u in enumerate(units):
                g = fr.loc[groups.groups[u]]
                yy, nn = g[_Y].to_numpy(dtype=float), g[_N].to_numpy(dtype=float)
                order = _worst_order(yy - cl * nn, dirs[j])
                cases_of[u] = (yy[order], nn[order])
                if len(yy) > 1:
                    worst_y[j], worst_n[j] = yy[order[0]], nn[order[0]]
        else:
            first = groups[[_MAXY, _MAXN]].first()
            worst_y = first[_MAXY].loc[units].to_numpy(dtype=float)
            worst_n = first[_MAXN].loc[units].to_numpy(dtype=float)
        ok = np.isfinite(worst_y) & np.isfinite(worst_n) & ~excl
        pv, ratio = p_after(units, np.where(ok, worst_y, 0.0), np.where(ok, worst_n, 0.0))
        pv = np.where(ok, pv, np.nan)
        idx = np.flatnonzero(rows)
        p_drop[idx] = pv

        flagged = (sub["signal"].to_numpy() != "none") & ~excl
        same_side = np.sign(ratio - cl) == dirs
        for j in np.flatnonzero(flagged & np.isfinite(pv)).tolist():
            survives[idx[j]] = bool(keeps(pv[j]) and same_side[j])
        if not case_level:
            continue
        for j in np.flatnonzero(flagged).tolist():
            yy, nn = cases_of[units[j]]
            cap = min(len(yy) - 1, _FRAGILITY_MAX)
            if cap < 1:
                continue
            m = np.arange(1, cap + 1)
            cy, cn = np.cumsum(yy)[:cap], np.cumsum(nn)[:cap]
            for lo in range(0, cap, 10):
                sl = slice(lo, min(lo + 10, cap))
                pm, rm = p_after(np.repeat(units[j], sl.stop - sl.start), cy[sl], cn[sl])
                lost = ~(keeps(pm) & (np.sign(rm - cl) == dirs[j]))
                if lost.any():
                    fragility[idx[j]] = int(m[sl][np.argmax(lost)])
                    break
    out["p_value_drop1"] = p_drop
    out["flag_survives_drop1"] = survives
    out["fragility"] = fragility
    return out


def _tier_summary(spc_summary: dict, settings: dict, data: pd.DataFrame) -> dict[str, Any]:
    """The reader-facing keys for one chart (one facet)."""
    counted = data[~data["excluded"]]
    k = int(spc_summary.get("n_tested", len(counted)))
    n_outlier = int((counted["signal"] == "outlier").sum())
    n_alert = int((counted["signal"] == "alert").sum())
    if settings["signal"] == "limits":
        outer, inner = signal_thresholds(_SIDES[settings["worse"]], settings["limits"])
        expected = {"outlier": k * outer, "alert": k * (inner - outer)}
    else:
        q0, q1 = settings["fdr_levels"]
        expected = {"outlier": q0 * n_outlier, "alert": q1 * (n_outlier + n_alert)}
    out: dict[str, Any] = {
        "n_providers": int(len(data)),
        "n_tested": k,
        "n_outlier": n_outlier,
        "n_alert": n_alert,
        "expected_false_flags": {t: round(v, 2) for t, v in expected.items()},
        "center": spc_summary.get("cl"),
        "tau": spc_summary.get("dispersion_tau"),
        "count_model": spc_summary.get("count_model"),
        "p_value_method": spc_summary.get("p_value_method"),
        "dispersion_shape": spc_summary.get("dispersion_shape"),
        "within_dispersion_hint": spc_summary.get("within_dispersion_hint"),
        "within_dispersion_hint_source": spc_summary.get("within_dispersion_hint_source"),
        "underpowered": spc_summary.get("underpowered"),
        "n_underpowered": spc_summary.get("n_underpowered"),
    }
    out["within_dispersion"] = spc_summary.get("within_dispersion", 1.0)
    out["tau_method"] = settings["tau_method"]
    out["tau_source"] = spc_summary.get("tau_source", "estimated")
    out["tau_estimated"] = spc_summary.get("dispersion_tau_estimated", out["tau"])
    ci = spc_summary.get("dispersion_tau_ci")
    out["tau_ci"] = tuple(float(c) for c in ci) if ci is not None else None
    phi = spc_summary.get("dispersion_phi")
    out["phi_raw"] = spc_summary.get("dispersion_phi_raw", phi)
    out["phi_debiased"] = phi if spc_summary.get("dispersion_debiased") else math.nan
    out["n_filtered"] = int(spc_summary.get("n_filtered", 0))
    frag = counted["fragility"] if "fragility" in counted.columns else pd.Series(dtype="Int64")
    out["n_fragile"] = int((frag == 1).sum())
    out["notes"] = [
        spc_summary[key] for key in ("dispersion_shape_note", "power_note", "dispersion_note")
        if spc_summary.get(key)
    ]
    if out["n_fragile"]:
        note = (
            f"{out['n_fragile']} flagged provider(s) stop flagging when their single most "
            f"extreme case is removed (fragility = 1): review that case before acting."
        )
        if settings["measure"] != "proportion" and out["within_dispersion"] == 1.0:
            note += (
                " On event counts every event is one patient, so at low volume this is "
                "expected and is not by itself a data problem."
            )
        out["notes"].append(note)
    adjusted = settings["overdispersion"]
    if adjusted and out["tau_source"] == "estimated" and 0 < k < 30:
        out["notes"].append(
            f"With {k} providers the spread between them (tau = "
            f"{(out['tau'] or 0.0):.3g}) is imprecise, and the default estimator tends "
            f"to overstate it when there is no real spread. Consider a pre-specified "
            f"tau= estimated from earlier periods."
        )
    est, fixed = out["tau_estimated"], out["tau"]
    if (adjusted and out["tau_source"] == "pre-specified" and fixed and est is not None
            and not (fixed / 1.5 <= est <= fixed * 1.5)):
        out["notes"].append(
            f"The pre-specified tau = {fixed:.3g} differs from this period's estimate, "
            f"{est:.3g}, by more than 1.5-fold: the spread between providers may have "
            f"changed since tau was set. Review it before relying on these limits."
        )
    if out["n_filtered"]:
        out["notes"].append(
            f"{out['n_filtered']} provider(s) below test_min_expected = "
            f"{settings['test_min_expected']:g} were left out of the false discovery rate "
            f"step: they keep a p-value but have no q-value."
        )
    return out


def _public_summary(
    spc: SPCResult, settings: dict, facets: str | None, data: pd.DataFrame,
) -> dict[str, Any]:
    if facets is None:
        body = _tier_summary({**spc.summary, "cl": float(spc.data["cl"].iloc[0])}, settings, data)
        return {**settings, **body}
    by_facet = {}
    for fv, sub in spc.summary["by_facet"].items():
        rows = data[data["facet"].astype(str) == fv]
        cl = float(rows["cl"].iloc[0]) if len(rows) else math.nan
        by_facet[fv] = _tier_summary({**sub, "cl": cl}, settings, rows.reset_index(drop=True))
    totals = {
        key: sum(f[key] for f in by_facet.values())
        for key in ("n_providers", "n_tested", "n_outlier", "n_alert", "n_filtered", "n_fragile")
    }
    notes = [f"{fv}: {note}" for fv, f in by_facet.items() for note in f["notes"]]
    return {**settings, **totals, "by_facet": by_facet, "notes": notes}


def _column_phi_summary(summary: dict, out: pd.DataFrame, facets: str | None) -> None:
    """within_dispersion under a column: the volume-weighted φ̄ = Σn / Σ(n/φᵢ)."""
    def mean_phi(rows):
        eff = rows["effective_denominator"].sum()
        return float(rows["denominator"].sum() / eff) if eff > 0 else math.nan

    if facets is None:
        summary["within_dispersion"] = mean_phi(out)
        return
    for fv, f in summary["by_facet"].items():
        f["within_dispersion"] = mean_phi(out[out["facet"].astype(str) == fv])


def _describe(summary: dict) -> str:
    """print(result): what was compared, what flagged, and what a reader must know."""
    rule = (
        f"exact test, outlier beyond the {summary['limits'][0] * 100:g}% contour, alert "
        f"beyond {summary['limits'][1] * 100:g}%"
        if summary["signal"] == "limits"
        else f"false discovery rate, outlier q < {summary['fdr_levels'][0]:g}, "
             f"alert q < {summary['fdr_levels'][1]:g}"
    )
    side = f"worse = {summary['worse']}" if summary["worse"] else "both sides flagged"
    lines = [f"Funnel ({summary['measure']}; {rule}; {side})"]

    def counts(s: dict, prefix: str = "") -> str:
        text = (
            f"{prefix}{s['n_providers']} providers: {s['n_outlier']} outlier, "
            f"{s['n_alert']} alert"
        )
        exp = s.get("expected_false_flags")
        if exp:
            word = "expected by chance" if summary["signal"] == "limits" else "at most false"
            text += f" ({word}: {exp['outlier']:g} and {exp['alert']:g})"
        if s.get("tau") is not None and summary["overdispersion"]:
            text += f"; spread between providers tau = {s['tau']:.3g}"
        if s.get("within_dispersion", 1.0) != 1.0:
            text += f"; within_dispersion = {s['within_dispersion']:.3g}"
        return text

    if "by_facet" in summary:
        for fv, s in summary["by_facet"].items():
            lines.append(counts(s, f"  {fv}: "))
    else:
        lines.append(counts(summary))
    lines += [f"Note: {note}" for note in summary["notes"]]
    return "\n".join(lines)
