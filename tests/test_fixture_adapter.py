"""
The engine contract the shared fixtures speak, as tests/fixture_adapter.py maps it onto
qic() and funnel(). These pin the parts of that vocabulary that are not simply new
names for public columns, because the TypeScript engine reproduces them: runs_signal
there includes the too-few-crossings blanket, runs_signal_localized does not, and funnels
carry both as False. The public API is tested in test_spc.py, test_funnel.py and
test_public_api.py.
"""

from __future__ import annotations

import pathlib

import numpy as np
import pytest

from fixture_adapter import engine_qic, run_fixture
from qikit import funnel

ENGINE_SERIES_COLUMNS = {
    "x", "y", "cl", "ucl", "lcl", "ucl_95", "lcl_95", "sigma_signal", "runs_signal",
    "runs_signal_localized", "baseline", "excluded",
}


# weco/nelson need control limits, so they are not paired with run charts.
@pytest.mark.parametrize("chart,method", [
    (c, m) for c in ("run", "i", "c") for m in ("anhoej", "ihi")
] + [(c, m) for c in ("i", "c") for m in ("weco", "nelson")])
def test_localized_is_subset_of_runs_signal(chart, method, normal_30):
    """Invariant: localized never marks a point runs_signal doesn't."""
    for y in (normal_30, list(range(1, 31)), [20.0] * 15 + [1.0] * 15):
        r = engine_qic(y=list(y), chart=chart, method=method)
        loc = r.data["runs_signal_localized"].to_numpy()
        runs = r.data["runs_signal"].to_numpy()
        assert not (loc & ~runs).any()


def test_crossings_blanket_marks_every_useful_point():
    """Only the crossings test fires: runs_signal marks all 20, localized none."""
    y = [1.1, 1.2, 1.15, 1.25, 1.05, 0.8, 0.75, 0.9, 0.85, 0.7,
         1.2, 1.3, 1.1, 1.25, 1.15, 0.75, 0.85, 0.8, 0.9, 0.7]
    r = engine_qic(y=y, chart="i")
    assert r.data["runs_signal"].sum() == 20
    assert r.data["runs_signal_localized"].sum() == 0


def test_long_run_survives_the_blanket():
    """Both fire: the blanket marks all 24, localized keeps just the run."""
    y = [11, 12, 11, 12, 11, 12, 11, 12, 11] + [9, 8, 9, 8] + \
        [11, 12, 11] + [9, 8, 9, 8] + [11, 12, 11, 12]
    r = engine_qic(y=[float(v) for v in y], chart="i")
    assert r.data["runs_signal"].sum() == 24
    assert list(r.data.index[r.data["runs_signal_localized"]]) == list(range(9))


def test_without_the_blanket_the_two_agree():
    y = [12.0] * 10 + [9.0, 11.5] * 11
    r = engine_qic(y=y, chart="i")
    assert r.data["runs_signal"].sum() == 10
    assert (r.data["runs_signal"] == r.data["runs_signal_localized"]).all()


def test_multipart_blanket_applies_per_part():
    part = [4.2, 2.3, 1.2, 1.1, 5.1, 5.6, 4.0, 3.1,
            20.4, 17.2, 23.9, 21.9, 8.0, 22.6, 8.6, 19.0]
    r = engine_qic(y=part * 2, chart="t", part=17)
    assert r.data["runs_signal"].sum() == 32


def test_funnels_carry_runs_columns_as_false():
    y = [5, 8, 12, 20, 30, 41, 55, 70]
    n = [50, 80, 120, 200, 300, 400, 550, 700]
    r = engine_qic(y=y, n=n, chart="p", funnel=True)
    assert r.data["runs_signal"].sum() == 0
    assert r.data["runs_signal_localized"].sum() == 0


def test_series_columns(normal_30):
    """Every series chart carries the same engine columns."""
    for chart in ["run", "i", "c"]:
        assert set(engine_qic(y=normal_30, chart=chart).data.columns) == ENGINE_SERIES_COLUMNS


class TestFunnelExcludeByPosition:
    """The engine's exclude= is 1-based into the input order; summary["excluded"] gives
    the positions in the sorted (drawn) order; out-of-range positions are ignored."""

    Y, N = [4, 480, 45, 4700], [5, 500, 50, 5000]

    def _chart(self, **kw):
        return engine_qic(y=self.Y, n=self.N, chart="p", funnel=True, **kw)

    def test_position_two_is_the_second_input(self):
        r = self._chart(x=["A", "B", "C", "D"], exclude=[2])
        ghosted = r.data.loc[r.data["excluded"]].iloc[0]
        assert ghosted["x"] == "B"
        assert not ghosted["baseline"]

    def test_summary_excluded_reports_sorted_positions(self):
        assert self._chart(exclude=[2]).summary["excluded"] == [3]
        assert self._chart(exclude=2).summary["excluded"] == [3]

    def test_out_of_range_is_ignored(self):
        assert self._chart(exclude=[99]).data["excluded"].sum() == 0


