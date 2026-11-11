---
name: minimum-denominators
description: Recommend a minimum denominator (minimum volume, minimum sample size, case minimum, small-numbers threshold) for a provider quality measure from a reliability target, say how many providers are above and below it, and compare reporting levels to choose a rollup hierarchy, with qikit's funnel().min_denominator() and funnel_rollup(). Use when asked "what minimum denominator should we use for this metric", "how many cases before we report a physician", "is this measure reliable at physician level", or "what level should we roll this up to".
---

# Minimum denominators with qikit

A minimum denominator is the volume at which a provider's score is mostly signal, not
chance. qikit derives it from the measure's own data: `funnel()` measures the spread
between providers, and `min_denominator()` solves for the volume at which reliability
reaches a target. Do not quote a rule of thumb (11, 25 or 30 cases) and do not compute
reliability yourself; read the floor from the result.

This is not the `msd` under `benchmark="abc"`: that is the achievable-benchmark
method's own small-numbers adjustment, and answers a different question.

## 1. Ask for what you were not told

| Ask | Why | Sets |
|---|---|---|
| The measure, and its numerator and denominator columns | The model follows the kind of data | `measure=`, `y=`, `n=` |
| The level compared: physician, group, unit, hospital | Reliability belongs to a level, not to a metric | `unit=` |
| The peer group, if providers should only be compared within a specialty or campus | Each peer group has its own spread and so its own floor | `facets=` |
| What the scores are used for | It fixes the reliability target | `reliability=` |
| The reporting period (month, quarter, rolling year) | Query that period, so the counts above and below the floor are the ones that will be reported | the query |

The reliability target is the user's decision. Offer these and say which you used:

| Use | Target |
|---|---|
| Internal screening, reviewed before anyone acts | 0.5 |
| Scorecards, public reporting, pay, credentialing (Adams et al. 2010) | 0.7 |
| Decisions about one provider | 0.9 |

If the user gives no use, run all three and show them side by side.

## 2. Call funnel() as for a comparison, then min_denominator()

Pick `measure=` exactly as in the provider-funnels skill. Days, minutes, cost and
survey items need case-level rows there, and need them here too.

```python
from qikit import funnel

r = funnel(df, y="observed_deaths", n="expected_deaths", measure="oe", unit="physician")
floors = r.min_denominator([0.5, 0.7, 0.9])
floors[["reliability", "min_denominator", "min_low", "min_high", "denominator_unit",
        "n_above", "n_below", "share_volume_above", "note"]]
floors.attrs["notes"]             # cautions for the whole table: show them
```

| The query returns | Call | The floor is in |
|---|---|---|
| observed and expected events | `measure="oe", y=<observed>, n=<expected>` | expected events, not cases |
| events out of cases | `measure="proportion", y=<events>, n=<cases>` | cases |
| events over exposure | `measure="rate", y=<events>, n=<exposure>` | exposure (line-days, patient-days) |
| a per-case amount, one row per case | `measure="mean", y=<amount>` | cases |

Several measures in one table:

```python
import pandas as pd

measures = {
    "mortality O/E": dict(y="deaths", n="expected_deaths", measure="oe"),
    "30-day readmission": dict(y="readmits", n="discharges", measure="proportion"),
}
table = pd.concat(
    [funnel(df, unit="physician", **call).min_denominator(0.7).assign(metric=name)
     for name, call in measures.items()], ignore_index=True)
```

## 3. To choose a rollup level, compare the levels

When some providers are above the floor and some below, the question becomes where to
roll the small ones up to. `funnel_rollup()` fits each level and returns one table:

```python
from qikit import funnel_rollup

levels = funnel_rollup(df, units=["physician", "practice_group", "department", "hospital"],
                       reliability=0.7, y="readmits", n="discharges", measure="proportion")
levels[["level", "min_denominator", "n_providers", "n_above", "n_below",
        "share_volume_above", "note"]]
levels.attrs["notes"]
```

The rows must be at the finest level or finer (one row per physician, or per case),
with a column for every level. Ask the user for the hierarchy columns if you do not
have them. Each level has its own floor, because the spread between groups is not the
spread between physicians: a coarser level is not automatically reliable.

## 4. Report

- State the floor with its unit and its range: "at least 42 expected deaths (95% range
  18 to 113)". Round the floor up. Use the `note` column's sentence if in doubt.
- State how many providers are at or above the floor and how many are below
  (`n_above`, `n_below`), and the share of volume at or above (`share_volume_above`).
  A floor that most providers miss but most volume clears is usually workable; a floor
  no provider reaches is a finding about the level.
- Quote every sentence in `.attrs["notes"]`. With fewer than 30 providers the floor is
  imprecise: lead with the range.
- **"No minimum denominator" is an answer.** It means the data show no spread between
  providers at this level, so no volume makes the scores reliable. Say so. Then offer
  the remedies: a larger peer group, `tau=` from earlier periods, or a higher level
  (`funnel_rollup()`). Never substitute a conventional threshold.
- When `min_high` is `inf`, the data cannot rule out no spread: call the floor a lower
  bound, not a threshold.
- For a rollup, show the table by level and point to the finest level at which most
  units and most of the volume clear the floor. The choice of level is the user's.
- To list who is below the floor: `r.data[r.data.reliability < 0.7]`.
- A floor is about precision only. A provider above it can still be affected by case
  mix the measure does not adjust for, and physician outcomes often belong mostly to
  the hospital (Goodwin et al. 2013): facet by hospital or campus before concluding.
