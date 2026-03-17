# qikit Implementation Plan — SPC Bugs, Python Planned Experimentation, Excel Add-in, Shared Fixtures

> **Purpose**: Complete specification for an implementing agent. Read this fully before writing any code.
> **Current Status**: Phases 0, 1, 2, and 3 are COMPLETE. The project is currently in **Phase 4** (Excel Add-in UI Wiring & Integration).
> **Date**: 2026-03-16
> **Codebase**: `/Users/davidvandyke/repos/qikit/` — clinical-qikit v0.1.0a0
> **Tests**: 130 passing (`uv run pytest tests/ -v`), ruff clean (`uv run ruff check src/`)

---

## 🎯 Instructions for Next Implementing Agent
**Welcome!** Your task is to complete the Excel Add-in UI and then move to Phase 5.
1. **Read Section 6 (Implementation Phases)** to understand the remaining work in Phase 4.
2. Ensure all **UX Rules** in Section 5 are followed strictly during UI development.
3. Validate the add-in using the `dev-harness.tsx` and then via sideloading in Excel.
4. Follow the architecture rules strictly, ensuring all verification steps pass.

---

## Table of Contents

1. [Decisions Made](#1-decisions-made)
2. [SPC Code Review — Bugs to Fix First](#2-spc-code-review--bugs-to-fix-first)
3. [Shared Test Fixtures](#3-shared-test-fixtures)
4. [Python Planned Experimentation Module](#4-python-doe-module)
5. [TypeScript Excel Add-in](#5-typescript-excel-add-in)
6. [Implementation Phases](#6-implementation-phases)
7. [Verification Strategy](#7-verification-strategy)
8. [SPC Formula Reference](#8-spc-formula-reference)
9. [Critical Files](#9-critical-files)

---

## 1. Decisions Made

- **Chart rendering in Excel**: Both — interactive charts in task pane (primary via Chart.js, due to adaptability and elegance for typical data sizes) + "Insert Chart to Sheet" button for Excel native charts.
- **TypeScript engine packaging**: Monorepo only — engine lives inside `excel-addin/src/engine/` as internal modules (no separate npm package). Can extract later. Does not affect end-user install.
- **Fractional factorial scope**: Full standard textbook catalog parity — all 8 designs: 2^(3-1), 2^(4-1), 2^(5-1), 2^(5-2), 2^(7-3), 2^(7-4), 2^(8-4), 2^(16-11)
- **Repo structure**: Same repo — `excel-addin/` directory inside qikit repo (monorepo). Shared fixtures at `fixtures/`.
- **Planned Experimentation visual parity**: Functional parity only (same calculations, modern Plotly/Chart.js styling). NOT visual parity with standard textbook catalog.
- **Educational content**: Not included. Analysis engine only.
- **Architecture rules**: Frozen results, `to_dict()` is the integration contract, no scipy. See `docs/roadmap.md`.
- **UI Design & Theme**: Fluent UI React v9. The UI will adapt automatically to the user's native Excel theme (Light Mode / Dark Mode).
- **Data Selection UX**: "Use Current Selection" as the primary data binding mechanic, with fallback manual range inputs. Inline preview of first 5 rows + data shape validation (see Section 5, UX Rules).
- **Output Location Options**: User will be prompted to choose between writing results to a new sheet or specifying a destination cell on the active sheet.
- **Task Pane State**: State will be persistent across open/close of the task pane, with per-step undo and a "Start New Analysis" button (with confirmation).
- **Chart Selection UX**: Data-description questionnaire that auto-resolves to the appropriate chart type (NOT a grid of chart type icons). Students don't know which chart to pick — the tool should guide them. Expert override available.
- **Results Interpretation**: Every results view must include a plain-language interpretation panel. This is NOT educational content — it is making the tool's own output readable by novices.
- **Starter Templates**: "Try an Example" button at the top of each flow that loads a classic dataset and pre-configures the wizard, using data already in `fixtures/`.
- **Build Tooling**: Vite (NOT Webpack). Unified JSON manifest (NOT XML). See Section 5.
- **Planned Experimentation Flow**: 3-step wizard (NOT 4-step). "Choose Design" merges into "Generate & Run".

---

## 2. SPC Code Review — Bugs Fixed (Phase 0 Complete)

All 6 issues below have been fixed and verified. 130 tests passing.

### Bug 1: Double-application of notes (medium severity)

**File**: `src/qikit/__init__.py`, lines 663-710

Notes are added twice: first as `df_dict["notes"]` (line 675) and again as `df["note"]` (line 707). The second application uses the *original* `notes` argument (not the MR-truncated version), causing:
- Length mismatch crash for MR charts with notes
- Duplicate column for all other charts

**Fix**: Remove the second application (lines 700-710). The `"notes"` column from `df_dict` already handles everything. The `render.py` code already reads both `"notes"` and `"note"` columns, so just keep `"notes"` and remove the `"note"` addition. Update `render.py` to only look for `"notes"`. Update tests that check for `"note"` column to check for `"notes"` instead.

### Bug 2: `_mark_oscillation` broadcast error (medium severity)

**File**: `src/qikit/core.py`, line 440

```python
np.all(signs[::2] == -signs[1::2])
```

When `threshold=14`, `diffs` has 13 elements, `signs[::2]` has 7 elements, `signs[1::2]` has 6. This causes a broadcast error.

**Fix**: Ensure both slices have the same length:
```python
even = signs[::2]
odd = signs[1::2]
min_len = min(len(even), len(odd))
if min_len == 0:
    continue
alternating = np.all(even[:min_len] != 0) and np.all(odd[:min_len] != 0) and np.all(even[:min_len] == -odd[:min_len])
```

### Bug 3: `_mark_zones` only marks trailing point (low severity)

**File**: `src/qikit/core.py`, lines 466-476

When "2 of 3 beyond 2 sigma" triggers, only point `i` is marked, not the contributing points. For full WECO/Nelson compliance, all points in the window that are beyond the zone should be flagged.

**Fix**: When the zone rule fires at position `i`, mark all points in `[i-window+1 : i+1]` that individually satisfy the beyond-zone condition.

### Bug 4: RuntimeWarning on all-NaN input

**File**: `src/qikit/core.py`, line 84

`_cl_median` with all-NaN input triggers `RuntimeWarning: All-NaN slice encountered`.

**Fix**: Add guard:
```python
def _cl_median(y_base, n_base):
    valid = y_base[~np.isnan(y_base)]
    if len(valid) == 0:
        return np.nan
    return float(np.nanmedian(valid))
```

### Improvement 1: Render.py duplication

**File**: `src/qikit/render.py`

`plot_result()` (lines 368-583) reimplements most of `_add_chart_traces()` (lines 41-163). Refactor `plot_result()` to delegate to `_add_chart_traces(fig, df, ..., row=None, col=None)` for the trace-adding logic, then add the single-panel-only extras (part boundaries, note annotations, layout).

### Improvement 2: Add `to_dict()` and `to_json()` to ParetoResult and BChartResult

These result types are missing serialization, breaking the "to_dict() is the integration contract" rule.

### Improvement 3: Validate x/y length match

When both `x` and `y` are raw lists (no DataFrame), validate `len(x) == len(y)`.

---

## 3. Cross-Language Testing Strategy

> Full details: [`docs/cross-language-testing.md`](cross-language-testing.md)

### Design

Each JSON file in `fixtures/` is a self-contained test case with four fields:

```json
{
  "id": "i_chart_basic",
  "reference": "Montgomery 2019, §6.2",
  "function": "qic",
  "input": { "y": [2,4,6,4,2,4,6,4], "chart": "i" },
  "check": { "cl": [4.0, 0.01], "ucl": [9.319, 0.01], "signals": false },
  "snapshot": { }
}
```

- **`check`** — human-authored, textbook-anchored values. Floats are `[value, tolerance]`. Never auto-updates. Catches math bugs.
- **`snapshot`** — machine-generated full `to_dict()` output. Auto-updates when check passes. Catches contract drift.

Both test suites auto-discover `fixtures/**/*.json`. One parametrized test function per language handles all fixtures — zero per-fixture boilerplate.

### Workflow

```bash
# Python validates check values (math correctness)
uv run pytest tests/test_conformance.py -v

# Regenerate snapshots (gated by check passing)
uv run python scripts/update_snapshots.py

# TypeScript validates check values + deep-matches snapshots
cd excel-addin && npm test
```

### Fixture Inventory — SPC (23 files)

Three categories of data provenance. Each fixture's `reference` field must record which category applies.

**Category A — Published textbook examples** (data and expected values in the book; externally verifiable):

| Fixture | Data source | `check` values |
|---------|-------------|----------------|
| `i_chart_montgomery` | Montgomery 8th Ed, Example 6.4 — Chemical Process Concentration. y=[102,94,101,105,108,103,104,107,105,106,101,103,107,105,104,108,100,106,108,107], cl=104.7 | CL=104.7, UCL≈114.21, LCL≈95.19 |
| `p_chart_montgomery` | Montgomery 8th Ed, Table 7.4 — Orange Juice Trial Limits. y=[12,15,8,10,4,7,16,9,14,10,5,6,17,12,22,8,10,5,13,11,20,18,24,15,9,12,7,13,9,6], n=[50]×30 | CL=0.2313, UCL=0.4102, LCL=0.0524 |
| `mr_chart_d4` | Montgomery 2019, §6.3 — D4 constant formula | UCL = 3.267 × MR̄ |
| `c_chart_ucl` | Montgomery 2019, §7.3 — c-chart formula | UCL = c̄ + 3√c̄ |
| `anhoej_thresholds` | Anhoej 2014 — run/crossing threshold formula | n=10→6, n=20→7, n=25→7, n=100→9 |
| `constants` | Montgomery 2019, Appendix VI — control chart constants | D2/D4/B3/B4/A3 for n=2..25; spot-check B4[25]=1.435 |

**Category B — Hand-calculated** (synthetic inputs chosen so the math is clean; check values computed by hand using published formulas, verifiable with a calculator):

| Fixture | Input data | `check` values | Formula source |
|---------|-----------|----------------|----------------|
| `i_chart_basic` | y=[2,4,6,4,2,4,6,4] — constant-step pattern | CL=4.0, MR̄=2.0, σ̂=1.7730, UCL=9.319, LCL=-1.319 | Montgomery §6.2 |
| `i_chart_mr_screening` | y=[74.030,74.002,74.019,73.992,74.008,73.995,74.009,74.010,73.998,74.025] — precision measurement data | CL=mean(y), UCL/LCL from screened MR̄/1.128 | Provost & Murray 2011, p.140 |
| `p_chart_equal_n` | y=[10]×20, n=[100]×20 — p̄=0.10 | CL=0.10, σ=0.03, UCL=0.19, LCL=0.01 | Montgomery §7.2 |
| `p_chart_low_p_floor` | y=[0.8]×20, n=[100]×20 — p̄=0.008 | LCL=0.0 (floored from negative) | Montgomery §7.2 |
| `p_chart_variable_n` | y=[5,8,3,…], n=[50,80,40,…] — varying denominator | variable UCL/LCL per point | Montgomery §7.2 |
| `u_chart_weighted` | y=[2,3,1,…], n=[100,150,80,…] | CL=Σy/Σn, variable limits | Montgomery §7.4 |
| `xbar_known_limits` | 5 subgroups of [9.5,10.5,9.5,10.5] — equal-SD subgroups | CL=10.0, S̄=0.5774, A3[4]=1.628, UCL=10.814, LCL=9.186 | Montgomery §6.4 |
| `s_chart_b3b4` | same 5 subgroups as xbar | UCL=B4[4]×S̄=2.266×0.5774, LCL=B3[4]×S̄=0 | Montgomery §6.4 |
| `weco_rules` | y=[10]×8+[5]×10 — 8 consecutive above CL | WECO Rule 4 triggered, signals=true | Western Electric 1956 |
| `nelson_rules` | y=[10]×9+[5]×10 — 9 consecutive above CL | Nelson Rule 2 triggered, signals=true | Nelson 1984 |
| `ihi_shift_trend` | y=[10]×8+[15]×8 — step shift | IHI shift (8-point run) triggered | Provost & Murray 2011 |
| `run_chart_signal` | y=[20]×10+[1]×10 — bimodal with long run | median=10.5, longest_run=10, threshold=7, signals=true | Anhoej 2014 |
| `run_chart_no_signal` | y=[12,8]×10 — alternating | many crossings, longest_run=1, signals=false | Anhoej 2014 |

**Category C — Structural/formula** (no published numeric example; `check` verifies formula application, not specific textbook numbers):

| Fixture | Input data | `check` values | Notes |
|---------|-----------|----------------|-------|
| `g_chart_median` | y=[3,1,5,2,8,1,4] — gap lengths | CL=median(y), UCL=CL+3√(CL(CL+1)) | Formula from Provost & Murray |
| `pp_laney_overdispersion` | Simulated overdispersed data (np.random.seed(42), n=10000, p_base=0.05, σ_extra=0.01, 20 subgroups) | UCL_pp > UCL_p (Laney limits wider than standard p) | Laney 2002 — structural check only |
| `up_laney_overdispersion` | Same pattern as pp but u-chart | UCL_up > UCL_u | Laney 2002 — structural check only |
| `t_chart_power_transform` | y=[1,3,7,2,14,5,9] — time-between-events | CL back-transforms correctly: CL_raw^3.6 ≈ median(y) | — |
| `bchart_basic` | y=[0,0,0,1,0,0,0,1], target=0.1, or_ratio=2.0 | or_ratio=2.0, limit confirmed, cusum_up column present | — |
| `pareto_basic` | x=["A","A","A","B","B","C"] | A=3 (50%), B=2 (83.3%), C=1 (100%), descending order | — |

### Fixture Inventory — Planned Experimentation (19 files, added with Planned Experimentation module)

All Planned Experimentation check values come from Box, Hunter & Hunter *Statistics for Experimenters* (2nd Ed) and Montgomery *Design and Analysis of Experiments*.

| Category | Fixtures | `check` values | Reference |
|----------|---------|----------------|-----------|
| Full factorial | `full_factorial_2x{2,3,4,5}` | n_runs=2^k, matrix orthogonality (column dot products=0), Yates order | BHH Ch5 |
| Fractional | `fractional_2x{3-1,4-1,5-1,5-2,7-3,7-4,8-4,16-11}` | resolution, generator strings, alias structure | Montgomery Ch8 |
| Effects | `effects_2x2_known`, `effects_2x3_known` | specific effect magnitudes from textbook examples | BHH Ch5: 2×2 → A=10.5, B=-7.5, AB=2.5 |
| Interactions | `interaction_detected`, `interaction_none` | interaction effect above/below noise threshold | BHH Ch6 |
| Other | `center_points`, `replication`, `one_factor` | run counts, row structure | Montgomery Ch11 |

---

## 4. Python Planned Experimentation Module

### Files to Create

- `src/qikit/planned_experimentation.py` — design generation + analysis engine (~400-500 lines)
- `src/qikit/experiment_render.py` — Plotly chart rendering (~400-500 lines)
- `tests/test_planned_experimentation.py` — tests
- Update `src/qikit/__init__.py` — add `from qikit import doe` and export Planned ExperimentationDesign, Planned ExperimentationResult

### Dataclasses

```python
# src/qikit/planned_experimentation.py

from __future__ import annotations
import itertools
import json
import math
from dataclasses import dataclass, field
from typing import Any, Literal, Sequence
import numpy as np
import pandas as pd

DesignType = Literal["full_factorial", "fractional", "one_factor"]

@dataclass(frozen=True)
class Planned ExperimentationDesign:
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

    def fill(self, response: Sequence[float]) -> Planned ExperimentationResult:
        """Fill response column and return analysis result."""
        return analyze(self, response)

    def to_dict(self) -> dict[str, Any]:
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
        return json.dumps(self.to_dict(), default=str)


@dataclass(frozen=True)
class Planned ExperimentationResult:
    """Immutable Planned Experimentation analysis result. Same pattern as SPCResult."""
    design: Planned ExperimentationDesign
    response: tuple[float, ...]
    effects: pd.DataFrame             # Columns: term, effect, abs_effect, pct_contribution
    residuals: np.ndarray
    grand_mean: float
    r_squared: float
    adj_r_squared: float
    summary: dict[str, Any]
    _plot_opts: dict[str, Any] = field(default_factory=dict, repr=False)

    def plot(self, chart: str = "effects", **kwargs) -> Any:
        from qikit.doe_render import plot_doe
        opts = {**self._plot_opts, **kwargs}
        return plot_doe(self, chart_type=chart, **opts)

    def to_dict(self) -> dict[str, Any]:
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
        return json.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        return f"Planned ExperimentationResult(design={self.design.design_type!r}, n_runs={self.design.n_runs}, R²={self.r_squared:.4f})"
```

### Public API

```python
def design(
    factors: list[str],
    lows: list[float] | None = None,
    highs: list[float] | None = None,
    design: str = "full_factorial",
    generators: list[str] | None = None,
    replicates: int = 1,
    center_points: int = 0,
    randomize: str = "none",          # "none" | "full" | "within_blocks"
    seed: int | None = None,
) -> Planned ExperimentationDesign:

def analyze(
    design_obj: Planned ExperimentationDesign,
    response: Sequence[float],
    max_interaction: int = 2,         # up to k-way (max 3)
) -> Planned ExperimentationResult:
```

### Design Matrix Generation

**Full factorial (Yates standard order):**

```python
def _yates_matrix(k: int) -> np.ndarray:
    """Generate 2^k full factorial in Yates standard order.

    Factor j alternates every 2^j rows.
    Row i, column j: -1 if (i // 2^j) % 2 == 0, else +1
    """
    n = 2 ** k
    matrix = np.empty((n, k), dtype=int)
    for j in range(k):
        matrix[:, j] = np.where(
            (np.arange(n) // (2 ** j)) % 2 == 0, -1, 1
        )
    return matrix
```

**Fractional factorial (generator catalog — full standard textbook catalog parity):**

```python
_GENERATORS: dict[tuple[int, int], tuple[list[str], int]] = {
    (3, 1): (["C=AB"], 3),                                              # 2^(3-1) Resolution III
    (4, 1): (["D=ABC"], 4),                                             # 2^(4-1) Resolution IV
    (5, 1): (["E=ABCD"], 5),                                            # 2^(5-1) Resolution V
    (5, 2): (["D=AB", "E=AC"], 3),                                      # 2^(5-2) Resolution III
    (7, 3): (["E=ABC", "F=BCD", "G=ACD"], 4),                           # 2^(7-3) Resolution IV
    (7, 4): (["D=AB", "E=AC", "F=BC", "G=ABC"], 3),                     # 2^(7-4) Resolution III
    (8, 4): (["E=BCD", "F=ACD", "G=ABC", "H=ABD"], 4),                  # 2^(8-4) Resolution IV
    (16, 11): (["F=ABCDE", "G=ABCD", "H=ABCE", "I=ABDE", "J=ACDE",     # 2^(16-11) Resolution III
                "K=BCDE", "L=ABC", "M=ABD", "N=ACD", "O=BCD", "P=ABCDE"], 3),
}

def _fractional_matrix(k: int, p: int, generators: list[str] | None) -> np.ndarray:
    """Generate 2^(k-p) fractional factorial.

    1. Build full factorial for base factors (first k-p factors) = 2^(k-p) rows
    2. For each generator "D=ABC", compute column D = col_A * col_B * col_C
    3. Append generated columns to base matrix
    """
    if generators is None:
        key = (k, p)
        if key not in _GENERATORS:
            raise ValueError(f"No standard generators for 2^({k}-{p}). Supply generators= explicitly.")
        generators, resolution = _GENERATORS[key]

    base_k = k - p
    base = _yates_matrix(base_k)  # 2^(k-p) rows, base_k columns

    # Parse generators and compute additional columns
    factor_labels = [chr(65 + i) for i in range(k)]  # A, B, C, ...
    base_labels = factor_labels[:base_k]

    generated_cols = []
    for gen in generators:
        # Parse "D=ABC" → target="D", source=["A","B","C"]
        parts = gen.replace(" ", "").split("=")
        target = parts[0]
        source_factors = list(parts[1])

        # Compute product of source columns
        col = np.ones(len(base), dtype=int)
        for sf in source_factors:
            idx = base_labels.index(sf)
            col *= base[:, idx]
        generated_cols.append(col)

    return np.column_stack([base] + generated_cols) if generated_cols else base
```

**Replication, center points, randomization:**

```python
# In design():
matrix = ...  # from _yates_matrix or _fractional_matrix

if replicates > 1:
    matrix = np.tile(matrix, (replicates, 1))

if center_points > 0:
    center_rows = np.zeros((center_points, k), dtype=int)
    matrix = np.vstack([matrix, center_rows])

n_runs = len(matrix)
if randomize == "full":
    rng = np.random.default_rng(seed)
    run_order = rng.permutation(n_runs) + 1
elif randomize == "within_blocks":
    # Each replicate is a block; shuffle within blocks
    ...
else:
    run_order = np.arange(1, n_runs + 1)
```

### Effects Calculation

```python
def _compute_effects(matrix: np.ndarray, response: np.ndarray,
                     factor_names: list[str], max_order: int) -> tuple[list[dict], float]:
    """Compute main effects and interactions up to max_order.

    For each term (main effect or interaction):
      Effect = (2/N) × Σ(contrast_column × response)
      SS_term = Effect² × N / 4
      % Contribution = 100 × SS_term / SS_total
    """
    n = len(response)
    y_bar = np.mean(response)
    ss_total = np.sum((response - y_bar) ** 2)
    terms = []

    for order in range(1, max_order + 1):
        for combo in itertools.combinations(range(len(factor_names)), order):
            label = ":".join(factor_names[i] for i in combo)

            # Interaction column = element-wise product of factor columns
            contrast_col = np.ones(n, dtype=float)
            for i in combo:
                contrast_col *= matrix[:, i]

            # Effect = 2/N × dot(contrast, response)
            effect = 2.0 * np.dot(contrast_col, response) / n
            ss = effect ** 2 * n / 4.0
            pct = 100.0 * ss / ss_total if ss_total > 0 else 0.0

            terms.append({
                "term": label,
                "effect": float(effect),
                "abs_effect": float(abs(effect)),
                "ss": float(ss),
                "pct_contribution": float(pct),
            })

    ss_model = sum(t["ss"] for t in terms)
    r_squared = ss_model / ss_total if ss_total > 0 else 0.0

    return terms, r_squared
```

**R-squared and residuals:**

```python
# In analyze():
terms, r_squared = _compute_effects(coded_matrix, response_arr, factor_names, max_interaction)

# Predicted values from the model
y_bar = np.mean(response_arr)
predicted = np.full(n, y_bar)
for t in terms:
    # Rebuild contrast column and add contribution
    ...  # sum of (effect/2) * contrast_col for each term

residuals = response_arr - predicted

p = len(terms)  # number of model terms
adj_r_squared = 1.0 - (1.0 - r_squared) * (n - 1) / (n - p - 1) if n > p + 1 else 0.0
```

### Planned Experimentation Chart Types (in `experiment_render.py`)

All reuse the Tufte theme from `render.py`. Extract a shared `_apply_theme(fig)`:

```python
def _apply_theme(fig: go.Figure) -> go.Figure:
    """Apply qikit Tufte theme: white bg, no borders, minimal grid."""
    fig.update_layout(
        plot_bgcolor="white", paper_bgcolor="white",
        showlegend=False,
        margin=dict(l=50, r=80, t=60, b=50),
    )
    fig.update_xaxes(showgrid=False, zeroline=False, showline=True, linecolor="#cccccc")
    fig.update_yaxes(showgrid=False, zeroline=False, showline=True, linecolor="#cccccc")
    return fig
```

| Chart | Function | Description |
|-------|----------|-------------|
| `effects` | `_plot_effects(result)` | Horizontal lollipop of abs(effect), sorted largest first, zero line, significant effects in red (#d62728) |
| `interaction` | `_plot_interaction(result, factors=(0,1))` | X=factor A levels (Low/High), lines=factor B levels; non-parallel = interaction |
| `cube` | `_plot_cube(result)` | 3D scatter with cube edges for 3 factors, 8 corners with response mean annotations. 2D square fallback for 2 factors. |
| `run_order` | `_plot_run_order(result)` | Response vs run order scatter + OLS regression line (np.polyfit degree 1) |
| `timeseries` | `_plot_timeseries(result)` | Delegates to `qic(y=response, chart="i")` — reuses existing SPC code |
| `dot_diagram` | `_plot_dot_diagram(result)` | Horizontal strip of all response values |
| `single_factor` | `_plot_single_factor(result, factor)` | Mean response at each level for 1-factor experiments |
| `line_effects` | `_plot_line_effects(result)` | Design order vs response scatter |
| `extended_cube` | `_plot_extended_cube(result)` | Enhanced cube for 4-factor designs with face annotations |

### Planned Experimentation Tests

```
tests/test_planned_experimentation.py:
  TestDesignMatrix:
    test_full_factorial_2x2_yates_order    ← fixture
    test_full_factorial_2x3_yates_order    ← fixture
    test_full_factorial_2x4               ← fixture
    test_full_factorial_2x5               ← fixture
    test_fractional_2x4_1                 ← fixture
    test_fractional_2x5_2                 ← fixture
    test_fractional_2x7_4                 ← fixture
    test_fractional_2x8_4                 ← fixture
    test_fractional_2x16_11               ← fixture
    test_replication_doubles_rows
    test_center_points_added
    test_randomize_shuffles_order
    test_columns_orthogonal               ← property: dot(col_i, col_j) == 0 for i≠j

  TestEffects:
    test_effects_2x2_known               ← fixture (Box, Hunter & Hunter)
    test_effects_2x3_known               ← fixture
    test_interaction_detected            ← fixture: non-parallel interaction lines
    test_no_interaction_parallel         ← fixture: parallel lines = no interaction
    test_r_squared_full_model
    test_pct_contribution_sums_to_100

  TestPlanned ExperimentationResult:
    test_frozen                          ← cannot mutate result
    test_to_dict_serializable            ← json.dumps succeeds
    test_to_json_parseable               ← json.loads(result.to_json())
    test_fill_from_design                ← design.fill(response) returns Planned ExperimentationResult
    test_repr

  TestPlanned ExperimentationCharts:
    test_effects_plot_returns_figure
    test_interaction_plot_returns_figure
    test_cube_plot_returns_figure
    test_timeseries_delegates_to_qic
    test_run_order_plot_returns_figure
    test_dot_diagram_returns_figure
```

---

## 5. TypeScript Excel Add-in

### Project Structure

Uses **npm workspaces** to cleanly separate the pure-math engine from the Office.js/React UI. The engine package has ZERO dependencies on Office.js, React, or DOM and can be tested independently.

```
excel-addin/
  package.json                     # Workspace root: { "workspaces": ["packages/*"] }
  vite.config.ts                   # Vite build config (~15 lines, see Build Tooling)
  manifest.json                    # Unified JSON manifest (NOT XML — see Manifest section)
  taskpane.html                    # Entry HTML (loads Office.js CDN + Vite bundle)

  packages/
    engine/                        # @qikit/engine — pure math, independently testable
      package.json                 # "name": "@qikit/engine", zero browser/Office deps
      src/
        constants.ts               # D2, D4, B3, B4, A3 tables (verbatim from core.py)
        spc-types.ts               # SPCInput, SPCResult, ChartSpec interfaces
        spc-core.ts                # compute() + all 12 chart specs
        spc-helpers.ts             # nanmean, nanmedian, movingRanges, screenedMeanMR, binomCoeff
        signals.ts                 # anhoej, ihi, weco, nelson — all 4 methods
        bchart.ts                  # Bernoulli CUSUM
        paretochart.ts             # Pareto chart computation
        doe-types.ts               # Planned ExperimentationDesign, Planned ExperimentationResult interfaces
        doe-core.ts                # yatesMatrix, fractionalMatrix, createDesign()
        doe-analyze.ts             # effects calculation, analyzeDesign()
        index.ts                   # Public re-exports
      tests/
        spc-core.test.ts           # Validates against fixtures/spc/*.json
        signals.test.ts
        bchart.test.ts
        doe-core.test.ts           # Validates against fixtures/experiment/*.json
        doe-analyze.test.ts
        fixture-loader.ts          # Reads ../../../fixtures/ JSON files

    addin/                         # Office.js + React UI — depends on @qikit/engine
      package.json                 # depends on "@qikit/engine": "workspace:*"
      src/
        excel/                     # Office.js integration (thin adapter layer)
          excel-io.ts              # Read ranges, write results to sheets
          chart-builder.ts         # Create Excel native charts from result data
          range-utils.ts           # Range address parsing/validation

        ui/                        # React task pane UI (Fluent UI React v9)
          App.tsx                   # Top-level: SPC mode / Planned Experimentation mode toggle
          spc/
            SpcWizard.tsx           # 3-step: select data → configure → results
            DataDescriber.tsx       # Questionnaire-based chart type resolver (see UX Rules)
            DataPreview.tsx         # Inline 5-row preview + validation warnings
            SignalMethodSelector.tsx
            DataRangeInput.tsx      # Excel range picker with validation
            ResultsPanel.tsx        # Chart + interpretation + actions
          doe/
            DoeWizard.tsx           # 3-step: define factors → generate & run → results
            FactorEditor.tsx        # Factor name/low/high input rows
            DesignConfigurator.tsx   # Full/fractional toggle + run count badge (inline, not a separate step)
            EffectsDisplay.tsx      # Effects table + chart
            ResultsPanel.tsx        # Charts + interpretation + actions
          shared/
            StepIndicator.tsx
            ChartViewer.tsx         # Renders charts in task pane (Chart.js)
            ResultsTable.tsx
            InterpretationPanel.tsx  # Plain-language results interpretation (reused by SPC + DOE)
            TooltipHelp.tsx         # Contextual ? icon with hover explanations
            ExampleLoader.tsx       # "Try an Example" button — loads fixture data into sheet

        dev-harness.tsx            # Browser-only dev mode (mocks Office.context — DEV BUILDS ONLY)
        index.ts                   # Office.initialize entry point

  assets/
    icon-16.png, icon-32.png, icon-80.png
```

> **Why workspaces?** The engine already has zero Office.js/React imports by design. Making this a workspace package means engine tests run without any DOM/Office mocking (just `vitest` in `packages/engine/`), and the engine can be consumed by other frontends later without extraction surgery. Build caching also improves — the engine only rebuilds when engine code changes.

### TypeScript SPC Types

```typescript
// engine/spc-types.ts

export type ChartType =
  | 'run' | 'i' | 'ip' | 'mr' | 's' | 'p' | 'u' | 'c' | 'g'
  | 'pp' | 'up' | 'xbar' | 't';

export type SignalMethod = 'anhoej' | 'ihi' | 'weco' | 'nelson';

export interface SPCInput {
  y: number[];
  n?: number[];
  chart: ChartType;
  method?: SignalMethod;         // default 'anhoej'
  freeze?: number;               // 1-based
  part?: number[];               // 1-based boundaries
  exclude?: number[];            // 1-based indices
  clOverride?: number;
  multiply?: number;
  sBar?: number;                 // pre-computed for xbar
  subgroupN?: number;            // for xbar/s
}

export interface SPCResult {
  y: number[];
  cl: number[];
  ucl: number[];
  lcl: number[];
  sigmaSignal: boolean[];
  runsSignal: boolean[];
  signals: boolean;
  summary: Record<string, unknown>;
}

export interface ChartSpec {
  center: (yBase: number[], nBase?: number[]) => number;
  limits: (cl: number, y: number[], n: number[] | undefined,
           mask: boolean[], subgroupN?: number, sBar?: number) => [number[], number[]];
  needsN: boolean;
  floorLcl: boolean;
}
```

### TypeScript SPC Engine

**`engine/constants.ts`** — verbatim copy of Python tables:
```typescript
export const D2: Record<number, number> = { 2: 1.128 };
export const D4: Record<number, number> = { 2: 3.267 };
export const B3: Record<number, number> = {
  2: 0.000, 3: 0.000, 4: 0.000, 5: 0.000, 6: 0.030, 7: 0.118, 8: 0.185,
  9: 0.239, 10: 0.284, 11: 0.321, 12: 0.354, 13: 0.382, 14: 0.406,
  15: 0.428, 16: 0.448, 17: 0.466, 18: 0.482, 19: 0.497, 20: 0.510,
  21: 0.523, 22: 0.534, 23: 0.545, 24: 0.555, 25: 0.565,
};
export const B4: Record<number, number> = {
  2: 3.267, 3: 2.568, 4: 2.266, 5: 2.089, 6: 1.970, 7: 1.882, 8: 1.815,
  9: 1.761, 10: 1.716, 11: 1.679, 12: 1.646, 13: 1.618, 14: 1.594,
  15: 1.572, 16: 1.552, 17: 1.534, 18: 1.518, 19: 1.503, 20: 1.490,
  21: 1.477, 22: 1.466, 23: 1.455, 24: 1.445, 25: 1.435,
};
export const A3: Record<number, number> = {
  2: 2.659, 3: 1.954, 4: 1.628, 5: 1.427, 6: 1.287, 7: 1.182, 8: 1.099,
  9: 1.032, 10: 0.975, 11: 0.927, 12: 0.886, 13: 0.850, 14: 0.817,
  15: 0.789, 16: 0.763, 17: 0.739, 18: 0.718, 19: 0.698, 20: 0.680,
  21: 0.663, 22: 0.647, 23: 0.633, 24: 0.619, 25: 0.606,
};
```

**`engine/spc-helpers.ts`** — numpy replacements:
```typescript
export function nanmean(arr: number[]): number {
  const valid = arr.filter(v => !isNaN(v));
  return valid.length === 0 ? NaN : valid.reduce((a, b) => a + b, 0) / valid.length;
}

export function nanmedian(arr: number[]): number {
  const valid = arr.filter(v => !isNaN(v)).sort((a, b) => a - b);
  if (valid.length === 0) return NaN;
  const mid = Math.floor(valid.length / 2);
  return valid.length % 2 !== 0 ? valid[mid] : (valid[mid - 1] + valid[mid]) / 2;
}

export function movingRanges(y: number[]): number[] {
  return y.slice(1).map((v, i) => Math.abs(v - y[i]));
}

export function screenedMeanMR(y: number[], mask: boolean[]): number {
  const valid = y.filter((_, i) => mask[i] && !isNaN(y[i]));
  if (valid.length < 2) return NaN;
  const mrs = movingRanges(valid);
  const mrBar = nanmean(mrs);
  const screened = mrs.filter(m => m <= D4[2] * mrBar);
  return screened.length > 0 ? nanmean(screened) : mrBar;
}

export function binomCoeff(n: number, k: number): number {
  if (k > n) return 0;
  if (k === 0 || k === n) return 1;
  let result = 1;
  for (let i = 0; i < Math.min(k, n - k); i++) {
    result = result * (n - i) / (i + 1);
  }
  return Math.round(result);
}
```

**`engine/spc-core.ts`** — same CHARTS dict pattern as Python:
```typescript
export const CHARTS: Record<string, ChartSpec> = {
  run:  { center: clMedian, limits: noLimits, needsN: false, floorLcl: false },
  i:    { center: clMean,   limits: iLimits,  needsN: false, floorLcl: false },
  ip:   { center: clWeighted, limits: iLimits, needsN: true, floorLcl: false },
  mr:   { center: clMean,   limits: mrLimits, needsN: false, floorLcl: false },
  s:    { center: clMean,   limits: sLimits,  needsN: false, floorLcl: false },
  p:    { center: clWeighted, limits: pLimits, needsN: true, floorLcl: true },
  u:    { center: clWeighted, limits: uLimits, needsN: true, floorLcl: true },
  c:    { center: clMean,   limits: cLimits,  needsN: false, floorLcl: true },
  g:    { center: clMedian, limits: gLimits,  needsN: false, floorLcl: true },
  pp:   { center: clWeighted, limits: ppLimits, needsN: true, floorLcl: true },
  up:   { center: clWeighted, limits: upLimits, needsN: true, floorLcl: true },
  xbar: { center: clMean,   limits: xbarLimits, needsN: false, floorLcl: false },
};

export function compute(input: SPCInput): SPCResult { ... }
```

The `compute()` function must handle all of these (matching Python `qic()` logic):
- Baseline mask from freeze/part/exclude
- MR transform for chart='mr' (y → abs(diff(y)), x shortened by 1)
- Proportion transform for p/u/pp/up/ip (y = y/n)
- Power transform for chart='t' (y^(1/3.6), compute as 'i', back-transform)
- Multi-part: independent CL/limits per segment
- Signal detection dispatch based on method

**`engine/signals.ts`** — all 4 signal methods:
```typescript
// Anhoej thresholds
export function longestRunThreshold(n: number): number {
  if (n < 10) return n + 1;  // effectively impossible
  return Math.floor(Math.log2(n)) + 3;
}

export function crossingsThreshold(n: number): number {
  if (n < 10) return -1;
  const trials = n - 1;
  let cumprob = 0;
  for (let k = 0; k <= trials; k++) {
    cumprob += binomCoeff(trials, k) * Math.pow(0.5, trials);
    if (cumprob > 0.05) return k - 1;
  }
  return 0;
}

// Detection functions
export function longestRun(y: number[], cl: number[]): number;
export function countCrossings(y: number[], cl: number[]): number;
export function markLongRuns(y: number[], cl: number[], threshold: number): boolean[];
export function markTrends(y: number[], threshold: number): boolean[];
export function markOscillation(y: number[], threshold: number): boolean[];
export function markZones(y: number[], cl: number[], ucl: number[],
                          nBeyond: number, window: number, sigmaMult: number): boolean[];
export function markStratification(y: number[], cl: number[], ucl: number[], threshold: number): boolean[];
export function markMixture(y: number[], cl: number[], ucl: number[], threshold: number): boolean[];

// Dispatch
export function detectSignals(y: number[], cl: number[], method: SignalMethod,
                              ucl?: number[], lcl?: number[]): {
  signal: boolean[];
  summary: Record<string, unknown>;
};
```

### TypeScript Planned Experimentation Engine

**`engine/doe-core.ts`:**
```typescript
export function yatesMatrix(k: number): number[][] {
  const n = Math.pow(2, k);
  const matrix: number[][] = [];
  for (let i = 0; i < n; i++) {
    const row: number[] = [];
    for (let j = 0; j < k; j++) {
      row.push(Math.floor(i / Math.pow(2, j)) % 2 === 0 ? -1 : 1);
    }
    matrix.push(row);
  }
  return matrix;
}

// Generator catalog — same as Python, full standard textbook catalog parity
const STANDARD_GENERATORS: Record<string, { generators: string[]; resolution: number }> = {
  '3-1': { generators: ['C=AB'], resolution: 3 },
  '4-1': { generators: ['D=ABC'], resolution: 4 },
  '5-1': { generators: ['E=ABCD'], resolution: 5 },
  '5-2': { generators: ['D=AB', 'E=AC'], resolution: 3 },
  '7-3': { generators: ['E=ABC', 'F=BCD', 'G=ACD'], resolution: 4 },
  '7-4': { generators: ['D=AB', 'E=AC', 'F=BC', 'G=ABC'], resolution: 3 },
  '8-4': { generators: ['E=BCD', 'F=ACD', 'G=ABC', 'H=ABD'], resolution: 4 },
  '16-11': { generators: ['F=ABCDE','G=ABCD','H=ABCE','I=ABDE','J=ACDE',
             'K=BCDE','L=ABC','M=ABD','N=ACD','O=BCD','P=ABCDE'], resolution: 3 },
};

export function fractionalMatrix(k: number, p: number, generators?: string[]): number[][];
export function createDesign(opts: DesignOptions): Planned ExperimentationDesign;
```

**`engine/doe-analyze.ts`:**
```typescript
export function analyzeDesign(design: Planned ExperimentationDesign, response: number[],
                              maxInteraction?: number): Planned ExperimentationResult;
// Uses same formula: Effect = (2/N) × dot(contrast_col, response)
```

### Excel Integration

**`excel/excel-io.ts`:**
```typescript
export async function readColumn(rangeAddress: string): Promise<number[]>;
export async function readRange(rangeAddress: string): Promise<number[][]>;
export async function writeSPCResult(result: SPCResult, sheetName: string): Promise<void>;
export async function writePlanned ExperimentationDesign(design: Planned ExperimentationDesign): Promise<void>;
export async function readPlanned ExperimentationResponse(design: Planned ExperimentationDesign, responseCol: string): Promise<number[]>;
export async function writePlanned ExperimentationResult(result: Planned ExperimentationResult, sheetName: string): Promise<void>;
```

**`excel/chart-builder.ts`:**
```typescript
export async function createSPCChart(result: SPCResult, dataRange: string): Promise<void>;
export async function createEffectsChart(result: Planned ExperimentationResult): Promise<void>;
export async function createInteractionChart(result: Planned ExperimentationResult, factors: [string, string]): Promise<void>;
```

### UI Design

Task pane: 300-350px wide. **Fluent UI React v9** (Microsoft's latest design system) for native Excel look. The UI will adapt automatically to the user's native Excel theme (Light Mode / Dark Mode). State will be persistently remembered across task pane open/close sessions. Per-step undo is supported (clicking a completed step re-opens it without losing downstream state until something actually changes). A "Start New Analysis" button (with confirmation dialog) replaces the old "Clear/Reset" approach.

**In-Pane Charting:** Interactive, highly polished previews rendered via **Chart.js**, utilizing a clean "Tufte-style" theme.

**Progressive Disclosure / Vertical Stepper Patterns:** Instead of rigid Next/Back wizards, both flows will use an accordion or vertical stepper allowing users to quickly jump between steps without losing context.

**"Try an Example" Button:** Both SPC and DOE flows have a prominent "Try an Example" button at the top that loads a classic dataset into a new sheet and pre-configures the wizard. SPC example: Montgomery's orange juice concentration data (already in `fixtures/`). DOE example: BHH 2-factor pilot plant data (already in `fixtures/`). This massively reduces time-to-first-success for students.

#### UX Rules for Student Users

These rules are **mandatory** for all UI implementation. The target user is a student learning quality improvement methods, not an SPC expert.

1. **Never ask the user to pick a chart type directly.** Instead, use a short data-description questionnaire (`DataDescriber.tsx`) that resolves to the correct chart:
   - "What are you measuring?" → Counts / Proportions / Continuous / Time between events
   - "Is your sample size constant?" → Yes / No
   - "How many observations per sample?" → 1 / 2–25 / Varies
   - Display the resolved chart type with a one-sentence explanation: *"Based on your answers: **I-MR chart** — for individual continuous measurements."*
   - Provide an "I know which chart I want" link that reveals a direct selector for expert users.

2. **Always show a data preview after selection.** `DataPreview.tsx` shows the first 5 rows in a mini-table immediately after "Use Current Selection". Flag common mistakes: *"Your selection includes text in column A — this will be used as labels."*, *"Warning: 12 blank cells detected."*, *"3 columns detected: Labels | Data | Denominators"*.

3. **Every results view must include an `InterpretationPanel`.** This is a plain-language summary beneath the chart, not educational content:
   - SPC: *"3 points are outside the control limits, suggesting special-cause variation. Investigate what changed at points 12, 17, and 23."*
   - DOE: *"Factor A (Temperature) has the largest effect (10.5 units). The A:B interaction is also significant — the effect of Temperature depends on Pressure."*
   - The panel is generated from the result data programmatically (not hardcoded strings).

4. **Contextual tooltips on every non-obvious term.** `TooltipHelp.tsx` renders a `?` icon next to technical terms with hover explanations:
   - "Freeze baseline" → *"Use only the first N points to calculate control limits. Useful when comparing new data against a known stable period."*
   - "Anhoej" → *"Default signal detection. Looks for unusually long runs and too few crossings of the center line."*
   - "Resolution III" → *"Main effects are confounded with 2-factor interactions. Use for screening designs with many factors."*

5. **Never require sideloading for UI development.** The `dev-harness.tsx` mocks `Office.context.document` with an in-memory grid, so the full UI can be developed and demoed in a browser tab. Relevant for Chromebook/lab environments where students may not have desktop Excel.

#### SPC Flow (3 steps)

1. **Select Data**: Dominant "Use Current Selection" button as the primary data binding, capturing the active Excel range automatically. Immediately shows `DataPreview.tsx` with first 5 rows + shape info (e.g., `A1:A50 — 50 rows, 1 column`). Auto-detect logic: if 3 columns selected, assume Labels, Data, and Denominators. Fallback manual input fields available.
2. **Describe & Configure**: `DataDescriber.tsx` questionnaire auto-resolves chart type (see UX Rule 1). Advanced settings (baseline, signal methods like Anhoej/IHI/WECO/Nelson) are hidden behind an "Advanced Options" toggle to keep the view clean. Each option has a `TooltipHelp` icon.
3. **Results**: In-pane Chart.js preview. `InterpretationPanel` with plain-language summary (see UX Rule 3). Summary pill (e.g., "3 Signals Detected"). Primary actions: "Insert Chart to Sheet" and "Write Data to Sheet". User can choose output location: New Sheet or specify a Destination Cell.

#### Planned Experimentation Flow (3 steps)

> The old 4-step flow ("Define Factors → Choose Design → Run Experiment → Analyze") is replaced with 3 steps. "Choose Design" merges into "Generate & Run" because students don't need to contemplate the design matrix before generating the template — and for 2–3 factors there's only one reasonable choice anyway.

1. **Define Factors**: Dynamic, inline-editable list to tab through Factor Name, Low, and High values. Quick-add row at the bottom. `TooltipHelp` on "Low"/"High": *"The two levels you want to test for this factor."*
2. **Generate & Run**: Full/fractional toggle with immediate feedback badge (e.g., "16 Runs Required"). Replicates, center points, randomize options (collapsed by default). "Generate Template Sheet" button creates a formatted worksheet with randomized run order, headers, and an empty "Response" column. Once the template exists, a "Read Results" button appears in-place.
3. **Results**: `InterpretationPanel` with plain-language effect summary (see UX Rule 3). Tabbed view of generated charts (Effects Pareto with significance threshold line, Interaction lines) to preview in-pane. Actions: "Insert Chart to Sheet" and "Write Results to Sheet" (with prompt for New Sheet vs Destination Cell).

### Manifest and Distribution

Use the **unified JSON manifest** (NOT the legacy XML format). This is Microsoft's current recommendation, is shorter, easier to read, and supports Teams Marketplace distribution:

```json
{
  "$schema": "https://developer.microsoft.com/json-schemas/teams/vDevPreview/MicrosoftTeams.schema.json",
  "manifestVersion": "devPreview",
  "version": "1.0.0",
  "id": "qikit-spc-doe",
  "developer": {
    "name": "qikit",
    "websiteUrl": "https://github.com/your-org/qikit",
    "privacyUrl": "https://github.com/your-org/qikit/privacy",
    "termsOfUseUrl": "https://github.com/your-org/qikit/terms"
  },
  "name": { "short": "QI Kit", "full": "QI Kit — SPC & Planned Experimentation" },
  "description": {
    "short": "SPC charts and DOE for quality improvement",
    "full": "Statistical Process Control charts and Design of Experiments for quality improvement in healthcare and manufacturing."
  },
  "icons": { "outline": "assets/icon-32.png", "color": "assets/icon-80.png" },
  "accentColor": "#4F6BED",
  "extensions": [
    {
      "requirements": {
        "capabilities": [{ "name": "Workbook", "minVersion": "1.1" }]
      },
      "runtimes": [
        { "id": "TaskPaneRuntime", "type": "general", "code": { "page": "https://your-host.com/taskpane.html" } }
      ],
      "ribbons": [
        {
          "contexts": ["default"],
          "tabs": [
            {
              "id": "QIKitTab",
              "label": "QI Kit",
              "groups": [
                {
                  "id": "QIKitGroup",
                  "label": "Analysis",
                  "icons": [{ "size": 16, "url": "assets/icon-16.png" }, { "size": 32, "url": "assets/icon-32.png" }],
                  "controls": [
                    {
                      "id": "OpenTaskPane",
                      "type": "button",
                      "label": "Open QI Kit",
                      "icons": [{ "size": 16, "url": "assets/icon-16.png" }, { "size": 32, "url": "assets/icon-32.png" }],
                      "actionId": "TaskPaneRuntime"
                    }
                  ]
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

**Distribution** (for hospital QI staff):
1. **Centralized deployment** (recommended): IT admin uploads to Microsoft 365 admin center → auto-deployed
2. **Sideload**: Share manifest.json + hosted URL
3. **AppSource / Teams Marketplace**: Public listing (requires Microsoft review) — JSON manifest supports this natively

**Hosting**: Static files on any HTTPS endpoint. Azure Static Web Apps (free tier), GitHub Pages, or hospital intranet with SSL.

### Build Tooling

**Vite replaces Webpack.** Webpack requires verbose configuration (webpack.config.js, ts-loader, html-webpack-plugin, dev-server SSL setup). Vite handles all of this out of the box: sub-second HMR, native ESM in dev, Rollup-based production builds with automatic tree-shaking and code-splitting. No ts-loader, no webpack config file.

**`office-addin-mock` is NOT used.** The engine has zero Office.js dependency by design, so engine tests need no mocking. The thin `excel-io.ts` adapter layer uses Vitest's built-in `vi.mock()` for the handful of integration tests that need it.

**Workspace root `package.json`:**
```json
{
  "private": true,
  "workspaces": ["packages/*"],
  "scripts": {
    "dev": "vite --https",
    "build": "vite build",
    "preview": "vite preview",
    "test": "vitest",
    "test:engine": "vitest --project engine",
    "test:addin": "vitest --project addin",
    "sideload": "office-addin-debugging start manifest.json",
    "validate": "office-addin-manifest validate manifest.json"
  }
}
```

**`packages/engine/package.json`:**
```json
{
  "name": "@qikit/engine",
  "version": "1.0.0",
  "private": true,
  "type": "module",
  "main": "src/index.ts",
  "devDependencies": {
    "typescript": "^5.x",
    "vitest": "^3.x"
  }
}
```

**`packages/addin/package.json`:**
```json
{
  "name": "@qikit/addin",
  "version": "1.0.0",
  "private": true,
  "dependencies": {
    "@qikit/engine": "workspace:*",
    "@fluentui/react-components": "^9.x",
    "react": "^18.x",
    "react-dom": "^18.x",
    "chart.js": "^4.x"
  },
  "devDependencies": {
    "typescript": "^5.x",
    "@types/office-js": "^1.x",
    "@types/react": "^18.x",
    "@types/react-dom": "^18.x"
  }
}
```

**`vite.config.ts` (workspace root):**
```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import mkcert from 'vite-plugin-mkcert'

export default defineConfig({
  plugins: [react(), mkcert()],
  root: 'packages/addin',
  build: {
    outDir: '../../dist',
    rollupOptions: { input: 'taskpane.html' },
  },
  server: { https: true, port: 3000 },
  resolve: {
    alias: { '@qikit/engine': '../engine/src' },
  },
})
```

**Root `devDependencies`:**
```json
{
  "devDependencies": {
    "vite": "^6.x",
    "vitest": "^3.x",
    "@vitejs/plugin-react": "^4.x",
    "vite-plugin-mkcert": "^1.x"
  }
}
```
```

---

## 6. Implementation Phases

### Phase 0: SPC Bug Fixes — COMPLETE (2026-03-15)

All 6 issues fixed. 130 tests passing. See Section 2 for details.

### Phase 1: Shared Fixtures + Python Planned Experimentation Core — COMPLETE (2026-03-16)

**1a. SPC Fixtures (no Planned Experimentation dependency):**
- [x] 1. Create `fixtures/spc/` directory
- [x] 2. Author 23 SPC fixture JSON files (`id`, `reference`, `function`, `input`, `check`)
- [x] 3. Write `scripts/update_snapshots.py` — populates `snapshot` fields
- [x] 4. Write `tests/test_conformance.py` — parametrized test for all fixtures
- [x] 5. Run `update_snapshots.py` to populate snapshots

**1b. Python Planned Experimentation Core:**
- [x] 6. Implement `src/qikit/doe.py` (Design Matrix generation & Effects analysis)
- [x] 7. Create `fixtures/experiment/` directory, author Planned Experimentation fixture JSON files
- [x] 8. Write `tests/test_doe.py` (validating against fixtures)

### Phase 2: TypeScript SPC Engine — COMPLETE (2026-03-16)

- [x] 1. Scaffold `excel-addin/` workspace structure
- [x] 2. Implement `packages/engine/src/constants.ts` (verbatim port)
- [x] 3. Implement `packages/engine/src/spc-helpers.ts`
- [x] 4. Implement `packages/engine/src/spc-core.ts` (12 ChartSpecs + compute())
- [x] 5. Implement `packages/engine/src/signals.ts` (all 4 methods)
- [x] 6. Implement `packages/engine/src/bchart.ts`
- [x] 7. Write `packages/engine/tests/conformance.test.ts` (validates against fixtures)

### Phase 3: Python Planned Experimentation Rendering + TypeScript Planned Experimentation — COMPLETE (2026-03-16)

- [x] 1. Implement `src/qikit/render/doe_plots.py` (9 chart types)
- [x] 2. Extract `apply_tufte_theme()` in `utils.py` for shared use
- [x] 3. Update `src/qikit/__init__.py` exports
- [x] 4. Implement TypeScript `doe-core.ts` + `doe-analyze.ts`
- [x] 5. Validate TS Planned Experimentation against fixtures (`doe-conformance.test.ts`)

### Phase 4: Excel Add-in UI — IN PROGRESS

> **Key principle:** The target user is a student, not an expert. All UX Rules from Section 5 are mandatory. Do not skip the interpretation panel, data preview, contextual tooltips, or chart-type questionnaire.

- [x] 1. Set up Office.js project: `manifest.json`, `taskpane.html`, Vite config
- [x] 2. Implement browser dev harness (`dev-harness.tsx`)
- [x] 3. Implement `excel-io.ts` (range read/write)
- [x] 4. Implement shared components:
   - [x] `TooltipHelp.tsx`
   - [x] `InterpretationPanel.tsx`
   - [x] `ExampleLoader.tsx`
   - [x] `DataPreview.tsx`
   - [x] `ChartViewer.tsx` (Chart.js rendering)
   - [x] `StepIndicator.tsx`
- [ ] 5. Implement SPC flow:
   - [x] `DataDescriber.tsx` (questionnaire-based)
   - [x] `SpcWizard.tsx` (orchestration)
   - [ ] Final wiring to engine and data selection
- [ ] 6. Implement DOE flow:
   - [x] `FactorEditor.tsx`
   - [x] `DesignConfigurator.tsx`
   - [x] `DoeWizard.tsx` (orchestration)
   - [ ] Final wiring to engine and template generation
- [x] 7. Implement `chart-builder.ts` (Excel native charts)
- [ ] 8. End-to-end testing: sideloaded add-in verification

### Phase 5: Polish + Distribution — PLANNED

- [ ] 1. Error handling and input validation throughout
- [ ] 2. Build optimization
- [ ] 3. Set up HTTPS hosting
- [ ] 4. Centralized deployment documentation
- [ ] 5. Interpretation panel content review

### Dependency Graph

```
Phase 0 (COMPLETE) ──→ Phase 1 (COMPLETE) ──┐
                                            ├──→ Phase 3 (COMPLETE) ──→ Phase 4 (IN PROGRESS) ──→ Phase 5 (PLANNED)
                        Phase 2 (COMPLETE) ─┘
```

Phase 0 is complete — all bug fixes verified.
Phases 1, 2, and 3 are complete and verified via cross-language fixture tests.
Phase 4 is in progress, with core components built and orchestration wizards drafted.
Phase 4 depends on Phase 3. **Phase 4 implementer MUST read the UX Rules in Section 5 before writing any UI code.**

---

## 7. Verification Strategy

> See also: [`docs/cross-language-testing.md`](cross-language-testing.md) for the full fixture design.

### Cross-Validation Pipeline

```bash
# CI job
cd /Users/davidvandyke/repos/qikit

# Python: unit tests + fixture conformance (check values)
uv run pytest tests/ -v

# TypeScript engine tests (no Office.js/DOM dependency — runs standalone)
cd excel-addin && npm run test:engine

# TypeScript full suite
cd excel-addin && npm test

# After Python changes: regenerate snapshots (gated by check passing)
uv run python scripts/update_snapshots.py
```

### Property-Based Tests (implement in both Python and TypeScript)

| Property | Applies to |
|----------|-----------|
| UCL > CL > LCL (where limits exist) | All control charts |
| CL within range of non-NaN y values | All charts |
| LCL >= 0 | c, g, p, u, pp, up (floor_lcl charts) |
| Signal arrays same length as y | All charts |
| Design matrix has exactly 2^k rows | Full factorial |
| All factor columns orthogonal (dot product = 0) | All 2-level designs |
| Effects: SS_model <= SS_total | All Planned Experimentation analyses |
| Yates order: column j alternates every 2^j rows | Full factorial |
| Replicated design has n_replicates × base_runs rows | Replicated designs |

### Numerical Edge Cases (both implementations must handle)

- All-same values (zero variance) → CL at that value, zero-width limits
- Single data point → no crash
- NaN values in y → propagate correctly, don't corrupt CL/limits
- Zero denominators with nonzero y → raise error
- Very small p̄ → LCL floored to 0
- Large n in binomial coefficient → no overflow (use logarithmic computation)
- MR screening removes all MRs → fallback to unscreened
- Empty response array → raise error
- All points excluded → graceful handling

---

## 8. SPC Formula Reference

Complete formulas for implementing agent. All from Montgomery (2019) and Anhoej (2014).

### Center Lines
| Chart | Formula |
|-------|---------|
| run | CL = median(y_baseline) |
| i, mr, c, s, xbar | CL = mean(y_baseline) |
| p, u, pp, up, ip | CL = sum(y_baseline × n_baseline) / sum(n_baseline) |
| g | CL = median(y_baseline) |

### Control Limits
| Chart | UCL | LCL | Notes |
|-------|-----|-----|-------|
| run | NaN | NaN | No limits |
| i | CL + 3σ̂ | CL - 3σ̂ | σ̂ = screened_MR̄/1.128 |
| ip | CL + 3σ̂ | CL - 3σ̂ | Same as i, but CL is weighted mean |
| mr | 3.267 × CL | NaN | D4[2]=3.267, no LCL (D3=0) |
| p | CL + 3√(CL(1-CL)/nᵢ) | max(0, CL - 3√(CL(1-CL)/nᵢ)) | Variable limits per point |
| u | CL + 3√(CL/nᵢ) | max(0, CL - 3√(CL/nᵢ)) | Variable limits per point |
| c | CL + 3√CL | max(0, CL - 3√CL) | Constant limits |
| g | CL + 3√(CL(CL+1)) | max(0, CL - 3√(CL(CL+1))) | Constant limits |
| s | B4[n] × CL | B3[n] × CL | n = subgroup size |
| xbar | CL + A3[n] × S̄ | CL - A3[n] × S̄ | S̄ = mean of subgroup SDs |
| pp | CL + 3σ_base × σ_z | max(0, CL - 3σ_base × σ_z) | Laney: σ_z = MR̄(z)/1.128 |
| up | CL + 3σ_base × σ_z | max(0, CL - 3σ_base × σ_z) | Laney: σ_z = MR̄(z)/1.128 |
| t | Back-transform i limits | Back-transform i limits | y' = y^(1/3.6), compute as i, CL'³·⁶ |

### MR Screening (Provost & Murray 2011, p.140)
```
1. Compute all MRs = |y[i] - y[i-1]| for valid baseline points
2. MR̄_raw = mean(MRs)
3. Remove MRs > D4[2] × MR̄_raw (i.e., > 3.267 × MR̄_raw)
4. MR̄_screened = mean(remaining MRs)
5. σ̂ = MR̄_screened / 1.128
```

### Signal Detection Methods

**Anhoej (default):**
- Run threshold: floor(log₂(n_useful)) + 3
- Crossings threshold: lower 5th percentile of Binomial(n_useful - 1, 0.5)
- If crossings ≤ threshold → mark all useful points
- Elif longest_run ≥ threshold → mark only points in long runs

**IHI (Provost & Murray):**
- Shift: 8+ consecutive points on same side of CL
- Trend: 6+ consecutive strictly increasing or decreasing

**WECO (Western Electric):**
- Rule 1: 1 point beyond 3σ
- Rule 2: 2 of 3 beyond 2σ (same side)
- Rule 3: 4 of 5 beyond 1σ (same side)
- Rule 4: 8+ on same side of CL

**Nelson (8 rules):**
- Rule 1: 1 beyond 3σ
- Rule 2: 9+ on same side (not 8 like WECO)
- Rule 3: 6+ trending
- Rule 4: 14+ alternating
- Rule 5: 2 of 3 beyond 2σ
- Rule 6: 4 of 5 beyond 1σ
- Rule 7: 15+ within 1σ (stratification)
- Rule 8: 8+ with none in 1σ (mixture)

---

## 9. Critical Files

| File | Role |
|------|------|
| `src/qikit/core.py` | SPC math — port to TypeScript, reference for fixtures |
| `src/qikit/__init__.py` | Orchestration + frozen dataclasses — pattern for Planned Experimentation |
| `src/qikit/render.py` | Plotly theme — reuse for Planned Experimentation charts, extract `_apply_theme()` |
| `tests/test_core.py` | Test vectors to extract into SPC fixtures |
| `tests/test_phase2.py` | Regression vectors to extract into SPC fixtures |
| `tests/test_extended.py` | WECO/Nelson/bchart/pareto vectors for fixtures |
| `docs/roadmap.md` | Architecture rules (frozen results, to_dict contract, no scipy) |
| `docs/cross-language-testing.md` | Two-layer fixture strategy for Python/TypeScript sync |
| `docs/doe-replication-plan.md` | Planned Experimentation specification from standard textbook catalog |
| `docs/study-it2-technical-spec.md` | Planned Experimentation chart rendering details, design matrix patterns |
| `fixtures/` | Shared test fixtures — also used by "Try an Example" feature in the UI |
