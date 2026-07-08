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
result.plot()
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

`qic(..., funnel=True)` renders a funnel plot instead, for cross-sectional comparison
across p/pp/u/up charts sorted by denominator.

Beyond `qic()`, the package also provides:

- **`paretochart(x, data=...)`** — Pareto chart of categorical frequencies.
- **`bchart(...)`** — Bernoulli CUSUM chart for early detection of shifts in binary
  (pass/fail) data.
- **`design(factors, ...)`** / **`analyze(design_obj, response, ...)`** — full-factorial
  design of experiments (DOE) and effect analysis.

## Excel add-in

A Microsoft Excel task-pane add-in built on the same charting engine (ported to
TypeScript) lives in [`excel-addin/`](excel-addin/). See
[docs/excel-addin-roadmap.md](docs/excel-addin-roadmap.md) for its architecture and
setup notes.

## References

1. Montgomery DC. *Introduction to Statistical Quality Control*, 8th ed. Wiley, 2019.
2. Provost LP, Murray SK. *The Health Care Data Guide*, 2nd ed. Jossey-Bass, 2022.

## License

MIT
