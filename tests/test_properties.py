"""
Property-based tests (Hypothesis): rules qic() and funnel() must obey for any valid
input, not just the examples written by hand elsewhere. Each test states one rule;
Hypothesis generates inputs, and on a failure shrinks to the smallest one that breaks it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, assume, example, given, settings
from hypothesis import strategies as st

from qikit import funnel, qic

# Numerical code with optional SciPy-free special functions: no per-example deadline.
PROPS = settings(max_examples=60, deadline=None,
                 suppress_health_check=[HealthCheck.too_slow])

LIMIT_CHARTS = ["i", "mr", "c", "p", "u", "pp", "up", "g", "t"]
TOL = dict(rel=1e-9, abs=1e-9)


# ---- strategies -------------------------------------------------------------------

def _measurements(min_size=2, max_size=40):
    # Tenths between -500 and 500: real-looking values, no float-overflow noise.
    return st.lists(st.integers(-5000, 5000).map(lambda v: v / 10),
                    min_size=min_size, max_size=max_size)


def _counts(min_size=2, max_size=40, hi=60):
    return st.lists(st.integers(0, hi), min_size=min_size, max_size=max_size)


@st.composite
def _proportions(draw, min_size=2, max_size=40):
    """(y, n) with 0 <= y <= n and n >= 1."""
    n = draw(st.lists(st.integers(1, 400), min_size=min_size, max_size=max_size))
    y = [draw(st.integers(0, k)) for k in n]
    return y, n


@st.composite
def _rates(draw, min_size=2, max_size=40):
    """(y, n) with y >= 0 counts and n > 0 exposures."""
    k = draw(st.integers(min_size, max_size))
    n = draw(st.lists(st.integers(1, 2000).map(lambda v: v / 4), min_size=k, max_size=k))
    y = draw(st.lists(st.integers(0, 80), min_size=k, max_size=k))
    return y, n


@st.composite
def _chart_input(draw):
    """A chart and y (and n) that chart accepts."""
    chart = draw(st.sampled_from(LIMIT_CHARTS))
    if chart in ("p", "pp"):
        y, n = draw(_proportions(min_size=3))
        return chart, y, n
    if chart in ("u", "up"):
        y, n = draw(_rates(min_size=3))
        return chart, y, n
    if chart in ("c", "g"):
        return chart, draw(_counts(min_size=3)), None
    if chart == "t":
        # Times between events: positive.
        return chart, draw(st.lists(st.integers(1, 5000).map(lambda v: v / 10),
                                    min_size=3, max_size=40)), None
    return chart, draw(_measurements(min_size=3)), None


def _qic(chart, y, n=None, **kw):
    return qic(y=y, n=n, chart=chart, **kw)


def _cols(r, *names):
    return [r.data[c].to_numpy(dtype=float) for c in names]


# ---- qic(): limits ----------------------------------------------------------------

@PROPS
@given(_chart_input())
def test_limits_nest_around_the_center_line(case):
    """lcl <= lcl_95 <= cl <= ucl_95 <= ucl wherever they are defined."""
    chart, y, n = case
    r = _qic(chart, y, n)
    lcl, lcl95, cl, ucl95, ucl = _cols(r, "lcl", "lcl_95", "cl", "ucl_95", "ucl")
    eps = 1e-9 * (1 + np.nanmax(np.abs(np.r_[cl, 0.0])))
    for lo, hi in ((lcl, lcl95), (lcl95, cl), (cl, ucl95), (ucl95, ucl)):
        ok = np.isnan(lo) | np.isnan(hi) | (lo <= hi + eps)
        assert ok.all(), (chart, y, n)


@PROPS
@given(_chart_input())
def test_one_row_per_input_value(case):
    chart, y, n = case
    assert len(_qic(chart, y, n).data) == len(y)


@PROPS
@given(st.sampled_from(["c", "u", "g", "p", "t"]), st.data())
def test_count_and_rate_limits_never_go_below_zero(chart, data):
    if chart == "p":
        y, n = data.draw(_proportions(min_size=3))
    elif chart == "u":
        y, n = data.draw(_rates(min_size=3))
    elif chart == "t":
        y, n = data.draw(st.lists(st.integers(1, 5000).map(lambda v: v / 10),
                                  min_size=3, max_size=40)), None
    else:
        y, n = data.draw(_counts(min_size=3)), None
    lcl, lcl95 = _cols(_qic(chart, y, n), "lcl", "lcl_95")
    assert np.all(np.isnan(lcl) | (lcl >= 0)) and np.all(np.isnan(lcl95) | (lcl95 >= 0))


@PROPS
@given(_proportions(min_size=3))
def test_p_chart_limits_stay_within_zero_and_one(yn):
    y, n = yn
    lcl, ucl, ucl95 = _cols(_qic("p", y, n), "lcl", "ucl", "ucl_95")
    assert np.all(np.isnan(ucl) | (ucl <= 1)) and np.all(np.isnan(ucl95) | (ucl95 <= 1))
    assert np.all(np.isnan(lcl) | (lcl >= 0))


# ---- qic(): invariances -----------------------------------------------------------

@PROPS
@given(_measurements(min_size=3), st.integers(-1000, 1000), st.integers(1, 50))
def test_i_chart_follows_a_change_of_units(y, shift, scale):
    """y -> a + b*y (b > 0) moves cl and the limits the same way and keeps every signal."""
    a, b = shift / 10, scale / 10
    r0 = _qic("i", y)
    r1 = _qic("i", [a + b * v for v in y])
    for col in ("cl", "ucl", "lcl", "ucl_95", "lcl_95"):
        np.testing.assert_allclose(r1.data[col], a + b * r0.data[col].to_numpy(dtype=float),
                                   rtol=1e-9, atol=1e-6)
    _assume_off_boundaries(r0, "i")
    assert list(r1.data["signal"]) == list(r0.data["signal"])
    assert list(r1.data["runs_signal"]) == list(r0.data["runs_signal"])


@PROPS
@given(_measurements(min_size=3))
def test_i_chart_mirrors_when_y_is_negated(y):
    """y -> -y swaps the limits (ucl -> -lcl) and keeps every signal."""
    r0 = _qic("i", y)
    r1 = _qic("i", [-v for v in y])
    np.testing.assert_allclose(r1.data["ucl"], -r0.data["lcl"].to_numpy(dtype=float), atol=1e-9)
    np.testing.assert_allclose(r1.data["cl"], -r0.data["cl"].to_numpy(dtype=float), atol=1e-9)
    _assume_off_boundaries(r0, "i")
    assert list(r1.data["signal"]) == list(r0.data["signal"])
    assert list(r1.data["runs_signal"]) == list(r0.data["runs_signal"])


@PROPS
@given(st.lists(st.integers(1, 1000), min_size=3, max_size=40, unique=True))
def test_run_chart_signals_ignore_any_increasing_transform(y):
    """The run chart's center is the median and its rules count runs about it, so any
    strictly increasing transform of y (here log) leaves every signal unchanged."""
    r0 = _qic("run", y)
    r1 = _qic("run", [float(np.log(v)) for v in y])
    assert list(r1.data["runs_signal"]) == list(r0.data["runs_signal"])
    assert r1.summary["longest_run"] == r0.summary["longest_run"]
    assert r1.summary["n_crossings"] == r0.summary["n_crossings"]


@PROPS
@given(st.sampled_from(["p", "u"]), st.data(), st.integers(2, 10))
def test_more_of_the_same_rate_narrows_the_limits(chart, data, k):
    """Multiplying every numerator and denominator by k keeps each rate and the center
    line, and narrows each half-width by sqrt(k)."""
    y, n = data.draw(_proportions(min_size=3) if chart == "p" else _rates(min_size=3))
    r0 = _qic(chart, y, n)
    rk = _qic(chart, [v * k for v in y], [v * k for v in n])
    y0, cl0, ucl0 = _cols(r0, "y", "cl", "ucl")
    yk, clk, uclk = _cols(rk, "y", "cl", "ucl")
    np.testing.assert_allclose(yk, y0, rtol=1e-12)
    np.testing.assert_allclose(clk, cl0, rtol=1e-12)
    # The p chart's ucl is capped at 1, so compare only uncapped half-widths.
    keep = ~np.isnan(ucl0) & (ucl0 < 1)
    np.testing.assert_allclose((uclk - clk)[keep], (ucl0 - cl0)[keep] / np.sqrt(k),
                               rtol=1e-9, atol=1e-12)


@PROPS
@given(st.sampled_from(["p", "u", "c", "i"]), st.data(), st.integers(1, 1000))
def test_multiply_scales_the_chart_and_nothing_else(chart, data, m):
    if chart == "p":
        y, n = data.draw(_proportions(min_size=3))
    elif chart == "u":
        y, n = data.draw(_rates(min_size=3))
    elif chart == "c":
        y, n = data.draw(_counts(min_size=3)), None
    else:
        y, n = data.draw(_measurements(min_size=3)), None
    r0 = _qic(chart, y, n)
    rm = _qic(chart, y, n, multiply=m)
    for col in ("y", "cl", "ucl", "lcl", "ucl_95", "lcl_95"):
        np.testing.assert_allclose(rm.data[col], m * r0.data[col].to_numpy(dtype=float),
                                   rtol=1e-9, atol=1e-9)
    assert list(rm.data["signal"]) == list(r0.data["signal"])
    assert list(rm.data["runs_signal"]) == list(r0.data["runs_signal"])


# ---- qic(): baseline, exclude, freeze, part ---------------------------------------

@PROPS
@given(_counts(min_size=4), st.data())
def test_c_chart_center_line_skips_excluded_points(y, data):
    idx = data.draw(st.lists(st.integers(1, len(y)), min_size=1, max_size=len(y) - 1,
                             unique=True))
    r = _qic("c", y, exclude=idx)
    kept = [v for i, v in enumerate(y, start=1) if i not in idx]
    assert r.data["cl"].iloc[0] == pytest.approx(np.mean(kept), **TOL)
    assert sorted(r.summary["excluded"]) == sorted(idx)
    assert r.data["excluded"].sum() == len(idx)


@PROPS
@given(_measurements(min_size=4), st.data())
def test_freeze_ignores_everything_after_the_baseline(y, data):
    """With freeze=k, the limits come from the first k points only: changing any later
    point leaves cl and the limits where they were."""
    k = data.draw(st.integers(2, len(y) - 1))
    later = data.draw(st.lists(st.integers(-5000, 5000).map(lambda v: v / 10),
                               min_size=len(y) - k, max_size=len(y) - k))
    r0 = _qic("i", y, freeze=k)
    r1 = _qic("i", y[:k] + later, freeze=k)
    for col in ("cl", "ucl", "lcl"):
        np.testing.assert_allclose(r1.data[col], r0.data[col], rtol=1e-12, atol=1e-12)
    assert r0.data["baseline"].sum() == k


@PROPS
@given(st.lists(_counts(min_size=2, max_size=15), min_size=2, max_size=4))
def test_each_part_is_its_own_chart(segments):
    """part= splits the series: each part's c chart equals that segment charted alone."""
    y = [v for seg in segments for v in seg]
    ends = list(np.cumsum([len(s) for s in segments])[:-1])
    r = _qic("c", y, part=ends)
    start = 0
    for seg in segments:
        alone = _qic("c", seg)
        sl = slice(start, start + len(seg))
        for col in ("cl", "ucl", "lcl"):
            np.testing.assert_allclose(r.data[col].to_numpy(dtype=float)[sl],
                                       alone.data[col].to_numpy(dtype=float), rtol=1e-12)
        start += len(seg)


