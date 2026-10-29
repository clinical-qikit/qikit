"""
Tests for qikit.render — Plotly figure generation.
"""

from __future__ import annotations
import numpy as np
import pandas as pd
import pytest
import plotly.graph_objects as go
from qikit.spc.api import _qic as qic  # engine core: qic() plus funnel arguments
from qikit.render.spc_plots import _signal_label_offsets
from qikit.render.utils import NORMAL, RUNS, SIGMA



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
        """A point beyond limits should be colored brick red (#b13b31)."""
        y = [10.0] * 29 + [40.0]
        r = qic(y=y, chart="i")
        fig = r.plot()
        colors = fig.data[0].marker.color
        assert any(c == "#b13b31" for c in colors)

    def test_normal_points_are_gray(self):
        """Normal points should be the dark data ink."""
        y = [10.0] * 20
        r = qic(y=y, chart="i")
        fig = r.plot()
        colors = fig.data[0].marker.color
        assert all(c == "#3a3a3a" for c in colors)


# Hardcoded on purpose: these pin the palette against accidental drift.
SIGMA_RED = "#b13b31"
RUNS_ORANGE = "#d99a2b"
NORMAL_GRAY = "#3a3a3a"


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
        """all: the crossings blanket turns the whole chart amber."""
        fig = crossings_and_run.plot(runs_highlight="all")
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

    def test_default_matches_localized(self, crossings_and_run):
        """The default localizes: a crossings signal must not blanket the chart."""
        assert list(crossings_and_run.plot().data[0].marker.color) == \
            list(crossings_and_run.plot(runs_highlight="localized").data[0].marker.color)

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
        def amber(fig):
            return sum(
                list(t.marker.color).count(RUNS_ORANGE)
                for t in fig.data if t.mode and "markers" in t.mode
            )
        assert amber(r.plot(runs_highlight="all")) == 48
        assert amber(r.plot(runs_highlight="localized")) == 16
        # The default localizes, so it must match "localized" through this path too.
        assert amber(r.plot()) == 16

    def test_multipart_chart_honors_option(self):
        """Multi-part charts segment signals per part."""
        y = [11, 12, 11, 12, 11, 12, 11, 12] + [9, 8, 9, 8] + \
            [11, 12, 11, 12] + [9, 8, 9, 8] + [11, 12, 11, 12]
        r = qic(y=[float(v) for v in y] * 2, chart="i", part=25)
        assert r.data["runs_signal_localized"].sum() == 16
        colors = list(r.plot(runs_highlight="localized").data[0].marker.color)
        assert colors.count(RUNS_ORANGE) == 16


class TestPointSizes:
    """Signal points carry more ink than routine ones."""

    def test_signal_points_are_larger(self):
        y = list(np.random.default_rng(21).normal(50, 4, 23))
        y.insert(17, 120.0)
        fig = qic(y=y, chart="i").plot()
        sizes = list(fig.data[0].marker.size)
        colors = list(fig.data[0].marker.color)
        signal = [s for s, c in zip(sizes, colors) if c != NORMAL_GRAY]
        normal = [s for s, c in zip(sizes, colors) if c == NORMAL_GRAY]
        assert signal and normal
        assert min(signal) > max(normal)

    def test_point_size_scales_all_points(self, i_result):
        small = set(i_result.plot(point_size=1.0).data[0].marker.size)
        large = set(i_result.plot(point_size=3.0).data[0].marker.size)
        assert min(large) > max(small)


class TestLabelDecimals:
    """CL/UCL/LCL labels scale their precision to the spread they span."""

    @staticmethod
    def _labels(fig):
        return [a.text for a in fig.layout.annotations if a.text and "=" in a.text]

    def test_large_counts_drop_decimals(self):
        y = list(np.random.default_rng(3).poisson(1200, 24).astype(float))
        for text in self._labels(qic(y=y, chart="c").plot()):
            assert "." not in text

    def test_small_values_keep_resolution(self):
        """decimals=1 would round these limits into a single value."""
        y = list(np.random.default_rng(3).normal(0.82, 0.05, 24))
        labels = self._labels(qic(y=y, chart="i").plot())
        assert len(set(labels)) == 3
        for text in labels:
            assert len(text.split(".")[1]) >= 3

    def test_percent_axis_labels_match_axis(self):
        """A percent axis shows 100x the stored value; the labels must agree."""
        rng = np.random.default_rng(3)
        n = [120.0] * 24
        y = list(rng.binomial(120, 0.18, 24).astype(float))
        labels = self._labels(qic(y=y, n=n, chart="p").plot())
        assert labels and all(t.endswith("%") for t in labels)
        assert any(t.startswith("CL=1") for t in labels)  # ~18%, not 0.18

    def test_explicit_decimals_still_honored(self, i_result):
        labels = self._labels(i_result.plot(decimals=3))
        assert all(len(t.split(".")[1]) == 3 for t in labels)

    def test_flat_series_does_not_crash(self):
        """Zero spread has no scale to derive precision from, and no limits either."""
        labels = self._labels(qic(y=[10.0] * 20, chart="i").plot())
        # A flat series yields NaN limits, so only the center line is labeled.
        assert len(labels) == 1
        assert labels[0].startswith("CL=")


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
            chart="p", funnel=True, x_spacing="x",
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


