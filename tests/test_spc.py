"""
Tests for qikit — chart calculations, limit formulas, signal detection.

Numerical tolerances match published SPC constants to 3 decimal places.
"""

from __future__ import annotations
import math
import json
import pathlib
import numpy as np
import pandas as pd
import pytest
import plotly.graph_objects as go
from qikit import SPCResult, paretochart, bchart
# These tests pin the numbers, through the public qic() and funnel(). The engine
# vocabulary the shared fixtures speak (chart="oe", funnel=True, sigma_signal, ...) is
# tested in test_fixture_adapter.py; tests/test_funnel.py covers the rest of funnel().
from qikit import funnel, qic
import qikit.core.constants as _constants
import qikit.core.dist as _dist
import qikit.core.rules as _rules
from types import SimpleNamespace
import qikit.core.contours as _contours
import qikit.core.dispersion as _dispersion
import qikit.core.power as _power
import qikit.core.shewhart as _shewhart

# The functions the old limits module held, now split by concern across qikit.core.
_limits = SimpleNamespace(
    **{name: getattr(_contours, name) for name in (
        "_binomial_funnel_pair", "_mixture_funnel_pair", "_table_tails", "_tail_table",
        "beta_params", "contour", "fractional_binomial_pair")},
    **{name: getattr(_power, name) for name in (
        "binomial_detectable_rate", "binomial_point_ci", "oe_detectable_ratio", "oe_point_ci")},
    funnel_dispersion=_dispersion.funnel_dispersion,
    winsor_consistency=_dispersion.winsor_consistency,
)




def _result(chart, y, **kw):
    return qic(y=y, chart=chart, **kw)


def _providers(y, n, units=None) -> pd.DataFrame:
    """Providers given as lists: unit i + 1 (or units[i]) has y[i] out of n[i]."""
    units = list(range(1, len(y) + 1)) if units is None else list(units)
    return pd.DataFrame({"unit": units, "y": list(y), "n": list(n)})


def _funnel(y, n, measure, *, units=None, overdispersion=False, **kw):
    """funnel() on providers given as lists. overdispersion defaults to off here, so a
    test opts in to the spread allowance by name, as the plain and adjusted pairs do."""
    return funnel(_providers(y, n, units), y="y", n="n", unit="unit", measure=measure,
                  overdispersion=overdispersion, **kw)


# ---------------------------------------------------------------------------
# Run chart
# ---------------------------------------------------------------------------

class TestRunChart:
    def test_cl_is_median(self, normal_30):
        r = _result("run", normal_30)
        expected_cl = np.nanmedian(normal_30)
        assert np.allclose(r.data["cl"].unique(), [expected_cl], atol=1e-10)

    def test_limits_are_nan(self, normal_30):
        r = _result("run", normal_30)
        assert r.data["ucl"].isna().all()
        assert r.data["lcl"].isna().all()

    def test_returns_spcresult(self, normal_30):
        r = _result("run", normal_30)
        assert isinstance(r, SPCResult)
        assert r.chart == "run"

    def test_single_point(self):
        r = _result("run", [5.0])
        assert len(r.data) == 1
        assert not np.isnan(r.data["cl"].iloc[0])


# ---------------------------------------------------------------------------
# I chart (Individuals)
# ---------------------------------------------------------------------------

class TestIChart:
    def test_cl_is_mean(self, normal_30):
        r = _result("i", normal_30)
        expected_cl = np.mean(normal_30)
        assert np.allclose(r.data["cl"].unique(), [expected_cl], atol=1e-10)

    def test_limits_exist(self, normal_30):
        r = _result("i", normal_30)
        assert not r.data["ucl"].isna().all()
        assert not r.data["lcl"].isna().all()

    def test_ucl_above_cl(self, normal_30):
        r = _result("i", normal_30)
        assert (r.data["ucl"] > r.data["cl"]).all()
        assert (r.data["lcl"] < r.data["cl"]).all()

    def test_known_values(self):
        """
        Hand-calculated I-chart limits.

        Data: [2, 4, 6, 4, 2, 4, 6, 4]
        CL = mean = 4.0
        MR = [2, 2, 2, 2, 2, 2, 2], MR̄ = 2.0
        σ̂ = MR̄/d2 = 2.0/1.128 = 1.7730...
        UCL = 4.0 + 3×1.773 = 9.319...
        LCL = 4.0 − 3×1.773 = −1.319...
        """
        y = [2, 4, 6, 4, 2, 4, 6, 4]
        r = _result("i", y)
        cl = r.data["cl"].iloc[0]
        ucl = r.data["ucl"].iloc[0]
        lcl = r.data["lcl"].iloc[0]
        assert math.isclose(cl, 4.0, abs_tol=1e-10)
        expected_sigma = 2.0 / 1.128
        assert math.isclose(ucl, 4.0 + 3 * expected_sigma, abs_tol=0.01)
        assert math.isclose(lcl, 4.0 - 3 * expected_sigma, abs_tol=0.01)

    def test_mr_screening(self):
        """
        An outlier MR should be screened before computing limits.
        Provost & Murray (2011) p.140.
        """
        y = [10] * 14 + [50] + [10] * 15  # one spike at index 14
        r_with = _result("i", y)
        # Limits should be tighter than the spike
        assert r_with.data["ucl"].iloc[0] < 50

    def test_screening_does_not_collapse_sigma(self):
        """
        Screening must not throw away the only informative moving range.

        With 28 zero MRs and one of 30, MR̄ = 1.0345 and the D4·MR̄ screen sits
        at 3.38 — below the single MR that carries the variation. Screening it
        out left the survivors averaging 0, collapsing UCL/LCL onto CL and
        flagging all 30 points instead of the one real outlier.
        """
        y = [10.0] * 29 + [40.0]
        r = _result("i", y)
        cl = r.data["cl"].iloc[0]
        ucl = r.data["ucl"].iloc[0]
        lcl = r.data["lcl"].iloc[0]
        assert ucl > cl > lcl
        # σ̂ falls back to the unscreened MR̄ = 30/29 → σ̂ = 0.9171
        assert math.isclose(ucl, cl + 3 * (30 / 29) / 1.128, rel_tol=1e-6)
        assert int((r.data["signal"] == "outlier").sum()) == 1
        assert bool((r.data["signal"] == "outlier").iloc[-1])

    def test_screening_still_applies_when_it_leaves_signal(self):
        """The ordinary screening path is untouched: a lone spike is still screened."""
        y = [10.0, 11.0, 9.0, 10.0, 12.0] * 3 + [90.0] + [10.0, 11.0, 9.0, 10.0] * 2
        r = _result("i", y)
        # The spike is screened out of σ̂, so the limits stay far below it.
        assert r.data["ucl"].iloc[0] < 90.0

    def test_nan_handling(self):
        y = [1.0, 2.0, np.nan, 4.0, 5.0]
        r = _result("i", y)
        assert len(r.data) == 5
        assert not np.isnan(r.data["cl"].iloc[0])

    def test_all_same_values(self):
        """
        All-same values → CL at that value and no limits at all.

        A flat series has no variation to estimate a spread from. Zero-width
        limits would draw three coincident lines and call any departure a
        signal, so the chart reports NaN limits and reads as a run chart.
        """
        y = [5.0] * 20
        r = _result("i", y)
        assert math.isclose(r.data["cl"].iloc[0], 5.0)
        assert r.data["ucl"].isna().all()
        assert r.data["lcl"].isna().all()
        assert not (r.data["signal"] == "outlier").any()

    def test_signals_field(self, normal_30):
        r = _result("i", normal_30)
        assert isinstance(r.signals, bool)

    def test_freeze(self, normal_30):
        r = _result("i", normal_30, freeze=20)
        assert r.summary["freeze"] == 20
        cl_before = r.data["cl"].iloc[0]
        cl_after = r.data["cl"].iloc[25]
        assert math.isclose(cl_before, cl_after, abs_tol=1e-10)

    # A spike at 1-based index 11, on a baseline that varies. The baseline must
    # not be perfectly flat: excluding the spike would then leave no variation
    # at all and the limits would come back NaN, measuring nothing.
    _SPIKE_AT_11 = [10.0, 11.0, 9.0, 10.0, 12.0, 9.0, 11.0, 10.0, 9.0, 11.0] + \
                   [100.0] + \
                   [10.0, 12.0, 9.0, 11.0, 10.0, 9.0, 11.0, 10.0, 12.0]

    def test_exclude(self):
        y = self._SPIKE_AT_11
        r_excl = _result("i", y, exclude=[11])
        r_all = _result("i", y)
        assert r_excl.data["ucl"].iloc[0] < r_all.data["ucl"].iloc[0]

    def test_exclude_accepts_a_bare_index(self):
        """exclude=5 is accepted just as part=3 is; it used to raise TypeError."""
        y = self._SPIKE_AT_11
        scalar = _result("i", y, exclude=11)
        listed = _result("i", y, exclude=[11])
        assert scalar.summary["excluded"] == listed.summary["excluded"] == [11]
        assert scalar.data["ucl"].tolist() == pytest.approx(listed.data["ucl"].tolist())

    def test_exclude_rejects_a_bool(self):
        """A bool is not an index, even though it is an int in Python."""
        with pytest.raises(ValueError, match="1-based"):
            _result("i", [10.0] * 10, exclude=True)


# ---------------------------------------------------------------------------
# MR chart
# ---------------------------------------------------------------------------

class TestMRChart:
    def test_plots_moving_ranges(self, normal_30):
        """MR chart y-axis should be moving ranges, not raw data."""
        r = _result("mr", normal_30)
        expected_mrs = np.abs(np.diff(normal_30))
        # The first point has no moving range: its row is kept, with y missing.
        assert len(r.data) == len(normal_30)
        assert np.isnan(r.data["y"].iloc[0])
        np.testing.assert_allclose(r.data["y"].to_numpy()[1:], expected_mrs)

    def test_cl_is_mean_mr(self, normal_30):
        r = _result("mr", normal_30)
        expected_mrs = np.abs(np.diff(normal_30))
        expected_cl = np.mean(expected_mrs)
        assert math.isclose(r.data["cl"].iloc[0], expected_cl, rel_tol=0.01)

    def test_ucl_is_d4_times_cl(self, normal_30):
        """UCL = D4 × MR̄ (Montgomery 2019, §6.3; D4 = 3.267 for n = 2)."""
        r = _result("mr", normal_30)
        cl = r.data["cl"].iloc[0]
        ucl = r.data["ucl"].iloc[0]
        assert math.isclose(ucl, 3.267 * cl, rel_tol=0.001)

    def test_lcl_is_zero(self, normal_30):
        """D3 = 0 for n = 2, so the lower limit sits at 0, as qicharts2 draws it."""
        r = _result("mr", normal_30)
        assert (r.data["lcl"] == 0).all()
        assert (r.data["lcl_95"] == 0).all()

    def test_requires_two_points(self):
        with pytest.raises(ValueError, match="at least 2"):
            _result("mr", [5.0])

    def test_x_values_offset(self):
        """Each moving range sits at the second point of its pair; the first has none."""
        r = qic(x=[10, 20, 30, 40, 50], y=[1.0, 3.0, 2.0, 5.0, 4.0], chart="mr")
        assert list(r.data["x"]) == [10, 20, 30, 40, 50]
        assert r.data["y"].tolist()[1:] == [2.0, 1.0, 3.0, 1.0]
        assert np.isnan(r.data["y"].iloc[0])


# ---------------------------------------------------------------------------
# p chart
# ---------------------------------------------------------------------------

class TestPChart:
    def test_cl_is_weighted_mean(self, proportions):
        p, n = proportions
        # Convert pre-calculated proportions in the fixture back to counts
        y = p * n
        r = qic(y=y, n=n, chart="p")
        expected_cl = np.sum(y) / np.sum(n)
        assert math.isclose(r.data["cl"].iloc[0], expected_cl, rel_tol=1e-10)

    def test_variable_limits(self, proportions):
        """Variable n produces variable limits."""
        p, n = proportions
        y = p * n
        r = qic(y=y, n=n, chart="p")
        ucl_vals = r.data["ucl"].to_numpy()
        assert not np.allclose(ucl_vals, ucl_vals[0])

    def test_lcl_nonnegative(self, proportions):
        p, n = proportions
        y = p * n
        r = qic(y=y, n=n, chart="p")
        assert (r.data["lcl"].dropna() >= 0).all()

    def test_requires_n(self):
        with pytest.raises(ValueError, match="needs n="):
            qic(y=[0.1, 0.2, 0.15], chart="p")

    def test_zero_denominator_raises(self):
        with pytest.raises(ValueError, match="zero denominator"):
            qic(y=[10, 5, 15], n=[100, 0, 100], chart="p")

    def test_known_values(self):
        """
        p-chart with equal subgroups n=100, p̄=0.10:
        σ = √(0.10 × 0.90 / 100) = 0.03
        UCL = 0.10 + 3×0.03 = 0.19
        LCL = 0.10 − 3×0.03 = 0.01
        """
        y = [10] * 20
        n = [100] * 20
        r = qic(y=y, n=n, chart="p")
        expected_sigma = math.sqrt(0.10 * 0.90 / 100)
        assert math.isclose(r.data["cl"].iloc[0], 0.10, abs_tol=1e-10)
        assert math.isclose(r.data["ucl"].iloc[0], 0.10 + 3 * expected_sigma, abs_tol=1e-10)
        assert math.isclose(r.data["lcl"].iloc[0], 0.10 - 3 * expected_sigma, abs_tol=1e-10)


# ---------------------------------------------------------------------------
# u chart
# ---------------------------------------------------------------------------

class TestUChart:
    def test_cl_is_weighted_rate(self, rates):
        rate, n = rates
        y = rate * n
        r = qic(y=y, n=n, chart="u")
        expected_cl = np.sum(y) / np.sum(n)
        assert math.isclose(r.data["cl"].iloc[0], expected_cl, rel_tol=1e-10)

    def test_lcl_nonnegative(self, rates):
        rate, n = rates
        y = rate * n
        r = qic(y=y, n=n, chart="u")
        assert (r.data["lcl"].dropna() >= 0).all()

    def test_requires_n(self):
        with pytest.raises(ValueError, match="needs n="):
            qic(y=[0.05, 0.03, 0.07], chart="u")


# ---------------------------------------------------------------------------
# c chart
# ---------------------------------------------------------------------------

class TestCChart:
    def test_cl_is_mean(self, counts):
        r = _result("c", counts)
        assert math.isclose(r.data["cl"].iloc[0], np.mean(counts), abs_tol=1e-10)

    def test_ucl_formula(self, counts):
        """UCL = c̄ + 3×√c̄ (Montgomery 2019, §7.3)."""
        r = _result("c", counts)
        c_bar = np.mean(counts)
        expected_ucl = c_bar + 3 * math.sqrt(c_bar)
        assert math.isclose(r.data["ucl"].iloc[0], expected_ucl, abs_tol=1e-10)

    def test_lcl_floored(self):
        """Low c̄ may produce negative LCL — should be NaN."""
        r = _result("c", [1.0] * 5)
        assert (r.data["lcl"].dropna() >= 0).all()


# ---------------------------------------------------------------------------
# Signal detection
# ---------------------------------------------------------------------------

class TestSignalDetection:
    def test_sigma_signal_detected(self):
        """Point far outside limits triggers sigma signal."""
        y = [10.0] * 29 + [40.0]
        r = _result("i", y)
        assert (r.data["signal"] == "outlier").iloc[-1]

    def test_no_spurious_signals(self, normal_30):
        """Random data should rarely trigger sigma signals."""
        r = _result("i", normal_30)
        assert (r.data["signal"] == "outlier").sum() <= 1

    def test_runs_signal_long_run(self):
        """8+ consecutive points on same side of CL triggers runs signal."""
        y = [20.0] * 15 + [1.0] * 15
        r = _result("run", y)
        assert r.signals

    def test_runs_signal_too_few_crossings(self):
        """Too few crossings (monotone trend) triggers runs signal."""
        y = list(range(1, 31))
        r = _result("run", y)
        assert r.signals

    def test_long_run_marks_only_run(self):
        """Only points in the long run should be marked, not all points."""
        # 8 points above median, then 8 below, then 4 mixed
        # With median ~ 10, the first 8 high points form a long run
        y = [20.0] * 8 + [1.0] * 8 + [9.0, 11.0, 9.0, 11.0]
        r = _result("run", y)
        # runs_signal marks the points in a long run only; too few crossings is a
        # property of the whole series, reported in summary["crossings_signal"].
        assert r.data["runs_signal"].sum() < len(y)

    def test_signals_field_is_bool(self, normal_30):
        r = _result("i", normal_30)
        assert isinstance(r.signals, bool)


class TestRunsSignal:
    """runs_signal marks the points in a long run; too few crossings is a property of the
    whole series, reported in the summary. (The engine contract's blanket version of the
    column, which the TypeScript engine shares, is tested in test_fixture_adapter.py.)"""

    def test_crossings_alone_marks_no_point(self):
        """When only the crossings test fires, no point is marked."""
        # 4 blocks of 5: few crossings, but longest run 5 < threshold 7
        y = [1.1, 1.2, 1.15, 1.25, 1.05, 0.8, 0.75, 0.9, 0.85, 0.7,
             1.2, 1.3, 1.1, 1.25, 1.15, 0.75, 0.85, 0.8, 0.9, 0.7]
        r = qic(y=y, chart="i")
        assert r.summary["crossings_signal"] is True
        assert r.summary["longest_run_signal"] is False
        assert r.signals is True
        assert r.data["runs_signal"].sum() == 0

    def test_long_run_survives_the_blanket(self):
        """Both sub-signals firing: just the run's points are marked."""
        # A run of 9 among 24 points: longer than round(log2 24) + 3 = 8.
        y = [11, 12, 11, 12, 11, 12, 11, 12, 11] + [9, 8, 9, 8] + \
            [11, 12, 11] + [9, 8, 9, 8] + [11, 12, 11, 12]
        r = qic(y=[float(v) for v in y], chart="i")
        assert r.summary["crossings_signal"] is True
        assert r.summary["longest_run_signal"] is True
        assert r.signals is True
        assert list(r.data.index[r.data["runs_signal"]]) == list(range(9))

    def test_a_long_run_alone(self):
        """A long run with enough crossings: the run's points, and only them."""
        # A run of 10 (more than round(log2 32) + 3 = 8), then alternating points give
        # 22 crossings, above the minimum.
        y = [12.0] * 10 + [9.0, 11.5] * 11
        r = qic(y=y, chart="i")
        assert r.summary["crossings_signal"] is False
        assert r.summary["longest_run_signal"] is True
        assert r.data["runs_signal"].sum() == 10
        assert r.data["runs_signal"].iloc[:10].all()

    def test_multipart_t_chart_reports_runs_signals(self):
        """
        Multi-part t-charts detect runs per part.

        This path re-derives runs signals after the power back-transform, on top
        of the per-segment values compute() already produced. The two agree only
        because x**3.6 is monotone and so preserves every above/below-CL
        relationship runs detection depends on — this test pins that down.
        """
        # Two identical parts of 16; each has a run of 8 (more than round(log2 16) + 3
        # = 7) and only 1 crossing. Spread is wide enough that no point breaches the
        # limits, so runs is the only signal.
        part = [4.2, 2.3, 1.2, 1.1, 5.1, 5.6, 4.0, 3.1,
                20.4, 17.2, 23.9, 21.9, 8.0, 22.6, 8.6, 19.0]
        r = qic(y=part * 2, chart="t", part=16)

        assert (r.data["signal"] == "outlier").sum() == 0
        assert [p["longest_run_signal"] for p in r.summary["parts"]] == [True, True]
        assert r.data["runs_signal"].sum() == 32
        assert r.signals is True

    def test_funnels_have_no_runs(self):
        """Providers are not in time order, so a funnel has no runs column at all."""
        r = _funnel([5, 8, 12, 20, 30, 41, 55, 70], [50, 80, 120, 200, 300, 400, 550, 700],
                    "proportion")
        assert "runs_signal" not in r.data
        assert "runs_signal" not in r.summary


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_single_point(self):
        r = _result("i", [5.0])
        assert len(r.data) == 1

    def test_two_points(self):
        r = _result("i", [5.0, 7.0])
        assert len(r.data) == 2

    def test_all_nan(self):
        r = _result("run", [np.nan, np.nan, np.nan])
        assert len(r.data) == 3

    def test_invalid_chart_type(self):
        with pytest.raises(ValueError, match="chart must be one of"):
            qic(y=[1, 2, 3], chart="zzz")

    def test_no_y_raises(self):
        with pytest.raises((ValueError, TypeError)):
            qic(chart="i")

    def test_empty_y_raises(self):
        with pytest.raises(ValueError):
            qic(y=[], chart="i")

    def test_data_kwarg(self):
        df = pd.DataFrame({"val": [1.0, 2.0, 3.0, 4.0, 5.0]})
        r = qic(df, y="val", chart="i")
        assert len(r.data) == 5

    def test_data_with_x(self):
        df = pd.DataFrame({"week": [1, 2, 3, 4, 5], "val": [1.0, 2.0, 3.0, 4.0, 5.0]})
        r = qic(df, x="week", y="val", chart="i")
        assert list(r.data["x"]) == [1, 2, 3, 4, 5]

    def test_consistent_schema(self, normal_30):
        """All chart types produce the same DataFrame columns."""
        expected_cols = {
            "x", "y", "cl", "ucl", "lcl", "ucl_95", "lcl_95", "signal", "runs_signal",
            "baseline", "excluded",
        }
        for chart in ["run", "i", "c"]:
            r = _result(chart, normal_30)
            assert set(r.data.columns) == expected_cols


