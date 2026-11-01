# Changelog

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
