from __future__ import annotations
import json
import numpy as np
import pytest
from qikit import analyze, design
from qikit.doe import _yates_matrix, _fractional_matrix

class TestExperimentCore:
    def test_yates_matrix_2x2(self):
        matrix = _yates_matrix(2)
        expected = np.array([
            [-1, -1],
            [ 1, -1],
            [-1,  1],
            [ 1,  1]
        ])
        np.testing.assert_array_equal(matrix, expected)

    def test_fractional_matrix_2x3_1(self):
        # 2^(3-1) with C=AB
        matrix = _fractional_matrix(3, 1, ["C=AB"])
        # Base (2^2): [-1,-1], [1,-1], [-1,1], [1,1]
        # C = A*B:    [ 1],    [-1],   [-1],   [ 1]
        expected = np.array([
            [-1, -1,  1],
            [ 1, -1, -1],
            [-1,  1, -1],
            [ 1,  1,  1]
        ])
        np.testing.assert_array_equal(matrix, expected)

    def test_design_full_factorial(self):
        d = design(factors=["A", "B"])
        assert d.n_runs == 4
        assert d.n_factors == 2
        assert "A" in d.matrix.columns
        assert "B" in d.matrix.columns
        assert "Response" in d.matrix.columns

    def test_analyze_effects_known(self):
        # Box, Hunter & Hunter 2nd Ed, p. 177 (Example 5.1)
        # Factors: Temp (A), Conc (B)
        # Response: Yield
        d = design(factors=["A", "B"])
        response = [60, 72, 54, 68] # Yates order
        res = d.fill(response)
        
        # A effect = (72+68)/2 - (60+54)/2 = 70 - 57 = 13.0
        # Wait, Box uses a different formula? No, it's the same.
        # Contrast A = -60 + 72 - 54 + 68 = 26
        # Effect A = 26 / (4/2) = 13.0
        
        # In my code: Effect = 2.0 * np.dot(contrast_col, response) / n
        # Effect A = 2 * (-60 + 72 - 54 + 68) / 4 = 2 * 26 / 4 = 13.0
        
        # B effect = (54+68)/2 - (60+72)/2 = 61 - 66 = -5.0
        # Contrast B = -60 - 72 + 54 + 68 = -10
        # Effect B = 2 * (-10) / 4 = -5.0
        
        # AB interaction
        # Contrast AB = 60 - 72 - 54 + 68 = 2
        # Effect AB = 2 * 2 / 4 = 1.0
        
        eff_a = res.effects[res.effects["term"] == "A"]["effect"].iloc[0]
        eff_b = res.effects[res.effects["term"] == "B"]["effect"].iloc[0]
        eff_ab = res.effects[res.effects["term"] == "A:B"]["effect"].iloc[0]
        
        assert eff_a == 13.0
        assert eff_b == -5.0
        assert eff_ab == 1.0
        
    def test_r_squared(self):
        d = design(factors=["A", "B"])
        response = [10, 20, 10, 20] # Only A matters
        res = d.fill(response)
        assert res.r_squared > 0.99
        
    def test_to_dict_serializable(self):
        d = design(factors=["A", "B"])
        res = d.fill([1, 2, 3, 4])
        # Should not raise
        json.dumps(res.to_dict())


# Box, Hunter & Hunter, Statistics for Experimenters (2nd ed.), the pilot-plant 2^3
# example: temperature (A), concentration (B), catalyst (C); yield in Yates order.
PILOT = [60, 72, 54, 68, 52, 83, 45, 80]
PILOT_EFFECTS = {"A": 23.0, "B": -5.0, "C": 1.5, "A:B": 1.5, "A:C": 10.0, "B:C": 0.0,
                 "A:B:C": 0.5}


def _effects(result) -> dict:
    return dict(zip(result.effects["term"], result.effects["effect"]))


