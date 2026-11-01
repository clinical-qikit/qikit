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

## 2. Days, survey items, or anything where one case adds many units: use case-level rows

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

Rows sharing a `unit` are summed.

**Too many stays to pull?** Aggregate in SQL to one row per provider and pass the
sufficient statistics. The result equals the stay-level call to rounding, including the
clustering check:

```python
prov = session.sql("""
    SELECT provider_id, provider_name,
           SUM(los_days)                                  AS obs,
           SUM(expected_los_days)                         AS exp,
           COUNT(*)                                       AS n_stays,
           SUM(POWER(los_days, 2) / expected_los_days)    AS sum_sq,
           MAX_BY(los_days, los_days - expected_los_days)          AS max_obs,
           MAX_BY(expected_los_days, los_days - expected_los_days) AS max_exp
    FROM inpatient_stays
    WHERE discharge_date BETWEEN :start AND :end AND expected_los_days > 0
    GROUP BY provider_id, provider_name
""").to_pandas()

r = funnel(prov, y="OBS", n="EXP", measure="oe", unit="PROVIDER_ID",
           label="PROVIDER_NAME", within_dispersion="estimate",
           cases="N_STAYS", sum_sq="SUM_SQ",
           max_case_y="MAX_OBS", max_case_n="MAX_EXP", worse="higher")
```

`sum_sq` is the raw `SUM(POWER(y, 2) / n)`, not a residual: qikit forms the residuals.
`fragility` needs stay-level rows; the `max_case_*` columns give `p_value_drop1` and
`flag_survives_drop1` only.

**Variability that differs by DRG or service line.** Compute each DRG's φ_g in SQL, then
per provider `SUM(phi_g * expected_los_days) / SUM(expected_los_days)` as a column, and
pass `within_dispersion="<that column>"`. The plot's x axis then shows the effective
expected days (`effective_denominator`). Never pass a provider's *own* residual variance
as its φ: that hides exactly the providers with long, variable stays.

Event counts (deaths, readmissions, infections) need none of this; leave
`within_dispersion` at its default.

### Multi-question surveys and audits: one row per survey, not per item

HCAHPS composites ("Communication with Doctors": explains, listens, respects) are scored
per item, but one patient answers all three alike, so the items are not independent.
Passing item counts per physician treats 12 items from 4 surveys as 12 independent
answers when they carry about 5, which over-flags small panels and inflates `tau`.
Query one row per survey and let qikit measure the clustering:

```python
surveys = session.sql("""
    SELECT survey_id, physician_id,
           SUM(IFF(answer = 'Always', 1, 0)) AS always,     -- top-box items
           COUNT(answer)                     AS answered    -- items answered
    FROM hcahps_doctor_items
    WHERE discharge_date BETWEEN :start AND :end
    GROUP BY survey_id, physician_id
""").to_pandas()

r = funnel(surveys, y="ALWAYS", n="ANSWERED", measure="proportion",
           unit="PHYSICIAN_ID", within_dispersion="estimate",
           worse="lower", signal="fdr")
```

- Do **not** pass one row per item: a single yes/no cannot show clustering, and
  `"estimate"` refuses it.
- Bottom-box is a separate call (or facet) with its own `worse="higher"`.
- At a few surveys per physician most providers cannot flag anything: read
  `min_detectable` and `summary["underpowered"]` before calling a quiet physician "fine".

**If qikit warns "Counts look clustered within providers"**, the chart is wrong as drawn.
Re-run with case-level rows (stays, or surveys) and `within_dispersion="estimate"`
before reporting anything.

## 3. Set direction and the flag rule

- `worse="higher"` for mortality, readmission, LOS, infections; `worse="lower"` for
  satisfaction or top-box. Leave `None` only when both directions matter.
- `signal="limits"` (default): flags match the drawn lines (exact test).
- `signal="fdr"`: when there are hundreds of providers and false alarms are costly.
  Many very-low-volume providers? Add `fdr_min_denominator=<E>`. It sets a volume floor
  for the FDR step only; those providers keep a `p_value` and still flag under
  `"limits"`. Choose the floor from volume alone, never from outcomes.
