# qikit

**SPC charts and funnel plots for healthcare quality, in Python.**

Two questions, two functions, one vocabulary:

- **`qic()`**: is one measure changing over time? Control charts and run charts, with
  qicharts2's rules or NHS England's Making Data Count rules.
- **`funnel()`**: which providers differ from their peers? Spiegelhalter funnel plots
  with exact limits, over-dispersion, p- and q-values, and power.

Both return a result whose `.data` is a table ready to write back to a database, whose
`.summary` says what was found, and whose `.plot()` draws a Plotly figure.

## Install

```bash
pip install clinical-qikit            # tables only: numpy and pandas
pip install "clinical-qikit[plot]"    # adds plotly for .plot()
```

The core needs only numpy and pandas, so a Snowpark stored procedure or UDTF can compute
limits without plotly. `import qikit` never loads plotly; `.plot()` raises an
`ImportError` naming the extra when it is missing.

## Quickstart

```python
from qikit import qic, funnel

r = qic(df, x="month", y="deaths", n="admissions", chart="p")
r.data          # one row per month: cl, ucl, lcl, signal, runs_signal
r.summary       # which rules fired, and how the limits were set
r.plot()        # a Plotly figure

f = funnel(df, y="deaths", n="expected", measure="oe", unit="surgeon", worse="higher")
print(f)        # what was compared, what flagged, what to know
f.data[f.data.signal != "none"]
```

## One vocabulary

The two functions answer different questions, so they stay separate, but every shared
idea has one name.

| Idea | Argument or column | In `qic()` | In `funnel()` |
|---|---|---|---|
| Data | `data=`, then column names | `x=`, `y=`, `n=` | `y=`, `n=`, `unit=` |
| A fixed centre line | `center=` | yes | yes (`1.0` on O/E) |
| Which direction is bad | `worse="higher"`/`"lower"` | NHS improving/concerning | one-sided flags |
| Points left out of the model | `exclude=` | yes | yes |
| One chart per group | `facets=` (a column or list) | yes | yes |
| Display name, tooltip | `label=`, `hover=` | yes | yes |
| Scale y | `multiply=` | yes | yes |
| Flag column | `signal`: `"outlier"`, `"alert"`, `"none"` | outlier beyond 3σ | both tiers |
| Pattern column | `runs_signal` | yes | |
| Display | `.plot(title=, styles=, ...)` | yes | yes |

Arguments removed or renamed in 1.0 raise a `TypeError` naming the replacement, so an
old call fails loudly rather than drawing something different. See
[CHANGELOG.md](CHANGELOG.md).

## Over time: `qic()`

| You have, per period | `chart=` | `y=`, `n=` |
|---|---|---|
| Any measure, few assumptions (start here) | `"run"` | y |
| One continuous value (LOS, wait time, O/E) | `"i"` | y |
| Events out of cases (H&P in 24 h, mortality) | `"p"` | events, cases |
| The same, n in the thousands (over-dispersed) | `"pp"` | events, cases (Laney) |
| Events over exposure (infections per line-day) | `"u"` | events, exposure |
| The same, exposure in the thousands | `"up"` | events, exposure (Laney) |
| An O/E ratio over time | `"u"` | observed, expected |
| Counts with constant opportunity | `"c"` | count |
| Several raw values per period | `"xbar"`, `"s"` | raw values, x = period |
| Cases or days between rare events | `"g"`, `"t"` | cases or days between |
| The moving range of an i chart | `"mr"` | y |

Rows that share an `x` are aggregated into one subgroup. Numeric and date x are sorted.
`x_period="month"` buckets dates.

**Rules (`method=`):**

- **`"anhoej"`** (default): qicharts2's run rules. A run on one side of the centre line
  longer than round(log₂ n) + 3, or fewer crossings than the 5th percentile of
  Binomial(n − 1, ½).