class TestOEFunnelLimitNaming:
    """An O/E funnel's bands are probability contours, not sigma multiples."""

    @staticmethod
    def _oe():
        return qic(
            y=[4, 1, 12, 6, 28, 9, 110, 92],
            n=[2.5, 3.8, 5.0, 8.2, 12.0, 25.0, 96.0, 105.0],
            chart="oe", funnel=True,
        )

    def test_traces_named_by_probability(self):
        names = [t.name for t in self._oe().plot(show_95=True).data]
        assert "99.8%+" in names and "99.8%-" in names
        assert "95%+" in names and "95%-" in names
        assert "UCL" not in names and "2σ+" not in names

    def test_direct_labels_named_by_probability(self):
        texts = [a.text for a in self._oe().plot().layout.annotations]
        assert any(t.startswith("99.8%+=") for t in texts)
        assert not any(t.startswith("UCL=") for t in texts)

    def test_other_charts_keep_sigma_naming(self):
        """The rename is scoped to oe; every other chart still reads in sigma."""
        r = qic(y=[5, 6, 7, 8, 6, 5, 7, 9], chart="i")
        names = [t.name for t in r.plot(show_95=True).data]
        assert "UCL" in names and "2σ+" in names

    def test_faceted_oe_also_renames(self):
        """Catches a missed forward through _plot_faceted."""
        df = pd.DataFrame({
            "y": [4, 1, 12, 6, 28, 9, 110, 92] * 2,
            "n": [2.5, 3.8, 5.0, 8.2, 12.0, 25.0, 96.0, 105.0] * 2,
            "site": ["North"] * 8 + ["South"] * 8,
        })
        r = qic(data=df, y="y", n="n", chart="oe", funnel=True, facets="site")
        names = [t.name for t in r.plot().data]
        assert "99.8%+" in names
        assert "UCL" not in names


class TestOEPFunnelLimitNaming:
    """The over-dispersed O/E funnel labels its bands by probability too."""

    def test_traces_named_by_probability(self):
        r = qic(
            y=[23, 8, 34, 19, 59, 31, 72, 38, 104, 64, 120, 88],
            n=[12.0, 18.0, 25.0, 30.0, 38.0, 45.0, 55.0, 64.0, 72.0, 85.0, 96.0, 110.0],
            chart="oep", funnel=True,
        )
        names = [t.name for t in r.plot(show_95=True).data]
        assert "99.8%+" in names and "95%+" in names
        assert "UCL" not in names and "2σ+" not in names


class TestOEHoverAndCaption:
    """An O/E chart has to be readable by a department chair, not just a statistician:
    counts before ratios, and the power caveat attached to the picture."""

    Y = [12, 8, 8, 3, 20, 14, 31, 26, 55, 48, 72, 110]
    N = [5.0, 3.2, 6.5, 4.1, 12.0, 15.5, 28.0, 30.0, 52.0, 60.0, 70.0, 62.0]

    def _fig(self, **kw):
        return qic(y=self.Y, n=self.N, chart="oe", funnel=True, **kw).plot()

    def test_hover_leads_with_counts_then_interval_then_detectability(self):
        trace = self._fig().data[0]
        tpl = trace.hovertemplate
        assert "Observed %{customdata[1]}" in tpl
        assert "95% CI: %{customdata[2]}" in tpl
        assert "Smallest detectable O/E: %{customdata[3]}" in tpl
        assert tpl.index("Observed") < tpl.index("95% CI") < tpl.index("Smallest")

    def test_hover_values_are_preformatted_strings(self):
        """Plotly renders a NaN through a d3 number format literally, so the values
        are strings by the time they reach the template."""
        row = self._fig().data[0].customdata[0]
        assert row[1] == "8 / expected 3.2"
        assert row[2] == "1.08–4.93"
        assert row[3] == "4.62"

    def test_missing_expected_reads_as_na_not_nan(self):
        fig = qic(y=[0, 5, 8], n=[0.0, 4.0, 6.0], chart="oe").plot()
        assert fig.data[0].customdata[0][3] == "n/a"

    def test_underpowered_chart_captions_itself(self):
        """summary["underpowered"] does not travel with a screenshot."""
        texts = [a.text.replace("<br>", " ") for a in self._fig().layout.annotations]
        assert any("not evidence of acceptable performance" in t for t in texts)

    def test_user_caption_wins(self):
        texts = [a.text for a in self._fig(caption="Source: Vizient Q4 2025").layout.annotations]
        assert any("Vizient" in t for t in texts)
        assert not any("not evidence" in t for t in texts)

    def test_well_powered_chart_has_no_auto_caption(self):
        fig = qic(y=[400] * 12, n=[400.0] * 12, chart="oe", funnel=True).plot()
        assert not any("not evidence" in (a.text or "") for a in fig.layout.annotations)

    def test_underpowered_p_funnel_captions_itself_too(self):
        """The caveat follows summary["underpowered"], which p/u funnels now report."""
        y = [4, 1, 3, 2, 4, 3, 5, 6, 8, 7, 10, 12, 19, 48]
        n = [12, 15, 20, 24, 30, 38, 45, 60, 75, 90, 120, 150, 200, 260]
        fig = qic(y=y, n=n, chart="p", funnel=True).plot()
        assert any("not evidence" in (a.text or "") for a in fig.layout.annotations)

    def test_other_charts_keep_the_plain_hover(self):
        fig = qic(y=[3, 2, 6, 2], n=[90, 113, 105, 102], chart="u").plot()
        tpl = fig.data[0].hovertemplate
        assert "%{customdata}<extra></extra>" in tpl
        assert "95% CI" not in tpl


