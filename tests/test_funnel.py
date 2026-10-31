"""
tests/test_funnel.py — the public funnel() API: argument mapping, the result's
columns and summary, within-provider dispersion and its diagnostic, and display.

The engine underneath is pinned in test_spc.py and test_render.py.
"""
from __future__ import annotations

import math
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


def _surveys(rng, k=300, base=0.8, rho=0.71, provider_sd=0.0, min_surveys=4, items=3):
    """
    One row per survey of a multi-item instrument: each survey has a latent
    propensity drawn from a beta with intraclass correlation rho, so its items agree
    (design effect 1 + (items − 1)·rho; 2.42 at the defaults). rho = 0 makes the
    items independent.
    """
    rows = []
    for j in range(k):
        s = max(min_surveys, int(round(rng.lognormal(np.log(15), 0.8))))
        theta = float(np.clip(base + provider_sd * rng.standard_normal(), 0.01, 0.99))
        p = (rng.beta(theta * (1 / rho - 1), (1 - theta) * (1 / rho - 1), s) if rho > 0
             else np.full(s, theta))
        rows += [(f"D{j:03d}", int(v), items) for v in rng.binomial(items, p)]
    return pd.DataFrame(rows, columns=["doctor", "always", "answered"])


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

    @pytest.mark.parametrize("measure,chart", [("oe", "oep"), ("rate", "up"), ("proportion", "pp")])
    def test_spiegelhalter_is_the_published_engine(self, measure, chart):
        n = [v * 10 for v in EXP] if measure == "proportion" else EXP
        r = funnel(y=OBS, n=n, measure=measure, tau_method="spiegelhalter")
        core = _qic(y=OBS, n=n, chart=chart, funnel=True, tau_method="spiegelhalter")
        assert r.data["upper_outlier"].tolist() == core.data["ucl"].tolist()
        assert r.data["p_value"].tolist() == core.data["p_value"].tolist()
        assert math.isnan(r.summary["phi_debiased"])

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
            "raw_excess", "reliability", "eb_rate", "eb_excess", "prob_worse",
            "p_value_drop1", "flag_survives_drop1", "fragility",
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
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # the rows show clustered days, by design
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


