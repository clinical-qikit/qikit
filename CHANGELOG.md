# Changelog

## 1.3.0 (2026-11-10)

A predictable, compact surface for pipelines and agents. Nothing is removed.

### Added

- **`qikit.schema("qic" | "funnel")`:** every column `result.data` can hold, with its
  type, whether every call produces it, and its meaning. It is now the single source of
  the column lists.
- **`result.to_table()`** on `qic()` and `funnel()` results: `.data` with every schema
  column, in schema order and with fixed types (nullable booleans and integers, strings
  as objects), empty where the call did not produce it; the `facets=` columns first and
  the `hover=` columns last. The shape a database table or a Snowpark `RETURNS TABLE`
  clause needs, whatever options the call used.
- **`result.brief(digits=4, limit=25)`:** what was found as a small JSON-safe dict: the
  verdict or counts, the notes, and only the flagged points (the most recent) or
  providers (outliers first, then by p-value). About 1 KB where `to_json()` is tens.
- **`result.facet_summary()`:** the summary as a table, one row per facet, with the
  same columns faceted or not.
- **`to_dict(digits=)` and `to_json(digits=)`:** round every number to that many
  significant figures. Default unchanged.
- **Choices ignore case and surrounding spaces** (`measure="OE"`, `signal=" FDR "`),
  and a misspelt choice or keyword suggests the closest: `measure must be one of ...,
  got 'proportions'. Did you mean 'proportion'?`; `qic() got an unexpected keyword
  argument 'charts'. Did you mean 'chart'?`.
- **The signatures spell out the choices** as `Literal` types (`chart`, `method`,
  `measure`, `worse`, `signal`, `tau_method`, `benchmark`, `compare_to`, `agg_fun`), so
  `help()`, editors and type checkers show them.

### Fixed

- `to_json()` raised on Python `date` values in `x` and `Decimal` unit ids, as Snowpark
  returns DATE and NUMBER columns. Dates serialize as ISO text, Decimals as numbers.
- A faceted `qic()` summary lacked the top-level `runs_signal`.
- `qic()`'s docstring did not document the `special_cause` column.

## 1.2.1 (2026-11-10)

Messy input no longer becomes a silent wrong answer.

### Fixed

- **`funnel()` read a missing value as zero.** A provider whose `y` was missing was
  summed to 0 events and could be flagged a low outlier. A row missing `y`, `n` or
  `unit` is now left out of the sums and counted in the new
  `summary["n_rows_dropped"]`, with a note; a provider with no complete row is listed
  with no value and is not tested. A missing denominator no longer raises "events but a
  zero denominator", and rows with a missing `unit` are no longer dropped unannounced.
- **`qic()` charted Python `date` objects in row order.** Snowpark's `to_pandas()`
  returns a DATE column as `datetime.date` objects, which were treated as text and left
  unsorted, so limits and run rules were computed on shuffled time. They are now sorted
  like any other date, and `.data["x"]` keeps the `date` objects.
- **`qic()` turned text that is not a number into a gap.** `"x"` or `"n/a"` in `y`,
  `n` or `target` now raises a `ValueError` showing the values; `funnel()` and
  `bchart()` give the same message in place of a raw numpy error. None, NaN, blank
  text, numeric text and Decimals are read as before.
- **A handful of points was called stable.** `print(qic(y=[5]))` no longer says "the
  process looks stable".

### Added

- **`qic()` `summary["notes"]` and `summary["provisional"]`:** sentences to show a
  reader (fewer than 12 baseline points, control limits from fewer than 20, points with
  no value, a frozen baseline), as `funnel()` already had; `provisional` is True under
  12 baseline points. Faceted, the notes are prefixed by facet. `print(result)` shows
  them.
- **Column-name errors list the columns and suggest the closest**, ignoring case, in
  `qic()`, `funnel()` and `paretochart()`: `y='deaths' is not a column of data. Did you
  mean 'DEATHS'?`. `funnel()`'s message changes from "must name a column of data".

## 1.2.0 (2026-11-08)

### Added

