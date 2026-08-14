# qikit

**SPC charts and quality improvement tools for healthcare, in Python.**

One function. One result object. One `.plot()` call.

## Install

```bash
pip install clinical-qikit
```

## Quickstart

```python
from qikit import qic

result = qic(y=values, chart="i")
result.plot()   # returns a Plotly figure
```

`qic()` mirrors R's [qicharts2](https://github.com/anhoej/qicharts2), the package most
healthcare QI practitioners already know — same chart types, same run-chart signal
detection, same mental model, now in Python.

## Chart types

All chart types are computed by the same `qic()` entry point via the `chart=` argument:

| `chart=` | Chart | Use for |
|---|---|---|
| `run` | Run chart | Any sequential data, median center line |
| `i` | Individuals (I) chart | Continuous data, one observation per subgroup |
| `mr` | Moving range | Variation between consecutive observations |
| `xbar` | X-bar chart | Continuous data with subgroups (paired with `s`) |
| `s` | S chart | Subgroup standard deviation |
| `t` | Time-between-events chart | Time or count between rare events |
| `p` | P chart | Proportion (percent) defective, unequal subgroup sizes |
| `pp` | P′ (Laney) chart | Proportion data with overdispersion |
| `c` | C chart | Count of defects, constant opportunity |
| `u` | U chart | Rate of defects, unequal opportunity |
| `up` | U′ (Laney) chart | Rate data with overdispersion |
| `g` | G chart | Number of opportunities between rare events |
| `oe` | O/E (SMR) chart | Observed vs risk-model expected events, e.g. mortality O/E |
| `oep` | O/E with over-dispersion | O/E across many providers, limits widened by √φ̂ |

`qic(..., funnel=True)` renders a funnel plot instead, for cross-sectional comparison
across p/pp/u/up/oe/oep charts sorted by denominator.

### Risk-adjusted O/E funnel plots

**Which chart for a cross-sectional comparison:**

| What you are comparing | Use |
| --- | --- |
| Units on events against exposure (device-days, discharges) | `p` / `u` with `funnel=True` |
| Providers on outcomes against model-expected events (Vizient O/E) | `oe` with `funnel=True` |
| Many providers, where `oe` flags an implausible number of them | `oep` |
| Anything whose summary reports `underpowered` | Aggregate more time, or compare at a higher level, before concluding |

`chart="oe"` compares observed events against model-derived expected events — the form
used for provider-level benchmarking of mortality, readmissions, and complications.
Pass observed counts as `y=` and expected events as `n=`:

```python
qic(x=physicians, y=observed_deaths, n=expected_deaths,
    chart="oe", funnel=True, show_95=True)
```

Limits are exact Poisson probability contours at 95% and 99.8% rather than 3σ
(Spiegelhalter, *Statistics in Medicine* 2005;24:1185-1202), which matters at the
volumes individual physicians actually have: the limits are asymmetric about the center
line, and the lower limit stays above zero where a normal approximation would clip it
and lose better-than-expected outliers. `limit_method="byar"` selects the closed-form
Wilson-Hilferty approximation instead; it drifts from exact below ~20 expected events.

The center line defaults to the pooled ΣO/ΣE, so points are judged against their peers
and any overall miscalibration of the risk model is absorbed. Pass `cl=1.0` to judge
them against the risk model itself.

#### Over-dispersion

Across a few hundred providers, exact Poisson limits typically flag far more than the
nominal 0.2% — real providers differ for reasons no risk model fully captures.
`chart="oep"` applies Spiegelhalter's winsorized multiplicative adjustment
(*QSHC* 2005;14:347-351), widening the limits by √φ̂:

```python
r = qic(y=observed, n=expected, chart="oep", funnel=True)
r.summary["dispersion_phi"]       # 1.0 means no adjustment was warranted
r.summary["dispersion_adjusted"]  # False when the sample is within noise of Poisson
```