class TestClusteredProportions:
    """within_dispersion on measure="proportion": items clustered in surveys."""

    ARGS = dict(y="always", n="answered", unit="doctor", measure="proportion")

    def test_supplied_phi_is_effective_counts(self):
        """Rao–Scott: a proportion of n clustered items is binomial in n/φ."""
        y = [3, 10, 14, 25, 40, 61, 70, 101]
        n = [12, 18, 24, 36, 60, 90, 99, 150]
        r = funnel(y=y, n=n, measure="proportion", overdispersion=False, within_dispersion=2.42)
        scaled = _qic(y=[v / 2.42 for v in y], n=[v / 2.42 for v in n], chart="p", funnel=True)
        assert r.data["upper_outlier"].tolist() == scaled.data["ucl"].tolist()
        assert r.data["p_value"].tolist() == pytest.approx(scaled.data["p_value"].tolist(), rel=1e-12)
        assert r.data["numerator"].tolist() == y
        assert r.summary["within_dispersion"] == 2.42
        assert r.summary["within_dispersion_source"] == "supplied"
        assert r.summary["p_value_method"] == "interpolated"
        assert r.data[["ci_lower", "ci_upper"]].notna().all().all()
        assert r.data["min_detectable"].iloc[-3:].notna().all()  # NaN: nothing can flag

    def test_one_is_a_no_op(self):
        d = _surveys(np.random.default_rng(1), k=60)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            a = funnel(d, **self.ARGS)
            b = funnel(d, within_dispersion=1.0, **self.ARGS)
        assert a.data.equals(b.data)

    def test_contours_redrawn_in_the_callers_units(self):
        y, n = [3, 10, 14, 25, 40], [12, 18, 24, 36, 60]
        r = funnel(y=y, n=n, measure="proportion", within_dispersion=2.42)
        assert r.limits(n)["upper_outlier"].tolist() == r.data["upper_outlier"].tolist()

    @pytest.mark.parametrize("base", [0.8, 0.1])
    def test_estimate_recovers_the_design_effect(self, base):
        d = _surveys(np.random.default_rng(2), k=400, base=base)
        r = funnel(d, within_dispersion="estimate", **self.ARGS)
        assert r.summary["within_dispersion"] == pytest.approx(2.42, rel=0.06)
        assert r.summary["within_dispersion_source"] == "estimated"

    def test_estimate_is_one_for_independent_items(self):
        d = _surveys(np.random.default_rng(3), k=400, rho=0.0)
        r = funnel(d, within_dispersion="estimate", **self.ARGS)
        assert r.summary["within_dispersion"] == pytest.approx(1.0, abs=0.06)

    def test_estimate_ignores_real_provider_differences(self):
        a = funnel(_surveys(np.random.default_rng(4), k=400, base=0.3),
                   within_dispersion="estimate", **self.ARGS).summary["within_dispersion"]
        b = funnel(_surveys(np.random.default_rng(4), k=400, base=0.3, provider_sd=0.08),
                   within_dispersion="estimate", **self.ARGS).summary["within_dispersion"]
        assert b == pytest.approx(a, rel=0.08)

    def test_providers_at_zero_or_all_events_are_kept(self):
        """At a 3% rate most doctors have no events; they still count toward φ̂."""
        d = _surveys(np.random.default_rng(5), k=400, base=0.03)
        theta = d.groupby("doctor")["always"].sum()
        assert (theta == 0).mean() > 0.3
        r = funnel(d, within_dispersion="estimate", **self.ARGS)
        assert r.summary["within_dispersion"] == pytest.approx(2.42, rel=0.15)

    def test_estimate_refuses_one_item_per_row(self):
        items = pd.DataFrame({"doctor": np.repeat([f"D{i}" for i in range(50)], 6),
                              "always": np.random.default_rng(6).binomial(1, 0.8, 300),
                              "answered": 1})
        with pytest.raises(ValueError, match="one item per row"):
            funnel(items, within_dispersion="estimate", **self.ARGS)

    def test_estimate_per_facet(self):
        top = _surveys(np.random.default_rng(7), k=150, rho=0.71).assign(box="top")
        low = _surveys(np.random.default_rng(8), k=150, rho=0.2).assign(box="bottom")
        r = funnel(pd.concat([top, low]), facets="box", within_dispersion="estimate", **self.ARGS)
        phis = {fv: s["within_dispersion"] for fv, s in r.summary["by_facet"].items()}
        assert phis["top"] == pytest.approx(2.42, rel=0.1)
        assert phis["bottom"] == pytest.approx(1.4, rel=0.1)

    @pytest.mark.parametrize("base", [0.8, 0.1])
    def test_calibrates_the_flag_rate(self, base):
        """No true provider effect: the default over-flags, φ̂ holds the chance share."""
        d = _surveys(np.random.default_rng(9), k=575, base=base)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            naive = funnel(d, overdispersion=False, **self.ARGS).summary
        fixed = funnel(d, overdispersion=False, within_dispersion="estimate", **self.ARGS).summary
        assert naive["n_alert"] > 1.3 * naive["expected_false_flags"]["alert"]
        assert fixed["n_outlier"] <= 3
        assert fixed["n_alert"] <= fixed["expected_false_flags"]["alert"]


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

    @pytest.mark.parametrize("base", [0.8, 0.1])
    def test_survey_rows_fire_where_totals_cannot(self, base):
        """Clustered items with a real spread between doctors: the totals read
        "between" (the spread hides the clumping); the survey rows see it."""
        d = _surveys(np.random.default_rng(11), k=575, base=base,
                     provider_sd=0.06 if base == 0.8 else 0.04)
        r, caught = self._warns(data=d, y="always", n="answered", unit="doctor",
                                measure="proportion")
        assert len(caught) == 1
        assert r.summary["dispersion_shape"] in ("within", "both")
        assert r.summary["within_dispersion_hint"] == pytest.approx(2.42, rel=0.1)
        assert r.summary["within_dispersion_hint_source"] == "rows"
        assert "one row per case (per survey" in r.summary["notes"][0]
        totals = d.groupby("doctor", as_index=False)[["always", "answered"]].sum()
        t, _ = self._warns(data=totals, y="always", n="answered", unit="doctor",
                           measure="proportion")
        assert t.summary["dispersion_shape"] == "between"
        assert t.summary["within_dispersion_hint_source"] == "totals"

    def test_estimate_silences_the_row_check(self):
        d = _surveys(np.random.default_rng(11), k=300)
        r, caught = self._warns(data=d, y="always", n="answered", unit="doctor",
                                measure="proportion", within_dispersion="estimate")
        assert caught == []

    @pytest.mark.parametrize("rows", ["independent_items", "one_per_patient"])
    def test_row_check_quiet_on_independent_cases(self, rows):
        rng = np.random.default_rng(12)
        if rows == "independent_items":
            d = _surveys(rng, k=575, rho=0.0, provider_sd=0.05)
        else:
            d = pd.DataFrame({"doctor": np.repeat([f"D{i}" for i in range(400)], 20),
                              "always": rng.binomial(1, 0.8, 8000), "answered": 1})
        r, caught = self._warns(data=d, y="always", n="answered", unit="doctor",
                                measure="proportion")
        assert caught == []

    def test_row_check_quiet_on_death_rows(self):
        """Patient-level O/E rows (died 0/1 against predicted risk) vary less than
        Poisson, not more."""
        rng = np.random.default_rng(13)
        risk = rng.beta(1, 9, 20_000)
        d = pd.DataFrame({"provider": np.repeat([f"P{i}" for i in range(400)], 50),
                          "died": rng.binomial(1, risk), "risk": risk})
        r, caught = self._warns(data=d, y="died", n="risk", unit="provider", measure="oe")
        assert caught == []

    def test_row_check_fires_on_stay_rows(self):
        stays = _los_stays(np.random.default_rng(14), k=60)
        r, caught = self._warns(data=stays, y="los", n="exp_los", measure="oe", unit="provider")
        assert len(caught) == 1
        assert r.summary["within_dispersion_hint_source"] == "rows"
        assert r.summary["within_dispersion_hint"] == pytest.approx(5 / 0.6, rel=0.15)

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


