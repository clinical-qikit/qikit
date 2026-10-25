# Methods: funnel plots and over-dispersion

This is qikit's record of how its funnel plots are computed, which published method each
step follows, and where it deliberately departs from that method and why. The numbered
references at the end are the ones cited, as `[n]`, in the engine's docstrings
(`src/qikit/spc/limits.py`, `dist.py`, `compute.py`, `api.py`) and in the TypeScript
twin (`excel-addin/packages/engine/src/stats.ts`, `spc-core.ts`).

Time-ordered control charts (run, I, p, u, Laney p′/u′, and the rest) follow Provost &
Murray and Montgomery as before and are not covered here, except where a chart code
behaves differently in a funnel.

## 1. Which charts are funnels

| Call | Count model | Limits | Over-dispersion |
|---|---|---|---|
| `chart="p", funnel=True` | Binomial | Exact binomial, 95% and 99.8% [1, A.1.1] | Estimated and reported, not applied |
| `chart="u", funnel=True` | Poisson | Exact Poisson, exposure as denominator [1, A.2.1, A.2.3] | Estimated and reported, not applied |
| `chart="oe"` | Poisson | Exact Poisson on expected events [1, A.2.1] | Estimated and reported, not applied |
| `chart="pp", funnel=True` | Beta-binomial | Exact quantiles of the additive model [1, eq. 11] | Additive τ² [1, §5], applied |
| `chart="up", funnel=True` | Poisson–gamma | Exact quantiles of the additive model [1, eq. 11; 7] | Additive τ² [1, §5], applied |
| `chart="oep"` | Poisson–gamma | Exact quantiles of the additive model [1, eq. 11; 7] | Additive τ² [1, §5], applied |

Without `funnel=True`, p/u keep their 3σ Shewhart limits and pp/up keep Laney's σ_z [6].
`oe`/`oep` are probability-contour charts with or without `funnel=True`; the flag only
controls the sort and the suppression of runs rules.

## 2. What each chart answers

The two kinds of funnel ask different questions, and both are legitimate:

- **Unadjusted** (`p`, `u` and `oe`): *is this provider's result consistent with the
  target, given chance (and, for O/E, the risk model)?* A provider in the upper tail of
  real between-provider variation will flag here, correctly, because it does differ from
  the target.
- **Adjusted** (`pp`, `up` and `oep`): *is this provider unusual given the observed
  spread between providers?* This treats the spread, τ, as "acceptable" variation [1, §5]
  and flags only providers outside it.

Which question applies is a policy decision. Make it before seeing the data, and record
it in the analysis plan [8, step 1]; Spiegelhalter calls the boundary between
acceptable and out-of-control "a matter of judgement" [1, §5]. If the data are
over-dispersed, the spread itself is a finding about the system: unmeasured case mix,
data or coding differences, or real differences in practice. Spiegelhalter is explicit
that adjusting is "purely a temporary measure" while its causes are explored [1, §5].
Every unadjusted funnel therefore reports the estimate (`dispersion_phi`,
`dispersion_tau`, `overdispersed`) and, when it is present, a `dispersion_note` saying
so.

At individual-physician volumes the two usually coincide. τ is rarely detectable with
5–20 expected events per physician; on the bundled 24-surgeon data φ̂ = 0.93 and τ̂ = 0.
When τ̂ = 0 the adjusted chart is the unadjusted chart, to the bit.

## 3. Conformance to Spiegelhalter (2005)

| Element | Spiegelhalter [1] | qikit |
|---|---|---|
| Contours | p = 0.001/0.999 and 0.025/0.975 (§2) | Same, on every funnel |
| Unadjusted limits | Exact binomial (A.1.1) and Poisson (A.2.1), interpolated as (r_p − α) | Same; u follows A.2.3 (N in place of E) |
| Target θ₀ | External, or pooled from the data and treated as known | Same: `cl=`, or pooled Σy/Σn (Σ O / Σ E) |
| Residuals for over-dispersion | Pearson z on the natural scale (eq. 4) | Same |
| Robustness | 10% winsorized φ̂ (eqs. 6, 8) | Same |
| Winsorizing debiasing factor w(q) | Derived (eq. 9), not adopted in his example | Not applied (§4.3) |
| Multiplicative model | φ̂, applied if φ̂ > 1 + 2√(2/I) | Not used (§4.4) |
| Additive model | τ̂² by method of moments (eq. 10), 0 if φ̂ < (I−1)/I | Same |
| Adjusted limits | θ₀ ± z√(V + τ²), normal (eq. 11) | **Differs**: same variance, exact mixture quantiles (§4.5) |
| Under-dispersion | Never narrow the limits | Same |
| X-axis | Indicator against precision ρ, smooth pre-drawn limits (§2) | **Differs**: providers in volume-rank order, limits per point (§6) |
| Outcome–volume association | Formal regression test (§4) | **Not yet** (§6) |
| Multiple comparisons | Small P values; FDR "best carried out separately" (§6) | Same; the 95% band is a warn tier kept out of `signals` |
| Change data, continuous outcomes | A.1.2, A.2.2, A.3 | Not offered |
| Per-point power and intervals | Not part of the method | Extension on `oe`/`oep` and p/u funnels (§4.8) |

