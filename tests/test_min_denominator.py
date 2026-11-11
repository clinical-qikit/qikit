"""
Minimum denominators from a reliability target: FunnelResult.min_denominator() and
funnel_rollup() (methods §4.14).

The defining property is that the floor agrees with the `reliability` column: a
provider is at or above the floor exactly when its reliability is at or above the target.
"""

from __future__ import annotations

import math
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import qikit
from qikit import funnel, funnel_rollup
from qikit.core.shrinkage import Prior, min_denominator

ROOT = Path(__file__).resolve().parent.parent
TARGETS = [0.5, 0.7, 0.9]


def _quiet(fn, *args, **kw):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return fn(*args, **kw)


def _physicians(k=240, seed=3):
    """Physicians in groups in hospitals, with real spread at every level."""
    rng = np.random.default_rng(seed)
    group = np.arange(k) // 8
    hospital = group // 6
    effect = (rng.normal(0, 0.25, k) + rng.normal(0, 0.15, group.max() + 1)[group]
              + rng.normal(0, 0.10, hospital.max() + 1)[hospital])
    exp = rng.gamma(2.0, 12.0, k)
    cases = rng.integers(20, 400, k)
    p = np.clip(0.15 * np.exp(effect), 0.01, 0.9)
    return pd.DataFrame({
        "doc": [f"d{i:03d}" for i in range(k)], "group": [f"g{g:02d}" for g in group],
        "hospital": [f"h{h}" for h in hospital], "campus": np.where(hospital % 2, "N", "S"),
        "exp": exp, "obs": rng.poisson(exp * np.exp(effect)).astype(float),
        "cases": cases, "events": rng.binomial(cases, p),
        "days": rng.integers(200, 4000, k).astype(float),
    }).assign(infections=lambda f: rng.poisson(f["days"] * 0.02 * np.exp(effect)))


CALLS = {
    "oe": dict(y="obs", n="exp", measure="oe"),
    "proportion": dict(y="events", n="cases", measure="proportion"),
    "rate": dict(y="infections", n="days", measure="rate"),
}


def _stays(k=60, seed=5):
    rng = np.random.default_rng(seed)
    n = rng.integers(15, 120, k)
    mean = 5.0 * np.exp(rng.normal(0, 0.2, k))
    return pd.DataFrame({
        "doc": np.repeat([f"d{i:02d}" for i in range(k)], n),
        "los": np.concatenate([rng.gamma(2.0, m / 2.0, c) for m, c in zip(mean, n)]),
    })


# ---------------------------------------------------------------------------
# The inversion itself
# ---------------------------------------------------------------------------

class TestCore:
    def test_counts_and_proportions_closed_form(self):
        counts = Prior(1.1, 0.04, 1.1, False, None)
        assert min_denominator(counts, 0.7) == pytest.approx(0.7 / 0.3 * 1.1 / 0.04)
        s = 0.2 * 0.8 / 0.0025 - 1.0
        beta = Prior(0.2, 0.0025, 0.2, False, (0.2 * s, 0.8 * s), True)
        assert min_denominator(beta, 0.9) == pytest.approx(9.0 * s)

    def test_no_spread_has_no_floor_and_tau2_overrides(self):
        flat = Prior(1.0, 0.0, 1.0, False, None)
        assert math.isinf(min_denominator(flat, 0.7))
        assert min_denominator(flat, 0.5, tau2=0.25) == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# FunnelResult.min_denominator()
# ---------------------------------------------------------------------------