# ---------------------------------------------------------------------------
# 0.10: debiased φ, sufficient statistics, per-unit φ, shrinkage, drop-one,
# filtered FDR, speed (docs/methods.md §4.3, §4.11, §4.12, §4.14, §4.15, §4.5)
# ---------------------------------------------------------------------------

def _physicians(rng, k=1000, tau=0.0, lo=2.0, hi=60.0):
    e = rng.uniform(lo, hi, k)
    theta = np.clip(1.0 + tau * rng.standard_normal(k), 0.05, None)
    return rng.poisson(theta * e).astype(float), e


def _los_cohort(rng, k=100, m=30, shape=1.5, provider_sd=0.0):
    """Stay-level LOS: k providers of m stays, gamma days (var/mean = 4/shape) around 4."""
    rows = []
    for j in range(k):
        eff = float(np.exp(provider_sd * rng.standard_normal())) if provider_sd else 1.0
        days = rng.gamma(shape, 4.0 * eff / shape, m).round()
        rows += [(f"P{j:03d}", d, 4.0) for d in days]
    return pd.DataFrame(rows, columns=["provider", "los", "exp_los"])


def _sql_totals(stays, y="los", n="exp_los", unit="provider"):
    """What the SQL in funnel()'s docstring returns: O, E, k, SUM(o^2/e), worst case."""
    s = stays.assign(_sq=stays[y] ** 2 / stays[n], _r=stays[y] - stays[n])
    worst = s.loc[s.groupby(unit)["_r"].idxmax(), [unit, y, n]].set_index(unit)
    g = s.groupby(unit).agg(o=(y, "sum"), e=(n, "sum"), k=(y, "size"), ss=("_sq", "sum"))
    return g.join(worst.rename(columns={y: "max_y", n: "max_n"})).reset_index()


class TestDebiasedPhi:
    def test_phi_is_unbiased_under_the_null(self):
        from qikit.spc import limits as _limits
        rng = np.random.default_rng(11)
        raw, deb = [], []
        for _ in range(40):
            e = rng.uniform(5, 50, 1000)
            y = 1.0 + rng.standard_normal(1000) * np.sqrt(1.0 / e)
            mask = np.ones(1000, bool)
            raw.append(_limits.funnel_dispersion(1.0, y, e, mask, "poisson",
                                                 method="spiegelhalter")[0])
            deb.append(_limits.funnel_dispersion(1.0, y, e, mask, "poisson")[0])
        assert np.mean(raw) == pytest.approx(0.679, abs=0.02)
        assert np.mean(deb) == pytest.approx(1.0, abs=0.05)

    def test_tau_is_recovered_at_physician_volumes(self):
        rng = np.random.default_rng(12)
        on, off = [], []
        for _ in range(20):
            o, e = _physicians(rng, tau=0.10)
            on.append(funnel(y=o, n=e, measure="oe").summary["tau"])
            off.append(funnel(y=o, n=e, measure="oe", tau_method="spiegelhalter").summary["tau"])
        assert np.mean(on) == pytest.approx(0.10, abs=0.02)
        assert np.mean(off) < 0.03  # the published estimator misses it

    def test_summary_reports_both_estimates(self):
        from qikit.spc.limits import winsor_consistency
        s = _r().summary
        assert s["tau_method"] == "winsorized"
        assert s["phi_debiased"] == pytest.approx(s["phi_raw"] * winsor_consistency())
        assert winsor_consistency(0.10) == pytest.approx(1.4735, abs=1e-4)

    def test_rejects_an_unknown_method(self):
        with pytest.raises(ValueError, match="tau_method must be one of"):
            _r(tau_method="reml")