- τ (the spread between providers): leave `tau_method="spiegelhalter"` (the default,
  as published). It is the screening choice: robust to outliers and errs toward
  flagging.
  - Flags acted on one by one, where the 0.1% and 2.5% chance rates must hold (for
    example credentialing): `tau_method="winsorized"`, the debiased estimator.
  - Reproducing a CQC or NHS SHMI funnel: `tau_method="cqc"` or `"shmi"`.
  - Fewer than 30 providers, or a validated τ from earlier periods: pass
    `tau=<value>`. If `summary["notes"]` says the current estimate differs more than
    1.5-fold, report that.
  - `tau_method="ml"` only with no gross outliers; it reports `summary["tau_ci"]`.
- Two questions, two settings. "Unusual among peers?" is the default. "Different from
  what the risk model predicts?" is `overdispersion=False, center=1.0`, usually with
  `signal="fdr"` to control false alarms.
- **Does a flag depend on the model?** Before reporting a borderline flag, run
  `funnel_sensitivity(<same arguments>)`. It returns one row per provider with
  `signal_spiegelhalter`, `signal_winsorized`, `signal_ml`, `signal_unadjusted` and
  `consistent`. Report a flag that is not consistent as model-dependent.
- **A goal to show beside the funnel** (with `worse=`; methods §4.18):
  - Process proportions (H&P in 24 h): `benchmark="abc"`, the achievable benchmark of
    care. `summary["benchmark"]` holds `value`, `providers`, `group_denominator` and
    `without_small`. If `without_small` differs, a note says the ABC leans on
    low-volume providers; quote it.
  - Outcomes (O/E mortality, LOS, readmission): `benchmark="eb"`, the 90th percentile
    of the shrunk estimates. Report it rather than an ABC. If both were run and the
    ABC is far better than `"eb"`, say the ABC pools lucky low-volume providers.
  - Peer groups (teaching vs community, specialty): `facets=` gives each its own
    benchmark. Choose them before looking.
  - `benchmark_share=` (default 0.10) is set before looking, never tuned afterwards.
  - Use it in confidential feedback only, never for credentialing, compensation or
    public report cards.
- Several measures: one call with `facets="<measure column>"` (or a list of columns);
  each gets its own centre line, spread and FDR step, and the facet columns lead
  `r.data`.

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
  To order *flagged* providers for action, sort by `eb_excess` (expected excess
  days/events after shrinkage), not `raw_excess`, which favours high volume.
- `signal` answers "unusual among peers?". `prob_worse` answers "probably worse than
  average?" (the CMS question). Name the question you report, and don't flag on
  `prob_worse` unless the user asked that question.
- Report `reliability` with any single-provider number. Below about 0.7 a score is too
  noisy for high-stakes use. Reliability 0 everywhere means the chart found no spread
  between providers (τ̂ = 0): no provider is reliably different.
- For each flagged provider, report `fragility` (stay rows) or `flag_survives_drop1`. A
  fragility of 1 on length of stay means one stay carries the flag, so ask for that case
  to be reviewed before acting. On event counts it is expected at low volume (every event
  is one patient) and is not by itself a reason to discount the flag.
- Do not compute your own shrinkage, leave-one-out p-values or q-values from
  `p_value_drop1`. It is descriptive, and no false discovery rate survives choosing each
  provider's worst case.
- Keep the figure's auto caption. It states the rule that colored the points.
- Report a benchmark as "the best providers here achieve X", never as a standard a
  provider failed. `meets_benchmark` False is not a signal; at low volume it is often
  chance.

## Columns of `r.data`

`unit, label, y, numerator, denominator, cl, lower_outlier, upper_outlier,
lower_alert, upper_alert, p_value, q_value, signal, direction, min_detectable,
ci_lower, ci_upper, excluded, raw_excess, reliability, eb_rate, eb_excess, prob_worse,
p_value_drop1, flag_survives_drop1, fragility` (plus `effective_denominator` under a
`within_dispersion` column; `benchmark`, `meets_benchmark` and, for the ABC only,
`benchmark_group` with `benchmark=`; the `facets=` columns first; and any `hover=`
columns).

Display options (`title=`, `styles=`, `label_signals=`, `x_log=`, sizes) go to
`r.plot()`, not to `funnel()`.

Full reference: `help(qikit.funnel)`. Methods: `docs/methods.md`; CQC and SHMI in
§4.17; choosing τ in §4.16. Writing results back from a stored procedure or UDTF:
`docs/snowflake.md`.