class TestByarLimits:
    """Byar's approximation to the O/E Poisson limits exists for the shared fixtures
    (fixtures/spc carries one); funnel() itself always draws exact limits."""

    Y = [4, 1, 12, 6, 28, 9, 110, 92]
    N = [2.5, 3.8, 5.0, 8.2, 12.0, 25.0, 96.0, 105.0]

    def _chart(self, **kw):
        return engine_qic(y=self.Y, n=self.N, chart="oe", funnel=True, **kw)

    def test_byar_widens_the_small_volume_limits(self):
        exact, byar = self._chart(), self._chart(limit_method="byar")
        assert byar.data["ucl"].iloc[0] > exact.data["ucl"].iloc[0]
        assert byar.summary["limit_method"] == "byar"

    def test_rejects_an_unknown_limit_method(self):
        with pytest.raises(ValueError, match="limit_method must be one of"):
            self._chart(limit_method="bogus")


class TestOEIsAlwaysAFunnel:
    """In the engine vocabulary chart="oe" and "oep" are funnels with or without
    funnel=True (the TypeScript engine reads them the same way)."""

    Y = [20, 19, 45, 4, 31, 10, 21, 18, 22, 20]
    N = [20.0] * 10

    @pytest.mark.parametrize("chart", ["oe", "oep"])
    def test_warn_tier_without_the_flag(self, chart):
        r = engine_qic(y=self.Y, n=self.N, chart=chart)
        assert "warn_signal" in r.data.columns
        assert r.summary["n_warn"] == int(r.data["warn_signal"].sum())

    def test_signal_side_without_the_flag(self):
        d = engine_qic(y=self.Y, n=self.N, chart="oe", cl=1.0, signal_side="below").data
        assert [i for i, v in enumerate(d["sigma_signal"]) if v] == [3]


_FUNNEL_FIXTURES = sorted(
    (pathlib.Path(__file__).parent.parent / "fixtures" / "spc").glob("funnel_*.json")
)


@pytest.mark.parametrize("path", _FUNNEL_FIXTURES, ids=lambda p: p.stem)
def test_contours_pass_through_every_fixture_point_exactly(path):
    """
    Every funnel fixture — p, pp, u, up, oe exact and Byar, oep, with cl=, exclude=,
    multiply= and τ̂ > 0 among them — through the public FunnelResult.limits(). A curve
    that missed a point's own limit by even an ulp could draw a flagged point inside the
    funnel.
    """
    _, r = run_fixture(path)
    public = r.public
    at_points = public.limits(n=public.data["denominator"])
    for col in ("cl", "upper_outlier", "lower_outlier", "upper_alert", "lower_alert"):
        np.testing.assert_array_equal(at_points[col].to_numpy(), public.data[col].to_numpy())


class TestMappingMatchesFunnel:
    """The adapter's chart codes reach the same model funnel() does, so the fixtures
    (and the TypeScript engine conforming to them) test the numbers funnel() reports."""

    OBS = [8, 3, 9, 6, 15, 11, 20, 14, 33, 30, 52, 110]
    EXP = [3.2, 4.0, 5.5, 6.1, 8.0, 9.4, 12.0, 15.5, 20.0, 26.0, 40.0, 70.0]

    @pytest.mark.parametrize("measure,over,chart", [
        ("oe", True, "oep"), ("oe", False, "oe"), ("rate", True, "up"),
        ("rate", False, "u"), ("proportion", True, "pp"), ("proportion", False, "p"),
    ])
    def test_measure_and_overdispersion_pick_the_model(self, measure, over, chart):
        n = [v * 10 for v in self.EXP] if measure == "proportion" else self.EXP
        r = funnel(y=self.OBS, n=n, measure=measure, overdispersion=over)
        core = engine_qic(y=self.OBS, n=n, chart=chart, funnel=True)
        assert r.data["upper_outlier"].tolist() == core.data["ucl"].tolist()
        assert r.data["p_value"].tolist() == core.data["p_value"].tolist()

    @pytest.mark.parametrize("measure,chart", [("oe", "oep"), ("rate", "up"), ("proportion", "pp")])
    def test_spiegelhalter_is_the_published_engine(self, measure, chart):
        n = [v * 10 for v in self.EXP] if measure == "proportion" else self.EXP
        r = funnel(y=self.OBS, n=n, measure=measure, tau_method="spiegelhalter")
        core = engine_qic(y=self.OBS, n=n, chart=chart, funnel=True, tau_method="spiegelhalter")
        assert r.data["upper_outlier"].tolist() == core.data["ucl"].tolist()
        assert r.data["p_value"].tolist() == core.data["p_value"].tolist()

    @pytest.mark.parametrize("worse,side", [(None, "both"), ("higher", "above"), ("lower", "below")])
    def test_worse_is_the_signal_side(self, worse, side):
        r = funnel(y=self.OBS, n=self.EXP, measure="oe", worse=worse)
        core = engine_qic(y=self.OBS, n=self.EXP, chart="oep", funnel=True, signal_side=side)
        assert r.data["p_value"].tolist() == core.data["p_value"].tolist()