- **`compare_to=` on `funnel()`:** names which question the chart answers.
  `"peers"`: the pooled center line and `overdispersion=True` (the default settings).
  `"model"`: O/E against the risk model's expected, `center=1.0` and
  `overdispersion=False`; `measure="oe"` only, and a proportion or rate is told to pass
  `center=<target>, overdispersion=False`. A `center=` or `overdispersion=` that
  contradicts it is an error naming the fix; agreeing values are allowed.
  `summary["compare_to"]` records `"peers"`, `"model"` or `"custom"` on every call, and
  `print(result)` ends its first line with the question. Passing `compare_to=` adds a
  note saying which question the chart answers. `funnel_sensitivity()` forwards
  `"peers"` and rejects `"model"`, whose runs would all be the same chart.
  - `overdispersion=` now defaults to `None` (meaning `True` unless
    `compare_to="model"`), so an agreeing value can be told from an unset one. Every
    existing call resolves as before.
- **A warning for a fixed center under the spread allowance:** `center=` with
  `overdispersion=True` let τ̂ absorb any system-wide gap between the providers and the
  center, silently widening every limit (`center=1.0` on a system running 10% above
  its risk model nearly quadrupled τ̂). When the gap is beyond chance (p < 0.001, a
  sandwich-variance t test) and widens the limits at the median volume by at least
  10%, `funnel()` raises a `UserWarning` and adds a note with the gap, the widening and
  the fix. New summary keys `center_gap`, `center_gap_p` and `tau_pooled`. Skipped
  under a pre-specified `tau=`. Calibrated by `scripts/simulate_center_gap.py`: at most
  0.4% false warnings in any cell; methods §4.2.1, §5.
  - README, the docstring, AGENTS.md (a new funnel decision recipe, with a canonical
    physician LOS vs Vizient expected call and scorecard-wide FDR), the provider-funnels
    skill and `llms.txt` now pair "against the risk model" with `compare_to="model"`
    rather than `center=1.0` alone. The README's "identical when τ̂ = 0" now says it
    holds around the pooled center only.
  - Python only; the Excel add-in does not draw funnels.

- **`measure="mean"` on `funnel()`:** compares providers on a per-case amount, such as
  EHR minutes per discharge or cost per case, in the amount's own units. Pass one row
  per case (`y=` the amount; `n=` may be omitted), or SQL totals (`y=SUM`,
  `n=COUNT(*)`, `sum_sq=SUM(y*y)`). The center line is the pooled mean, and cases are on
  the x axis. It is the quasi-Poisson model with `within_dispersion` always estimated,
  so every option applies: `worse=`, `signal="fdr"`, `tau_method`, `max_case_y=`,
  `benchmark="eb"`, `facets=` and `multiply=`. It gives exactly the result of the
  earlier workaround (each case ÷ the pooled mean as O/E, then `multiply=`), without
  the rescaling. Methods §4.19.
  - `summary["case_sd"]`: the SD of a single case, in y's units.
  - Amounts must be ≥ 0. A scalar `within_dispersion`, `cases=` and `max_case_n=` are
    refused under `"mean"`, because `n` already is the case count and a single case's
    denominator is 1.
  - `n=` is now optional in the signature; every other measure still requires it.
  - The `benchmark=` docs now say which option suits which measure: `"abc"` for
    proportions, `"eb"` for `"oe"`, `"rate"` and `"mean"`.
  - Python only; the Excel add-in does not draw funnels.