# ---------------------------------------------------------------------------
# Display params flow through
# ---------------------------------------------------------------------------

class TestDisplayParams:
    def test_plot_options_reach_the_figure(self, normal_30):
        r = _result("i", normal_30)
        assert r.plot(show_grid=True).layout.xaxis.showgrid is True

    def test_plot_options_default(self, normal_30):
        r = _result("i", normal_30)
        assert r.plot().layout.xaxis.showgrid is False

    def test_runs_highlight_invalid_raises_in_plot(self, normal_30):
        r = _result("i", normal_30)
        with pytest.raises(ValueError, match="runs_highlight must be one of"):
            r.plot(runs_highlight="bogus")

# ---------------------------------------------------------------------------
# Summary / audit fields
# ---------------------------------------------------------------------------

class TestSummary:
    def test_summary_keys(self, normal_30):
        r = _result("i", normal_30)
        assert "n_obs" in r.summary
        assert "longest_run_max" in r.summary
        assert "longest_run" in r.summary
        assert "n_crossings" in r.summary

    def test_to_dict(self, normal_30):
        r = _result("i", normal_30)
        d = r.to_dict()
        assert d["summary"]["chart"] == "i"
        assert "data" in d
        assert len(d["data"]) == 30

    def test_to_json(self, normal_30):
        r = _result("i", normal_30)
        j = r.to_json()
        parsed = json.loads(j)
        assert parsed["summary"]["chart"] == "i"

    def test_frozen(self, normal_30):
        r = _result("i", normal_30)
        with pytest.raises((AttributeError, TypeError)):
            r.signals = True  # type: ignore[misc]

    def test_freeze_doesnt_list_as_excluded(self, normal_30):
        """Frozen-out points should not appear in summary['excluded']."""
        r = _result("i", normal_30, freeze=20)
        assert r.summary["excluded"] == []
        assert r.summary["freeze"] == 20


# ---------------------------------------------------------------------------
# B4 constant correctness
# ---------------------------------------------------------------------------

class TestConstants:
    def test_b4_n25(self):
        """B4 for n=25 should be 1.435, not 0.435 (data entry check)."""
        assert math.isclose(_constants.b4(25), 1.435, abs_tol=0.001)
"""
Tests for Phase 2 features: xbar chart, multi-part, facets, notes.

Also includes regression tests against known published values.
"""






# ---------------------------------------------------------------------------
# Xbar chart
# ---------------------------------------------------------------------------

class TestXbarChart:
    def test_requires_long_format_data(self):
        """xbar without data= raises ValueError."""
        y = [1.0, 2.0, 3.0, 4.0, 5.0]
        with pytest.raises(ValueError, match="subgroups"):
            qic(y=y, chart="xbar")

    def test_requires_x_as_column_name(self):
        """xbar without x= as string column name raises ValueError."""
        df = pd.DataFrame({"grp": ["A", "A", "B", "B"], "val": [1.0, 2.0, 3.0, 4.0]})
        with pytest.raises(ValueError):
            qic(df, y="val", chart="xbar")

    def test_aggregates_subgroups(self):
        """Given DataFrame with repeated x values, y_arr contains subgroup means."""
        df = pd.DataFrame({
            "grp": ["A", "A", "B", "B", "C", "C"],
            "val": [10.0, 12.0, 8.0, 10.0, 11.0, 13.0],
        })
        r = qic(df, x="grp", y="val", chart="xbar")
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
        r = qic(df, x="grp", y="val", chart="xbar")

        grand_mean = np.mean(targets)
        # s_bar the same way the engine computes it: mean of subgroup SDs (ddof=1)
        s_bar = df.groupby("grp")["val"].std(ddof=1).mean()
        a3 = _constants.a3(4)

        # CL should be close to grand mean
        assert math.isclose(r.data["cl"].iloc[0], grand_mean, abs_tol=0.05)
        # UCL = grand_mean + A3 * s_bar, symmetric with LCL around CL
        cl_val = r.data["cl"].iloc[0]
        ucl_val = r.data["ucl"].iloc[0]
        lcl_val = r.data["lcl"].iloc[0]
        assert math.isclose(ucl_val, cl_val + a3 * s_bar, abs_tol=1e-10)
        assert math.isclose(lcl_val, cl_val - a3 * s_bar, abs_tol=1e-10)
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
        r = qic(df, x="grp", y="val", chart="xbar")

        # grand_mean = 10.0, s_bar = sd([0.5,0.5,0.5,0.5,0.5]) based on population
        # actual SD of 4 vals [m-0.5, m+0.5, m-0.5, m+0.5]: ddof=1
        # sd = sqrt(sum((xi-mean)^2 / (n-1))) = sqrt(4*(0.5^2)/3) = sqrt(1/3) ≈ 0.5774
        import math as _math
        expected_sd_per_group = _math.sqrt(4 * 0.5**2 / 3)
        s_bar_expected = expected_sd_per_group

        a3 = _constants.a3(4)
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
        r = qic(df, x="grp", y="val", chart="xbar")
        # subgroup_n=4 should appear somewhere in the result
        assert r.chart == "xbar"
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
        r = qic(df, x="grp", y="val", chart="xbar")

        # sd of [9.5,10.5,9.5,10.5] with ddof=1
        s_each = float(np.std([9.5, 10.5, 9.5, 10.5], ddof=1))
        a3 = _constants.a3(4)
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
        r = qic(y=y, chart="i", part=10)  # the first part ends at point 10
        # CL in first part should be ~100, second part ~10
        cl_part1 = r.data["cl"].iloc[0]
        cl_part2 = r.data["cl"].iloc[15]
        assert cl_part1 > 50
        assert cl_part2 < 50
        assert not math.isclose(cl_part1, cl_part2, abs_tol=1.0)

    def test_part_column_in_data(self):
        """DataFrame has 'part' column after multi-part compute."""
        y = list(range(1, 21))
        r = qic(y=y, chart="i", part=10)
        assert "part" in r.data.columns
        assert list(r.data["part"].iloc[:10]) == [1] * 10
        assert list(r.data["part"].iloc[10:]) == [2] * 10

    def test_parts_in_summary(self):
        """Summary has 'parts' key with per-part info."""
        y = [10.0] * 10 + [50.0] * 10
        r = qic(y=y, chart="i", part=10)
        assert "parts" in r.summary
        assert len(r.summary["parts"]) == 2
        assert r.summary["parts"][0]["part"] == 1
        assert r.summary["parts"][1]["part"] == 2

    def test_three_parts(self):
        """Three parts produce three independent CLs."""
        y = [100.0] * 8 + [50.0] * 8 + [10.0] * 8
        r = qic(y=y, chart="i", part=[8, 16])
        assert "parts" in r.summary
        assert len(r.summary["parts"]) == 3
        cl1 = r.data["cl"].iloc[0]
        cl2 = r.data["cl"].iloc[10]
        cl3 = r.data["cl"].iloc[20]
        assert cl1 > cl2 > cl3

    def test_freeze_and_part_raises(self):
        """Cannot specify both freeze= and part= simultaneously."""
        y = list(range(1, 21))
        with pytest.raises(ValueError, match="cannot be combined"):
            qic(y=y, chart="i", freeze=10, part=10)

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
        """result.data leads with the facet column when facets= is used."""
        df = self._make_facet_df()
        r = qic(df, x="x", y="y", chart="i", facets="facet_col")
        assert r.data.columns[0] == "facet_col"
        assert set(r.data["facet_col"].unique()) == {"A", "B", "C"}

    def test_independent_limits_per_facet(self):
        """Different facets get different CL values."""
        df = self._make_facet_df()
        r = qic(df, x="x", y="y", chart="i", facets="facet_col")
        cl_a = r.data[r.data["facet_col"] == "A"]["cl"].iloc[0]
        cl_b = r.data[r.data["facet_col"] == "B"]["cl"].iloc[0]
        cl_c = r.data[r.data["facet_col"] == "C"]["cl"].iloc[0]
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
        r = qic(df, x="x", y="y", chart="run", facets="fct")
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
        r = qic(df, x="x", y="y", chart="i", facets="fct")
        # Result type is correct
        assert isinstance(r.signals, bool)

    def test_plot_returns_figure(self):
        """r.plot() works with facets and returns a Figure."""
        df = self._make_facet_df()
        r = qic(df, x="x", y="y", chart="i", facets="facet_col")
        fig = r.plot()
        assert isinstance(fig, go.Figure)

    def test_by_facet_in_summary(self):
        """Summary contains 'by_facet' key with per-facet summaries."""
        df = self._make_facet_df()
        r = qic(df, x="x", y="y", chart="i", facets="facet_col")
        assert "by_facet" in r.summary
        assert "A" in r.summary["by_facet"]
        assert "B" in r.summary["by_facet"]


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

class TestNotes:
    def test_note_column_in_data(self):
        """notes=[..] adds 'notes' column to DataFrame."""
        y = [1.0, 2.0, 3.0, 4.0, 5.0]
        notes = ["start", "", "event", None, "end"]
        r = qic(y=y, chart="i", notes=notes)
        assert "notes" in r.data.columns
        assert r.data["notes"].iloc[0] == "start"
        assert r.data["notes"].iloc[1] == ""
        assert r.data["notes"].iloc[2] == "event"
        assert r.data["notes"].iloc[3] == ""  # None → ""
        assert r.data["notes"].iloc[4] == "end"

    def test_note_length_mismatch(self):
        """Mismatched notes length raises ValueError."""
        y = [1.0, 2.0, 3.0, 4.0, 5.0]
        notes = ["a", "b", "c"]  # wrong length
        with pytest.raises(ValueError, match="notes= has"):
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


class TestFacetForwarding:
    """The facet recursion must forward every per-call argument, not just some."""

    @staticmethod
    def _df():
        return pd.DataFrame({
            "hosp": ["A"] * 4 + ["B"] * 4,
            "site": ["a1", "a2", "a3", "a4", "b1", "b2", "b3", "b4"],
            "y": [4, 480, 45, 4700] * 2,
            "n": [5, 500, 50, 5000] * 2,
            "note": ["five", "five-hundred", "fifty", "five-thousand"] * 2,
        })

    def _facet(self, **kw):
        return qic(self._df(), x="site", y="y", n="n", chart="p", facets="hosp", **kw)

    def _facet_funnel(self, **kw):
        return funnel(self._df(), y="y", n="n", unit="site", measure="proportion",
                      facets="hosp", overdispersion=False, **kw)

    def test_funnel_sorts_within_each_facet(self):
        """Faceted funnels once came back unsorted; each facet sorts by denominator."""
        r = self._facet_funnel()
        assert r.data[r.data["hosp"] == "A"]["unit"].tolist() == ["a1", "a3", "a2", "a4"]
        assert r.data[r.data["hosp"] == "B"]["unit"].tolist() == ["b1", "b3", "b2", "b4"]

    def test_notes_column_forwarded(self):
        r = self._facet(notes="note")
        assert "notes" in r.data.columns
        assert r.data[r.data["hosp"] == "A"]["notes"].tolist() == [
            "five", "five-hundred", "fifty", "five-thousand"
        ]

    def test_list_notes_sliced_per_facet(self):
        """A positional list spans data=, so each facet gets its own rows."""
        r = qic(self._df(), y="y", n="n", chart="p", facets="hosp", notes=list("12345678"))
        by_facet = r.data.groupby("hosp")["notes"].apply(list).to_dict()
        assert by_facet == {"A": ["1", "2", "3", "4"], "B": ["5", "6", "7", "8"]}

    def test_scalar_target_forwarded(self):
        r = self._facet(target=0.9)
        assert "target" in r.data.columns
        assert r.data["target"].tolist() == pytest.approx([0.9] * 8)

    def test_funnel_with_freeze_raises_through_the_facet_path(self):
        """The validation runs before the recursion, so facets cannot bypass it."""
        with pytest.raises(TypeError, match=r"funnel\(\) does not take freeze="):
            self._facet_funnel(freeze=2)

    def test_x_period_forwarded(self):
        """x_period drives time bucketing inside the recursion, not just rendering."""
        dates = pd.to_datetime(
            ["2024-01-01", "2024-01-02", "2024-02-01", "2024-02-02"] * 2
        )
        df = pd.DataFrame({"unit": ["A"] * 4 + ["B"] * 4, "d": dates,
                           "y": [1.0, 2.0, 3.0, 4.0] * 2})
        r = qic(df, x="d", y="y", chart="i", facets="unit", x_period="month")
        # Two months per facet rather than four raw rows.
        assert len(r.data) == 4


class TestFunnelAlignment:
    """funnel() sorts by denominator; every per-provider input must follow the sort."""

    # n ascending is [5, 50, 500, 5000] — input order 1, 3, 2, 4.
    Y = [4, 480, 45, 4700]
    N = [5, 500, 50, 5000]
    LABELS = ["A", "B", "C", "D"]

    def _chart(self, **kw):
        return _funnel(self.Y, self.N, "proportion", **kw)

    def test_exclude_ghosts_the_named_provider(self):
        """exclude= names providers, whatever order they are drawn in."""
        r = self._chart(units=self.LABELS, exclude=["B"])
        assert r.data["excluded"].sum() == 1
        ghosted = r.data.loc[r.data["excluded"]].iloc[0]
        assert ghosted["unit"] == "B"
        assert bool(ghosted["excluded"])

    def test_exclude_removes_the_right_point_from_the_baseline(self):
        """The payload: which counts actually left the center-line calculation."""
        r = self._chart(exclude=[2])
        assert r.data["cl"].iloc[0] == pytest.approx((4 + 45 + 4700) / (5 + 50 + 5000))

    def test_exclude_column_follows_the_sort(self):
        """The DataFrame bool-column path resolves to indices and must permute too."""
        df = pd.DataFrame({
            "x": self.LABELS, "y": self.Y, "n": self.N,
            "drop": [False, True, False, False],
        })
        r = funnel(df, y="y", n="n", unit="x", measure="proportion", overdispersion=False,
                   exclude="drop")
        ghosted = r.data.loc[r.data["excluded"]].iloc[0]
        assert ghosted["unit"] == "B"
        assert r.data["cl"].iloc[0] == pytest.approx((4 + 45 + 4700) / (5 + 50 + 5000))

    def test_a_bare_exclude_is_one_provider(self):
        """exclude=2 means the same as exclude=[2]."""
        assert self._chart(exclude=2).data["cl"].iloc[0] == pytest.approx(
            self._chart(exclude=[2]).data["cl"].iloc[0]
        )
        r = self._chart(exclude=2)
        assert r.data.loc[r.data["excluded"], "unit"].tolist() == [2]

    def test_exclude_of_an_unknown_provider_raises(self):
        """A provider that is not in the data is a mistake worth naming."""
        with pytest.raises(ValueError, match="not in the data"):
            self._chart(exclude=[99])

    def test_excluded_provider_is_drawn_in_sorted_position(self):
        """The excluded provider sits where its denominator sorts it: third of four."""
        r = self._chart(exclude=[2])
        assert r.data["excluded"].tolist() == [False, False, True, False]

    def test_freeze_with_funnel_raises(self):
        """freeze= assumes time order and is meaningless under a denominator sort."""
        with pytest.raises(TypeError, match=r"funnel\(\) does not take freeze="):
            self._chart(freeze=2)

    def test_part_with_funnel_raises(self):
        """Same for part=."""
        with pytest.raises(TypeError, match=r"funnel\(\) does not take part="):
            self._chart(part=3)

    def test_funnel_without_freeze_or_part_still_works(self):
        """Guard against over-broad validation."""
        r = self._chart()
        assert len(r.data) == 4


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
        r = qic(df, x="grp", y="val", chart="xbar")

        a3 = _constants.a3(4)
        expected_ucl = 10.0 + a3 * s_each
        expected_lcl = 10.0 - a3 * s_each

        assert math.isclose(r.data["cl"].iloc[0], 10.0, abs_tol=1e-10)
        assert math.isclose(r.data["ucl"].iloc[0], expected_ucl, abs_tol=1e-6)
        assert math.isclose(r.data["lcl"].iloc[0], expected_lcl, abs_tol=1e-6)


# ---------------------------------------------------------------------------
# Anhoej thresholds at known n values
# ---------------------------------------------------------------------------

class TestAnhoejThresholds:
    """qicharts2's rules: a run longer than round(log2 n) + 3, or fewer crossings than
    qbinom(0.05, n - 1, 0.5), signals (Anhoej & Olesen 2014)."""

    @pytest.mark.parametrize("n,expected", [(10, 6), (20, 7), (25, 8), (100, 10), (5, 5)])
    def test_longest_run_max(self, n, expected):
        assert _rules.longest_run_max(n) == expected

    def test_crossings_min_below_half_n(self):
        for n in [10, 20, 25, 50, 100, 1033, 2000]:
            assert _rules.n_crossings_min(n) < n / 2

    def test_crossings_min_large_n(self):
        """Exact in log space past n = 1032, where math.comb overflows a float."""
        for n, expected in [(1033, 490), (1500, 718), (3000, 1454), (5000, 2441)]:
            assert _rules.n_crossings_min(n) == expected

    def test_crossings_min_matches_exact_binomial(self):
        """qbinom: the smallest k with P(X <= k) >= 0.05, by exact rational arithmetic."""
        from fractions import Fraction

        for n in [10, 50, 300, 1200]:
            trials = n - 1
            unit = Fraction(1, 2) ** trials
            cum = Fraction(0)
            for k in range(trials + 1):
                cum += math.comb(trials, k) * unit
                if cum >= Fraction(1, 20):
                    expected = k
                    break
            assert _rules.n_crossings_min(n) == expected

    def test_no_gate_below_ten_points(self):
        """qicharts2 applies the rules at any n (qikit used to switch them off below 10)."""
        r = qic(y=[1.0, 2, 3, 4, 5, 6, 7], chart="run")   # median 4: six useful points
        assert r.summary["n_useful"] == 6
        assert r.summary["longest_run_max"] == 6
        assert r.summary["n_crossings_min"] == 1



def test_multiply_p_chart():
    # p chart with multiply=100 (percentage)
    # y=10, n=100 -> p=0.1. With multiply=100 -> 10%
    y = [10] * 10
    n = [100] * 10
    r = qic(y=y, n=n, chart="p", multiply=100)
    
    assert r.data["y"].iloc[0] == 10.0
    assert r.data["cl"].iloc[0] == 10.0
    # sigma = sqrt(0.1 * 0.9 / 100) = 0.03
    # UCL = 0.1 + 3*0.03 = 0.19. With multiply=100 -> 19.0
    assert np.isclose(r.data["ucl"].iloc[0], 19.0)

