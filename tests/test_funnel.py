"""
tests/test_funnel.py — the public funnel() API: argument mapping, the result's
columns and summary, within-provider dispersion and its diagnostic, and display.

The engine underneath is pinned in test_spc.py and test_render.py.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

from qikit import FunnelResult, funnel, qic
from qikit.spc.api import _qic

# Twelve physicians: observed deaths against expected, as in funnel_oe_physician_power.
OBS = [8, 3, 9, 6, 15, 11, 20, 14, 33, 30, 52, 110]
EXP = [3.2, 4.0, 5.5, 6.1, 8.0, 9.4, 12.0, 15.5, 20.0, 26.0, 40.0, 70.0]


def _frame():
    return pd.DataFrame({
        "surgeon": [f"S{i:02d}" for i in range(1, 13)],
        "name": [f"Dr {chr(64 + i)}" for i in range(1, 13)],
        "deaths": OBS, "expected": EXP,
    })


def _r(**kw):
    args = dict(y="deaths", n="expected", measure="oe", unit="surgeon")
    args.update(kw)
    return funnel(_frame(), **args)


def _los_stays(rng, k=300, phi_shape=0.6, provider_sd=0.0, mean_stays=60):
    """Stay-level length of stay: gamma days per stay (var/mean = 5 / phi_shape)."""
    rows = []
    for j in range(k):
        m = max(5, int(rng.lognormal(np.log(mean_stays), 0.9)))
        effect = float(np.exp(provider_sd * rng.standard_normal())) if provider_sd else 1.0
        days = rng.gamma(phi_shape, 5 * effect / phi_shape, m).round()
        rows += [(f"P{j:03d}", d, 5.0) for d in days]
    return pd.DataFrame(rows, columns=["provider", "los", "exp_los"])


def _aggregate(stays):
    return stays.groupby("provider", sort=False)[["los", "exp_los"]].sum().reset_index()


# ---------------------------------------------------------------------------
# Mapping onto the engine
# ---------------------------------------------------------------------------

class TestMapping:
    @pytest.mark.parametrize("measure,over,chart", [
        ("oe", True, "oep"), ("oe", False, "oe"), ("rate", True, "up"),
        ("rate", False, "u"), ("proportion", True, "pp"), ("proportion", False, "p"),
    ])
    def test_measure_and_overdispersion_pick_the_model(self, measure, over, chart):
        n = [v * 10 for v in EXP] if measure == "proportion" else EXP
        r = funnel(y=OBS, n=n, measure=measure, overdispersion=over)
        core = _qic(y=OBS, n=n, chart=chart, funnel=True)
        assert r.data["upper_outlier"].tolist() == core.data["ucl"].tolist()
        assert r.data["p_value"].tolist() == core.data["p_value"].tolist()

    @pytest.mark.parametrize("worse,side", [(None, "both"), ("higher", "above"), ("lower", "below")])
    def test_worse_is_the_signal_side(self, worse, side):
        r = _r(worse=worse)
        core = _qic(y=OBS, n=EXP, chart="oep", funnel=True, signal_side=side)
        assert r.data["p_value"].tolist() == core.data["p_value"].tolist()
        assert r.summary["worse"] == worse

    def test_center_benchmarks_against_the_model(self):
        assert (_r(center=1.0).data["cl"] == 1.0).all()


# ---------------------------------------------------------------------------
# result.data and result.summary
# ---------------------------------------------------------------------------

class TestResult:
    def test_columns(self):
        d = _r(label="name").data
        assert list(d.columns) == [
            "unit", "label", "y", "numerator", "denominator", "cl",
            "lower_outlier", "upper_outlier", "lower_alert", "upper_alert",
            "p_value", "q_value", "signal", "direction",
            "min_detectable", "ci_lower", "ci_upper", "excluded",
        ]
        assert set(d["signal"]) <= {"outlier", "alert", "none"}
        assert d["numerator"].sum() == sum(OBS) and d["denominator"].sum() == pytest.approx(sum(EXP))

    def test_tiers_are_disjoint_and_follow_the_lines(self):
        d = _r(overdispersion=False).data
        up = d["y"] > d["upper_outlier"]
        lo = d["y"] < d["lower_outlier"]
        assert ((d["signal"] == "outlier") == (up | lo)).all()
        beyond_alert = (d["y"] > d["upper_alert"]) | (d["y"] < d["lower_alert"])
        assert ((d["signal"] == "alert") == (beyond_alert & ~(up | lo))).all()

    def test_worse_flags_only_its_side(self):
        o = OBS[:10] + [80, 45]  # one provider well above, one well below
        both = funnel(y=o, n=EXP, measure="oe", overdispersion=False).data
        assert set(both.loc[both["signal"] != "none", "direction"]) == {"higher", "lower"}
        d = funnel(y=o, n=EXP, measure="oe", overdispersion=False, worse="higher").data
        flagged = d[d["signal"] != "none"]
        assert len(flagged) and (flagged["direction"] == "higher").all()

    def test_proportion_numerator_is_the_count(self):
        r = funnel(y=OBS, n=[v * 10 for v in EXP], measure="proportion", multiply=100)
        assert r.data["numerator"].round(9).tolist() == sorted(OBS, key=lambda o: EXP[OBS.index(o)])

    def test_summary_keys(self):
        s = _r().summary
        for key in ("measure", "overdispersion", "worse", "signal", "limits", "fdr_levels",
                    "n_providers", "n_tested", "n_outlier", "n_alert", "expected_false_flags",
                    "center", "tau", "count_model", "within_dispersion",
                    "within_dispersion_source", "dispersion_shape", "underpowered", "notes"):
            assert key in s, key
        assert s["within_dispersion_source"] == "default"
        assert isinstance(s["notes"], list)

    def test_expected_false_flags_in_limits_mode(self):
        """K·α per tier: what average providers alone would put there."""
        two = _r(overdispersion=False).summary["expected_false_flags"]
        assert two == {"outlier": round(12 * 0.002, 2), "alert": round(12 * 0.048, 2)}
        one = _r(overdispersion=False, worse="higher").summary["expected_false_flags"]
        assert one == {"outlier": round(12 * 0.001, 2), "alert": round(12 * 0.024, 2)}

    def test_fdr_tiers_and_bound(self):
        r = _r(overdispersion=False, signal="fdr", fdr_levels=(0.2, 0.4))
        d, s = r.data, r.summary
        assert ((d["signal"] == "outlier") == (d["q_value"] < 0.2)).all()
        assert ((d["signal"] == "alert") == ((d["q_value"] < 0.4) & (d["q_value"] >= 0.2))).all()
        assert s["expected_false_flags"] == {
            "outlier": round(0.2 * s["n_outlier"], 2),
            "alert": round(0.4 * (s["n_outlier"] + s["n_alert"]), 2),
        }

    def test_limits_parameter(self):
        wide = _r(limits=(0.999, 0.95)).data
        base = _r().data
        assert (wide["upper_outlier"] >= base["upper_outlier"]).all()
        assert _r(limits=(0.999, 0.95)).summary["limits"] == (0.999, 0.95)

    def test_limits_method_gives_the_contours(self):
        lim = _r().limits([5.0, 50.0])
        assert list(lim.columns) == ["denominator", "cl", "lower_outlier", "upper_outlier",
                                     "lower_alert", "upper_alert"]
        point = _r().limits(EXP)
        d = _r().data.sort_values("denominator")
        assert point["upper_outlier"].tolist() == d["upper_outlier"].tolist()

    def test_str_describes_it(self):
        text = str(_r(worse="higher"))
        assert text.startswith("Funnel (oe; exact test, outlier beyond the 99.8% contour")
        assert "12 providers" in text and "expected by chance" in text

    def test_returns_a_funnel_result(self):
        assert isinstance(_r(), FunnelResult)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

class TestInputs:
    def test_sequences_without_data(self):
        r = funnel(y=OBS, n=EXP, measure="oe", unit=[f"S{i:02d}" for i in range(1, 13)])
        assert r.data["unit"].tolist() == _r().data["unit"].tolist()

    def test_stay_level_rows_sum_per_unit(self):
        stays = _los_stays(np.random.default_rng(1), k=40)
        a = funnel(stays, y="los", n="exp_los", measure="oe", unit="provider")
        b = funnel(_aggregate(stays), y="los", n="exp_los", measure="oe", unit="provider")
        for col in ("y", "upper_outlier", "p_value", "signal"):
            assert a.data[col].tolist() == b.data[col].tolist()

    def test_exclude_by_unit(self):
        r = _r(exclude=["S12"])
        assert r.data.loc[r.data["unit"] == "S12", "excluded"].item()
        assert r.summary["n_tested"] == 11
        with pytest.raises(ValueError, match="not in the data"):
            _r(exclude=["nobody"])

    def test_facets_summarize_each_panel(self):
        df = pd.concat([_frame().assign(site="A"), _frame().assign(site="B")])
        r = funnel(df, y="deaths", n="expected", measure="oe", unit="surgeon", facets="site")
        assert set(r.summary["by_facet"]) == {"A", "B"}
        assert r.summary["n_providers"] == 24
        assert set(r.data["facet"]) == {"A", "B"}

    @pytest.mark.parametrize("kw,match", [
        (dict(measure="smr"), "measure must be one of"),
        (dict(worse="above"), "worse must be one of"),
        (dict(signal="exact"), "signal must be one of"),
        (dict(signal="fdr", fdr_levels=(0.1, 0.05)), "fdr_levels"),
        (dict(limits=(0.95, 0.998)), "levels"),
        (dict(unit="nope"), "must name a column"),
        (dict(hover="y"), "hover="),
    ])
    def test_errors(self, kw, match):
        with pytest.raises(ValueError, match=match):
            _r(**kw)

    def test_hover_collision(self):
        df = _frame().assign(signal=1)
        with pytest.raises(ValueError, match="collides"):
            funnel(df, y="deaths", n="expected", measure="oe", hover="signal")


# ---------------------------------------------------------------------------
# qic() is time-ordered only
# ---------------------------------------------------------------------------

class TestQicIsTimeOrdered:
    def test_rejects_oe(self):
        with pytest.raises(ValueError, match="qikit.funnel"):
            qic(y=OBS, n=EXP, chart="oe")

    @pytest.mark.parametrize("kw,replacement", [
        ({"funnel": True}, "qikit.funnel(data, y=..., n=..., measure=...)"),
        ({"signal_side": "above"}, "funnel(worse=...)"),
        ({"signal_method": "fdr"}, "funnel(signal=...)"),
        ({"limit_method": "exact"}, "always draws exact limits"),
        ({"x_spacing": "n"}, "plots each provider at its volume"),
        ({"x_log": True}, "funnel(x_log=True)"),
        ({"levels": (0.998, 0.95)}, "funnel(limits=...)"),
        ({"fdr_levels": (0.05, 0.1)}, "funnel(fdr_levels=...)"),
        ({"within_dispersion": 2.0}, "funnel(within_dispersion=...)"),
    ])
    def test_removed_arguments_name_their_replacement(self, kw, replacement):
        """A 0.7 call is told where each funnel argument went, not just that it is gone."""
        with pytest.raises(TypeError, match="qic\\(\\) no longer takes") as err:
            qic(y=OBS, n=EXP, chart="u", **kw)
        assert "qikit.funnel()" in str(err.value) and replacement in str(err.value)

    def test_every_removed_argument_is_named_together(self):
        with pytest.raises(TypeError, match="'funnel', 'signal_side'"):
            qic(y=OBS, n=EXP, chart="u", funnel=True, signal_side="above")

    def test_other_unknown_arguments_keep_pythons_error(self):
        with pytest.raises(TypeError, match="^qic\\(\\) got an unexpected keyword argument 'bogus'$"):
            qic(y=OBS, n=EXP, chart="u", bogus=1)

    def test_time_ordered_charts_unchanged(self):
        a = qic(y=OBS, n=EXP, chart="u")
        b = _qic(y=OBS, n=EXP, chart="u")
        assert a.data.equals(b.data)


# ---------------------------------------------------------------------------
# Within-provider dispersion
# ---------------------------------------------------------------------------

class TestWithinDispersion:
    def test_one_is_a_no_op(self):
        a, b = _r(), _r(within_dispersion=1.0)
        assert a.data.equals(b.data)

    def test_supplied_phi_is_effective_counts(self):
        """Variance φ × mean is a Poisson count of O/φ events against E/φ expected."""
        r = _r(overdispersion=False, within_dispersion=2.0)
        scaled = _qic(y=[o / 2 for o in OBS], n=[e / 2 for e in EXP], chart="oe", funnel=True)
        assert r.data["upper_outlier"].tolist() == scaled.data["ucl"].tolist()
        assert r.data["p_value"].tolist() == pytest.approx(scaled.data["p_value"].tolist(), rel=1e-12)
        assert r.data["numerator"].tolist() == sorted(OBS, key=lambda o: EXP[OBS.index(o)])
        assert r.summary["within_dispersion"] == 2.0
        assert r.summary["within_dispersion_source"] == "supplied"

    def test_contours_redrawn_in_the_callers_units(self):
        r = _r(within_dispersion=3.0)
        lim = r.limits(EXP)
        d = r.data.sort_values("denominator")
        assert lim["upper_outlier"].tolist() == d["upper_outlier"].tolist()

    def test_estimate_recovers_phi(self):
        stays = _los_stays(np.random.default_rng(2), k=200, phi_shape=0.6)
        r = funnel(stays, y="los", n="exp_los", measure="oe", unit="provider",
                   within_dispersion="estimate")
        assert r.summary["within_dispersion"] == pytest.approx(5 / 0.6, rel=0.1)
        assert r.summary["within_dispersion_source"] == "estimated"

    def test_estimate_ignores_real_provider_differences(self):
        rng = np.random.default_rng(3)
        same = _los_stays(rng, k=200, phi_shape=0.6)
        spread = _los_stays(np.random.default_rng(3), k=200, phi_shape=0.6, provider_sd=0.3)
        a = funnel(same, y="los", n="exp_los", measure="oe", unit="provider",
                   within_dispersion="estimate").summary["within_dispersion"]
        b = funnel(spread, y="los", n="exp_los", measure="oe", unit="provider",
                   within_dispersion="estimate").summary["within_dispersion"]
        assert b == pytest.approx(a, rel=0.15)

    def test_estimate_per_facet(self):
        lo = _los_stays(np.random.default_rng(4), k=80, phi_shape=2.5).assign(line="med")
        hi = _los_stays(np.random.default_rng(5), k=80, phi_shape=0.5).assign(line="surg")
        r = funnel(pd.concat([lo, hi]), y="los", n="exp_los", measure="oe", unit="provider",
                   facets="line", within_dispersion="estimate")
        phis = {fv: s["within_dispersion"] for fv, s in r.summary["by_facet"].items()}
        assert phis["med"] == pytest.approx(2.0, rel=0.15)
        assert phis["surg"] == pytest.approx(10.0, rel=0.15)

    def test_estimate_needs_stay_level_rows(self):
        with pytest.raises(ValueError, match="several rows per unit"):
            _r(within_dispersion="estimate")

    def test_not_for_proportions(self):
        with pytest.raises(ValueError, match="measure='oe' and 'rate'"):
            funnel(y=OBS, n=[v * 10 for v in EXP], measure="proportion", within_dispersion=2.0)

    def test_calibrates_the_flag_rate(self):
        """No true provider effect: with φ̂ the tiers hold about their chance share."""
        stays = _los_stays(np.random.default_rng(6), k=400, phi_shape=0.6)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            naive = funnel(stays, y="los", n="exp_los", measure="oe", unit="provider",
                           overdispersion=False).summary
        fixed = funnel(stays, y="los", n="exp_los", measure="oe", unit="provider",
                       overdispersion=False, within_dispersion="estimate").summary
        assert naive["n_outlier"] > 10 * fixed["expected_false_flags"]["outlier"]
        assert fixed["n_outlier"] <= 4
        assert fixed["n_alert"] <= 2 * fixed["expected_false_flags"]["alert"]


class TestDispersionShape:
    def _warns(self, **kw):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            r = funnel(**kw)
        return r, [w for w in caught if "clustered within providers" in str(w.message)]

    def test_fires_on_aggregated_length_of_stay(self):
        agg = _aggregate(_los_stays(np.random.default_rng(7), k=300))
        r, caught = self._warns(data=agg, y="los", n="exp_los", measure="oe", unit="provider")
        assert len(caught) == 1
        assert r.summary["dispersion_shape"] in ("within", "both")
        assert r.summary["within_dispersion_hint"] == pytest.approx(5 / 0.6, rel=0.25)
        assert any("clustered" in note for note in r.summary["notes"])

    def test_setting_within_dispersion_silences_it(self):
        stays = _los_stays(np.random.default_rng(7), k=300)
        r, caught = self._warns(data=stays, y="los", n="exp_los", measure="oe",
                                unit="provider", within_dispersion="estimate")
        assert caught == []
        assert r.summary["dispersion_shape"] in ("none", "between")

    @pytest.mark.parametrize("scenario", ["poisson", "between", "binary"])
    def test_quiet_on_event_counts(self, scenario):
        rng = np.random.default_rng(8)
        k = 600
        e = rng.lognormal(np.log(40), 0.9, k)
        if scenario == "binary":
            cases = np.maximum(1, np.round(e / 0.15)).astype(int)
            o = rng.binomial(cases, 0.15)
            e = cases * 0.15
        else:
            theta = np.exp(0.2 * rng.standard_normal(k)) if scenario == "between" else 1.0
            o = rng.poisson(theta * e)
        r, caught = self._warns(y=o, n=e, measure="oe")
        assert caught == []
        assert r.summary["dispersion_shape"] in ("none", "between")


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

class TestDisplay:
    def _captions(self, fig):
        return [a.text for a in fig.layout.annotations if a.yref == "paper"]

    def test_legend_and_inner_band_by_default(self):
        fig = _r().plot()
        assert fig.layout.showlegend is True
        names = {t.name for t in fig.data}
        assert {"99.8% limits", "95% limits", "95%+"} <= names

    def test_caption_states_the_rule(self):
        (cap,) = self._captions(_r(worse="higher").plot())
        assert cap.startswith("Outlier: beyond the 99.8% limit (exact test, one-sided")

    def test_axis_titles_from_columns(self):
        fig = funnel(y=OBS, n=EXP, measure="rate").plot()
        assert fig.layout.yaxis.title.text == "Rate"
        fig = _r().plot()
        assert fig.layout.xaxis.title.text == "expected"
        assert fig.layout.yaxis.title.text == "Observed / expected"

    def test_plot_overrides_text(self):
        fig = _r().plot(title="Mortality", ylab="SMR")
        assert "Mortality" in fig.layout.title.text
        assert fig.layout.yaxis.title.text == "SMR"

    def test_y_is_fitted_to_the_data(self):
        fig = _r().plot()
        lo, hi = fig.layout.yaxis.range
        assert hi < 6  # the E = 3 flare would reach far higher
        assert hi >= max(o / e for o, e in zip(OBS, EXP))

    def test_styles_list_merges_house_style(self):
        house = {"limits": {"color": "#333333"}, "font": {"family": "Georgia", "size": 14},
                 "data": {"opacity": 0.6}}
        fig = _r().plot(styles=[house, {"ucl": {"color": "#990000"}}])
        assert next(t for t in fig.data if t.name == "99.8%+").line.color == "#990000"
        assert next(t for t in fig.data if t.name == "99.8%-").line.color == "#333333"
        assert fig.layout.font.family == "Georgia" and fig.layout.font.size == 14
        data = next(t for t in fig.data if t.name == "data" and t.x[0] is not None)
        assert max(data.marker.opacity) == 0.6

    def test_points_default_to_085_opacity(self):
        data = next(t for t in _r().plot().data if t.name == "data" and t.x[0] is not None)
        assert max(data.marker.opacity) == 0.85

    def test_label_alert_tier(self):
        fig = _r(overdispersion=False, label_signals="both").plot()
        assert fig is not None


class TestReadmeExample:
    """The README's physician workflow through funnel(). If this breaks, the README is
    wrong."""

    def _df(self):
        import pathlib
        path = pathlib.Path("data/examples/physician_mortality_oe.csv")
        if not path.exists():
            pytest.skip("example data not present")
        return pd.read_csv(path)

    def _funnel(self, frame):
        return funnel(frame, y="observed_deaths", n="expected_deaths", measure="oe",
                      unit="physician")

    def test_one_year_is_underpowered_with_no_outlier(self):
        df = self._df()
        s = self._funnel(df[df.year == 2025]).summary
        assert s["underpowered"] is True and s["n_outlier"] == 0

    def test_three_years_pooled_find_three(self):
        d = self._funnel(self._df()).data
        flagged = d[d["signal"] != "none"].set_index("unit")
        assert flagged["direction"].to_dict() == {
            "SURG-07": "higher", "SURG-15": "higher", "SURG-21": "lower",
        }
        assert (flagged["signal"] == "outlier").all()
