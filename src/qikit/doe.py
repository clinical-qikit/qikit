"""
planned_experimentation.py — Planned Experimentation (Experimental Design) engine for qikit.

Implements 2-level full and fractional factorial designs with Yates ordering,
orthogonal design matrices, and effect analysis including interactions.

References
----------
1. Box GEP, Hunter JS, Hunter WG. Statistics for Experimenters, 2nd ed. Wiley, 2005.
2. Montgomery DC. Design and Analysis of Experiments, 9th ed. Wiley, 2017.
"""

from __future__ import annotations

import itertools
import json
import math
from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

import numpy as np
import pandas as pd

DesignType = Literal["full_factorial", "fractional", "one_factor"]

_GENERATORS: dict[tuple[int, int], tuple[list[str], int]] = {
    (3, 1): (["C=AB"], 3),                                              # 2^(3-1) Resolution III
    (4, 1): (["D=ABC"], 4),                                             # 2^(4-1) Resolution IV
    (5, 1): (["E=ABCD"], 5),                                            # 2^(5-1) Resolution V
    (5, 2): (["D=AB", "E=AC"], 3),                                      # 2^(5-2) Resolution III
    (7, 3): (["E=ABC", "F=BCD", "G=ACD"], 4),                           # 2^(7-3) Resolution IV
    (7, 4): (["D=AB", "E=AC", "F=BC", "G=ABC"], 3),                     # 2^(7-4) Resolution III
    (8, 4): (["E=BCD", "F=ACD", "G=ABC", "H=ABD"], 4),                  # 2^(8-4) Resolution IV
    (16, 11): (["F=ABCDE", "G=ABCD", "H=ABCE", "I=ABDE", "J=ACDE",      # 2^(16-11) Resolution III
                "K=BCDE", "L=ABC", "M=ABD", "N=ACD", "O=BCD", "P=ABCDE"], 3),
}