class TestSignalMethodRendering:
    """A screenshot carries no summary keys, so every funnel states the rule that
    coloured its points; under signal_method="fdr" the curves no longer decide them."""

    Y = [2, 30, 5, 40, 3, 50, 8, 60, 1, 70]
    N = [20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0, 55.0, 60.0, 65.0]

    def _captions(self, fig):
        # Captions wrap to the figure width; the tests read the notes as written.
        return [a.text.replace("<br>", " ") for a in fig.layout.annotations if a.yref == "paper"]

    def _r(self, **kw):
        return qic(y=self.Y, n=self.N, chart="up", funnel=True, **kw)

    def test_limits_states_the_exact_test(self):
        (cap,) = self._captions(self._r(signal_side="above", show_95=True).plot())
        assert cap.startswith(
            "Outlier: beyond the 99.8% limit (exact test, one-sided, above the center "
            "line, p < 0.001); alert: beyond the 95% limit (p < 0.025)."
        )

    def test_levels_follow_the_parameter(self):
        (cap,) = self._captions(self._r(levels=(0.997, 0.95)).plot())
        assert cap.startswith("Outlier: beyond the 99.7% limit (exact test, two-sided, p < 0.003)")

    def test_fdr_names_its_scope_and_alert_tier(self):
        (cap,) = self._captions(self._r(signal_method="fdr", show_95=True).plot())
        assert cap.startswith("Outlier: q < 0.05; alert: q < 0.1 (Benjamini-Hochberg false "
                              "discovery rate across 10 providers, two-sided p-values).")
        assert "not adjusted for multiple comparisons" in cap

    def test_faceted_fdr_is_per_panel(self):
        df = pd.DataFrame({"o": self.Y * 2, "e": self.N * 2, "site": ["A"] * 10 + ["B"] * 10})
        fig = qic(y="o", n="e", data=df, chart="up", funnel=True, facets="site",
                  signal_method="fdr").plot()
        assert any("within each panel" in c for c in self._captions(fig))

    def test_joins_the_underpowered_caption(self):
        fig = qic(y=TestOEHoverAndCaption.Y, n=TestOEHoverAndCaption.N, chart="oe",
                  funnel=True).plot()
        (cap,) = self._captions(fig)
        assert cap.startswith("Outlier: beyond the 99.8% limit (exact test, two-sided")
        assert cap.endswith("not evidence of acceptable performance.")

    def test_long_captions_wrap_to_the_figure(self):
        fig = self._r(signal_method="fdr", show_95=True).plot(width=500)
        (ann,) = [a for a in fig.layout.annotations if a.yref == "paper"]
        assert all(len(line) <= 80 for line in ann.text.split("<br>"))

    def test_user_caption_wins(self):
        fig = self._r(signal_method="fdr", caption="Source: registry").plot()
        assert self._captions(fig) == ["Source: registry"]

    def test_hover_reports_p_and_q(self):
        trace = self._r(signal_side="below").plot().data[0]
        assert "<br>p = %{customdata[1]}" in trace.hovertemplate
        assert all(" (below), q = " in row[1] for row in trace.customdata)


# ---------------------------------------------------------------------------
# Funnel ergonomics: warn tier, signal labels, rank spacing, labels and hover
# ---------------------------------------------------------------------------


