"""
The public API as a caller sees it: qic(), funnel(), funnel_sensitivity() and their
results. The column lists here are the contract a Snowflake pipeline writes against;
change one only with a CHANGELOG entry.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

import qikit
from qikit import FunnelResult, SPCResult, funnel, funnel_sensitivity, qic

QIC_COLUMNS = ["x", "y", "cl", "ucl", "lcl", "ucl_95", "lcl_95", "signal", "runs_signal",
               "baseline", "excluded"]
FUNNEL_COLUMNS = [
    "unit", "y", "numerator", "denominator", "cl", "lower_outlier", "upper_outlier",
    "lower_alert", "upper_alert", "p_value", "q_value", "signal", "direction",
    "min_detectable", "ci_lower", "ci_upper", "excluded", "raw_excess", "reliability",
    "eb_rate", "eb_excess", "prob_worse", "eb_low", "eb_high", "estimate_flag",
    "p_value_drop1", "flag_survives_drop1", "fragility",
]


# ---------------------------------------------------------------------------
# Package
# ---------------------------------------------------------------------------

def test_import_does_not_load_plotly():
    """A Snowpark UDTF never draws, so the analysis must not need plotly."""
    out = subprocess.run(
        [sys.executable, "-c", "import sys, qikit; qikit.qic(y=[1.0, 2, 3], chart='i'); "
         "qikit.funnel(y=[1, 2], n=[3.0, 4], measure='oe'); print('plotly' in sys.modules)"],
        capture_output=True, text=True, check=True,
    )
    assert out.stdout.strip() == "False"


def test_version_and_exports():
    assert qikit.__version__ == "1.3.0"
    for name in ("qic", "funnel", "funnel_sensitivity", "SPCResult", "FunnelResult"):
        assert name in qikit.__all__


# ---------------------------------------------------------------------------
# qic()
# ---------------------------------------------------------------------------

def _monthly(k=24, seed=1):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "month": pd.date_range("2024-01-01", periods=k, freq="MS"),
        "events": rng.binomial(200, 0.15, k), "cases": 200,
        "los": rng.gamma(4, 1.2, k),
    })


class TestQicTable:
    def test_columns_are_the_contract(self):
        r = qic(_monthly(), x="month", y="los", chart="i")
        assert list(r.data.columns) == QIC_COLUMNS
        assert isinstance(r, SPCResult) and r.chart == "i" and r.method == "anhoej"

    def test_denominator_and_optional_columns(self):
        df = _monthly().assign(note="", goal=0.2, who="unit A")
        df.loc[5, "note"] = "new protocol"
        r = qic(df, x="month", y="events", n="cases", chart="p", notes="note",
                target="goal", label="who", hover="who" if False else None)
        assert {"n", "target", "notes", "label"} <= set(r.data.columns)
        assert r.data["notes"].iloc[5] == "new protocol"

    def test_facets_take_one_or_more_columns_and_stay_in_the_table(self):
        df = pd.concat([_monthly(seed=s).assign(site=site, unit=u)
                        for s, (site, u) in enumerate([("A", "icu"), ("A", "ward"),
                                                       ("B", "icu")])])
        r = qic(df, x="month", y="events", n="cases", chart="p", facets=["site", "unit"])
        assert list(r.data.columns[:2]) == ["site", "unit"]
        assert len(r.data) == 72
        assert set(r.summary["by_facet"]) == {"A / icu", "A / ward", "B / icu"}
        assert r.summary["n_obs"] == 72
        # The table is a plain frame: no working columns leak out.
        assert not any(c.startswith("__") for c in r.data.columns)

    def test_rows_sharing_x_are_aggregated_and_numbers_and_dates_sorted(self):
        df = pd.DataFrame({"m": [3, 1, 2, 1, 3, 2], "e": [1, 2, 3, 4, 5, 6], "n": [10] * 6})
        r = qic(df, x="m", y="e", n="n", chart="p")
        assert r.data["x"].tolist() == [1, 2, 3]
        assert r.data["y"].tolist() == pytest.approx([6 / 20, 9 / 20, 6 / 20])
        text = pd.DataFrame({"m": ["c", "a", "b"], "v": [1.0, 2.0, 3.0]})
        assert qic(text, x="m", y="v", chart="i").data["x"].tolist() == ["c", "a", "b"]

    def test_x_period_buckets_dates(self):
        days = pd.DataFrame({"d": pd.date_range("2024-01-01", periods=90, freq="D"),
                             "e": 1, "n": 10})
        r = qic(days, x="d", y="e", n="n", chart="p", x_period="month")
        assert len(r.data) == 3

    def test_freeze_and_part_end_at_their_point(self):
        y = list(np.r_[np.full(10, 5.0), np.full(10, 9.0)] + np.tile([0.1, -0.1], 10))
        frozen = qic(y=y, chart="i", freeze=10)
        assert frozen.data["cl"].iloc[0] == pytest.approx(5.0)
        assert frozen.data["baseline"].tolist() == [True] * 10 + [False] * 10
        parts = qic(y=y, chart="i", part=10)
        assert parts.data["part"].tolist() == [1] * 10 + [2] * 10
        assert parts.data["cl"].iloc[-1] == pytest.approx(9.0)
        assert len(parts.summary["parts"]) == 2

    def test_exclude_by_column_or_position(self):
        y = [10.0, 10, 50, 10, 10, 11, 9, 10]
        by_pos = qic(y=y, chart="i", exclude=3)
        by_col = qic(pd.DataFrame({"v": y, "bad": [False, False, True] + [False] * 5}),
                     y="v", chart="i", exclude="bad")
        for r in (by_pos, by_col):
            assert r.data["excluded"].tolist()[2] is True
            assert r.data["cl"].iloc[0] == pytest.approx(np.mean([v for i, v in enumerate(y) if i != 2]))
            assert r.data["signal"].iloc[2] == "none"

    def test_multiply_scales_y_and_limits_not_signals(self):
        df = _monthly()
        a = qic(df, x="month", y="events", n="cases", chart="u")
        b = qic(df, x="month", y="events", n="cases", chart="u", multiply=1000)
        assert b.data["ucl"].tolist() == pytest.approx((a.data["ucl"] * 1000).tolist())
        assert b.data["signal"].tolist() == a.data["signal"].tolist()

    @pytest.mark.parametrize("chart", ["run", "i", "mr", "c", "g", "t"])
    def test_every_single_value_chart(self, chart):
        y = list(np.random.default_rng(3).poisson(8, 30).astype(float) + 1)
        r = qic(y=y, chart=chart)
        assert len(r.data) == 30 and set(r.data["signal"]) <= {"outlier", "none"}

    @pytest.mark.parametrize("chart", ["p", "pp", "u", "up"])
    def test_every_rate_chart(self, chart):
        r = qic(_monthly(), x="month", y="events", n="cases", chart=chart)
        assert r.data["cl"].iloc[0] == pytest.approx(r.data["y"].mean())
        if chart in ("pp", "up"):
            assert r.summary["sigma_z"] > 0

    @pytest.mark.parametrize("chart", ["xbar", "s"])
    def test_subgroup_charts(self, chart):
        rng = np.random.default_rng(4)
        df = pd.DataFrame({"week": np.repeat(range(12), 5), "v": rng.normal(10, 1, 60)})
        r = qic(df, x="week", y="v", chart=chart)
        assert r.data["n"].tolist() == [5.0] * 12

    def test_xbar_spread_comes_from_the_baseline_only(self):
        rng = np.random.default_rng(0)
        df = pd.DataFrame({"g": np.repeat(range(20), 5),
                           "v": np.r_[rng.normal(50, 1, 50), rng.normal(50, 10, 50)]})
        full = qic(df, x="g", y="v", chart="xbar")
        frozen = qic(df, x="g", y="v", chart="xbar", freeze=10)
        assert (frozen.data["ucl"] - frozen.data["cl"]).iloc[0] < \
            0.3 * (full.data["ucl"] - full.data["cl"]).iloc[0]

    def test_summary_reads_as_words_and_serializes(self):
        r = qic(_monthly(), x="month", y="events", n="cases", chart="p")
        assert "p chart, 24 points" in str(r)
        d = json.loads(r.to_json())
        assert len(d["data"]) == 24 and d["summary"]["chart"] == "p"
        assert isinstance(d["data"][0]["x"], str)  # dates become ISO text
        assert "SPCResult(chart='p'" in repr(r)


class TestQicValidation:
    @pytest.mark.parametrize("kw,match", [
        (dict(chart="zzz"), "chart must be one of"),
        (dict(chart="oe"), "qikit.funnel"),
        (dict(method="bogus"), "method must be one of"),
        (dict(worse="up"), "worse must be one of"),
        (dict(agg_fun="mode"), "agg_fun must be one of"),
        (dict(freeze=0), "freeze=0 must be between"),
        (dict(freeze=4, part=2), "cannot be combined"),
        (dict(part=[5, 3]), "must increase"),
        (dict(chart="run", method="weco"), "has no limits"),
        (dict(multiply=0), "multiply must be a number > 0"),
    ])
    def test_errors_name_the_fix(self, kw, match):
        with pytest.raises(ValueError, match=match):
            qic(y=[1.0, 2, 3, 4, 5, 6], **kw)

    def test_rate_checks(self):
        with pytest.raises(ValueError, match="needs n="):
            qic(y=[1, 2], chart="p")
        with pytest.raises(ValueError, match="cannot exceed n"):
            qic(y=[1, 12], n=[10, 10], chart="p")
        with pytest.raises(ValueError, match="zero denominator"):
            qic(y=[1, 2], n=[10, 0], chart="u")

    def test_names_clash_with_output_columns(self):
        df = pd.DataFrame({"y": [1.0, 2.0], "signal": ["a", "b"]})
        with pytest.raises(ValueError, match="share a name"):
            qic(df, y="y", chart="i", facets="signal")
        with pytest.raises(ValueError, match="collide"):
            qic(df, y="y", chart="i", hover="signal")

    @pytest.mark.parametrize("old,new", [("cl", "center="), ("point_labels", "label="),
                                         ("hover_extra", "hover=")])
    def test_renamed_arguments(self, old, new):
        with pytest.raises(TypeError, match=f"it is now {new}"):
            qic(y=[1.0, 2.0], chart="i", **{old: 1})

    def test_display_options_moved_to_plot(self):
        with pytest.raises(TypeError, match=r"qic\(\.\.\.\)\.plot\(title="):
            qic(y=[1.0, 2.0], chart="i", title="Waits")

    @pytest.mark.parametrize("old", ["print_summary", "y_percent_accuracy", "strip_horizontal"])
    def test_removed_no_ops_say_so(self, old):
        with pytest.raises(TypeError, match=f"{old}=: removed"):
            qic(y=[1.0, 2.0], chart="i", **{old: True})

    def test_unknown_argument_is_pythons_error(self):
        with pytest.raises(TypeError, match="unexpected keyword argument 'bogus'"):
            qic(y=[1.0, 2.0], chart="i", bogus=1)


class TestMakingDataCount:
    Y = [50.0, 52, 49, 51, 50, 48, 51, 49, 50, 52, 50, 49] + [44, 43, 45, 44, 43, 44, 42]

    def test_variation_and_assurance(self):
        r = qic(y=self.Y, chart="i", method="nhs", worse="higher", target=40)
        assert {"variation", "special_cause"} <= set(r.data.columns)
        assert r.summary["variation"] == "improving"
        assert r.summary["assurance"] in ("pass", "fail", "variable")
        assert set(r.data["variation"]) <= {"improving", "concerning", "common"}

    def test_without_worse_the_reading_is_neutral(self):
        r = qic(y=self.Y, chart="i", method="nhs")
        assert set(r.data["variation"]) <= {"neutral", "common"}
        assert r.summary["assurance"] is None

    def test_limits_use_the_mdc_constant(self):
        r = qic(y=self.Y, chart="i", method="nhs")
        mr = np.abs(np.diff(self.Y))
        kept = mr[mr < 3.267 * mr.mean()]
        assert r.data["ucl"].iloc[0] - r.data["cl"].iloc[0] == pytest.approx(2.66 * kept.mean())


# ---------------------------------------------------------------------------
# funnel()
# ---------------------------------------------------------------------------

OBS = [8, 3, 9, 6, 15, 11, 20, 14, 33, 30, 52, 110]
EXP = [3.2, 4.0, 5.5, 6.1, 8.0, 9.4, 12.0, 15.5, 20.0, 26.0, 40.0, 70.0]


def _physicians(k=400, tau=0.2, seed=5):
    rng = np.random.default_rng(seed)
    e = rng.uniform(3, 60, k)
    return pd.DataFrame({"doc": [f"D{i:03d}" for i in range(k)],
                         "o": rng.poisson(e * rng.gamma(1 / tau ** 2, tau ** 2, k)), "e": e})


class TestFunnelTable:
    def test_columns_are_the_contract(self):
        r = funnel(y=OBS, n=EXP, measure="oe")
        assert list(r.data.columns) == FUNNEL_COLUMNS
        assert isinstance(r, FunnelResult)

    def test_sorted_by_volume_with_counts_in_caller_units(self):
        r = funnel(y=OBS[::-1], n=EXP[::-1], measure="oe")
        assert r.data["denominator"].tolist() == sorted(EXP)
        assert r.data["numerator"].tolist() == OBS

    def test_default_is_the_published_estimator(self):
        s = funnel(y=OBS, n=EXP, measure="oe").summary
        assert s["tau_method"] == "spiegelhalter" and s["tau_scale"] == "natural"

    def test_facets_take_several_columns(self):
        df = pd.concat([_physicians(60, seed=s).assign(year=y, svc=v)
                        for s, (y, v) in enumerate([(2024, "med"), (2024, "surg"),
                                                    (2025, "med")])])
        r = funnel(df, y="o", n="e", unit="doc", measure="oe", facets=["year", "svc"])
        assert list(r.data.columns[:2]) == ["year", "svc"]
        assert set(r.summary["by_facet"]) == {"2024 / med", "2024 / surg", "2025 / med"}
        assert r.summary["n_providers"] == 180
        lim = r.limits()
        assert list(lim.columns[:2]) == ["year", "svc"]

    def test_tau_per_facet(self):
        df = pd.concat([_physicians(60, seed=s).assign(svc=v) for s, v in enumerate("ab")])
        r = funnel(df, y="o", n="e", unit="doc", measure="oe", facets="svc",
                   tau={"a": 0.1, "b": 0.3})
        assert r.summary["by_facet"]["a"]["tau"] == pytest.approx(0.1)
        assert r.summary["by_facet"]["b"]["tau_source"] == "pre-specified"

    def test_expected_false_flags_under_fdr_name_the_bound(self):
        s = funnel(_physicians(), y="o", n="e", measure="oe", signal="fdr").summary
        assert set(s["expected_false_flags"]) == {"outlier", "outlier_or_alert"}

    def test_reads_as_words_and_serializes(self):
        r = funnel(y=OBS, n=EXP, measure="oe", worse="higher")
        assert str(r).startswith("Funnel (oe; exact test")
        assert json.loads(r.to_json())["summary"]["measure"] == "oe"
        assert "FunnelResult(measure='oe'" in repr(r)


class TestTransformedMethods:
    """tau_method="cqc" and "shmi": FunnelPlotR's estimators and transformed-scale limits."""

    @pytest.mark.parametrize("method,scale", [("cqc", "sqrt"), ("shmi", "log")])
    def test_counts(self, method, scale):
        r = funnel(_physicians(), y="o", n="e", measure="oe", center=1.0, tau_method=method)
        s = r.summary
        assert s["tau_scale"] == scale and s["tau"] > 0
        assert s["limit_method"] == s["p_value_method"] == "transformed_normal"
        assert s["count_model"] == f"normal_{scale}"

    def test_proportions_use_the_arcsine_scale(self):
        rng = np.random.default_rng(8)
        n = rng.integers(20, 300, 200)
        y = rng.binomial(n, np.clip(rng.normal(0.2, 0.05, 200), 0.01, 0.99))
        s = funnel(y=y, n=n, measure="proportion", tau_method="cqc").summary
        assert s["tau_scale"] == "arcsine"
        with pytest.raises(ValueError, match="arcsine"):
            funnel(y=y, n=n, measure="proportion", tau_method="shmi")

    @pytest.mark.parametrize("method", ["cqc", "shmi"])
    def test_the_line_is_still_the_test(self, method):
        r = funnel(_physicians(), y="o", n="e", measure="oe", tau_method=method, worse="higher")
        d = r.data
        assert ((d["y"] > d["upper_outlier"]) == (d["p_value"] < 0.001)).all()
        assert ((d["y"] > d["upper_alert"]) == (d["p_value"] < 0.025)).all()

    def test_shrinkage_carries_tau_back_to_the_ratio_scale(self):
        r = funnel(_physicians(), y="o", n="e", measure="oe", tau_method="shmi")
        assert r.data["reliability"].between(0, 1).all() and r.data["reliability"].max() > 0


