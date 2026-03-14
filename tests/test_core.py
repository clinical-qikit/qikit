"""
Tests for qikit — chart calculations, limit formulas, signal detection.

Numerical tolerances match published SPC constants to 3 decimal places.
"""

import math

import numpy as np
import pandas as pd
import pytest

from qikit import SPCResult, qic
from qikit import core as _core


def _result(chart, y, **kw):
    return qic(y=y, chart=chart, **kw)


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
        assert r.chart_type == "run"

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

    def test_nan_handling(self):
        y = [1.0, 2.0, np.nan, 4.0, 5.0]
        r = _result("i", y)
        assert len(r.data) == 5
        assert not np.isnan(r.data["cl"].iloc[0])

    def test_all_same_values(self):
        """All-same values → CL at that value, zero-width limits, no crash."""
        y = [5.0] * 20
        r = _result("i", y)
        assert math.isclose(r.data["cl"].iloc[0], 5.0)
        assert math.isclose(r.data["ucl"].iloc[0], 5.0, abs_tol=1e-10)

    def test_signals_field(self, normal_30):
        r = _result("i", normal_30)
        assert isinstance(r.signals, bool)

    def test_freeze(self, normal_30):
        r = _result("i", normal_30, freeze=20)
        assert r.summary["freeze"] == 20
        cl_before = r.data["cl"].iloc[0]
        cl_after = r.data["cl"].iloc[25]
        assert math.isclose(cl_before, cl_after, abs_tol=1e-10)

    def test_exclude(self):
        y = [10.0] * 10 + [100.0] + [10.0] * 9
        r_excl = _result("i", y, exclude=[11])
        r_all = _result("i", y)
        assert r_excl.data["ucl"].iloc[0] < r_all.data["ucl"].iloc[0]


# ---------------------------------------------------------------------------
# MR chart
# ---------------------------------------------------------------------------

class TestMRChart:
    def test_plots_moving_ranges(self, normal_30):
        """MR chart y-axis should be moving ranges, not raw data."""
        r = _result("mr", normal_30)
        expected_mrs = np.abs(np.diff(normal_30))
        assert len(r.data) == len(normal_30) - 1
        np.testing.assert_allclose(r.data["y"].to_numpy(), expected_mrs)

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

    def test_no_lcl(self, normal_30):
        """MR chart has no LCL (D3 = 0 for n = 2)."""
        r = _result("mr", normal_30)
        assert r.data["lcl"].isna().all()

    def test_requires_two_points(self):
        with pytest.raises(ValueError, match="at least 2"):
            _result("mr", [5.0])

    def test_x_values_offset(self):
        """MR x-values should correspond to the second point in each pair."""
        r = qic(x=[10, 20, 30, 40, 50], y=[1.0, 3.0, 2.0, 5.0, 4.0], chart="mr")
        assert list(r.data["x"]) == [20, 30, 40, 50]


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
        with pytest.raises(ValueError, match="requires denominators"):
            qic(y=[0.1, 0.2, 0.15], chart="p")

    def test_zero_denominator_raises(self):
        with pytest.raises(ValueError, match="[Zz]ero denom"):
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
        with pytest.raises(ValueError, match="requires denominators"):
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
        assert r.data["sigma_signal"].iloc[-1]

    def test_no_spurious_signals(self, normal_30):
        """Random data should rarely trigger sigma signals."""
        r = _result("i", normal_30)
        assert r.data["sigma_signal"].sum() <= 1

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
        runs_sig = r.data["runs_signal"]
        # The mixed points at the end should NOT be marked
        # (unless the crossings signal fires, which marks everything)
        if r.summary.get("crossings_signal"):
            # Crossings signal marks all useful points
            pass
        else:
            # Only the long-run points should be marked
            assert runs_sig.sum() < len(y)

    def test_signals_field_is_bool(self, normal_30):
        r = _result("i", normal_30)
        assert isinstance(r.signals, bool)


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
        with pytest.raises(ValueError, match="Unknown chart"):
            qic(y=[1, 2, 3], chart="zzz")

    def test_no_y_raises(self):
        with pytest.raises((ValueError, TypeError)):
            qic(chart="i")

    def test_empty_y_raises(self):
        with pytest.raises(ValueError):
            qic(y=[], chart="i")

    def test_data_kwarg(self):
        df = pd.DataFrame({"val": [1.0, 2.0, 3.0, 4.0, 5.0]})
        r = qic(data=df, y="val", chart="i")
        assert len(r.data) == 5

    def test_data_with_x(self):
        df = pd.DataFrame({"week": [1, 2, 3, 4, 5], "val": [1.0, 2.0, 3.0, 4.0, 5.0]})
        r = qic(data=df, x="week", y="val", chart="i")
        assert list(r.data["x"]) == [1, 2, 3, 4, 5]

    def test_consistent_schema(self, normal_30):
        """All chart types produce the same DataFrame columns."""
        expected_cols = {"x", "y", "cl", "ucl", "lcl", "ucl_95", "lcl_95", "sigma_signal", "runs_signal", "baseline"}
        for chart in ["run", "i", "c"]:
            r = _result(chart, normal_30)
            assert set(r.data.columns) == expected_cols


# ---------------------------------------------------------------------------
# Display params flow through
# ---------------------------------------------------------------------------

class TestDisplayParams:
    def test_plot_opts_stored(self, normal_30):
        r = _result("i", normal_30, decimals=3, show_grid=True, point_size=2.0)
        assert r._plot_opts["decimals"] == 3
        assert r._plot_opts["show_grid"] is True
        assert r._plot_opts["point_size"] == 2.0

    def test_plot_opts_used_by_plot(self, normal_30):
        r = _result("i", normal_30, show_grid=True)
        fig = r.plot()
        assert fig.layout.xaxis.showgrid is True

    def test_plot_opts_overridden(self, normal_30):
        r = _result("i", normal_30, show_grid=True)
        fig = r.plot(show_grid=False)
        assert fig.layout.xaxis.showgrid is False


# ---------------------------------------------------------------------------
# Summary / audit fields
# ---------------------------------------------------------------------------

class TestSummary:
    def test_summary_keys(self, normal_30):
        r = _result("i", normal_30)
        assert "n_obs" in r.summary
        assert "limit_basis" in r.summary
        assert "longest_run" in r.summary
        assert "n_crossings" in r.summary

    def test_to_dict(self, normal_30):
        r = _result("i", normal_30)
        d = r.to_dict()
        assert d["chart_type"] == "i"
        assert "data" in d
        assert len(d["data"]) == 30

    def test_to_json(self, normal_30):
        import json
        r = _result("i", normal_30)
        j = r.to_json()
        parsed = json.loads(j)
        assert parsed["chart_type"] == "i"

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
        assert math.isclose(_core.B4[25], 1.435, abs_tol=0.001)
