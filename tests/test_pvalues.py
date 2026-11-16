"""
The corners of core/pvalues.py that the funnel tests do not reach: the normal-model
fallbacks, Byar's approximation, the transformed scales, and the guards for values no
test applies to. Expected values come from the standard library (statistics.NormalDist,
math) or from the formula in the docstring, never from the function under test.
"""

from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pytest

from qikit.core.dist import byar_quantile
from qikit.core.pvalues import (
    _normal_tails,
    _point_tails,
    bh_q_values,
    byar_tails,
    count_model,
    funnel_p_values,
    transformed_tails,
)

PHI = NormalDist().cdf


def _normal(o: float, mu: float, var: float) -> tuple[float, float]:
    z = (o - mu) / math.sqrt(var)
    return PHI(z), PHI(-z)


def _poisson_cdf(k: int, lam: float) -> float:
    return sum(math.exp(-lam) * lam**j / math.factorial(j) for j in range(k + 1))


class TestNormalTails:
    def test_half_each_side_at_the_mean(self):
        assert _normal_tails(10.0, 10.0, 4.0) == (0.5, 0.5)

    def test_matches_the_normal_distribution(self):
        lower, upper = _normal_tails(13.92, 10.0, 4.0)       # z = 1.96
        assert lower == pytest.approx(PHI(1.96), abs=1e-12)
        assert upper == pytest.approx(PHI(-1.96), abs=1e-12)
        assert lower + upper == pytest.approx(1.0, abs=1e-15)

    @pytest.mark.parametrize("o, mu, var", [
        (1.0, 1.0, 0.0), (1.0, 1.0, -1.0), (1.0, 1.0, math.nan),
        (math.nan, 1.0, 1.0), (1.0, math.nan, 1.0),
    ])
    def test_nan_where_there_is_no_model(self, o, mu, var):
        assert all(math.isnan(t) for t in _normal_tails(o, mu, var))


class TestByarTails:
    @pytest.mark.parametrize("lam", [0.5, 5.0, 20.0, 400.0])
    @pytest.mark.parametrize("coverage_tail", [0.025, 0.001])
    def test_inverts_the_byar_contour(self, lam, coverage_tail):
        """A count on a Byar contour has exactly that contour's tail probability."""
        z = NormalDist().inv_cdf(1.0 - coverage_tail)
        upper_count = byar_quantile(lam, z, upper=True)
        assert byar_tails(upper_count, lam)[1] == pytest.approx(coverage_tail, rel=1e-9)
        lower_count = byar_quantile(lam, z, upper=False)
        if lower_count > 0:                       # floored at zero for a small expected count
            assert byar_tails(lower_count, lam)[0] == pytest.approx(coverage_tail, rel=1e-9)

    def test_tails_sum_to_one(self):
        lower, upper = byar_tails(7.0, 5.0)
        assert lower + upper == pytest.approx(1.0, abs=1e-15)
        assert upper < 0.5 < lower                # 7 observed against 5 expected

    @pytest.mark.parametrize("o, lam", [(-1.0, 5.0), (3.0, 0.0), (3.0, -2.0), (math.nan, 5.0),
                                        (3.0, math.nan)])
    def test_nan_for_an_impossible_count_or_expectation(self, o, lam):
        assert all(math.isnan(t) for t in byar_tails(o, lam))


class TestTransformedTails:
    def test_at_the_center_line_each_tail_is_a_half(self):
        assert transformed_tails(1.0, 40.0, 1.0, 0.01, "log") == (0.5, 0.5)

    def test_above_the_center_the_upper_tail_is_the_small_one(self):
        lower, upper = transformed_tails(1.3, 40.0, 1.0, 0.01, "sqrt")
        assert upper < 0.5 < lower
        assert lower + upper == pytest.approx(1.0, abs=1e-15)

    def test_more_spread_between_providers_weakens_the_evidence(self):
        tight = transformed_tails(1.3, 40.0, 1.0, 0.001, "sqrt")[1]
        loose = transformed_tails(1.3, 40.0, 1.0, 0.05, "sqrt")[1]
        assert tight < loose < 0.5

    def test_no_events_on_the_log_scale_is_as_low_as_possible(self):
        assert transformed_tails(0.0, 40.0, 1.0, 0.01, "log") == (0.0, 1.0)

    def test_a_missing_value_has_no_p_value(self):
        assert all(math.isnan(t) for t in transformed_tails(math.nan, 40.0, 1.0, 0.01, "log"))