## 4. Design choices

### 4.1 Exact limits, interpolated

Every funnel draws the exact discrete quantile with Spiegelhalter's continuity
interpolation: r_p is the smallest count with F(r_p) ≥ p, and the limit is
(r_p − α)/n with α = (F(r_p) − p)/f(r_p) [1, A.1.1]. The normal approximation of eq. 3 is
symmetric and badly placed at the volumes individual providers have. At 5 expected events
and O/E = 1, the 99.8% limits are:

| Method | Lower | Upper |
|---|---|---|
| Exact Poisson (qikit) | 0.00 | 2.55 |
| Normal, natural scale (eq. 3) | 0 (clipped) | 2.38 |
| Normal, square-root scale | 0.10 | 2.86 |
| Normal, log scale | 0.25 | 3.98 |

The transformed-scale versions flag a zero-death physician (P = 0.7%) or a three-death
physician against ten expected (P = 1.0%) as better than expected at the nominal 0.1%.
The natural-scale version's upper limit is too tight, so it over-flags high outliers.

R's `qpois`/`qbinom` return r_p without the interpolation, so an external cross-check
should bracket qikit's value between r_p − 1 and r_p.

### 4.2 Center line

The default is the pooled rate (Σy/Σn, or ΣO/ΣE), which judges providers against their
peers and, for O/E, absorbs overall miscalibration of the risk model. `cl=1.0` judges O/E
against the risk model itself. The pooled line includes each provider. On a small cohort,
one extreme provider drags the line toward itself, leaves every other provider to one
side, and inflates τ̂ even though its own residual is winsorized. This is the circularity
[1, §5] attributes to Marshall et al. The test suite pins a case where it hides the
provider entirely (`test_a_lone_outlier_still_leaks_in_through_the_pooled_center_line`).
Anchoring with `cl=` removes the effect. Pavlou et al. [9] suggest a pre-specified τ as
another remedy (§6).

### 4.3 The over-dispersion estimator, as published

`funnel_dispersion()` implements [1, §5] exactly:

1. Pearson residuals zᵢ = (yᵢ − θ₀)/√V₀ᵢ, with V₀ᵢ = θ₀/nᵢ for counts and θ₀(1 − θ₀)/nᵢ
   for proportions (eq. 4).
2. Winsorize at the 10th and 90th percentiles; φ̂ = mean(z_W²) (eqs. 6, 8).
3. τ̂² = (Kφ̂ − (K − 1)) / (Σwᵢ − Σwᵢ²/Σwᵢ), wᵢ = 1/V₀ᵢ (eq. 10, the DerSimonian–Laird
   form [3]), and τ̂² = 0 when φ̂ < (K − 1)/K.

**No debiasing factor.** Winsorizing 10% from each tail shrinks the variance of a normal
sample to 0.68 of its value. Spiegelhalter derives the correction w(0.10) = 1.47
(eq. 9), but reports that it gave "somewhat wide limits" and does not adopt it in his
example. FunnelPlotR [13] and the CQC/SHMI implementations follow the example. qikit
does the same, so its numbers reproduce the published method. The consequence is
directional and is documented rather than corrected: under pure chance φ̂ averages about
0.68, the estimate engages only for clear over-dispersion, and τ̂ runs low (median 0.22
when the true τ = 0.3, K = 30). The method therefore under-adjusts, which errs toward
more flags rather than fewer. For a screening chart that erring sends a provider to
review rather than clearing them.

**Pearson rather than square-root residuals.** qikit 0.4's `oep` used the square-root
scale, 2(√O − √(θ₀E)), as the CQC variant does, on the grounds that Pearson residuals
are skewed at small counts. After winsorizing, the difference is negligible at physician
volumes: simulated τ̂ is within 0.015 of the square-root variant, and the bundled
surgeons give τ̂ = 0 either way. The natural scale is [1]'s, and it feeds eq. 11
directly, with no delta-method mapping.