class TestSufficientStatistics:
    def test_matches_case_rows_for_counts(self):
        stays = _los_cohort(np.random.default_rng(21), provider_sd=0.15)
        rows = funnel(stays, y="los", n="exp_los", unit="provider", measure="oe",
                      within_dispersion="estimate", worse="higher")
        agg = funnel(_sql_totals(stays), y="o", n="e", unit="provider", measure="oe",
                     cases="k", sum_sq="ss", within_dispersion="estimate", worse="higher")
        for key in ("center", "tau", "within_dispersion"):
            assert agg.summary[key] == pytest.approx(rows.summary[key], rel=1e-12)
        a, b = rows.data.set_index("unit"), agg.data.set_index("unit").loc[rows.data["unit"]]
        for col in ("p_value", "q_value", "eb_excess", "reliability"):
            np.testing.assert_allclose(b[col], a[col], rtol=1e-10)
        assert (a["signal"].to_numpy() == b["signal"].to_numpy()).all()

    def test_matches_case_rows_for_proportions(self):
        surveys = _surveys(np.random.default_rng(22), k=150)
        rows = funnel(surveys, y="always", n="answered", unit="doctor",
                      measure="proportion", within_dispersion="estimate")
        s = surveys.assign(_sq=surveys["always"] ** 2 / surveys["answered"])
        g = s.groupby("doctor").agg(y=("always", "sum"), n=("answered", "sum"),
                                    k=("always", "size"), ss=("_sq", "sum")).reset_index()
        agg = funnel(g, y="y", n="n", unit="doctor", measure="proportion",
                     cases="k", sum_sq="ss", within_dispersion="estimate")
        assert agg.summary["within_dispersion"] == pytest.approx(
            rows.summary["within_dispersion"], rel=1e-12)
        assert agg.summary["tau"] == pytest.approx(rows.summary["tau"], rel=1e-9, abs=1e-12)

    def test_clustering_check_works_from_aggregates(self):
        stays = _los_cohort(np.random.default_rng(23), k=200)
        with pytest.warns(UserWarning, match="clustered"):
            r = funnel(_sql_totals(stays), y="o", n="e", unit="provider", measure="oe",
                       cases="k", sum_sq="ss")
        assert r.summary["within_dispersion_hint_source"] == "rows"

    def test_errors(self):
        g = _sql_totals(_los_cohort(np.random.default_rng(24), k=10))
        base = dict(y="o", n="e", unit="provider", measure="oe")
        with pytest.raises(ValueError, match="go together"):
            funnel(g, cases="k", **base)
        with pytest.raises(ValueError, match="one provider per row"):
            funnel(pd.concat([g, g]), cases="k", sum_sq="ss", **base)
        with pytest.raises(ValueError, match="cases= must be"):
            funnel(g.assign(k=0), cases="k", sum_sq="ss", **base)
        with pytest.raises(ValueError, match="sum_sq= must be"):
            funnel(g.assign(ss=-1.0), cases="k", sum_sq="ss", **base)
        with pytest.raises(ValueError, match="cases= must name a column"):
            funnel(g, cases="nope", sum_sq="ss", **base)
        with pytest.raises(ValueError, match="need|pass data="):
            funnel(y=g["o"], n=g["e"], measure="oe", cases="k", sum_sq="ss")
        with pytest.raises(ValueError, match="no provider with more than one case"):
            funnel(g.assign(k=1), cases="k", sum_sq="ss", within_dispersion="estimate", **base)