class TestFunnelLabeling:
    Y = [9, 6, 7, 11, 13, 17, 37, 29, 66, 40]
    N = [4.0, 6.0, 8.0, 10.0, 14.0, 18.0, 24.0, 30.0, 40.0, 55.0]
    # 10-digit, numeric-looking IDs: the coercion trap x_spacing="rank" exists for.
    X = [str(1234567890 + i) for i in range(10)]
    NAMES = [f"Dr {c}" for c in "ABCDEFGHIJ"]

    def _r(self, **kw):
        return qic(x=self.X, y=self.Y, n=self.N, chart="oe", funnel=True, cl=1.0, **kw)

    def test_warn_points_amber_with_show_95(self):
        r = self._r(show_95=True)
        colors = r.plot().data[0].marker.color
        d = r.data
        assert [c for c, w in zip(colors, d["warn_signal"]) if w] == [RUNS] * 3
        assert [c for c, s in zip(colors, d["sigma_signal"]) if s] == [SIGMA]

    def test_warn_points_plain_without_show_95(self):
        r = self._r()
        colors = r.plot().data[0].marker.color
        assert all(c == NORMAL for c, w in zip(colors, r.data["warn_signal"]) if w)

    def test_one_sided_leaves_the_other_side_plain(self):
        # Two outliers at E = 20: 45 above the line, 4 below it.
        y = [20, 19, 45, 4, 31, 10, 21, 18, 22, 20]
        r = qic(y=y, n=[20.0] * 10, chart="oe", funnel=True, cl=1.0,
                signal_side="above", show_95=True, label_signals="both")
        fig = r.plot()
        colors = fig.data[0].marker.color
        assert colors[2] == SIGMA and colors[3] == NORMAL
        assert colors[4] == RUNS and colors[5] == NORMAL
        assert len(self._signal_annotations(fig)) == 2

    def test_non_funnel_oe_keeps_runs_coloring(self):
        r = qic(y=self.Y, n=self.N, chart="oe", cl=1.0, show_95=True)
        colors = r.plot().data[0].marker.color
        # Runs, not the warn tier, own amber on a time-ordered chart.
        amber = [c == RUNS for c in colors]
        assert amber == list(r.data["runs_signal_localized"] & ~r.data["sigma_signal"])

    def _signal_annotations(self, fig):
        return [a for a in fig.layout.annotations if a.showarrow and a.arrowhead == 0]

    @pytest.mark.parametrize("mode,count", [("outlier", 1), ("warn", 3), ("both", 4)])
    def test_label_signals_counts(self, mode, count):
        fig = self._r(label_signals=mode).plot()
        assert len(self._signal_annotations(fig)) == count

    def test_labels_use_point_labels_and_tier_color(self):
        fig = self._r(label_signals="both", point_labels=self.NAMES).plot()
        anns = {a.text: a for a in self._signal_annotations(fig)}
        assert set(anns) == {"Dr A", "Dr G", "Dr I", "Dr J"}
        assert anns["Dr I"].font.color == SIGMA
        assert anns["Dr A"].font.color == RUNS
        assert anns["Dr A"].ay < 0 and anns["Dr J"].ay > 0   # above up, below down

    def test_label_absorbs_note(self):
        notes = [""] * 8 + ["reviewed", ""]
        fig = self._r(label_signals="outlier", notes=notes).plot()
        texts = [a.text for a in fig.layout.annotations]
        assert f"{self.X[8]} — reviewed" in texts
        assert "reviewed" not in texts

    def test_label_signals_plot_override_and_guard(self):
        r = self._r()
        assert len(self._signal_annotations(r.plot(label_signals="warn"))) == 3
        with pytest.raises(ValueError, match="warn tier"):
            qic(y=[1.0, 2.0, 3.0, 4.0], chart="i").plot(label_signals="warn")

    def test_label_signals_outlier_on_any_chart(self):
        r = qic(y=[10, 11, 9, 10, 30, 10, 11, 9, 10, 10], chart="i", label_signals="outlier")
        assert len(self._signal_annotations(r.plot())) == 1

    def test_offsets_stagger_neighbours_and_reset_after_a_gap(self):
        offs = _signal_label_offsets([0, 1, 2, 3, 10], [True] * 5, min_gap=1)
        assert [ay for _, ay in offs] == [-22, -38, -54, -22, -22]
        assert offs[1][0] != offs[2][0]

    def test_offsets_gap_is_inclusive(self):
        offs = _signal_label_offsets([0, 2, 5], [True] * 3, min_gap=2)
        assert [ay for _, ay in offs] == [-22, -38, -22]

    def test_offsets_sides_are_independent(self):
        offs = _signal_label_offsets([0, 1], [True, False], min_gap=5)
        assert offs == [(0, -22), (0, 22)]

    def test_rank_spacing_emits_only_numeric_x(self):
        fig = self._r(x_spacing="rank", show_95=True, label_signals="both",
                      notes=["x"] + [""] * 9).plot()
        for trace in fig.data:
            assert all(isinstance(v, (int, np.integer)) for v in trace.x), trace.name
        for a in fig.layout.annotations:
            if a.xref in (None, "x"):
                assert isinstance(a.x, (int, float)), a.text
        assert fig.layout.xaxis.type == "linear"
        assert list(fig.layout.xaxis.tickvals) == list(range(1, 11))
        assert list(fig.layout.xaxis.ticktext) == self.X
        assert fig.layout.hovermode == "closest"

    def test_rank_ticktext_uses_labels(self):
        fig = self._r(x_spacing="rank", point_labels=self.NAMES).plot()
        assert list(fig.layout.xaxis.ticktext) == self.NAMES

    def test_rank_as_plot_override_and_x_order_guard(self):
        r = self._r()
        assert r.plot(x_spacing="rank").layout.xaxis.type == "linear"
        with pytest.raises(ValueError, match="x_order"):
            r.plot(x_spacing="rank", x_order=self.X)

    def test_labels_on_categorical_axis(self):
        fig = self._r(point_labels=self.NAMES, x_spacing="x").plot()
        assert list(fig.layout.xaxis.ticktext) == self.NAMES
        assert fig.data[0].x[0] == self.X[0]

    def test_hover_names_the_point_and_lists_extras(self):
        fig = self._r(point_labels=self.NAMES,
                      hover_extra={"Encounters": list(range(100, 110)),
                                   "Practice": ["East"] * 10}).plot()
        trace = fig.data[0]
        tpl = trace.hovertemplate
        row = trace.customdata[0]
        # O/E fields keep their indices; p/q, then extras, then header are appended.
        assert "Observed %{customdata[1]}" in tpl
        assert "<br>p = %{customdata[4]}" in tpl
        assert "<br>Encounters: %{customdata[5]}" in tpl
        assert "<br>Practice: %{customdata[6]}" in tpl
        assert tpl.startswith("%{customdata[7]}: %{y}")
        assert " (two-sided), q = " in row[4]
        assert row[5] == "100" and row[6] == "East"
        assert row[7] == f"Dr A ({self.X[0]})"

    def test_hover_extra_on_plain_chart(self):
        fig = qic(y=[1.0, 2.0, 3.0], chart="i",
                  hover_extra={"k": [1.5, float("nan"), 3.0]}).plot()
        trace = fig.data[0]
        assert trace.hovertemplate.startswith("%{x}: %{y}")
        assert [r[1] for r in trace.customdata] == ["1.5", "n/a", "3"]

    def test_faceted_rank_and_labels(self):
        df = pd.DataFrame({
            "o": self.Y * 2, "e": self.N * 2, "name": self.NAMES * 2,
            "site": ["A"] * 10 + ["B"] * 10,
        })
        fig = qic(y="o", n="e", data=df, chart="oe", funnel=True, cl=1.0,
                  facets="site", point_labels="name", x_spacing="rank",
                  label_signals="both").plot()
        assert list(fig.layout.xaxis2.ticktext) == self.NAMES
        assert len(self._signal_annotations(fig)) == 8