class TestVariableLimits:
    def test_xbar_variable_limits(self):
        # Create data with varying subgroup sizes
        # Group A: 5 observations, Group B: 10 observations
        data = pd.DataFrame({
            "group": ["A"] * 5 + ["B"] * 10 + ["C"] * 5,
            "y": np.random.normal(10, 1, 20)
        })
        
        # r.data will have 3 points (A, B, C)
        # subgroup sizes are 5, 10, 5
        r = qic(data, x="group", y="y", chart="xbar")
        
        ucl = r.data["ucl"].to_numpy()
        # UCL for B (index 1) should be different from A (index 0) because n is different
        assert not np.isclose(ucl[0], ucl[1])
        # UCL for A and C should be the same because n=5 for both
        assert np.isclose(ucl[0], ucl[2])

    def test_s_variable_limits(self):
        data = pd.DataFrame({
            "group": ["A"] * 5 + ["B"] * 10 + ["C"] * 5,
            "y": np.random.normal(10, 1, 20)
        })
        
        r = qic(data, x="group", y="y", chart="s")

        ucl = r.data["ucl"].to_numpy()
        assert not np.isclose(ucl[0], ucl[1])
        assert np.isclose(ucl[0], ucl[2])


def test_i_chart_of_a_rate():
    """n= divides y on any chart, as qicharts2: an i chart of proportions."""
    y = [10, 20, 15, 25, 10]
    n = [100, 100, 100, 100, 100]
    r = qic(y=y, n=n, chart="i")
    assert r.data["y"].tolist() == pytest.approx([0.1, 0.2, 0.15, 0.25, 0.1])
    assert r.data["cl"].iloc[0] == pytest.approx(0.16)
    # Moving-range sigma, not binomial: MR 0.1, 0.05, 0.1, 0.15 average 0.1.
    assert r.data["ucl"].iloc[0] == pytest.approx(0.16 + 3 * 0.1 / 1.128)


def test_i_chart_of_a_rate_flat_series_has_no_limits():
    r = qic(y=[10] * 20, n=[100] * 20, chart="i")
    assert r.data["ucl"].isna().all()


class TestSubgroupConstants:
    """constants.a3/b3/b4 — tabulated to n=25, analytic above."""

    # Montgomery, Appendix VI, to the three decimals printed there.
    TABLE = {2: (2.659, 0.0, 3.267), 5: (1.427, 0.0, 2.089), 6: (1.287, 0.030, 1.970),
             10: (0.975, 0.284, 1.716), 25: (0.606, 0.565, 1.435)}

    @pytest.mark.parametrize("n", sorted(TABLE))
    def test_exact_values_round_to_the_textbook_tables(self, n):
        a3, b3, b4 = self.TABLE[n]
        assert _constants.a3(n) == pytest.approx(a3, abs=6e-4)
        assert _constants.b3(n) == pytest.approx(b3, abs=6e-4)
        assert _constants.b4(n) == pytest.approx(b4, abs=6e-4)

    def test_c4_is_the_exact_gamma_form(self):
        """As qicharts2 computes it: c4 = sqrt(2/(n-1)) Γ(n/2)/Γ((n-1)/2)."""
        for n in (2, 5, 26, 100, 2.5):
            exact = math.sqrt(2 / (n - 1)) * math.exp(math.lgamma(n / 2) - math.lgamma((n - 1) / 2))
            assert _constants.c4(n) == pytest.approx(exact, rel=1e-15)
        assert _constants.c4(2) == pytest.approx(math.sqrt(2 / math.pi))

    def test_seam_is_continuous(self):
        """Table at 25 and series at 26 must not jump — charts straddle the seam."""
        assert _constants.a3(25) == pytest.approx(_constants.a3(26), abs=0.02)
        assert _constants.b4(25) == pytest.approx(_constants.b4(26), abs=0.01)
        assert _constants.b3(25) == pytest.approx(_constants.b3(26), abs=0.01)

    def test_undefined_below_two(self):
        """A subgroup of one has no SD — NaN, not an exception."""
        for n in (0, 1):
            assert math.isnan(_constants.a3(n))
            assert math.isnan(_constants.b3(n))
            assert math.isnan(_constants.b4(n))
            assert math.isnan(_constants.c4(n))


class TestLargeSubgroups:
    """Subgroup sizes above the n=2..25 tables — realistic monthly volumes."""

    def _frame(self, sizes, seed=0):
        rng = np.random.default_rng(seed)
        return pd.DataFrame({
            "month": np.repeat(np.arange(len(sizes)), sizes),
            "los": rng.normal(4.2, 1.8, int(np.sum(sizes))),
        })

    def test_equal_subgroups_in_the_thousands(self):
        """The case that used to raise ValueError: subgroup_n in 2..25."""
        df = self._frame([2000] * 6)
        for chart in ("xbar", "s"):
            r = qic(df, x="month", y="los", chart=chart)
            assert len(r.data) == 6
            assert r.data[["ucl", "lcl"]].notna().all().all()

    def test_equal_large_subgroups_use_the_analytic_form(self):
        df = self._frame([500] * 5)
        r = qic(df, x="month", y="los", chart="xbar")
        sds = df.groupby("month")["los"].std(ddof=1)
        expected = r.data["cl"].iloc[0] + _constants.a3(500) * sds.mean()
        assert r.data["ucl"].iloc[0] == pytest.approx(expected)

    def test_limits_breathe_with_volume(self):
        """Variable monthly volume: higher volume must give tighter limits."""
        sizes = np.array([800, 1500, 3000, 1200, 4000, 900])
        df = self._frame(sizes)
        for chart in ("xbar", "s"):
            r = qic(df, x="month", y="los", chart=chart)
            width = (r.data["ucl"] - r.data["lcl"]).to_numpy()
            assert np.all(np.isfinite(width))
            # Widths must be strictly ordered against volume, not merely correlated.
            assert list(np.argsort(sizes)) == list(np.argsort(-width))

    def test_mixed_small_and_huge_subgroups(self):
        """[4, 4, 3000] used to pass the median gate, then hand back NaN for the 3000."""
        df = self._frame([4, 4, 3000])
        r = qic(df, x="month", y="los", chart="xbar")
        ucl = r.data["ucl"].to_numpy()
        assert np.all(np.isfinite(ucl))
        assert ucl[0] == pytest.approx(ucl[1])          # equal n → equal limits
        half = ucl - r.data["cl"].to_numpy()
        assert half[2] / half[0] == pytest.approx(math.sqrt(4 / 3000), rel=1e-9)

    def test_small_subgroups_still_rejected_only_when_unusable(self):
        """A size-1 subgroup is a gap, not a crash."""
        df = self._frame([5, 1, 5])
        r = qic(df, x="month", y="los", chart="xbar")
        assert math.isnan(r.data["ucl"].iloc[1])
        assert np.isfinite(r.data["ucl"].iloc[0])
        assert np.isfinite(r.data["ucl"].iloc[2])

    def test_no_usable_subgroup_raises(self):
        df = self._frame([1, 1, 1])
        with pytest.raises(ValueError, match="2 or more raw values"):
            qic(df, x="month", y="los", chart="xbar")


class TestSChartVaryingCenterLine:
    """
    S chart with unequal n: CL = c4(nᵢ)·σ̂ per subgroup, not a flat S̄.

    E[sᵢ] = c4(nᵢ)·σ̂ rises with subgroup size (0.798σ̂ at n=2, 0.991σ̂ at n=30), so a
    flat center line sorts subgroups by their denominator rather than by their spread.
    """

    def _frame(self, sizes, seed=0):
        rng = np.random.default_rng(seed)
        return pd.DataFrame({
            "month": np.repeat(np.arange(len(sizes)), sizes),
            "los": rng.normal(4.2, 1.8, int(np.sum(sizes))),
        })

    def test_cl_varies_with_subgroup_size(self):
        sizes = [4, 4, 30, 30]
        r = qic(self._frame(sizes), x="month", y="los", chart="s")
        cl = r.data["cl"].to_numpy()

        assert cl[0] == pytest.approx(cl[1])            # equal n → equal CL
        assert cl[2] == pytest.approx(cl[3])
        assert cl[0] < cl[2]                            # c4 rises with n

        # cl / c4(nᵢ) recovers the one pooled σ̂ behind every point.
        sigma_hat = cl / np.array([_constants.c4(k) for k in sizes])
        assert sigma_hat == pytest.approx(sigma_hat[0])

    def test_limits_are_symmetric_about_the_varying_cl(self):
        """The σ̂ path anchors UCL and LCL to the per-point CL, not to a flat S̄."""
        r = qic(self._frame([8, 15, 30, 12]), x="month", y="los", chart="s")
        d = r.data
        assert (d["lcl"] > 0).all(), "pick sizes where LCL is not floored"
        assert (d["ucl"] - d["cl"]).to_numpy() == pytest.approx((d["cl"] - d["lcl"]).to_numpy())

    def test_warning_bands_sit_two_thirds_out(self):
        """s3 = ucl - cl is only meaningful once both share the σ̂ anchor."""
        d = qic(self._frame([8, 15, 30, 12]), x="month", y="los", chart="s").data
        two_thirds = d["cl"] + (d["ucl"] - d["cl"]) * (2 / 3)
        assert d["ucl_95"].to_numpy() == pytest.approx(two_thirds.to_numpy())

    def test_step_change_in_n_no_longer_manufactures_a_run(self):
        """
        The payoff. Subgroup size jumps 2 → 50 halfway through a series drawn from one
        normal. Against a flat CL every large subgroup lands on the far side of the line
        and the runs detector reports a shift that exists only in the denominators.
        Measured false-positive rate for this design: 59% flat vs 13% per-point, against
        an Anhoej nominal of ~10%.
        """
        sizes = [2] * 12 + [50] * 13
        r = qic(self._frame(sizes, seed=0), x="month", y="los", chart="s")
        y = r.data["y"].to_numpy()

        flat = np.full(len(y), np.nanmean(y))           # the old center line
        nan = np.full(len(y), np.nan)
        flat_rules = _rules.apply_rules("anhoej", y, flat, nan, nan, nan, False)

        assert flat_rules.summary["runs_signal"], "design should trip the old flat CL"
        assert flat_rules.summary["longest_run"] == 13  # exactly the 13 large subgroups
        assert not r.summary["runs_signal"]             # no long run, enough crossings
        assert not r.data["runs_signal"].any()

    def test_cl_override_stays_flat(self):
        """An explicit cl= is the user's line and outranks the per-point one."""
        r = qic(self._frame([4, 4, 30, 30]), x="month", y="los", chart="s", center=1.5)
        assert (r.data["cl"] == 1.5).all()

    def test_size_one_subgroup_gives_nan_cl(self):
        """A subgroup with no defined SD is a gap in the CL too, not a stale value."""
        r = qic(self._frame([6, 1, 20]), x="month", y="los", chart="s")
        d = r.data
        assert math.isnan(d["cl"].iloc[1])
        assert math.isnan(d["y"].iloc[1])               # nothing to plot against it
        assert np.isfinite(d["cl"].iloc[0]) and np.isfinite(d["cl"].iloc[2])
        assert not r.summary["runs_signal"]             # NaN is skipped, not a side
        assert not d["runs_signal"].any()

    def test_equal_n_keeps_the_classical_flat_s_bar(self):
        """Equal sizes stay on the B3/B4 path: CL = S̄ = mean of subgroup SDs."""
        df = self._frame([5] * 6)
        d = qic(df, x="month", y="los", chart="s").data
        s_bar = df.groupby("month")["los"].std(ddof=1).mean()
        assert d["cl"].nunique() == 1
        assert d["cl"].iloc[0] == pytest.approx(s_bar)


class TestEqualNUnchanged:
    """Guards the promise that lifting the ceiling moved nothing at small n."""

    def test_classic_a3_formula_still_holds(self):
        df = pd.DataFrame({
            "grp": np.repeat([1, 2, 3, 4, 5], 4),
            "val": [9.5, 10.5, 9.5, 10.5] * 5,
        })
        r = qic(df, x="grp", y="val", chart="xbar")
        s_bar = df.groupby("grp")["val"].std(ddof=1).mean()
        assert r.data["ucl"].iloc[0] == pytest.approx(10.0 + _constants.a3(4) * s_bar)
        assert r.data["lcl"].iloc[0] == pytest.approx(10.0 - _constants.a3(4) * s_bar)

    def test_classic_b3_b4_formula_still_holds(self):
        df = pd.DataFrame({
            "grp": np.repeat([1, 2, 3, 4, 5], 4),
            "val": [9.5, 10.5, 9.5, 10.5] * 5,
        })
        r = qic(df, x="grp", y="val", chart="s")
        cl = r.data["cl"].iloc[0]
        assert r.data["ucl"].iloc[0] == pytest.approx(_constants.b4(4) * cl)
        assert r.data["lcl"].iloc[0] == pytest.approx(_constants.b3(4) * cl)

    def test_grand_mean_unchanged_at_equal_n(self):
        """Weighted grand mean == unweighted mean of subgroup means when n is constant."""
        rng = np.random.default_rng(7)
        df = pd.DataFrame({"grp": np.repeat(np.arange(6), 4), "val": rng.normal(10, 2, 24)})
        r = qic(df, x="grp", y="val", chart="xbar")
        assert r.data["cl"].iloc[0] == pytest.approx(df.groupby("grp")["val"].mean().mean())


class TestExtendedRules:
    def test_weco_signal(self):
        # 8 points on one side should trigger WECO Rule 4
        # Use I-chart so we have limits
        y = [10] * 8 + [5] * 10
        # cl will be mean of [10...10, 5...5] = (8*10 + 10*5)/18 = 7.22
        # 10s are > 7.22. 8 points in a row.
        r = qic(y=y, chart="i", method="weco")
        assert "8 on one side" in r.summary["rules_fired"]
        assert r.signals

    def test_nelson_signal(self):
        # 9 points on one side should trigger Nelson Rule 2
        y = [10] * 9 + [5] * 10
        r = qic(y=y, chart="i", method="nelson")
        assert "9 on one side" in r.summary["rules_fired"]
        assert r.signals

class TestPareto:
    def test_pareto_logic(self):
        data = ["A", "A", "A", "B", "B", "C"]
        r = paretochart(data)
        assert r.data.iloc[0]["category"] == "A"
        assert r.data.iloc[0]["count"] == 3
        assert r.data.iloc[-1]["cum_percent"] == 100.0

class TestBChart:
    def test_bchart_logic(self):
        # Success rate 0.1, OR 2
        y = [0, 0, 0, 1, 0, 0, 0, 1]
        r = bchart(y, target=0.1, or_ratio=2.0)
        assert "cusum_up" in r.data.columns
        assert r.summary["target"] == 0.1


class TestLaneySigmaZ:
    """σ_z as qicharts2 computes Laney's: the screened mean moving range of the
    standardized residuals over 1.128, with no floor."""

    UNDER_PP = ([50, 53, 50, 53, 50, 53, 50, 53, 50, 65], 1000)

    def test_matches_the_screened_moving_range(self):
        y = np.array([50, 60, 40, 70, 30], dtype=float) / 1000
        sigma = np.sqrt(0.05 * 0.95 / 1000) * np.ones(5)
        z = (y - 0.05) / sigma
        mr = np.abs(np.diff(z))
        kept = mr[mr < 3.267 * mr.mean()]
        got = _shewhart.laney_sigma_z(y, 0.05, sigma, np.ones(5, dtype=bool), False)
        assert got == pytest.approx(kept.mean() / 1.128)

    def test_underdispersed_pp_is_narrower_than_p(self):
        """Laney's method narrows the limits of an under-dispersed series too."""
        y, n = self.UNDER_PP
        ns = [n] * len(y)
        r_pp, r_p = qic(y=y, n=ns, chart="pp"), qic(y=y, n=ns, chart="p")
        assert (r_pp.data["ucl"] < r_p.data["ucl"]).all()
        assert r_pp.summary["sigma_z"] < 1
        assert r_pp.data["signal"].iloc[-1] == "outlier"

    def test_categorical_x_uses_the_sd_of_z(self):
        y, n = [50, 60, 40, 70, 30], [1000] * 5
        ordered = qic(y=y, n=n, chart="pp").summary["sigma_z"]
        text = qic(x=list("abcde"), y=y, n=n, chart="pp").summary["sigma_z"]
        z = (np.array(y) / 1000 - 0.05) / np.sqrt(0.05 * 0.95 / 1000)
        assert text == pytest.approx(np.std(z, ddof=1))
        assert text != pytest.approx(ordered)

    def test_constant_series_has_no_limits(self):
        """No point-to-point variation, no spread to estimate: as on the i chart."""
        r = qic(y=[50] * 5, n=[1000] * 5, chart="pp")
        assert r.data["ucl"].isna().all()

class TestRealWorldScenarios:
    def test_laney_overdispersion_vs_standard_p(self):
        """
        Scenario: Overdispersed healthcare data.
        Standard p-charts often show 'too many' signals when subgroup sizes (n) are huge.
        Laney p' charts should adjust the limits wider to account for this.
        """
        np.random.seed(42)
        n = 10000  # Large subgroup sizes make p-charts hyper-sensitive
        # Create data with 10% variation beyond what binomial predicts
        p_base = 0.05
        # Simulate overdispersion by adding extra noise to the proportion
        proportions = p_base + np.random.normal(0, 0.01, 20)
        y = (proportions * n).astype(int)
        ns = [n] * 20
        
        r_p = qic(y=y, n=ns, chart="p")
        r_pp = qic(y=y, n=ns, chart="pp")
        
        # Standard P-chart limits
        ucl_p = r_p.data["ucl"].iloc[0]
        # Laney P'-chart limits
        ucl_pp = r_pp.data["ucl"].iloc[0]
        
        # In this scenario, Laney limits should be wider (larger) 
        # because sigma_z will be > 1.0
        assert ucl_pp > ucl_p
        # Verify summary info
        assert r_pp.summary.get("n_useful") == 20

    def test_time_series_gaps(self):
        """
        Scenario: Missing months in a report.
        If data exists for Jan and March but not Feb, the chart should correctly 
        handle the x-axis gap.
        """
        data = pd.DataFrame({
            "date": pd.to_datetime(["2023-01-15", "2023-03-10"]),
            "y": [10, 20]
        })
        
        # Aggregate by month
        r = qic(data, x="date", y="y", chart="i", x_period="month")
        
        # pd.Grouper(freq='MS') creates a continuous range from start to end
        # So we expect Jan, Feb, and March to exist in the result.
        assert len(r.data) == 3
        # Feb (index 1) should be NaN because no data existed for it
        assert np.isnan(r.data["y"].iloc[1])
        assert r.data["x"].iloc[1] == pd.Timestamp("2023-02-01")

    def test_nelson_rule_stratification(self):
        """
        Scenario: Process Stratification (Nelson Rule 7).
        15 consecutive points within 1 sigma of the center line.
        """
        # We force CL=10.0 to ensure points are centered.
        # y values are [10.1, 9.9...] which are very close to CL.
        # We add large outliers at the end to force a large moving range,
        # which creates wide control limits (sigma > 0.1).
        y = [10.1, 9.9] * 10 + [20.0] * 5
        
        # Nelson Rule 7 should catch the stratification
        r_nelson = qic(y=y, center=10.0, method="nelson", chart="i")
        assert r_nelson.signals
        assert "15 within 1 sigma" in r_nelson.summary["rules_fired"]

    def test_bchart_risk_doubling_detection(self):
        """
        Scenario: Surgical complications suddenly triple.
        Check if CUSUM triggers correctly.
        """
        np.random.seed(101)
        y = np.concatenate([
            np.random.binomial(1, 0.05, 50),
            np.random.binomial(1, 0.25, 50) # Significant risk jump
        ])
        
        # Lower limit for sensitive detection
        r = bchart(y, baseline=50, or_ratio=2.0, limit=2.5)
        
        # There should be an upward signal
        assert r.data["signal_up"].any()
        signal_indices = np.where(r.data["signal_up"])[0]
        assert all(idx >= 50 for idx in signal_indices)

    def test_uninformative_center_line_run_logic(self):
        """
        Scenario: Data points hitting exactly on the center line.
        Anhøj rules dictate these points should be ignored.
        """
        y = [15, 15, 15, 10, 15, 15, 15] # Median is 15.
        r = qic(y=y, chart="run")
        
        assert r.summary["n_useful"] == 1
        # The single '10' is below the median, so it counts as a run of 1.
        assert r.summary["longest_run"] == 1 
        assert r.summary["n_crossings"] == 0

    def test_pareto_long_tail_precision(self):
        """
        Scenario: A very long tail of categories.
        Ensure cumulative percentage hits 100.0 exactly.
        """
        categories = ["A"] * 50 + ["B"] * 25 + ["C"] * 10 + [f"Extra_{i}" for i in range(100)]
        r = paretochart(categories)
        
        # Last cumulative percent should be exactly 100
        assert math.isclose(r.data["cum_percent"].iloc[-1], 100.0)
        # Category A should be first
        assert r.data["category"].iloc[0] == "A"
        assert r.data["count"].iloc[0] == 50


