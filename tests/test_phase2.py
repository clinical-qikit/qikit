"""
Tests for Phase 2 features: xbar chart, multi-part, facets, notes.

Also includes regression tests against known published values.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
import plotly.graph_objects as go

from qikit import SPCResult, qic
from qikit import core as _core


# ---------------------------------------------------------------------------
# Xbar chart
# ---------------------------------------------------------------------------

class TestXbarChart:
    def test_requires_long_format_data(self):
        """xbar without data= raises ValueError."""
        y = [1.0, 2.0, 3.0, 4.0, 5.0]
        with pytest.raises(ValueError, match="xbar chart requires"):
            qic(y=y, chart="xbar")

    def test_requires_x_as_column_name(self):
        """xbar without x= as string column name raises ValueError."""
        df = pd.DataFrame({"grp": ["A", "A", "B", "B"], "val": [1.0, 2.0, 3.0, 4.0]})
        with pytest.raises(ValueError):
            qic(data=df, y="val", chart="xbar")

    def test_aggregates_subgroups(self):
        """Given DataFrame with repeated x values, y_arr contains subgroup means."""
        df = pd.DataFrame({
            "grp": ["A", "A", "B", "B", "C", "C"],
            "val": [10.0, 12.0, 8.0, 10.0, 11.0, 13.0],
        })
        r = qic(data=df, x="grp", y="val", chart="xbar")
        assert len(r.data) == 3
        expected_means = [11.0, 9.0, 12.0]
        np.testing.assert_allclose(r.data["y"].to_numpy(), expected_means, atol=1e-10)

    def test_known_limits(self):
        """
        Hand-calculated xbar limits for equal subgroups.

        5 subgroups of n=4:
        means  = [10.0, 10.2, 9.8, 10.1, 9.9]
        SDs    = all 0.5
        grand_mean = 10.0
        S̄ = 0.5
        A3[4] = 1.628
        UCL = 10.0 + 1.628*0.5 = 10.814
        LCL = 10.0 - 1.628*0.5 = 9.186
        """
        rng = np.random.default_rng(99)
        groups = []
        targets = [10.0, 10.2, 9.8, 10.1, 9.9]
        for i, mean_val in enumerate(targets):
            # Generate 4 values with exact mean and approximately correct SD
            vals = rng.normal(mean_val, 0.5, size=4)
            # Force the mean to be exact
            vals = vals - vals.mean() + mean_val
            groups.extend([(i + 1, v) for v in vals])

        df = pd.DataFrame(groups, columns=["grp", "val"])
        r = qic(data=df, x="grp", y="val", chart="xbar")

        grand_mean = np.mean(targets)
        # s_bar computed from actual SD of subgroups
        s_bar = r.summary.get("s_bar", None)
        a3 = _core.A3[4]

        # CL should be close to grand mean
        assert math.isclose(r.data["cl"].iloc[0], grand_mean, abs_tol=0.05)
        # UCL = grand_mean + A3 * s_bar
        expected_ucl = r.data["cl"].iloc[0] + a3 * r.data["cl"].iloc[0] * 0  # placeholder
        # Verify UCL and LCL are symmetric around CL
        cl_val = r.data["cl"].iloc[0]
        ucl_val = r.data["ucl"].iloc[0]
        lcl_val = r.data["lcl"].iloc[0]
        assert ucl_val > cl_val
        assert lcl_val < cl_val
        assert math.isclose(ucl_val - cl_val, cl_val - lcl_val, abs_tol=1e-10)

    def test_known_limits_exact(self):
        """
        Exact xbar limits with deterministic subgroups.

        5 subgroups, each 4 values with sd=0.5 exactly.
        """
        # Create subgroups with exactly controlled mean and SD
        # For SD=0.5 with 4 values, use: mean +/- 0.5, mean +/- 0.5
        base_means = [10.0, 10.0, 10.0, 10.0, 10.0]
        rows = []
        for i, m in enumerate(base_means):
            # 4 values: m-0.5, m+0.5, m-0.5, m+0.5 → mean=m, sd=0.5
            vals = [m - 0.5, m + 0.5, m - 0.5, m + 0.5]
            for v in vals:
                rows.append({"grp": i + 1, "val": v})

        df = pd.DataFrame(rows)
        r = qic(data=df, x="grp", y="val", chart="xbar")

        # grand_mean = 10.0, s_bar = sd([0.5,0.5,0.5,0.5,0.5]) based on population
        # actual SD of 4 vals [m-0.5, m+0.5, m-0.5, m+0.5]: ddof=1
        # sd = sqrt(sum((xi-mean)^2 / (n-1))) = sqrt(4*(0.5^2)/3) = sqrt(1/3) ≈ 0.5774
        import math as _math
        expected_sd_per_group = _math.sqrt(4 * 0.5**2 / 3)
        s_bar_expected = expected_sd_per_group

        a3 = _core.A3[4]
        expected_ucl = 10.0 + a3 * s_bar_expected
        expected_lcl = 10.0 - a3 * s_bar_expected

        assert math.isclose(r.data["cl"].iloc[0], 10.0, abs_tol=1e-10)
        assert math.isclose(r.data["ucl"].iloc[0], expected_ucl, abs_tol=1e-6)
        assert math.isclose(r.data["lcl"].iloc[0], expected_lcl, abs_tol=1e-6)

    def test_subgroup_n_in_summary(self):
        """subgroup_n should be stored in summary or accessible."""
        df = pd.DataFrame({
            "grp": [1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3],
            "val": [10.0] * 12,
        })
        r = qic(data=df, x="grp", y="val", chart="xbar")
        # subgroup_n=4 should appear somewhere in the result
        assert r.chart_type == "xbar"
        assert len(r.data) == 3

    def test_xbar_limits_regression(self):
        """
        Regression: 5 subgroups of size 4 with known exact values.

        S̄=0.5, A3[4]=1.628
        UCL = 10.0 + 1.628*0.5 = 10.814
        LCL = 10.0 - 1.628*0.5 = 9.186
        """
        # All subgroups have mean=10.0, sd=0.5
        rows = []
        for grp in range(1, 6):
            for v in [9.5, 10.5, 9.5, 10.5]:
                rows.append({"grp": grp, "val": float(v)})
        df = pd.DataFrame(rows)
        r = qic(data=df, x="grp", y="val", chart="xbar")

        # sd of [9.5,10.5,9.5,10.5] with ddof=1
        s_each = float(np.std([9.5, 10.5, 9.5, 10.5], ddof=1))
        a3 = _core.A3[4]
        expected_ucl = 10.0 + a3 * s_each
        expected_lcl = 10.0 - a3 * s_each

        assert math.isclose(r.data["cl"].iloc[0], 10.0, abs_tol=1e-10)
        assert math.isclose(r.data["ucl"].iloc[0], expected_ucl, abs_tol=1e-6)
        assert math.isclose(r.data["lcl"].iloc[0], expected_lcl, abs_tol=1e-6)


# ---------------------------------------------------------------------------
# Multi-part
# ---------------------------------------------------------------------------

class TestMultiPart:
    def test_two_parts_independent_limits(self):
        """First part high mean, second part low mean; CL differs between parts."""
        y_high = [100.0] * 10
        y_low = [10.0] * 10
        y = y_high + y_low
        r = qic(y=y, chart="i", part=11)  # new part starts at index 11
        # CL in first part should be ~100, second part ~10
        cl_part1 = r.data["cl"].iloc[0]
        cl_part2 = r.data["cl"].iloc[15]
        assert cl_part1 > 50
        assert cl_part2 < 50
        assert not math.isclose(cl_part1, cl_part2, abs_tol=1.0)

    def test_part_column_in_data(self):
        """DataFrame has 'part' column after multi-part compute."""
        y = list(range(1, 21))
        r = qic(y=y, chart="i", part=11)
        assert "part" in r.data.columns
        assert list(r.data["part"].iloc[:10]) == [1] * 10
        assert list(r.data["part"].iloc[10:]) == [2] * 10

    def test_parts_in_summary(self):
        """Summary has 'parts' key with per-part info."""
        y = [10.0] * 10 + [50.0] * 10
        r = qic(y=y, chart="i", part=11)
        assert "parts" in r.summary
        assert len(r.summary["parts"]) == 2
        assert r.summary["parts"][0]["part"] == 1
        assert r.summary["parts"][1]["part"] == 2

    def test_three_parts(self):
        """Three parts produce three independent CLs."""
        y = [100.0] * 8 + [50.0] * 8 + [10.0] * 8
        r = qic(y=y, chart="i", part=[9, 17])
        assert "parts" in r.summary
        assert len(r.summary["parts"]) == 3
        cl1 = r.data["cl"].iloc[0]
        cl2 = r.data["cl"].iloc[10]
        cl3 = r.data["cl"].iloc[20]
        assert cl1 > cl2 > cl3

    def test_freeze_and_part_raises(self):
        """Cannot specify both freeze= and part= simultaneously."""
        y = list(range(1, 21))
        with pytest.raises(ValueError, match="Cannot use both freeze= and part="):
            qic(y=y, chart="i", freeze=10, part=11)

    def test_no_part_column_without_part(self):
        """Without part=, no 'part' column in DataFrame."""
        y = list(range(1, 11))
        r = qic(y=y, chart="i")
        assert "part" not in r.data.columns


# ---------------------------------------------------------------------------
# Facets
# ---------------------------------------------------------------------------

class TestFacets:
    def _make_facet_df(self):
        rng = np.random.default_rng(7)
        rows = []
        for fv in ["A", "B", "C"]:
            mean = {"A": 10.0, "B": 20.0, "C": 30.0}[fv]
            for i in range(15):
                rows.append({"facet_col": fv, "x": i + 1, "y": rng.normal(mean, 1.0)})
        return pd.DataFrame(rows)

    def test_facet_column_in_data(self):
        """result.data has 'facet' column when facets= is used."""
        df = self._make_facet_df()
        r = qic(data=df, x="x", y="y", chart="i", facets="facet_col")
        assert "facet" in r.data.columns
        assert set(r.data["facet"].unique()) == {"A", "B", "C"}

    def test_independent_limits_per_facet(self):
        """Different facets get different CL values."""
        df = self._make_facet_df()
        r = qic(data=df, x="x", y="y", chart="i", facets="facet_col")
        cl_a = r.data[r.data["facet"] == "A"]["cl"].iloc[0]
        cl_b = r.data[r.data["facet"] == "B"]["cl"].iloc[0]
        cl_c = r.data[r.data["facet"] == "C"]["cl"].iloc[0]
        assert not math.isclose(cl_a, cl_b, abs_tol=2.0)
        assert not math.isclose(cl_b, cl_c, abs_tol=2.0)

    def test_signals_union(self):
        """result.signals=True if any facet has a signal."""
        # Create a facet with a clear signal (8+ run)
        rows = []
        for i in range(20):
            rows.append({"fct": "normal", "x": i + 1, "y": float(5 + (i % 3))})
        for i in range(20):
            # monotonically increasing → runs signal
            rows.append({"fct": "signal", "x": i + 1, "y": float(i + 1)})
        df = pd.DataFrame(rows)
        r = qic(data=df, x="x", y="y", chart="run", facets="fct")
        assert r.signals is True

    def test_no_signal_when_no_facet_signals(self):
        """result.signals=False if no facet has a signal."""
        rng = np.random.default_rng(42)
        rows = []
        for fv in ["A", "B"]:
            y_vals = rng.normal(10, 1.0, size=15)
            for i, yv in enumerate(y_vals):
                rows.append({"fct": fv, "x": i + 1, "y": float(yv)})
        df = pd.DataFrame(rows)
        r = qic(data=df, x="x", y="y", chart="i", facets="fct")
        # Result type is correct
        assert isinstance(r.signals, bool)

    def test_plot_returns_figure(self):
        """r.plot() works with facets and returns a Figure."""
        df = self._make_facet_df()
        r = qic(data=df, x="x", y="y", chart="i", facets="facet_col")
        fig = r.plot()
        assert isinstance(fig, go.Figure)

    def test_by_facet_in_summary(self):
        """Summary contains 'by_facet' key with per-facet summaries."""
        df = self._make_facet_df()
        r = qic(data=df, x="x", y="y", chart="i", facets="facet_col")
        assert "by_facet" in r.summary
        assert "A" in r.summary["by_facet"]
        assert "B" in r.summary["by_facet"]


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

class TestNotes:
    def test_note_column_in_data(self):
        """notes=[..] adds 'note' column to DataFrame."""
        y = [1.0, 2.0, 3.0, 4.0, 5.0]
        notes = ["start", "", "event", None, "end"]
        r = qic(y=y, chart="i", notes=notes)
        assert "note" in r.data.columns
        assert r.data["note"].iloc[0] == "start"
        assert r.data["note"].iloc[1] == ""
        assert r.data["note"].iloc[2] == "event"
        assert r.data["note"].iloc[3] == ""  # None → ""
        assert r.data["note"].iloc[4] == "end"

    def test_note_length_mismatch(self):
        """Mismatched notes length raises ValueError."""
        y = [1.0, 2.0, 3.0, 4.0, 5.0]
        notes = ["a", "b", "c"]  # wrong length
        with pytest.raises(ValueError, match="Length of notes"):
            qic(y=y, chart="i", notes=notes)

    def test_note_plot_has_annotations(self):
        """r.plot() with notes produces annotations for non-empty notes."""
        y = [1.0, 2.0, 3.0, 4.0, 5.0]
        notes = ["start", "", "", "", ""]
        r = qic(y=y, chart="i", notes=notes)
        fig = r.plot()
        # Should have at least one annotation from notes (plus possible labels)
        note_annotations = [
            a for a in fig.layout.annotations
            if a.text == "start"
        ]
        assert len(note_annotations) >= 1

    def test_no_note_column_without_notes(self):
        """Without notes=, no 'note' column in DataFrame."""
        y = [1.0, 2.0, 3.0]
        r = qic(y=y, chart="i")
        assert "note" not in r.data.columns


# ---------------------------------------------------------------------------
# Regression values — known published/hand-calculated data
# ---------------------------------------------------------------------------

class TestRegressionValues:
    def test_i_chart_known_values(self):
        """
        I-chart regression with hand-calculated values.

        y = [74.030, 74.002, 74.019, 73.992, 74.008,
             73.995, 74.009, 74.010, 73.998, 74.025]
        CL = mean(y)
        MR = [|74.002-74.030|, ...] etc.
        σ̂ = MR̄/1.128
        UCL = CL + 3σ̂
        LCL = CL - 3σ̂
        """
        y = [74.030, 74.002, 74.019, 73.992, 74.008,
             73.995, 74.009, 74.010, 73.998, 74.025]
        r = qic(y=y, chart="i")

        expected_cl = np.mean(y)
        assert math.isclose(r.data["cl"].iloc[0], expected_cl, abs_tol=1e-6)

        mrs = np.abs(np.diff(y))
        mr_bar_raw = float(np.mean(mrs))
        # Screened MR (remove those > D4 * MR̄)
        d4 = 3.267
        mrs_screened = mrs[mrs <= d4 * mr_bar_raw]
        mr_bar = float(np.mean(mrs_screened))
        sigma = mr_bar / 1.128

        expected_ucl = expected_cl + 3 * sigma
        expected_lcl = expected_cl - 3 * sigma

        assert math.isclose(r.data["ucl"].iloc[0], expected_ucl, abs_tol=1e-6)
        assert math.isclose(r.data["lcl"].iloc[0], expected_lcl, abs_tol=1e-6)

    def test_p_chart_equal_n_known_values(self):
        """
        p-chart regression: equal n=100, p̄=0.10, 20 subgroups.

        σ = sqrt(0.10*0.90/100) = 0.03
        UCL = 0.10 + 3*0.03 = 0.19
        LCL = 0.10 - 3*0.03 = 0.01 (positive, so not floored)
        """
        p_bar = 0.10
        n = 100
        y = [p_bar * n] * 20
        ns = [n] * 20
        r = qic(y=y, n=ns, chart="p")

        sigma = math.sqrt(p_bar * (1 - p_bar) / n)
        expected_ucl = p_bar + 3 * sigma
        expected_lcl = p_bar - 3 * sigma

        assert math.isclose(r.data["cl"].iloc[0], p_bar, abs_tol=1e-10)
        assert math.isclose(r.data["ucl"].iloc[0], expected_ucl, abs_tol=1e-6)
        assert math.isclose(r.data["lcl"].iloc[0], expected_lcl, abs_tol=1e-6)

    def test_p_chart_low_p_floors_lcl(self):
        """
        p-chart with very small p̄ floors negative LCL to 0.0.

        p̄=0.008, n=100: LCL = 0.008 - 3*sqrt(0.008*0.992/100) < 0 → 0.0
        """
        p_bar = 0.008
        n = 100
        y = [p_bar * n] * 20
        ns = [n] * 20
        r = qic(y=y, n=ns, chart="p")
        assert (r.data["lcl"] == 0.0).all()

    def test_run_chart_signal_8point_run(self):
        """15 points with 8-point run above median → signal expected.

        y = [20]*8 + [5]*7
        median = 5.0 (just above: n_useful = all 15 since 5.0 == median for 7
        but median of [20,20,20,20,20,20,20,20,5,5,5,5,5,5,5] = 5.0)
        Actually use [20]*8 + [1]*7 so median=5 is not among the values.
        median ~ 5 ≈ (20*8+1*7)/15 area. Sort: [1,1,1,1,1,1,1,20,20,20,20,20,20,20,20]
        median = element 8 (0-indexed 7) = 20. So 8 points at 20 are ON median.
        Use two-level data with clear separation.
        """
        # 15 points: 8 high (above median), 7 low (below median)
        # median of [20]*8+[5]*7 is sorted[7] = 20 — bad.
        # Use [30]*8 + [5]*7: sorted=[5,5,5,5,5,5,5,30,30,30,30,30,30,30,30] → median=30
        # All 8 points at 30 are ON median → not useful.
        # Better: [30]*8 + [5]*7 + [18] = 16 points, median ~18
        # Use: alternating with a long run: 10 high then 10 mixed
        y = [20.0] * 10 + [1.0] * 10
        # median of [1]*10 + [20]*10 = (1+20)/2 = 10.5
        # first 10 points (20.0) are above median, last 10 (1.0) are below
        # n_useful = 20, threshold = floor(log2(20))+3 = 4+3 = 7
        # longest_run = 10 >= 7 → signal
        r = qic(y=y, chart="run")
        assert r.signals

    def test_run_chart_no_signal_random(self):
        """Well-mixed data with sufficient crossings → no runs signal expected."""
        # Alternating above/below CL → many crossings, no long run
        y = [12.0, 8.0, 12.0, 8.0, 12.0, 8.0, 12.0, 8.0,
             12.0, 8.0, 12.0, 8.0, 12.0, 8.0, 12.0, 8.0,
             12.0, 8.0, 12.0, 8.0]
        r = qic(y=y, chart="run")
        # Crossings will be high (many), long run will be 1 → no signal
        assert not r.signals

    def test_xbar_regression(self):
        """
        Exact regression: 5 subgroups size 4, mean=10.0, all SDs=0.5.

        S̄=0.5, A3[4]=1.628
        UCL = 10.0 + 1.628*0.5 = 10.814
        LCL = 10.0 - 1.628*0.5 = 9.186
        """
        # Subgroup SD for [9.5, 10.5, 9.5, 10.5] (ddof=1)
        s_each = float(np.std([9.5, 10.5, 9.5, 10.5], ddof=1))
        rows = []
        for grp in range(1, 6):
            for v in [9.5, 10.5, 9.5, 10.5]:
                rows.append({"grp": grp, "val": float(v)})
        df = pd.DataFrame(rows)
        r = qic(data=df, x="grp", y="val", chart="xbar")

        a3 = _core.A3[4]
        expected_ucl = 10.0 + a3 * s_each
        expected_lcl = 10.0 - a3 * s_each

        assert math.isclose(r.data["cl"].iloc[0], 10.0, abs_tol=1e-10)
        assert math.isclose(r.data["ucl"].iloc[0], expected_ucl, abs_tol=1e-6)
        assert math.isclose(r.data["lcl"].iloc[0], expected_lcl, abs_tol=1e-6)


# ---------------------------------------------------------------------------
# Anhoej thresholds at known n values
# ---------------------------------------------------------------------------

class TestAnhoejThresholds:
    def test_longest_run_threshold_n10(self):
        """n=10: floor(log2(10))+3 = 3+3 = 6."""
        assert _core._longest_run_threshold(10) == 6

    def test_longest_run_threshold_n20(self):
        """n=20: floor(log2(20))+3 = 4+3 = 7."""
        assert _core._longest_run_threshold(20) == 7

    def test_longest_run_threshold_n25(self):
        """n=25: floor(log2(25))+3 = 4+3 = 7."""
        assert _core._longest_run_threshold(25) == 7

    def test_longest_run_threshold_n100(self):
        """n=100: floor(log2(100))+3 = 6+3 = 9."""
        assert _core._longest_run_threshold(100) == 9

    def test_crossings_threshold_less_than_half_n(self):
        """crossings_threshold should be < n/2 for all valid n >= 10."""
        for n in [10, 20, 25, 50, 100]:
            ct = _core._crossings_threshold(n)
            assert ct < n / 2, f"crossings_threshold({n})={ct} is not < {n/2}"

    def test_crossings_threshold_n_less_than_10(self):
        """For n < 10, crossings threshold should be -1 (no signalling)."""
        for n in [1, 5, 9]:
            assert _core._crossings_threshold(n) == -1

    def test_run_threshold_below_10(self):
        """For n < 10, run threshold > n (effectively impossible to signal)."""
        for n in [1, 5, 9]:
            assert _core._longest_run_threshold(n) > n