- **Shrunk estimates with a range, and a caterpillar plot:** new columns `eb_low` and
  `eb_high`, an equal-tailed interval for each provider's true value from its exact
  posterior (gamma on counts, beta on proportions, on effective counts), with
  `interval=` (default 0.95), and `estimate_flag`: `"worse"`, `"better"` or
  `"no different"` (`"higher"`/`"lower"` without `worse=`) as the interval lies against
  the reference. `estimate_flag` answers "clearly worse than the reference?", where
  `signal` answers "unusual?"; `signal` is unchanged. No interval and a note when there
  is no measurable spread. `result.plot(kind="caterpillar")` draws them: providers
  sorted by `eb_rate`, intervals colored by `estimate_flag`, raw values faint, the
  reference dotted, small multiples per facet, and `top=`/`bottom=` for long lists.
  New summary keys `reference` and `estimate_tau`. Methods §4.14, §5.
  - **The estimate columns' prior now uses the ML τ̂** (or `tau=`) whatever
    `tau_method` the limits use, so **`eb_rate`, `eb_excess`, `reliability`,
    `prob_worse` and `benchmark="eb"` values change**. The published estimator
    understates τ: under it 95% intervals covered 49–89% of true values, under ML
    91–95%. Limits, p-values, q-values and `signal` are unchanged. An ML τ̂ that would
    leave every provider's reliability below 0.01 counts as no spread.
  - **Shrinkage against the risk model:** under `compare_to="model"` (and the
    equivalent `center=1.0, overdispersion=False`) the estimate columns, which were
    empty, now use a prior centered on the pooled value with τ̂ around it, and judge each
    provider against 1.0. `tau=` is accepted there and sets only that spread. Limits and
    flags are unchanged.
  - New core helpers `gamma_quantile` and `beta_quantile` (no new dependencies).
  - `docs/examples/hierarchical_readmissions.ipynb`: the patient-level hierarchical
    model in PyMC beside `funnel()`, with an optional hospital level. On its simulated
    data the two agree to a correlation of 0.996.
  - With `within_dispersion` the intervals cover about 90%, not 95% (methods §5).
  - Cited: Keenan 2008, Dimick 2010, Marshall & Spiegelhalter 1998, Goodwin 2013, Jones
    & Spiegelhalter 2011; README physician section now cites Hofer 1999 and Goodwin 2013.
  - Python only; the Excel add-in does not draw funnels.

- **`color_by="fdr"` on `FunnelResult.plot()`:** colors the points by their q-value
  tiers (outlier q < `fdr_levels[0]`, alert q < `fdr_levels[1]`) on a `signal="limits"`
  result. The `signal` column and the drawn 95% and 99.8% lines are unchanged; the
  legend and caption state the q rule. A figure can now match an action list built
  from `q_value` without recoloring traces by name.
  - `fdr_watch=` (e.g. `0.20`) adds a pale, open-diamond watch tier for q below it, on
    the figure only. It has a `watch` role in `styles=`.
  - README, methods §4.11 and the provider-funnels skill now say that under
    `signal="limits"` a point beyond the 95% line can have a large q-value.
  - Python only; the Excel add-in does not draw funnels.

## 1.1.0 (2026-11-01)

### Added

