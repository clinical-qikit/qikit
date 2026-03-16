from __future__ import annotations
import json
import numpy as np
import pandas as pd
import pytest
from qikit import design, analyze, ExperimentDesign, ExperimentResult
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