@dataclass(frozen=True)
class ExperimentDesign:
    """Immutable experimental design. Same pattern as SPCResult."""
    factors: tuple[str, ...]
    lows: tuple[float, ...]
    highs: tuple[float, ...]
    design_type: DesignType
    matrix: pd.DataFrame              # Coded design matrix: RunOrder + factor columns (-1/+1) + Response (NaN)
    n_factors: int
    n_runs: int
    n_replicates: int
    n_center_points: int
    generators: tuple[str, ...] | None
    resolution: int | None

    def fill(self, response: Sequence[float]) -> ExperimentResult:
        """Fill response column and return analysis result."""
        return analyze(self, response)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict suitable for JSON."""
        return {
            "factors": list(self.factors),
            "lows": list(self.lows),
            "highs": list(self.highs),
            "design_type": self.design_type,
            "matrix": self.matrix.to_dict(orient="records"),
            "n_factors": self.n_factors,
            "n_runs": self.n_runs,
            "n_replicates": self.n_replicates,
            "n_center_points": self.n_center_points,
            "generators": list(self.generators) if self.generators else None,
            "resolution": self.resolution,
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), default=str)


@dataclass(frozen=True)
class ExperimentResult:
    """Immutable experimental analysis result. Same pattern as SPCResult."""
    design: ExperimentDesign
    response: tuple[float, ...]
    effects: pd.DataFrame             # Columns: term, effect, abs_effect, pct_contribution
    residuals: np.ndarray
    grand_mean: float
    r_squared: float
    adj_r_squared: float
    summary: dict[str, Any]
    _plot_opts: dict[str, Any] = field(default_factory=dict, repr=False)

    def plot(self, chart: str = "effects", **kwargs: Any) -> Any:
        """Render as a Plotly Figure."""
        from qikit.render.doe_plots import plot_experiment
        opts = {**self._plot_opts, **kwargs}
        return plot_experiment(self, chart_type=chart, **opts)


    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict suitable for JSON."""
        def _safe(v):
            if isinstance(v, float) and np.isnan(v):
                return None
            if isinstance(v, (np.integer, np.floating, np.bool_)):
                return v.item()
            return v
        return {
            "design": self.design.to_dict(),
            "response": [_safe(v) for v in self.response],
            "effects": [{k: _safe(v) for k, v in row.items()} for _, row in self.effects.iterrows()],
            "grand_mean": self.grand_mean,
            "r_squared": self.r_squared,
            "adj_r_squared": self.adj_r_squared,
            "summary": {k: _safe(v) for k, v in self.summary.items()},
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        return f"ExperimentResult(design={self.design.design_type!r}, n_runs={self.design.n_runs}, R²={self.r_squared:.4f})"


def design(
    factors: list[str],
    lows: list[float] | None = None,
    highs: list[float] | None = None,
    design_type: str = "full_factorial",
    generators: list[str] | None = None,
    replicates: int = 1,
    center_points: int = 0,
    randomize: str = "none",          # "none" | "full" | "within_blocks"
    seed: int | None = None,
) -> ExperimentDesign:
    """
    Create an experimental design.

    Parameters
    ----------
    factors : list of factor names
    lows    : list of low levels (default -1)
    highs   : list of high levels (default +1)
    design_type : full_factorial | fractional | one_factor
    generators  : explicit generators for fractional design (e.g. ["D=ABC"])
    replicates  : number of times to repeat the design
    center_points : number of center points to add
    randomize   : none | full | within_blocks
    seed        : random seed

    Returns
    -------
    ExperimentDesign
    """
    k = len(factors)
    if lows is None: lows = [-1.0] * k
    if highs is None: highs = [1.0] * k

    if design_type == "full_factorial":
        matrix = _yates_matrix(k)
        resolution = None
        gen_tuple = None
    elif design_type == "fractional":
        # Extract k and p from 2^(k-p)
        if generators:
            p = len(generators)
            resolution = None
        else:
            # Look up standard generators from catalog
            available_p = [key[1] for key in _GENERATORS.keys() if key[0] == k]
            if not available_p:
                raise ValueError(f"No standard fractional generators for k={k}. Supply generators= explicitly.")
            p = max(available_p)
            generators, resolution = _GENERATORS[(k, p)]

        matrix = _fractional_matrix(k, p, generators)
        gen_tuple = tuple(generators)
    elif design_type == "one_factor":
        # One factor at a time: center point + each factor at high level
        matrix = np.full((k + 1, k), -1, dtype=int)
        for i in range(k):
            matrix[i + 1, i] = 1
        resolution = None
        gen_tuple = None
    else:
        raise ValueError(f"Unknown design type: {design_type!r}")

    # Replicate
    if replicates > 1:
        matrix = np.tile(matrix, (replicates, 1))

    # Center points
    if center_points > 0:
        cp_matrix = np.zeros((center_points, k), dtype=int)
        matrix = np.vstack([matrix, cp_matrix])

    n_runs = len(matrix)
    
    # Randomize
    run_order = np.arange(1, n_runs + 1)
    if randomize == "full":
        rng = np.random.default_rng(seed)
        run_order = rng.permutation(run_order)
    elif randomize == "within_blocks" and replicates > 1:
        rng = np.random.default_rng(seed)
        base_runs = n_runs // replicates
        for i in range(replicates):
            start = i * base_runs
            end = (i + 1) * base_runs
            run_order[start:end] = rng.permutation(run_order[start:end])

    # Assemble DataFrame
    df_dict = {"RunOrder": run_order}
    for i, name in enumerate(factors):
        df_dict[name] = matrix[:, i]
    df_dict["Response"] = np.nan
    
    df = pd.DataFrame(df_dict).sort_values("RunOrder").reset_index(drop=True)

    return ExperimentDesign(
        factors=tuple(factors),
        lows=tuple(lows),
        highs=tuple(highs),
        design_type=design_type,
        matrix=df,
        n_factors=k,
        n_runs=n_runs,
        n_replicates=replicates,
        n_center_points=center_points,
        generators=gen_tuple,
        resolution=resolution,
    )


def analyze(
    design_obj: ExperimentDesign,
    response: Sequence[float],
    max_interaction: int = 2,
) -> ExperimentResult:
    """
    Analyze experimental results.

    Parameters
    ----------
    design_obj : the design used
    response   : experimental results in RunOrder
    max_interaction : maximum order of interactions to compute (default 2)

    Returns
    -------
    ExperimentResult
    """
    resp_arr = np.asarray(response, dtype=float)
    if len(resp_arr) != design_obj.n_runs:
        raise ValueError(f"Response length ({len(resp_arr)}) must match n_runs ({design_obj.n_runs}).")

    # Extract coded matrix from DataFrame (excluding RunOrder and Response)
    factor_cols = [c for c in design_obj.matrix.columns if c not in ("RunOrder", "Response")]
    coded_matrix = design_obj.matrix[factor_cols].to_numpy()

    terms, r_squared, ss_total = _compute_effects(coded_matrix, resp_arr, factor_cols, max_interaction)

    # Residuals and predicted
    grand_mean = float(np.mean(resp_arr))
    n = len(resp_arr)
    predicted = np.full(n, grand_mean)
    for t in terms:
        # Rebuild contrast column
        combo = t["_combo"]
        contrast_col = np.ones(n, dtype=float)
        for idx in combo:
            contrast_col *= coded_matrix[:, idx]
        predicted += (t["effect"] / 2.0) * contrast_col

    residuals = resp_arr - predicted
    
    p = len(terms)
    adj_r_squared = 1.0 - (1.0 - r_squared) * (n - 1) / (n - p - 1) if n > p + 1 else 0.0

    effects_df = pd.DataFrame([
        {k: v for k, v in t.items() if not k.startswith("_")} for t in terms
    ])

    summary = {
        "n_runs": n,
        "n_factors": design_obj.n_factors,
        "ss_total": float(ss_total),
    }

    return ExperimentResult(
        design=design_obj,
        response=tuple(resp_arr),
        effects=effects_df,
        residuals=residuals,
        grand_mean=grand_mean,
        r_squared=float(r_squared),
        adj_r_squared=float(adj_r_squared),
        summary=summary,
    )


def _yates_matrix(k: int) -> np.ndarray:
    """Generate 2^k full factorial in Yates standard order."""
    n = 2 ** k
    matrix = np.empty((n, k), dtype=int)
    for j in range(k):
        # Factor j alternates every 2^j rows
        matrix[:, j] = np.where(
            (np.arange(n) // (2 ** j)) % 2 == 0, -1, 1
        )
    return matrix


def _fractional_matrix(k: int, p: int, generators: list[str]) -> np.ndarray:
    """Generate 2^(k-p) fractional factorial."""
    base_k = k - p
    base = _yates_matrix(base_k)
    
    factor_labels = [chr(65 + i) for i in range(k)]
    base_labels = factor_labels[:base_k]
    
    generated_cols = []
    for gen in generators:
        parts = gen.replace(" ", "").split("=")
        target = parts[0]
        source_factors = list(parts[1])
        
        col = np.ones(len(base), dtype=int)
        for sf in source_factors:
            idx = base_labels.index(sf)
            col *= base[:, idx]
        generated_cols.append(col)
        
    return np.column_stack([base] + generated_cols) if generated_cols else base


def _compute_effects(matrix: np.ndarray, response: np.ndarray, 
                     factor_names: list[str], max_order: int) -> tuple[list[dict], float, float]:
    """Compute main effects and interactions."""
    n = len(response)
    y_bar = np.mean(response)
    ss_total = np.sum((response - y_bar) ** 2)
    terms = []
    
    for order in range(1, max_order + 1):
        for combo in itertools.combinations(range(len(factor_names)), order):
            label = ":".join(factor_names[i] for i in combo)
            
            contrast_col = np.ones(n, dtype=float)
            for i in combo:
                contrast_col *= matrix[:, i]
                
            effect = 2.0 * np.dot(contrast_col, response) / n
            ss = effect ** 2 * n / 4.0
            pct = 100.0 * ss / ss_total if ss_total > 0 else 0.0
            
            terms.append({
                "term": label,
                "effect": float(effect),
                "abs_effect": float(abs(effect)),
                "ss": float(ss),
                "pct_contribution": float(pct),
                "_combo": combo,
            })
            
    ss_model = sum(t["ss"] for t in terms)
    r_squared = ss_model / ss_total if ss_total > 0 else 0.0
    
    return terms, r_squared, ss_total