class TestMinDenominator:
    @pytest.mark.parametrize("measure", list(CALLS))
    def test_floor_agrees_with_the_reliability_column(self, measure):
        r = _quiet(funnel, _physicians(), unit="doc", **CALLS[measure])
        m = r.min_denominator(TARGETS)
        assert m["reliability"].tolist() == TARGETS
        for row in m.itertuples():
            reliable = r.data["reliability"] >= row.reliability
            assert row.n_above == int(reliable.sum())
            assert (r.data["denominator"] >= row.min_denominator).equals(reliable)
            assert row.n_above + row.n_below == row.n_providers == len(r.data)
            assert row.volume_above == pytest.approx(r.data["denominator"][reliable].sum())
            assert row.min_low <= row.min_denominator <= row.min_high
        assert m["min_denominator"].is_monotonic_increasing
        assert 0 < m["n_above"].iloc[1] < len(r.data)

    def test_mean_floor_is_in_cases_and_agrees(self):
        r = _quiet(funnel, _stays(), y="los", measure="mean", unit="doc")
        m = r.min_denominator(0.7)
        row = m.iloc[0]
        assert row["denominator_unit"] == "cases"
        assert row["n_above"] == int((r.data["reliability"] >= 0.7).sum())
        # cases needed = R/(1 − R) · within-case variance / τ²
        phi, tau, center = r.summary["within_dispersion"], row["tau"], row["center"]
        assert row["min_denominator"] == pytest.approx(0.7 / 0.3 * phi * center / tau ** 2)

    def test_fixed_tau_gives_the_closed_form_and_no_range(self):
        d = _physicians()
        r = _quiet(funnel, d, unit="doc", tau=0.3, **CALLS["oe"])
        row = r.min_denominator(0.7).iloc[0]
        assert row["min_denominator"] == pytest.approx(0.7 / 0.3 * r.summary["center"] / 0.09)
        assert math.isnan(row["min_low"]) and math.isnan(row["min_high"])
        assert r.summary["estimate_tau_ci"] is None
        p = _quiet(funnel, d, unit="doc", tau=0.04, **CALLS["proportion"])
        c = p.summary["center"]
        assert p.min_denominator(0.7)["min_denominator"].iloc[0] == pytest.approx(
            0.7 / 0.3 * (c * (1 - c) / 0.04 ** 2 - 1))

    def test_no_spread_gives_no_floor_and_says_so(self):
        rng = np.random.default_rng(0)
        d = pd.DataFrame({"u": range(40), "n": [50] * 40})
        d["y"] = rng.binomial(1000, 0.1, 40) // 20          # far less spread than chance
        r = _quiet(funnel, d, y="y", n="n", measure="proportion", unit="u")
        assert r.summary["estimate_tau"] == 0
        m = r.min_denominator([0.5, 0.7])
        assert m["min_denominator"].isna().all()
        assert (m["n_above"] == 0).all() and (m["n_below"] == 40).all()
        assert all("no measurable spread" in note for note in m["note"])
        assert any("No minimum denominator" in note for note in m.attrs["notes"])

    def test_an_unadjusted_chart_has_no_reliability(self):
        r = _quiet(funnel, _physicians(), unit="doc", overdispersion=False, **CALLS["oe"])
        m = r.min_denominator()
        assert math.isnan(m["min_denominator"].iloc[0])
        assert "overdispersion=True" in m["note"].iloc[0]

    def test_against_the_model_uses_the_pooled_prior(self):
        r = _quiet(funnel, _physicians(), unit="doc", compare_to="model", **CALLS["oe"])
        row = r.min_denominator(0.7).iloc[0]
        assert row["min_denominator"] > 0
        assert row["n_above"] == int((r.data["reliability"] >= 0.7).sum())

    def test_few_providers_are_told_to_report_the_range(self):
        r = _quiet(funnel, _physicians(k=24), unit="doc", **CALLS["oe"])
        notes = r.min_denominator().attrs["notes"]
        assert len(notes) == 1 and ("24 providers" in notes[0] or "lower bound" in notes[0])

    def test_facets_come_first_one_row_per_facet_and_target(self):
        d = _physicians()
        r = _quiet(funnel, d, unit="doc", facets="campus", **CALLS["proportion"])
        m = r.min_denominator(TARGETS)
        assert list(m.columns[:2]) == ["campus", "reliability"]
        assert len(m) == 2 * len(TARGETS)
        for campus, part in m.groupby("campus"):
            alone = _quiet(funnel, d[d.campus == campus], unit="doc", **CALLS["proportion"])
            assert part["min_denominator"].to_numpy() == pytest.approx(
                alone.min_denominator(TARGETS)["min_denominator"].to_numpy())
            assert part["n_providers"].iloc[0] == (d.campus == campus).sum()

    def test_excluded_providers_are_not_counted(self):
        d = _physicians().assign(skip=lambda f: f.index < 10)
        r = _quiet(funnel, d, unit="doc", exclude="skip", **CALLS["oe"])
        row = r.min_denominator(0.5).iloc[0]
        assert row["n_providers"] == len(d) - 10

    def test_a_phi_column_reports_effective_denominators(self):
        d = _physicians().assign(phi=2.0)
        r = _quiet(funnel, d, unit="doc", within_dispersion="phi", **CALLS["oe"])
        row = r.min_denominator(0.7).iloc[0]
        assert row["denominator_unit"].startswith("effective ")
        assert row["n_above"] == int((r.data["effective_denominator"]
                                      >= row["min_denominator"]).sum())

    @pytest.mark.parametrize("measure, unit", [
        ("oe", "expected events (exp)"), ("proportion", "cases (cases)"),
        ("rate", "exposure (days)")])
    def test_the_unit_of_the_floor_is_named(self, measure, unit):
        r = _quiet(funnel, _physicians(), unit="doc", **CALLS[measure])
        m = r.min_denominator()
        assert m["denominator_unit"].iloc[0] == unit
        assert unit in m["note"].iloc[0] and "are below" in m["note"].iloc[0]

    @pytest.mark.parametrize("bad", [0, 1, 1.5, -0.2, "0.7", True, [0.7, 1.0], []])
    def test_targets_outside_zero_to_one_are_refused(self, bad):
        r = _quiet(funnel, _physicians(), unit="doc", **CALLS["oe"])
        with pytest.raises(ValueError, match="reliability="):
            r.min_denominator(bad)

    def test_the_example_data(self):
        d = pd.read_csv(ROOT / "data/examples/physician_mortality_oe.csv")
        r = _quiet(funnel, d, y="observed_deaths", n="expected_deaths", measure="oe",
                   unit="physician")
        m = r.min_denominator(TARGETS)
        tau, center = r.summary["estimate_tau"], m["center"].iloc[0]
        assert m["min_denominator"].to_numpy() == pytest.approx(
            [t / (1 - t) * center / tau ** 2 for t in TARGETS])
        assert m["n_above"].tolist() == [int((r.data["reliability"] >= t).sum())
                                         for t in TARGETS]


