# qikit

**SPC charts, funnel plots and quality improvement tools for healthcare, in Python.**

Two functions: `qic()` for a process over time, `funnel()` for providers compared
with each other. One result object each, and one `.plot()` call.

## Install

```bash
pip install clinical-qikit
```

## Quickstart

```python
from qikit import qic, funnel

result = qic(y=values, chart="i")           # a process over time
result.plot()                               # returns a Plotly figure

r = funnel(df, y="deaths", n="expected", measure="oe", unit="hospital")
print(r)                                    # providers compared with each other
```

`qic()` mirrors R's [qicharts2](https://github.com/anhoej/qicharts2), the package most
healthcare QI practitioners already know — same chart types, same run-chart signal
detection, same mental model, now in Python.

## Chart types

`qic()` draws time-ordered SPC charts, chosen with `chart=`:

| `chart=` | Chart | Use for |
|---|---|---|
| `run` | Run chart | Any sequential data, median center line |
| `i` | Individuals (I) chart | Continuous data, one observation per subgroup |
| `mr` | Moving range | Variation between consecutive observations |
| `xbar` | X-bar chart | Continuous data with subgroups (paired with `s`) |
| `s` | S chart | Subgroup standard deviation |
| `t` | Time-between-events chart | Time or count between rare events |
| `p` | P chart | Proportion (percent) defective, unequal subgroup sizes |
| `pp` | P′ chart | Proportions with overdispersion (Laney) |
| `c` | C chart | Count of defects, constant opportunity |
| `u` | U chart | Rate of defects, unequal opportunity; also a monthly O/E series, with `y=observed, n=expected` |
| `up` | U′ chart | Rates with overdispersion (Laney) |
| `g` | G chart | Number of opportunities between rare events |

Comparing providers with each other, rather than tracking one over time, is a funnel
plot: use `funnel()`, below. `qic()` no longer takes the 0.7 funnel arguments (`funnel=`,
`signal_side=`, `signal_method=` and the rest). Passing one raises a `TypeError` that
names its replacement.

## Comparing providers: `funnel()`

```python
from qikit import funnel

r = funnel(df, y="deaths", n="expected", measure="oe", unit="surgeon",
           label="surgeon_name", worse="higher")
print(r)                                  # what was compared, what flagged, what to know
r.data[r.data.signal != "none"]           # one row per provider, with signal and p/q values
r.plot()
```

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
| **Survey items**, scored per item (HCAHPS composites such as Communication with Doctors) | one row per survey (`y` = items "Always", `n` = items answered), `measure="proportion"`, `within_dispersion="estimate"` |
| A measure where only one direction is bad | `worse="higher"` (mortality) or `worse="lower"` (top-box) |
| Hundreds of providers, and few false alarms matter more than the drawn lines | `signal="fdr"` |
| A benchmark against the risk model itself, not the peer average | `center=1.0` |

Rows that share a `unit` are summed, so stay-level or year-level data aggregates itself.

### Reading the result

`r.data` has one row per provider:

| Column | Meaning |
|---|---|
| `unit`, `label` | The provider and its display name |
| `y` | The plotted value: O/E, proportion or rate |
| `numerator`, `denominator` | The summed `y=` and `n=` (observed and expected, events and cases) |
| `cl` | The center line: pooled ΣO/ΣE (or Σevents/Σn) unless `center=` is given |
| `lower_outlier`, `upper_outlier` | The 99.8% contour at this provider's volume |
| `lower_alert`, `upper_alert` | The 95% contour |
| `p_value` | Exact p-value against the model the contours are drawn from; one-sided toward `worse=`, doubled when two-sided |
| `q_value` | Its Benjamini–Hochberg adjustment across the chart's providers |
| `signal` | `"outlier"`, `"alert"` or `"none"`. The tiers never overlap |
| `direction` | `"higher"` or `"lower"` than the center line |
| `min_detectable` | The smallest true value this provider could have flagged with 80% power |
| `ci_lower`, `ci_upper` | Exact 95% interval for the provider's own value |
| `excluded` | Left out with `exclude=` (drawn faded, not tested) |

`r.summary` holds the model and how to read the counts:

- `n_outlier`, `n_alert`, and `expected_false_flags`.
- `tau`: the estimated spread of true values between providers.
- `count_model`, `within_dispersion`, `dispersion_shape` and `underpowered`.
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
well as chance. qikit uses Spiegelhalter's additive random-effects model, with τ
estimated as published. The smallest providers' limits barely move. The busiest level
off at about the center ± z·τ instead of closing onto the line. When τ̂ is 0, which is
common at physician scale, the chart is identical to `overdispersion=False`.

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
  diamonds, so the tier never depends on colour alone. The colour pair passes a
  colour-vision-deficiency check.