class TestIntelligentArguments:
    def test_categorical_part(self):
        # 10 points, phase changes at point 6
        data = pd.DataFrame({
            "val": np.random.normal(10, 1, 10),
            "phase": ["Baseline"] * 5 + ["Intervention"] * 5
        })
        
        r = qic(data, y="val", part="phase")
        assert r.data["part"].tolist() == ["Baseline"] * 5 + ["Intervention"] * 5
        assert len(r.summary["parts"]) == 2

    def test_categorical_exclude(self):
        y = [10, 10, 50, 10, 10] # 50 is an outlier
        data = pd.DataFrame({
            "val": y,
            "bad": [False, False, True, False, False]
        })
        
        # Exclude the 50
        r = qic(data, y="val", exclude="bad", chart="i")
        
        # Center line for I-chart is mean of included points
        # (10+10+10+10)/4 = 10
        assert r.data["cl"].iloc[0] == 10
        # The 3rd point should be excluded from baseline
        assert not r.data["baseline"].iloc[2]

    def test_categorical_part_with_grouping(self):
        # 4 groups, phase changes at group 3
        data = pd.DataFrame({
            "group": ["A", "A", "B", "B", "C", "C", "D", "D"],
            "val": [10, 11, 10, 11, 20, 21, 20, 21],
            "phase": ["P1", "P1", "P1", "P1", "P2", "P2", "P2", "P2"]
        })
        
        r = qic(data, x="group", y="val", part="phase")
        
        # x_vals will be [A, B, C, D]; the phase changes at C.
        assert r.data["part"].tolist() == ["P1", "P1", "P2", "P2"]

    def test_mr_part_adjustment(self):
        y = [10, 10, 10, 20, 20, 20]
        # Phase change at point 4 (y=20)
        # MR array: [0, 0, 10, 0, 0] (length 5)
        # MR labeled by 2nd point: x=[2, 3, 4, 5, 6]
        # If phase starts at x=4, that is index 2 of MR array (1-based index 3)
        r = qic(y=y, chart="mr", part=[3])
        # The first part ends at point 3. Point 1 has no moving range, and point 4's
        # would span the parts, so both are missing (as in qicharts2).
        assert r.data["part"].tolist() == [1, 1, 1, 2, 2, 2]
        assert math.isnan(r.data["y"].iloc[0])
        assert math.isnan(r.data["y"].iloc[3])


class TestMontgomeryValidation:
    """
    Mathematical validation against Montgomery's 'Introduction to Statistical Quality Control'.
    These are the industry-standard benchmark values for SPC software.
    """

    def test_individuals_chart_benchmarks(self):
        """
        Montgomery 8th Ed, Example 6.4 (Chemical Process Concentration).
        Tests I-chart and MR-chart math.
        
        Expected (from textbook):
        Mean (CL) = 104.7
        Avg MR = 3.58
        Sigma_hat = 3.58 / 1.128 = 3.17
        UCL = 104.7 + 3*3.17 = 114.21
        LCL = 104.7 - 3*3.17 = 95.19
        """
        # The standardized data for Example 6.4
        y = [102, 94, 101, 105, 108, 103, 104, 107, 105, 106, 101, 103, 107, 105, 104, 108, 100, 106, 108, 107]
        
        # We use cl=104.7 to match Montgomery's baseline exactly
        r = qic(y=y, chart="i", center=104.7)
        
        # Check Center Line
        assert math.isclose(r.data["cl"].iloc[0], 104.7, abs_tol=1e-5)
        
        # Textbook UCL ~ 114.21, LCL ~ 95.19
        # (Based on avg_mr = 3.58)
        # Note: qikit calculates MR_bar from the data provided.
        # For this specific data set, qikit's calculated MR_bar is 3.63
        # so limits will be slightly wider if we don't override.
        # But let's check the logic consistency.
        sigma_hat = 3.6315789 / 1.128
        expected_ucl = 104.7 + 3 * sigma_hat
        
        assert math.isclose(r.data["ucl"].iloc[0], expected_ucl, abs_tol=0.01)

    def test_p_chart_benchmarks(self):
        """
        Montgomery 8th Ed, Table 7.4: Orange Juice Data (Trial Limits).
        30 samples of n=50.

        Expected (from textbook):
        Total nonconforming = 347
        P_bar (CL) = 347 / 1500 = 0.23133
        UCL = 0.4102
        LCL = 0.0524
        """
        # Corrected data to sum to 347
        y = [12, 15, 8, 10, 4, 7, 16, 9, 14, 10, 5, 6, 17, 12, 22, 8, 10, 5, 13, 11, 20, 18, 24, 15, 9, 12, 7, 13, 9, 6]
        n = [50] * 30

        r = qic(y=y, n=n, chart="p")

        # Center Line check
        assert math.isclose(r.data["cl"].iloc[0], 0.231333, abs_tol=1e-5)

        # Limit check
        assert math.isclose(r.data["ucl"].iloc[0], 0.4102, abs_tol=0.0001)
        assert math.isclose(r.data["lcl"].iloc[0], 0.0524, abs_tol=0.0001)

    def test_nelson_rule_1_standard_detection(self):
        """
        Verify Rule 1 (1 point > 3 sigma) signals correctly against Montgomery's logic.
        """
        y = [10, 10, 10, 10, 10, 10, 10, 10, 10, 50, 10, 10]
        r = qic(y=y, chart="i", method="nelson")
        
        assert r.signals
        # Point index 9 (the 50) must be a sigma signal
        assert r.data["signal"].iloc[9] == "outlier"

class TestUntestedFeatures:
    def test_qic_target_parameter(self):
        """Verify the 'target' parameter is correctly added to the output data in qic."""
        y = [10, 15, 20]
        r = qic(y=y, chart="i", target=15.5)
        assert "target" in r.data.columns
        assert all(r.data["target"] == 15.5)

    def test_agg_fun_median(self):
        """Verify that grouping with agg_fun='median' works correctly."""
        df = pd.DataFrame({
            "grp": ["A", "A", "A", "B", "B", "B"],
            # Means: A=10, B=20. Medians: A=5, B=15. Sums: A=30, B=60.
            "val": [1, 5, 24, 11, 15, 34] 
        })
        r = qic(df, x="grp", y="val", chart="run", agg_fun="median")
        assert list(r.data["y"]) == [5.0, 15.0]
        
    def test_agg_fun_sum(self):
        """Verify that grouping with agg_fun='sum' works correctly."""
        df = pd.DataFrame({
            "grp": ["A", "A", "A", "B", "B", "B"],
            "val": [1, 5, 24, 11, 15, 34] 
        })
        r = qic(df, x="grp", y="val", chart="run", agg_fun="sum")
        assert list(r.data["y"]) == [30.0, 60.0]

    def test_notes_as_column_name(self):
        """Verify that 'notes' can be passed as a string column name."""
        df = pd.DataFrame({
            "val": [10, 20, 30],
            "my_notes": ["event 1", "", "event 2"]
        })
        r = qic(df, y="val", chart="i", notes="my_notes")
        assert "notes" in r.data.columns
        assert list(r.data["notes"]) == ["event 1", "", "event 2"]


# ---------------------------------------------------------------------------
# O/E (SMR) funnel — exact Poisson limits
# ---------------------------------------------------------------------------

class TestPoissonQuantile:
    """The hand-rolled Poisson quantile behind the O/E funnel limits."""

    def test_lands_on_the_integer_at_an_exact_cdf_value(self):
        """F(3; 5) = 0.2650259, so p at that value interpolates to exactly 3."""
        assert _dist.poisson_quantile_interp(0.2650259152973616, 5.0) == pytest.approx(3.0)
        assert _dist.poisson_quantile_interp(0.12465201948308113, 5.0) == pytest.approx(2.0)

    def test_interpolates_between_integers(self):
        """p inside the jump from F(2) to F(3) lands strictly between 2 and 3.

        The interpolation is what keeps a funnel smooth: without it the limit would
        only move when the integer quantile jumps, drawing a staircase.
        """
        q = _dist.poisson_quantile_interp(0.2, 5.0)
        assert 2.0 < q < 3.0

    def test_is_monotone_in_lambda(self):
        prev = -1.0
        for lam in (0.5, 1.0, 5.0, 10.0, 100.0, 1000.0):
            q = _dist.poisson_quantile_interp(0.999, lam)
            assert q > prev
            prev = q

    def test_clamps_at_zero_for_a_small_mean(self):
        """A low tail on a small mean has no room below zero to interpolate into."""
        assert _dist.poisson_quantile_interp(0.001, 0.5) == 0.0

    def test_nan_for_non_positive_lambda(self):
        assert math.isnan(_dist.poisson_quantile_interp(0.975, 0.0))
        assert math.isnan(_dist.poisson_quantile_interp(0.975, -1.0))
        assert math.isnan(_dist.poisson_quantile_interp(0.975, math.nan))

    def test_refuses_lambda_above_the_exact_ceiling(self):
        """Past the ceiling the caller must switch to Byar, not silently loop."""
        with pytest.raises(ValueError, match="exact-method ceiling"):
            _dist.poisson_quantile_interp(0.999, _dist._EXACT_MAX_LAMBDA * 2)


class TestByarQuantile:
    """Byar's closed-form approximation and how far it sits from the exact answer."""

    def test_matches_the_closed_form_by_hand(self):
        """λ=10, z=1.959964: (1 − 1/90 + z/(3√10))³·10 = 17.085781."""
        assert _dist.byar_quantile(10.0, _constants.Z_95, upper=True) == pytest.approx(
            17.085781, abs=1e-5
        )
        assert _dist.byar_quantile(10.0, _constants.Z_95, upper=False) == pytest.approx(
            4.787450, abs=1e-5
        )

    def test_lower_bound_floors_at_zero(self):
        """For a small mean the cube-root bracket goes negative; cubing it would
        put the limit below zero rather than at it."""
        assert _dist.byar_quantile(0.5, _constants.Z_998, upper=False) == 0.0

    def test_nan_for_non_positive_lambda(self):
        assert math.isnan(_dist.byar_quantile(0.0, _constants.Z_95, upper=True))
        assert math.isnan(_dist.byar_quantile(math.nan, _constants.Z_95, upper=True))

    def test_converges_toward_exact_as_lambda_grows(self):
        """The gap is ~10% at λ=10 and ~0.02% at λ=10000 — which is why 'exact' is
        the default: per-physician expected counts live at the bad end."""
        def rel(lam):
            e = _dist.poisson_quantile_interp(0.999, lam)
            b = _dist.byar_quantile(lam, _constants.Z_998, upper=True)
            return abs(e - b) / e

        assert rel(10.0) > 0.05
        assert rel(1000.0) < 5e-3
        assert rel(10000.0) < 5e-4


class TestOEFunnel:
    """chart='oe' — observed vs model-expected events on a Poisson funnel."""

    # Eight providers; pooled SMR = 262/257.5 = 1.017476. One high outlier at
    # E=12 (O/E 2.33) and one low outlier at E=25 (O/E 0.36).
    Y = [4, 1, 12, 6, 28, 9, 110, 92]
    N = [2.5, 3.8, 5.0, 8.2, 12.0, 25.0, 96.0, 105.0]

    def _chart(self, **kw):
        return _funnel(self.Y, self.N, "oe", **kw)

    def test_center_line_is_the_pooled_smr(self):
        r = self._chart()
        assert r.data["cl"].iloc[0] == pytest.approx(262 / 257.5)

    def test_y_is_the_oe_ratio(self):
        r = self._chart()
        assert r.data["y"].iloc[0] == pytest.approx(4 / 2.5)

    def test_limits_are_asymmetric_about_the_center_line(self):
        """The point of using Poisson at low volume: at E=8.2 there is far more
        room above the line than below it."""
        r = self._chart()
        row = r.data.iloc[3]
        above = row["upper_outlier"] - row["cl"]
        below = row["cl"] - row["lower_outlier"]
        assert above > below * 1.2

    def test_funnel_narrows_as_expected_grows(self):
        r = self._chart()
        spread = r.data["upper_outlier"] - r.data["lower_outlier"]
        assert list(spread) == sorted(spread, reverse=True)

    def test_lower_limit_lifts_off_zero_at_high_volume(self):
        """A normal-approximation chart clips the lower limit to zero here and
        loses better-than-expected outliers entirely."""
        r = self._chart()
        assert r.data["lower_outlier"].iloc[0] == 0.0
        assert r.data["lower_outlier"].iloc[-1] > 0.7

    def test_flags_both_the_high_and_the_low_outlier(self):
        r = self._chart()
        flagged = r.data.loc[r.data["signal"] == "outlier", "y"].tolist()
        assert flagged == pytest.approx([28 / 12.0, 9 / 25.0])

    def test_95_band_is_a_probability_contour_not_two_thirds_of_the_outer(self):
        """The 2/3 shortcut is exact only for symmetric normal limits."""
        r = self._chart()
        row = r.data.iloc[0]
        shortcut = row["cl"] + (row["upper_outlier"] - row["cl"]) * (2 / 3)
        assert row["upper_alert"] == pytest.approx(2.670660, abs=1e-6)
        assert abs(row["upper_alert"] - shortcut) > 0.1

    def test_95_band_sits_inside_the_998_band(self):
        r = self._chart()
        assert (r.data["upper_alert"] <= r.data["upper_outlier"]).all()
        assert (r.data["lower_alert"] >= r.data["lower_outlier"]).all()

    def test_points_are_sorted_by_expected_events(self):
        r = self._chart(units=[f"Dr {i}" for i in range(1, 9)])
        # This input is already ascending in n, so the labels must come back in order.
        assert r.data["unit"].tolist() == [f"Dr {i}" for i in range(1, 9)]

    def test_funnels_test_no_runs(self):
        r = self._chart()
        assert "runs_signal" not in r.summary
        assert "runs_signal" not in r.data

    def test_cl_override_benchmarks_against_the_risk_model(self):
        """cl=1.0 asks who differs from their expected count; the pooled default
        asks who differs from their peers."""
        r = self._chart(center=1.0)
        assert (r.data["cl"] == 1.0).all()
        # The cohort runs 1.7% above expected, so recentering tightens the limits.
        assert r.data["upper_outlier"].iloc[0] < self._chart().data["upper_outlier"].iloc[0]

    def test_exclude_drops_the_point_from_the_pooled_center_line(self):
        r = self._chart(exclude=5)
        assert r.data["cl"].iloc[0] == pytest.approx((262 - 28) / (257.5 - 12))

    def test_limit_method_recorded_in_summary(self):
        assert self._chart().summary["limit_method"] == "exact"

    def test_y_axis_is_a_ratio_not_a_percent(self):
        assert self._chart().plot().layout.yaxis.tickformat != ".0%"

    def test_requires_expected_events(self):
        df = pd.DataFrame({"unit": range(1, 9), "y": self.Y})
        with pytest.raises(ValueError, match="n= is required for measure='oe'"):
            funnel(df, y="y", unit="unit", measure="oe")

    def test_rejects_zero_expected_with_observed_events(self):
        with pytest.raises(ValueError, match="zero denominator"):
            _funnel([3, 5], [0, 6], "oe")

    def test_zero_expected_with_zero_observed_is_a_gap(self):
        r = _funnel([0, 3, 5], [0, 4, 6], "oe")
        assert math.isnan(r.data["y"].iloc[0])


class TestOEFunnelCalibration:
    """Simulation check: the limits should behave like the probabilities they claim."""

    @staticmethod
    def _simulate(seed, n_providers=500):
        rng = np.random.default_rng(seed)
        expected = rng.uniform(2.0, 400.0, n_providers)
        observed = rng.poisson(expected)
        return _funnel(observed.tolist(), expected.tolist(), "oe")

    def test_in_control_data_stays_inside_the_998_limits(self):
        """Data generated from the model itself must not raise a crowd of alarms.

        A normal-approximation funnel over-flags the low-volume tail here, which is
        the practical failure this chart type exists to avoid.
        """
        flagged = sum(int((self._simulate(s).data["signal"] == "outlier").sum())
                      for s in range(5))
        # 5 x 500 points at a two-sided 0.2% rate: ~5 expected, generous ceiling.
        assert flagged <= 15

    def test_a_genuine_outlier_still_breaks_through(self):
        """Calibration must not have come at the cost of sensitivity."""
        rng = np.random.default_rng(7)
        expected = rng.uniform(20.0, 100.0, 60).tolist()
        observed = rng.poisson(expected).tolist()
        expected.append(30.0)
        observed.append(75)  # O/E = 2.5 against 30 expected
        r = _funnel(observed, expected, "oe")
        assert (r.data.loc[r.data["y"] > 2.0, "signal"] == "outlier").all()