@PROPS
@given(_chart_input())
def test_summary_counts_match_the_rows(case):
    chart, y, n = case
    r = _qic(chart, y, n)
    assert r.summary["n_outlier"] == int((r.data["signal"] == "outlier").sum())
    # n_obs counts plotted values: the MR chart's first row has none.
    assert r.summary["n_obs"] == int(np.isfinite(r.data["y"].to_numpy(dtype=float)).sum())


# ---- funnel() ---------------------------------------------------------------------

MEASURE_INPUTS = {"proportion": _proportions, "rate": _rates}


@st.composite
def _providers(draw, measure=None, min_size=3, max_size=25):
    measure = measure or draw(st.sampled_from(["proportion", "rate", "oe"]))
    if measure == "oe":
        k = draw(st.integers(min_size, max_size))
        y = draw(st.lists(st.integers(0, 80), min_size=k, max_size=k))
        n = draw(st.lists(st.integers(4, 800).map(lambda v: v / 4), min_size=k, max_size=k))
    else:
        y, n = draw(MEASURE_INPUTS[measure](min_size=min_size, max_size=max_size))
    assume(sum(y) > 0)
    units = [f"u{i}" for i in range(len(y))]
    return measure, y, n, units


def _f(measure, y, n, units, **kw):
    return funnel(y=y, n=n, unit=units, measure=measure, **kw)


