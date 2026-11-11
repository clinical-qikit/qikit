"""
Messy input never becomes a silent wrong answer: a missing value is not a zero, a row
that cannot be used is counted and named, text that is not a number is refused, dates
are charted in date order, and a handful of points is not called stable.
"""

from __future__ import annotations

import datetime as dt
import warnings

import numpy as np
import pandas as pd
import pytest

from qikit import bchart, funnel, paretochart, qic


def _providers(k: int = 40, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    f = pd.DataFrame({"doc": [f"d{i}" for i in range(k)], "exp": rng.gamma(2, 10, k)})
    f["obs"] = rng.poisson(f["exp"]).astype(float)
    return f


def _funnel(data, **kw):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return funnel(data, **{"y": "obs", "n": "exp", "measure": "oe", "unit": "doc", **kw})


# ---------------------------------------------------------------------------
# funnel(): missing values
# ---------------------------------------------------------------------------

class TestFunnelMissing:
    def test_a_missing_numerator_is_not_zero_events(self):
        f = _providers()
        f.loc[0, "obs"] = np.nan
        r = _funnel(f)
        row = r.data[r.data["unit"] == "d0"].iloc[0]
        assert np.isnan(row["y"]) and np.isnan(row["numerator"])
        assert row["signal"] == "none" and np.isnan(row["p_value"])
        assert r.summary["n_providers"] == 40 and r.summary["n_tested"] == 39
        assert r.summary["n_rows_dropped"] == 1

    def test_the_other_providers_are_judged_as_if_the_row_were_absent(self):
        f = _providers()
        g = f.copy()
        g.loc[0, "obs"] = np.nan
        with_gap = _funnel(g).data.set_index("unit").drop(index="d0")
        without = _funnel(f.iloc[1:]).data.set_index("unit")
        cols = ["y", "cl", "upper_outlier", "lower_alert", "p_value", "q_value", "signal"]
        pd.testing.assert_frame_equal(with_gap.loc[without.index, cols], without[cols])

    def test_missing_case_rows_leave_the_sums(self):
        rng = np.random.default_rng(2)
        c = pd.DataFrame({"doc": np.repeat(list("abcd"), 50), "exp": 1.0})
        c["obs"] = rng.poisson(1, 200).astype(float)
        c.loc[:9, "obs"] = np.nan                      # ten of provider a's stays
        r = _funnel(c)
        a = r.data[r.data["unit"] == "a"].iloc[0]
        assert a["denominator"] == 40 and a["numerator"] == c["obs"].iloc[10:50].sum()
        assert r.summary["n_rows_dropped"] == 10

    def test_a_provider_with_no_complete_row_is_shown_untested(self):
        c = pd.DataFrame({"doc": np.repeat(list("abcd"), 50), "exp": 1.0})
        c["obs"] = np.random.default_rng(2).poisson(1, 200).astype(float)
        c.loc[:49, "obs"] = np.nan
        r = _funnel(c)
        a = r.data[r.data["unit"] == "a"].iloc[0]
        assert np.isnan(a["y"]) and a["signal"] == "none"
        assert any("no complete row" in note for note in r.summary["notes"])

    def test_a_missing_denominator_is_a_dropped_row_not_a_zero(self):
        f = _providers()
        f.loc[0, "exp"] = np.nan
        r = _funnel(f)                                  # was: "events but a zero denominator"
        assert np.isnan(r.data[r.data["unit"] == "d0"]["y"].iloc[0])
        assert r.summary["n_rows_dropped"] == 1

    def test_rows_without_a_unit_are_counted(self):
        f = _providers()
        f.loc[:4, "doc"] = None
        r = _funnel(f)
        assert r.summary["n_providers"] == 35 and r.summary["n_rows_dropped"] == 5
        note = next(n for n in r.summary["notes"] if "left out" in n)
        assert "5 row(s)" in note and "not counted as zero" in note

    def test_complete_data_drops_nothing_and_says_nothing(self):
        r = _funnel(_providers())
        assert r.summary["n_rows_dropped"] == 0
        assert not any("left out" in n for n in r.summary["notes"])

    def test_dropped_rows_are_counted_per_facet(self):
        f = _providers()
        f["campus"] = np.where(np.arange(len(f)) % 2, "N", "S")
        f.loc[0, "obs"] = np.nan                       # d0 is on campus S
        r = _funnel(f, facets="campus")
        assert r.summary["n_rows_dropped"] == 1
        assert r.summary["by_facet"]["S"]["n_rows_dropped"] == 1
        assert r.summary["by_facet"]["N"]["n_rows_dropped"] == 0

    def test_nothing_usable_is_an_error(self):
        f = _providers()
        f["doc"] = None
        with pytest.raises(ValueError, match="unit"):
            _funnel(f)


# ---------------------------------------------------------------------------
# Text that is not a number
# ---------------------------------------------------------------------------

class TestNumbers:
    def test_qic_refuses_text_in_y_and_shows_it(self):
        t = pd.DataFrame({"m": range(12), "v": ["1", "2", "x", "4", "5", "n/a", "7", "8",
                                                "9", "10", "11", "12"]})
        with pytest.raises(ValueError, match=r"y=.*not numbers.*'x'.*'n/a'"):
            qic(t, x="m", y="v", chart="i")

    def test_funnel_gives_the_same_message(self):
        f = _providers()
        f["obs"] = f["obs"].astype(object)
        f.loc[3, "obs"] = "unknown"
        with pytest.raises(ValueError, match=r"y=.*not numbers.*'unknown'"):
            _funnel(f)

    def test_numeric_text_decimals_and_blanks_are_read(self):
        from decimal import Decimal

        t = pd.DataFrame({"m": range(4), "v": ["1", " 2.5 ", "", None]})
        assert qic(t, x="m", y="v", chart="run").data["y"].tolist()[:2] == [1.0, 2.5]
        f = _providers()
        f["obs"] = [Decimal(int(v)) for v in f["obs"]]
        assert _funnel(f).summary["n_rows_dropped"] == 0

    def test_sequences_without_data(self):
        with pytest.raises(ValueError, match="y=.*not numbers"):
            qic(y=[1, 2, "three"])
        with pytest.raises(ValueError, match="x=.*not numbers"):
            bchart([0, 1, "yes"])

    def test_nullable_integers(self):
        t = pd.DataFrame({"m": range(4), "v": pd.array([1, 2, None, 4], dtype="Int64")})
        y = qic(t, x="m", y="v", chart="run").data["y"]
        assert y.iloc[0] == 1.0 and np.isnan(y.iloc[2])


# ---------------------------------------------------------------------------
# Column names
# ---------------------------------------------------------------------------

class TestColumns:
    def test_funnel_lists_the_columns_and_suggests(self):
        with pytest.raises(ValueError, match=r"unit='docs' is not a column.*Did you mean "
                                             r"'doc'\?.*Columns: \['doc', 'exp', 'obs'\]"):
            _funnel(_providers(), unit="docs")

    def test_snowflake_case_is_suggested(self):
        t = pd.DataFrame({"MONTH": range(12), "DEATHS": range(12)})
        with pytest.raises(ValueError, match="Did you mean 'DEATHS'"):
            qic(t, x="MONTH", y="deaths")

    def test_pareto_uses_the_same_check(self):
        with pytest.raises(ValueError, match="Did you mean 'reason'"):
            paretochart("reasons", data=pd.DataFrame({"reason": list("aab")}))


# ---------------------------------------------------------------------------
# qic(): date order
# ---------------------------------------------------------------------------

class TestDateOrder:
    DATES = [dt.date(2024, m, 1) for m in (3, 1, 2, 6, 5, 4)]

    def test_python_dates_are_charted_in_date_order(self):
        """Snowpark's to_pandas() returns DATE columns as datetime.date objects."""
        t = pd.DataFrame({"m": self.DATES, "y": [3, 1, 2, 6, 5, 4]})
        d = qic(t, x="m", y="y", chart="i").data
        assert d["x"].tolist() == sorted(self.DATES)
        assert d["y"].tolist() == [1, 2, 3, 4, 5, 6]
        assert isinstance(d["x"].iloc[0], dt.date)       # still a date, for the join back

    def test_and_when_rows_are_aggregated(self):
        t = pd.DataFrame({"m": self.DATES * 2, "y": [3, 1, 2, 6, 5, 4] * 2})
        assert qic(t, x="m", y="y", chart="i").data["x"].tolist() == sorted(self.DATES)

    def test_text_keeps_its_order(self):
        t = pd.DataFrame({"m": ["c", "a", "b"], "y": [1, 2, 3]})
        assert qic(t, x="m", y="y").data["x"].tolist() == ["c", "a", "b"]


# ---------------------------------------------------------------------------
# qic(): notes, and what a few points can say
# ---------------------------------------------------------------------------

class TestQicNotes:
    def test_a_long_clean_series_has_no_notes_and_looks_stable(self):
        r = qic(y=np.random.default_rng(0).normal(10, 1, 24), chart="i")
        assert r.summary["notes"] == [] and r.summary["provisional"] is False
        assert str(r).endswith("No signal: the process looks stable.")

    @pytest.mark.parametrize("k", [1, 3, 11])
    def test_a_few_points_are_not_called_stable(self, k):
        r = qic(y=list(range(1, k + 1)))
        assert r.summary["provisional"] is True
        assert any("too few" in n for n in r.summary["notes"])
        assert "looks stable" not in str(r)
        assert f"{k} point" in str(r)

    def test_limits_from_under_twenty_points_are_provisional(self):
        r = qic(y=np.random.default_rng(0).normal(10, 1, 15), chart="i")
        assert any("15 points" in n and "provisional" in n for n in r.summary["notes"])
        assert not any("provisional" in n
                       for n in qic(y=np.random.default_rng(0).normal(10, 1, 15)).summary["notes"])

    def test_missing_points_are_named(self):
        y = list(np.random.default_rng(0).normal(10, 1, 24))
        y[5] = y[9] = None
        r = qic(y=y, chart="i")
        assert any(n.startswith("2 point(s) have no value") for n in r.summary["notes"])

    def test_a_frozen_baseline_is_named(self):
        r = qic(y=np.random.default_rng(0).normal(10, 1, 30), chart="i", freeze=20)
        assert any("first 20 points" in n for n in r.summary["notes"])

    def test_facets_prefix_their_notes(self):
        t = pd.DataFrame({"m": list(range(24)) + list(range(5)),
                          "y": np.random.default_rng(0).normal(10, 1, 29),
                          "site": ["A"] * 24 + ["B"] * 5})
        r = qic(t, x="m", y="y", chart="i", facets="site")
        assert r.summary["provisional"] is True
        assert r.summary["by_facet"]["A"]["notes"] == []
        assert all(n.startswith("B: ") for n in r.summary["notes"]) and r.summary["notes"]

    def test_print_shows_the_notes(self):
        r = qic(y=np.random.default_rng(0).normal(10, 1, 30), chart="i", freeze=20)
        assert "Note: " in str(r)


# ---------------------------------------------------------------------------
# bchart() and paretochart()
# ---------------------------------------------------------------------------

class TestExtras:
    def test_bchart_wants_zero_one_outcomes(self):
        with pytest.raises(ValueError, match="0/1 outcomes"):
            bchart([0, 1, 2, 5])

    @pytest.mark.parametrize("baseline", [0, 99, 2.5, True])
    def test_bchart_baseline_is_a_case_count_in_range(self, baseline):
        with pytest.raises(ValueError, match="baseline= is a number of cases between 1 and 4"):
            bchart([0, 1, 0, 1], baseline=baseline)

    def test_bchart_reads_a_column_and_skips_missing(self):
        d = pd.DataFrame({"comp": [0, 1, None, 0, 1, 1, 1, 1, 1, 1, 1, 1]})
        r = bchart("comp", target=0.2, data=d)
        assert len(r.data) == 12 and r.summary["signal_up"] is True
        assert r.data["cusum_up"].iloc[2] == r.data["cusum_up"].iloc[1]
        with pytest.raises(ValueError, match="Did you mean 'comp'"):
            bchart("comps", data=d)

    def test_print_says_what_was_found(self):
        r = bchart([0, 1, 0, 0] + [1] * 10, target=0.2)
        assert "Signal: more events than the target, first at case" in str(r)
        assert str(bchart([0, 1, 0, 0, 0, 0, 1, 0], target=0.25)).endswith("No signal.")
        text = str(paretochart(list("aaabbc")))
        assert text.splitlines()[0] == "Pareto: 6 items in 3 categories"
        assert "a: 3 (50% cumulative)" in text


def test_a_warning_points_at_the_callers_line():
    """Not at a line inside qikit, however deep the warning arose."""
    f = _providers(60)
    f["obs"] = f["obs"] * 1.5
    with pytest.warns(UserWarning, match="absorbing") as caught:
        funnel(f, y="obs", n="exp", measure="oe", unit="doc", center=1.0)
    assert caught[0].filename == __file__
