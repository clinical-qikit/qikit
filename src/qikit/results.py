"""
results.py — what qic(), funnel(), paretochart() and bchart() return.

Each result is a frozen dataclass whose .data is a plain DataFrame (one row per point
or provider, ready to write back to a table) and whose .summary is a plain dict. The
figure is drawn on demand by .plot(), which is the only place plotly is imported.
"""

from __future__ import annotations

import datetime
import decimal
import json
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from .schema import FUNNEL_COLUMNS, QIC_COLUMNS, fixed_table

if TYPE_CHECKING:
    import plotly.graph_objects as go

# Geometric steps between a funnel's smallest and largest denominator for its contours;
# every provider's own denominator is added, so each curve passes through the limit that
# decided that provider's signal.
_GRID_STEPS = 200


def _require_plotly() -> None:
    """Figures need plotly, an optional extra so that analysis alone installs less."""
    try:
        import plotly  # noqa: F401
    except ImportError as err:
        raise ImportError(
            "Drawing a figure needs plotly: pip install 'clinical-qikit[plot]'. The "
            "analysis itself (.data, .summary) does not."
        ) from err


def _plain(v: Any) -> Any:
    """A JSON-safe value: NaN and NA become None, numpy scalars plain Python."""
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if v is None or v is pd.NA:
        return None
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return None if math.isnan(v) else float(v)
    if isinstance(v, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(v).isoformat())
    if isinstance(v, datetime.date):          # Snowpark returns DATE columns as these
        return v.isoformat()
    if isinstance(v, decimal.Decimal):        # and NUMBER columns as these
        return int(v) if v == v.to_integral_value() else float(v)
    return v


def _round(v: Any, digits: int | None) -> Any:
    """v with every float at `digits` significant figures, through dicts and lists."""
    if digits is None:
        return v
    if isinstance(v, dict):
        return {k: _round(x, digits) for k, x in v.items()}
    if isinstance(v, list):
        return [_round(x, digits) for x in v]
    if isinstance(v, float) and v and math.isfinite(v):
        return round(v, digits - 1 - math.floor(math.log10(abs(v))))
    return v


def _records(frame: pd.DataFrame, digits: int | None = None, sparse: bool = False) -> list[dict]:
    """One JSON-safe dict per row; sparse leaves out the keys with no value."""
    rows = [{k: _round(_plain(v), digits) for k, v in row.items()}
            for row in frame.to_dict(orient="records")]
    if sparse:
        rows = [{k: v for k, v in row.items() if v is not None} for row in rows]
    return rows


def _flat(summary: dict) -> dict:
    """A summary as one table row: nested dicts spread into prefixed keys, notes joined."""
    out: dict[str, Any] = {}
    for key, value in summary.items():
        if key in ("by_facet", "parts"):
            continue
        if key == "notes":
            out[key] = " | ".join(value)
        elif isinstance(value, dict):
            out.update({f"{key}_{k}": _plain(v) for k, v in value.items()
                        if not isinstance(v, (dict, list, tuple))})
        elif isinstance(value, (list, tuple)):
            out[key] = json.dumps(_plain(value))
        else:
            out[key] = _plain(value)
    return out


class _Serializable:
    data: pd.DataFrame
    summary: dict[str, Any]

    def to_dict(self, digits: int | None = None) -> dict[str, Any]:
        """
        {"data": [one dict per row], "summary": {...}}, JSON-safe (NaN becomes None).
        digits=4 rounds every number to 4 significant figures, for a smaller payload.
        """
        return {"data": _records(self.data, digits),
                "summary": _round(_plain(self.summary), digits)}

    def to_json(self, digits: int | None = None) -> str:
        return json.dumps(self.to_dict(digits))

    def facet_summary(self) -> pd.DataFrame:
        """
        The summary as a table: one row per facet (one row when there are none), the
        facet columns first, with the same columns either way. Nested values are spread
        into prefixed columns (expected_false_flags_outlier) and notes joined with " | ".
        """
        s = self.summary
        facets = getattr(self, "_meta", {}).get("facets", [])
        if "by_facet" not in s:
            return pd.DataFrame([_flat(s)])
        top = {k: v for k, v in s.items() if k != "notes"}
        rows = []
        for key in self.data[facets].drop_duplicates().itertuples(index=False, name=None):
            facet = s["by_facet"][" / ".join(str(v) for v in key)]
            rows.append({**dict(zip(facets, key)), **_flat({**top, **facet})})
        return pd.DataFrame(rows)


