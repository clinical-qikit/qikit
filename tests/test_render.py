"""
Tests for qikit.render — Plotly figure generation.
"""

from __future__ import annotations
import numpy as np
import pandas as pd
import pytest
import plotly.graph_objects as go
from qikit import qic



@pytest.fixture
def i_result():
    rng = np.random.default_rng(7)
    y = rng.normal(10, 2, 25)
    return qic(y=y, chart="i", title="Test I Chart", ylab="Value", xlab="Week")


class TestPlotBasics:
    def test_returns_figure(self, i_result):
        fig = i_result.plot()
        assert isinstance(fig, go.Figure)

    def test_has_traces(self, i_result):
        fig = i_result.plot()
        # data, CL, UCL, LCL = 4 traces
        assert len(fig.data) >= 4

    def test_first_trace_is_scatter(self, i_result):
        fig = i_result.plot()
        assert isinstance(fig.data[0], go.Scatter)

    def test_title_in_layout(self, i_result):
        fig = i_result.plot()
        assert "Test I Chart" in (fig.layout.title.text or "")

    def test_no_legend(self, i_result):
        fig = i_result.plot()
        assert fig.layout.showlegend is False

    def test_white_background(self, i_result):
        fig = i_result.plot()
        assert fig.layout.plot_bgcolor == "white"


class TestSignalColors:
    def test_signal_point_is_red(self):
        """A point beyond limits should be colored red (#d62728)."""
        y = [10.0] * 29 + [40.0]
        r = qic(y=y, chart="i")
        fig = r.plot()
        colors = fig.data[0].marker.color
        assert any(c == "#d62728" for c in colors)

    def test_normal_points_are_gray(self):
        """Normal points should be muted gray."""
        y = [10.0] * 20
        r = qic(y=y, chart="i")
        fig = r.plot()
        colors = fig.data[0].marker.color
        assert all(c == "#888888" for c in colors)


SIGMA_RED = "#d62728"
RUNS_ORANGE = "#ff7f0e"
NORMAL_GRAY = "#888888"


@pytest.fixture
def crossings_and_run():
    """
    24 points in blocks of 8/4/4/4/4 alternating around CL=10.5.

    Only 4 crossings (<= threshold) so the Anhoej crossings test fires and marks
    every point; the leading block of 8 is also a long run (>= threshold 7).
    Spread is tight enough that no point breaches UCL/LCL, so runs coloring is
    never masked by sigma red.
    """
    y = [11, 12, 11, 12, 11, 12, 11, 12] + [9, 8, 9, 8] + \
        [11, 12, 11, 12] + [9, 8, 9, 8] + [11, 12, 11, 12]
    return qic(y=[float(v) for v in y], chart="i")


class TestRunsHighlight:
    def test_fixture_preconditions(self, crossings_and_run):
        """Both Anhoej sub-signals fire and nothing is a sigma outlier."""
        s = crossings_and_run.summary
        assert s["crossings_signal"] is True
        assert s["run_signal"] is True
        assert crossings_and_run.data["sigma_signal"].sum() == 0

    def test_all_colors_every_point(self, crossings_and_run):
        """Default: the crossings blanket turns the whole chart orange."""
        fig = crossings_and_run.plot()
        colors = list(fig.data[0].marker.color)
        assert colors.count(RUNS_ORANGE) == 24

    def test_localized_colors_only_the_run(self, crossings_and_run):
        """localized: only the 8 points forming the long run."""
        fig = crossings_and_run.plot(runs_highlight="localized")
        colors = list(fig.data[0].marker.color)
        assert colors.count(RUNS_ORANGE) == 8
        assert colors[:8] == [RUNS_ORANGE] * 8
        assert all(c == NORMAL_GRAY for c in colors[8:])

    def test_none_colors_nothing(self, crossings_and_run):
        fig = crossings_and_run.plot(runs_highlight="none")
        colors = list(fig.data[0].marker.color)
        assert all(c == NORMAL_GRAY for c in colors)

    def test_default_matches_all(self, crossings_and_run):
        assert list(crossings_and_run.plot().data[0].marker.color) == \
            list(crossings_and_run.plot(runs_highlight="all").data[0].marker.color)

    @pytest.mark.parametrize("mode", ["all", "localized", "none"])
    def test_sigma_stays_red(self, mode):
        """Sigma outliers are unaffected by runs_highlight."""
        y = [10.0] * 29 + [40.0]
        fig = qic(y=y, chart="i").plot(runs_highlight=mode)
        assert list(fig.data[0].marker.color).count(SIGMA_RED) >= 1

    @pytest.mark.parametrize("mode", ["all", "localized", "none"])
    def test_symbols_track_colors(self, crossings_and_run, mode):
        """A diamond marks a runs-only point; gray points must stay circles."""
        fig = crossings_and_run.plot(runs_highlight=mode)
        colors = list(fig.data[0].marker.color)
        symbols = list(fig.data[0].marker.symbol)
        for c, s in zip(colors, symbols):
            assert (s == "diamond") == (c == RUNS_ORANGE)

    def test_invalid_value_raises(self, crossings_and_run):
        with pytest.raises(ValueError, match="runs_highlight must be one of"):
            crossings_and_run.plot(runs_highlight="bogus")

    def test_faceted_chart_honors_option(self):
        """Facets take a separate render path (_plot_faceted)."""
        y = [11, 12, 11, 12, 11, 12, 11, 12] + [9, 8, 9, 8] + \
            [11, 12, 11, 12] + [9, 8, 9, 8] + [11, 12, 11, 12]
        df = pd.DataFrame({"y": [float(v) for v in y] * 2, "grp": ["a"] * 24 + ["b"] * 24})
        r = qic(data=df, y="y", chart="i", facets="grp")
        n_all = sum(list(t.marker.color).count(RUNS_ORANGE) for t in r.plot().data if t.mode and "markers" in t.mode)
        n_loc = sum(
            list(t.marker.color).count(RUNS_ORANGE)
            for t in r.plot(runs_highlight="localized").data if t.mode and "markers" in t.mode
        )
        assert n_all == 48
        assert n_loc == 16

    def test_multipart_chart_honors_option(self):
        """Multi-part charts segment signals per part."""
        y = [11, 12, 11, 12, 11, 12, 11, 12] + [9, 8, 9, 8] + \
            [11, 12, 11, 12] + [9, 8, 9, 8] + [11, 12, 11, 12]
        r = qic(y=[float(v) for v in y] * 2, chart="i", part=25)
        assert r.data["runs_signal_localized"].sum() == 16
        colors = list(r.plot(runs_highlight="localized").data[0].marker.color)
        assert colors.count(RUNS_ORANGE) == 16