class TestNormalFallback:
    """Where no exact model exists the tails are normal, at the exact model's mean and
    variance (the docstring of _point_tails)."""

    def test_proportion_spread_wider_than_any_beta(self):
        # θ₀(1 − θ₀) = 0.25 < τ² = 0.3, so no beta has this variance: [1] eq. 11.
        tails, method = _point_tails(30.0, 50.0, 0.5, 0.3, "binomial")
        assert method == "normal"
        assert tails == pytest.approx(_normal(30.0, 25.0, 50 * 0.25 + 50**2 * 0.3), rel=1e-12)

    def test_the_same_with_a_fractional_count(self):
        tails, method = _point_tails(30.5, 50.0, 0.5, 0.3, "binomial")
        assert method == "normal"
        assert tails == pytest.approx(_normal(30.5, 25.0, 50 * 0.25 + 50**2 * 0.3), rel=1e-12)

    def test_the_same_with_a_fractional_denominator(self):
        tails, method = _point_tails(30.0, 50.5, 0.5, 0.3, "binomial")
        assert method == "normal"
        assert tails == pytest.approx(
            _normal(30.0, 25.25, 50.5 * 0.25 + 50.5**2 * 0.3), rel=1e-12)

    def test_poisson_gamma_past_the_exact_walk(self):
        # Variance λ + λ²·τ²/θ₀² for the gamma mixture at θ₀ = 1.
        lam, tau2 = 3e6, 0.04
        var = lam + lam * lam * tau2
        tails, method = _point_tails(lam + 2e5, lam, 1.0, tau2, "poisson")
        assert method == "normal"
        assert tails == pytest.approx(_normal(lam + 2e5, lam, var), rel=1e-9)

    def test_poisson_gamma_past_the_exact_walk_with_a_fractional_count(self):
        lam, tau2 = 3e6, 0.04
        var = lam + lam * lam * tau2
        tails, method = _point_tails(lam + 2e5 + 0.5, lam, 1.0, tau2, "poisson")
        assert method == "normal"
        assert tails == pytest.approx(_normal(lam + 2e5 + 0.5, lam, var), rel=1e-9)

    def test_beta_binomial_past_the_exact_walk(self):
        # α + β = θ₀(1 − θ₀)/τ² − 1 = 24; variance nθ₀(1 − θ₀)(α + β + n)/(α + β + 1).
        n, cl, tau2 = 1e6, 0.5, 0.01
        var = n * 0.25 * (24 + n) / 25
        for o in (5.6e5, 5.6e5 + 0.5):
            tails, method = _point_tails(o, n, cl, tau2, "binomial")
            assert method == "normal"
            assert tails == pytest.approx(_normal(o, n * cl, var), rel=1e-9)

    def test_funnel_p_values_reports_the_fallback(self):
        p, method, model = funnel_p_values(
            0.5, np.array([0.6, 0.44]), np.array([50.0, 50.0]), 0.3, "binomial", "both")
        assert method == "normal" and model == "beta_binomial"
        var = 50 * 0.25 + 50**2 * 0.3
        assert p[0] == pytest.approx(2 * _normal(30.0, 25.0, var)[1], rel=1e-12)
        assert p[1] == pytest.approx(2 * _normal(22.0, 25.0, var)[0], rel=1e-12)


class TestInterpolation:
    def test_a_fractional_count_is_linear_between_its_neighbors(self):
        (lower, upper), method = _point_tails(3.25, 5.0, 1.0, 0.0, "poisson")
        assert method == "interpolated"
        assert lower == pytest.approx(
            0.75 * _poisson_cdf(3, 5.0) + 0.25 * _poisson_cdf(4, 5.0), rel=1e-12)
        assert upper == pytest.approx(
            0.75 * (1 - _poisson_cdf(2, 5.0)) + 0.25 * (1 - _poisson_cdf(3, 5.0)), rel=1e-12)

    def test_a_whole_count_is_exact(self):
        (lower, upper), method = _point_tails(3.0, 5.0, 1.0, 0.0, "poisson")
        assert method == "exact"
        assert lower == pytest.approx(_poisson_cdf(3, 5.0), rel=1e-12)
        assert upper == pytest.approx(1 - _poisson_cdf(2, 5.0), rel=1e-12)


