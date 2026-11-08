# qikit for agents

qikit answers two questions about healthcare quality data. Pick the function by the
question, then read its docstring: each opens with a table of which settings fit which
data and documents every result column.

| Question | Function | Result |
|---|---|---|
| Is one measure changing over time? | `qic(data, x=, y=, n=, chart=)` | `SPCResult` |
| Which providers differ from their peers? | `funnel(data, y=, n=, measure=, unit=)` | `FunnelResult` |
| Does a provider's flag depend on the τ model? | `funnel_sensitivity(data, ...)` | DataFrame |
| Which categories account for most defects? | `paretochart(x, data=)` | `ParetoResult` |
| Has a pass/fail process shifted? (CUSUM) | `bchart(x, target=)` | `BChartResult` |
| Which factors matter in an experiment? | `design(...)`, `analyze(...)` | `ExperimentDesign`, `ExperimentResult` |

The chart results (`SPCResult`, `FunnelResult`, `ParetoResult`, `BChartResult`) have
`.data` (a DataFrame, the thing to write back to a table), `.summary` (a dict; `notes`
holds sentences ready to show a reader), `.plot(**options)` (a Plotly figure; needs
`clinical-qikit[plot]`), `.to_dict()` and `.to_json()`. `print(result)` says what was
compared and what was found.

## Shared vocabulary

Both `qic()` and `funnel()` take `data=` first, then keyword arguments naming columns.
These names mean the same thing in both:

- `center=`: a fixed center line. On a funnel, pair it with `overdispersion=False`, or
  use `compare_to=` (below); `center=` alone with the spread allowance on draws a warning.
- `worse="higher"|"lower"`: which direction is bad.
- `exclude=`: points or providers left out of the model, still drawn.
- `facets=`: one column or a list; one chart per combination; the columns lead `.data`.
- `label=`, `hover=`, `multiply=`.
- `signal` column: `"outlier"`, `"alert"` (funnels only), or `"none"`.

Display options (title, axis labels, `styles=`, ranges, sizes) belong to `.plot()`, not
to `qic()` or `funnel()`. A removed or renamed argument raises `TypeError` naming the
replacement; read the message and apply it.

## Choosing quickly

- **Time series:** `chart="run"` when unsure; `"p"` for events/cases; `"u"` for
  events/exposure or monthly O/E; `"i"` for one continuous value per period. Rules:
  `method="anhoej"` (default, qicharts2) or `method="nhs"` with `chart="i"` and
  `worse=` for NHS Making Data Count.
- **Funnels:** `measure="oe"` (y=observed, n=expected), `"proportion"` (events, cases)
  `"rate"` (events, exposure) or `"mean"` (a per-case amount such as minutes or cost,
  one row per case; never rescale it to O/E). Length of stay in days needs stay-level rows and
  `within_dispersion="estimate"`. Keep `tau_method="spiegelhalter"` (the default)
  unless the user asks for CQC/SHMI (`"cqc"`, `"shmi"`) or for the stated chance-flag
  rate to hold (`"winsorized"`).
- **A goal, not the average:** `benchmark="abc"` (process proportions; Kiefe 1998) or
  `"eb"` (outcomes; shrunk 90th percentile), with `worse=`. It adds `summary["benchmark"]`
  (a dict: `method`, `share`, `value`, and the ABC's provenance), the `benchmark` and
  `meets_benchmark` columns, and a dashed line. Methods §4.18.
- **No signal is not reassurance.** Physician funnels are often underpowered: read
  `summary["underpowered"]` and the `min_detectable` column before saying a provider
  is fine.

## Funnel decision recipe

Settle these in order, before looking at who flags:

1. **Which question.** `compare_to="peers"`: is this provider unusual among its
   peers (pooled center, spread allowed)? `compare_to="model"`: does it differ from
   the risk model (O/E against 1.0, no spread allowance; `measure="oe"` only)? Use
   `"model"` for observed against an external expected (Vizient, CMS). Never pass
   `center=1.0` alone: τ̂ absorbs any system-wide gap and widens every limit
   (a `UserWarning`, methods §4.2.1).
2. **Events, or days and items.** Deaths and readmissions: leave `within_dispersion`
   alone. Length of stay in days, minutes, or multi-item surveys: stay- or survey-level
   rows with `within_dispersion="estimate"` (or `cases=`/`sum_sq=` from SQL).
3. **How many providers per chart.** Tens: `signal="limits"`. Hundreds:
   `signal="fdr"`, with `fdr_min_denominator=` if many tiny providers dilute the step.
4. **Few providers (K < 30) under `"peers"`:** a `tau=` fixed from earlier periods.
5. **Multiplicity across a scorecard.** The Benjamini–Hochberg step runs per chart
   (per facet). For control across every measure on a scorecard, pool the `p_value`
   columns and call `qikit.core.pvalues.bh_q_values` once:

```python
import numpy as np
from qikit.core.pvalues import bh_q_values

results = {"los": r_los, "mortality": r_mort, "readmit": r_readmit}
p = np.concatenate([r.data["p_value"].to_numpy(dtype=float) for r in results.values()])
q = bh_q_values(p)   # scorecard-wide q, in the same order; split back by measure
```

Canonical call: physician LOS, observed against Vizient expected days, from stay-level
rows in Snowflake.

```python
from snowflake.snowpark.context import get_active_session
from qikit import funnel

session = get_active_session()
stays = session.sql("""
    SELECT attending_npi, attending_name, los_days, vizient_expected_los
    FROM inpatient_stays
    WHERE discharge_date >= '2026-01-01'
""").to_pandas()

r = funnel(stays, y="LOS_DAYS", n="VIZIENT_EXPECTED_LOS", measure="oe",
           unit="ATTENDING_NPI", label="ATTENDING_NAME",
           compare_to="model", within_dispersion="estimate", worse="higher",
           signal="fdr")
r.data[r.data.signal != "none"]   # longer stays than Vizient expects, beyond chance
r.summary["notes"]                # show these with the chart
```

## Signal or estimate

- `signal` (with `p_value`, `q_value`): is this provider unusual, given chance and the
  spread between providers? The screen. Use it to choose whom to review.
- `estimate_flag` (with `eb_rate`, `eb_low`, `eb_high`, `prob_worse`): is this
  provider's true value clearly above or below the reference (`summary["reference"]`:
  1.0 under `compare_to="model"`, else the center line)? The CMS-style estimate. Use it
  for scorecards that show each provider's value with a range. It has no multiplicity
  control, and small providers' intervals usually cross the reference.
