"""
The surface an agent or a pipeline reads: a fixed table shape, a compact brief, one
summary row per facet, choices that forgive case, and signatures that show the choices.
"""

from __future__ import annotations

import datetime as dt
import json
import typing
import warnings
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

import qikit
from qikit import funnel, qic
from qikit.core.dispersion import TAU_METHODS
from qikit.core.rules import METHODS
from qikit.core.shewhart import CHARTS
from qikit.funnel import BENCHMARKS, COMPARE_TO, MEASURES, SIGNALS
from qikit.schema import FUNNEL_COLUMNS, QIC_COLUMNS
from qikit.spc import AGG_FUNS


def _monthly(k=24, seed=1):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "month": pd.date_range("2024-01-01", periods=k, freq="MS"),
        "events": rng.binomial(200, 0.15, k), "cases": 200, "site": "A",
        "phase": ["before"] * (k // 2) + ["after"] * (k - k // 2), "who": "x",
    })


def _providers(k=60, seed=1):
    rng = np.random.default_rng(seed)
    f = pd.DataFrame({"doc": [f"d{i}" for i in range(k)], "exp": rng.gamma(2, 10, k)})
    f["obs"] = rng.poisson(f["exp"] * np.exp(rng.normal(0, 0.3, k))).astype(float)
    f["campus"] = np.where(np.arange(k) % 2, "N", "S")
    return f


def _funnel(data=None, **kw):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return funnel(_providers() if data is None else data,
                      **{"y": "obs", "n": "exp", "measure": "oe", "unit": "doc", **kw})


# ---------------------------------------------------------------------------
# schema() and to_table()
# ---------------------------------------------------------------------------

class TestSchema:
    def test_schema_lists_every_column(self):
        s = qikit.schema("funnel")
        assert list(s.columns) == ["column", "dtype", "always", "meaning"]
        assert s["column"].tolist() == [c.name for c in FUNNEL_COLUMNS]
        assert set(s["dtype"]) <= {"float", "int", "bool", "string", "any"}
        with pytest.raises(ValueError, match="'qic' or 'funnel'"):
            qikit.schema("pareto")

    @pytest.mark.parametrize("fn, columns", [(qic, QIC_COLUMNS), (funnel, FUNNEL_COLUMNS)])
    def test_the_docstring_documents_every_column(self, fn, columns):
        missing = [c.name for c in columns if c.name not in fn.__doc__]
        assert not missing

    def test_always_columns_are_exactly_a_plain_calls_columns(self):
        d = _monthly()
        plain = qic(d, x="month", y="events", chart="run").data
        assert list(plain.columns) == [c.name for c in QIC_COLUMNS if c.always]
        assert list(_funnel().data.columns) == [c.name for c in FUNNEL_COLUMNS if c.always]

    def test_data_never_holds_a_column_outside_the_schema(self):
        d = _monthly()
        r = qic(d, x="month", y="events", n="cases", chart="i", method="nhs", worse="higher",
                target=0.2, label="who", notes="who", part="phase")
        assert set(r.data.columns) == {c.name for c in QIC_COLUMNS}
        f = _providers().assign(phi=1.5)
        r = _funnel(f, label="doc", within_dispersion="phi", benchmark="abc", worse="higher")
        assert set(r.data.columns) == {c.name for c in FUNNEL_COLUMNS}


class TestToTable:
    def test_qic_shape_does_not_depend_on_the_options(self):
        d = _monthly()
        plain = qic(d, x="month", y="events", chart="run").to_table()
        full = qic(d, x="month", y="events", n="cases", chart="i", method="nhs",
                   worse="higher", target=0.2, label="who", notes="who",
                   part="phase").to_table()
        assert list(plain.columns) == list(full.columns) == [c.name for c in QIC_COLUMNS]
        assert dict(plain.dtypes.astype(str)) == dict(full.dtypes.astype(str))
        assert full["part"].tolist()[0] == "before"
        assert plain["target"].isna().all() and plain["label"].isna().all()

    def test_funnel_shape_does_not_depend_on_the_options(self):
        f = _providers().assign(phi=1.5)
        plain = _funnel().to_table()
        full = _funnel(f, label="doc", within_dispersion="phi", benchmark="abc",
                       worse="higher").to_table()
        assert list(plain.columns) == list(full.columns) == [c.name for c in FUNNEL_COLUMNS]
        assert dict(plain.dtypes.astype(str)) == dict(full.dtypes.astype(str))
        assert str(plain["fragility"].dtype) == "Int64"
        assert str(plain["meets_benchmark"].dtype) == "boolean"

    def test_facets_lead_and_hover_trails(self):
        t = _funnel(facets="campus", hover="exp").to_table()
        assert t.columns[0] == "campus" and t.columns[-1] == "exp"
        assert list(t.columns[1:-1]) == [c.name for c in FUNNEL_COLUMNS]
        q = qic(_monthly(), x="month", y="events", facets="site", hover="who").to_table()
        assert q.columns[0] == "site" and q.columns[-1] == "who"

    def test_values_are_those_of_data(self):
        r = _funnel()
        pd.testing.assert_series_equal(r.to_table()["p_value"], r.data["p_value"])
        assert len(r.to_table()) == len(r.data)