def _by_unit(r):
    return r.data.set_index("unit").sort_index()


FUNNEL_NUMBERS = ["y", "cl", "lower_outlier", "upper_outlier", "lower_alert",
                  "upper_alert", "p_value"]


@PROPS
@given(_providers(), st.booleans())
@example(("proportion", [0, 0, 1, 2], [1, 105, 24, 2], ["u0", "u1", "u2", "u3"]), True)
def test_funnel_limits_nest_around_the_center_line(case, overdispersion):
    """Outer contours outside the inner ones, in range; around cl without τ²."""
    measure, y, n, units = case
    d = _f(measure, y, n, units, overdispersion=overdispersion).data
    lo, la, cl, ua, uo = (d[c].to_numpy(dtype=float) for c in
                          ("lower_outlier", "lower_alert", "cl", "upper_alert", "upper_outlier"))
    eps = 1e-9 * (1 + np.abs(cl))
    pairs = [(lo, la), (ua, uo)]
    if not overdispersion:
        # Around the center line only without τ²: near the largest spread a proportion
        # can have, the beta-binomial is U-shaped (most providers at 0%, a few at 100%),
        # its 97.5% point is 0 events, and the alert contour rightly sits at 1 event,
        # below cl. CI found [0, 0, 1, 2] of [1, 105, 24, 2].
        pairs += [(la, cl), (cl, ua)]
    for a, b in pairs:
        assert np.all(np.isnan(a) | np.isnan(b) | (a <= b + eps))
    assert np.all(np.isnan(lo) | (lo >= 0))
    if measure == "proportion":
        assert np.all(np.isnan(uo) | (uo <= 1 + 1e-12))


