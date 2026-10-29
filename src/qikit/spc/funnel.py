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

from .limits import DEFAULT_LEVELS
from .pvalues import signal_thresholds
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
)

# Internal working columns on the normalized frame.
_UNIT, _Y, _N, _LABEL, _EXCL = "__unit", "__y", "__n", "__label", "__exclude"


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
    | a measure where only one direction is bad          | worse="higher" (or "lower")            |
    | hundreds of providers, and want few false alarms   | signal="fdr"                           |

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

    result.summary holds the model and how to read the counts:
    n_outlier, n_alert, expected_false_flags (per tier; see signal=), tau (the spread
    of true values between providers), count_model, within_dispersion and its source,
    dispersion_shape with within_dispersion_hint (and its source: the case "rows" or the
    provider "totals"), underpowered, and notes (a list of sentences to show readers:
    power, over-dispersion, clustered counts). print(result) summarizes it in words.

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
    frame, hover_names = _normalize(data, y, n, unit, label, hover, facets, exclude)

    source = "default"
    phi: Any = within_dispersion
    if isinstance(within_dispersion, str):
        if within_dispersion != "estimate":
            raise ValueError(
                f"within_dispersion must be a number or 'estimate', got {within_dispersion!r}."
            )
        phi = _estimate_within(frame, facets, measure)
        source = "estimated"
    elif within_dispersion != 1.0:
        source = "supplied"
    check = _within_check(frame, facets, measure) if source == "default" else None

    from .api import _qic

    chart = _CHARTS[measure][1 if overdispersion else 0]
    spc = _qic(
        data=frame, x=_UNIT, y=_Y, n=_N, chart=chart, funnel=True, facets=facets,
        point_labels=_LABEL if _LABEL in frame.columns else None,
        hover_extra=hover_names or None,
        exclude=_EXCL if _EXCL in frame.columns else None,
        cl=center, multiply=multiply,
        signal_side=_SIDES[worse], signal_method=signal,
        levels=tuple(limits), fdr_levels=tuple(fdr_levels), within_dispersion=phi,
        within_check=check,
        title=title, subtitle=subtitle, caption=caption,
        ylab=ylab if ylab is not None else _default_ylab(measure, y, n, multiply),
        xlab=xlab if xlab is not None else _default_xlab(measure, n),
        label_signals={"alert": "warn"}.get(label_signals, label_signals),
        styles=styles, x_log=x_log, x_range=x_range, y_range=y_range,
        show_legend=show_legend, width=width, height=height,
        show_95=True, show_labels=False,
        y_percent=measure == "proportion" and multiply == 1.0,
    )
    settings = {
        "measure": measure, "overdispersion": bool(overdispersion), "worse": worse,
        "signal": signal, "limits": tuple(limits), "fdr_levels": tuple(fdr_levels),
        "within_dispersion_source": source,
    }
    return FunnelResult(
        data=_public_data(spc.data, hover_names, multiply),
        summary=_public_summary(spc, settings, facets),
        _spc=spc,
    )


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


def _normalize(data, y, n, unit, label, hover, facets, exclude):
    """
    One DataFrame with working columns for unit, y, n, label and exclude, whatever
    form the caller used. Rows sharing a unit (and facet) are summed by the engine.
    """
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


def _by_facet(frame: pd.DataFrame, facets: str | None, fn):
    if facets is None:
        return fn(frame)
    return {fv: fn(rows) for fv, rows in frame.groupby(facets, sort=False)}


def _estimate_within(frame: pd.DataFrame, facets: str | None, measure: str) -> float | dict:
    """within_dispersion="estimate": φ̂ of _row_phi, one value per facet on a faceted call."""
    binomial = measure == "proportion"

    def one(rows: pd.DataFrame) -> float:
        if binomial and len(rows) and bool(np.all(rows[_N] == 1)):
            raise ValueError(
                "within_dispersion='estimate' found one item per row (every n is 1). A "
                "row that is a single yes/no cannot show clustering, so there is nothing "
                "to estimate. If several rows belong to one case (the questions of one "
                "survey), sum them to one row per case: y = items meeting the measure, "
                "n = items answered. If each row really is one independent case, leave "
                "within_dispersion at 1."
            )
        found = _row_phi(rows, binomial)
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


def _within_check(frame: pd.DataFrame, facets: str | None, measure: str):
    """
    (φ̂, p) from case-level rows for the clustering warning, with p the Pearson χ² test
    of φ = 1 on N − K degrees of freedom (Wilson–Hilferty); None where the rows are
    providers, carry fewer than _ROWS_MIN_DF residual degrees of freedom, or are single
    yes/no items, which cannot show clustering. A dict per facet on a faceted call.
    """
    binomial = measure == "proportion"

    def one(rows: pd.DataFrame):
        if binomial and bool(np.all(rows[_N] == 1)):
            return None
        found = _row_phi(rows, binomial)
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
    out["notes"] = [
        spc_summary[key] for key in ("dispersion_shape_note", "power_note", "dispersion_note")
        if spc_summary.get(key)
    ]
    return out


def _public_summary(spc: SPCResult, settings: dict, facets: str | None) -> dict[str, Any]:
    data = _public_data(spc.data, [], 1.0)
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
        for key in ("n_providers", "n_tested", "n_outlier", "n_alert")
    }
    notes = [f"{fv}: {note}" for fv, f in by_facet.items() for note in f["notes"]]
    return {**settings, **totals, "by_facet": by_facet, "notes": notes}


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