### 4.4 Additive, not multiplicative

Spiegelhalter presents both models and illustrates the difference in his Figure 6.
Multiplicative φ inflates every provider's variance by the same factor, so the band keeps
closing onto θ₀ at high volume. Additive τ² adds a constant between-provider variance, so
the band is "essentially independent of volume" there [1, §5]. His companion paper finds
the additive formulation has the stronger conceptual foundation [2], and it is what CQC,
NHS SHMI and FunnelPlotR use. Pavlou et al. [9] reach the same preference for
random-effects approaches when the common-mean assumption fails.

For physician comparisons the choice matters at both ends of the funnel:

- **Small volume.** V₀ dominates, and additive τ² barely moves the limits. Multiplicative
  φ widens them most, in absolute terms, exactly where power is already 5–44%.
- **Large volume.** Additive limits level off at roughly θ₀ ± z·τ, so a busy provider is
  not flagged for a difference smaller than the spread between providers.

qikit 0.4's multiplicative `oep` had a further defect. When φ̂ was clamped to 1 it still
drew normal-approximation limits, 7–10% *tighter* than `oe` at E ≤ 8. Switching to `oep`
"to be safe" therefore produced more high flags. In 0.5, `oep` with τ̂ = 0 is `oe`.

### 4.5 Adjusted limits drawn exactly

Eq. 11 describes a model in which providers' true rates θᵢ are spread around θ₀ with
variance τ², and observed counts are Poisson or binomial given θᵢ. Drawing θᵢ from a
gamma distribution (counts) or a beta distribution (proportions) with that mean and
variance gives the classic hierarchical model for standardized ratios [7], whose
marginal distributions are exact:

| Family | Count distribution | Variance on the indicator scale |
|---|---|---|
| Counts (`up` and `oep`) | Poisson–gamma (negative binomial), size θ₀²/τ² | θ₀/n + τ² (eq. 11 exactly) |
| Proportions (`pp`) | Beta-binomial, α + β = θ₀(1 − θ₀)/τ² − 1 | θ₀(1 − θ₀)/n + τ²(n − 1)/n |

qikit draws the interpolated quantiles of these, as §4.1 does for the unadjusted ones.
This is the one methodological departure from [1]: same model and same variance, exact
rather than normal quantiles. It is the substitution [1, Appendix A] itself makes for the
unadjusted limits. Neither Verburg et al. [8] nor Pavlou et al. [9] evaluate it. Verburg
uses multiplicative φ̂ because the additive model could not be combined with exact
binomial limits. Pavlou uses the additive model on the log scale and accepts the normal
approximation, warning that it may fail at small counts. The mixture distributions
remove that trade-off.

Implementation notes (`dist.py`, `stats.ts`):

- **Arithmetic only.** Each pmf is built from its term ratio f(k+1)/f(k) outward from
  the mode and normalised at the end. It uses only + − × ÷, so results are bit-identical
  across platforms and between Python and TypeScript. There is no lgamma cancellation as
  τ² → 0, and the cost scales with the distribution's spread, not its mean.
- **Validated** against `scipy.stats` (`binom`, `nbinom`, `betabinom`) to < 1e-9, and one
  beta-binomial case against 60-digit `mpmath`. There scipy itself is off by ~1e-5, from
  the cancellation this design avoids.
- **Fallbacks.** A non-integer denominator, a spread no beta distribution can have
  (τ² ≥ θ₀(1 − θ₀)), or a distribution too wide to walk (only absurd τ) falls back to
  eq. 11 as published. `summary["limit_method"]` then says `"normal"` instead of
  `"exact"`.

### 4.6 Laney's p′/u′ stay for time order

Laney's σ_z is the mean moving range of consecutive standardized residuals [6]. That
statistic depends on order and is defined for time series [11]. In a funnel the order is
the sort by volume. On the bundled 3-year surgeon data, the published test finds no
over-dispersion, yet the 0.4 `up` funnel widened its limits 1.87× and hid all three real
signals. In 0.5, `pp`/`up` use the additive method inside a funnel and Laney outside one.
`summary["dispersion_method"]` says which.

### 4.7 Warn tier and multiplicity

The 95% contour marks `warn_signal` points, which are counted in `n_warn` and kept out
of `signals`: at one chance alarm in twenty per provider, a large funnel would always
report a signal. The 99.8% contour drives `sigma_signal`. With 99.8% limits about 0.2%
of providers flag by chance, roughly one in a 500-provider funnel. Formal FDR control
[12] is deferred, as [1, §6] recommends doing it separately.