# ---------------------------------------------------------------------------
# Volume axis: a funnel plotted against its denominator, as Spiegelhalter draws it
# ---------------------------------------------------------------------------


class TestVolumeAxis:
    Y = [9, 6, 7, 11, 13, 17, 37, 29, 66, 40]
    N = [4.0, 6.0, 8.0, 10.0, 14.0, 18.0, 24.0, 30.0, 40.0, 55.0]
    X = [str(1234567890 + i) for i in range(10)]
    PY = [8, 15, 9, 33, 6, 20, 41, 12]
    PN = [45, 120, 80, 260, 55, 150, 300, 70]

    def _oe(self, **kw):
        return qic(x=self.X, y=self.Y, n=self.N, chart="oe", funnel=True, cl=1.0, **kw)

    def _p(self, **kw):
        return qic(x=[f"Clinic {c}" for c in "ABCDEFGH"], y=self.PY, n=self.PN,
                   chart="p", funnel=True, **kw)

    @staticmethod
    def _trace(fig, name):
        return next(t for t in fig.data if t.name == name)

    # -- spacing resolution ------------------------------------------------

    def test_funnel_defaults_to_volume_axis(self):
        r = self._oe()
        fig = r.plot()
        assert list(fig.data[0].x) == list(r.data["expected"])
        assert fig.layout.xaxis.type == "linear"
        assert fig.layout.hovermode == "closest"
        assert fig.layout.xaxis.ticktext is None

    def test_p_funnel_plots_against_n(self):
        r = self._p()
        assert list(r.plot().data[0].x) == sorted(self.PN)
        assert list(r.data["n"]) == sorted(self.PN)

    def test_explicit_x_keeps_the_categorical_funnel(self):
        fig = self._p(x_spacing="x").plot()
        assert fig.layout.xaxis.type == "category"
        assert fig.data[0].x[0] == "Clinic A"

    def test_equal_denominators_fall_back_to_x(self):
        fig = qic(x=list("abcd"), y=[40, 52, 61, 38], n=[400.0] * 4, chart="oe", funnel=True).plot()
        assert list(fig.data[0].x) == list("abcd")

    def test_time_ordered_charts_stay_on_x(self):
        fig = qic(x=list("abcd"), y=[3, 2, 6, 2], n=[90, 113, 105, 102], chart="u").plot()
        assert list(fig.data[0].x) == list("abcd")

    def test_spacing_is_a_plot_override_both_ways(self):
        assert self._oe().plot(x_spacing="x").layout.xaxis.type == "category"
        r = self._oe(x_spacing="x")
        assert list(r.plot(x_spacing="n").data[0].x) == self.N

    # -- contours ----------------------------------------------------------

    @pytest.mark.parametrize("name", ["CL", "99.8%+", "99.8%-", "95%+", "95%-"])
    def test_limits_are_drawn_on_the_grid(self, name):
        r = self._oe(show_95=True)
        trace = self._trace(r.plot(), name)
        grid = r.funnel_limits()
        assert len(trace.x) == len(grid) > len(self.N)
        assert list(trace.x) == list(grid["n"])

    def test_curves_pass_through_each_points_limit(self):
        r = self._p(show_95=True)
        fig = r.plot()
        for name, col in [("99.8%+", "ucl"), ("99.8%-", "lcl"), ("95%+", "ucl_95")]:
            trace = self._trace(fig, name)
            at = dict(zip(trace.x, trace.y))
            for n_i, lim in zip(r.data["n"], r.data[col]):
                assert at[n_i] == lim

    def test_trace_names_unchanged(self):
        names = [t.name for t in self._oe(show_95=True).plot().data]
        assert names == ["data", "CL", "99.8%+", "99.8%-", "95%+", "95%-"]

    # -- titles and hover --------------------------------------------------

    def test_title_defaults_to_the_n_column(self):
        df = pd.DataFrame({"site": list("abcdef"), "d": [3, 7, 4, 15, 9, 11],
                           "e": [2.5, 4.0, 6.1, 8.0, 12.0, 14.0]})
        r = qic(x="site", y="d", n="e", data=df, chart="oe", funnel=True)
        assert r.xlab == "e"
        assert r.plot().layout.xaxis.title.text == "e"

    @pytest.mark.parametrize("chart,title", [
        ("oe", "Expected events"), ("oep", "Expected events"),
        ("p", "Sample size"), ("pp", "Sample size"),
        ("u", "Exposure"), ("up", "Exposure"),
    ])
    def test_title_defaults_to_what_the_denominator_measures(self, chart, title):
        r = qic(y=self.PY, n=self.PN, chart=chart, funnel=True)
        assert r.plot().layout.xaxis.title.text == title

    def test_explicit_xlab_titles_the_volume_axis(self):
        r = self._p(xlab="Patients treated")
        fig = r.plot()
        assert fig.layout.xaxis.title.text == "Patients treated"
        assert "Patients treated: %{x}" in fig.data[0].hovertemplate

    def test_title_follows_a_spacing_override(self):
        r = self._p()
        assert r.plot(x_spacing="x").layout.xaxis.title.text == "Subgroup"
        assert r.plot(x_spacing="rank").layout.xaxis.title.text == "Subgroup"
        assert self._p(x_spacing="x").plot(x_spacing="n").layout.xaxis.title.text == "Sample size"

    def test_hover_names_the_point_and_gives_its_denominator(self):
        trace = self._p().plot().data[0]
        assert trace.customdata[0][-1] == "Clinic A"
        assert "Sample size: %{x}" in trace.hovertemplate

    def test_oe_hover_keeps_its_counts(self):
        tpl = self._oe().plot().data[0].hovertemplate
        assert "Observed %{customdata[1]}" in tpl
        assert "Expected events: %{x}" not in tpl

    # -- log axis ----------------------------------------------------------

    def test_log_axis_puts_annotations_on_log10(self):
        r = self._oe(x_log=True, label_signals="both", point_labels=[f"Dr {c}" for c in "ABCDEFGHIJ"])
        fig = r.plot()
        assert fig.layout.xaxis.type == "log"
        direct = [a for a in fig.layout.annotations if a.text and a.text.startswith(("CL=", "99.8%"))]
        assert direct and all(a.x == pytest.approx(np.log10(max(self.N))) for a in direct)
        by_name = dict(zip(r.data["label"], r.data["expected"]))
        signal = [a for a in fig.layout.annotations if a.showarrow and a.arrowhead == 0]
        assert len(signal) == 4
        for a in signal:
            assert a.x == pytest.approx(np.log10(by_name[a.text]))

    def test_linear_axis_annotations_are_raw_n(self):
        fig = self._oe(label_signals="outlier").plot()
        signal = [a for a in fig.layout.annotations if a.showarrow and a.arrowhead == 0]
        assert [a.x for a in signal] == [40.0]

    def test_log_ticks_carry_full_labels(self):
        fig = self._oe(x_log=True).plot()
        assert list(fig.layout.xaxis.tickvals) == [5.0, 10.0, 20.0, 50.0]
        assert list(fig.layout.xaxis.ticktext) == ["5", "10", "20", "50"]

    @pytest.mark.parametrize("lo,hi,expected", [
        (8.0, 95.0, [10.0, 20.0, 50.0]),
        (40.0, 60.0, [40.0, 50.0, 60.0]),
        (20.0, 50000.0, [20.0, 50.0, 100.0, 200.0, 500.0, 1000.0, 2000.0, 5000.0,
                         10000.0, 20000.0, 50000.0]),
        (51.0, 55.0, [51.0, 55.0]),
    ])
    def test_log_tick_values(self, lo, hi, expected):
        from qikit.render.spc_plots import _log_ticks
        assert _log_ticks(lo, hi) == pytest.approx(expected)

    def test_log_axis_as_plot_override(self):
        assert self._oe().plot(x_log=True).layout.xaxis.type == "log"

    # -- facets ------------------------------------------------------------

    def test_faceted_volume_axis(self):
        df = pd.DataFrame({
            "site": ["A"] * 5 + ["B"] * 5,
            "y": [2, 5, 9, 4, 12, 20, 31, 18, 44, 60],
            "n": [40, 90, 150, 210, 300, 120, 200, 260, 400, 650],
        })
        r = qic(y="y", n="n", data=df, chart="p", funnel=True, facets="site", x_log=True)
        fig = r.plot()
        grid = r.funnel_limits()
        ucl = [t for t in fig.data if t.name == "99.8%+"]
        assert len(ucl) == 2
        for t, site in zip(ucl, ["A", "B"]):
            assert list(t.x) == list(grid.loc[grid["facet"] == site, "n"])
        assert fig.layout.xaxis.type == "log" and fig.layout.xaxis2.type == "log"
        assert fig.layout.xaxis.title.text == "n"

    # -- guards, on qic() and on plot() -----------------------------------

    def test_n_needs_a_funnel(self):
        with pytest.raises(ValueError, match="funnel=True"):
            qic(y=self.PY, n=self.PN, chart="p", x_spacing="n")
        with pytest.raises(ValueError, match="funnel=True"):
            qic(y=self.PY, n=self.PN, chart="p").plot(x_spacing="n")

    def test_n_needs_varying_denominators(self):
        args = dict(y=[40, 52, 61, 38], n=[400.0] * 4, chart="oe", funnel=True)
        with pytest.raises(ValueError, match="vary"):
            qic(x_spacing="n", **args)
        with pytest.raises(ValueError, match="vary"):
            qic(**args).plot(x_spacing="n")

    def test_x_log_needs_the_volume_axis(self):
        with pytest.raises(ValueError, match="x_log"):
            self._p(x_spacing="x", x_log=True)
        with pytest.raises(ValueError, match="x_log"):
            self._p(x_spacing="x").plot(x_log=True)
        with pytest.raises(ValueError, match="x_log"):
            qic(y=[1.0, 2.0, 3.0], chart="i", x_log=True)

    @pytest.mark.parametrize("spacing", [None, "n"])
    def test_x_order_needs_x_spacing_x_on_a_funnel(self, spacing):
        order = [f"Clinic {c}" for c in "HGFEDCBA"]
        with pytest.raises(ValueError, match="x_spacing='x'"):
            self._p(x_spacing=spacing, x_order=order)
        with pytest.raises(ValueError, match="x_spacing='x'"):
            self._p().plot(x_spacing=spacing, x_order=order)
        fig = self._p(x_spacing="x", x_order=order).plot()
        assert list(fig.layout.xaxis.categoryarray) == order