@dataclass(frozen=True)
class SPCResult(_Serializable):
    """
    What qic() returns. data: one row per point (qic's docstring lists every column);
    summary: what the rules found and how the limits were set. plot(**options) draws it.
    """

    data: pd.DataFrame
    summary: dict[str, Any]
    chart: str
    method: str
    _meta: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def signals(self) -> bool:
        """Whether any point is an outlier or any rule found a pattern."""
        return bool(self.summary.get("signals"))

    def plot(self, **options: Any) -> "go.Figure":
        """
        A Plotly figure. Options: title, subtitle, caption, xlab, ylab, show_95,
        show_labels, show_grid, show_x_labels, label_signals ("outlier"), runs_highlight
        ("localized", "all", "none"), styles (restyle by role), x_range, y_range, x_order,
        x_format, x_angle, y_percent, y_neg, y_expand, decimals, point_size, connect,
        show_legend, flip, width, height, and nrow, ncol, scales for facets.
        An unknown name raises TypeError.
        """
        _require_plotly()
        from .plot.charts import plot_spc

        return plot_spc(self, **options)

    def to_table(self) -> pd.DataFrame:
        """
        .data with every column of qikit.schema("qic"), in that order and with those
        types, empty where this call did not produce it: the facets= columns, the schema
        columns, then the hover= columns. The same shape for every call with the same
        facets= and hover=, as a table or a Snowpark RETURNS TABLE clause needs.
        """
        return fixed_table(self.data, QIC_COLUMNS, self._meta.get("facets", []),
                           self._meta.get("hover", []))

    def brief(self, digits: int = 4, limit: int = 25) -> dict[str, Any]:
        """
        What was found, small enough to read or to hand to a language model: the
        verdict, the notes, and only the flagged points (an outlier, or part of a run),
        the most recent `limit` of them, with numbers at `digits` significant figures.
        JSON-safe. Faceted, "facets" gives each chart's verdict.
        """
        s, d = self.summary, self.data
        flagged = d[(d["signal"] != "none") | d["runs_signal"]]
        cols = [c for c in (*self._meta.get("facets", []), "x", "label", "y", "cl", "lcl",
                            "ucl", "signal", "runs_signal", "variation") if c in d]
        out: dict[str, Any] = {
            "function": "qic", "chart": self.chart, "method": self.method,
            "signals": self.signals, "provisional": bool(s.get("provisional", False)),
            "n_points": int(len(d)), "n_outlier": int(s.get("n_outlier", 0)),
            "runs_signal": bool(s.get("runs_signal", False)),
            "n_flagged": int(len(flagged)),
            "flagged": _records(flagged[cols].tail(limit), digits, sparse=True),
            "notes": list(s.get("notes", [])),
        }
        for key in ("variation", "assurance"):
            if s.get(key):
                out[key] = s[key]
        if "by_facet" in s:
            out["facets"] = {
                name: {k: _plain(f[k]) for k in ("signals", "n_outlier", "runs_signal",
                                                 "provisional", "variation", "assurance")
                       if f.get(k) is not None}
                for name, f in s["by_facet"].items()}
        return out

    def __repr__(self) -> str:
        sig = "signals" if self.signals else "no signal"
        return f"SPCResult(chart={self.chart!r}, method={self.method!r}, n={len(self.data)}, {sig})"

    def __str__(self) -> str:
        s = self.summary
        lines = [f"{self.chart} chart, {s.get('n_obs', len(self.data))} points, "
                 f"rules: {self.method}"]

        def one(p: dict, prefix: str = "") -> str:
            text = f"{prefix}{p.get('n_outlier', 0)} beyond the limits"
            if "longest_run" in p:
                text += (f"; longest run {p['longest_run']} (more than "
                         f"{p['longest_run_max']} signals); {p['n_crossings']} crossings "
                         f"(fewer than {p['n_crossings_min']} signals)")
            elif p.get("rules_fired"):
                text += "; rules fired: " + ", ".join(p["rules_fired"])
            if p.get("variation"):
                text += f"; latest point: {p['variation']}"
            if p.get("assurance"):
                text += f"; assurance: {p['assurance']}"
            return text

        if "by_facet" in s:
            lines += [one(f, f"  {k}: ") for k, f in s["by_facet"].items()]
        else:
            lines.append(one(s))
        if self.signals:
            lines.append("Signal.")
        elif s.get("provisional"):
            lines.append("No signal so far, with too few points to call the process stable.")
        else:
            lines.append("No signal: the process looks stable.")
        lines += [f"Note: {note}" for note in s.get("notes", [])]
        return "\n".join(lines)