### 4.8 Power and intervals

Not part of [1]. At physician volumes a funnel mostly cannot detect even a doubling of
risk [10], and a blank funnel reads as a clean bill of health. This is in the spirit of
Verburg's sample-size step [8, step 3], with a doubling rather than 1.5× as the
reference effect. Power is fixed at 80% and is not a parameter: on a chart that feeds
credentialing, a tunable threshold invites reporting whichever number reads best.

**The detectable effect.** It is measured against the limit the chart actually draws,
including the wider limits of `oep`/`pp`/`up`: the question is whether this point would
flag on *this* chart. Signals fire strictly above `ucl`, so a count flags when
X ≥ ⌊ucl·n⌋ + 1. The smallest true effect with 80% power is the one at which
F(⌊ucl·n⌋) = 0.2. That equation is solved exactly by bisecting the CDF in its own
parameter, never by scanning over ratios:

| Chart | Count model | Solved for | Column (y scale) | Per-point 95% CI |
|---|---|---|---|---|
| `oe`, `oep` | Poisson(ρE) | mean, then ρ = μ/E | `min_detectable_oe` | Garwood [5] |
| `u`, `up` funnel | Poisson(θn) | mean, then θ = μ/n | `min_detectable` | Garwood [5] |
| `p`, `pp` funnel | Binomial(n, θ) | θ directly | `min_detectable` | Clopper–Pearson [14] |

A u funnel's algebra is the O/E chart's with exposure in place of expected events, so it
reuses the same functions. A Clopper–Pearson interval inverts the exact binomial test the
same way Garwood inverts the Poisson one: the lower bound is the θ at which x or more
events has probability 0.025, and the upper bound is the θ at which x or fewer does.

**Cross-platform reproducibility.** The Poisson solve sums lgamma terms, whose last ulp
differs between platforms, so it is quantized to 1e-9. The binomial solve is lgamma-free. Its CDF is built from the
term ratio outward from the mode, using the same walk as the binomial limits (§4.5), and
normalized by its own total, so (1 − θ)ⁿ, which underflows at hospital volumes, is never
formed. It uses only + − × ÷, so the bisection takes the same path on every platform and
in both engines, and needs no quantizing.

**The summary.** Every chart reports `underpowered`, `n_underpowered` and, when
underpowered, a quotable `power_note`. Ghosted (`exclude=`) points are left out: they
cannot flag, so they say nothing about the chart's reach.

- **O/E.** The test is `min_detectable_oe > 2`, with the median reported as
  `min_detectable_oe_median`.
- **p/u funnels.** A proportion or rate has no natural unit, so the test is relative to
  the center line: `min_detectable / cl > 2`, with the median of that ratio reported as
  `min_detectable_ratio_median`. On a p funnel with cl ≥ 0.5 a doubling is not a
  proportion. There only points that cannot flag at all count as underpowered; the ratio
  still says how far above the line a point would have to be.

**Edge cases.** A point whose limit reaches n cannot flag at any θ. Internally its
detectable proportion is infinite, so it counts as underpowered and enters the median;
the column shows NaN. With exact interpolated limits this is effectively unreachable.
A non-integer denominator (an averaged or weighted n) has no binomial description,
which is why its limits fall back to the normal approximation. For the same reason its
detectability and interval are NaN rather than approximated.

## 5. Evidence from simulation

The engine was run on simulated cohorts, 300 replicates per row; reproduce the table
with `uv run python scripts/simulate_funnel_dispersion.py`. Volumes are E ~ U(3, 30) for counts and
n ~ U(20, 200) for proportions (base rate 12%). True provider effects are drawn with
relative SD τ, plus one planted outlier (O/E 2.5 at E = 15, or 30% at n = 120).

"In-distribution" is the share of non-outlier providers flagged above the 99.8% limit;
the nominal rate is 0.1%. "Outlier" is how often the planted outlier is detected.

| Family | K | τ | Unadjusted, in-distribution | Unadjusted, outlier | Adjusted, in-distribution | Adjusted, outlier | τ̂ median (IQR) |
|---|---|---|---|---|---|---|---|
| Counts | 30 | 0 | 0.06% | 93% | 0.05% | 93% | 0 (0–0) |
| Counts | 30 | 0.15 | 0.32% | 94% | 0.16% | 89% | 0.01 (0–0.13) |
| Counts | 30 | 0.3 | 2.48% | 94% | 0.44% | 62% | 0.22 (0.17–0.27) |
| Counts | 150 | 0.3 | 3.04% | 93% | 0.72% | 75% | 0.20 (0.17–0.22) |
| Proportions | 30 | 0.3 | 1.89% | 96% | 0.38% | 74% | 0.026 (0.019–0.032) |
| Proportions | 150 | 0.3 | 2.65% | 99% | 0.69% | 88% | 0.023 (0.020–0.026) |