# ---------------------------------------------------------------------------
# styles=, x_range=/y_range=, show_legend= — slide-quality figures without patching
# ---------------------------------------------------------------------------

_Y = [9, 6, 7, 11, 13, 17, 37, 29, 66, 40]
_N = [4.0, 6.0, 8.0, 10.0, 14.0, 18.0, 24.0, 30.0, 40.0, 55.0]


def _oe_funnel(**kw):
    return qic(y=_Y, n=_N, chart="oe", funnel=True, cl=1.0, **kw)


def _trace(fig, name):
    matches = [t for t in fig.data if t.name == name]
    return matches[0] if matches else None


def _end_labels(fig):
    return [a.text for a in _end_label_annotations(fig)]


def _end_label_annotations(fig):
    """The CL/limit labels: unarrowed, left-anchored, on the data axes (not the caption)."""
    return [a for a in fig.layout.annotations
            if not a.showarrow and a.xanchor == "left" and a.xref != "paper"]


class TestPlotStyles:
    def test_unknown_override_is_an_error(self):
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            _oe_funnel().plot(x_rnage=(1, 10))

    @pytest.mark.parametrize("styles,match", [
        ({"limit": {"color": "red"}}, "unknown role"),
        ({"cl": {"colour": "red"}}, "unknown attribute"),
        ({"sigma": {"width": 2}}, "unknown attribute"),
        ({"ucl_95": {"dash": "dotted"}}, "dash"),
        ({"cl": {"width": 0}}, "positive number"),
        ({"cl": "red"}, "must be a dict"),
    ])
    def test_validation(self, styles, match):
        with pytest.raises(ValueError, match=match):
            _oe_funnel(styles=styles)
        with pytest.raises(ValueError, match=match):
            _oe_funnel().plot(styles=styles)

    def test_group_then_specific(self):
        fig = _oe_funnel(show_95=True, styles={
            "limits_95": {"color": "#777", "width": 1.5, "dash": "solid"},
            "limits": {"width": 2}, "ucl": {"color": "#000"},
        }).plot()
        for name in ("95%+", "95%-"):
            line = _trace(fig, name).line
            assert (line.color, line.width, line.dash) == ("#777", 1.5, "solid")
        assert (_trace(fig, "99.8%+").line.color, _trace(fig, "99.8%+").line.width) == ("#000", 2)
        assert _trace(fig, "99.8%-").line.width == 2

    def test_invisible_line_and_its_label_go(self):
        fig = _oe_funnel(styles={"lcl": {"visible": False}}).plot()
        assert _trace(fig, "99.8%-") is None
        assert not any(t.startswith("99.8%-=") for t in _end_labels(fig))
        assert any(t.startswith("99.8%+=") for t in _end_labels(fig))

    def test_name_renames_trace_and_end_label(self):
        fig = _oe_funnel(styles={"ucl": {"name": "Upper 99.8%"}}).plot()
        assert _trace(fig, "Upper 99.8%") is not None and _trace(fig, "99.8%+") is None
        assert any(t.startswith("Upper 99.8%=") for t in _end_labels(fig))

    def test_point_and_label_colors(self):
        fig = _oe_funnel(label_signals="outlier", styles={
            "sigma": {"color": "#c00000"}, "data": {"color": "#111111", "width": 2},
        }).plot()
        d = fig.data[0]
        assert d.marker.color[8] == "#c00000" and d.marker.color[0] == "#111111"
        assert d.line.width == 2
        labels = [a for a in fig.layout.annotations if a.showarrow and a.arrowhead == 0]
        assert [a.font.color for a in labels] == ["#c00000"]

    def test_warn_role_colors_the_funnel_amber_tier(self):
        fig = _oe_funnel(show_95=True, styles={"warn": {"color": "#ff8800"}}).plot()
        assert fig.data[0].marker.color.count("#ff8800") == 3

    def test_end_label_style(self):
        fig = _oe_funnel(styles={"end_labels": {"color": "#222", "size": 14}}).plot()
        anns = _end_label_annotations(fig)
        assert anns and all(a.font.size == 14 and a.font.color == "#222" for a in anns)

    def test_round_trips_through_plot_opts(self):
        styles = {"limits": {"width": 2}}
        r = _oe_funnel(styles=styles, show_legend=True, x_range=(10, None))
        assert r._plot_opts["styles"] == styles
        assert r._plot_opts["show_legend"] is True
        assert r._plot_opts["x_range"] == (10, None)