φ̂ is estimated from variance-stabilized residuals winsorized at the 10th/90th
percentiles, so the outliers being screened for cannot inflate the limits past
themselves. Like Laney's σ_z it only ever widens: an under-dispersed sample falls back
to the unadjusted limits. These limits are a normal approximation — a multiplicative
variance factor has no exact-Poisson counterpart, so `limit_method=` does not apply.

On a small cohort, note that one extreme provider will drag the pooled center line
toward itself and inflate φ̂ even after its own residual is clipped; pass `cl=1.0` to
anchor the center line if that matters.

#### Physician-level comparison

At individual-physician volumes a funnel is mostly a test with no power. The chance of
flagging a physician whose **true** O/E is 2.0, at the 99.8% limit:

| Expected deaths | 2 | 5 | 10 | 20 | 50 |
| --- | --- | --- | --- | --- | --- |
| Chance of flagging a true O/E of 2.0 | 5% | 21% | 44% | 81% | 99.8% |

Most physicians sit at 5–20 expected events, so a genuinely poor performer is more
likely to be missed than caught. That is a property of the sample size, not of the
method — but it means **absence of a signal is not evidence of acceptable
performance**, and that is exactly how a blank funnel tends to get read.

O/E charts therefore report what they could not have found. Every point carries its own
detectability and interval, and the summary says whether the chart had any reach:

```python
r = qic(x=physicians, y=observed_deaths, n=expected_deaths, chart="oe", funnel=True)

r.data[["observed", "expected", "y", "min_detectable_oe",
        "ci_95_lower", "ci_95_upper", "sigma_signal"]]

r.summary["underpowered"]               # True when the median point can't detect a doubling
r.summary["min_detectable_oe_median"]
r.summary["n_underpowered"]
r.summary["power_note"]                 # one quotable sentence, present only when underpowered
```

- **`min_detectable_oe`** — the smallest true O/E this point would flag 80% of the time.
  A physician at O/E 2.5 who does not signal, but whose `min_detectable_oe` is 4.3, has
  not been cleared; the chart simply cannot see that far at their volume.
- **`ci_95_lower` / `ci_95_upper`** — an exact (Garwood) interval on *this point's own*
  O/E. This is a different object from the funnel band: the band asks where the point
  would fall if the risk model were right and the provider average, while the interval
  asks what range of true performance is consistent with what the provider actually did.
  The band moves with the center line; the interval does not.
- An underpowered chart also captions itself, so the caveat survives being pasted into
  a slide deck. Supplying your own `caption=` replaces it.

Note too that at 99.8% about 0.2% of points flag by chance alone, so in a 500-physician
funnel roughly one signal is expected even when every physician is average.

**The workflow that actually works** is to aggregate until the chart has power. Using
the bundled example (24 surgeons, 3 years):

```python
import pandas as pd
from qikit import qic

df = pd.read_csv("data/examples/physician_mortality_oe.csv")

# Any single year: not one surgeon flags, and underpowered is True.
y2025 = df[df.year == 2025]
qic(x="physician", y="observed_deaths", n="expected_deaths", data=y2025,
    chart="oe", funnel=True).summary["underpowered"]        # True

# Three years pooled: the chart gains resolution and finds three real signals,
# including a high performer below the lower limit.
agg = df.groupby("physician", as_index=False)[["observed_deaths", "expected_deaths"]].sum()
qic(x="physician", y="observed_deaths", n="expected_deaths", data=agg,
    chart="oe", funnel=True).plot()
```

A last caution for anyone reading these in a credentialing context: at 5 expected
deaths, a confidence interval that contains 1.0 means *insufficient information*, not
exoneration. The honest report of a low-volume physician is the interval, not a verdict.

Beyond `qic()`, the package also provides:

- **`paretochart(x, data=...)`** — Pareto chart of categorical frequencies.
- **`bchart(...)`** — Bernoulli CUSUM chart for early detection of shifts in binary
  (pass/fail) data.
- **`design(factors, ...)`** / **`analyze(design_obj, response, ...)`** — full-factorial
  design of experiments (DOE) and effect analysis.

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