- **`benchmark=` on `funnel()`:** a goal the best providers already reach, drawn as a
  dashed line, with `benchmark_share=` (default 0.10) defining "the best". Both need
  `worse=`; methods §4.18.
  - `"abc"`: Kiefe and Weissman's achievable benchmark of care. Providers are ranked by
    (x + 1)/(n + 2), and the best are pooled until they hold 10% of patients, ties
    included. It reproduces GAMUT's worked example. It reports the providers who set it
    and their volumes, and the minimum sufficient denominator (whose exact rule
    reproduces Kiefe's Table 3). It also gives the ABC without providers below that
    denominator (Hall et al. 2013).
  - `"eb"`: the 90th percentile of the shrunk `eb_rate` toward the better side (O'Brien
    et al. 2008), for outcome measures.
  - `summary["benchmark"]` is one dict: `method`, `share`, `value`, and under `"abc"`
    `providers`, `coverage`, `group_denominator`, `msd`, `n_below_msd` and
    `without_small`. The columns are `benchmark`, `meets_benchmark`, and
    `benchmark_group` under `"abc"`.
  - Python only. The TypeScript engine and the Excel add-in do not have it yet.

## 1.0.0 (2026-11-01)

1.0 is a breaking release. `qic()` and `funnel()` now share one vocabulary, display
options moved to `.plot()`, the package imports without plotly, and both functions were
checked against R (qicharts2, FunnelPlotR, NHSRplotthedots). Every removed or renamed
argument raises a `TypeError` naming its replacement, so running an app once lists the
changes to make.

### Breaking: calling `qic()` and `funnel()`

- **Keyword-only after `data`.** `qic(data=None, *, x=None, y, n=None, chart="run", ...)`
  and `funnel(data=None, *, y, n, measure, ...)`. A positional `qic(x, y)` call raises.
- **Display options moved to `.plot()`:** `title`, `subtitle`, `caption`, `xlab`, `ylab`,
  `styles`, `label_signals`, `x_range`, `y_range`, `show_legend`, `width`, `height` on
  both, plus `x_log` on funnels and `part_labels`, `show_95`, `show_labels`,
  `show_grid`, `show_x_labels`, `decimals`, `point_size`, `x_format`, `x_angle`,
  `x_pad`, `x_order`, `y_expand`, `y_neg`, `y_percent`, `connect`, `runs_highlight`,
  `flip`, `nrow`, `ncol` and `scales` on `qic()`.
- **Renamed arguments:**

  | Old | New | Where |
  |---|---|---|
  | `cl=` | `center=` | both |
  | `point_labels=` | `label=` | both |
  | `hover_extra=` | `hover=` | both |
  | `test_min_expected=` | `fdr_min_denominator=` | `funnel()` |
  | `signal_side=` | `worse=` | `funnel()` |
  | `signal_method=` | `signal=` | `funnel()` |
  | `levels=` | `limits=` | `funnel()` |

- **Removed:** `print_summary`, `y_percent_accuracy` and `strip_horizontal` (no effect),
  and the hidden `chart="ip"` (an i chart of a rate is `chart="i", y=events, n=cases`).
- **`facets=`** takes one column or a list on both functions. The facet columns lead
  `.data` under their own names.

### Breaking: results

- **`qic()` columns.** `sigma_signal` (bool) is now `signal` (`"outlier"` or `"none"`),
  the same column a funnel has. `runs_signal` now marks only the points that form a
  pattern (0.10's `runs_signal_localized`); too few crossings is
  `summary["crossings_signal"]`.
- **`qic()` summary.** `run_signal` is `longest_run_signal`, `run_threshold` is
  `longest_run_max`, `crossings_threshold` is `n_crossings_min`, and `limit_basis` is
  gone. New: `chart`, `method`, `n_outlier`, `runs_signal`, and per-method keys.
- **`funnel()` summary.** `phi_raw` and `phi_debiased` are one key, `phi`, as the chosen
  `tau_method` defines it. `test_min_expected` is `fdr_min_denominator`. New:
  `limit_method`, `tau_scale`, `min_detectable_median`.
- **Every result** has `to_dict()` and `to_json()`. `FunnelResult` lives in
  `qikit.results` with the others.

### Breaking: packaging and modules

- **plotly is optional.** `pip install "clinical-qikit[plot]"` for `.plot()`. The core
  depends only on numpy and pandas, and `import qikit` does not load plotly. `.plot()`
  without plotly raises an `ImportError` naming the extra.
- **Modules.** `qikit.spc` (a package) and `qikit.render` are gone. The numeric core is
  `qikit.core` (`dist`, `constants`, `shewhart`, `rules`, `contours`, `dispersion`,
  `pvalues`, `power`); the front doors are `qikit.spc` (a module) and `qikit.funnel`;
  figures are `qikit.plot`. Import from `qikit` itself; the internal paths are not API.

### Behavior changes

Each moves results on some data. "More" or "less sensitive" is relative to 0.10.

- **`tau_method="spiegelhalter"` is the default again,** in both engines. 0.10's
  debiased default was not sensitive enough for screening in production use: it found
  a planted outlier 38% of the time against 70% (methods §5, K = 150, τ = 0.3). The
  published estimator is also uncorrected like the CQC, NHS and FunnelPlotR estimators.
  Flag rates return to 0.9's. `"winsorized"` remains for when the stated chance-flag
  rate must hold. More sensitive.
- **Run-chart rule (anhoej) matches qicharts2:** longest run > round(log₂ n) + 3, and no
  minimum n. 0.10 used floor(log₂ n) + 3 with ≥. Less sensitive: in simulation false
  signals fall from 2–10% to 0–2%, and power to see a 1 SD shift falls from 37% to 13%
  at n = 30. The crossings rule is unchanged. `method="nhs"` or `"ihi"` restore a
  shorter run under a published rule set.
- **xbar and s charts** take their spread from the baseline and each part, honouring
  `freeze=`, `part=` and `exclude=`. More sensitive after a real change.
- **g chart** limits come from the mean, with the median drawn as the centre line
  (Montgomery, qicharts2). Limits about 10–15% wider. Less sensitive.
- **Laney σ_z** is screened at 3.267·MR̄ and no longer floored at 1. Narrower limits on
  under-dispersed series.
- **`method="ihi"`** uses Provost and Murray's run-chart rules (shift 6, trend 5) on run
  charts, adds 2 of 3 beyond 2σ and 15 within 1σ on Shewhart charts, and passes over
  repeated values in a trend. More sensitive.
- **`n=` divides y on every chart,** as in qicharts2. p and pp upper limits are capped
  at 1; the MR chart's lower limit is 0; a moving range across a part boundary is NaN.
- **Grouped x is sorted** when numeric or a date, so runs and moving ranges follow time.
- **c₄ is exact** (from the gamma function), not a table. A₃, B₃ and B₄ follow it.
  Differences are in the fourth significant figure.
- **A fixed `center=`** counts K degrees of freedom in `"winsorized"`'s τ̂², not K − 1.
  τ̂² is smaller by about 1/K.
- **An estimated within-dispersion below 1** (binary-outcome O/E from case rows) is kept
  and labelled as the binomial-variance correction, not floored.

### Added

- **`method="nhs"`:** NHS England's Making Data Count rules on `qic()`, with
  `variation` and `special_cause` per point, `summary["variation"]`, and
  `summary["assurance"]` against `target=`. Plot colours for improving, concerning and
  neutral special causes. Checked against NHSRplotthedots.
- **`tau_method="cqc"` and `"shmi"`:** CQC and NHS SHMI over-dispersion on the √,
  arcsine or log scale, as FunnelPlotR computes them, with limits drawn on that scale
  and mapped back (`limit_method="transformed_normal"`). Methods §4.17.
- **`funnel_sensitivity()`:** one row per provider with its tier under each τ option and
  a `consistent` flag.
- **Reference tests against R.** `fixtures/reference/` holds 31 cases from qicharts2,
  FunnelPlotR and NHSRplotthedots, regenerated by `scripts/make_reference_fixtures.R`;
  `tests/test_reference.py` checks them to 1e-6, with each departure listed.
- **Validation:** y < 0, y > n on proportions, `center` out of range, `freeze`, `part`,
  `method`, `agg_fun`, and facet names that collide with output columns.
- **Documentation for people and agents:** `docs/qic-methods.md`, `docs/snowflake.md`,
  `src/qikit/AGENTS.md` (shipped in the wheel), `llms.txt`, and the
  `skills/spc-monitoring` skill. `py.typed` marks the package as typed.
- **`tests/test_docs.py`:** every argument, quoted value, summary key and column named in
  the README, AGENTS.md, llms.txt, the skills and the methods docs is checked against the
  code, and the skills' column lists are checked in both directions.

### Fixed (`funnel()`)

- `exclude=` is honoured by `within_dispersion="estimate"` and the clustering check.
- `expected_false_flags["alert"]` counts the alert tier only, under both `signal=`
  modes.
- Above 10⁵ expected events, the limits and p-values both use Byar's approximation and
  `summary["limit_method"]` says `"byar"`.
- `max_case_y=`/`max_case_n=` drop the worst case only on the provider's own side of the
  line.
- Docstrings for `reliability` and the p-values corrected.

### Fixed (`.plot()`)

- A chart with `part=` and text x values (dates read from a CSV) no longer crashes when
  drawing the part labels.

### Performance

| Case | 0.10 | 1.0 |
|---|---|---|
| Proportion funnel, 2,000 providers | 3.6 s | 0.42 s |
| Proportion funnel, 5,000 providers | 10 s | 1.1 s |
| O/E funnel, 5,000 providers | 0.47 s | 0.2 s |

Exact binomial intervals and detectability use safeguarded Newton steps on the log tail,
about five CDF evaluations instead of fifty. The distribution cache evicts least
recently used entries instead of clearing. `.plot()` and `limits()` reuse the contours
computed for the table.

### TypeScript engine

The Excel add-in's engine matches every behaviour change above: the Anhøj thresholds,
`ihi` rules, exact c₄, g, MR, p and Laney limits, and the `tauMethod` default.
The shared fixtures in `fixtures/spc/` were regenerated.

## 0.10.0 (2026-10-31)

### Behavior change

- **The over-dispersion estimate is debiased by default, in both engines**
  (`tau_method="winsorized"`). The 10%-winsorized φ̂ is multiplied by its Gaussian
  consistency factor 1.4735 (Spiegelhalter 2005, eq. 9) before τ² is estimated. τ̂ is larger, the adjusted
  contours are wider, and fewer average providers flag. Without the factor, at 1,000
  physicians (E from 2 to 60), τ̂ was 0 for a true spread of 0.10, and average providers
  flagged at about twice the stated rate. On the bundled example
  (`data/examples/physician_mortality_oe.csv`, three years) τ̂ goes from 0 to 0.113, and
  the same three physicians are outliers. `tau_method="spiegelhalter"` reproduces 0.9
  (and FunnelPlotR/CQC) exactly. The engine core, `qic()` on O/E charts and the
  TypeScript engine (`tauMethod`) use the same default. The shared fixtures that check
  Spiegelhalter's published numbers now pin `tauMethod: "spiegelhalter"`, and three new
  fixtures (`funnel_*_winsorized`) check the default in both engines. See
  docs/methods.md §4.3.

### Added (`funnel()`)

- `tau_method=`: `"winsorized"` (default), `"spiegelhalter"` (as published) or `"ml"`
  (maximum likelihood of the chart's own random-effects model, with a profile-likelihood
  `tau_ci`). `tau=`: a τ fixed in advance (a number, or one per facet). Summary keys
  `tau_method`, `tau_source`, `tau_estimated`, `tau_ci`; notes below 30 providers and
  when a fixed τ has drifted from this period's estimate (§4.16).
- `prob_worse` column: the posterior probability that a provider is worse than average
  (the CMS question), alongside `signal` (unusual among peers) (§4.14, §4.16).

- `reliability`, `eb_rate`, `eb_excess`, `raw_excess` columns: shrinkage by the exact
  posterior mean of the chart's own Poisson–gamma or beta-binomial model (§4.14).
- `p_value_drop1`, `flag_survives_drop1`, `fragility` columns: single-case robustness
  (§4.15). `max_case_y=`/`max_case_n=` supply the worst case from SQL.
- `cases=`/`sum_sq=`: `within_dispersion="estimate"` and the clustering check from one
  row per provider aggregated in SQL; equal to the stay-level result to rounding (§4.12).
- `within_dispersion="<column>"`: one φᵢ per provider (e.g. case-mix weighted by DRG);
  adds `effective_denominator`, the plot's x axis (§4.12).
- `test_min_expected=`: a volume floor for the false discovery rate step only
  (independent filtering) (§4.11).
- Summary keys `phi_raw`, `phi_debiased`, `test_min_expected`,
  `n_filtered`, `n_fragile`, and notes for fragile flags and filtering.

### Performance

- `dist.py` walks are vectorised with strictly sequential numpy accumulations and cached
  per distribution. Every value is bit-identical to 0.9. A 1,000-provider `oep` funnel
  at E from 30 to 2,000 takes about 0.3 s cold, down from 1.3 s. scipy is not required.
  Monkeypatches of the removed `qikit.spc.dist.poisson_cdf` have had no effect since
  0.8 and can be deleted.

### Evaluated and declined

These are recorded in docs/methods.md §6 with reasons: per-provider own-variance
`continuous_oe`, `q_value_loo`, Storey/power-screened FDR, winsorized/median center
lines, and smoothed display contours.