- **`"nhs"`**: NHS England's Making Data Count, for XmR boards. A point beyond the
  limits, 7 on one side, 7 rising or falling, or 2 of 3 near a limit. With `worse=`,
  each point is classed improving, concerning or common cause; with `target=`, the
  summary gives the assurance verdict (pass, fail or variable).
- **`"ihi"`**: Provost and Murray. **`"weco"`**, **`"nelson"`**: the classic zone rules.

**Baseline and phases.** `freeze=k` sets the limits from points 1..k and judges later
points against them. `part=` splits the chart into phases, each with its own centre
line, limits and rules. `exclude=` drops points from the limits and the rules.

`qic()` reproduces qicharts2 to 1e-6 on its own data. Where it departs, and why, is in
[docs/qic-methods.md](docs/qic-methods.md).

## Across providers: `funnel()`

Each provider is plotted at its own volume, against Spiegelhalter's exact 99.8% and 95%
probability contours (*Statistics in Medicine* 2005;24:1185-1202). Every method,
reference and design choice is recorded in [docs/methods.md](docs/methods.md),
including where qikit departs from the paper.

### Choosing the settings

| You have | Pass |
|---|---|
| Observed events and risk-model expected events (mortality or readmission O/E) | `measure="oe"`, `y=observed`, `n=expected` |
| Events out of cases (complication %, top-box %) | `measure="proportion"`, `y=events`, `n=cases` |
| Events over exposure (infections per line-day) | `measure="rate"`, `y=events`, `n=exposure` |
| **Days**, or anything where one case adds many units (length of stay as O/E days) | stay-level rows, one per case, and `within_dispersion="estimate"` |
| The same, summed per provider in SQL so the stays never leave the warehouse | one row per provider with `cases=` (k) and `sum_sq=` (`SUM(POWER(obs, 2) / exp)`), and `within_dispersion="estimate"` |
| Stays whose variability differs by DRG or service line | `within_dispersion="<column>"`: one case-mix-weighted φᵢ per provider, from SQL |
| Leaders will ask "is this flag one patient?" | case-level rows (automatic), or `max_case_y=`/`max_case_n=` from SQL: see `p_value_drop1`, `fragility` |
| **Survey items**, scored per item (HCAHPS composites) | one row per survey (`y` = items "Always", `n` = items answered), `measure="proportion"`, `within_dispersion="estimate"` |
| A measure where only one direction is bad | `worse="higher"` (mortality) or `worse="lower"` (top-box) |
| Hundreds of providers, and few false alarms matter more than the drawn lines | `signal="fdr"` |
| Many very-low-volume providers diluting the FDR step | `fdr_min_denominator=` (a volume floor for the FDR step only) |
| To rank flagged providers for action | sort by `eb_excess`, not `raw_excess` |
| To reproduce a CQC or NHS SHMI funnel | `tau_method="cqc"` or `"shmi"` |
| Flags acted on one by one, where the stated chance-flag rate must hold | `tau_method="winsorized"` |
| The spread between providers known from earlier periods, or fewer than 30 providers | `tau=<value>` (fixed in advance) |
| "Does this flag depend on the model?" | `funnel_sensitivity(...)` |
| "Is this provider probably worse than average?" (the CMS question) | read `prob_worse`; `signal` answers "unusual among peers?" |
| A benchmark against the risk model itself, not the peer average | `center=1.0` |

Rows that share a `unit` are summed, so stay-level or year-level data aggregates itself.

### Reading the result

`r.data` has one row per provider:

| Column | Meaning |
|---|---|
| `unit`, `label` | The provider and its display name |
| `y` | The plotted value: O/E, proportion or rate |
| `numerator`, `denominator` | The summed `y=` and `n=` (observed and expected, events and cases) |
| `cl` | The centre line: pooled ΣO/ΣE (or Σevents/Σn) unless `center=` is given |
| `lower_outlier`, `upper_outlier` | The 99.8% contour at this provider's volume |
| `lower_alert`, `upper_alert` | The 95% contour |
| `p_value` | Exact p-value against the model the contours are drawn from; one-sided toward `worse=`, doubled when two-sided |
| `q_value` | Its Benjamini–Hochberg adjustment across the chart's providers |
| `signal` | `"outlier"`, `"alert"` or `"none"`. The tiers never overlap |
| `direction` | `"higher"` or `"lower"` than the centre line |
| `min_detectable` | The smallest true value this provider could have flagged with 80% power |
| `ci_lower`, `ci_upper` | Exact 95% interval for the provider's own value |
| `excluded` | Left out with `exclude=` (drawn faded, not tested) |
| `raw_excess` | (observed − cl × denominator), signed so positive is worse: excess days or events |
| `reliability` | How much of the provider's difference is signal, 0–1. 0 everywhere when τ̂ = 0 |
| `eb_rate`, `eb_excess` | The shrunk (empirical Bayes) value and its excess: the exact posterior mean of the chart's own model. Rank flagged providers on `eb_excess` |
| `prob_worse` | Posterior probability that the true value is worse than the centre line (CMS-style "worse than average"); NaN when τ̂ = 0 |
| `p_value_drop1` | The p-value with the provider's single most extreme case removed (needs case rows or `max_case_y=`/`max_case_n=`); descriptive, no q-value |
| `flag_survives_drop1` | For flagged providers: still flagged without that case? |
| `fragility` | Case rows: the fewest worst cases whose removal clears the flag (1 = one case carries it) |
| `effective_denominator` | Only with a `within_dispersion` column: n/φᵢ, the plot's x axis |

`r.summary` holds the model and how to read the counts:

- `n_outlier`, `n_alert`, and `expected_false_flags`.
- `tau`: the estimated spread of true values between providers; `tau_method`,
  `tau_scale`, `tau_source` ("estimated" or "pre-specified"), `tau_estimated`, and
  `tau_ci` under `tau_method="ml"`.
- `phi`: the over-dispersion ratio as the chosen method defines it.
- `count_model`, `limit_method`, `within_dispersion`, `dispersion_shape`, `underpowered`,
  `n_filtered`, `n_fragile`.
- `notes`: sentences ready to show a reader.

On a faceted funnel the same keys are under `by_facet`.

### What decides a flag

Each contour is the boundary of an **exact test**. A provider is beyond the 99.8% line
exactly when its one-sided p-value is below 0.001, and beyond the 95% line exactly when
it is below 0.025. For the unadjusted O/E chart that is the same as "the provider's own
exact 95% interval excludes the center line". The line, the p-value, the colour and the
interval always agree.

`signal=` picks one test for both tiers:

- **`"limits"`** (default): outlier beyond the outer contour, alert beyond the inner one.
  About 0.1% of average providers land beyond each 99.8% line by chance, and 2.5% beyond
  each 95% line. `summary["expected_false_flags"]` counts that for your chart. With 1,000
  providers on a one-sided chart it is about 1 outlier and 24 alerts, so "35 alerts" is
  read against that.
- **`"fdr"`**: outlier when `q_value < 0.05`, alert when `q_value < 0.10`
  (`fdr_levels=`). At most that share of each tier is expected to be false, however many
  providers there are. The flags then no longer match the drawn lines, and the caption
  says so.

There is deliberately no "limit OR q" mode. That union only ever adds flags, so it never
removes the chance alerts that make FDR worth using, and neither guarantee holds for
the combined tier ([methods §4.11](docs/methods.md)).

`limits=(0.998, 0.95)` moves the contours, for example to `(0.997, 0.95)`.

### Over-dispersion: real differences between providers

No risk model captures everything, so providers differ by more than chance allows. With
`overdispersion=True` (the default) each provider is judged against that spread as
well as chance, using Spiegelhalter's additive random-effects model. The smallest
providers' limits barely move. The busiest level off at about the centre ± z·τ instead
of closing onto the line. When τ̂ is 0, which is common at physician scale, the chart is
identical to `overdispersion=False`.