class TestPerUnitDispersion:
    def test_a_constant_column_is_the_scalar(self):
        stays = _los_cohort(np.random.default_rng(31))
        scalar = funnel(stays, y="los", n="exp_los", unit="provider", measure="oe",
                        within_dispersion=2.5, worse="higher")
        col = funnel(stays.assign(phi=2.5), y="los", n="exp_los", unit="provider",
                     measure="oe", within_dispersion="phi", worse="higher")
        a = scalar.data.set_index("unit")
        b = col.data.set_index("unit").loc[a.index]
        for c in ("y", "numerator", "denominator", "p_value", "eb_excess"):
            np.testing.assert_allclose(b[c], a[c], rtol=1e-12)
        np.testing.assert_allclose(b["effective_denominator"], a["denominator"] / 2.5)
        assert col.summary["within_dispersion"] == pytest.approx(2.5)
        assert col.summary["within_dispersion_source"] == "column"

    def test_case_mix_phi_judges_each_provider_on_its_own(self):
        stays = _los_cohort(np.random.default_rng(32))
        phi = {p: (1.5 if i % 2 else 4.0) for i, p in enumerate(stays["provider"].unique())}
        r = funnel(stays.assign(phi=stays["provider"].map(phi)), y="los", n="exp_los",
                   unit="provider", measure="oe", within_dispersion="phi")
        d = r.data
        np.testing.assert_allclose(d["denominator"] / d["effective_denominator"],
                                   d["unit"].map(phi))

    def test_errors(self):
        stays = _los_cohort(np.random.default_rng(33), k=5)
        base = dict(y="los", n="exp_los", unit="provider", measure="oe")
        with pytest.raises(ValueError, match="varies within a provider"):
            funnel(stays.assign(phi=np.arange(len(stays)) + 1.0), within_dispersion="phi", **base)
        with pytest.raises(ValueError, match="positive, finite"):
            funnel(stays.assign(phi=0.0), within_dispersion="phi", **base)
        with pytest.raises(ValueError, match="within_dispersion= must name a column"):
            funnel(stays, within_dispersion="phi", **base)


class TestShrinkage:
    def test_eb_rate_is_the_gamma_posterior_mean(self):
        o, e = _physicians(np.random.default_rng(41), k=300, tau=0.3)
        r = funnel(y=o, n=e, measure="oe")
        cl, tau2 = r.summary["center"], r.summary["tau"] ** 2
        assert tau2 > 0
        d = r.data
        a, b = cl * cl / tau2, cl / tau2
        np.testing.assert_allclose(d["eb_rate"], (a + d["numerator"]) / (b + d["denominator"]),
                                   rtol=1e-10)
        np.testing.assert_allclose(d["eb_excess"], (d["eb_rate"] - cl) * d["denominator"])

    def test_eb_rate_is_the_beta_posterior_mean(self):
        rng = np.random.default_rng(42)
        n = rng.integers(20, 300, 300).astype(float)
        y = rng.binomial(n.astype(int), np.clip(0.8 + 0.05 * rng.standard_normal(300), .01, .99))
        r = funnel(y=y, n=n, measure="proportion")
        cl, tau2 = r.summary["center"], r.summary["tau"] ** 2
        s = cl * (1 - cl) / tau2 - 1
        d = r.data
        np.testing.assert_allclose(d["eb_rate"], (cl * s + d["numerator"]) / (s + d["denominator"]),
                                   rtol=1e-10)

    def test_no_spread_means_no_reliability(self):
        d = _r(overdispersion=False).data
        assert (d["reliability"] == 0).all()
        np.testing.assert_allclose(d["eb_rate"], d["cl"])
        assert (d["eb_excess"] == 0).all()

    def test_excess_is_signed_toward_worse(self):
        hi, lo = _r(worse="higher").data, _r(worse="lower").data
        np.testing.assert_allclose(hi["raw_excess"], hi["numerator"] - hi["cl"] * hi["denominator"])
        np.testing.assert_allclose(lo["raw_excess"], -hi["raw_excess"])
        np.testing.assert_allclose(lo["eb_excess"], -hi["eb_excess"])

    def test_within_dispersion_shrinks_on_effective_counts(self):
        o, e = _physicians(np.random.default_rng(43), k=300, tau=0.3, lo=20, hi=200)
        r = funnel(y=o * 3, n=e * 3, measure="oe", within_dispersion=3.0)
        cl, tau2 = r.summary["center"], r.summary["tau"] ** 2
        d = r.data
        expect = (cl * cl / tau2 + d["numerator"] / 3) / (cl / tau2 + d["denominator"] / 3)
        np.testing.assert_allclose(d["eb_rate"], expect, rtol=1e-10)


def _one_patient_cohort(rng):
    """100 providers of 30 stays near 4/4, and P_X: 29 stays at 4/4 plus one at 60/4."""
    stays = _los_cohort(rng, k=100, m=30, shape=1.5)
    x = pd.DataFrame({"provider": "P_X", "los": [4.0] * 29 + [60.0], "exp_los": 4.0})
    return pd.concat([stays, x], ignore_index=True)