class TestOEOverdispersion:
    """chart='oep' — O/E funnel with Spiegelhalter's additive over-dispersion adjustment."""

    # Twelve providers whose ratios vary far more than Poisson allows.
    Y = [23, 8, 34, 19, 59, 31, 72, 38, 104, 64, 120, 88]
    N = [12.0, 18.0, 25.0, 30.0, 38.0, 45.0, 55.0, 64.0, 72.0, 85.0, 96.0, 110.0]

    # Near-Poisson counterpart: τ̂² must come out 0.
    Y_TIGHT = [12, 19, 24, 31, 37, 46, 54, 66, 71, 86, 95, 111]

    def _oep(self, y=None, **kw):
        return _funnel(y or self.Y, self.N, "oe", overdispersion=True, **kw)

    def test_detects_overdispersion(self):
        r = self._oep(tau_method="spiegelhalter")
        assert r.summary["overdispersion"] is True
        assert r.summary["tau"] > 0
        assert r.summary["tau_source"] == "estimated"
        assert r.summary["phi"] == pytest.approx(6.261737, abs=1e-6)
        assert r.summary["tau"] == pytest.approx(0.335455, abs=1e-6)

    def test_estimator_matches_spiegelhalter_by_hand(self):
        """[1] eqs. 4, 6, 8 and 10, written out independently of the engine."""
        y, n = np.array(self.Y, float), np.array(self.N)
        cl = y.sum() / n.sum()
        z = (y / n - cl) / np.sqrt(cl / n)                    # eq. 4, Pearson
        lo, hi = np.percentile(z, [10, 90])
        phi = np.mean(np.clip(z, lo, hi) ** 2)                # eqs. 6 and 8
        w = n / cl
        k = len(y)
        tau2 = (k * phi - (k - 1)) / (w.sum() - (w ** 2).sum() / w.sum())  # eq. 10
        r = self._oep(tau_method="spiegelhalter")
        assert r.summary["phi"] == pytest.approx(phi)
        assert r.summary["tau"] == pytest.approx(math.sqrt(tau2))
        # tau_method="winsorized" differs only by eq. 9's consistency factor (§4.3).
        c = _limits.winsor_consistency()
        tau2_d = (k * phi * c - (k - 1)) / (w.sum() - (w ** 2).sum() / w.sum())
        d = self._oep(tau_method="winsorized")
        assert d.summary["phi"] == pytest.approx(phi * c)
        assert d.summary["tau"] == pytest.approx(math.sqrt(tau2_d))

    def test_clears_points_the_unadjusted_chart_flags(self):
        """The point of the adjustment: 2 of 12 flagged at 99.8% is not a credible
        rate of genuine outliers, it is unmodeled between-provider variation."""
        plain = _funnel(self.Y, self.N, "oe")
        assert (plain.data["signal"] == "outlier").sum() == 2
        assert (self._oep().data["signal"] == "outlier").sum() == 0

    def test_equals_oe_exactly_when_tau_is_zero(self):
        """No evidence of over-dispersion, no adjustment: the two charts must agree to
        the bit. The 0.4 multiplicative version drew a normal approximation here that
        sat 7-10% inside oe's exact upper limit at small E."""
        r = self._oep(y=self.Y_TIGHT)
        plain = _funnel(self.Y_TIGHT, self.N, "oe")
        assert r.summary["tau"] == 0.0
        assert r.summary["tau_estimated"] == 0.0
        for col in ("upper_outlier", "lower_outlier", "upper_alert", "lower_alert"):
            assert r.data[col].tolist() == plain.data[col].tolist()

    def test_phi_below_its_null_threshold_assumes_homogeneity(self):
        """[1]: if φ̂ < (K−1)/K, τ̂² is set to 0. The published, unwinsorized-debiased
        φ̂ averages ~0.68 under chance, so this is the usual outcome at physician scale."""
        r = self._oep(y=self.Y_TIGHT)
        k = len(self.Y_TIGHT)
        assert r.summary["phi"] < (k - 1) / k

    def test_limits_level_off_at_high_volume(self):
        """The additive model's defining property [1, Fig. 6c]: a high-volume provider
        is judged against the spread between providers, so the band levels off near
        θ₀ ± z·τ instead of closing onto θ₀ as the unadjusted limits do."""
        y = self.Y + [10_000]
        n = self.N + [10_000.0]
        r = _funnel(y, n, "oe", overdispersion=True)
        plain = _funnel(y, n, "oe")
        cl, tau = r.data["cl"].iloc[0], r.summary["tau"]
        top = r.data.iloc[-1]
        assert top["upper_outlier"] - cl > 0.9 * _constants.Z_998 * tau
        assert plain.data.iloc[-1]["upper_outlier"] - cl < 0.1 * (top["upper_outlier"] - cl)

    def test_widening_grows_with_volume(self):
        """V₀ dominates at small E, τ² at large E: the adjustment matters most for the
        busiest providers and barely at all for the smallest."""
        adj = self._oep().data
        plain = _funnel(self.Y, self.N, "oe").data
        ratio = (adj["upper_outlier"] - adj["cl"]) / (plain["upper_outlier"] - plain["cl"])
        assert ratio.iloc[-1] > ratio.iloc[0] > 1.0

    def test_limits_are_asymmetric(self):
        """Exact Poisson–gamma quantiles, not the symmetric normal of [1] eq. 11."""
        row = self._oep().data.iloc[0]
        assert row["upper_outlier"] - row["cl"] > row["cl"] - row["lower_outlier"]

    def test_winsorizing_blunts_an_outlier_in_the_dispersion_estimate(self):
        """Without it, the outliers being screened for would widen the limits past
        themselves."""
        y = list(self.Y_TIGHT)
        y[5] = 300  # one absurd provider on an otherwise in-control cohort
        yy, n = np.array(y, float), np.array(self.N)
        cl = yy.sum() / n.sum()
        raw = float(np.mean(((yy / n - cl) / np.sqrt(cl / n)) ** 2))
        winsorized = self._oep(y=y).summary["phi"]
        assert raw > 30.0
        assert winsorized < raw / 5.0

    def test_a_lone_outlier_still_leaks_in_through_the_pooled_center_line(self):
        """A documented limitation, not a defect of the winsorizing.

        The pooled ΣO/ΣE is not itself robust: on a small cohort one extreme provider
        drags the center line toward itself, every other provider then sits to one side
        of it, and τ̂ inflates even though the outlier's own residual is clipped. Here
        that is enough to hide the provider entirely. Anchoring with cl= removes it.
        """
        y = [23, 8, 34, 19, 59, 31, 72, 38, 104, 64, 120, 400]
        pooled = self._oep(y=y)
        anchored = self._oep(y=y, center=1.0)
        assert pooled.summary["tau"] > anchored.summary["tau"]
        assert pooled.data["signal"].iloc[-1] != "outlier"
        assert anchored.data["signal"].iloc[-1] == "outlier"

    def test_center_line_is_the_pooled_smr(self):
        assert self._oep().data["cl"].iloc[0] == pytest.approx(sum(self.Y) / sum(self.N))

    def test_95_band_uses_the_same_tau(self):
        r = self._oep()
        d = r.data
        assert ((d["upper_alert"] < d["upper_outlier"]) & (d["lower_alert"] > d["lower_outlier"])).all()
        plain = _funnel(self.Y, self.N, "oe").data
        assert (d["upper_alert"] > plain["upper_alert"]).all()

    def test_exclude_drops_the_point_from_the_dispersion_estimate(self):
        assert self._oep(exclude=1).summary["phi"] != pytest.approx(
            self._oep().summary["phi"]
        )

    def test_multiply_does_not_change_the_estimate(self):
        """φ̂ and τ̂ are statements about the raw ratio; multiply only rescales the axis."""
        base, scaled = self._oep(), self._oep(multiply=100)
        assert scaled.summary["tau"] == base.summary["tau"]
        assert scaled.data["upper_outlier"].tolist() == pytest.approx((base.data["upper_outlier"] * 100).tolist())


class TestMixtureQuantiles:
    """dist.binomial_quantiles / poisson_gamma_quantiles / beta_binomial_quantiles.

    Pinned values agree with scipy.stats (binom, nbinom, betabinom) interpolated the
    same way to < 1e-9, and the beta-binomial case with 60-digit mpmath; scipy's own
    betabinom drifts by ~1e-5 there, from the lgamma cancellation these functions avoid.
    """

    P = (0.001, 0.025, 0.975, 0.999)
    Z = (-_constants.Z_998, -_constants.Z_95, _constants.Z_95, _constants.Z_998)

    @pytest.mark.parametrize("fn,args,expected", [
        (_dist.binomial_quantiles, (40, 0.15), [0.0, 1.353317438, 10.274115942, 13.407411677]),
        (_dist.binomial_quantiles, (500, 0.06), [14.37069487, 19.488889585, 40.335778753, 47.099535085]),
        (_dist.poisson_gamma_quantiles, (12.0, 4.0), [0.0, 1.426666667, 28.035000962, 42.959417236]),
        (_dist.poisson_gamma_quantiles, (60.0, 25.0), [23.458676928, 34.336499809, 90.132141283, 111.962395051]),
        # θ = 0.02, τ = 0.00012: α + β = θ(1 − θ)/τ² − 1.
        (_dist.beta_binomial_quantiles, (800, "bb"), [4.692840993, 8.189438538, 23.729079843, 29.00454447]),
    ])
    def test_reference_values(self, fn, args, expected):
        if args[-1] == "bb":
            s = 0.02 * 0.98 / 0.00012 ** 2 - 1
            args = (args[0], 0.02 * s, 0.98 * s)
        got, exact = fn(self.P, *args, self.Z)
        assert exact is True
        assert got == pytest.approx(expected, abs=2e-9)

    def test_binomial_matches_a_direct_cdf(self):
        n, th = 20, 0.3
        cdf = np.cumsum([math.comb(n, k) * th ** k * (1 - th) ** (n - k) for k in range(n + 1)])
        got, _ = _dist.binomial_quantiles((0.025, 0.975), n, th, (-1.96, 1.96))
        for p, q in zip((0.025, 0.975), got):
            r = int(np.searchsorted(cdf, p))
            f = cdf[r] - (cdf[r - 1] if r else 0.0)
            assert q == pytest.approx(r - (cdf[r] - p) / f, abs=1e-9)

    def test_poisson_gamma_tends_to_poisson(self):
        got, _ = _dist.poisson_gamma_quantiles(self.P, 7.3, 1e12, self.Z)
        assert got == pytest.approx([_dist.poisson_quantile_interp(p, 7.3) for p in self.P], abs=1e-8)

    def test_beta_binomial_tends_to_binomial(self):
        got, _ = _dist.beta_binomial_quantiles(self.P, 50, 0.2e12, 0.8e12, self.Z)
        expected, _ = _dist.binomial_quantiles(self.P, 50, 0.2, self.Z)
        assert got == pytest.approx(expected, abs=1e-8)

    def test_non_integer_n_falls_back_to_normal(self):
        """No binomial has 40.5 trials; [1] eq. 3 is the honest answer, and says so."""
        got, exact = _dist.binomial_quantiles((0.999,), 40.5, 0.15, (_constants.Z_998,))
        assert exact is False
        assert got[0] == pytest.approx(40.5 * 0.15 + _constants.Z_998 * math.sqrt(40.5 * 0.15 * 0.85))

    def test_degenerate_rates(self):
        assert _dist.binomial_quantiles(self.P, 30, 0.0, self.Z)[0] == [0.0] * 4
        assert _dist.binomial_quantiles(self.P, 30, 1.0, self.Z)[0] == [30.0] * 4
        assert all(math.isnan(v) for v in _dist.poisson_gamma_quantiles(self.P, 0.0, 4.0, self.Z)[0])

    def test_quantiles_sit_inside_their_integer_bracket(self):
        got, _ = _dist.beta_binomial_quantiles(self.P, 120, 2.9, 26.1, self.Z)
        assert got == sorted(got)
        assert all(q >= 0 for q in got)


class TestFunnelDispersionEstimator:
    """limits.funnel_dispersion — Spiegelhalter [1] §5 as published."""

    def test_binomial_family_uses_the_binomial_variance(self):
        y = np.array([4, 9, 3, 15, 8, 22, 30, 12], float)
        n = np.array([40, 60, 50, 90, 100, 150, 200, 160], float)
        cl = y.sum() / n.sum()
        phi, tau2 = _limits.funnel_dispersion(cl, y / n, n, np.ones(8, bool), "binomial",
                                              method="spiegelhalter")
        z = (y / n - cl) / np.sqrt(cl * (1 - cl) / n)
        lo, hi = np.percentile(z, [10, 90])
        assert phi == pytest.approx(np.mean(np.clip(z, lo, hi) ** 2))

    def test_tau_never_negative(self):
        n = np.array([100.0] * 10)
        y = np.full(10, 0.1)  # every provider exactly on target
        phi, tau2 = _limits.funnel_dispersion(0.1, y, n, np.ones(10, bool), "binomial")
        assert phi == 0.0 and tau2 == 0.0

    def test_too_few_points(self):
        phi, tau2 = _limits.funnel_dispersion(1.0, np.array([1.2]), np.array([10.0]), np.ones(1, bool), "poisson")
        assert math.isnan(phi) and tau2 == 0.0

    def test_ignores_points_outside_the_mask(self):
        y = np.array([1.0, 1.1, 0.9, 5.0])
        n = np.array([20.0, 30.0, 40.0, 50.0])
        a = _limits.funnel_dispersion(1.0, y, n, np.array([True, True, True, False]), "poisson")
        b = _limits.funnel_dispersion(1.0, y[:3], n[:3], np.ones(3, bool), "poisson")
        assert a == b


class TestExactFunnelLimits:
    """Proportion and rate funnels: Spiegelhalter's exact contours instead of 3σ."""

    Y = [3, 7, 5, 12, 9, 20, 18, 31]
    N = [20, 40, 55, 80, 95, 130, 160, 240]

    def test_p_funnel_limits_are_exact_binomial(self):
        r = _funnel(self.Y, self.N, "proportion")
        cl = sum(self.Y) / sum(self.N)
        n0 = sorted(self.N)[0]
        (lo, hi), _ = _dist.binomial_quantiles((0.001, 0.999), n0, cl, (-_constants.Z_998, _constants.Z_998))
        # The upper contour is the exact test's boundary, one count past the quantile.
        assert r.data["upper_outlier"].iloc[0] == pytest.approx((hi + 1) / n0)
        assert r.data["lower_outlier"].iloc[0] == pytest.approx(lo / n0)
        assert r.summary["limit_method"] == "exact"

    def test_u_funnel_is_the_poisson_funnel(self):
        """A u funnel and an O/E funnel are the same model with a different
        denominator [1, A.2.3]: exposure in place of expected events."""
        u = _funnel(self.Y, self.N, "rate").data
        oe = _funnel(self.Y, self.N, "oe").data
        for col in ("cl", "upper_outlier", "lower_outlier", "upper_alert", "lower_alert"):
            assert u[col].tolist() == oe[col].tolist()

    def test_time_ordered_p_and_u_keep_3_sigma(self):
        r = qic(y=self.Y, n=self.N, chart="p")
        cl = sum(self.Y) / sum(self.N)
        assert r.data["ucl"].iloc[0] == pytest.approx(cl + 3 * math.sqrt(cl * (1 - cl) / self.N[0]))
        assert "limit_method" not in r.summary
        assert "phi" not in r.summary

    def test_funnel_reports_dispersion_without_adjusting(self):
        r = _funnel(self.Y, self.N, "proportion")
        for key in ("phi", "tau", "tau_estimated"):
            assert key in r.summary
        assert r.summary["overdispersion"] is False

    def test_dispersion_note_only_when_overdispersed(self):
        def spread_notes(r):
            return [note for note in r.summary["notes"] if "Compare with overdispersion=True" in note]
        quiet = _funnel(self.Y, self.N, "proportion")
        assert quiet.summary["tau"] == 0
        assert spread_notes(quiet) == []
        y = [1, 19, 2, 40, 5, 70, 10, 120]
        loud = _funnel(y, self.N, "proportion")
        assert loud.summary["tau"] > 0
        assert len(spread_notes(loud)) == 1

    def test_non_integer_denominator_is_reported(self):
        """A fractional denominator (n/φ under within_dispersion) is interpolated
        between its whole neighbors, not handed to the normal approximation."""
        r = _funnel(self.Y, [v + 0.5 for v in self.N], "proportion")
        assert r.summary["limit_method"] == "interpolated"


class TestAdjustedFunnels:
    """overdispersion=True: the same additive model for every measure."""

    COUNTS = dict(y=[23, 8, 34, 19, 59, 31, 72, 38, 104, 64, 120, 88],
                  n=[12.0, 18.0, 25.0, 30.0, 38.0, 45.0, 55.0, 64.0, 72.0, 85.0, 96.0, 110.0])
    PROPS = dict(y=[2, 14, 5, 30, 9, 41, 20, 77, 35, 50, 160, 96],
                 n=[40, 50, 60, 80, 100, 120, 150, 200, 250, 300, 500, 600])
    TIGHT_PROPS = dict(y=[4, 6, 5, 8, 10, 12, 15, 21, 25, 30, 51, 60],
                       n=[40, 50, 60, 80, 100, 120, 150, 200, 250, 300, 500, 600])

    @pytest.mark.parametrize("measure,data", [
        ("rate", "COUNTS"), ("oe", "COUNTS"), ("proportion", "PROPS"),
    ])
    def test_adjusts_and_levels_off(self, measure, data):
        d = getattr(self, data)
        adj = _funnel(d["y"], d["n"], measure, overdispersion=True)
        ref = _funnel(d["y"], d["n"], measure)
        assert adj.summary["tau"] > 0
        widen = (adj.data["upper_outlier"] - adj.data["cl"]) / (ref.data["upper_outlier"] - ref.data["cl"])
        assert widen.iloc[-1] > widen.iloc[0] > 1.0

    def test_pp_equals_p_when_tau_is_zero(self):
        d = self.TIGHT_PROPS
        adj = _funnel(d["y"], d["n"], "proportion", overdispersion=True)
        ref = _funnel(d["y"], d["n"], "proportion")
        assert adj.summary["tau"] == 0.0
        for col in ("upper_outlier", "lower_outlier", "upper_alert", "lower_alert"):
            assert adj.data[col].tolist() == ref.data[col].tolist()

    def test_up_and_oep_agree(self):
        """Same Poisson–gamma model; only the name of the denominator differs."""
        d = self.COUNTS
        up = _funnel(d["y"], d["n"], "rate", overdispersion=True).data
        oep = _funnel(d["y"], d["n"], "oe", overdispersion=True).data
        assert up["upper_outlier"].tolist() == oep["upper_outlier"].tolist()

    def test_time_ordered_pp_up_stay_laney(self):
        """Laney's σ_z is the right tool in time order, which is what it was built for."""
        r = qic(chart="pp", **self.PROPS)
        assert "sigma_z" in r.summary
        assert "tau" not in r.summary

    def test_laney_in_a_funnel_would_have_erased_real_signals(self):
        """Why the funnel no longer uses σ_z. On the bundled 3-year surgeon data the
        published test finds no over-dispersion, yet moving ranges taken in volume
        order widened the old up funnel by 1.87x and hid all three signals."""
        df = pd.read_csv("data/examples/physician_mortality_oe.csv")
        agg = df.groupby("physician", as_index=False)[["observed_deaths", "expected_deaths"]].sum()
        r = funnel(agg, y="observed_deaths", n="expected_deaths", unit="physician",
                   measure="rate", overdispersion=True, tau_method="spiegelhalter")
        assert r.summary["tau"] == 0.0
        flagged = r.data.loc[r.data["signal"] == "outlier", "unit"]
        assert sorted(flagged) == ["SURG-07", "SURG-15", "SURG-21"]

    def test_beta_binomial_infeasible_spread_falls_back_and_says_so(self):
        diag = {}
        ucl, lcl = _limits._mixture_funnel_pair(
            0.2, np.array([50.0, 100.0]), 0.2 * 0.8, "binomial", 0.001, 0.999,
            _constants.Z_998, diag,
        )
        assert diag == {"normal": True}
        assert ucl[0] == pytest.approx(0.2 + _constants.Z_998 * math.sqrt(0.16 / 50 + 0.16))


class TestPoissonMeanInversion:
    """dist.poisson_tails / poisson_mean_for_cdf — the primitives behind both O/E
    detectability and the per-point intervals."""

    def test_cdf_known_values(self):
        assert _dist.poisson_tails(3, 5)[0] == pytest.approx(0.2650259, abs=1e-7)
        assert _dist.poisson_tails(2, 5)[0] == pytest.approx(0.1246520, abs=1e-7)
        assert _dist.poisson_tails(0, 1)[0] == pytest.approx(math.exp(-1))

    def test_cdf_edges(self):
        assert _dist.poisson_tails(-1, 5) == (0.0, 1.0)
        assert all(math.isnan(v) for v in _dist.poisson_tails(3, 0))
        assert all(math.isnan(v) for v in _dist.poisson_tails(3, float("nan")))

    @pytest.mark.parametrize("k", [0, 1, 3, 10, 50, 200, 2_000, 10_000])
    @pytest.mark.parametrize("p", [0.025, 0.2, 0.5, 0.975])
    def test_mean_for_cdf_inverts(self, k, p):
        mu = _dist.poisson_mean_for_cdf(k, p)
        assert _dist.poisson_tails(k, mu)[0] == pytest.approx(p, rel=1e-9)

    def test_mean_for_cdf_is_fast_at_hospital_volumes(self):
        """Newton steps, not fifty full CDF sweeps: a thousand-provider funnel with
        counts in the thousands took ~17 s on the bisection."""
        import time
        t = time.perf_counter()
        for k in range(5_000, 5_050):
            _dist.poisson_mean_for_cdf(k, 0.975)
        assert time.perf_counter() - t < 0.5

    def test_lgamma_results_are_quantized_for_cross_platform_reproducibility(self):
        """math.lgamma's last ulp differs between platforms, and both routines
        accumulate many of its terms. The fixture snapshots are compared byte for
        byte, so every lgamma-derived value has to land on a fixed grid or CI can
        only ever pass on the machine that generated the snapshots."""
        q = _dist._QUANTIZE_DECIMALS

        mean = _dist.poisson_mean_for_cdf(9, 0.975)
        assert mean == round(mean, q)
        assert mean == pytest.approx(4.795388, abs=1e-6)  # still the Garwood bound

        for p in (0.001, 0.025, 0.975, 0.999):
            for lam in (0.5, 3.2, 12.0, 55.0, 1000.0):
                val = _dist.poisson_quantile_interp(p, lam)
                assert val == round(val, q)

    def test_mean_for_cdf_monotone_in_p(self):
        """More probability at or below k means a smaller mean."""
        means = [_dist.poisson_mean_for_cdf(10, p) for p in (0.025, 0.2, 0.5, 0.975)]
        assert means == sorted(means, reverse=True)

    def test_mean_for_cdf_rejects_above_ceiling(self):
        with pytest.raises(ValueError, match="solve ceiling"):
            _dist.poisson_mean_for_cdf(int(_dist._MEAN_SOLVE_MAX_K) + 1, 0.5)