@dataclass(frozen=True)
class FunnelResult(_Serializable):
    """
    What funnel() returns. data: one row per provider (funnel's docstring lists every
    column); summary: the model, tier counts, expected_false_flags and notes.
    plot(**options) draws it; limits(n=None) gives the contours at any denominators;
    min_denominator(reliability=0.7) gives the minimum denominator (minimum volume) at
    which a provider's score is reliable, and how many providers are above and below
    it; print(result) describes it in a few sentences.
    """

    data: pd.DataFrame
    summary: dict[str, Any]
    _models: dict[Any, dict[str, Any]] = field(default_factory=dict, repr=False)
    _meta: dict[str, Any] = field(default_factory=dict, repr=False)
    # The default contour grid, drawn once: plotting twice reuses it.
    _grid: dict[str, pd.DataFrame] = field(default_factory=dict, repr=False, compare=False)

    def plot(self, kind: str = "funnel", **options: Any) -> "go.Figure":
        """
        A Plotly figure against each provider's volume. Options: title, subtitle,
        caption, xlab, ylab, label_signals ("outlier", "alert", "both"), styles (restyle
        by role), x_log, x_range, y_range, show_legend, show_x_labels, width, height, and
        nrow, ncol, scales for facets. An unset caption states the flag rule.

        color_by="fdr" colors the points by their q-value tiers (fdr_levels) on a
        signal="limits" result, leaving its signal column and the drawn limits as they
        are; fdr_watch=0.20 adds a pale watch tier for q below it.

        kind="caterpillar" draws the shrunk estimates instead: one row per provider
        sorted by eb_rate, the eb_low–eb_high interval as a bar colored by
        estimate_flag, the raw value as a faint open circle, and the reference as a
        dotted line. Its options: title, subtitle, caption, xlab, ylab, top= and
        bottom= (keep the N highest and lowest per panel), label_flagged (None names
        every row up to 60 per panel and only flagged ones beyond; False names all),
        show_legend, width, height, styles (roles worse, better, higher, lower,
        no_different, raw, reference).
        """
        _require_plotly()
        from .plot.charts import plot_caterpillar, plot_funnel

        if kind == "caterpillar":
            return plot_caterpillar(self, **options)
        if kind != "funnel":
            raise ValueError(f"kind must be 'funnel' or 'caterpillar', got {kind!r}.")
        return plot_funnel(self, **options)

    def to_table(self) -> pd.DataFrame:
        """
        .data with every column of qikit.schema("funnel"), in that order and with those
        types, empty where this call did not produce it: the facets= columns, the schema
        columns, then the hover= columns. The same shape for every call with the same
        facets= and hover=, as a table or a Snowpark RETURNS TABLE clause needs.
        """
        return fixed_table(self.data, FUNNEL_COLUMNS, self._meta.get("facets", []),
                           self._meta.get("hover", []))

    def brief(self, digits: int = 4, limit: int = 25) -> dict[str, Any]:
        """
        What was found, small enough to read or to hand to a language model: the
        question asked, the counts, the notes, and only the flagged providers (outliers
        first, then by p-value; at most `limit`), with numbers at `digits` significant
        figures. JSON-safe. Faceted, "facets" gives each chart's counts and model.
        """
        s, d = self.summary, self.data
        flagged = d[(d["signal"] != "none") & ~d["excluded"]]
        flagged = flagged.assign(_tier=(flagged["signal"] != "outlier")).sort_values(
            ["_tier", "p_value"], kind="stable")
        cols = [c for c in (*self._meta.get("facets", []), "unit", "label", "y",
                            "denominator", "cl", "signal", "direction", "p_value", "q_value",
                            "eb_rate", "prob_worse", "estimate_flag", "fragility") if c in d]
        model = ("center", "tau", "underpowered", "expected_false_flags")
        out: dict[str, Any] = {
            "function": "funnel",
            **{k: _plain(s.get(k)) for k in ("measure", "compare_to", "signal", "worse",
                                              "n_providers", "n_tested", "n_outlier",
                                              "n_alert")},
            **{k: _round(_plain(s[k]), digits) for k in model if s.get(k) is not None},
            "n_flagged": int(len(flagged)),
            "flagged": _records(flagged[cols].head(limit), digits, sparse=True),
            "notes": list(s.get("notes", [])),
        }
        if "by_facet" in s:
            out["facets"] = {
                name: {k: _round(_plain(f[k]), digits)
                       for k in ("n_providers", "n_outlier", "n_alert", *model)
                       if f.get(k) is not None}
                for name, f in s["by_facet"].items()}
        return out

    def limits(self, n: Any = None) -> pd.DataFrame:
        """
        The contours at any denominators: columns denominator, cl, lower_outlier,
        upper_outlier, lower_alert, upper_alert (on the plotted y scale), plus the facet
        columns. n=None gives the grid the plot draws, which passes through every
        provider's own limits. Under a within_dispersion column the denominator is the
        effective one, the plot's x axis.
        """
        if n is None and "default" in self._grid:
            return self._grid["default"].copy()
        from .core.contours import funnel_contours

        frames = []
        facets = self._meta.get("facets", [])
        for name, model in self._models.items():
            if n is not None:
                grid = np.asarray(n, dtype=float)
            else:
                grid = _funnel_grid(model["axis"], model["family"] == "binomial")
            phi = model["phi"]
            n_model = grid if phi in (None, 1.0) else grid / phi
            lim = funnel_contours(model["family"], model["cl"], n_model, model["tau2"],
                                  model["levels"], model["limit_method"], model["scale"])
            m = model["multiply"]
            frame = pd.DataFrame({
                "denominator": grid, "cl": np.full(len(grid), model["cl"] * m),
                "lower_outlier": lim.lcl * m, "upper_outlier": lim.ucl * m,
                "lower_alert": lim.lcl_95 * m, "upper_alert": lim.ucl_95 * m,
            })
            for i, col in enumerate(facets):
                frame.insert(i, col, model["key"][i])
            frames.append(frame)
        out = pd.concat(frames, ignore_index=True)
        if n is None:
            self._grid["default"] = out
        return out.copy()

    def min_denominator(self, reliability: Any = 0.7) -> pd.DataFrame:
        """
        The minimum denominator for this measure: the volume (minimum sample size, case
        minimum, small-numbers threshold) at which a provider's score reaches a
        reliability target, and how many providers are above and below it.

        Reliability is the share of a provider's difference from the center that is real
        rather than chance, the `reliability` column (methods §4.14). It rises with the
        denominator as n/(n + k), so each target has one floor: a provider is at or above
        the floor exactly when its reliability is at or above the target.

        reliability : the target, or several, each between 0 and 1. It is a judgment
            about the use, not a statistical result, so ask whoever owns the decision:
            0.7 is the usual floor for high-stakes profiling (public reporting, pay,
            credentialing; Adams et al. 2010), 0.9 for decisions about one provider,
            0.5 for internal screening that is reviewed before anyone acts.

        Returns one row per target (per facet under facets=), the facet columns first:

        - reliability: the target.
        - min_denominator: the floor, in the units of n= (denominator_unit says which:
          expected events for O/E, cases for proportions and means, exposure for
          rates). Round it up. Empty when no floor exists; note says why.
        - min_low, min_high: its range from the 95% interval for the spread between
          providers. min_high is inf when the data cannot rule out no spread. Empty when
          tau= was given.
        - n_providers, n_above, n_below: providers compared, how many are at or above
          the floor, and how many are below it. share_above is n_above / n_providers.
        - volume_above, volume_below, share_volume_above: the denominator they hold.
        - center, tau: the model the floor comes from: the center of the estimates'
          prior and the spread between providers around it (summary["estimate_tau"]).
        - note: the row as one sentence to show a reader.

        .attrs["notes"] lists cautions for the whole table: few providers (the floor is
        imprecise, show the range), or no measurable spread (no volume makes a score
        reliable; compare within a larger peer group, pass tau= from earlier periods, or
        report at a higher level: funnel_rollup() compares levels).

        Under a within_dispersion column the floor is in effective denominators
        (denominator / phi), the plot's x axis. Excluded providers are not counted.
        Which providers are below the floor: result.data["reliability"] < target.
        """
        from .core.shrinkage import min_denominator as floor_at

        several = isinstance(reliability, (list, tuple, np.ndarray, pd.Series))
        targets = list(reliability) if several else [reliability]
        for r in targets:
            ok = (isinstance(r, (int, float, np.integer, np.floating))
                  and not isinstance(r, bool) and 0.0 < float(r) < 1.0)
            if not ok:
                raise ValueError(
                    f"reliability= must be a number between 0 and 1 (not 0 or 1), or a "
                    f"list of them, e.g. 0.7 or [0.5, 0.7, 0.9]. Got {reliability!r}.")
        if not targets:
            raise ValueError("reliability= needs at least one target, e.g. 0.7.")
        facets = self._meta.get("facets", [])
        measure = self._meta.get("measure")
        unit_name = {"oe": "expected events", "rate": "exposure"}.get(str(measure), "cases")
        if self._meta.get("n_name"):
            unit_name += f" ({self._meta['n_name']})"
        no_prior = (not self.summary.get("overdispersion")
                    and self.summary.get("compare_to") != "model")
        d = self.data
        rows, notes = [], []
        for name, model in self._models.items():
            prior, phi = model["prior"], model["phi"]
            part = d
            for col, val in zip(facets, model["key"]):
                part = part[part[col].isna() if pd.isna(val) else part[col] == val]
            effective = phi is None
            den = part["effective_denominator" if effective else "denominator"]
            den = den[~part["excluded"].to_numpy(dtype=bool)].to_numpy(dtype=float)
            den = den[np.isfinite(den) & (den > 0)]
            k, volume = int(len(den)), float(den.sum())
            scale = 1.0 if effective else float(phi)
            unit = ("effective " if effective else "") + unit_name
            has_floor = prior.tau2 > 0
            prefix = f"{name}: " if name is not None else ""
            if no_prior:
                why = ("this chart allows no spread between providers "
                       "(overdispersion=False), so it has no reliability to reach; use "
                       "overdispersion=True or compare_to='model'")
            elif not has_floor:
                why = ("the data show no measurable spread between providers (tau = 0), "
                       "so no volume makes a score reliable at this level")
            else:
                why = ""
            if why:
                notes.append(prefix + "No minimum denominator: " + why + ".")
            elif prior.tau_ci is None:
                notes.append(prefix + "tau= was given, so the minimum denominator has no "
                             "range: it is exactly as certain as that tau.")
            elif prior.tau_ci[0] == 0:
                notes.append(
                    f"{prefix}The data cannot rule out no spread between providers "
                    f"(the interval for tau reaches 0), so the minimum denominator has "
                    f"no upper bound: treat it as a lower bound, not a threshold.")
            elif k < 30:
                notes.append(
                    f"{prefix}With {k} providers the spread between them is imprecise, "
                    f"and so is the minimum denominator: report its range (min_low to "
                    f"min_high), not the single number.")
            for r in targets:
                r = float(r)
                floor = floor_at(prior, r) * scale if has_floor else math.nan
                low = high = math.nan
                if prior.tau_ci is not None and not no_prior:
                    lo_t, hi_t = prior.tau_ci
                    low = 0.0 if math.isinf(hi_t) else floor_at(prior, r, hi_t * hi_t) * scale
                    high = floor_at(prior, r, lo_t * lo_t) * scale
                above = den >= floor
                n_above, v_above = int(above.sum()), float(den[above].sum())
                if has_floor:
                    span = "" if math.isnan(low) else (
                        f" (95% range {_volume(low)} to "
                        f"{'no upper bound' if math.isinf(high) else _volume(high)})")
                    note = (f"Reliability {r:g} needs at least {_volume(floor)} {unit}{span}; "
                            f"{n_above} of {k} providers are at or above it and "
                            f"{k - n_above} are below, with "
                            f"{(v_above / volume if volume else 0.0):.0%} of the volume "
                            f"at or above.")
                else:
                    note = f"No minimum denominator: {why}."
                row: dict[str, Any] = dict(zip(facets, model["key"]))
                row.update({
                    "reliability": r, "min_denominator": floor, "min_low": low,
                    "min_high": high, "denominator_unit": unit, "n_providers": k,
                    "n_above": n_above, "n_below": k - n_above,
                    "share_above": n_above / k if k else math.nan,
                    "volume_above": v_above, "volume_below": volume - v_above,
                    "share_volume_above": v_above / volume if volume else math.nan,
                    "center": prior.center * model["multiply"],
                    "tau": math.sqrt(prior.tau2), "note": note,
                })
                rows.append(row)
        out = pd.DataFrame(rows)
        out.attrs["notes"] = notes
        return out

    def __repr__(self) -> str:
        s = self.summary
        return (f"FunnelResult(measure={s.get('measure')!r}, providers={s.get('n_providers')}, "
                f"outliers={s.get('n_outlier')}, alerts={s.get('n_alert')})")

    def __str__(self) -> str:
        return _describe(self.summary)