@PROPS
@given(_providers(), st.booleans(), st.randoms(use_true_random=False))
def test_funnel_ignores_the_order_of_providers(case, overdispersion, rnd):
    measure, y, n, units = case
    order = list(range(len(y)))
    rnd.shuffle(order)
    r0 = _f(measure, y, n, units, overdispersion=overdispersion)
    r1 = _f(measure, [y[i] for i in order], [n[i] for i in order],
            [units[i] for i in order], overdispersion=overdispersion)
    a, b = _by_unit(r0), _by_unit(r1)
    for col in FUNNEL_NUMBERS:
        np.testing.assert_allclose(b[col].to_numpy(dtype=float), a[col].to_numpy(dtype=float),
                                   rtol=1e-8, atol=1e-12)
    _assume_funnel_off_boundaries(r0)
    assert list(b["signal"]) == list(a["signal"])
    assert r1.summary["center"] == pytest.approx(r0.summary["center"], rel=1e-12)


@PROPS
@given(_providers(), st.booleans(), st.data())
def test_excluding_a_provider_is_leaving_it_out(case, overdispersion, data):
    """An excluded provider is dropped from the center line, the dispersion and testing:
    every other provider's result is the same as with that provider not in the data."""
    measure, y, n, units = case
    assume(len(y) >= 4)
    k = data.draw(st.integers(0, len(y) - 1))
    rest = [i for i in range(len(y)) if i != k]
    assume(sum(y[i] for i in rest) > 0)
    rx = _f(measure, y, n, units, overdispersion=overdispersion, exclude=[units[k]])
    rw = _f(measure, [y[i] for i in rest], [n[i] for i in rest], [units[i] for i in rest],
            overdispersion=overdispersion)
    a, b = _by_unit(rx), _by_unit(rw)
    assert bool(a.loc[units[k], "excluded"])
    assert a.loc[units[k], "signal"] == "none"
    a = a.drop(index=units[k])
    for col in FUNNEL_NUMBERS:
        np.testing.assert_allclose(a[col].to_numpy(dtype=float), b[col].to_numpy(dtype=float),
                                   rtol=1e-9, atol=1e-12)
    assert list(a["signal"]) == list(b["signal"])