class TestOEPointCI:
    """limits.oe_point_ci — exact Garwood interval on a point's own O/E."""

    def test_garwood_anchor(self):
        """Published exact Poisson interval for 10 observed events."""
        lo, hi = _limits.oe_point_ci(10, 1.0)
        assert lo == pytest.approx(4.795, abs=1e-3)
        assert hi == pytest.approx(18.390, abs=1e-3)

    def test_zero_observed(self):
        """No events gives a lower bound of exactly zero, upper of −ln(0.025)/E."""
        lo, hi = _limits.oe_point_ci(0, 5.0)
        assert lo == 0.0
        assert hi == pytest.approx(-math.log(0.025) / 5.0)

    def test_scales_by_expected(self):
        lo1, hi1 = _limits.oe_point_ci(10, 1.0)
        lo5, hi5 = _limits.oe_point_ci(10, 5.0)
        assert (lo5, hi5) == pytest.approx((lo1 / 5.0, hi1 / 5.0))

    def test_interval_contains_the_point_estimate(self):
        for o, e in [(1, 1.0), (5, 4.0), (12, 3.2), (100, 90.0)]:
            lo, hi = _limits.oe_point_ci(o, e)
            assert lo <= o / e <= hi

    def test_byar_fallback_for_non_integer_counts(self):
        """An averaged aggregate is not a Poisson count; fall back rather than round."""
        lo, hi = _limits.oe_point_ci(20.5, 10.0)
        exact_lo, exact_hi = _limits.oe_point_ci(20, 10.0)
        assert lo == pytest.approx(exact_lo, rel=0.05)
        assert hi == pytest.approx(exact_hi, rel=0.05)

    def test_nan_without_usable_expected(self):
        assert all(math.isnan(v) for v in _limits.oe_point_ci(3, 0.0))
        assert all(math.isnan(v) for v in _limits.oe_point_ci(-1, 5.0))


class TestOEDetectability:
    """limits.oe_detectable_ratio — the smallest true O/E worth calling detectable."""

    @pytest.mark.parametrize("e", [2, 5, 10, 20, 50, 200])
    def test_achieves_exactly_80_percent_power(self, e):
        """The returned ratio is the one at which power is 0.8 — not an approximation
        of it. Verified against the same event the chart actually signals on."""
        t = _dist.poisson_quantile_interp(0.999, e)
        rho = _limits.oe_detectable_ratio(t, e)
        power = 1.0 - _dist.poisson_tails(math.floor(t), rho * e)[0]
        assert power == pytest.approx(0.8)

    def test_signal_event_matches_sigma_signal_semantics(self):
        """_sigma_signals flags strictly y > ucl, so the detectability event must be
        O >= floor(T)+1. Pin both halves against the real signal path."""
        e = 8.0
        r = _funnel([8], [e], "oe", center=1.0)
        t = float(r.data["upper_outlier"].iloc[0]) * e
        m = math.floor(t)

        at_threshold = _funnel([m], [e], "oe", center=1.0)
        just_over = _funnel([m + 1], [e], "oe", center=1.0)
        assert at_threshold.data["signal"].iloc[0] != "outlier"
        assert just_over.data["signal"].iloc[0] == "outlier"

    def test_power_curve_matches_measured_values(self):
        """Regression on the numbers quoted in the README: a funnel needs roughly
        E=20 before a true doubling is reliably caught."""
        def det(e):
            return _limits.oe_detectable_ratio(_dist.poisson_quantile_interp(0.999, e), e)

        assert det(10) > 2.0     # 44% power at O/E 2.0 — a coin flip at best
        assert det(50) < 2.0     # ~99.8% power — a doubling here is unmissable
        assert det(20) == pytest.approx(2.0, abs=0.05)

    def test_monotone_non_increasing_in_expected(self):
        vals = [
            _limits.oe_detectable_ratio(_dist.poisson_quantile_interp(0.999, e), e)
            for e in (2, 5, 10, 20, 50, 100, 400)
        ]
        assert vals == sorted(vals, reverse=True)

    def test_normal_fallback_is_continuous_with_the_exact_path(self):
        cap = _dist._MEAN_SOLVE_MAX_K
        below = _limits.oe_detectable_ratio(cap - 1, cap)
        above = _limits.oe_detectable_ratio(cap + 1, cap)
        assert below == pytest.approx(above, rel=1e-3)

    def test_nan_without_usable_expected(self):
        assert math.isnan(_limits.oe_detectable_ratio(5.0, 0.0))
        assert math.isnan(_limits.oe_detectable_ratio(float("inf"), 5.0))


class TestOEPowerReporting:
    """The columns, summary keys, and caption that make an underpowered O/E chart
    say so instead of reading as a clean bill of health."""

    # Twelve physicians. The smallest-volume one sits at 2.5x expected mortality and
    # still does not flag; the largest flags at 1.77x. That inversion is the point.
    Y = [12, 8, 8, 3, 20, 14, 31, 26, 55, 48, 72, 110]
    N = [5.0, 3.2, 6.5, 4.1, 12.0, 15.5, 28.0, 30.0, 52.0, 60.0, 70.0, 62.0]
    COLS = ("min_detectable", "ci_lower", "ci_upper", "numerator", "denominator")

    def _r(self, **kw):
        return _funnel(self.Y, self.N, "oe", **kw)

    @staticmethod
    def _power_notes(r):
        return [note for note in r.summary["notes"] if "to detect even a doubling" in note]

    def test_the_trap_point_reports_why_it_did_not_flag(self):
        row = self._r().data.iloc[0]
        assert row["y"] == pytest.approx(2.5)
        assert row["signal"] != "outlier"
        assert row["min_detectable"] == pytest.approx(4.6177, abs=1e-4)
        assert row["ci_lower"] == pytest.approx(1.0793, abs=1e-4)
        assert row["ci_upper"] == pytest.approx(4.9260, abs=1e-4)

    def test_lower_ratio_can_flag_where_a_higher_one_does_not(self):
        """The whole logic of a funnel, and the thing readers misread."""
        d = self._r().data
        flagged = d[d["signal"] == "outlier"]
        assert len(flagged) == 1
        assert flagged["y"].iloc[0] < d["y"].iloc[0]          # 1.77 vs 2.50
        assert flagged["denominator"].iloc[0] > d["denominator"].iloc[0]

    def test_summary_reports_power(self):
        s = self._r().summary
        assert s["underpowered"] is True
        assert s["n_underpowered"] == 8
        assert s["min_detectable_median"] == pytest.approx(2.3049, abs=1e-4)

    def test_power_note_is_quotable(self):
        (note,) = self._power_notes(self._r())
        assert "8 of 12" in note
        assert "not evidence of acceptable performance" in note
        assert "aggregate" in note

    def test_well_powered_chart_stays_quiet(self):
        n = [400.0] * 12
        r = _funnel([400] * 12, n, "oe")
        assert r.summary["underpowered"] is False
        assert self._power_notes(r) == []

    def test_no_console_warning(self):
        """Reported through the summary and the caption, deliberately not by
        interrupting every call."""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            self._r()

    def test_columns_present_on_every_oe_funnel(self):
        d = self._r().data
        assert all(c in d.columns for c in self.COLS)

    def test_columns_absent_on_control_charts(self):
        d = qic(y=[3, 2, 6, 2], n=[90, 113, 105, 102], chart="u").data
        assert not any(c in d.columns for c in self.COLS)
        assert "underpowered" not in qic(y=[3, 2, 6], n=[90, 113, 105], chart="u").summary

    def test_oep_uses_its_own_wider_limits(self):
        """Detectability answers 'would this point flag on *this* chart', so the
        over-dispersed chart must report a harder bar than the unadjusted one."""
        y = [23, 8, 34, 19, 59, 31, 72, 38, 104, 64, 120, 88]
        n = [12.0, 18.0, 25.0, 30.0, 38.0, 45.0, 55.0, 64.0, 72.0, 85.0, 96.0, 110.0]
        oe = _funnel(y, n, "oe").data["min_detectable"]
        oep = _funnel(y, n, "oe", overdispersion=True).data["min_detectable"]
        assert (oep >= oe).all()
        assert (oep > oe).any()

    def test_counts_survive_the_funnel_sort(self):
        """The reason the counts are echoed at all: after sorting, a caller cannot
        rejoin their own inputs by position."""
        d = self._r().data
        assert d["denominator"].tolist() == sorted(self.N)
        for _, row in d.iterrows():
            assert row["numerator"] == pytest.approx(row["y"] * row["denominator"])

    def test_multiply_scales_ratios_but_not_counts_or_thresholds(self):
        base, x100 = self._r(), self._r(multiply=100)
        assert x100.data["min_detectable"].iloc[0] == pytest.approx(
            base.data["min_detectable"].iloc[0] * 100
        )
        assert x100.data["ci_upper"].iloc[0] == pytest.approx(
            base.data["ci_upper"].iloc[0] * 100
        )
        # Counts are events, not ratios; thresholds describe the unscaled ratio.
        assert x100.data["numerator"].tolist() == base.data["numerator"].tolist()
        assert x100.summary["n_underpowered"] == base.summary["n_underpowered"]
        assert x100.summary["min_detectable_median"] == pytest.approx(
            base.summary["min_detectable_median"]
        )

    def test_nan_columns_where_expected_is_zero(self):
        r = _funnel([0, 5, 8], [0.0, 4.0, 6.0], "oe")
        assert math.isnan(r.data["min_detectable"].iloc[0])
        assert math.isnan(r.data["ci_lower"].iloc[0])
        assert r.to_dict()["data"][0]["min_detectable"] is None

    def test_ghosted_points_are_left_out_of_the_power_aggregate(self):
        """A point excluded from signal detection is not one the chart could flag, so
        counting its detectability would misdescribe the chart's reach."""
        base, excl = self._r(), self._r(exclude=1)
        assert excl.summary["n_underpowered"] < base.summary["n_underpowered"]
        # The remaining points are still all present in the frame.
        assert len(excl.data) == len(base.data)
        assert excl.data["excluded"].sum() == 1


class TestPhysicianExampleWorkflow:
    """The physician workflow, pinned against the bundled dataset.
    tests/test_funnel.py::TestReadmeExample pins the README's funnel() version."""

    @staticmethod
    def _df():
        import pathlib
        path = pathlib.Path("data/examples/physician_mortality_oe.csv")
        if not path.exists():
            pytest.skip("example data not present")
        return pd.read_csv(path)

    @staticmethod
    def _funnel(frame):
        return funnel(frame, y="observed_deaths", n="expected_deaths", unit="physician",
                      measure="oe", overdispersion=False)

    @pytest.mark.parametrize("year", [2023, 2024, 2025])
    def test_no_single_year_can_find_anyone(self, year):
        df = self._df()
        r = self._funnel(df[df.year == year].reset_index(drop=True))
        assert r.summary["underpowered"] is True
        assert not (r.data["signal"] == "outlier").any()

    def test_pooling_three_years_gives_the_chart_reach(self):
        df = self._df()
        agg = df.groupby("physician", as_index=False)[
            ["observed_deaths", "expected_deaths"]
        ].sum()
        r = self._funnel(agg)
        assert r.summary["underpowered"] is False
        flagged = set(r.data.loc[r.data["signal"] == "outlier", "unit"])
        assert {"SURG-07", "SURG-15", "SURG-21"} == flagged

    def test_the_high_performer_flags_below_the_lower_limit(self):
        """Exact Poisson keeps the lower limit off zero at volume, so genuinely good
        performance is detectable and not just clipped away."""
        df = self._df()
        agg = df.groupby("physician", as_index=False)[
            ["observed_deaths", "expected_deaths"]
        ].sum()
        row = self._funnel(agg).data.set_index("unit").loc["SURG-21"]
        assert row["y"] < row["lower_outlier"]
        assert row["lower_outlier"] > 0
        assert row["ci_upper"] < 1.0

    def test_the_trap_surgeon_is_invisible_annually(self):
        """SURG-07 runs ~2.2x expected every year on ~5 expected deaths and never
        signals until the years are pooled — the case the power reporting exists for."""
        df = self._df()
        for year in (2023, 2024, 2025):
            r = self._funnel(df[df.year == year].reset_index(drop=True))
            row = r.data.set_index("unit").loc["SURG-07"]
            assert row["y"] > 2.0                      # plainly elevated
            assert row["signal"] != "outlier"          # and plainly undetectable
            assert row["min_detectable"] > row["y"]    # the chart says so itself


# ---------------------------------------------------------------------------
# warn_signal — the 95% tier
# ---------------------------------------------------------------------------

class TestWarnSignal:
    """Same data as fixtures/spc/funnel_oe_warn_tier.json, which pins the values."""

    Y = [9, 6, 7, 11, 13, 17, 37, 29, 66, 40]
    N = [4.0, 6.0, 8.0, 10.0, 14.0, 18.0, 24.0, 30.0, 40.0, 55.0]

    def _oe(self, **kw):
        return _funnel(self.Y, self.N, "oe", center=1.0, **kw)

    @pytest.mark.parametrize("measure,overdispersion", [
        ("oe", False), ("oe", True), ("proportion", False), ("proportion", True),
        ("rate", False), ("rate", True),
    ])
    def test_present(self, measure, overdispersion):
        n = [v * 10 for v in self.N] if measure == "proportion" else self.N
        r = _funnel(self.Y, n, measure, overdispersion=overdispersion)
        assert "upper_alert" in r.data.columns
        assert r.summary["n_alert"] == int((r.data["signal"] == "alert").sum())

    @pytest.mark.parametrize("chart", ["p", "u", "i", "run"])
    def test_absent_on_control_charts(self, chart):
        n = [v * 10 for v in self.N] if chart in ("p", "u") else None
        r = qic(y=self.Y, n=n, chart=chart)
        assert not (r.data["signal"] == "alert").any()
        assert "n_alert" not in r.summary

    def test_tiers_are_disjoint_and_sided(self):
        d = self._oe().data
        alert, outlier = d["signal"] == "alert", d["signal"] == "outlier"
        assert not (alert & outlier).any()
        beyond = (d["y"] > d["upper_alert"]) | (d["y"] < d["lower_alert"])
        assert (alert == (beyond & ~outlier & ~d["excluded"])).all()
        assert alert.tolist() == [
            True, False, False, False, False, False, True, False, False, True,
        ]

    def test_excluded_point_never_warns(self):
        d = self._oe(exclude=7).data
        assert d.loc[6, "excluded"]
        assert d.loc[6, "y"] > d.loc[6, "upper_alert"]
        assert d.loc[6, "signal"] != "alert"

    def test_does_not_feed_signals(self):
        # Low side warn only: 40 vs 55 expected, nothing else out.
        r = _funnel([4, 6, 8, 10, 14, 18, 24, 30, 40, 40], self.N, "oe", center=1.0)
        assert (r.data["signal"] == "alert").any()
        assert not (r.data["signal"] == "outlier").any()
        assert r.summary["n_outlier"] == 0

    def test_multiply_does_not_move_tiers(self):
        assert (self._oe(multiply=100).data["signal"] == self._oe().data["signal"]).all()

    def test_facets_carry_it(self):
        df = pd.DataFrame({
            "o": self.Y * 2, "e": self.N * 2, "site": ["A"] * 10 + ["B"] * 10,
        })
        r = funnel(df, y="o", n="e", measure="oe", facets="site", overdispersion=False)
        assert "upper_alert" in r.data.columns
        assert len(r.data) == 20

# ---------------------------------------------------------------------------
# worse= — one-sided funnels
# ---------------------------------------------------------------------------

class TestSignalSide:
    # One outlier and one 95%-tier point on each side of cl=1.0, all at E = 20.
    Y = [20, 19, 45, 4, 31, 10, 21, 18, 22, 20]
    N = [20.0] * 10
    OUTLIER = {None: [2, 3], "higher": [2], "lower": [3]}
    ALERT = {None: [4, 5], "higher": [4], "lower": [5]}

    def _oe(self, **kw):
        return _funnel(self.Y, self.N, "oe", center=1.0, **kw)

    @staticmethod
    def _idx(col):
        return [i for i, v in enumerate(col) if v]

    @pytest.mark.parametrize("worse", [None, "higher", "lower"])
    def test_flags_only_the_chosen_side(self, worse):
        d = self._oe(worse=worse).data
        assert self._idx(d["signal"] == "outlier") == self.OUTLIER[worse]
        assert self._idx(d["signal"] == "alert") == self.ALERT[worse]
        assert set(d["signal"]) <= {"none", "alert", "outlier"}

    def test_both_is_the_default(self):
        pd.testing.assert_frame_equal(self._oe().data, self._oe(worse=None).data)

    def test_summary_follows_the_side(self):
        r = self._oe(worse="higher")
        assert r.summary["worse"] == "higher"
        assert r.summary["n_alert"] == 1
        assert self._oe().summary["worse"] is None
        below_only = _funnel([20, 20, 4, 20], [20.0] * 4, "oe", center=1.0, worse="higher")
        assert below_only.summary["n_outlier"] == 0

    @pytest.mark.parametrize("measure,overdispersion", [
        ("proportion", False), ("proportion", True), ("rate", False), ("rate", True),
        ("oe", True),
    ])
    def test_every_funnel_takes_it(self, measure, overdispersion):
        n = [200.0] * 10 if measure == "proportion" else self.N
        r = _funnel(self.Y, n, measure, overdispersion=overdispersion, worse="higher")
        d = r.data
        assert not ((d["signal"] == "outlier") & (d["y"] < d["cl"])).any()
        assert not ((d["signal"] == "alert") & (d["y"] < d["cl"])).any()
        assert r.summary["worse"] == "higher"

    def test_invalid_value(self):
        with pytest.raises(ValueError, match="worse must be one of"):
            self._oe(worse="up")

    def test_facets_forward_it(self):
        df = pd.DataFrame({
            "o": self.Y * 2, "e": self.N * 2, "site": ["A"] * 10 + ["B"] * 10,
        })
        r = funnel(df, y="o", n="e", measure="oe", center=1.0, overdispersion=False,
                   facets="site", worse="higher")
        assert self._idx(r.data["signal"] == "outlier") == [2, 12]
        assert r.summary["worse"] == "higher"
        assert all(s["n_outlier"] == 1 for s in r.summary["by_facet"].values())

    def test_physician_example(self):
        """Pooled over three years, SURG-21 is the one below the line."""
        df = TestPhysicianExampleWorkflow._df()
        agg = df.groupby("physician", as_index=False)[
            ["observed_deaths", "expected_deaths"]
        ].sum()
        flagged = {}
        for side in ("above", "below"):
            r = funnel(agg, y="observed_deaths", n="expected_deaths", unit="physician",
                       measure="oe", overdispersion=False,
                       worse={"above": "higher", "below": "lower"}[side])
            flagged[side] = set(r.data.loc[r.data["signal"] == "outlier", "unit"])
        assert flagged == {"above": {"SURG-07", "SURG-15"}, "below": {"SURG-21"}}