# ---------------------------------------------------------------------------
# brief()
# ---------------------------------------------------------------------------

class TestBrief:
    def test_funnel_brief_is_small_and_names_only_the_flagged(self):
        r = _funnel(worse="higher")
        b = r.brief()
        text = json.dumps(b)
        assert len(text) < len(r.to_json()) / 10
        assert b["function"] == "funnel" and b["compare_to"] == "peers"
        assert b["n_flagged"] == r.summary["n_outlier"] + r.summary["n_alert"] > 0
        assert [row["unit"] for row in b["flagged"]] == (
            r.data[r.data.signal != "none"].assign(o=lambda d: d.signal != "outlier")
            .sort_values(["o", "p_value"], kind="stable")["unit"].tolist())
        assert b["notes"] == r.summary["notes"]

    def test_numbers_are_rounded_and_empty_keys_left_out(self):
        row = _funnel(worse="higher").brief(digits=3)["flagged"][0]
        assert row["y"] == float(f"{row['y']:.3g}")
        assert "label" not in row and all(v is not None for v in row.values())

    def test_limit_caps_the_rows_not_the_count(self):
        r = _funnel(overdispersion=False)
        b = r.brief(limit=2)
        assert len(b["flagged"]) == 2 < b["n_flagged"]

    def test_faceted_funnel_brief(self):
        b = _funnel(facets="campus").brief()
        assert set(b["facets"]) == {"N", "S"}
        assert {"n_providers", "n_outlier", "n_alert", "center", "tau"} <= set(b["facets"]["N"])
        assert all("campus" in row for row in b["flagged"])
        json.dumps(b)

    def test_qic_brief(self):
        rng = np.random.default_rng(0)
        y = np.concatenate([rng.normal(10, 1, 20), rng.normal(16, 1, 4)])
        b = qic(y=y, chart="i").brief()
        assert b["function"] == "qic" and b["signals"] is True and b["provisional"] is False
        assert b["n_outlier"] >= 1 and b["n_flagged"] == len(b["flagged"]) >= b["n_outlier"]
        assert set(b["flagged"][0]) >= {"x", "y", "cl", "ucl", "lcl", "signal", "runs_signal"}
        quiet = qic(y=np.tile([9.5, 10.5, 10.0], 8), chart="i").brief()
        assert quiet["flagged"] == [] and quiet["signals"] is False

    def test_qic_brief_keeps_the_most_recent_and_reports_facets(self):
        d = _monthly()
        two = pd.concat([d, d.assign(site="B", events=d["events"] + np.arange(24) * 3)])
        b = qic(two, x="month", y="events", n="cases", chart="p", facets="site").brief(limit=3)
        assert set(b["facets"]) == {"A", "B"} and b["facets"]["B"]["signals"] is True
        assert len(b["flagged"]) == 3 and b["flagged"][-1]["x"].startswith("2025-12")
        json.dumps(b)


# ---------------------------------------------------------------------------
# to_dict(digits=), JSON safety, facet_summary()
# ---------------------------------------------------------------------------

class TestSerialize:
    def test_digits_shrinks_the_payload_without_changing_the_default(self):
        r = _funnel()
        assert len(r.to_json(digits=4)) < len(r.to_json())
        assert r.to_dict()["data"][0]["y"] == r.data["y"].iloc[0]
        y = r.to_dict(digits=3)["data"][0]["y"]
        assert y == float(f"{r.data['y'].iloc[0]:.3g}")

    def test_snowflake_dates_and_decimals_serialize(self):
        t = pd.DataFrame({"m": [dt.date(2024, 1, 1) + dt.timedelta(days=31 * i)
                                for i in range(12)], "y": range(12)})
        assert json.loads(qic(t, x="m", y="y").to_json())["data"][0]["x"] == "2024-01-01"
        f = _providers()
        f["doc"] = [Decimal(1000 + i) for i in range(len(f))]
        units = [row["unit"] for row in json.loads(_funnel(f).to_json())["data"]]
        assert sorted(units) == list(range(1000, 1060))