class TestFunnelPValues:
    def test_sides(self):
        y, n = np.array([1.4]), np.array([10.0])           # 14 observed, 10 expected
        above = funnel_p_values(1.0, y, n, 0.0, "poisson", "above")[0][0]
        below = funnel_p_values(1.0, y, n, 0.0, "poisson", "below")[0][0]
        both = funnel_p_values(1.0, y, n, 0.0, "poisson", "both")[0][0]
        assert above == pytest.approx(1 - _poisson_cdf(13, 10.0), rel=1e-12)
        assert below == pytest.approx(_poisson_cdf(14, 10.0), rel=1e-12)
        assert both == pytest.approx(2 * above, rel=1e-12)

    def test_two_sided_is_capped_at_one(self):
        p = funnel_p_values(1.0, np.array([1.0]), np.array([10.0]), 0.0, "poisson", "both")[0]
        assert p[0] == 1.0

    def test_no_p_value_without_a_value_or_a_denominator(self):
        p, method, _ = funnel_p_values(
            1.0, np.array([np.nan, 1.2, 1.2, 1.2]), np.array([10.0, 0.0, np.nan, 10.0]),
            0.0, "poisson", "both")
        assert np.isnan(p[:3]).all() and np.isfinite(p[3])
        assert method == "exact"

    def test_a_point_the_model_cannot_score_is_skipped(self):
        # A negative ratio has no Byar tail; it gets no p-value and names no method.
        p, method, model = funnel_p_values(
            1.0, np.array([-0.5, 1.2]), np.array([10.0, 10.0]), 0.0, "poisson", "both", byar=True)
        assert math.isnan(p[0]) and np.isfinite(p[1])
        assert (method, model) == ("byar", "poisson")

    def test_the_method_reported_is_the_least_exact_one_used(self):
        y = np.array([1.2, 1.25])                           # counts 12 and 12.5 of 10
        assert funnel_p_values(1.0, y[:1], np.array([10.0]), 0.0, "poisson", "both")[1] == "exact"
        assert funnel_p_values(1.0, y, np.array([10.0, 10.0]), 0.0, "poisson", "both")[1] \
            == "interpolated"
        big = np.array([10.0, 2e5])                         # past the exact Poisson range
        assert funnel_p_values(1.0, y, big, 0.0, "poisson", "both")[1] == "byar"

    def test_a_transformed_scale_uses_its_normal_model(self):
        y, n = np.array([1.3, 0.8]), np.array([40.0, 60.0])
        p, method, model = funnel_p_values(1.0, y, n, 0.01, "poisson", "above", scale="log")
        assert (method, model) == ("transformed_normal", "normal_log")
        assert p[0] == transformed_tails(1.3, 40.0, 1.0, 0.01, "log")[1]

    def test_a_transformed_scale_with_no_spread_is_the_exact_model(self):
        y, n = np.array([1.3]), np.array([40.0])
        exact = funnel_p_values(1.0, y, n, 0.0, "poisson", "above")
        same = funnel_p_values(1.0, y, n, 0.0, "poisson", "above", scale="log")
        assert same[0][0] == exact[0][0] and same[1:] == exact[1:] == ("exact", "poisson")


class TestCountModel:
    @pytest.mark.parametrize("family, tau2, scale, expected", [
        ("poisson", 0.0, "natural", "poisson"),
        ("poisson", 0.02, "natural", "poisson_gamma"),
        ("binomial", 0.0, "natural", "binomial"),
        ("binomial", 0.02, "natural", "beta_binomial"),
        ("poisson", 0.02, "sqrt", "normal_sqrt"),
        ("binomial", 0.02, "arcsine", "normal_arcsine"),
        ("poisson", 0.0, "log", "poisson"),
    ])
    def test_names_the_distribution_used(self, family, tau2, scale, expected):
        assert count_model(family, tau2, scale) == expected


class TestBenjaminiHochberg:
    def test_nothing_to_test(self):
        assert bh_q_values(np.array([])).shape == (0,)
        assert np.isnan(bh_q_values(np.array([np.nan, np.nan]))).all()

    def test_worked_example(self):
        # Sorted p: .01 .02 .03 .5 with K = 4 gives p·K/rank = .04 .04 .04 .5.
        q = bh_q_values(np.array([0.5, 0.01, 0.03, 0.02]))
        assert q == pytest.approx([0.5, 0.04, 0.04, 0.04], abs=1e-15)

    def test_properties(self):
        rng = np.random.default_rng(7)
        p = rng.uniform(size=200) ** 3
        p[::17] = np.nan
        q = bh_q_values(p)
        tested = np.isfinite(p)
        assert np.isnan(q[~tested]).all()
        assert (q[tested] >= p[tested]).all() and (q[tested] <= 1.0).all()
        order = np.argsort(p[tested])
        assert (np.diff(q[tested][order]) >= 0).all()       # q keeps the order of p
        shuffled = rng.permutation(len(p))
        assert np.array_equal(bh_q_values(p[shuffled]), q[shuffled], equal_nan=True)


class TestOneSidedFallbackThroughFunnel:
    """The normal fallback once returned its two tails swapped, which reversed every
    one-sided p-value it produced; two-sided ones hid it."""

    Y = np.array([45, 30, 27, 25, 25, 23, 20, 5.0])
    N = np.full(8, 50.0)

    def _p(self, worse):
        import qikit

        # tau=0.6 is wider than any proportion can spread around 0.5, forcing the fallback.
        f = qikit.funnel(y=self.Y, n=self.N, measure="proportion", tau=0.6, worse=worse)
        assert f.summary["p_value_method"] == "normal"
        return f.data["p_value"].to_numpy()

    def test_worse_higher_gives_the_highest_provider_the_smallest_p(self):
        p = self._p("higher")
        assert p[0] == p.min() and p[-1] == p.max()
        assert (np.diff(p) >= 0).all()

    def test_worse_lower_gives_the_lowest_provider_the_smallest_p(self):
        p = self._p("lower")
        assert p[-1] == p.min() and p[0] == p.max()
        assert (np.diff(p) <= 0).all()