How τ is estimated (`tau_method=`, [methods §4.16](docs/methods.md)):

| `tau_method=` | What it is | Use when |
|---|---|---|
| `"spiegelhalter"` (default) | 10%-winsorized method of moments, as published | Screening. The most sensitive robust option, and uncorrected like the NHS and CQC estimators |
| `"winsorized"` | The same with the consistency factor of his eq. 9 | Flags acted on one by one, where the 0.1% and 2.5% chance rates must hold |
| `"ml"` | Maximum likelihood, with an interval `tau_ci` | Data already cleaned of outliers; not robust |
| `"cqc"`, `"shmi"` | CQC (√ or arcsine scale) and NHS SHMI (log scale), as FunnelPlotR computes them | Reproducing those indicators ([methods §4.17](docs/methods.md)) |
| `tau=<value>` | Fixed in advance from earlier periods | Fewer than 30 providers, or a stable benchmark |

The published estimator understates a small real spread, so average providers flag
somewhat more often than the stated rate. That is the right error for a screen whose
flags are reviewed. `funnel_sensitivity()` runs each option and marks the providers
whose tier depends on the choice:

```python
from qikit import funnel_sensitivity

s = funnel_sensitivity(df, y="deaths", n="expected", measure="oe", unit="surgeon")
s[~s.consistent]      # flagged under one model and not another: a judgement call
```

Treat a non-zero τ̂ as a finding about the system: unmeasured case mix, data
differences, or real variation in practice.

### Length of stay and other clustered counts

A funnel of observed/expected **patient-days** treats every day as an independent
event. Days come in stays, so a provider's day total varies 5–10 times more than that
assumption allows. Every small provider's limits come out far too narrow, and every
p-value and q-value too small. τ cannot absorb this, because the missing variance
shrinks with volume while τ does not.

Pass stay-level rows and let qikit measure it:

```python
stays = session.sql("""
    SELECT provider_id, provider_name, los_days, expected_los_days
    FROM inpatient_stays WHERE discharge_date >= '2026-01-01'
""").to_pandas()

r = funnel(stays, y="LOS_DAYS", n="EXPECTED_LOS_DAYS", measure="oe",
           unit="PROVIDER_ID", label="PROVIDER_NAME",
           within_dispersion="estimate", worse="higher")
r.summary["within_dispersion"]     # φ̂: how much more variable each count is than Poisson
```

- **The estimate:** φ̂ comes from each stay's residual around its own provider's rate, so
  real differences between providers stay with τ.
- **Already-aggregated data:** pass a number, computed once in SQL:
  `SUM(POWER(los - exp_los, 2) / exp_los) / (COUNT(*) - COUNT(DISTINCT provider))`.
- **Event counts** (deaths, readmissions) need nothing; leave the default of 1.
- **The guard:** if the spread looks clustered and `within_dispersion` was left at 1,
  qikit raises a `UserWarning` and says so in `summary["notes"]` and on the figure.
- **Upstream choices:** cap extreme stays at a stated percentile before aggregating. If
  φ̂ differs a lot between service lines, facet by service line; `"estimate"` is then
  taken per facet.
- **Multi-item surveys** are the same problem on a proportion: one patient answers the
  three doctor questions alike, so item counts look like more data than they are. Pass
  one row per survey with `within_dispersion="estimate"`; the model then sees y/φ̂ out
  of n/φ̂ (Rao–Scott effective counts), interpolated rather than rounded
  ([methods §4.13](docs/methods.md)).

In one simulated length-of-stay cohort of 1,000 providers with no real differences
between them, the chart flags 24 outliers and 65 alerts without the fix. With
`within_dispersion="estimate"` it flags 3 and 20, against 1 and 24 expected by chance
([methods §5](docs/methods.md) has the full simulation).

### Physician-level comparison: what the chart could not find