class TestFacetSummary:
    def test_one_row_per_facet_with_the_same_columns_either_way(self):
        one, two = _funnel().facet_summary(), _funnel(facets="campus").facet_summary()
        assert len(one) == 1 and two["campus"].tolist() == ["S", "N"]
        assert set(two.columns) - {"campus"} == set(one.columns)
        assert two["n_providers"].tolist() == [30, 30]
        assert {"expected_false_flags_outlier", "expected_false_flags_alert"} <= set(one.columns)
        assert isinstance(one["notes"].iloc[0], str) and one["limits"].iloc[0] == "[0.998, 0.95]"

    def test_qic(self):
        d = _monthly()
        two = pd.concat([d, d.assign(site="B")])
        one = qic(d, x="month", y="events", n="cases", chart="p").facet_summary()
        both = qic(two, x="month", y="events", n="cases", chart="p", facets="site").facet_summary()
        assert both["site"].tolist() == ["A", "B"]
        assert set(both.columns) - {"site"} == set(one.columns)
        assert both["longest_run"].iloc[0] == one["longest_run"].iloc[0]

    def test_faceted_qic_summary_keeps_runs_signal(self):
        d = _monthly()
        two = pd.concat([d, d.assign(site="B", events=d["events"] + np.arange(24) * 3)])
        s = qic(two, x="month", y="events", n="cases", chart="p", facets="site").summary
        assert s["runs_signal"] is True


# ---------------------------------------------------------------------------
# Choices and keywords
# ---------------------------------------------------------------------------

class TestForgiving:
    def test_case_and_spaces_do_not_matter(self):
        r = _funnel(measure="OE", signal=" FDR ", worse="Higher", tau_method="ML",
                    compare_to="Peers")
        s = r.summary
        assert (s["measure"], s["signal"], s["worse"], s["tau_method"]) == (
            "oe", "fdr", "higher", "ml")
        q = qic(_monthly(), x="month", y="events", n="cases", chart=" P", method="IHI")
        assert (q.chart, q.method) == ("p", "ihi")

    def test_measure_is_read_before_it_is_used(self):
        rng = np.random.default_rng(0)
        cases = pd.DataFrame({"doc": np.repeat(list("abcdef"), 40),
                              "minutes": rng.gamma(4, 5, 240)})
        r = funnel(cases, y="minutes", measure=" Mean", unit="doc")
        assert r.summary["measure"] == "mean" and "case_sd" in r.summary

    @pytest.mark.parametrize("kw, hint", [
        (dict(measure="proportions"), "Did you mean 'proportion'"),
        (dict(tau_method="spiegelhalte"), "Did you mean 'spiegelhalter'"),
        (dict(signal="limit"), "Did you mean 'limits'"),
    ])
    def test_a_near_miss_is_suggested(self, kw, hint):
        with pytest.raises(ValueError, match=hint):
            _funnel(**kw)

    def test_the_hint_for_a_funnel_chart_still_shows(self):
        with pytest.raises(ValueError, match="funnel plot"):
            qic(y=[1, 2, 3], chart="OE")

    def test_an_unknown_keyword_suggests_the_real_one(self):
        with pytest.raises(TypeError, match=r"'charts'\. Did you mean 'chart'\?"):
            qic(y=[1, 2, 3], charts="p")
        with pytest.raises(TypeError, match="Did you mean 'tau_method'"):
            _funnel(tau_methods="ml")
        with pytest.raises(TypeError, match=r"keyword argument 'zzz'\.$"):
            qic(y=[1, 2, 3], zzz=1)


class TestSignatures:
    @pytest.mark.parametrize("fn, name, valid", [
        (qic, "chart", CHARTS), (qic, "method", METHODS), (qic, "agg_fun", AGG_FUNS),
        (qic, "worse", ("higher", "lower")),
        (funnel, "measure", MEASURES), (funnel, "signal", SIGNALS),
        (funnel, "tau_method", TAU_METHODS), (funnel, "worse", ("higher", "lower")),
        (funnel, "benchmark", tuple(b for b in BENCHMARKS if b)),
        (funnel, "compare_to", tuple(c for c in COMPARE_TO if c)),
    ])
    def test_the_signature_spells_out_the_choices_the_code_accepts(self, fn, name, valid):
        hint = typing.get_type_hints(fn)[name]
        literals = [a for a in typing.get_args(hint) if a is not type(None)]
        choices = typing.get_args(literals[0]) if typing.get_args(literals[0]) else tuple(literals)
        assert tuple(choices) == tuple(valid)

    def test_help_shows_them(self):
        import inspect

        assert "'proportion'" in str(inspect.signature(funnel))
        assert "'xbar'" in str(inspect.signature(qic))
