---
name: provider-funnels
description: Compare hospitals, physicians or units on a quality measure (mortality, readmission, length of stay, infection rate, survey top-box) with qikit's funnel() and report who is unusual. Use when asked to benchmark, rank, flag outliers among, or build a funnel plot of providers.
---

# Provider comparison with qikit.funnel()

`qikit.funnel()` is the single source of truth for provider flags. Do not write your own
limits, p-values, FDR or tier logic; read them from the result.

## 1. Pick the measure from the data you have

| The query returns, per provider (or per case) | Call |
|---|---|
| observed events and risk-model expected events | `measure="oe", y=<observed>, n=<expected>` |
| events out of cases | `measure="proportion", y=<events>, n=<cases>` |
| events over exposure (line-days, patient-days at risk) | `measure="rate", y=<events>, n=<exposure>` |

## 2. Days, minutes, or anything where one case adds many units: use case-level rows

Length of stay as observed/expected **days** is not a count of independent events. Query
one row per stay, not per provider, and let qikit measure how clumped the days are:

```python
stays = session.sql("""
    SELECT provider_id, provider_name, los_days, expected_los_days
    FROM inpatient_stays
    WHERE discharge_date BETWEEN :start AND :end
""").to_pandas()

r = funnel(stays, y="LOS_DAYS", n="EXPECTED_LOS_DAYS", measure="oe",
           unit="PROVIDER_ID", label="PROVIDER_NAME",
           within_dispersion="estimate", worse="higher")
```

Rows sharing a `unit` are summed. If only aggregated rows exist, compute φ in SQL from
stay-level data and pass the number:
`SUM(POWER(los - exp_los, 2) / exp_los) / (COUNT(*) - COUNT(DISTINCT provider_id))`.

Event counts (deaths, readmissions, infections) need none of this; leave
`within_dispersion` at its default.

**If qikit warns "Counts look clustered within providers"**, the chart is wrong as drawn.
Re-run with stay-level rows and `within_dispersion="estimate"` before reporting anything.

## 3. Set direction and the flag rule

- `worse="higher"` for mortality, readmission, LOS, infections; `worse="lower"` for
  satisfaction or top-box. Leave `None` only when both directions matter.
- `signal="limits"` (default): flags match the drawn lines (exact test).
- `signal="fdr"`: when there are hundreds of providers and false alarms are costly.
- Several measures: one call with `facets="<measure column>"` (each gets its own
  center line, spread and FDR step), or one call per measure.

## 4. Read and report

```python
print(r)                                   # summary in words: counts, chance, notes
flags = r.data[r.data.signal != "none"]    # signal is "outlier" or "alert"
r.summary["expected_false_flags"]          # flags expected by chance in each tier
r.summary["notes"]                         # sentences to show the reader verbatim
fig = r.plot()                             # Plotly; st.plotly_chart(fig) in Streamlit
```

Reporting rules:

- Report `outlier` and `alert` separately, and always next to
  `expected_false_flags`. For example, "35 alerts, about 24 expected by chance".
- Quote every sentence in `summary["notes"]`. These cover power, over-dispersion and
  clustered counts.
- A provider inside the funnel is **not** "fine" when `min_detectable` is large or
  `summary["underpowered"]` is True. Say "not enough data to tell".
- Do not re-rank providers by `p_value` into a league table; the tiers are the result.
- Keep the figure's auto caption. It states the rule that colored the points.

## Columns of `r.data`

`unit, label, y, numerator, denominator, cl, lower_outlier, upper_outlier,
lower_alert, upper_alert, p_value, q_value, signal, direction, min_detectable,
ci_lower, ci_upper, excluded` (plus `facet`, and any `hover=` columns).

Full reference: `help(qikit.funnel)`. Methods: `docs/methods.md` in the qikit repository.