@PROPS
@given(_providers(measure="proportion"), st.data())
def test_a_provider_split_over_rows_is_summed(case, data):
    """Rows sharing a unit are one provider: splitting a provider's counts over two rows
    gives the same funnel as one row with the totals."""
    measure, y, n, units = case
    k = data.draw(st.integers(0, len(y) - 1))
    assume(n[k] >= 2)
    n1 = data.draw(st.integers(1, n[k] - 1))
    y1 = data.draw(st.integers(max(0, y[k] - (n[k] - n1)), min(y[k], n1)))
    ys = y + [y1]
    ns = n + [n1]
    ys[k], ns[k] = y[k] - y1, n[k] - n1
    r0 = _f(measure, y, n, units)
    r1 = _f(measure, ys, ns, units + [units[k]])
    a, b = _by_unit(r0), _by_unit(r1)
    for col in FUNNEL_NUMBERS + ["numerator", "denominator"]:
        np.testing.assert_allclose(b[col].to_numpy(dtype=float), a[col].to_numpy(dtype=float),
                                   rtol=1e-9, atol=1e-12)


@PROPS
@given(_providers(), st.sampled_from(["y", "n", "unit"]))
def test_an_incomplete_row_is_dropped_and_counted(case, missing):
    """A row missing its numerator, denominator or unit leaves the analysis (never as
    zero events) and is counted in n_rows_dropped."""
    measure, y, n, units = case
    extra = {"y": (np.nan, 10.0, "extra"), "n": (3.0, np.nan, "extra"),
             "unit": (3.0, 10.0, None)}[missing]
    df = pd.DataFrame({"y": y + [extra[0]], "n": n + [extra[1]],
                       "unit": units + [extra[2]]})
    r0 = _f(measure, y, n, units)
    r1 = funnel(df, y="y", n="n", unit="unit", measure=measure)
    assert r1.summary["n_rows_dropped"] == 1
    a, b = _by_unit(r0), _by_unit(r1).loc[lambda d: d.index.isin(units)]
    for col in FUNNEL_NUMBERS:
        np.testing.assert_allclose(b[col].to_numpy(dtype=float), a[col].to_numpy(dtype=float),
                                   rtol=1e-12, atol=1e-12)


@PROPS
@given(_providers(measure="proportion"), st.integers(2, 1000))
def test_funnel_multiply_scales_values_not_verdicts(case, m):
    measure, y, n, units = case
    r0 = _f(measure, y, n, units)
    rm = _f(measure, y, n, units, multiply=m)
    a, b = _by_unit(r0), _by_unit(rm)
    for col in ("y", "cl", "lower_outlier", "upper_outlier", "lower_alert", "upper_alert"):
        np.testing.assert_allclose(b[col].to_numpy(dtype=float),
                                   m * a[col].to_numpy(dtype=float), rtol=1e-9, atol=1e-12)
    np.testing.assert_allclose(b["p_value"], a["p_value"], rtol=1e-12)
    assert list(b["signal"]) == list(a["signal"])


