"""Figures for designed experiments: ExperimentResult.plot(chart)."""

from __future__ import annotations

import plotly.graph_objects as go
import pytest

from qikit import design
from qikit.plot.doe import plot_experiment

# Box, Hunter & Hunter's pilot-plant 2^3 example, in Yates order.
PILOT = [60, 72, 54, 68, 52, 83, 45, 80]


@pytest.fixture(scope="module")
def result():
    return design(["A", "B", "C"]).fill(PILOT)


@pytest.mark.parametrize("chart", [
    "effects", "interaction", "cube", "run_order", "timeseries", "dot_diagram",
    "single_factor", "line_effects", "extended_cube",
])
def test_every_chart_draws(result, chart):
    fig = result.plot(chart)
    assert isinstance(fig, go.Figure) and len(fig.data) > 0


def test_effects_is_the_default_and_the_largest_effect_is_on_top(result):
    fig = result.plot()
    points = fig.data[-1]
    assert points.mode == "markers"
    assert list(points.y) == ["B:C", "C", "A:B", "B", "A:C", "A"]      # drawn bottom to top
    assert list(points.x) == [0.0, 1.5, 1.5, 5.0, 10.0, 23.0]
    assert len(fig.data) == 7                                          # a stem per term
    assert fig.layout.title.text == "Pareto Chart of Effects (R²=1.000)"
    assert fig.layout.showlegend is False


def test_interaction_plots_the_cell_means(result):
    fig = result.plot("interaction")
    low, high = fig.data
    assert (low.name, high.name) == ("B Low (-1)", "B High (+1)")
    # Mean yield at A low/high, at each level of B.
    assert (list(low.x), list(low.y)) == ([-1, 1], [56.0, 77.5])
    assert (list(high.x), list(high.y)) == ([-1, 1], [49.5, 74.0])
    assert fig.layout.title.text == "Interaction Plot: A and B"


def test_interaction_takes_the_pair_of_factors(result):
    fig = result.plot("interaction", factors=(0, 2))
    low, high = fig.data
    assert (list(low.y), list(high.y)) == ([57.0, 70.0], [48.5, 81.5])   # the A:C effect of 10
    assert fig.layout.title.text == "Interaction Plot: A and C"
    assert fig.layout.xaxis.title.text == "A"


def test_cube_labels_each_corner_with_its_mean(result):
    fig = result.plot("cube")
    edges, corners = fig.data[:-1], fig.data[-1]
    assert len(edges) == 12 and all(isinstance(t, go.Scatter3d) for t in fig.data)
    at = {(x, y, z): t for x, y, z, t in zip(corners.x, corners.y, corners.z, corners.text)}
    assert at[(-1, -1, -1)] == 60 and at[(1, -1, 1)] == 83 and at[(1, 1, 1)] == 80
    assert len(at) == 8
    assert fig.layout.title.text == "Cube Plot: A, B, C"


def test_cube_averages_over_replicates():
    res = design(["A", "B", "C"], replicates=2).fill(PILOT + [y + 2 for y in PILOT])
    corners = res.plot("cube").data[-1]
    assert sorted(corners.text) == sorted(y + 1 for y in PILOT)


def test_cube_of_two_factors_is_a_square():
    fig = design(["A", "B"]).fill([60, 72, 54, 68]).plot("cube")
    outline, corners = fig.data
    assert list(outline.x) == [-1, 1, 1, -1, -1] and list(outline.y) == [-1, -1, 1, 1, -1]
    assert sorted(zip(corners.x, corners.y, corners.text)) == [
        (-1, -1, 60.0), (-1, 1, 54.0), (1, -1, 72.0), (1, 1, 68.0)]
    assert fig.layout.title.text == "Cube Plot: A, B"
    assert fig.layout.yaxis.scaleanchor == "x"                         # drawn square
    assert not fig.layout.annotations


def test_square_shows_center_points_at_the_center():
    res = design(["A", "B"], center_points=2).fill([60, 72, 54, 68, 63, 64])
    corners = res.plot("cube").data[-1]
    assert (0, 0, 63.5) in set(zip(corners.x, corners.y, corners.text))


def test_cube_of_one_factor_names_the_chart_to_use():
    with pytest.raises(ValueError, match='at least two factors; use chart="single_factor"'):
        design(["A"]).fill([1.0, 2.0]).plot("cube")


def test_line_effects_puts_a_randomized_run_back_in_standard_order():
    d = design(["A", "B", "C"], randomize="full", seed=4)
    coded = d.matrix[["A", "B", "C"]].to_numpy()
    assert coded.tolist() != design(["A", "B", "C"]).matrix[["A", "B", "C"]].to_numpy().tolist()
    # Each run's response is its standard-order position, so the plot must read 1..8.
    position = ((coded[:, 0] + 1) // 2 + (coded[:, 1] + 1) + 2 * (coded[:, 2] + 1) + 1)
    trace = d.fill(position.astype(float)).plot("line_effects").data[0]
    assert list(trace.y) == [1, 2, 3, 4, 5, 6, 7, 8] and list(trace.x) == [1, 2, 3, 4, 5, 6, 7, 8]
    assert sorted(trace.customdata) == [1, 2, 3, 4, 5, 6, 7, 8]        # the run each came from
    assert list(trace.customdata) != [1, 2, 3, 4, 5, 6, 7, 8]


def test_line_effects_keeps_replicates_in_turn_and_center_points_last():
    res = design(["A", "B"], replicates=2, center_points=1).fill([1, 2, 3, 4, 5, 6, 7, 8, 9])
    assert list(res.plot("line_effects").data[0].y) == [1, 5, 2, 6, 3, 7, 4, 8, 9]


def test_line_effects_orders_a_fraction_on_its_base_factors():
    res = design(list("ABC"), design_type="fractional").fill([1, 2, 3, 4])
    assert list(res.plot("line_effects").data[0].y) == [1, 2, 3, 4]


def test_run_order_plots_the_response_as_run(result):
    trace = result.plot("run_order").data[0]
    assert list(trace.x) == list(range(1, 9)) and list(trace.y) == PILOT


def test_timeseries_is_an_individuals_chart_of_the_response(result):
    fig = result.plot("timeseries")
    assert fig.layout.title.text == "Experimental Response Time Series"
    assert any(list(t.y) == PILOT for t in fig.data if t.y is not None)


def test_dot_diagram_shows_every_response(result):
    trace = result.plot("dot_diagram").data[0]
    assert isinstance(trace, go.Box) and trace.boxpoints == "all"
    assert list(trace.x) == PILOT


def test_single_factor_plots_the_main_effect(result):
    first = result.plot("single_factor")
    assert list(first.data[0].y) == [52.75, 75.75]                      # A: effect 23
    assert first.layout.title.text == "Main Effect: A"
    second = result.plot("single_factor", factor=1)
    assert list(second.data[0].y) == [66.75, 61.75]                     # B: effect −5
    assert second.layout.title.text == "Main Effect: B"


def test_line_effects_plots_the_response_in_order(result):
    assert list(result.plot("line_effects").data[0].y) == PILOT


def test_unknown_chart(result):
    with pytest.raises(ValueError, match="Unknown experiment chart type: 'spider'"):
        result.plot("spider")
    with pytest.raises(ValueError, match="Unknown experiment chart type"):
        plot_experiment(result, chart_type="spider")  # type: ignore[arg-type]
