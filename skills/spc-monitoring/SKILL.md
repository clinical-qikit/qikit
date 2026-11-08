---
name: spc-monitoring
description: Monitor a healthcare quality measure over time (monthly mortality, H&P within 24 hours, infections, length of stay, wait times) with qikit's qic() control and run charts, and report whether it has changed. Use when asked for an SPC chart, run chart, control chart, XmR or Making Data Count chart, or whether a measure has improved or shifted.
---

# Monitoring a measure over time with qikit.qic()

`qikit.qic()` is the single source of truth for center lines, limits and signals. Do
not compute your own limits or run rules; read them from the result.

Comparing providers with each other is a different question: use `funnel()` and the
provider-funnels skill.

## 1. Shape the data: one row per period, or raw rows with a period column

```python
df = session.sql("""
    SELECT DATE_TRUNC('month', admit_date) AS month,
           SUM(IFF(hp_within_24h, 1, 0))   AS hp_done,
           COUNT(*)                        AS admissions
    FROM admissions
    WHERE admit_date >= DATEADD(month, -36, CURRENT_DATE)
    GROUP BY 1
""").to_pandas()
```

Rows that share an `x` are combined into one subgroup (numerators and denominators
summed), and date or numeric `x` is sorted. `x_period="month"` buckets raw dates, so
row-level data also works. Aim for at least 20 periods; with fewer, say the limits are
provisional.

## 2. Pick the chart

| Per period you have | Call |
|---|---|
| Any measure, and you are unsure | `chart="run"` |
| Events out of cases (H&P in 24 h, mortality %) | `chart="p", y=<events>, n=<cases>` |
| The same, cases in the thousands per period | `chart="pp"` (Laney) |
| Events over exposure (CLABSI per line-day) | `chart="u", y=<events>, n=<exposure>` |
| Observed and expected per period (monthly O/E) | `chart="u", y=<observed>, n=<expected>` |
| One continuous value (mean LOS, median wait) | `chart="i"` |
| Several raw values per period | `chart="xbar"` (and `"s"` for their spread), y = raw values |
| Cases between rare events | `chart="g"`; days between: `chart="t"` |

Use `multiply=100` for percentages, `multiply=1000` for a rate per 1,000.

## 3. Pick the rules

- `method="anhoej"` (default): qicharts2's run rules, a long run on one side or too few
  crossings. Right for run charts and general use.
- `method="nhs"` with `chart="i"` and `worse="higher"|"lower"`: NHS Making Data Count.
  Each point gets `variation` (`improving`, `concerning`, `common`) and
  `special_cause`. Add `target=<value>` for `summary["assurance"]` (`pass`, `fail`,
  `variable`). Use this when the audience uses Making Data Count boards.
- `method="ihi"`: Provost and Murray, for teams trained on the IHI rules.

## 4. Set the baseline

- `freeze=<k>`: limits from the first k points; later points are judged against them.
  Use this when monitoring after a stable baseline, so new data cannot move the limits.
- `part=<k>` (or a column whose value changes between phases): a new center line and
  limits after a known change, such as a new protocol. Only split at a change you can
  name, never to make a signal go away.
- `exclude=<column or positions>`: points with a known special cause (a data outage),
  left out of the limits and still drawn.

## 5. Read and report

```python
r = qic(df, x="MONTH", y="HP_DONE", n="ADMISSIONS", chart="p", multiply=100)
print(r)                                   # what fired, in words
r.data[r.data.signal == "outlier"]         # points beyond the 3-sigma limits
r.data[r.data.runs_signal]                 # points in a run or trend
r.summary                                  # rules fired, limits, by_facet
fig = r.plot(title="H&P within 24 hours")  # Plotly; st.plotly_chart(fig)
```

Reporting rules:

- A point beyond the limits (`signal == "outlier"`) and a pattern (`runs_signal`) are
  both special cause. Name which one fired, and when.
- Too few crossings marks the whole series, not single points:
  `summary["crossings_signal"]`.
- No signal means the process is stable, not that it is good. Compare the center line
  with the target; with `method="nhs"` report `assurance`.
- With `part=`, describe the latest part as the current process; `summary["parts"]`
  holds each part.
- A shift that starts at a known change is evidence the change worked (or harmed).
  Recommend `part=` at that point only when the change is real and documented.
- Do not recompute limits after removing points to "clean" the chart. Use `exclude=`
  with a stated reason.

## 6. Many measures or units at once

`facets=` takes one column or a list. Each combination gets its own chart, limits and
rules, and the facet columns lead `r.data`:

```python
r = qic(df, x="MONTH", y="NUM", n="DEN", chart="p", facets=["MEASURE", "SERVICE"])
r.data                                     # write back to a table
```

For a Snowpark stored procedure or UDTF, see `docs/snowflake.md`.

## Columns of `r.data`

`x, y, cl, ucl, lcl, ucl_95, lcl_95, signal, runs_signal, baseline, excluded`, plus
`n`, `label`, `part`, `target`, `notes`, `variation` and `special_cause` when the matching
option is used, the `facets=` columns first, and any `hover=` columns.

Display options (`title=`, `styles=`, `y_percent=`, `show_95=`, sizes) go to
`r.plot()`, not to `qic()`.

Full reference: `help(qikit.qic)`. Methods and departures from qicharts2:
`docs/qic-methods.md`.
