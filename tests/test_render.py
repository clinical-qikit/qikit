"""
Tests for qikit.plot — the figures qic(...).plot() and funnel(...).plot() draw.

Trace names, colours, labels, captions, axes, styles and legends are a public contract:
callers restyle figures by trace name and paste screenshots into reports.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest

from qikit import funnel, qic
from qikit.plot.charts import _log_ticks, _signal_label_offsets
from qikit.plot.theme import CONCERNING, IMPROVING, NORMAL, RUNS, SIGMA

# Hardcoded on purpose: these pin the palette against accidental drift.
SIGMA_RED = "#b13b31"
RUNS_ORANGE = "#d99a2b"
NORMAL_GRAY = "#3a3a3a"


@pytest.fixture
def i_result():
    rng = np.random.default_rng(7)
    return qic(y=rng.normal(10, 2, 25), chart="i")


def _colors(fig):
    return list(fig.data[0].marker.color)


def _trace(fig, name):
    matches = [t for t in fig.data if t.name == name]
    return matches[0] if matches else None


def _end_labels(fig):
    return [a.text for a in fig.layout.annotations
            if not a.showarrow and a.xanchor == "left" and a.xref != "paper"]


def _signal_annotations(fig):
    return [a for a in fig.layout.annotations if a.showarrow and a.arrowhead == 0]


def _captions(fig):
    return [a.text.replace("<br>", " ") for a in fig.layout.annotations if a.yref == "paper"]


# ---------------------------------------------------------------------------
# Time-ordered charts
# ---------------------------------------------------------------------------

class TestPlotBasics:
    def test_returns_a_figure_with_data_and_reference_lines(self, i_result):
        fig = i_result.plot(title="Test I Chart")
        assert isinstance(fig, go.Figure)
        assert [t.name for t in fig.data] == ["data", "CL", "UCL", "LCL"]
        assert "Test I Chart" in fig.layout.title.text

    def test_quiet_white_and_legend_free_by_default(self, i_result):
        fig = i_result.plot()
        assert fig.layout.showlegend is False
        assert fig.layout.plot_bgcolor == "white"

    def test_axis_titles_default_to_the_columns(self):
        df = pd.DataFrame({"month": range(1, 13), "waits": np.arange(12.0)})
        fig = qic(df, x="month", y="waits", chart="i").plot()
        assert fig.layout.xaxis.title.text == "month"
        assert fig.layout.yaxis.title.text == "waits"

    def test_a_signal_is_named_in_the_title(self):
        fig = qic(y=[10.0] * 29 + [40.0], chart="i").plot(title="Waits")
        assert fig.layout.title.text == "Waits (signal)"

    def test_unknown_option_is_an_error(self, i_result):
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            i_result.plot(x_rnage=(1, 10))


class TestSignalColors:
    def test_outlier_is_brick_and_routine_points_dark(self):
        fig = qic(y=[10.0] * 29 + [40.0], chart="i").plot(runs_highlight="none")
        colors = _colors(fig)
        assert colors[-1] == SIGMA_RED and SIGMA == SIGMA_RED
        assert all(c == NORMAL_GRAY for c in colors[:-1]) and NORMAL == NORMAL_GRAY

    def test_signal_points_are_larger(self):
        y = list(np.random.default_rng(21).normal(50, 4, 23))
        y.insert(17, 120.0)
        fig = qic(y=y, chart="i").plot()
        sizes, colors = list(fig.data[0].marker.size), _colors(fig)
        signal = [s for s, c in zip(sizes, colors) if c != NORMAL_GRAY]
        normal = [s for s, c in zip(sizes, colors) if c == NORMAL_GRAY]
        assert signal and normal and min(signal) > max(normal)

    def test_point_size_scales_every_point(self, i_result):
        small = set(i_result.plot(point_size=1.0).data[0].marker.size)
        large = set(i_result.plot(point_size=3.0).data[0].marker.size)
        assert min(large) > max(small)


@pytest.fixture
def crossings_and_run():
    """
    24 points in blocks of 9/4/3/4/4 around the centre: only 4 crossings (fewer than 8,
    so the crossings rule fires and covers the series), and the leading 9 are a run
    longer than round(log2 24) + 3 = 8. No point is beyond the limits.
    """
    y = [11, 12, 11, 12, 11, 12, 11, 12, 11] + [9, 8, 9, 8] + \
        [11, 12, 11] + [9, 8, 9, 8] + [11, 12, 11, 12]
    return qic(y=[float(v) for v in y], chart="i")


class TestRunsHighlight:
    def test_fixture_preconditions(self, crossings_and_run):
        s = crossings_and_run.summary
        assert s["crossings_signal"] and s["longest_run_signal"]
        assert (crossings_and_run.data["signal"] == "none").all()

    def test_all_colours_every_point(self, crossings_and_run):
        assert _colors(crossings_and_run.plot(runs_highlight="all")).count(RUNS_ORANGE) == 24

    def test_localized_colours_only_the_run(self, crossings_and_run):
        colors = _colors(crossings_and_run.plot(runs_highlight="localized"))
        assert colors[:9] == [RUNS_ORANGE] * 9
        assert all(c == NORMAL_GRAY for c in colors[9:]) and RUNS == RUNS_ORANGE

    def test_none_and_default(self, crossings_and_run):
        assert all(c == NORMAL_GRAY for c in _colors(crossings_and_run.plot(runs_highlight="none")))
        assert _colors(crossings_and_run.plot()) == \
            _colors(crossings_and_run.plot(runs_highlight="localized"))

    @pytest.mark.parametrize("mode", ["all", "localized", "none"])
    def test_outliers_stay_brick_and_symbols_track_colour(self, crossings_and_run, mode):
        assert SIGMA_RED in _colors(qic(y=[10.0] * 29 + [40.0], chart="i").plot(runs_highlight=mode))
        fig = crossings_and_run.plot(runs_highlight=mode)
        for c, s in zip(_colors(fig), fig.data[0].marker.symbol):
            assert (s == "diamond") == (c == RUNS_ORANGE)

    def test_invalid_value_raises(self, crossings_and_run):
        with pytest.raises(ValueError, match="runs_highlight must be one of"):
            crossings_and_run.plot(runs_highlight="bogus")

    def test_faceted_and_multipart_charts_honor_it(self, crossings_and_run):
        y = crossings_and_run.data["y"].tolist()
        df = pd.DataFrame({"y": y * 2, "grp": ["a"] * 24 + ["b"] * 24})
        r = qic(df, y="y", chart="i", facets="grp")

        def amber(fig):
            return sum(list(t.marker.color).count(RUNS_ORANGE)
                       for t in fig.data if t.mode and "markers" in t.mode)

        assert amber(r.plot(runs_highlight="all")) == 48
        assert amber(r.plot()) == 18
        parts = qic(y=y * 2, chart="i", part=24)
        assert _colors(parts.plot()).count(RUNS_ORANGE) == 18


class TestLabelsAndOptions:
    def test_large_counts_drop_decimals(self):
        y = list(np.random.default_rng(3).poisson(1200, 24).astype(float))
        assert all("." not in t for t in _end_labels(qic(y=y, chart="c").plot()))

    def test_small_values_keep_resolution(self):
        y = list(np.random.default_rng(3).normal(0.82, 0.05, 24))
        labels = _end_labels(qic(y=y, chart="i").plot())
        assert len(set(labels)) == 3 and all(len(t.split(".")[1]) >= 3 for t in labels)

    def test_percent_axis_labels_match_axis(self):
        y = list(np.random.default_rng(3).binomial(120, 0.18, 24).astype(float))
        fig = qic(y=y, n=[120.0] * 24, chart="p").plot()
        assert fig.layout.yaxis.tickformat == ".0%"
        labels = _end_labels(fig)
        assert labels and all(t.endswith("%") for t in labels)
        assert any(t.startswith("CL=1") for t in labels)

    def test_explicit_decimals(self, i_result):
        assert all(len(t.split(".")[1]) == 3 for t in _end_labels(i_result.plot(decimals=3)))

    def test_flat_series_labels_only_the_centre(self):
        labels = _end_labels(qic(y=[10.0] * 20, chart="i").plot())
        assert len(labels) == 1 and labels[0].startswith("CL=")

    def test_run_chart_draws_data_and_centre_only(self):
        assert len(qic(y=list(range(1, 21)), chart="run").plot().data) == 2

    def test_display_options(self, i_result):
        assert i_result.plot(show_grid=True).layout.xaxis.showgrid is True
        assert len(i_result.plot(show_labels=False).layout.annotations) == 0
        assert "%" in i_result.plot(y_percent=True).layout.yaxis.tickformat
        assert len(i_result.plot(show_95=True).data) == len(i_result.plot().data) + 2
        assert i_result.plot(x_format="%Y").layout.xaxis.tickformat == "%Y"

    def test_show_x_labels(self, i_result):
        hidden = i_result.plot(show_x_labels=False)
        assert hidden.layout.xaxis.showticklabels is False and hidden.layout.xaxis.ticks == ""
        assert i_result.plot().layout.xaxis.ticks == "outside"
        df = pd.DataFrame({"x": list(range(1, 11)) * 2, "y": list(np.arange(10.0)) * 2,
                           "unit": ["A"] * 10 + ["B"] * 10})
        fig = qic(df, x="x", y="y", chart="i", facets="unit").plot(show_x_labels=False)
        assert fig.layout.xaxis.showticklabels is False
        assert fig.layout.xaxis2.showticklabels is False

    def test_text_x_draws_dots_only(self):
        df = pd.DataFrame({"hosp": ["H1", "H2", "H3"], "val": [10, 20, 15]})
        assert qic(df, x="hosp", y="val", chart="i").plot().data[0].mode == "markers"

    def test_labels_replace_text_ticks_and_name_the_hover(self):
        df = pd.DataFrame({"k": ["a", "b", "c"], "v": [1.0, 2.0, 3.0],
                           "name": ["Ann", "Bob", "Cy"], "site": ["E", "W", "E"]})
        fig = qic(df, x="k", y="v", chart="i", label="name", hover="site").plot()
        assert list(fig.layout.xaxis.ticktext) == ["Ann", "Bob", "Cy"]
        assert list(fig.data[0].customdata[0]) == ["Ann", "E"]
        assert "site: %{customdata[1]}" in fig.data[0].hovertemplate

    def test_notes_and_label_signals(self):
        y = [10, 11, 9, 10, 30, 10, 11, 9, 10, 10]
        r = qic(y=y, chart="i", notes=["", "", "", "", "audit", "", "", "", "", ""])
        assert [a.text for a in _signal_annotations(r.plot(label_signals="outlier"))] == ["5 — audit"]
        assert not any(a.text == "audit" for a in r.plot(label_signals="outlier").layout.annotations)
        assert any(a.text == "audit" for a in r.plot().layout.annotations)
        with pytest.raises(ValueError, match="alert tier"):
            r.plot(label_signals="alert")

    def test_part_boundaries_are_drawn_and_named(self):
        df = pd.DataFrame({"v": np.arange(10.0), "phase": ["Before"] * 5 + ["After"] * 5})
        fig = qic(df, y="v", chart="i", part="phase").plot()
        assert any(s.type == "line" for s in fig.layout.shapes)
        assert any(a.text == "After" for a in fig.layout.annotations)

    def test_part_boundary_on_a_text_x_axis(self):
        # Dates read from a CSV are text; plotly's add_vline label crashed on them.
        months = [f"2024-{m:02d}-01" for m in range(1, 11)]
        df = pd.DataFrame({"month": months, "v": np.arange(10.0),
                           "phase": ["Before"] * 5 + ["After"] * 5})
        fig = qic(df, x="month", y="v", chart="i", part="phase").plot()
        assert any(a.text == "After" and a.x == "2024-06-01" for a in fig.layout.annotations)

    def test_target_line(self):
        fig = qic(y=np.arange(10.0), chart="i", target=4.5).plot()
        assert list(_trace(fig, "Target").y) == [4.5] * 10


class TestMakingDataCount:
    """method="nhs" colours each special cause by direction, as NHS boards read them."""

    Y = [50.0] * 3 + [52, 49, 51, 50, 48, 51, 49, 50, 52] + [30, 29, 31, 30, 29, 31, 30]

    def test_improving_and_concerning_take_mdc_colours(self):
        down_is_good = qic(y=self.Y, chart="i", method="nhs", worse="higher")
        up_is_good = qic(y=self.Y, chart="i", method="nhs", worse="lower")
        assert IMPROVING in _colors(down_is_good.plot())
        assert CONCERNING in _colors(up_is_good.plot())
        assert down_is_good.summary["variation"] == "improving"
        assert up_is_good.summary["variation"] == "concerning"

    def test_legend_names_the_reading(self):
        fig = qic(y=self.Y, chart="i", method="nhs", worse="higher").plot(show_legend=True)
        assert _trace(fig, "Improving") is not None

    def test_special_cause_is_in_the_hover(self):
        r = qic(y=self.Y, chart="i", method="nhs", worse="higher")
        assert r.plot().data[0].customdata[-1][-1] == r.summary["special_cause"]


# ---------------------------------------------------------------------------
# Funnels
# ---------------------------------------------------------------------------

Y = [9, 6, 7, 11, 13, 17, 37, 29, 66, 40]
E = [4.0, 6.0, 8.0, 10.0, 14.0, 18.0, 24.0, 30.0, 40.0, 55.0]
NAMES = [f"Dr {c}" for c in "ABCDEFGHIJ"]


def _oe(**kw):
    args = dict(y=Y, n=E, measure="oe", center=1.0, overdispersion=False)
    args.update(kw)
    return funnel(**args)


class TestFunnelBasics:
    def test_contours_are_named_by_probability(self):
        fig = _oe().plot(show_legend=False)
        assert [t.name for t in fig.data] == ["data", "CL", "99.8%+", "99.8%-", "95%+", "95%-"]
        assert not any(t.name in ("UCL", "2σ+") for t in fig.data)

    def test_end_labels_are_off_by_default_and_named_by_probability(self):
        assert _end_labels(_oe().plot()) == []
        labels = _end_labels(_oe().plot(show_labels=True))
        assert any(t.startswith("99.8%+=") for t in labels)

    def test_tiers_take_their_colours(self):
        r = _oe()
        colors = _colors(r.plot())
        assert [c for c, s in zip(colors, r.data["signal"]) if s == "alert"] == [RUNS] * 3
        assert [c for c, s in zip(colors, r.data["signal"]) if s == "outlier"] == [SIGMA]

    def test_one_sided_leaves_the_other_side_plain(self):
        y = [20, 19, 45, 4, 31, 10, 21, 18, 22, 20]
        r = funnel(y=y, n=[20.0 + i * 1e-3 for i in range(10)], measure="oe", center=1.0,
                   overdispersion=False, worse="higher")
        fig = r.plot(label_signals="both")
        colors = _colors(fig)
        assert colors[2] == SIGMA and colors[3] == NORMAL
        assert len(_signal_annotations(fig)) == 2

    @pytest.mark.parametrize("mode,count", [("outlier", 1), ("alert", 3), ("both", 4)])
    def test_label_signals(self, mode, count):
        assert len(_signal_annotations(_oe().plot(label_signals=mode))) == count

    def test_labels_use_names_and_tier_colour(self):
        anns = {a.text: a for a in _signal_annotations(_oe(label=NAMES).plot(label_signals="both"))}
        assert set(anns) == {"Dr A", "Dr G", "Dr I", "Dr J"}
        assert anns["Dr I"].font.color == SIGMA and anns["Dr A"].font.color == RUNS
        assert anns["Dr A"].ay < 0 and anns["Dr J"].ay > 0

    def test_offsets_stagger_neighbours_and_reset_after_a_gap(self):
        offs = _signal_label_offsets([0, 1, 2, 3, 10], [True] * 5, min_gap=1)
        assert [ay for _, ay in offs] == [-22, -38, -54, -22, -22]
        assert offs[1][0] != offs[2][0]
        assert [ay for _, ay in _signal_label_offsets([0, 2, 5], [True] * 3, 2)] == [-22, -38, -22]
        assert _signal_label_offsets([0, 1], [True, False], 5) == [(0, -22), (0, 22)]


class TestFunnelHover:
    def test_counts_then_interval_then_detectability_then_p(self):
        r = funnel(y=[12, 8, 3, 20], n=[5.0, 3.2, 4.1, 12.0], measure="oe", overdispersion=False)
        trace = r.plot().data[0]
        tpl = trace.hovertemplate
        assert tpl.index("95% CI") < tpl.index("Smallest detectable O/E") < tpl.index("p = ")
        first = trace.customdata[0]
        assert first[1] == "8 observed / 3.2 expected"
        assert " (two-sided), q = " in first[4]

    def test_proportions_name_their_cases(self):
        r = funnel(y=[8, 15, 9], n=[45, 120, 80], measure="proportion")
        assert r.plot().data[0].customdata[0][1] == "8 events / 45.0 cases"

    def test_hover_columns_follow(self):
        df = pd.DataFrame({"u": list("abc"), "o": [3, 5, 7], "e": [2.0, 4.0, 6.0],
                           "practice": ["East", "West", "East"]})
        fig = funnel(df, y="o", n="e", unit="u", measure="oe", hover="practice").plot()
        assert fig.data[0].customdata[0][-1] == "East"
        assert "practice: %{customdata[5]}" in fig.data[0].hovertemplate


class TestFunnelCaptions:
    """A screenshot carries no summary keys, so the figure states its own rule and caveats."""

    def test_limits_rule(self):
        (cap,) = _captions(_oe(worse="higher").plot())
        assert cap.startswith("Outlier: beyond the 99.8% limit (exact test, one-sided, above the "
                              "center line, p < 0.001); alert: beyond the 95% limit (p < 0.025).")

    def test_levels_follow_the_setting(self):
        (cap,) = _captions(_oe(limits=(0.997, 0.95)).plot())
        assert cap.startswith("Outlier: beyond the 99.7% limit (exact test, two-sided, p < 0.003)")

    def test_fdr_rule_names_its_scope(self):
        (cap,) = _captions(_oe(signal="fdr").plot())
        assert cap.startswith("Outlier: q < 0.05; alert: q < 0.1 (Benjamini-Hochberg false "
                              "discovery rate across 10 providers, two-sided p-values).")
        assert "not adjusted for multiple comparisons" in cap
        df = pd.DataFrame({"o": Y * 2, "e": E * 2, "site": ["A"] * 10 + ["B"] * 10})
        fig = funnel(df, y="o", n="e", measure="oe", facets="site", signal="fdr").plot()
        assert any("within each panel" in c for c in _captions(fig))

    def test_underpowered_warning_is_never_dropped(self):
        r = funnel(y=[12, 8, 8, 3, 20, 14], n=[5.0, 3.2, 6.5, 4.1, 12.0, 15.5], measure="oe")
        (cap,) = _captions(r.plot())
        assert cap.endswith("not evidence of acceptable performance.")
        (mine,) = _captions(r.plot(caption="Source: Vizient Q4 2025"))
        assert mine.startswith("Source: Vizient Q4 2025") and "not evidence" in mine
        assert "Outlier:" not in mine

    def test_well_powered_has_no_warning(self):
        fig = funnel(y=[400, 420, 380, 410], n=[400.0, 410, 390, 405], measure="oe").plot()
        assert not any("not evidence" in c for c in _captions(fig))

    def test_long_captions_wrap(self):
        fig = _oe(signal="fdr").plot(width=500)
        (ann,) = [a for a in fig.layout.annotations if a.yref == "paper"]
        assert all(len(line) <= 80 for line in ann.text.split("<br>"))


class TestVolumeAxis:
    PY = [8, 15, 9, 33, 6, 20, 41, 12]
    PN = [45, 120, 80, 260, 55, 150, 300, 70]

    def _p(self, **kw):
        return funnel(y=self.PY, n=self.PN, unit=[f"Clinic {c}" for c in "ABCDEFGH"],
                      measure="proportion", **kw)

    def test_points_sit_at_their_denominator(self):
        r = self._p()
        fig = r.plot()
        assert list(fig.data[0].x) == sorted(self.PN)
        assert fig.layout.xaxis.type == "linear" and fig.layout.hovermode == "closest"

    def test_contours_pass_through_each_points_limit(self):
        r = self._p()
        fig = r.plot()
        assert len(_trace(fig, "99.8%+").x) == len(r.limits()) > len(self.PN)
        for name, col in [("99.8%+", "upper_outlier"), ("99.8%-", "lower_outlier"),
                          ("95%+", "upper_alert")]:
            at = dict(zip(_trace(fig, name).x, _trace(fig, name).y))
            for n_i, lim in zip(r.data["denominator"], r.data[col]):
                assert at[n_i] == lim

    def test_axis_title_defaults(self):
        df = pd.DataFrame({"site": list("abcdef"), "d": [3, 7, 4, 15, 9, 11],
                           "e": [2.5, 4.0, 6.1, 8.0, 12.0, 14.0]})
        assert funnel(df, y="d", n="e", unit="site", measure="oe").plot().layout.xaxis.title.text == "e"
        for measure, title in (("oe", "Expected"), ("proportion", "Cases"), ("rate", "Exposure")):
            fig = funnel(y=self.PY, n=self.PN, measure=measure).plot()
            assert fig.layout.xaxis.title.text == title
        assert self._p().plot(xlab="Patients").layout.xaxis.title.text == "Patients"

    def test_log_axis(self):
        r = _oe(label=NAMES)
        fig = r.plot(x_log=True, label_signals="both", show_labels=True)
        assert fig.layout.xaxis.type == "log"
        assert list(fig.layout.xaxis.tickvals) == [5.0, 10.0, 20.0, 50.0]
        assert list(fig.layout.xaxis.ticktext) == ["5", "10", "20", "50"]
        ends = [a for a in fig.layout.annotations if a.text and a.text.startswith(("CL=", "99.8%"))]
        assert ends and all(a.x == pytest.approx(np.log10(max(E))) for a in ends)
        at = dict(zip(r.data["label"], r.data["denominator"]))
        for a in _signal_annotations(fig):
            assert a.x == pytest.approx(np.log10(at[a.text]))

    @pytest.mark.parametrize("lo,hi,expected", [
        (8.0, 95.0, [10.0, 20.0, 50.0]),
        (40.0, 60.0, [40.0, 50.0, 60.0]),
        (51.0, 55.0, [51.0, 55.0]),
    ])
    def test_log_tick_values(self, lo, hi, expected):
        assert _log_ticks(lo, hi) == pytest.approx(expected)

    def test_equal_denominators_are_drawn_by_unit(self):
        r = funnel(y=[40, 52, 61, 38], n=[400.0] * 4, unit=list("abcd"), measure="oe")
        fig = r.plot()
        assert list(fig.data[0].x) == list("abcd")
        assert fig.layout.xaxis.type == "category"
        with pytest.raises(ValueError, match="x_log"):
            r.plot(x_log=True)

    def test_faceted_volume_axis(self):
        df = pd.DataFrame({"site": ["A"] * 5 + ["B"] * 5,
                           "y": [2, 5, 9, 4, 12, 20, 31, 18, 44, 60],
                           "n": [40, 90, 150, 210, 300, 120, 200, 260, 400, 650]})
        r = funnel(df, y="y", n="n", measure="proportion", facets="site")
        fig = r.plot(x_log=True)
        grid = r.limits()
        ucl = [t for t in fig.data if t.name == "99.8%+"]
        assert len(ucl) == 2
        for t, site in zip(ucl, ["A", "B"]):
            assert list(t.x) == list(grid.loc[grid["site"] == site, "denominator"])
        assert fig.layout.xaxis.type == "log" and fig.layout.xaxis2.type == "log"

    def test_time_ordered_options_are_refused(self):
        with pytest.raises(TypeError, match="drawn against volume"):
            self._p().plot(x_order=["Clinic A"])


class TestStyles:
    @pytest.mark.parametrize("styles,match", [
        ({"limit": {"color": "red"}}, "unknown role"),
        ({"sigma": {"color": "red"}}, "it is 'outlier' now"),
        ({"cl": {"colour": "red"}}, "unknown attribute"),
        ({"outlier": {"width": 2}}, "unknown attribute"),
        ({"ucl_95": {"dash": "dotted"}}, "dash"),
        ({"cl": {"width": 0}}, "positive number"),
        ({"cl": "red"}, "must be a dict"),
    ])
    def test_validation(self, styles, match):
        with pytest.raises(ValueError, match=match):
            _oe().plot(styles=styles)

    def test_group_then_specific(self):
        fig = _oe().plot(styles={
            "limits_95": {"color": "#777", "width": 1.5, "dash": "solid"},
            "limits": {"width": 2}, "ucl": {"color": "#000"},
        })
        for name in ("95%+", "95%-"):
            line = _trace(fig, name).line
            assert (line.color, line.width, line.dash) == ("#777", 1.5, "solid")
        assert (_trace(fig, "99.8%+").line.color, _trace(fig, "99.8%+").line.width) == ("#000", 2)
        assert _trace(fig, "99.8%-").line.width == 2

    def test_a_list_of_styles_merges_in_order(self):
        house = {"limits": {"color": "#555"}}
        fig = _oe().plot(styles=[house, {"ucl": {"color": "#000"}}])
        assert _trace(fig, "99.8%-").line.color == "#555"
        assert _trace(fig, "99.8%+").line.color == "#000"

    def test_invisible_line_and_its_label_go(self):
        fig = _oe().plot(styles={"lcl": {"visible": False}}, show_labels=True)
        assert _trace(fig, "99.8%-") is None
        assert not any(t.startswith("99.8%-=") for t in _end_labels(fig))

    def test_name_renames_trace_and_end_label(self):
        fig = _oe().plot(styles={"ucl": {"name": "Upper 99.8%"}}, show_labels=True)
        assert _trace(fig, "Upper 99.8%") is not None and _trace(fig, "99.8%+") is None
        assert any(t.startswith("Upper 99.8%=") for t in _end_labels(fig))

    def test_point_label_and_line_colours(self):
        fig = _oe().plot(label_signals="outlier", styles={
            "outlier": {"color": "#c00000"}, "alert": {"color": "#ff8800"},
            "data": {"color": "#111111", "width": 2},
        })
        colors = _colors(fig)
        assert "#c00000" in colors and colors.count("#ff8800") == 3 and "#111111" in colors
        assert [a.font.color for a in _signal_annotations(fig)] == ["#c00000"]

    def test_end_label_and_font(self):
        fig = _oe().plot(show_labels=True, styles={"end_labels": {"color": "#222", "size": 14},
                                                   "font": {"family": "Segoe UI"}})
        anns = [a for a in fig.layout.annotations if a.text in _end_labels(fig)]
        assert anns and all(a.font.size == 14 and a.font.color == "#222" for a in anns)
        assert fig.layout.font.family == "Segoe UI"


class TestRanges:
    def test_x_range_with_an_open_end(self):
        lo, hi = _oe().plot(x_range=(10, None)).layout.xaxis.range
        assert lo == 10 and hi > 55

    def test_log_axis_takes_log10(self):
        lo, hi = _oe().plot(x_log=True, x_range=(5, 50)).layout.xaxis.range
        assert (lo, hi) == pytest.approx((np.log10(5), np.log10(50)))

    def test_trimmed_points_no_longer_stretch_y(self):
        r = _oe()
        lo, hi = r.plot(x_range=(10, None)).layout.yaxis.range
        assert 66 / 40 < hi < 9 / 4
        assert lo < r.data["upper_outlier"].iloc[-1] < hi

    def test_y_range_wins_and_can_be_half_open(self):
        assert list(_oe().plot(y_range=(0, 3)).layout.yaxis.range) == [0, 3]
        lo, hi = _oe().plot(y_range=(0, None)).layout.yaxis.range
        assert lo == 0 and hi > 9 / 4

    def test_time_ordered_flip_and_categorical(self):
        r = qic(y=np.arange(10.0), chart="i")
        assert list(r.plot(x_range=(2, 8), flip=True).layout.xaxis.range) == [8, 2]
        cat = qic(x=list("abcdefghij"), y=np.arange(10.0), chart="i")
        with pytest.raises(ValueError, match="categorical"):
            cat.plot(x_range=(1, 3))

    @pytest.mark.parametrize("bad", [(1,), "1,5", (5, 1)])
    def test_bad_ranges(self, bad):
        with pytest.raises(ValueError):
            _oe().plot(x_range=bad)

    def test_faceted_shares_x_and_fits_each_panel(self):
        df = pd.DataFrame({"o": Y * 2, "e": E * 2, "site": ["A"] * 10 + ["B"] * 10})
        fig = funnel(df, y="o", n="e", measure="oe", center=1.0, overdispersion=False,
                     facets="site").plot(x_range=(10, None))
        assert fig.layout.xaxis.range[0] == 10 and fig.layout.xaxis2.range[0] == 10
        assert fig.layout.yaxis.range[1] < 9 / 4


class TestLegend:
    def test_qic_has_none_by_default_and_names_its_signals(self):
        assert qic(y=[10.0] * 29 + [40.0], chart="i").plot().layout.showlegend is False
        fig = qic(y=[10.0] * 29 + [40.0], chart="i").plot(show_legend=True)
        assert _trace(fig, "Beyond UCL/LCL") is not None
        assert fig.layout.legend.orientation == "h"

    def test_funnel_pairs_share_an_entry_and_tiers_get_one(self):
        fig = _oe().plot()
        assert fig.layout.showlegend is True
        upper, lower = _trace(fig, "99.8%+"), _trace(fig, "99.8%-")
        assert upper.legendgroup == lower.legendgroup == "limits"
        assert upper.showlegend is False and lower.showlegend is False
        entry = _trace(fig, "99.8% limits")
        assert entry.x == (None,) and entry.legendgroup == "limits" and entry.showlegend
        assert _trace(fig, "95% limits").line.dash == "dash"
        assert _trace(fig, "Outlier (beyond 99.8%)") is not None
        assert _trace(fig, "Alert (beyond 95%)") is not None
        provider = _trace(fig, "Provider")
        assert provider.legendgroup == "data" and provider.marker.color == NORMAL
        assert _trace(fig, "Center line").legendgroup == "cl"
        assert fig.layout.legend.orientation == "v" and fig.layout.legend.x > 1

    def test_entries_follow_the_rule_and_styles(self):
        fdr = _oe(signal="fdr", fdr_levels=(0.2, 0.3), worse="higher").plot()
        assert _trace(fdr, "Worse than expected: outlier (q < 0.2)") is not None
        worse = _oe(worse="higher").plot()
        assert _trace(worse, "Worse than expected: outlier (beyond 99.8%)") is not None
        named = _oe().plot(styles={"outlier": {"name": "Outlier"}})
        assert _trace(named, "Outlier") is not None

    def test_no_signal_entry_without_signals(self):
        fig = funnel(y=[400, 410, 390, 405], n=[400.0, 410, 390, 405], measure="oe").plot()
        assert _trace(fig, "Outlier (beyond 99.8%)") is None

    def test_faceted_entries_come_from_one_panel(self):
        df = pd.DataFrame({"o": Y * 2, "e": E * 2, "site": ["A"] * 10 + ["B"] * 10})
        fig = funnel(df, y="o", n="e", measure="oe", facets="site").plot()
        assert sum(1 for t in fig.data if t.name == "Center line" and t.showlegend) == 1
        assert sum(1 for t in fig.data if t.name == "Provider" and t.showlegend) == 1


class TestOtherCharts:
    def test_pareto_and_bchart_draw(self):
        from qikit import bchart, paretochart

        pareto = paretochart(["a", "b", "a", "c", "a", "b"]).plot(title="Causes")
        assert pareto.data[0].type == "bar" and "Causes" in pareto.layout.title.text
        cusum = bchart([0, 0, 1, 0, 1, 1, 1, 0, 1, 1], target=0.1).plot()
        assert [t.name for t in cusum.data][:2] == ["CUSUM up", "CUSUM down"]