class TestFunnelCorrections:
    def test_fixed_center_spends_no_degree_of_freedom(self):
        """With center= given, the calibrated estimator uses K, not K - 1 (methods §4.3)."""
        from qikit.core.dispersion import funnel_dispersion
        y, e = np.array(OBS, float) / np.array(EXP), np.array(EXP)
        mask = np.ones(len(e), bool)
        phi, tau2 = funnel_dispersion(1.0, y, e, mask, "poisson", "winsorized", known_mean=True)
        assert tau2 == pytest.approx(len(e) * (phi - 1) / np.sum(e))
        s = funnel(y=OBS, n=EXP, measure="oe", center=1.0, tau_method="winsorized").summary
        assert s["tau_estimated"] ** 2 == pytest.approx(tau2)

    def test_excluded_providers_stay_out_of_the_within_estimate(self):
        rng = np.random.default_rng(2)
        rows = pd.DataFrame({"p": np.repeat(range(40), 30)})
        rows["e"] = rng.uniform(2, 8, len(rows))
        rows["o"] = rng.poisson(rows["e"] * 3) / 3 * 3
        rows.loc[rows["p"] == 0, "o"] *= 25           # one wild provider
        kw = dict(y="o", n="e", unit="p", measure="oe", within_dispersion="estimate")
        with_all = funnel(rows, **kw).summary["within_dispersion"]
        without = funnel(rows, exclude=[0], **kw).summary["within_dispersion"]
        assert without < with_all

    def test_an_estimate_below_one_is_kept_and_explained(self):
        rng = np.random.default_rng(3)
        stays = pd.DataFrame({"p": np.repeat(range(60), 40)})
        stays["e"] = rng.uniform(0.05, 0.4, len(stays))
        stays["o"] = rng.binomial(1, stays["e"])
        s = funnel(stays, y="o", n="e", unit="p", measure="oe",
                   within_dispersion="estimate").summary
        assert s["within_dispersion"] < 1
        assert any("below 1" in note for note in s["notes"])

    def test_byar_above_the_exact_range_is_labeled_and_tested_alike(self):
        r = funnel(y=[200_100, 199_000, 201_500], n=[200_000.0, 200_000.0, 200_000.0],
                   measure="oe", overdispersion=False)
        assert r.summary["limit_method"] == "byar" and r.summary["p_value_method"] == "byar"
        d = r.data
        assert ((d["y"] > d["upper_alert"]) == (d["p_value"] < 0.05) & (d["direction"] == "higher")).all()

    @pytest.mark.parametrize("kw,match", [
        (dict(y=[5, 12], n=[10, 10], measure="proportion"), "cannot exceed n"),
        (dict(y=[-1, 2], n=[10, 10], measure="oe"), "0 or more"),
        (dict(y=[1, 2], n=[10, 10], measure="proportion", center=1.2), "between 0 and 1"),
        (dict(y=[1, 2], n=[10, 10], measure="oe", center=0), "center"),
        (dict(y=[1, 2], n=[10, 10], measure="oe", test_min_expected=3), "fdr_min_denominator"),
        (dict(y=[1, 2], n=[10, 10], measure="oe", title="x"), r"\.plot\(title="),
    ])
    def test_validation(self, kw, match):
        with pytest.raises((ValueError, TypeError), match=match):
            funnel(**kw)