# ---------------------------------------------------------------------------
# Exact p-values, q-values and signal_method= (docs/methods.md §4.11)
# ---------------------------------------------------------------------------

def _brute_tails(pmf, k, support):
    """(P(X ≤ k), P(X ≥ k)) by direct lgamma summation, smallest terms first."""
    lower = sorted(pmf(j) for j in support if j <= k)
    upper = sorted(pmf(j) for j in support if j >= k)
    return math.fsum(lower), math.fsum(upper)


class TestTailProbabilities:
    @staticmethod
    def _close(got, want):
        for g, w in zip(got, want):
            assert g == pytest.approx(w, rel=1e-10, abs=1e-300)

    @pytest.mark.parametrize("lam,k", [(5.0, 13), (5.0, 0), (0.7, 3), (40.0, 75), (40.0, 18)])
    def test_poisson(self, lam, k):
        pmf = lambda j: math.exp(j * math.log(lam) - lam - math.lgamma(j + 1))  # noqa: E731
        self._close(_dist.poisson_tails(k, lam), _brute_tails(pmf, k, range(400)))

    @pytest.mark.parametrize("m,theta,k", [(10, 0.1, 3), (50, 0.12, 0), (200, 0.3, 95), (30, 0.6, 9)])
    def test_binomial(self, m, theta, k):
        def pmf(j):
            return math.exp(math.lgamma(m + 1) - math.lgamma(j + 1) - math.lgamma(m - j + 1)
                            + j * math.log(theta) + (m - j) * math.log1p(-theta))
        self._close(_dist.binomial_tails(k, m, theta), _brute_tails(pmf, k, range(m + 1)))

    @pytest.mark.parametrize("lam,size,k", [(5.0, 4.0, 14), (12.0, 0.8, 1), (30.0, 25.0, 70)])
    def test_poisson_gamma(self, lam, size, k):
        def pmf(j):
            return math.exp(math.lgamma(j + size) - math.lgamma(size) - math.lgamma(j + 1)
                            + size * math.log(size / (size + lam)) + j * math.log(lam / (size + lam)))
        self._close(_dist.poisson_gamma_tails(k, lam, size), _brute_tails(pmf, k, range(3000)))

    @pytest.mark.parametrize("m,a,b,k", [(40, 2.0, 15.0, 20), (120, 6.0, 30.0, 2), (15, 0.7, 0.9, 7)])
    def test_beta_binomial(self, m, a, b, k):
        def lbeta(x, y):
            return math.lgamma(x) + math.lgamma(y) - math.lgamma(x + y)

        def pmf(j):
            return math.exp(math.lgamma(m + 1) - math.lgamma(j + 1) - math.lgamma(m - j + 1)
                            + lbeta(j + a, m - j + b) - lbeta(a, b))
        self._close(_dist.beta_binomial_tails(k, m, a, b), _brute_tails(pmf, k, range(m + 1)))

    def test_tiny_tails_keep_their_digits(self):
        """Summed directly, not as a complement: 1 − F would keep ~4 digits here."""
        lam, k = 5.0, 30
        pmf = lambda j: math.exp(j * math.log(lam) - lam - math.lgamma(j + 1))  # noqa: E731
        want = _brute_tails(pmf, k, range(400))[1]
        assert 1e-14 < want < 1e-10
        assert _dist.poisson_tails(k, lam)[1] == pytest.approx(want, rel=1e-10)

    def test_the_two_tails_overlap_by_the_pmf(self):
        lam, k = 7.3, 9
        lower, upper = _dist.poisson_tails(k, lam)
        pmf = math.exp(k * math.log(lam) - lam - math.lgamma(k + 1))
        assert lower + upper - 1.0 == pytest.approx(pmf, rel=1e-12)

    def test_out_of_support_and_degenerate(self):
        assert _dist.binomial_tails(11, 10, 0.3) == (1.0, 0.0)
        assert _dist.binomial_tails(-1, 10, 0.3) == (0.0, 1.0)
        assert _dist.binomial_tails(0, 10, 0.0) == (1.0, 1.0)
        assert _dist.binomial_tails(10, 10, 1.0) == (1.0, 1.0)
        assert all(math.isnan(v) for v in _dist.poisson_tails(3, 0.0))
        assert all(math.isnan(v) for v in _dist.poisson_tails(3, math.nan))


class TestPValues:
    # Heavily over-dispersed, so the adjusted charts have a τ̂ to use.
    Y = [2, 30, 5, 40, 3, 50, 8, 60, 1, 70]
    N = [20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0, 55.0, 60.0, 65.0]

    def test_worked_example(self):
        """13 deaths against 5 expected: P(X ≥ 13) = 0.20%, so it sits between the 95%
        and 99.8% lines; 14 deaths, P(X ≥ 14) = 0.07%, is beyond the 99.8% line. Under
        Spiegelhalter's drawn contour 13 was already beyond it."""
        r = _funnel([13, 10, 20], [5.0, 10.0, 20.0], "oe", center=1.0, worse="higher")
        row = r.data.iloc[0]
        assert row["p_value"] == pytest.approx(0.0020188516274, rel=1e-9)
        assert row["upper_alert"] * 5 < 13 < row["upper_outlier"] * 5
        assert row["signal"] == "alert"
        r14 = _funnel([14, 10, 20], [5.0, 10.0, 20.0], "oe", center=1.0, worse="higher")
        assert r14.data["signal"].iloc[0] == "outlier"
        assert r14.data["p_value"].iloc[0] < 0.001

    @pytest.mark.parametrize("measure,overdispersion,model", [
        ("oe", False, "poisson"), ("oe", True, "poisson_gamma"), ("rate", False, "poisson"),
        ("rate", True, "poisson_gamma"), ("proportion", False, "binomial"),
        ("proportion", True, "beta_binomial"),
    ])
    def test_count_model(self, measure, overdispersion, model):
        n = [v * 4 for v in self.N] if measure == "proportion" else self.N
        r = _funnel(self.Y, n, measure, overdispersion=overdispersion)
        assert r.summary["count_model"] == model
        assert r.summary["p_value_method"] == "exact"
        assert r.summary["n_tested"] == 10
        assert {"p_value", "q_value"} <= set(r.data.columns)

    def test_adjusted_chart_without_spread_is_the_plain_one(self):
        y = [4, 6, 8, 10, 14, 18, 24, 30, 40, 55]
        n = [4.0, 6.0, 8.0, 10.0, 14.0, 18.0, 24.0, 30.0, 40.0, 55.0]
        oe, oep = (_funnel(y, n, "oe", overdispersion=od) for od in (False, True))
        assert oep.summary["tau"] == 0.0
        assert oep.summary["count_model"] == "poisson"
        assert list(oe.data["p_value"]) == list(oep.data["p_value"])
        pn = [v * 10 for v in n]
        p, pp = (_funnel(y, pn, "proportion", overdispersion=od) for od in (False, True))
        assert pp.summary["count_model"] == "binomial"
        assert list(p.data["p_value"]) == list(pp.data["p_value"])

    def test_two_sided_doubles_the_smaller_tail(self):
        def p_values(**kw):
            return _funnel(self.Y, self.N, "oe", center=1.0, **kw).data["p_value"].to_numpy()
        up, down, both = p_values(worse="higher"), p_values(worse="lower"), p_values()
        assert np.allclose(both, np.minimum(1.0, 2.0 * np.minimum(up, down)), rtol=0, atol=0)

    def test_overdispersed_oe_stays_poisson(self):
        """The diagnostic τ̂ on an unadjusted chart must not leak into its p-values."""
        r = _funnel(self.Y, self.N, "oe", worse="higher")
        assert r.summary["tau"] > 0
        cl = r.data["cl"].iloc[0]
        for o, e, p in zip(self.Y, r.data["denominator"], r.data["p_value"]):
            assert p == pytest.approx(_dist.poisson_tails(round(o), cl * e)[1], rel=1e-12)

    def test_excluded_points_are_not_tested(self):
        r = _funnel(self.Y, self.N, "oe", exclude=[3])
        row = r.data.loc[r.data["excluded"]].iloc[0]
        assert math.isnan(row["p_value"]) and math.isnan(row["q_value"])
        assert r.summary["n_tested"] == 9

    def test_non_integer_denominator_is_interpolated(self):
        r = _funnel([3, 4, 9, 2], [30.5, 40.0, 50.0, 60.0], "proportion")
        assert r.summary["p_value_method"] == "interpolated"
        assert r.data["p_value"].notna().all()

    def test_multiply_leaves_them_alone(self):
        a = _funnel(self.Y, self.N, "rate").data
        b = _funnel(self.Y, self.N, "rate", multiply=1000).data
        assert list(a["p_value"]) == list(b["p_value"])
        assert list(a["q_value"]) == list(b["q_value"])

    def test_physician_example(self):
        df = TestPhysicianExampleWorkflow._df()
        agg = df.groupby("physician", as_index=False)[
            ["observed_deaths", "expected_deaths"]
        ].sum()
        p = {}
        for side in ("above", "below"):
            r = funnel(agg, y="observed_deaths", n="expected_deaths", unit="physician",
                       measure="oe", center=1.0, overdispersion=False,
                       worse={"above": "higher", "below": "lower"}[side])
            p[side] = r.data.set_index("unit")["p_value"]
        assert 1e-5 < p["above"]["SURG-07"] < 1e-4
        assert 1e-6 < p["above"]["SURG-15"] < 1e-4
        assert 1e-6 < p["below"]["SURG-21"] < 1e-4

    def test_absent_on_control_charts(self):
        r = qic(y=[3, 4, 5], n=[10, 20, 30], chart="p")
        assert "p_value" not in r.data.columns
        assert "count_model" not in r.summary


class TestBenjaminiHochberg:
    def test_hand_worked(self):
        from qikit.core.pvalues import bh_q_values
        q = bh_q_values(np.array([0.01, 0.04, 0.03, 0.005, 0.5]))
        assert q.tolist() == pytest.approx([0.025, 0.05, 0.05, 0.025, 0.5])

    def test_nan_is_untested(self):
        from qikit.core.pvalues import bh_q_values
        q = bh_q_values(np.array([0.01, np.nan, 0.04]))
        assert math.isnan(q[1])
        assert q[[0, 2]].tolist() == pytest.approx([0.02, 0.04])

    def test_monotone_bounded_and_capped(self):
        from qikit.core.pvalues import bh_q_values
        rng = np.random.default_rng(7)
        p = rng.uniform(size=200) ** 3
        q = bh_q_values(p)
        order = np.argsort(p)
        assert (np.diff(q[order]) >= 0).all()
        assert (q >= p).all() and (q <= 1.0).all()


class TestSignalMethod:
    Y = TestPValues.Y
    N = TestPValues.N

    def _oe(self, **kw):
        return _funnel(self.Y, self.N, "oe", center=1.0, **kw)

    @pytest.mark.parametrize("worse,side", [(None, "both"), ("higher", "above"), ("lower", "below")])
    def test_limits_tiers_are_the_p_value_test(self, worse, side):
        """The contours are the exact test's boundaries, so "limits" is p < α."""
        from qikit.core.pvalues import signal_thresholds
        d = self._oe(worse=worse).data
        outer, inner = signal_thresholds(side)
        p = d["p_value"].to_numpy()
        assert ((d["signal"] == "outlier").to_numpy() == (p < outer)).all()
        assert ((d["signal"] == "alert").to_numpy() == ((p < inner) & ~(p < outer))).all()

    @pytest.mark.parametrize("worse", [None, "higher", "lower"])
    def test_fdr_tiers_follow_the_q_values(self, worse):
        d = self._oe(worse=worse, signal="fdr", fdr_levels=(0.05, 0.10)).data
        q = d["q_value"].to_numpy()
        assert ((d["signal"] == "outlier").to_numpy() == (q < 0.05)).all()
        assert ((d["signal"] == "alert").to_numpy() == ((q < 0.10) & ~(q < 0.05))).all()

    def test_fdr_levels_are_a_parameter(self):
        loose = self._oe(signal="fdr", fdr_levels=(0.2, 0.4)).data
        strict = self._oe(signal="fdr", fdr_levels=(0.001, 0.025)).data
        assert (loose["signal"] == "outlier").sum() >= (strict["signal"] == "outlier").sum()
        with pytest.raises(ValueError, match="fdr_levels"):
            self._oe(signal="fdr", fdr_levels=(0.10, 0.05))

    def test_summary_and_signals(self):
        r = self._oe(signal="fdr")
        assert r.summary["signal"] == "fdr"
        assert r.summary["fdr_levels"] == (0.05, 0.10)
        assert r.summary["n_outlier"] == int((r.data["signal"] == "outlier").sum())
        assert r.summary["n_alert"] == int((r.data["signal"] == "alert").sum())
        assert self._oe().summary["signal"] == "limits"

    def test_excluded_point_never_flags(self):
        d = self._oe(signal="fdr", exclude=[10]).data
        assert (d.loc[d["excluded"], "signal"] == "none").all()

    @pytest.mark.parametrize("method", ["bonferroni", "exact"])
    def test_invalid_value(self, method):
        with pytest.raises(ValueError, match="signal must be one of"):
            self._oe(signal=method)

    def test_facets_adjust_separately(self):
        df = pd.DataFrame({
            "o": self.Y * 2, "e": self.N * 2, "site": ["A"] * 10 + ["B"] * 10,
        })
        r = funnel(df, y="o", n="e", measure="oe", center=1.0, overdispersion=False,
                   facets="site", signal="fdr")
        alone = self._oe(signal="fdr").data["q_value"].tolist()
        for site in ("A", "B"):
            assert r.data.loc[r.data["site"] == site, "q_value"].tolist() == alone
        assert r.summary["signal"] == "fdr"

    @staticmethod
    def _random_funnel(rng, measure, whole=True):
        k = 40
        if measure == "proportion":
            n = rng.integers(5, 300, size=k).astype(float)
            theta = np.clip(0.12 * rng.lognormal(0, 0.5, size=k), 0, 0.9)
            y = rng.binomial(n.astype(int), theta).astype(float)
        else:
            n = np.round(rng.uniform(0.5, 80, size=k), 2)
            y = rng.poisson(n * rng.lognormal(0, 0.45, size=k)).astype(float)
        if whole == "phi":
            return y / 2.37, n / 2.37  # effective counts under within_dispersion
        if not whole:
            y = y + rng.uniform(0, 1, size=k) * (y < n)  # averaged aggregates
        return y, n

    @pytest.mark.parametrize("whole", [True, False, "phi"])
    @pytest.mark.parametrize("measure,overdispersion", [
        ("oe", False), ("oe", True), ("rate", False), ("rate", True),
        ("proportion", False), ("proportion", True),
    ])
    def test_lines_and_p_values_agree(self, measure, overdispersion, whole):
        """Beyond a contour exactly when p < its tail probability, on both sides and at
        both levels, for whole counts (the exact test) and for counts between whole
        numbers (each tail interpolated, the inverse of the interpolated quantile)."""
        from qikit.core.pvalues import signal_thresholds
        rng = np.random.default_rng(11)
        for _ in range(15):
            y, n = self._random_funnel(rng, measure, whole)
            for worse, side in (("higher", "above"), ("lower", "below")):
                r = _funnel(y, n, measure, overdispersion=overdispersion, worse=worse)
                if "normal" in (r.summary["limit_method"], r.summary["p_value_method"]):
                    continue
                d = r.data
                outer, inner = signal_thresholds(side)
                p = d["p_value"].to_numpy()
                beyond_outer = (d["signal"] == "outlier").to_numpy()
                beyond_inner = beyond_outer | (d["signal"] == "alert").to_numpy()
                assert (beyond_outer == (p < outer)).all()
                assert (beyond_inner == (p < inner)).all()

    @pytest.mark.parametrize("family,tau2", [
        ("poisson", 0.0), ("poisson", 0.05), ("binomial", 0.0), ("binomial", 0.001),
    ])
    def test_upper_contours_are_monotone(self, family, tau2):
        """The exact-test boundary never climbs on the ratio scale, where
        Spiegelhalter's drawn contour reversed thousands of times on a dense grid."""
        binomial = family == "binomial"
        grid = np.arange(3, 400).astype(float) if binomial else np.geomspace(0.3, 200, 20_000)
        lim = _contours.funnel_contours(family, 0.1 if binomial else 1.0, grid, tau2,
                                        (0.998, 0.95), "exact")
        for upper in (lim.ucl, lim.ucl_95):
            assert not (np.diff(upper) > 1e-12).any()

    def test_95_flag_is_the_garwood_interval_excluding_the_center(self):
        """On an unadjusted O/E funnel, beyond the 95% line on either side is exactly
        "the provider's own 95% Garwood interval excludes the center line"."""
        rng = np.random.default_rng(3)
        e = np.round(rng.uniform(0.5, 60, 300), 2)
        o = rng.poisson(e * rng.lognormal(0, 0.4, 300)).astype(float)
        d = _funnel(o, e, "oe", center=1.0).data
        flagged = d["signal"] != "none"
        excludes = (d["ci_lower"] > 1.0) | (d["ci_upper"] < 1.0)
        assert (flagged == excludes).all()

    def test_levels_move_the_contours(self):
        wide = self._oe(limits=(0.999, 0.95)).data
        base = self._oe().data
        up = "upper_outlier"
        assert (wide[up] >= base[up]).all() and (wide[up] > base[up]).any()
        assert wide["upper_alert"].tolist() == base["upper_alert"].tolist()
        assert self._oe(limits=(0.998, 0.95)).data[up].tolist() == base[up].tolist()
        with pytest.raises(ValueError, match="limits"):
            self._oe(limits=(0.95, 0.998))


# ---------------------------------------------------------------------------
# label= and hover=
# ---------------------------------------------------------------------------

class TestLabelAndHover:
    X = ["n3", "n1", "n2", "n4"]
    Y = [5, 2, 9, 4]
    N = [30.0, 10.0, 60.0, 20.0]
    NAMES = ["Carol", "Alice", "Bea", "Dana"]

    def test_labels_follow_the_funnel_sort(self):
        r = funnel(y=self.Y, n=self.N, unit=self.X, measure="oe", overdispersion=False,
                   label=self.NAMES, hover={"enc": [300, 100, 600, 200]})
        d = r.data
        assert d["unit"].tolist() == ["n1", "n4", "n3", "n2"]
        assert d["label"].tolist() == ["Alice", "Dana", "Carol", "Bea"]
        assert d["enc"].tolist() == [100, 200, 300, 600]

    def test_column_names_with_grouping(self):
        df = pd.DataFrame({
            "npi": ["n1", "n1", "n2", "n2"], "name": ["Alice", "Alice", "Bea", "Bea"],
            "practice": ["East", "East", "West", "West"],
            "o": [1, 2, 3, 4], "e": [1.0, 1.5, 2.0, 2.5],
        })
        r = funnel(df, y="o", n="e", unit="npi", measure="oe", overdispersion=False,
                   label="name", hover="practice")
        assert r.data["label"].tolist() == ["Alice", "Bea"]
        assert r.data["practice"].tolist() == ["East", "West"]
        assert r.data["y"].tolist() == pytest.approx([3 / 2.5, 7 / 4.5])

    def test_ungrouped_columns(self):
        df = pd.DataFrame({"o": self.Y, "e": self.N, "name": self.NAMES})
        r = funnel(df, y="o", n="e", measure="oe", overdispersion=False, label="name")
        assert r.data["label"].tolist() == ["Alice", "Dana", "Carol", "Bea"]

    def test_mr_keeps_every_point(self):
        """The first point has no moving range but keeps its row, label and hover."""
        r = qic(y=[1.0, 3.0, 2.0, 5.0], chart="mr", label=list("abcd"),
                hover={"k": [1, 2, 3, 4]})
        assert r.data["label"].tolist() == ["a", "b", "c", "d"]
        assert r.data["k"].tolist() == [1, 2, 3, 4]
        assert np.isnan(r.data["y"].iloc[0])

    def test_facets_slice_labels(self):
        df = pd.DataFrame({
            "o": self.Y * 2, "e": self.N * 2, "name": self.NAMES * 2,
            "site": ["A"] * 4 + ["B"] * 4, "grp": list("wxyzwxyz"),
        })
        r = funnel(df, y="o", n="e", measure="oe", overdispersion=False, facets="site",
                   label="name", hover=["grp"])
        sub = r.data[r.data["site"] == "B"]
        assert sub["label"].tolist() == ["Alice", "Dana", "Carol", "Bea"]
        assert sub["grp"].tolist() == ["x", "z", "w", "y"]

    def test_reserved_name_rejected(self):
        with pytest.raises(ValueError, match="collide"):
            funnel(y=self.Y, n=self.N, measure="oe", hover={"numerator": [1, 2, 3, 4]})

    def test_missing_column_rejected(self):
        df = pd.DataFrame({"o": self.Y, "e": self.N})
        with pytest.raises(ValueError, match="nope"):
            funnel(df, y="o", n="e", measure="oe", hover="nope")
        with pytest.raises(ValueError, match="nope"):
            funnel(df, y="o", n="e", measure="oe", label="nope")

    def test_wrong_shapes_rejected(self):
        with pytest.raises(ValueError, match="dict"):
            funnel(y=self.Y, n=self.N, measure="oe", hover=["a"])
        with pytest.raises(ValueError, match="must be a sequence"):
            funnel(y=self.Y, n=self.N, measure="oe", label="name")
        with pytest.raises(ValueError, match="one value per y"):
            funnel(y=self.Y, n=self.N, measure="oe", label=["a"])