class TestDropOne:
    def test_a_single_case_driven_flag(self):
        stays = _one_patient_cohort(np.random.default_rng(51))
        r = funnel(stays, y="los", n="exp_los", unit="provider", measure="oe",
                   within_dispersion="estimate", worse="higher")
        x = r.data.set_index("unit").loc["P_X"]
        assert x["signal"] != "none"
        assert x["flag_survives_drop1"] is False or not bool(x["flag_survives_drop1"])
        assert x["fragility"] == 1
        assert x["p_value_drop1"] > 0.20
        assert r.summary["n_fragile"] >= 1
        assert any("fragility = 1" in note for note in r.summary["notes"])

    def test_sql_worst_case_columns_give_the_same_p(self):
        stays = _one_patient_cohort(np.random.default_rng(52))
        kw = dict(unit="provider", measure="oe", within_dispersion="estimate", worse="higher")
        rows = funnel(stays, y="los", n="exp_los", **kw).data.set_index("unit")
        agg = funnel(_sql_totals(stays), y="o", n="e", cases="k", sum_sq="ss",
                     max_case_y="max_y", max_case_n="max_n", **kw).data.set_index("unit")
        assert agg.loc["P_X", "p_value_drop1"] == pytest.approx(rows.loc["P_X", "p_value_drop1"],
                                                                rel=1e-9)
        assert agg["fragility"].isna().all()  # needs the cases themselves

    def test_a_uniformly_high_provider_is_robust(self):
        rng = np.random.default_rng(53)
        stays = _los_cohort(rng, k=100, m=30, shape=1.5)
        high = pd.DataFrame({"provider": "P_H", "los": rng.gamma(1.5, 7.0 / 1.5, 60).round(),
                             "exp_los": 4.0})
        r = funnel(pd.concat([stays, high]), y="los", n="exp_los", unit="provider",
                   measure="oe", within_dispersion="estimate", worse="higher")
        h = r.data.set_index("unit").loc["P_H"]
        assert h["signal"] == "outlier"
        assert bool(h["flag_survives_drop1"])
        assert pd.isna(h["fragility"]) or h["fragility"] > 3

    def test_provider_rows_have_no_case_information(self):
        d = _r().data
        assert d["p_value_drop1"].isna().all()
        assert d["flag_survives_drop1"].isna().all() and d["fragility"].isna().all()

    def test_worst_case_columns_go_together(self):
        with pytest.raises(ValueError, match="max_case_y= and max_case_n="):
            _r(max_case_y="deaths")


class TestFilteredFdr:
    def test_filter_touches_only_the_fdr_step(self):
        o, e = _physicians(np.random.default_rng(61), k=400, tau=0.2, lo=0.5, hi=40)
        full = funnel(y=o, n=e, measure="oe", signal="fdr", worse="higher")
        cut = funnel(y=o, n=e, measure="oe", signal="fdr", worse="higher", test_min_expected=5)
        low = cut.data["denominator"] < 5
        assert low.any()
        assert cut.data.loc[low, "q_value"].isna().all()
        assert cut.data.loc[low, "p_value"].notna().all()
        assert (cut.data.loc[low, "signal"] == "none").all()
        np.testing.assert_array_equal(cut.data["p_value"], full.data["p_value"])
        assert cut.summary["center"] == full.summary["center"]
        assert cut.summary["tau"] == full.summary["tau"]
        assert cut.summary["n_filtered"] == int(low.sum())
        assert any("test_min_expected" in note for note in cut.summary["notes"])
        # Fewer tests in the step: the kept providers' q-values can only fall.
        kept = ~low
        assert (cut.data.loc[kept, "q_value"] <= full.data.loc[kept, "q_value"] + 1e-15).all()

    def test_limits_mode_is_unchanged(self):
        o, e = _physicians(np.random.default_rng(62), k=200, tau=0.2, lo=0.5, hi=40)
        a = funnel(y=o, n=e, measure="oe")
        b = funnel(y=o, n=e, measure="oe", test_min_expected=5)
        assert a.data["signal"].tolist() == b.data["signal"].tolist()

    @pytest.mark.parametrize("bad", [-1, float("nan"), "5", True])
    def test_rejects_bad_values(self, bad):
        with pytest.raises(ValueError, match="test_min_expected"):
            _r(test_min_expected=bad)


class TestSpeed:
    def test_a_thousand_provider_adjusted_funnel_is_fast(self):
        import time

        from qikit.spc import dist
        rng = np.random.default_rng(1)
        e = rng.uniform(30, 2000, 1000)
        o = rng.poisson(e * rng.gamma(50, 1 / 50, 1000))
        dist._WALK_CACHE.clear()
        dist._poisson_mean_solve.cache_clear()
        t = time.perf_counter()
        funnel(y=o, n=e, measure="oe", worse="higher")
        # ~0.3 s cold on a 2024 laptop (1.3 s in 0.9); generous for CI runners.
        assert time.perf_counter() - t < 1.5