class TestDesignTypes:
    def test_levels_default_to_coded_units(self):
        d = design(["A", "B"])
        assert d.lows == (-1.0, -1.0) and d.highs == (1.0, 1.0)
        assert d.matrix["RunOrder"].tolist() == [1, 2, 3, 4]
        assert d.matrix["Response"].isna().all()

    def test_given_levels_are_kept(self):
        d = design(["Temp", "Conc"], lows=[160, 20], highs=[180, 40])
        assert d.lows == (160, 20) and d.highs == (180, 40)

    @pytest.mark.parametrize("k, runs, generators, resolution", [
        (3, 4, ("C=AB",), 3),
        (4, 8, ("D=ABC",), 4),
        (5, 8, ("D=AB", "E=AC"), 3),          # the smallest catalogued fraction for 5
        (7, 8, ("D=AB", "E=AC", "F=BC", "G=ABC"), 3),
    ])
    def test_fractional_from_the_catalog(self, k, runs, generators, resolution):
        d = design([chr(65 + i) for i in range(k)], design_type="fractional")
        assert (d.n_runs, d.generators, d.resolution) == (runs, generators, resolution)
        m = d.matrix[list(d.factors)].to_numpy()
        assert set(np.unique(m)) == {-1, 1}
        # Balanced, mutually orthogonal columns.
        assert (m.sum(axis=0) == 0).all()
        assert np.array_equal(m.T @ m, runs * np.eye(k, dtype=int))

    def test_fractional_with_explicit_generators(self):
        d = design(list("ABCDE"), design_type="fractional", generators=["E=ABCD"])
        assert d.n_runs == 16 and d.generators == ("E=ABCD",) and d.resolution is None
        m = d.matrix[list("ABCDE")].to_numpy()
        assert np.array_equal(m[:, 4], m[:, 0] * m[:, 1] * m[:, 2] * m[:, 3])

    def test_fractional_without_a_catalog_entry_says_what_to_do(self):
        with pytest.raises(ValueError, match="Supply generators="):
            design(["A", "B"], design_type="fractional")

    def test_one_factor_at_a_time(self):
        d = design(["A", "B", "C"], design_type="one_factor")
        assert d.matrix[["A", "B", "C"]].to_numpy().tolist() == [
            [-1, -1, -1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]]
        assert d.generators is None and d.resolution is None

    def test_unknown_design_type(self):
        with pytest.raises(ValueError, match="Unknown design type: 'latin'"):
            design(["A"], design_type="latin")


class TestReplicatesCentersAndRandomization:
    def test_replicates_repeat_the_design(self):
        d = design(["A", "B"], replicates=3)
        assert (d.n_runs, d.n_replicates) == (12, 3)
        m = d.matrix[["A", "B"]].to_numpy()
        assert np.array_equal(m[:4], m[4:8]) and np.array_equal(m[:4], m[8:])

    def test_center_points_follow_the_factorial_runs(self):
        d = design(["A", "B"], center_points=3)
        assert (d.n_runs, d.n_center_points) == (7, 3)
        assert (d.matrix[["A", "B"]].to_numpy()[4:] == 0).all()

    def test_full_randomization_reorders_the_same_runs(self):
        plain = design(["A", "B", "C"])
        shuffled = design(["A", "B", "C"], randomize="full", seed=3)
        assert shuffled.matrix["RunOrder"].tolist() == list(range(1, 9))
        rows = lambda d: sorted(map(tuple, d.matrix[["A", "B", "C"]].to_numpy()))  # noqa: E731
        assert rows(shuffled) == rows(plain)
        assert not shuffled.matrix[["A", "B", "C"]].equals(plain.matrix[["A", "B", "C"]])

    def test_a_seed_reproduces_the_order(self):
        a = design(["A", "B", "C"], randomize="full", seed=11)
        b = design(["A", "B", "C"], randomize="full", seed=11)
        assert a.matrix.equals(b.matrix)

    def test_within_blocks_keeps_each_replicate_together(self):
        d = design(["A", "B"], replicates=3, randomize="within_blocks", seed=5)
        m = d.matrix[["A", "B"]].to_numpy()
        full = {(-1, -1), (1, -1), (-1, 1), (1, 1)}
        for block in range(3):
            assert set(map(tuple, m[4 * block:4 * block + 4])) == full
        assert not np.array_equal(m, design(["A", "B"], replicates=3).matrix[["A", "B"]].to_numpy())

    def test_within_blocks_needs_replicates_to_do_anything(self):
        d = design(["A", "B"], randomize="within_blocks", seed=5)
        assert d.matrix.equals(design(["A", "B"]).matrix)

    def test_within_blocks_with_center_points_keeps_each_replicate_together(self):
        d = design(["A", "B"], replicates=2, center_points=3, randomize="within_blocks", seed=1)
        m = d.matrix[["A", "B"]].to_numpy()
        full = {(-1, -1), (1, -1), (-1, 1), (1, 1)}
        assert set(map(tuple, m[:4])) == full and set(map(tuple, m[4:8])) == full