def _volume(x: float) -> str:
    """A denominator in words: three significant figures, never an exponent."""
    return f"{x:,.0f}" if x >= 100 else f"{x:.3g}"


def _funnel_grid(n_obs: np.ndarray, integer: bool) -> np.ndarray:
    """
    Denominators to draw a funnel's contours at: geometric steps across the observed
    range, merged with every observed n. A binomial chart steps in whole numbers, where
    its limits are exact; between them they are interpolated (docs/methods.md §4.13).
    """
    n_obs = np.asarray(n_obs, dtype=float)
    n_obs = n_obs[np.isfinite(n_obs) & (n_obs > 0)]
    if len(n_obs) == 0:
        return n_obs
    lo, hi = float(n_obs.min()), float(n_obs.max())
    steps = np.geomspace(lo, hi, _GRID_STEPS) if hi > lo else np.array([lo])
    if integer:
        steps = np.round(steps)
    return np.unique(np.concatenate([steps[steps > 0], n_obs]))


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
    asks = {"peers": "; compared with peers", "model": "; compared with the risk model"}
    lines = [f"Funnel ({summary['measure']}; {rule}; {side}"
             f"{asks.get(summary.get('compare_to') or '', '')})"]

    def counts(s: dict, prefix: str = "") -> str:
        text = (
            f"{prefix}{s['n_providers']} providers: {s['n_outlier']} outlier, "
            f"{s['n_alert']} alert"
        )
        exp = s.get("expected_false_flags")
        if exp and summary["signal"] == "limits":
            text += f" (expected by chance: {exp['outlier']:g} and {exp['alert']:g})"
        elif exp:
            text += (f" (at most false: {exp['outlier']:g} outliers, "
                     f"{exp['outlier_or_alert']:g} of outliers and alerts)")
        if s.get("tau") is not None and summary["overdispersion"]:
            scale = s.get("tau_scale", "natural")
            on = "" if scale == "natural" else f" on the {scale} scale"
            text += f"; spread between providers tau = {s['tau']:.3g}{on}"
        if s.get("case_sd") is not None:
            text += f"; one case varies with SD {s['case_sd']:.3g}"
        elif s.get("within_dispersion", 1.0) != 1.0:
            text += f"; within_dispersion = {s['within_dispersion']:.3g}"
        b = s.get("benchmark")
        if b is not None:
            if b["method"] == "abc":
                text += (f"; achievable benchmark (ABC) = {b['value']:.4g} from "
                         f"{b['providers']} providers")
            else:
                text += f"; benchmark (shrunk percentile) = {b['value']:.4g}"
        return text

    if "by_facet" in summary:
        for fv, s in summary["by_facet"].items():
            lines.append(counts(s, f"  {fv}: "))
    else:
        lines.append(counts(summary))
    lines += [f"Note: {note}" for note in summary["notes"]]
    return "\n".join(lines)