# ---------------------------------------------------------------------------
# Choosing τ: tau_method="winsorized" | "spiegelhalter" | "ml", tau= fixed, prob_worse
# (docs/methods.md §4.16)
# ---------------------------------------------------------------------------

class TestTauMethods:
    def test_ml_matches_a_brute_force_maximum(self):
        from qikit.spc.limits import _mixture_loglik, tau2_ml
        rng = np.random.default_rng(71)
        for family in ("poisson", "binomial"):
            if family == "poisson":
                e = rng.uniform(3, 30, 300)
                o = rng.poisson(rng.gamma(1 / 0.2 ** 2, 0.2 ** 2, 300) * e).astype(float)
            else:
                e = rng.integers(20, 200, 300).astype(float)
                o = rng.binomial(e.astype(int), rng.beta(12, 88, 300)).astype(float)
            cl = o.sum() / e.sum()
            t2, (lo, hi) = tau2_ml(cl, o / e, e, np.ones(300, bool), family)
            grid = np.linspace(0, 3 * math.sqrt(t2) + 0.01, 3001)
            best = grid[int(np.argmax([_mixture_loglik(t, cl, o, e, family) for t in grid]))]
            assert math.sqrt(t2) == pytest.approx(best, abs=2 * (grid[1] - grid[0]))
            assert lo < math.sqrt(t2) < hi

    def test_ml_is_zero_under_the_null_at_small_k_more_often_than_not(self):
        from qikit.spc.limits import tau2_ml
        rng = np.random.default_rng(72)
        zeros = 0
        for _ in range(60):
            e = rng.uniform(3, 30, 30)
            o = rng.poisson(e).astype(float)
            zeros += tau2_ml(o.sum() / e.sum(), o / e, e, np.ones(30, bool), "poisson")[0] == 0
        assert zeros > 30

    def test_ml_interval_covers_the_truth(self):
        from qikit.spc.limits import tau2_ml
        rng = np.random.default_rng(73)
        hits = 0
        for _ in range(100):
            e = rng.uniform(3, 30, 200)
            o = rng.poisson(rng.gamma(1 / 0.2 ** 2, 0.2 ** 2, 200) * e).astype(float)
            _, (lo, hi) = tau2_ml(o.sum() / e.sum(), o / e, e, np.ones(200, bool), "poisson")
            hits += lo <= 0.2 <= hi
        assert 85 <= hits <= 100

    def test_ml_through_funnel_reports_its_interval(self):
        o, e = _physicians(np.random.default_rng(74), k=300, tau=0.25)
        s = funnel(y=o, n=e, measure="oe", tau_method="ml").summary
        lo, hi = s["tau_ci"]
        assert s["tau_method"] == "ml" and s["tau_source"] == "estimated"
        assert lo < s["tau"] < hi
        assert s["tau_estimated"] != s["tau"]  # the winsorized estimate, kept beside it
        assert funnel(y=o, n=e, measure="oe").summary["tau_ci"] is None

    def test_fixed_tau_is_used_and_this_periods_estimate_reported(self):
        o, e = _physicians(np.random.default_rng(75), k=300, tau=0.25)
        r = funnel(y=o, n=e, measure="oe", tau=0.2)
        core = _qic(y=o, n=e, chart="oep", funnel=True, tau_fixed=0.04)
        np.testing.assert_array_equal(np.sort(r.data["upper_outlier"]), np.sort(core.data["ucl"]))
        assert r.summary["tau"] == pytest.approx(0.2)
        assert r.summary["tau_source"] == "pre-specified"
        est = funnel(y=o, n=e, measure="oe").summary["tau"]
        assert r.summary["tau_estimated"] == pytest.approx(est)

    def test_fixed_tau_zero_is_the_unadjusted_chart(self):
        o, e = _physicians(np.random.default_rng(76), k=200, tau=0.3)
        fixed = funnel(y=o, n=e, measure="oe", tau=0.0).data
        plain = funnel(y=o, n=e, measure="oe", overdispersion=False).data
        np.testing.assert_array_equal(fixed["upper_outlier"], plain["upper_outlier"])
        np.testing.assert_array_equal(fixed["p_value"], plain["p_value"])

    def test_a_drifted_fixed_tau_says_so(self):
        o, e = _physicians(np.random.default_rng(77), k=400, tau=0.3)
        s = funnel(y=o, n=e, measure="oe", tau=0.1).summary
        assert any("differs from this period's estimate" in n for n in s["notes"])
        s = funnel(y=o, n=e, measure="oe", tau=s["tau_estimated"]).summary
        assert not any("differs from this period's estimate" in n for n in s["notes"])

    def test_fixed_tau_per_facet(self):
        rng = np.random.default_rng(78)
        o1, e1 = _physicians(rng, k=100, tau=0.1)
        o2, e2 = _physicians(rng, k=100, tau=0.3)
        df = pd.DataFrame({"o": np.r_[o1, o2], "e": np.r_[e1, e2],
                           "line": ["med"] * 100 + ["surg"] * 100})
        r = funnel(df, y="o", n="e", measure="oe", facets="line",
                   tau={"med": 0.1, "surg": 0.3})
        assert r.summary["by_facet"]["med"]["tau"] == pytest.approx(0.1)
        assert r.summary["by_facet"]["surg"]["tau"] == pytest.approx(0.3)
        with pytest.raises(ValueError, match="missing"):
            funnel(df, y="o", n="e", measure="oe", facets="line", tau={"med": 0.1})

    @pytest.mark.parametrize("bad", [-0.1, float("inf"), "0.2", True])
    def test_bad_tau_is_rejected(self, bad):
        with pytest.raises(ValueError, match="tau= must be a number"):
            _r(tau=bad)

    def test_tau_needs_the_adjusted_chart_and_facets_for_a_dict(self):
        with pytest.raises(ValueError, match="needs overdispersion=True"):
            _r(tau=0.2, overdispersion=False)
        with pytest.raises(ValueError, match="needs facets="):
            _r(tau={"a": 0.2})

    def test_small_k_note(self):
        s = _r().summary  # twelve surgeons
        assert any("With 12 providers" in n for n in s["notes"])
        assert not any("With 12 providers" in n for n in _r(tau=0.1).summary["notes"])