- **Axes and caption:** the y axis is fitted to the providers and the narrow end of the
  funnel, not its low-volume flare. Axis titles come from your column names. An unset
  caption states the flag rule.
- **`styles=`** restyles by role. The roles are `data` (color, opacity, name), `sigma`,
  `warn`, `cl`, `ucl`, `lcl`, `ucl_95` and `lcl_95`, the groups `limits` and
  `limits_95`, `end_labels`, and `font`. A list of dicts is merged in order, so a house
  style is one constant, with no global state to reset between Streamlit reruns.
- **`r.limits(n=None)`** returns the contours at any denominators, for drawing
  elsewhere.
- **Unknown names raise.** `r.plot(...)` overrides any display argument of `funnel()`,
  and an unknown name raises `TypeError`.

### Options at a glance

| Parameter | Default | What it does |
|---|---|---|
| `measure` | required | `"oe"`, `"proportion"` or `"rate"` |
| `unit`, `label`, `hover` | `None` | Provider id, display name, extra tooltip columns |
| `facets` | `None` | One funnel per value: own center line, τ, FDR step |
| `exclude` | `None` | A boolean column, or a list of unit ids, left out of the model |
| `center` | pooled | A fixed center line, e.g. `1.0` on O/E |
| `overdispersion` | `True` | Judge against the spread between providers (τ) |
| `within_dispersion` | `1.0` | Clustered counts or survey items: a number, or `"estimate"` from case-level rows (stays, surveys) |
| `worse` | `None` | `"higher"` or `"lower"`: flag one side, one-sided p-values |
| `signal` | `"limits"` | `"limits"` (exact test, drawn) or `"fdr"` (q-values) |
| `limits` | `(0.998, 0.95)` | Outer and inner contour coverage |
| `fdr_levels` | `(0.05, 0.10)` | Outlier and alert false discovery rates under `signal="fdr"` |
| `multiply` | `1` | Scale y, e.g. `1000` for a rate per 1,000 |
| `label_signals` | `None` | `"outlier"`, `"alert"` or `"both"` |
| `styles`, `x_log`, `x_range`, `y_range`, `show_legend`, `width`, `height`, `title`, `xlab`, `ylab`, `caption` | | Display |

Beyond `qic()` and `funnel()`, the package also provides:

- **`paretochart(x, data=...)`** — Pareto chart of categorical frequencies.
- **`bchart(...)`** — Bernoulli CUSUM chart for early detection of shifts in binary
  (pass/fail) data.
- **`design(factors, ...)`** / **`analyze(design_obj, response, ...)`** — full-factorial
  design of experiments (DOE) and effect analysis.

## For AI agents

`funnel()`'s docstring is written as the agent-facing reference: it starts with a
decision table and documents every column of the result. Run `help(qikit.funnel)`. For
Snowflake Cortex Code, or any agent that loads skills,
[`skills/provider-funnels/SKILL.md`](skills/provider-funnels/SKILL.md) gives the
provider-comparison workflow, including the length-of-stay case. Copy it into your
agent's skills folder.

## Excel add-in

A Microsoft Excel task-pane add-in built on the same charting engine (ported to
TypeScript) lives in [`excel-addin/`](excel-addin/) — see its
[README](excel-addin/README.md) for dev-harness and sideload instructions, and
[docs/excel-addin-roadmap.md](docs/excel-addin-roadmap.md) for the roadmap.

## Web app

`app.py` is a Streamlit front end over the same engine:

```bash
pip install -e .[app]
streamlit run app.py
```

## Development

```bash
uv sync --extra dev
uv run ruff check .        # lint (CI-enforced)
uv run pytest tests/       # 176 tests incl. cross-language fixture conformance
```

The Python engine is authoritative; the TypeScript port in
`excel-addin/packages/engine` conforms to it via the shared JSON fixtures in
[`fixtures/`](fixtures/). After intentional engine changes, regenerate the
fixture snapshots with `uv run python scripts/update_snapshots.py`.

## References

1. Montgomery DC. *Introduction to Statistical Quality Control*, 8th ed. Wiley, 2019.
2. Provost LP, Murray SK. *The Health Care Data Guide*, 2nd ed. Jossey-Bass, 2022.

## License

MIT