@dataclass(frozen=True)
class ParetoResult(_Serializable):
    """What paretochart() returns: categories by count, with the cumulative share."""
    data: pd.DataFrame
    summary: dict[str, Any] = field(default_factory=dict)

    def plot(self, **options: Any) -> "go.Figure":
        _require_plotly()
        from .plot.charts import plot_pareto

        return plot_pareto(self, **options)

    def __repr__(self) -> str:
        return f"ParetoResult(n_categories={len(self.data)})"

    def __str__(self) -> str:
        d = self.data
        lines = [f"Pareto: {int(d['count'].sum())} items in {len(d)} categories"]
        lines += [f"  {row.category}: {row.count} ({row.cum_percent:.0f}% cumulative)"
                  for row in d.head(5).itertuples()]
        if len(d) > 5:
            lines.append(f"  and {len(d) - 5} more")
        return "\n".join(lines)


@dataclass(frozen=True)
class BChartResult(_Serializable):
    """What bchart() returns: the two Bernoulli CUSUMs and where they signalled."""
    data: pd.DataFrame
    summary: dict[str, Any] = field(default_factory=dict)

    def plot(self, **options: Any) -> "go.Figure":
        _require_plotly()
        from .plot.charts import plot_bchart

        return plot_bchart(self, **options)

    def __repr__(self) -> str:
        return f"BChartResult(n_obs={len(self.data)}, target={self.summary.get('target', math.nan):.3f})"

    def __str__(self) -> str:
        s, d = self.summary, self.data
        lines = [f"Bernoulli CUSUM, {len(d)} cases, target probability {s['target']:.3g}, "
                 f"looking for the odds changing {s['or_ratio']:g}-fold"]
        for name, word in (("signal_up", "more"), ("signal_down", "fewer")):
            at = d.loc[d[name], "x"].tolist()
            if at:
                lines.append(f"Signal: {word} events than the target, first at case {at[0]}"
                             + (f" ({len(at)} signals)" if len(at) > 1 else "") + ".")
        if len(lines) == 1:
            lines.append("No signal.")
        return "\n".join(lines)
