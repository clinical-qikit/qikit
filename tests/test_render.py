"""
Tests for qikit.render — Plotly figure generation.
"""

from __future__ import annotations
import math
import numpy as np
import pandas as pd
import pytest
import plotly.graph_objects as go
from qikit import qic, paretochart, bchart



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


def test_y_percent_default():
    # p-chart should default to y_percent=True
    y = [10] * 10
    n = [100] * 10
    r = qic(y=y, n=n, chart="p")
    assert r._plot_opts["y_percent"] == True
    
    # i-chart should default to y_percent=False
    r2 = qic(y=y, chart="i")
    assert r2._plot_opts["y_percent"] == False

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