# ---------------------------------------------------------------------------
# funnel_rollup()
# ---------------------------------------------------------------------------

class TestRollup:
    LEVELS = ["doc", "group", "hospital"]

    def test_each_level_is_its_own_funnel(self):
        d = _physicians()
        out = _quiet(funnel_rollup, d, units=self.LEVELS, reliability=[0.7, 0.9],
                     **CALLS["oe"])
        assert out.columns[0] == "level"
        assert out["level"].tolist() == [lv for lv in self.LEVELS for _ in range(2)]
        for level in self.LEVELS:
            alone = _quiet(funnel, d, unit=level, **CALLS["oe"]).min_denominator([0.7, 0.9])
            got = out[out.level == level].drop(columns="level").reset_index(drop=True)
            pd.testing.assert_frame_equal(got, alone)
        assert out[out.reliability == 0.7]["n_providers"].tolist() == [240, 30, 5]

    def test_coarser_levels_hold_more_volume_per_unit(self):
        out = _quiet(funnel_rollup, _physicians(), units=self.LEVELS, **CALLS["proportion"])
        doc, group = out.iloc[0], out.iloc[1]
        assert group["share_above"] > doc["share_above"]
        assert (out["n_above"] + out["n_below"] == out["n_providers"]).all()

    def test_notes_carry_the_level(self):
        out = _quiet(funnel_rollup, _physicians(), units=self.LEVELS, **CALLS["oe"])
        assert any(note.startswith("hospital: ") for note in out.attrs["notes"])

    def test_one_level_as_a_string_and_labels_are_left_out(self):
        d = _physicians()
        out = _quiet(funnel_rollup, d, units="group", label="doc", **CALLS["oe"])
        assert out["level"].tolist() == ["group"]

    @pytest.mark.parametrize("kw, match", [
        (dict(units=["doc"], unit="doc"), "sets unit= itself"),
        (dict(units=None), "units= needs"),
        (dict(units=["doc", "grp"]), "is not a column"),
    ])
    def test_errors_name_the_fix(self, kw, match):
        with pytest.raises(ValueError, match=match):
            funnel_rollup(_physicians(), **{**CALLS["oe"], **kw})

    def test_needs_a_frame(self):
        with pytest.raises(ValueError, match="needs data="):
            funnel_rollup(units=["doc"], y=[1, 2], n=[1.0, 2.0], measure="oe")


# ---------------------------------------------------------------------------
# What an agent reads
# ---------------------------------------------------------------------------

class TestAgentSurface:
    def test_exported_and_described_in_the_words_people_use(self):
        assert "funnel_rollup" in qikit.__all__
        doc = qikit.FunnelResult.min_denominator.__doc__
        for phrase in ("minimum denominator", "minimum sample size", "reliability",
                       "above and below"):
            assert phrase in doc
        assert "min_denominator" in qikit.FunnelResult.__doc__
        assert "min_denominator" in qikit.__doc__ and "funnel_rollup" in qikit.__doc__
        assert "estimate_tau_ci" in funnel.__doc__

    @pytest.mark.parametrize("path", ["src/qikit/AGENTS.md", "README.md", "llms.txt",
                                      "skills/minimum-denominators/SKILL.md",
                                      "skills/provider-funnels/SKILL.md"])
    def test_the_agent_docs_name_the_calls(self, path):
        text = (ROOT / path).read_text(encoding="utf-8")
        assert "min_denominator" in text
        if "provider-funnels" not in path:
            assert "funnel_rollup" in text

    def test_the_skill_says_what_to_ask(self):
        text = (ROOT / "skills/minimum-denominators/SKILL.md").read_text(encoding="utf-8")
        head = text.split("---")[1]
        assert "minimum denominator" in head and "roll" in head
        for ask in ("reliability", "level", "peer group", "period"):
            assert ask in text