At individual-physician volumes a funnel is mostly a test with no power. The chance of
flagging a physician whose **true** O/E is 2.0 at the 99.8% limit:

| Expected deaths | 2 | 5 | 10 | 20 | 50 |
| --- | --- | --- | --- | --- | --- |
| Chance of flagging a true O/E of 2.0 | 5% | 21% | 44% | 81% | 99.8% |

Most physicians sit at 5–20 expected events, so **absence of a signal is not evidence
of acceptable performance**. That is exactly how a blank funnel tends to get read. So
every provider carries `min_detectable` and an exact interval. `summary["underpowered"]`
says whether the typical provider could detect even a doubling, and an underpowered
figure captions itself so the caveat survives a slide deck. A physician at O/E 2.5
whose `min_detectable` is 4.6 has not been cleared; the chart cannot see that far at
their volume.

The workflow that works is to aggregate until the chart has power. With the bundled
example (24 surgeons, 3 years):

```python
import pandas as pd
from qikit import funnel

df = pd.read_csv("data/examples/physician_mortality_oe.csv")

# Any single year: no outlier, and underpowered is True.
funnel(df[df.year == 2025], y="observed_deaths", n="expected_deaths",
       measure="oe", unit="physician").summary["underpowered"]       # True

# All three years (rows per physician are summed): three real signals, SURG-07 and
# SURG-15 above, and a high performer, SURG-21, below the lower limit.
r = funnel(df, y="observed_deaths", n="expected_deaths", measure="oe", unit="physician")
r.data[r.data.signal != "none"]
```

### Figures

```python
HOUSE = {"font": {"family": "Segoe UI", "size": 13}, "limits": {"color": "#555"}}

r.plot(
    styles=[HOUSE, {"lcl": {"visible": False}, "lcl_95": {"visible": False}}],
    x_range=(2, None),          # start at 2 expected deaths; the y axis refits
    label_signals="outlier",
    width=1000, height=560,
)
```

- **Defaults for a projector:** contours at 3.5:1 contrast, the 95% line dashed, points
  at 0.85 opacity, and the legend on. Outliers are red circles and alerts amber
  diamonds, so the tier never depends on colour alone.
- **Axes and caption:** the y axis is fitted to the providers and the narrow end of the
  funnel, not its low-volume flare. An unset caption states the flag rule.
- **`styles=`** restyles by role: `data`, `outlier`, `alert`, `runs`, `improving`,
  `concerning`, `neutral`, `cl`, `ucl`, `lcl`, `ucl_95`, `lcl_95`, `target`, the groups
  `limits` and `limits_95`, `end_labels` and `font`. A list of dicts is merged in order,
  so a house style is one constant.
- **`r.limits(n=None)`** returns the contours at any denominators, for drawing
  elsewhere.
- **Unknown names raise.** An unknown `.plot()` option raises `TypeError`.

### Options at a glance

| Parameter | Default | What it does |
|---|---|---|
| `measure` | required | `"oe"`, `"proportion"` or `"rate"` |
| `unit`, `label`, `hover` | `None` | Provider id, display name, extra tooltip columns |
| `facets` | `None` | One funnel per value (a column or list): own centre line, τ, FDR step |
| `exclude` | `None` | A boolean column, or a list of unit ids, left out of the model |
| `center` | pooled | A fixed centre line, e.g. `1.0` on O/E |
| `overdispersion` | `True` | Judge against the spread between providers (τ) |
| `within_dispersion` | `1.0` | Clustered counts or survey items: a number, `"estimate"`, or a column of per-provider φᵢ |
| `tau_method` | `"spiegelhalter"` | `"spiegelhalter"`, `"winsorized"`, `"ml"`, `"cqc"`, `"shmi"` |
| `tau` | `None` | A τ fixed in advance (a number, or one per facet) |
| `cases`, `sum_sq` | `None` | Per-provider SQL totals so `"estimate"` needs no case rows |
| `max_case_y`, `max_case_n` | `None` | Per-provider SQL worst case, for `p_value_drop1` |
| `fdr_min_denominator` | `None` | Volume floor for the FDR step only (independent filtering) |
| `worse` | `None` | `"higher"` or `"lower"`: flag one side, one-sided p-values |
| `signal` | `"limits"` | `"limits"` (exact test, drawn) or `"fdr"` (q-values) |
| `limits` | `(0.998, 0.95)` | Outer and inner contour coverage |
| `fdr_levels` | `(0.05, 0.10)` | Outlier and alert false discovery rates under `signal="fdr"` |
| `multiply` | `1` | Scale y, e.g. `1000` for a rate per 1,000 |

