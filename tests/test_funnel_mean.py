"""measure="mean": a per-case amount (minutes, cost) averaged per provider (methods §4.19)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from qikit import funnel

KW = {"unit": "p", "worse": "higher", "signal": "fdr"}
# Same model, same units: everything but the echoed numerator and its excesses.
_SCALE_FREE = ["y", "cl", "lower_outlier", "upper_outlier", "lower_alert", "upper_alert",
               "p_value", "q_value", "min_detectable", "ci_lower", "ci_upper",
               "p_value_drop1"]
# The estimate columns rest on the ML τ̂, found by a numerical search whose optimum is
# flat to about 1e-6 relative: equivalent inputs agree to that, not to rounding.
_ESTIMATES = ["reliability", "eb_rate", "eb_low", "eb_high", "prob_worse"]


@pytest.fixture(scope="module")
def cases() -> pd.DataFrame:
    rng = np.random.default_rng(1)
    k = 150
    prov = np.repeat(np.arange(k), rng.integers(5, 400, k))
    effect = rng.normal(0, 0.1, k)
    minutes = rng.gamma(2.0, 15 * np.exp(effect[prov]) / 2)
    minutes[rng.random(len(minutes)) < 0.002] *= 20
    return pd.DataFrame({"p": prov, "minutes": minutes})


@pytest.fixture(scope="module")
def totals(cases) -> pd.DataFrame:
    return cases.groupby("p").agg(
        total=("minutes", "sum"), n=("minutes", "size"),
        ss=("minutes", lambda v: float((v ** 2).sum())), worst=("minutes", "max"),
    ).reset_index()


def _close(a: pd.DataFrame, b: pd.DataFrame, cols, rtol=1e-12):
    for c in cols:
        np.testing.assert_allclose(a[c].to_numpy(float), b[c].to_numpy(float),
                                   rtol=rtol, atol=1e-12, equal_nan=True, err_msg=c)
    assert (a["signal"] == b["signal"]).all()


def test_equals_oe_ratio_workaround(cases):
    """The construction users validated: case / pooled mean as O/E, multiplied back."""
    mu = cases["minutes"].mean()
    ratio = cases.assign(r=cases["minutes"] / mu, one=1.0)
    a = funnel(cases, y="minutes", measure="mean", **KW)
    b = funnel(ratio, y="r", n="one", measure="oe", within_dispersion="estimate",
               multiply=mu, **KW)
    _close(a.data, b.data, _SCALE_FREE)
    _close(a.data, b.data, _ESTIMATES, rtol=1e-5)


def test_equals_rate_with_estimated_phi(cases):
    a = funnel(cases, y="minutes", measure="mean", **KW)
    b = funnel(cases.assign(one=1.0), y="minutes", n="one", measure="rate",
               within_dispersion="estimate", **KW)
    _close(a.data, b.data, [*_SCALE_FREE, "numerator", "raw_excess", "eb_excess"])


def test_sql_totals_match_case_rows(cases, totals):
    a = funnel(cases, y="minutes", measure="mean", **KW)
    b = funnel(totals, y="total", n="n", sum_sq="ss", max_case_y="worst", measure="mean", **KW)
    _close(a.data, b.data, [*_SCALE_FREE, "numerator", "denominator", "raw_excess"])
    # SQL knows only the worst case: the same drop-one answer; fragility is rows-only.
    survives = a.data["flag_survives_drop1"].astype(object).fillna("na")
    assert (survives == b.data["flag_survives_drop1"].astype(object).fillna("na")).all()
    assert a.summary["within_dispersion"] == pytest.approx(b.summary["within_dispersion"])


def test_scale_equivariant(cases):
    """Minutes or hours: the same flags and p-values, limits in each unit."""
    a = funnel(cases, y="minutes", measure="mean", **KW)
    b = funnel(cases.assign(hours=cases["minutes"] / 60), y="hours", measure="mean", **KW)
    _close(a.data, b.data, ["p_value", "q_value"], rtol=1e-9)
    _close(a.data, b.data, ["reliability", "prob_worse"], rtol=1e-5)
    np.testing.assert_allclose(a.data["upper_outlier"], 60 * b.data["upper_outlier"], rtol=1e-9)
    assert a.summary["case_sd"] == pytest.approx(60 * b.summary["case_sd"])


def test_summary_in_original_units(cases):
    r = funnel(cases, y="minutes", measure="mean", **KW)
    assert r.summary["center"] == pytest.approx(cases["minutes"].mean())
    assert r.summary["within_dispersion_source"] == "estimated"
    # √(φ·center) is the pooled within-provider SD of one case.
    within_sd = np.sqrt(cases.groupby("p")["minutes"].var(ddof=1).mul(
        cases.groupby("p").size() - 1).sum() / (len(cases) - cases["p"].nunique()))
    assert r.summary["case_sd"] == pytest.approx(within_sd, rel=0.1)
    assert "one case varies with SD" in str(r)
    assert not any("below 1" in n for n in r.summary["notes"])


def test_case_sd_below_one_no_poisson_note():
    """Amounts in small units give φ < 1 (here hours); no Poisson note for a mean."""
    rng = np.random.default_rng(3)
    df = pd.DataFrame({"p": np.repeat(np.arange(40), 30),
                       "h": rng.gamma(20.0, 0.01, 1200)})
    r = funnel(df, y="h", measure="mean", unit="p")
    assert r.summary["within_dispersion"] < 1
    assert not any("Poisson" in n for n in r.summary["notes"])


def test_options_run(cases):
    df = cases.assign(line=np.where(cases["p"] % 2 == 0, "a", "b"))
    r = funnel(df, y="minutes", measure="mean", facets="line", tau_method="ml",
               benchmark="eb", multiply=1 / 60, **KW)
    assert set(r.summary["by_facet"]) == {"a", "b"}
    assert np.all(r.data["y"] < 2)  # hours
    assert r.data["benchmark"].notna().all()


def test_fdr_floor_counts_cases(cases):
    r = funnel(cases, y="minutes", measure="mean", fdr_min_denominator=50, **KW)
    small = r.data["denominator"] < 50
    assert r.data.loc[small, "q_value"].isna().all()
    assert r.data.loc[~small, "q_value"].notna().all()


@pytest.mark.parametrize("kwargs, match", [
    ({"within_dispersion": 2.0}, "cannot be supplied"),
    ({"max_case_y": "minutes", "max_case_n": "minutes"}, "max_case_y= alone"),
    ({"cases": "p"}, "cases= is implied"),
])
def test_rejects_scalar_settings(cases, kwargs, match):
    with pytest.raises(ValueError, match=match):
        funnel(cases, y="minutes", measure="mean", unit="p", **kwargs)


def test_rejects_negative_amounts(cases):
    with pytest.raises(ValueError, match="0 or more"):
        funnel(cases.assign(d=cases["minutes"] - 30), y="d", measure="mean", unit="p")


def test_provider_rows_need_sum_sq(totals):
    with pytest.raises(ValueError, match="sum_sq"):
        funnel(totals, y="total", n="n", measure="mean", unit="p")


def test_sum_sq_needs_n(totals):
    with pytest.raises(ValueError, match="needs n="):
        funnel(totals, y="total", sum_sq="ss", measure="mean", unit="p")


def test_other_measures_still_need_n(cases):
    with pytest.raises(ValueError, match="n= is required"):
        funnel(cases, y="minutes", measure="rate", unit="p")


def test_plot_labels(cases, totals):
    fig = funnel(cases, y="minutes", measure="mean", **KW).plot()
    assert fig.layout.xaxis.title.text == "Cases"
    assert fig.layout.yaxis.title.text == "Mean minutes"
    templates = " ".join(t.hovertemplate or "" for t in fig.data)
    assert "Smallest detectable mean" in templates
    hover = " ".join(str(c) for t in fig.data if t.customdata is not None for c in t.customdata[0])
    assert "total" in hover and "cases" in hover
    fig = funnel(totals, y="total", n="n", sum_sq="ss", measure="mean", unit="p").plot()
    assert fig.layout.xaxis.title.text == "n"
    assert fig.layout.yaxis.title.text == "Mean total"
