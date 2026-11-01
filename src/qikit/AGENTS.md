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

- `center=`: a fixed centre line (`1.0` for O/E against the risk model).
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
  or `"rate"` (events, exposure). Length of stay in days needs stay-level rows and
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

## Module map

```
qikit/
  __init__.py      public exports
  spc.py           qic(): normalise -> aggregate by x -> baseline -> limits -> rules -> table
  funnel.py        funnel(), funnel_sensitivity(): sums per unit -> dispersion -> contours
                   -> p/q values -> tiers -> shrinkage and robustness -> table
  results.py       SPCResult, FunnelResult, ParetoResult, BChartResult
  validate.py      argument checks and messages shared by both front doors
  extras.py        paretochart(), bchart()
  doe.py           design(), analyze()
  core/            pure numpy, no pandas or plotly; mirrored by the TypeScript engine
    shewhart.py    centre lines and 3-sigma limits per chart type
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