## In Snowflake

`qic(...).data` and `funnel(...).data` are the tables a pipeline writes back. With
`facets=` a list of columns, one call covers every measure and service line, and the
facet columns stay in the output, so the result joins back to the source table.
[docs/snowflake.md](docs/snowflake.md) has a stored procedure and a UDTF that add limits
to a pre-aggregated metrics table, packaging steps, and Streamlit in Snowflake notes.

## Also included

- **`paretochart(x, data=...)`**: Pareto chart of categorical frequencies.
- **`bchart(x, ...)`**: Bernoulli CUSUM for early detection of a shift in pass/fail data.
- **`design(factors, ...)`** / **`analyze(design_obj, response, ...)`**: full-factorial
  design of experiments and effect analysis.

## For AI agents

- **[AGENTS.md](src/qikit/AGENTS.md)** ships inside the package. It maps each module,
  says which function answers which question, and lists the conventions an agent must
  not break. [llms.txt](llms.txt) is the same map at the repository root.
- **Docstrings are the reference.** `help(qikit.qic)` and `help(qikit.funnel)` open with
  a decision table and document every result column.
- **Skills** for Snowflake Cortex Code or any agent that loads them:
  [`skills/spc-monitoring/SKILL.md`](skills/spc-monitoring/SKILL.md) and
  [`skills/provider-funnels/SKILL.md`](skills/provider-funnels/SKILL.md).
- **Errors name the fix,** and removed arguments name their replacement.

## Excel add-in

A Microsoft Excel task-pane add-in built on the same engine, ported to TypeScript, lives
in [`excel-addin/`](excel-addin/). See its [README](excel-addin/README.md) and
[docs/excel-addin-roadmap.md](docs/excel-addin-roadmap.md).

## Web app

`app.py` is a Streamlit front end over the same engine:

```bash
pip install -e ".[app]"
streamlit run app.py
```

## Development

```bash
uv sync --extra dev
uv run ruff check .
uv run mypy
uv run pytest tests/
```

The Python engine is authoritative. The TypeScript port in `excel-addin/packages/engine`
conforms to it through the shared JSON fixtures in [`fixtures/spc`](fixtures/spc). After
an intentional engine change, regenerate the snapshots with
`uv run python scripts/update_snapshots.py`. `fixtures/reference` holds output from R's
qicharts2, FunnelPlotR and NHSRplotthedots, regenerated by
`scripts/make_reference_fixtures.R`; `tests/test_reference.py` checks qikit against it
to 1e-6, with each accepted departure listed and explained.

## References

1. Montgomery DC. *Introduction to Statistical Quality Control*, 8th ed. Wiley, 2019.
2. Provost LP, Murray SK. *The Health Care Data Guide*, 2nd ed. Jossey-Bass, 2022.
3. Anhøj J, Olesen AV. Run charts revisited: a simulation study of run chart rules for
   detection of non-random variation in health care processes. *PLoS ONE*
   2014;9(11):e113825.
4. Spiegelhalter DJ. Funnel plots for comparing institutional performance. *Statistics
   in Medicine* 2005;24(8):1185–1202.
5. NHS England. *Making Data Count*. Strengthening your decisions, 2019.

## License

MIT
