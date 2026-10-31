# Changelog

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