class TestSensitivity:
    def test_one_row_per_provider_and_a_verdict(self):
        df = _physicians(300, tau=0.25)
        out = funnel_sensitivity(df, y="o", n="e", unit="doc", measure="oe", worse="higher")
        assert list(out.columns) == ["unit", "y", "denominator", "signal_spiegelhalter",
                                     "signal_winsorized", "signal_ml", "signal_unadjusted",
                                     "consistent"]
        assert len(out) == 300
        changed = out[~out["consistent"]]
        assert (changed.filter(like="signal_").nunique(axis=1) > 1).all()

    def test_refuses_to_choose_the_model_twice(self):
        with pytest.raises(ValueError, match="sets tau_method"):
            funnel_sensitivity(y=OBS, n=EXP, measure="oe", tau_method="ml")


# ---------------------------------------------------------------------------
# Snowpark: the UDTF body is qic()/funnel() on one partition, returning .data
# ---------------------------------------------------------------------------

def test_snowpark_style_partitions_match_one_faceted_call():
    """A vectorized UDTF hands each partition to end_partition(); the rows it returns
    must equal the faceted call's, so either way of running gives one answer."""
    df = pd.concat([_monthly(seed=s).assign(unit=f"U{s}") for s in range(4)])
    whole = qic(df, x="month", y="events", n="cases", chart="p", facets="unit").data
    parts = []
    for unit, rows in df.groupby("unit", sort=False):
        t = qic(rows, x="month", y="events", n="cases", chart="p").data
        t.insert(0, "unit", unit)
        parts.append(t)
    pd.testing.assert_frame_equal(whole, pd.concat(parts, ignore_index=True))
    assert all(isinstance(v, (str, float, int, bool, np.generic, pd.Timestamp))
               for v in whole.iloc[0].tolist())
    assert not math.isnan(whole["cl"].iloc[0])


def test_a_two_thousand_provider_proportion_funnel_is_fast():
    """Exact intervals and detectability for every provider; ~0.4 s on a 2024 laptop."""
    import time

    rng = np.random.default_rng(1)
    n = rng.integers(10, 400, 2000)
    t = time.perf_counter()
    funnel(y=rng.binomial(n, 0.85), n=n, measure="proportion", worse="lower")
    assert time.perf_counter() - t < 3.0


def test_plot_without_plotly_names_the_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "plotly", None)
    r = qic(y=[1.0, 2.0, 3.0], chart="i")
    with pytest.raises(ImportError, match=r"clinical-qikit\[plot\]"):
        r.plot()