class TestPlotRanges:
    def test_x_range_with_an_open_end(self):
        lo, hi = _oe_funnel(x_range=(10, None)).plot().layout.xaxis.range
        assert lo == 10 and hi > 55

    def test_log_axis_takes_log10(self):
        lo, hi = _oe_funnel(x_log=True, x_range=(5, 50)).plot().layout.xaxis.range
        assert (lo, hi) == pytest.approx((np.log10(5), np.log10(50)))

    def test_trimmed_points_no_longer_stretch_y(self):
        r = _oe_funnel(x_range=(10, None))
        lo, hi = r.plot().layout.yaxis.range
        assert hi < 9 / 4                     # the E = 4 point, now off the axis
        assert hi > 66 / 40                   # the largest point still on it
        assert lo < r.data["ucl"].iloc[-1] < hi  # the narrow end of the funnel too

    def test_y_range_wins_and_can_be_half_open(self):
        assert list(_oe_funnel(y_range=(0, 3)).plot().layout.yaxis.range) == [0, 3]
        lo, hi = _oe_funnel(y_range=(0, None)).plot().layout.yaxis.range
        assert lo == 0 and hi > 9 / 4

    def test_flip_reverses_the_range(self):
        fig = _oe_funnel(x_range=(10, 50), flip=True).plot()
        assert list(fig.layout.xaxis.range) == [50, 10]
        assert fig.layout.xaxis.autorange != "reversed"

    def test_categorical_axis_is_rejected(self):
        r = qic(x=list("abcdefghij"), y=_Y, n=_N, chart="oe", funnel=True, x_spacing="x")
        with pytest.raises(ValueError, match="categorical"):
            r.plot(x_range=(1, 3))

    def test_rank_axis_ranges_by_position(self):
        fig = _oe_funnel(x_spacing="rank", x_range=(3, 8)).plot()
        assert list(fig.layout.xaxis.range) == [3, 8]

    @pytest.mark.parametrize("bad", [(1,), "1,5", (5, 1)])
    def test_bad_ranges(self, bad):
        with pytest.raises(ValueError):
            _oe_funnel(x_range=bad)

    def test_faceted_shares_x_and_fits_each_panel(self):
        df = pd.DataFrame({"o": _Y * 2, "e": _N * 2, "site": ["A"] * 10 + ["B"] * 10})
        fig = qic(y="o", n="e", data=df, chart="oe", funnel=True, facets="site",
                  x_range=(10, None)).plot()
        assert fig.layout.xaxis.range[0] == 10 and fig.layout.xaxis2.range[0] == 10
        assert fig.layout.yaxis.range[1] < 9 / 4