class TestRunChart:
    def test_run_chart_no_limit_traces(self):
        y = list(range(1, 21))
        r = qic(y=y, chart="run")
        fig = r.plot()
        # run chart: data + CL only (UCL/LCL are all NaN, skipped)
        assert len(fig.data) == 2


class TestOptions:
    def test_show_grid(self, i_result):
        fig = i_result.plot(show_grid=True)
        assert fig.layout.xaxis.showgrid is True

    def test_show_labels_false(self, i_result):
        fig = i_result.plot(show_labels=False)
        assert len(fig.layout.annotations) == 0

    def test_y_percent(self, i_result):
        fig = i_result.plot(y_percent=True)
        assert "%" in (fig.layout.yaxis.tickformat or "")

    def test_show_95(self, i_result):
        fig_without = i_result.plot(show_95=False)
        fig_with = i_result.plot(show_95=True)
        assert len(fig_with.data) > len(fig_without.data)


class TestShowXLabels:
    """show_x_labels=False hides tick text but keeps the label in hover."""

    @staticmethod
    def _funnel():
        return qic(
            x=[f"Clinic {c}" for c in "ABCDEF"],
            y=[8, 15, 9, 33, 6, 20], n=[45, 120, 80, 260, 55, 150],
            chart="p", funnel=True,
        )

    def test_show_x_labels_false_hides_ticks(self, i_result):
        """The only guard against plot_result's **_kwargs swallowing the param."""
        fig = i_result.plot(show_x_labels=False)
        assert fig.layout.xaxis.showticklabels is False
        assert fig.layout.xaxis.ticks == ""

    def test_show_x_labels_default_shows_ticks(self, i_result):
        fig = i_result.plot()
        assert fig.layout.xaxis.showticklabels is None
        assert fig.layout.xaxis.ticks == "outside"

    def test_hidden_labels_keep_x_in_hover(self):
        """Hiding ticks must not cost the label — %{x} still carries it."""
        fig = self._funnel().plot(show_x_labels=False)
        assert "%{x}" in fig.data[0].hovertemplate
        assert fig.data[0].x[0] == "Clinic A"

    def test_show_x_labels_on_funnel_categorical_axis(self):
        """Tick visibility and tick density are independent settings."""
        fig = self._funnel().plot(show_x_labels=False)
        assert fig.layout.xaxis.showticklabels is False
        assert fig.layout.xaxis.nticks == 0

    def test_show_x_labels_faceted(self):
        """Catches a missed forward through _plot_faceted."""
        df = pd.DataFrame({
            "x": list(range(1, 11)) * 2,
            "y": list(np.arange(10.0)) * 2,
            "unit": ["A"] * 10 + ["B"] * 10,
        })
        r = qic(data=df, x="x", y="y", chart="i", facets="unit")
        fig = r.plot(show_x_labels=False)
        assert fig.layout.xaxis.showticklabels is False
        assert fig.layout.xaxis2.showticklabels is False


def test_y_percent_default():
    # p-chart should default to y_percent=True
    y = [10] * 10
    n = [100] * 10
    r = qic(y=y, n=n, chart="p")
    assert r._plot_opts["y_percent"] is True
    
    # i-chart should default to y_percent=False
    r2 = qic(y=y, chart="i")
    assert r2._plot_opts["y_percent"] is False

def test_dots_only_connectivity():
    # Categorical x-axis without x_period should imply dots_only in render
    # (We test the logic in __init__ passing categorical X)
    data = pd.DataFrame({
        "hosp": ["H1", "H2", "H3"],
        "val": [10, 20, 15]
    })
    r = qic(data=data, x="hosp", y="val", chart="i")
    # render.py logic handles this during .plot(), but we verify x is string
    assert all(isinstance(x, str) for x in r.data["x"])

def test_summary_method(capsys):
    y = [10, 11, 12, 10, 11]
    r = qic(y=y, chart="i")
    r.show_summary()
    captured = capsys.readouterr()
    assert "Chart: I" in captured.out
    assert "n observations : 5" in captured.out

def test_x_format_and_y_expand():
    y = [10, 20, 30]
    # This just ensures parameters are accepted and stored
    r = qic(y=y, chart="i", x_format="%Y", y_expand=100)
    assert r._plot_opts["x_format"] == "%Y"
    assert r._plot_opts["y_expand"] == 100