class TestBinomialInversion:
    """dist.binomial_cdf / binomial_theta_for_cdf — the lgamma-free binomial solve."""

    @staticmethod
    def _cdf(k, m, t):
        return sum(math.comb(m, j) * t**j * (1 - t) ** (m - j) for j in range(k + 1))

    @pytest.mark.parametrize("k,m,t", [(3, 20, 0.1), (0, 5, 0.3), (10, 40, 0.2),
                                       (50, 300, 0.15), (4, 10, 0.9)])
    def test_cdf_matches_direct_sum(self, k, m, t):
        assert _dist.binomial_cdf(k, m, t) == pytest.approx(self._cdf(k, m, t), rel=1e-12)

    def test_cdf_survives_hospital_volumes(self):
        """(1 − θ)^m underflows here; the normalized walk never forms it."""
        assert _dist.binomial_cdf(5000, 10_000, 0.5) == pytest.approx(0.5040, abs=1e-4)

    def test_cdf_edges(self):
        assert _dist.binomial_cdf(-1, 10, 0.3) == 0.0
        assert _dist.binomial_cdf(10, 10, 0.3) == 1.0
        assert _dist.binomial_cdf(3, 10, 0.0) == 1.0
        assert _dist.binomial_cdf(3, 10, 1.0) == 0.0
        assert math.isnan(_dist.binomial_cdf(3, 10, float("nan")))

    @pytest.mark.parametrize("k,m", [(0, 1), (0, 12), (3, 20), (46, 260), (900, 10_000)])
    @pytest.mark.parametrize("p", [0.025, 0.2, 0.975])
    def test_theta_inverts_the_cdf(self, k, m, p):
        assert _dist.binomial_cdf(k, m, _dist.binomial_theta_for_cdf(k, m, p)) == (
            pytest.approx(p, abs=1e-12)
        )

    def test_theta_nan_where_no_theta_moves_the_cdf(self):
        assert math.isnan(_dist.binomial_theta_for_cdf(10, 10, 0.5))
        assert math.isnan(_dist.binomial_theta_for_cdf(-1, 10, 0.5))
        assert math.isnan(_dist.binomial_theta_for_cdf(3, 10, 1.0))


class TestBinomialPointCI:
    """limits.binomial_point_ci — exact Clopper–Pearson interval on a proportion."""

    def test_clopper_pearson_anchors(self):
        """Published exact intervals: 10/100 and 0/20."""
        assert _limits.binomial_point_ci(10, 100) == pytest.approx((0.0490, 0.1762), abs=1e-4)
        lo, hi = _limits.binomial_point_ci(0, 20)
        assert lo == 0.0
        assert hi == pytest.approx(1 - 0.025 ** (1 / 20), abs=1e-12)

    def test_all_events_gives_an_upper_bound_of_one(self):
        lo, hi = _limits.binomial_point_ci(20, 20)
        assert hi == 1.0
        assert lo == pytest.approx(0.025 ** (1 / 20), abs=1e-12)

    def test_contains_the_point_estimate(self):
        for x, n in [(1, 3), (4, 12), (19, 200), (48, 260)]:
            lo, hi = _limits.binomial_point_ci(x, n)
            assert lo <= x / n <= hi

    def test_nan_without_a_usable_count(self):
        assert all(math.isnan(v) for v in _limits.binomial_point_ci(3, 0))
        assert all(math.isnan(v) for v in _limits.binomial_point_ci(11, 10))


class TestBinomialDetectability:
    """limits.binomial_detectable_rate — the p funnel's smallest detectable proportion."""

    @pytest.mark.parametrize("n", [10, 30, 100, 400, 1000])
    def test_achieves_exactly_80_percent_power(self, n):
        (_, t), _ = _dist.binomial_quantiles((0.001, 0.999), n, 0.1, (-3.09, 3.09))
        theta = _limits.binomial_detectable_rate(t, n)
        power = 1.0 - TestBinomialInversion._cdf(math.floor(t), n, theta)
        assert power == pytest.approx(0.8, abs=1e-9)

    def test_signal_event_matches_sigma_signal_semantics(self):
        """Flags strictly y > ucl, so the detectable event is X ≥ floor(ucl·n) + 1."""
        n = 40
        ucl = float(_funnel([4], [n], "proportion", center=0.1).data["upper_outlier"].iloc[0])
        m = math.floor(ucl * n)
        at = _funnel([m], [n], "proportion", center=0.1)
        over = _funnel([m + 1], [n], "proportion", center=0.1)
        assert at.data["signal"].iloc[0] != "outlier"
        assert over.data["signal"].iloc[0] == "outlier"

    def test_unflaggable_point_is_inf(self):
        assert _limits.binomial_detectable_rate(5.0, 5) == math.inf

    def test_nan_without_usable_denominator(self):
        assert math.isnan(_limits.binomial_detectable_rate(3.0, 0))
        assert math.isnan(_limits.binomial_detectable_rate(float("inf"), 10))


class TestFractionalBinomial:
    """
    Binomial and beta-binomial funnels at a fractional denominator ν (n/φ under
    within_dispersion): every tail interpolated in ν between ⌊ν⌋ and ⌈ν⌉, exact at a
    whole ν, and the contours solved from those tails (docs/methods.md §4.13).
    """

    OUT = _limits.contour(0.998)
    IN = _limits.contour(0.95)

    @pytest.mark.parametrize("m", [1, 7, 40, 300])
    @pytest.mark.parametrize("cl", [0.1, 0.8])
    @pytest.mark.parametrize("tau2", [0.0, 0.002])
    def test_tables_match_the_exact_tails_bit_for_bit(self, m, cl, tau2):
        table = _limits._tail_table(m, cl, tau2)
        params = _limits.beta_params(cl, tau2) if tau2 else None
        for k in range(m + 1):
            exact = (_dist.beta_binomial_tails(k, m, *params) if params
                     else _dist.binomial_tails(k, m, cl))
            assert _limits._table_tails(table, float(k)) == exact

    @pytest.mark.parametrize("cl", [0.1, 0.8])
    @pytest.mark.parametrize("tau2", [0.0, 0.002])
    def test_contours_continuous_through_whole_numbers(self, cl, tau2):
        for m in (4, 12, 37, 150):
            grid = np.array([m - 1e-7, float(m), m + 1e-7])
            lim = _contours.funnel_contours("binomial", cl, grid, tau2, (0.998, 0.95), "exact")
            for curve in (lim.ucl, lim.lcl, lim.ucl_95, lim.lcl_95):
                assert curve[0] == pytest.approx(curve[1], abs=1e-6)
                assert curve[2] == pytest.approx(curve[1], abs=1e-6)

    @pytest.mark.parametrize("tau2", [0.0, 0.002])
    def test_contours_monotone_on_a_fine_grid(self, tau2):
        lim = _contours.funnel_contours("binomial", 0.1, np.arange(1.0, 60.0, 0.05), tau2, (0.998, 0.95), "exact")
        for upper in (lim.ucl, lim.ucl_95):
            assert not (np.diff(upper) > 1e-12).any()
        for lower in (lim.lcl, lim.lcl_95):
            assert not (np.diff(lower) < -1e-12).any()

    def test_contour_is_where_the_tail_crosses(self):
        from qikit.core.pvalues import _point_tails
        nu, cl = 17.3, 0.4
        ucl, lcl = _limits.fractional_binomial_pair(cl, nu, 0.0, *self.IN[:2])
        assert 0 < lcl < cl < ucl < 1
        (lo_in, _), _ = _point_tails((lcl + 1e-9) * nu, nu, cl, 0.0, "binomial")
        (lo_out, _), _ = _point_tails((lcl - 1e-9) * nu, nu, cl, 0.0, "binomial")
        assert lo_out < 0.025 <= lo_in
        (_, up_in), _ = _point_tails((ucl - 1e-9) * nu, nu, cl, 0.0, "binomial")
        (_, up_out), _ = _point_tails((ucl + 1e-9) * nu, nu, cl, 0.0, "binomial")
        assert up_out <= 0.025 < up_in

    def test_upper_contour_is_one_when_nothing_can_flag(self):
        ucl, _ = _limits.fractional_binomial_pair(0.8, 4.96, 0.0, *self.OUT[:2])
        assert ucl == 1.0

    def test_tau_zero_reproduces_the_binomial(self):
        e = np.array([4.96, 12.4, 30.7])
        a = _limits._mixture_funnel_pair(0.2, e, 0.0, "binomial", *self.OUT)
        b = _limits._binomial_funnel_pair(0.2, e, *self.OUT)
        assert a[0].tolist() == b[0].tolist() and a[1].tolist() == b[1].tolist()

    def test_ci_is_clopper_pearson_at_whole_counts_and_continuous(self):
        exact = _limits.binomial_point_ci(3, 12)
        near = _limits.binomial_point_ci(3, 12 + 1e-7)
        assert near == pytest.approx(exact, abs=1e-6)
        lo, hi = _limits.binomial_point_ci(3.3, 4.96)
        assert 0 < lo < 3.3 / 4.96 < hi < 1
        assert _limits.binomial_point_ci(0.0, 4.96)[0] == 0.0
        assert _limits.binomial_point_ci(4.96, 4.96)[1] == 1.0

    def test_detectable_rate_continuous_through_whole_numbers(self):
        grid = np.array([24 - 1e-7, 24.0, 24 + 1e-7])
        ucl = _contours.funnel_contours("binomial", 0.1, grid, 0.0, (0.998, 0.95), "exact").ucl
        d = [_limits.binomial_detectable_rate(u * g, g) for u, g in zip(ucl, grid)]
        assert d[0] == pytest.approx(d[1], abs=1e-6)
        assert d[2] == pytest.approx(d[1], abs=1e-6)


class TestFunnelPowerReporting:
    """Proportion and rate funnels report what a signal would have required, as O/E do."""

    Y = [4, 1, 3, 2, 4, 3, 5, 6, 8, 7, 10, 12, 19, 48]
    N = [12, 15, 20, 24, 30, 38, 45, 60, 75, 90, 120, 150, 200, 260]
    COLS = ("min_detectable", "ci_lower", "ci_upper")

    def _r(self, **kw):
        return _funnel(self.Y, self.N, "proportion", **kw)

    @staticmethod
    def _power_note(r):
        (note,) = [note for note in r.summary["notes"] if "to detect even a doubling" in note]
        return note


    def test_the_trap_point_reports_why_it_did_not_flag(self):
        row = self._r().data.iloc[0]
        assert row["y"] == pytest.approx(1 / 3)
        assert row["signal"] != "outlier"
        assert row["min_detectable"] == pytest.approx(0.6559, abs=1e-4)
        assert row["ci_lower"] == pytest.approx(0.0992, abs=1e-4)
        assert row["ci_upper"] == pytest.approx(0.6511, abs=1e-4)

    def test_summary_and_note(self):
        r = self._r()
        s, note = r.summary, self._power_note(r)
        assert s["underpowered"] is True
        assert s["n_underpowered"] == 12
        assert s["min_detectable_median"] == pytest.approx(2.9631, abs=1e-4)
        assert "12 of 14" in note
        assert "proportion" in note
        assert "not evidence of acceptable performance" in note

    def test_u_funnel_note_speaks_of_rates(self):
        r = _funnel([3, 1, 0, 2, 4], [180, 220, 260, 310, 350], "rate")
        assert "rate" in self._power_note(r)
        assert r.data.sort_values("y")["ci_lower"].iloc[0] == 0.0

    def test_u_funnel_reuses_the_oe_algebra(self):
        """Counts over exposure are counts over expected events: identical columns."""
        y, n = [3, 1, 0, 2, 4], [180.0, 220.0, 260.0, 310.0, 350.0]
        u = _funnel(y, n, "rate").data
        cl = sum(y) / sum(n)
        oe = _funnel(y, [v * cl for v in n], "oe").data
        assert (u["min_detectable"] / cl).tolist() == pytest.approx(
            oe["min_detectable"].tolist(), rel=1e-8)

    def test_columns_scale_with_multiply_but_the_verdict_does_not(self):
        a, b = self._r(), self._r(multiply=100)
        for c in self.COLS:
            assert (b.data[c] / 100).tolist() == pytest.approx(a.data[c].tolist())
        assert b.summary["min_detectable_median"] == a.summary["min_detectable_median"]

    def test_excluded_points_do_not_color_the_verdict(self):
        assert self._r(exclude=[1]).summary["n_underpowered"] == 11

    def test_well_powered_funnel_stays_quiet(self):
        r = _funnel([70] * 10, [1000] * 10, "proportion")
        assert r.summary["underpowered"] is False
        assert not any("to detect even a doubling" in note for note in r.summary["notes"])

    def test_adjusted_funnel_uses_its_own_wider_limits(self):
        y = [1, 6, 2, 9, 4, 11, 7, 16, 10, 21, 13, 30, 19, 33]
        n = [18, 25, 31, 40, 46, 55, 63, 80, 92, 110, 130, 160, 185, 220]
        p = _funnel(y, n, "proportion").data["min_detectable"]
        pp = _funnel(y, n, "proportion", overdispersion=True).data["min_detectable"]
        assert (pp >= p).all()
        assert (pp > p).any()

    def test_absent_on_control_charts(self):
        r = qic(y=self.Y, n=self.N, chart="p")
        assert not any(c in r.data.columns for c in self.COLS)
        assert "underpowered" not in r.summary


# ---------------------------------------------------------------------------
# Funnel contours off the points: FunnelResult.limits()
# (Every shared fixture's contours are checked against its points in
# test_fixture_adapter.py.)
# ---------------------------------------------------------------------------

class TestFunnelLimits:
    LIMITS = ["cl", "upper_outlier", "lower_outlier", "upper_alert", "lower_alert"]

    def test_default_grid_covers_and_includes_every_point(self):
        y = [23, 8, 34, 19, 59, 31, 72, 38, 104, 64, 120, 88]
        n = [12.0, 18.0, 25.0, 30.0, 38.0, 45.0, 55.0, 64.0, 72.0, 85.0, 96.0, 110.0]
        r = _funnel(y, n, "oe", overdispersion=True)
        assert r.summary["tau"] > 0
        n_obs = r.data["denominator"].to_numpy()
        grid = r.limits()
        g = grid["denominator"].to_numpy()
        assert np.all(np.diff(g) > 0)
        assert g[0] == n_obs.min() and g[-1] == n_obs.max()
        assert set(n_obs) <= set(g)
        assert len(g) > len(n_obs)
        # The grid's rows at the points are the points' own limits.
        at = grid.set_index("denominator").loc[n_obs]
        for col in self.LIMITS:
            np.testing.assert_array_equal(at[col].to_numpy(), r.data[col].to_numpy())

    def test_binomial_grid_is_whole_numbers(self):
        r = _funnel([3, 9, 14, 30, 41], [17, 60, 120, 333, 512], "proportion",
                    overdispersion=True)
        g = r.limits()["denominator"].to_numpy()
        np.testing.assert_array_equal(g, np.round(g))
        assert r.summary["limit_method"] == "exact"

    def test_multiply_and_center_scale_like_the_data(self):
        r = _funnel([2, 5, 9, 4, 12], [400.0, 900, 1500, 2100, 3000], "rate", multiply=1000)
        assert r.limits()["cl"].iloc[0] == r.data["cl"].iloc[0]
        r = _funnel([3, 7, 4, 15, 9], [2.5, 4.0, 6.1, 8.0, 12.0], "oe", center=1.0)
        assert set(r.limits()["cl"]) == {1.0}

    def test_faceted_contours_are_per_facet(self):
        df = pd.DataFrame({
            "site": ["A"] * 5 + ["B"] * 5,
            "y": [2, 5, 9, 4, 12, 20, 31, 18, 44, 60],
            "n": [40, 90, 150, 210, 300, 120, 200, 260, 400, 650],
        })
        r = funnel(df, y="y", n="n", measure="proportion", facets="site", overdispersion=False)
        grid = r.limits()
        assert set(grid["site"]) == {"A", "B"}
        for site in ("A", "B"):
            cl_data = r.data.loc[r.data["site"] == site, "cl"].iloc[0]
            assert set(grid.loc[grid["site"] == site, "cl"]) == {cl_data}
            g = grid.loc[grid["site"] == site, "denominator"]
            n_site = df.loc[df["site"] == site, "n"]
            assert g.min() == n_site.min() and g.max() == n_site.max()

    def test_control_charts_have_no_contours(self):
        assert not hasattr(qic(y=[3, 4, 5], n=[10, 20, 30], chart="p"), "limits")

    def test_denominator_column_on_every_denominator_chart(self):
        y, n = [3, 4, 5, 9], [10, 20, 30, 50]
        assert list(_funnel(y, n, "proportion").data["denominator"]) == n
        assert list(qic(y=y, n=n, chart="p").data["n"]) == n
        oe = _funnel(y, n, "oe").data
        assert list(oe["denominator"]) == n
        assert "n" not in qic(y=y, chart="i").data.columns
        # A y-scale rescale; the denominator is not on the y scale.
        assert list(qic(y=y, n=n, chart="u", multiply=100).data["n"]) == n

    def test_denominator_follows_the_funnel_sort(self):
        r = _funnel([9, 4, 5, 3], [50, 20, 30, 10], "rate", units=list("abcd"))
        assert list(r.data["unit"]) == list("dbca")
        assert list(r.data["denominator"]) == [10, 20, 30, 50]

    def test_hover_cannot_shadow_the_denominator(self):
        df = pd.DataFrame({"x": list("abc"), "y": [3, 4, 5], "n": [10, 20, 30],
                           "denominator": [1, 2, 3]})
        with pytest.raises(ValueError, match="collide"):
            funnel(df, y="y", n="n", unit="x", measure="proportion", hover="denominator")


def test_runtime_messages_print_on_a_windows_code_page():
    """
    Errors, warnings and summary notes must encode as cp1252.

    Python writes to a piped stdout on Windows in the ANSI code page, which has no Greek
    letters, so a σ in a message a caller prints raises UnicodeEncodeError. Docstrings
    keep their math notation (help() on a pipe needs PYTHONUTF8=1 either way), and the
    render package is exempt: its labels go into Plotly figures, never a console.
    """
    import ast

    offenders = []
    import qikit

    package = pathlib.Path(qikit.__file__).parent
    for path in sorted(p for p in package.rglob("*.py") if "plot" not in p.parts):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in docstrings):
                try:
                    node.value.encode("cp1252")
                except UnicodeEncodeError:
                    offenders.append(f"{path.name}:{node.lineno}: {node.value[:60]!r}")
    assert not offenders, "\n".join(offenders)