- **τ̂ = 0 is common at physician scale.** That happened in 86% of K = 30 replicates at
  τ = 0. In every one of those, the adjusted limits were identical to the unadjusted
  limits.
- **Adjusted flag rates sit above the nominal 0.1%.** When τ is real the adjustment cuts
  in-distribution flags four- to fivefold. They stay above nominal because the published
  estimator runs low (§4.3). Under the 0.4 multiplicative `oep`, measured the same way
  before this change, they were 1.06% (K = 30) and 1.34% (K = 150).
- **The cost is detection of a genuine outlier.** It falls as the spread it is judged
  against widens. That trade is inherent to asking "unusual among peers?" rather than
  "different from target?" (§2).

## 6. Known limitations and planned work

- **Small cohorts.** τ̂ is imprecise below about 30 providers (IQR 0.17–0.27 when
  τ = 0.3, K = 30), and the pooled center line can be pulled by one extreme provider
  (§4.2).
- **Downward bias.** The published φ̂ is biased low, so the method under-adjusts (§4.3).
- **X-axis.** Providers are plotted in volume-rank order with limits per point, not
  against a continuous precision axis with smooth contours [1, §2].
- **No outcome–volume test yet** [1, §4; 8, step 5]. A funnel assumes outcome does not
  depend on volume.
- **Binary outcomes on an O/E chart.** Observed counts that are sums of yes/no outcomes
  have variance Σp(1 − p) < Σp = E. Poisson limits are therefore slightly too wide for
  common outcomes: about 8% at a 15% event rate, negligible for mortality.
- **Planned:** a pre-specified τ [9], the volume test,
  binomial variance for binary-outcome O/E when case counts are known, and FDR [12].

## References

1. Spiegelhalter DJ. Funnel plots for comparing institutional performance. *Statistics
   in Medicine* 2005;24(8):1185–1202.
2. Spiegelhalter DJ. Handling over-dispersion of performance indicators. *Quality &
   Safety in Health Care* 2005;14:347–351.
3. DerSimonian R, Laird N. Meta-analysis in clinical trials. *Controlled Clinical Trials*
   1986;7:177–188.
4. Breslow NE, Day NE. *Statistical Methods in Cancer Research, Volume II: The Design and
   Analysis of Cohort Studies*. IARC, 1987. (Byar's approximation.)
5. Garwood F. Fiducial limits for the Poisson distribution. *Biometrika*
   1936;28:437–442.
6. Laney DB. Improved control charts for attributes. *Quality Engineering*
   2002;14(4).
7. Clayton D, Kaldor J. Empirical Bayes estimates of age-standardized relative risks for
   use in disease mapping. *Biometrics* 1987;43:671–681.
8. Verburg IWM, Holman R, Peek N, Abu-Hanna A, de Keizer NF. Guidelines on constructing
   funnel plots for quality indicators: a case study on mortality in intensive care unit
   patients. *Statistical Methods in Medical Research* 2018;27(11):3350–3366.
9. Pavlou M, Ambler G, Omar RZ, et al. Outlier identification and monitoring of
   institutional or clinician performance: an overview of statistical methods and
   application to national audit data. *BMC Health Services Research* 2023;23:23.
10. Walker K, Neuburger J, Groene O, Cromwell DA, van der Meulen J. Public reporting of
    surgeon outcomes: low numbers of procedures lead to false complacency. *Lancet*
    2013;382(9905):1674–1677.
11. Mohammed MA, Panesar JS, Laney DB, Wilson R. Statistical process control charts for
    attribute data involving very large sample sizes: a review of problems and
    solutions. *BMJ Quality & Safety* 2013;22:362–368.
12. Jones HE, Ohlssen DI, Spiegelhalter DJ. Use of the false discovery rate when
    comparing multiple health care providers. *Journal of Clinical Epidemiology*
    2008;61(3):232–240.
13. Mainey C. FunnelPlotR: funnel plots for comparing institutional performance (R
    package). https://github.com/chrismainey/FunnelPlotR
14. Clopper CJ, Pearson ES. The use of confidence or fiducial limits illustrated in the
    case of the binomial. *Biometrika* 1934;26(4):404–413.