class TestAnalysis:
    def test_pilot_plant_effects(self):
        res = analyze(design(["A", "B", "C"]), PILOT, max_interaction=3)
        assert _effects(res) == pytest.approx(PILOT_EFFECTS, abs=1e-12)
        assert res.grand_mean == 64.25

    def test_a_saturated_model_fits_exactly(self):
        res = analyze(design(["A", "B", "C"]), PILOT, max_interaction=3)
        assert res.r_squared == pytest.approx(1.0, abs=1e-12)
        assert res.residuals == pytest.approx(np.zeros(8), abs=1e-9)
        assert res.effects["pct_contribution"].sum() == pytest.approx(100.0, abs=1e-9)
        assert res.adj_r_squared == 0.0            # no degrees of freedom left for error

    def test_two_factor_interactions_by_default(self):
        res = design(["A", "B", "C"]).fill(PILOT)
        assert set(res.effects["term"]) == set(PILOT_EFFECTS) - {"A:B:C"}
        # What is left out is the three-factor interaction: effect 0.5, so ±0.25 each run.
        assert np.abs(res.residuals) == pytest.approx(np.full(8, 0.25), abs=1e-12)
        ss_total = sum((y - 64.25) ** 2 for y in PILOT)
        assert res.summary == {"n_runs": 8, "n_factors": 3, "ss_total": ss_total}
        assert res.r_squared == pytest.approx(1 - 8 * 0.25**2 / ss_total, abs=1e-12)
        assert res.adj_r_squared == pytest.approx(1 - (1 - res.r_squared) * 7 / 1, abs=1e-12)

    def test_main_effects_only(self):
        res = analyze(design(["A", "B", "C"]), PILOT, max_interaction=1)
        assert _effects(res) == pytest.approx({"A": 23.0, "B": -5.0, "C": 1.5}, abs=1e-12)

    def test_sums_of_squares_and_absolute_effects(self):
        res = design(["A", "B", "C"]).fill(PILOT)
        row = res.effects.set_index("term").loc["B"]
        assert (row["abs_effect"], row["ss"]) == (5.0, 50.0)       # SS = effect²·n/4

    def test_a_flat_response_has_no_effects(self):
        res = design(["A", "B"]).fill([5, 5, 5, 5])
        assert (res.effects["effect"] == 0).all() and (res.effects["pct_contribution"] == 0).all()
        assert res.r_squared == 0.0

    def test_replicates_average(self):
        res = design(["A", "B"], replicates=2).fill([60, 72, 54, 68, 62, 74, 56, 70])
        assert _effects(res) == pytest.approx({"A": 13.0, "B": -5.0, "A:B": 1.0}, abs=1e-12)

    def test_response_length_must_match(self):
        with pytest.raises(ValueError, match=r"Response length \(3\) must match n_runs \(4\)"):
            design(["A", "B"]).fill([1, 2, 3])

    def test_center_points_do_not_change_the_effects(self):
        y = np.array([60, 72, 54, 68, 63, 64], dtype=float)
        res = design(["A", "B"], center_points=2).fill(y)
        assert _effects(res) == pytest.approx({"A": 13.0, "B": -5.0, "A:B": 1.0}, abs=1e-12)
        # The effects are twice the least-squares coefficients, and the fit is that model's.
        a, b = res.design.matrix[["A", "B"]].to_numpy(dtype=float).T
        X = np.column_stack([np.ones(6), a, b, a * b])
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        assert 2 * beta[1:] == pytest.approx([13.0, -5.0, 1.0], abs=1e-9)
        assert res.residuals == pytest.approx(y - X @ beta, abs=1e-9)
        assert res.effects["ss"].sum() + (res.residuals ** 2).sum() == pytest.approx(
            res.summary["ss_total"], abs=1e-9)


class TestSerialization:
    def test_design_round_trips_through_json(self):
        d = design(list("ABC"), design_type="fractional")
        out = json.loads(d.to_json())
        assert out["generators"] == ["C=AB"] and out["resolution"] == 3
        assert out["n_runs"] == 4 and len(out["matrix"]) == 4
        assert out["matrix"][0] == {"RunOrder": 1, "A": -1, "B": -1, "C": 1, "Response": None}
        assert "NaN" not in d.to_json()                    # NaN is not JSON
        assert json.loads(design(["A"]).to_json())["generators"] is None

    def test_result_round_trips_through_json(self):
        res = design(["A", "B"]).fill([60, 72, 54, 68])
        out = json.loads(res.to_json())
        assert out["response"] == [60, 72, 54, 68]
        assert [e["term"] for e in out["effects"]] == ["A", "B", "A:B"]
        assert out["effects"][0]["effect"] == 13.0
        assert out["grand_mean"] == 63.5 and out["summary"]["n_runs"] == 4
        assert out["design"]["factors"] == ["A", "B"]

    def test_a_missing_response_serializes_as_null(self):
        res = design(["A", "B"]).fill([60, 72, float("nan"), 68])
        assert res.to_dict()["response"] == [60.0, 72.0, None, 68.0]

    def test_repr_names_the_design(self):
        res = design(["A", "B"]).fill([10, 20, 10, 20])
        assert repr(res) == "ExperimentResult(design='full_factorial', n_runs=4, R²=1.0000)"