- Name the question in whatever you write. Show `r.plot(kind="caterpillar")` for the
  estimates and `r.plot()` for the screen.
- Physician readmissions vary little between physicians once the hospital is accounted
  for (Goodwin et al. 2013): expect low `reliability`, and facet by hospital or campus.

Canonical call: physician readmissions against Vizient expected, with estimates,
intervals and a caterpillar plot.

```python
from snowflake.snowpark.context import get_active_session
from qikit import funnel

session = get_active_session()
stays = session.sql("""
    SELECT attending_npi, attending_name, campus, readmit_30d, vizient_expected_readmit
    FROM inpatient_stays
    WHERE discharge_date >= '2026-01-01'
""").to_pandas()

r = funnel(stays, y="READMIT_30D", n="VIZIENT_EXPECTED_READMIT", measure="oe",
           unit="ATTENDING_NPI", label="ATTENDING_NAME", facets="CAMPUS",
           compare_to="model", worse="higher")
r.data[["label", "y", "eb_rate", "eb_low", "eb_high", "prob_worse",
        "estimate_flag", "reliability"]]
r.plot(kind="caterpillar", top=15, bottom=10)
r.summary["notes"]                # show these with the scorecard
```

## Module map

```
qikit/
  __init__.py      public exports
  spc.py           qic(): normalize -> aggregate by x -> baseline -> limits -> rules -> table
  funnel.py        funnel(), funnel_sensitivity(): sums per unit -> dispersion -> contours
                   -> p/q values -> tiers -> shrinkage and robustness -> table
  results.py       SPCResult, FunnelResult, ParetoResult, BChartResult
  validate.py      argument checks and messages shared by both front doors
  extras.py        paretochart(), bchart()
  doe.py           design(), analyze()
  core/            pure numpy, no pandas or plotly; mirrored by the TypeScript engine
    shewhart.py    center lines and 3-sigma limits per chart type
    rules.py       run and zone rules by method (anhoej, ihi, nhs, weco, nelson)
    contours.py    exact and mixture funnel contours
    dispersion.py  phi and tau^2 estimators (spiegelhalter, winsorized, ml, cqc, shmi)
    pvalues.py     exact tails and Benjamini-Hochberg q-values
    power.py       detectability and exact intervals
    dist.py        Poisson/binomial walks, quantiles, incomplete gamma/beta
    constants.py   d2, D4, exact c4 and derived constants
  plot/            plotly figures; imported only by .plot()
```

## Invariants: do not break

- **The line is the test.** On a funnel a point is beyond a contour exactly when its
  p-value is below that contour's level. Contours and p-values come from the same model.
- **Defaults are decisions.** `tau_method="spiegelhalter"`, `method="anhoej"` and
  `limits=(0.998, 0.95)` were chosen deliberately; docs/methods.md §4.16 and
  docs/qic-methods.md say why.
- **Python is authoritative; TypeScript conforms.** `fixtures/spc/*.json` are shared
  with `excel-addin/packages/engine`. An intended engine change regenerates them
  (`scripts/update_snapshots.py`) and updates the TypeScript engine in the same change.
- **R reference output is ground truth.** `fixtures/reference/` holds qicharts2,
  FunnelPlotR and NHSRplotthedots output; a new departure goes in `DEPARTURES` in
  `tests/test_reference.py` with its reason, and in the methods docs.
- **`core/` stays pure.** Arrays in, arrays or small dataclasses out; no DataFrames.

## Where things are documented

- `docs/methods.md`: every funnel method, departure from Spiegelhalter (2005), and
  simulation.
- `docs/qic-methods.md`: time-series charts, rules, and departures from qicharts2.
- `docs/snowflake.md`: stored procedure, UDTF and Streamlit in Snowflake recipes.
- `skills/spc-monitoring/SKILL.md`, `skills/provider-funnels/SKILL.md`: workflows.

## Checks

```bash
uv run pytest tests/
uv run python scripts/update_snapshots.py --check
uv run ruff check . && uv run mypy
cd excel-addin && npx vitest run
```