class TestProbWorse:
    def test_matches_monte_carlo_from_the_gamma_posterior(self):
        o, e = _physicians(np.random.default_rng(81), k=200, tau=0.3)
        r = funnel(y=o, n=e, measure="oe", worse="higher")
        cl, tau2 = r.summary["center"], r.summary["tau"] ** 2
        d = r.data.iloc[::20]
        draws = np.random.default_rng(0).gamma(
            (cl * cl / tau2 + d["numerator"].to_numpy())[:, None],
            1.0 / (cl / tau2 + d["denominator"].to_numpy())[:, None], (len(d), 40000))
        np.testing.assert_allclose(d["prob_worse"], (draws > cl).mean(1), atol=0.01)

    def test_matches_monte_carlo_from_the_beta_posterior(self):
        rng = np.random.default_rng(82)
        n = rng.integers(20, 300, 200).astype(float)
        y = rng.binomial(n.astype(int), np.clip(0.8 + 0.06 * rng.standard_normal(200), .01, .99))
        r = funnel(y=y, n=n, measure="proportion", worse="lower")
        cl, tau2 = r.summary["center"], r.summary["tau"] ** 2
        s = cl * (1 - cl) / tau2 - 1
        d = r.data.iloc[::20]
        draws = np.random.default_rng(1).beta(
            (cl * s + d["numerator"].to_numpy())[:, None],
            ((1 - cl) * s + d["denominator"].to_numpy() - d["numerator"].to_numpy())[:, None],
            (len(d), 40000))
        np.testing.assert_allclose(d["prob_worse"], (draws < cl).mean(1), atol=0.01)

    def test_nan_without_spread_and_independent_of_signal(self):
        d = _r(overdispersion=False).data
        assert d["prob_worse"].isna().all()
        a, b = _r(tau=0.3).data, _r(tau=0.3, signal="fdr").data
        np.testing.assert_array_equal(a["prob_worse"], b["prob_worse"])

    def test_incomplete_gamma_and_beta_identities(self):
        from qikit.spc import dist
        for k in (1, 4, 37, 400):
            for x in (0.5, 0.8 * k, 1.3 * k + 2):
                lower, upper = dist.gamma_tails(float(k), x)
                assert upper == pytest.approx(dist.poisson_tails(k - 1, x)[0], rel=1e-10)
                assert lower + upper == pytest.approx(1.0, abs=1e-12)
        for m in (6, 50, 700):
            for k in (1, m // 2, m):
                for p in (0.05, 0.4, 0.9):
                    lower, _ = dist.beta_tails(p, float(k), float(m - k + 1))
                    assert lower == pytest.approx(dist.binomial_tails(k, m, p)[1], rel=1e-10,
                                                  abs=1e-14)