class TestLegend:
    def test_off_by_default(self):
        fig = _oe_funnel().plot()
        assert fig.layout.showlegend is False
        assert all(t.showlegend is None for t in fig.data)

    def test_pairs_share_an_entry_and_signals_get_one(self):
        fig = _oe_funnel(show_legend=True, show_95=True).plot()
        assert fig.layout.showlegend is True
        upper, lower = _trace(fig, "99.8%+"), _trace(fig, "99.8%-")
        assert upper.legendgroup == lower.legendgroup == "limits"
        assert upper.showlegend is False and lower.showlegend is False
        # One entry per contour pair, in the pair's group, named for its coverage.
        entry = _trace(fig, "99.8% limits")
        assert entry.x == (None,) and entry.legendgroup == "limits" and entry.showlegend
        assert _trace(fig, "95% limits").line.dash == "dash"
        assert _trace(fig, "Outlier (beyond 99.8%)").x == (None,)
        assert _trace(fig, "Alert (beyond 95%)") is not None
        # The series gets its own entry in its routine color, grouped with the points.
        (points,) = [t for t in fig.data if t.name == "data"]
        assert points.showlegend is False and points.legendgroup == "data"
        entry = _trace(fig, "Provider")
        assert entry.legendgroup == "data" and entry.marker.color == NORMAL
        assert _trace(fig, "Center line").legendgroup == "cl"
        # A funnel's legend is a column outside the right edge, clear of the title.
        assert fig.layout.legend.orientation == "v" and fig.layout.legend.x > 1

    def test_entries_follow_signal_method_and_styles(self):
        fig = _oe_funnel(show_legend=True, signal_method="fdr", fdr_levels=(0.2, 0.3),
                         signal_side="above").plot()
        assert _trace(fig, "Worse than expected: outlier (q < 0.2)") is not None
        worse = _oe_funnel(show_legend=True, signal_side="above").plot()
        assert _trace(worse, "Worse than expected: outlier (beyond 99.8%)") is not None
        named = _oe_funnel(show_legend=True, styles={"sigma": {"name": "Outlier"}}).plot()
        assert _trace(named, "Outlier") is not None

    def test_no_signal_entry_without_signals(self):
        fig = qic(y=[400] * 6, n=[400.0] * 6, chart="oe", funnel=True,
                  show_legend=True).plot()
        assert _trace(fig, "Outlier (beyond 99.8%)") is None

    def test_faceted_entries_come_from_one_panel(self):
        df = pd.DataFrame({"o": _Y * 2, "e": _N * 2, "site": ["A"] * 10 + ["B"] * 10})
        fig = qic(y="o", n="e", data=df, chart="oe", funnel=True, facets="site",
                  show_legend=True).plot()
        assert sum(1 for t in fig.data if t.name == "Center line" and t.showlegend) == 1
        assert sum(1 for t in fig.data if t.name == "Provider" and t.showlegend) == 1