@PROPS
@given(_providers(), st.booleans())
def test_funnel_summary_counts_match_the_rows(case, overdispersion):
    measure, y, n, units = case
    r = _f(measure, y, n, units, overdispersion=overdispersion)
    d = r.data
    assert r.summary["n_providers"] == len(set(units))
    assert r.summary["n_outlier"] == int((d["signal"] == "outlier").sum())
    assert r.summary["n_alert"] == int((d["signal"] == "alert").sum())
    flagged = d[d["signal"] != "none"]
    above = flagged["y"] > flagged["cl"]
    assert (flagged.loc[above, "direction"] == "higher").all()
    assert (flagged.loc[~above, "direction"] == "lower").all()


# ---- helpers ----------------------------------------------------------------------

def _assume_off_boundaries(r, chart):
    """Skip examples where a point sits within rounding of a limit or the center line:
    there an exact transform can flip a signal through the last bit, which is not a bug."""
    d = r.data
    y = d["y"].to_numpy(dtype=float)
    scale = 1 + np.nanmax(np.abs(y)) if len(y) else 1
    for col in ("cl", "ucl", "lcl", "ucl_95", "lcl_95"):
        gap = np.abs(y - d[col].to_numpy(dtype=float))
        assume(not np.any(gap < 1e-7 * scale))


def _assume_funnel_off_boundaries(r):
    d = r.data
    y = d["y"].to_numpy(dtype=float)
    for col in ("lower_outlier", "upper_outlier", "lower_alert", "upper_alert"):
        gap = np.abs(y - d[col].to_numpy(dtype=float))
        assume(not np.any(gap < 1e-9 * (1 + np.abs(y))))


# ---- regressions found by the properties ------------------------------------------

def test_beta_quantile_with_a_shape_near_zero_is_fast_and_right():
    """Found by test_funnel_limits_nest_around_the_center_line: Beta(0.0005, 1) put
    beta_tails on its slow continued fraction at x ≈ 0, and a funnel took minutes."""
    import time

    from qikit.core.dist import beta_quantile, beta_tails

    t = time.perf_counter()
    for a in (0.0019, 0.0005, 0.0001):
        # The 2.5% quantile, 0.025 ** (1 / a), is below the smallest double.
        assert beta_quantile(0.025, a, 1.0) == pytest.approx(0.0, abs=1e-300)
        # Beta(a, 1) has P(X <= x) = x ** a exactly.
        lower, upper = beta_tails(1e-6, a, 1.0)
        assert lower == pytest.approx(1e-6 ** a, rel=1e-12)
        assert upper == pytest.approx(1 - 1e-6 ** a, rel=1e-9)
    assert time.perf_counter() - t < 1.0
    # A tail checked against mpmath's betainc (40 digits): 0.0880009071464796768.
    assert beta_tails(0.001965853810069418, 0.21040594650822828, 361.7668580299126)[1] \
        == pytest.approx(0.0880009071464796768, rel=1e-10)


def test_proportion_funnel_limits_stop_at_one():
    """Found by test_funnel_limits_nest_around_the_center_line: providers spread wider
    than any beta distribution allows fall back to the normal limits of eq. 11, whose
    upper contour reached 2.34 for a proportion. It is now capped at 1, as the lower is
    at 0."""
    r = funnel(y=[1, 1, 0], n=[1, 1, 5], unit=["a", "b", "c"], measure="proportion",
               overdispersion=True)
    assert r.summary["limit_method"] == "normal"
    for col in ("upper_outlier", "upper_alert"):
        assert (r.data[col] <= 1.0).all()
