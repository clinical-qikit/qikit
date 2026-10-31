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

Funnels are drawn by `funnel()`. Its `measure=` and `overdispersion=` pick one of six
engine charts, whose codes the engine's docstrings and the shared fixtures use:

| `funnel(...)` | Engine chart | Count model | Limits | Over-dispersion |
|---|---|---|---|---|
| `measure="proportion", overdispersion=False` | `p` | Binomial | Exact binomial [1, A.1.1] | Estimated and reported, not applied |
| `measure="rate", overdispersion=False` | `u` | Poisson | Exact Poisson, exposure as denominator [1, A.2.1, A.2.3] | Estimated and reported, not applied |
| `measure="oe", overdispersion=False` | `oe` | Poisson | Exact Poisson on expected events [1, A.2.1] | Estimated and reported, not applied |
| `measure="proportion"` (default `overdispersion=True`) | `pp` | Beta-binomial | Exact quantiles of the additive model [1, eq. 11] | Additive τ² [1, §5], applied |
| `measure="rate"` | `up` | Poisson–gamma | Exact quantiles of the additive model [1, eq. 11; 7] | Additive τ² [1, §5], applied |
| `measure="oe"` | `oep` | Poisson–gamma | Exact quantiles of the additive model [1, eq. 11; 7] | Additive τ² [1, §5], applied |

The contours are 99.8% and 95% by default (`limits=`). `within_dispersion=` scales any
count model for counts that clump within cases (§4.12), and the binomial for the items
of one survey (§4.13). `qic()` keeps p/u with 3σ
Shewhart limits and pp/up with Laney's σ_z [6] for time order; it no longer draws
funnels.

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
| Unadjusted limits | Exact binomial (A.1.1) and Poisson (A.2.1), interpolated as (r_p − α) | **Differs above the line**: lower contour (r_p − α) as published; upper contour (r_p − α + 1), the exact test's boundary (§4.1). u follows A.2.3 (N in place of E) |
| Target θ₀ | External, or pooled from the data and treated as known | Same: `cl=`, or pooled Σy/Σn (Σ O / Σ E) |
| Residuals for over-dispersion | Pearson z on the natural scale (eq. 4) | Same |
| Robustness | 10% winsorized φ̂ (eqs. 6, 8) | Same |
| Winsorizing debiasing factor w(q) | Derived (eq. 9), not adopted in his example | **Differs**: applied by default in both engines (`tau_method="winsorized"`); `tau_method="spiegelhalter"` reproduces the example, and the published-value fixtures pin it (§4.3) |
| Between-provider variance τ² | Method of moments on winsorized residuals (eq. 10) | Same by default; also maximum likelihood (`tau_method="ml"`) or a τ fixed in advance (`tau=`) (§4.16) |
| Multiplicative model | φ̂, applied if φ̂ > 1 + 2√(2/I) | Not used (§4.4) |
| Additive model | τ̂² by method of moments (eq. 10), 0 if φ̂ < (I−1)/I | Same |
| Adjusted limits | θ₀ ± z√(V + τ²), normal (eq. 11) | **Differs**: same variance, exact mixture quantiles (§4.5) |
| Under-dispersion | Never narrow the limits | Same |
| X-axis | Indicator against precision ρ, smooth pre-drawn limits (§2) | Same in effect: against volume (n, or E), which is proportional to ρ, with smooth contours (§4.9) |
| Outcome–volume association | Formal regression test (§4) | **Not yet** (§6) |
| Multiple comparisons | Small P values; FDR "best carried out separately" (§6) | Exact p-values and Benjamini–Hochberg q-values on every funnel; `signal="fdr"` tiers on q instead of the contours, at `fdr_levels` (§4.11). `expected_false_flags` reports chance flags per tier |
| Counts that clump within cases (days per stay) | Not covered | Extension: `within_dispersion=φ`, effective counts O/φ against E/φ, with a diagnostic that warns when it is missing (§4.12) |
| Items clustered in cases (questions of one survey) | Not covered | Extension: the same `within_dispersion=φ` on a proportion, Rao–Scott effective counts y/φ out of n/φ [17], interpolated in n/φ between whole denominators (§4.13) |
| Change data, continuous outcomes | A.1.2, A.2.2, A.3 | Not offered |
| Per-point power and intervals | Not part of the method | Extension on every funnel (§4.8) |
| Shrunk estimates and reliability | Not part of the method | Extension: `reliability`, `eb_rate`, `eb_excess`, the exact posterior mean of the chart's own mixture model (§4.14) |
| Single-case robustness | Not part of the method | Extension: `p_value_drop1`, `flag_survives_drop1`, `fragility` (§4.15) |
| Volume floor for the FDR step | Not covered | Extension: `test_min_expected=`, independent filtering (§4.11) |

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

**The upper contour sits at the exact test's boundary.** For an integer count O the
interpolated quantile q = r_p − α decides the two sides differently:

- the point is below the lower contour exactly when P(X ≤ O) < α, which is the exact test;
- the point is above the upper contour q exactly when P(X > O) < α, which leaves out the
  probability of the observed count itself.

So qikit draws the upper contour at q + 1 on the count scale (capped at n for a
proportion). With that, a point is beyond either contour exactly when its conventional
exact p-value, P(X ≥ O) above or P(X ≤ O) below (§4.11), is below the contour's tail
probability. The drawn line, `p_value`, the point's colour and, on the unadjusted
O/E chart, "the point's Garwood 95% interval excludes the center line" are then one
statement. The test suite checks all three on random funnels of every chart.

The model, center line, τ² and levels are Spiegelhalter's; only the drawn upper
boundary moves, by at most one count. At 5 expected events and θ₀ = 1 the 99.8% upper
limit is 13.77 events (O/E 2.75) rather than the published 12.77 (2.55). Compared with
other funnel software that draws the published contour, qikit is up to one count more
conservative above the line at small volumes. This is a qikit derivation. As far as we
know it is not a published contour, though the test it draws is the standard exact
test, and also the comparison of a provider's exact interval with the benchmark.

**Shape at small counts.** Spiegelhalter's upper contour wiggles at small denominators:
on the ratio scale it climbs briefly within every integer step before falling again.
Within a step α runs from 1 to 0 as λ = θ₀n grows, and q = r_p − α has slope
q′(λ) = 1 + α(r_p/λ − 1), so q/λ has slope proportional to q′λ − q, which is 1 at the
start of every step. The contour qikit draws, (q + 1)/λ, has slope proportional to

  q′λ − (q + 1) = (1 − α)(λ − r_p − 1),

which is never positive, since an upper quantile r_p is at least λ. So it is monotone by
construction, in all four families. On dense grids the published contour climbs back
thousands of times (largest climb 0.067 on O/E for E between 0.3 and 2, 0.021 on a
proportion at θ₀ = 0.1); the drawn contour never does, and no display smoothing is
needed. The lower contours were already monotone.

To start the axis where volumes become informative, use `x_range=(2, None)` on an O/E
funnel or about n = 20 on a proportion, or spread the axis with `x_log=True`.

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

### 4.3 The over-dispersion estimator, debiased

`funnel_dispersion()` implements [1, §5], with one change of default:

1. Pearson residuals zᵢ = (yᵢ − θ₀)/√V₀ᵢ, with V₀ᵢ = θ₀/nᵢ for counts and θ₀(1 − θ₀)/nᵢ
   for proportions (eq. 4).
2. Winsorize at the 10th and 90th percentiles; φ̂ = c(0.10)·mean(z_W²) (eqs. 6, 8, 9).
3. τ̂² = (Kφ̂ − (K − 1)) / (Σwᵢ − Σwᵢ²/Σwᵢ), wᵢ = 1/V₀ᵢ (eq. 10, the DerSimonian–Laird
   form [3]), and τ̂² = 0 when φ̂ < (K − 1)/K.

**The consistency factor.** Winsorizing a standard normal at its p and 1 − p quantiles
z = Φ⁻¹(1 − p) leaves E[Z_W²] = (1 − 2p) − 2z·φ(z) + 2p·z², which is 0.6787 at p = 0.10.
Spiegelhalter derives the correction c(p) = 1/E[Z_W²] = 1.4735 (eq. 9), but reports that
it gave "somewhat wide limits" and does not adopt it in his example. FunnelPlotR [13] and
the CQC/SHMI implementations follow the example. qikit did too through 0.9. From 0.10,
both engines apply it by default (`tau_method="winsorized"`), because the omission costs
most exactly where qikit is used: hundreds or thousands of physicians at low volume.
No published healthcare application or evaluation of the factor was found (§4.16), so
this default rests on eq. 9 itself and on the simulations below and in §5.

**Why the default changed.** Without c, φ̂ averages 0.68 under pure chance. The τ² = 0
gate then needs a true over-dispersion of about 1.47 before it moves at all, and every
spread below that is ignored. At physician scale that is most real spread. 200 replicates
of K = 1,000 providers, E ~ U(2, 60), Poisson counts with true relative spread τ:

| true τ | φ̂ published | τ̂ published | τ̂ debiased | τ̂ plain DL (no winsorizing) |
|---|---|---|---|---|
| 0 | 0.678 | 0 | 0.017 | 0.016 |
| 0.10 | 0.881 | **0 in every replicate** | 0.098 | 0.100 |
| 0.20 | 1.452 | 0.120 | 0.192 | 0.200 |
| 0.30 | 2.387 | 0.212 | 0.285 | 0.300 |
| 0.10, plus 2% gross outliers (O/E 2.5) | 0.942 | 0.004 | **0.113** | 0.230 |

- **The published estimator under-adjusts.** With every provider differing only by a
  true τ = 0.2, 4.5% of average providers have a one-sided p below 0.025 (nominal 2.5%):
  about twice the chance flags the chart reports. Under `signal="fdr"` an understated τ
  makes every p-value too small, which inflates false discoveries in the same way. For
  physician profiling a false flag has a real cost, and the profiling literature counts
  misclassification as a primary harm [24, 25].
- **Debiasing keeps the robustness.** Plain DerSimonian–Laird recovers τ without outliers
  but doubles it when 2% of providers are gross outliers, so the providers being screened
  for widen their own limits. The debiased winsorized estimator stays within 0.02 of the
  truth in both cases. Among the alternatives (Paule–Mandel, REML [34]), none is robust
  to outliers in this way without winsorizing, so qikit keeps Spiegelhalter's estimator
  and fixes its bias.
- **Spiegelhalter's caution came from a small example.** With a dozen providers φ̂ is
  imprecise, and an upward error in τ̂ widens every limit. At K in the hundreds φ̂ is
  precise and the bias dominates the error.

**Reproducing published funnels.** `tau_method="spiegelhalter"` gives the published
estimator bit for bit; the shared Python/TypeScript fixtures that check Spiegelhalter's
numbers pin it, and `funnel_oep_winsorized`, `funnel_pp_winsorized` and
`funnel_up_winsorized` check the default in both engines. `summary["phi_raw"]` is
mean(z_W²) and `summary["phi_debiased"]` is c·mean(z_W²) (NaN under
`tau_method="spiegelhalter"`). On the bundled example (`data/examples/physician_mortality_oe.csv`,
three years pooled) τ̂ moves from 0 to 0.113, and the same three physicians are
outliers.

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
- **Fallbacks.** A spread no beta distribution can have (τ² ≥ θ₀(1 − θ₀)), or a
  distribution too wide to walk (only absurd τ), falls back to eq. 11 as published.
  `summary["limit_method"]` then says `"normal"` instead of `"exact"`. A non-integer
  denominator is interpolated between its whole neighbours (§4.13), and
  `limit_method` says `"interpolated"`.
- **Computation.** From 0.10 the walk is vectorised in blocks after its first 64 terms,
  with the upward and downward running products done by `np.multiply.accumulate` and
  `np.divide.accumulate` and every sum by `np.cumsum`. All three are strictly sequential,
  so every term, the point where the walk stops, every tail sum, and therefore every
  limit and p-value are bit-identical to the scalar loop the TypeScript twin keeps
  (checked on 36,000 random calls across all four families). A walk, and each Poisson
  mean inversion, is cached per distribution, because a point's two contours and its
  p-value walk the same pmf. A 1,000-provider `oep` funnel at hospital volumes
  (E from 30 to 2,000) takes about 0.3 s cold, down from 1.3 s, and 0.06 s when the same
  distributions recur. scipy is not used. It is not a dependency, its incomplete-gamma
  and beta routines differ from this walk in the last ulps across platforms, and its
  beta-binomial loses about 1e-5 to the cancellation described above. The cold time is
  dominated by the lgamma-based Poisson mean inversion behind intervals and detectability.
  Solving all providers' inversions at once would make it faster, but it moves the last
  quantized digit of some results at counts in the thousands, so it has not been done.

### 4.6 Laney's p′/u′ stay for time order

Laney's σ_z is the mean moving range of consecutive standardized residuals [6]. That
statistic depends on order and is defined for time series [11]. In a funnel the order is
the sort by volume. On the bundled 3-year surgeon data, the published test finds no
over-dispersion, yet the 0.4 `up` funnel widened its limits 1.87× and hid all three real
signals. In 0.5, `pp`/`up` use the additive method inside a funnel and Laney outside one.
`summary["dispersion_method"]` says which.

### 4.7 Warn tier and multiplicity

The 99.8% contour marks outliers and the 95% contour alerts (`signal`; the engine's
`sigma_signal` and `warn_signal`). The tiers never overlap, and alerts stay out of the
engine's `signals` flag, because at one chance alert in forty per side a large funnel
would always report one. About 0.1% of average providers land beyond each 99.8% line,
roughly one in a 1,000-provider one-sided funnel, and 2.5% beyond each 95% line, about
24 there. `summary["expected_false_flags"]` reports those numbers for the chart, so an
alert count is read against them. [1, §6] recommends formal FDR control [12] carried out
separately from the plot. Every funnel reports Benjamini–Hochberg q-values, and
`signal="fdr"` flags by them (§4.11).

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
F(⌊ucl·n⌋) = 0.2. With the upper contour at the exact test's boundary (§4.1) that event
is exactly "p < 0.001". The equation is solved exactly in the CDF's own parameter, never
by scanning over ratios. `funnel()` reports the result as `min_detectable` and the
interval as `ci_lower`/`ci_upper` on every measure:

| Engine chart | Count model | Solved for | Engine column (y scale) | Per-point 95% CI |
|---|---|---|---|---|
| `oe`, `oep` | Poisson(ρE) | mean, then ρ = μ/E | `min_detectable_oe` | Garwood [5] |
| `u`, `up` funnel | Poisson(θn) | mean, then θ = μ/n | `min_detectable` | Garwood [5] |
| `p`, `pp` funnel | Binomial(n, θ) | θ directly | `min_detectable` | Clopper–Pearson [14] |

A u funnel's algebra is the O/E chart's with exposure in place of expected events, so it
reuses the same functions. A Clopper–Pearson interval inverts the exact binomial test the
same way Garwood inverts the Poisson one: the lower bound is the θ at which x or more
events has probability 0.025, and the upper bound is the θ at which x or fewer does.

**The Poisson solve** takes safeguarded Newton steps on log F, where
F = f·S, S is a running sum of products of j/μ, and d log F/dμ = −1/S. Six to ten
steps replace fifty full CDF sweeps. A thousand-provider funnel with counts in the
thousands (length of stay in days) took about 17 s by bisection and now takes well
under 1 s. The TypeScript engine still bisects; the two agree far inside the
quantization below.

**Cross-platform reproducibility.** The Poisson solve uses one lgamma, whose last ulp
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
A non-integer denominator (n/φ under `within_dispersion`, or an averaged n) has no
binomial description. Its detectability and interval are interpolated between the
whole neighbours, as its limits are (§4.13).

### 4.9 The volume axis

[1, §2] plots each indicator against its precision ρ = 1/s², with the limits drawn as
smooth contours. qikit plots against the denominator instead: sample size on p/pp,
exposure on u/up, and expected events on oe/oep. That is the same axis up to a
constant. For a proportion s² = θ₀(1 − θ₀)/n, so ρ ∝ n. For a rate or an O/E ratio
s² = θ₀/n (or θ₀/E), so ρ ∝ n (or E). The difference is that volume is a unit a reader
already understands. The adjusted funnels use the same axis, which is where the
levelling-off of §4.4 shows.

This is the axis `funnel()` draws. A funnel whose denominators are all equal falls back
to plotting by unit, because a volume axis would stack every point on one line. The y
axis is fitted to the providers, the center line and each contour's value nearest the
center line, so the low-volume flare does not set the scale.

**The contours.** `FunnelResult.limits()` evaluates the limits on about 200
geometric steps between the smallest and largest denominator, merged with every point's
own n. It calls the same limit functions on the same path as the per-point limits
(`compute.funnel_limits`), with the unrounded τ², so each curve passes exactly through
the limit that decided that point's `signal`. A drawn point can
therefore never sit inside the curve while being flagged, or outside it while not
being flagged. A test pins this bit-for-bit on every funnel fixture. Between grid
steps the plot interpolates linearly.

**Binomial charts step in whole numbers.** On p/pp the grid is rounded to integers,
where the limits are exact. A non-integer n is interpolated between its whole
neighbours (§4.13), so the contours stay continuous through every step, including
under `within_dispersion`, where the model sees n/φ. The Poisson and Poisson–gamma
charts take any positive n.

**Log scale.** `x_log=True` log-scales the axis, which spreads out a funnel whose
providers span orders of magnitude. Plotly takes an annotation's position on a log axis
as log10 of the value, so the center-line and limit labels and the signal labels are
placed on that scale.

### 4.10 One-sided signalling

Many indicators matter in one direction only; excess mortality is the usual example.
`funnel(worse="higher")` flags only points beyond the upper contours, and
`worse="lower"` only those beyond the lower ones (the engine's `signal_side="above"` and
`"below"`). `worse=None`, the default, is the two-sided chart of [1]. The filter applies
to both tiers, and through them to the point colours, the legend ("Worse than
expected: …"), the counts and `label_signals=`. `summary["worse"]` records it.

- **Each side keeps its own tail probability.** A one-sided chart flags at 0.1% and 2.5%
  per provider by chance, half the two-sided chart's 0.2% and 5%.
- **The other side's limits are still drawn,** because they are still where the null
  model puts them. Hide them with
  `styles={"lcl": {"visible": False}, "lcl_95": {"visible": False}}`.
- **Only on funnels.** Runs rules describe patterns, not points beyond a line, and are
  never side-filtered, so `qic()` has no side argument.
- **Detectability is still about the upper limit.** `min_detectable` describes the
  upper limit whatever the side. Under `worse="lower"` it says what an above-centre
  provider would have needed, which the chart no longer flags.

### 4.11 P-values, the false discovery rate, and what decides a flag

Every funnel reports two values per point:

- **`p_value`:** an exact p-value against the null model its limits are drawn from;
- **`q_value`:** its Benjamini–Hochberg adjustment [15], the procedure [12] applies to
  provider comparisons.

**The null model.** It uses the same distribution, center line and τ² as the limits.
`summary["count_model"]` names it:

| Engine chart | `count_model` | Count X |
|---|---|---|
| `oe`, `u` | `poisson` | Poisson(θ₀n) |
| `oep`, `up` | `poisson_gamma` (`poisson` when τ̂ = 0) | Poisson–gamma, mean θ₀n, size θ₀²/τ² [7] |
| `p` | `binomial` | Binomial(n, θ₀) |
| `pp` | `beta_binomial` (`binomial` when τ̂ = 0) | Binomial(n, θ), θ ~ Beta(θ₀s, (1 − θ₀)s), s = θ₀(1 − θ₀)/τ² − 1 |

A few rules follow from using the limits' own model:

- The unadjusted charts ignore their diagnostic τ̂, as their limits do.
- θ₀ is treated as known, as in [1].
- Under `within_dispersion=φ` the model sees O/φ events against E/φ (§4.12).

**The p-value.** These are conventional exact tail probabilities of the observed count
O = y·n:

| `worse` | p-value |
|---|---|
| `"higher"` | P(X ≥ O) |
| `"lower"` | P(X ≤ O) |
| `None` | min(1, 2·min of the two) |

They are valid p-values (uniform or conservative under the null), which the
Benjamini–Hochberg step needs.

- **Computation.** Each tail is summed directly from its own terms, never as one minus
  the other, on the lgamma-free walk the mixture quantiles use (§4.5). A small p-value
  therefore keeps its digits, and the result is identical across platforms. Terms the
  walk drops sit below 1e-16 of the mass, so p-values smaller than that read 0.
- **A count between whole numbers.** This is an averaged aggregate, or an effective
  count O/φ. Each tail is interpolated linearly between its two integer neighbours. That
  is exactly the inverse of the interpolated quantile, so the line-equals-test property
  below holds for these counts too. `summary["p_value_method"]` is then
  `"interpolated"`.
- **A denominator between whole numbers** (binomial only: n/φ under
  `within_dispersion`). Each tail is interpolated in n as well, by the function the
  contours are solved from (§4.13). `p_value_method` is `"interpolated"`.
- **Normal fallback.** Where the limits fall back to the normal approximation, the
  p-values do too, with the same mean and variance and no continuity correction:
  - a `pp` spread no beta distribution can have;
  - a walk past its term limit.

  `p_value_method` is `"normal"` if any point fell back.

**The line is the test.** With the upper contour drawn at the exact test's boundary
(§4.1), a point is beyond a contour exactly when its p-value is below that contour's
tail probability. The tail probability is 0.001 and 0.025 one-sided at the default 99.8%
and 95%, doubled when two-sided. The test suite checks this on random funnels of all six
charts, for whole and fractional counts, at both levels and on both sides. With 13
deaths against 5 expected, for example, P(X ≥ 13) = 0.20%: the point is an alert,
between the 95% and 99.8% lines. Under the published contour it sat beyond the 99.8%
line.

**`signal`** picks one test for both tiers:

| `signal` | outlier | alert |
|---|---|---|
| `"limits"` (default) | beyond the outer contour, i.e. p < its tail probability | beyond the inner contour, not an outlier |
| `"fdr"` | `q_value` < `fdr_levels[0]` (0.05) | `q_value` < `fdr_levels[1]` (0.10), not an outlier |

`summary["expected_false_flags"]` gives each tier's chance count. Under `"limits"` it is
K·α: the providers a chart of K average providers would put in the tier. Under `"fdr"`
it is the Benjamini–Hochberg bound, at most Q times the number flagged.

**Why there is no union of the two.** A downstream request asked for "beyond the limit
OR q below its level", either test being enough, as the default. The q-value at rank i
is below Q exactly when p ≤ Q·R/K, where R is the number of Benjamini–Hochberg
discoveries. So the union is the same as p < max(α, Q·R/K):

- **At the alert tier** (α = 0.025, Q = 0.10), q adds a flag only when more than a
  quarter of providers are flagged, which is essentially never. The ~25 chance alerts
  in 1,000 that motivate FDR all stay.
- **At the outlier tier** (α = 0.001, Q = 0.05), q adds flags only when more than 2% of
  providers are discoveries. That is, it adds power where signals are already plentiful,
  which is the opposite of the stated aim.

The union's tier also carries neither guarantee: it is not "about α of average
providers", nor "at most Q of these are false". Each pure mode gives a clinical reader
one sentence. A "flagged on at least two measures" ranking rule is itself a strong
multiplicity guard: with four measures and independent chance alerts, about
6 × 0.025² ≈ 0.4% of average providers qualify.

**The q-value.** Take the K points that have a p-value (`summary["n_tested"]`;
excluded points have none) and sort them by p-value, ascending. The q-value at rank i is
the minimum over ranks j ≥ i of p₍ⱼ₎·K/j, capped at 1. A point is significant at false
discovery rate Q exactly when q < Q. Each chart, and each facet, is adjusted on its own.
`x_range=` only trims the view and never changes K.

**On the figure.**

- **Caption.** A figure without a caption of its own states the rule that coloured its
  points: the exact test and its levels, or the FDR levels and that the curves are then
  for reference only.
- **Hover.** It shows each point's p and q.
- **Detectability.** `min_detectable` describes the drawn outer contour, which under
  `"limits"` is the test itself. Under `"fdr"` what a point needs depends on every other
  point.

**Filtering before the FDR step.** `test_min_expected=t` leaves out of the
Benjamini–Hochberg step every provider whose denominator, as the model sees it (n/φ
under `within_dispersion`), is below t. Those providers keep their `p_value` but get no
`q_value`, so they cannot flag under `signal="fdr"`, and they do not count in its K.
Nothing else moves: they still count toward θ₀ and τ², are still drawn, and still flag
under `signal="limits"`. `summary["n_filtered"]` counts them.

- **Why this is valid.** A filter that depends only on each test's design (its
  denominator) and not on its outcome is *independent filtering* [29]. Under the null
  the kept p-values are still uniform or conservative, so Benjamini–Hochberg on the kept
  set still controls the false discovery rate, now over fewer tests.
- **Underpowered is not untestable.** For `worse="higher"` on counts the upper tail is
  unbounded. A physician with E = 1.5 and 8 readmissions has a tiny p-value, so low
  volume never makes a provider *unable* to flag, only unlikely to. A floor on volume is
  therefore a policy choice to give up those rare gross low-volume outliers in exchange
  for power among the rest. That is why it is opt-in and named for what it does. A truly
  untestable provider, whose smallest attainable p-value is above the threshold, exists
  only on a bounded tail: `worse="lower"` on counts (p ≥ e^(−θ₀E) at zero events), and
  proportions at very small n. That is Tarone's criterion [30], and the discrete FDR
  procedures built on it [31, 32] are the principled way to gain power there (planned,
  §6).
- **Declined: Storey's q-value [33] and a power-screened BH.** Storey's estimate of the
  null share π₀ gains power only when many providers are truly non-null. With τ² in the
  null model, most providers *are* null by construction, so π̂₀ ≈ 1 and the gain is small.
  Discrete, conservative p-values pile up near 1 and push π̂₀ toward 1 further. A
  screen on `min_detectable` that sets `q_value` to NaN would remove the gross
  low-volume outliers above, so it was declined as a default and replaced by this
  explicit floor.

### 4.12 Counts that clump within cases

Spiegelhalter's count models assume each counted unit is an independent event. Length
of stay as observed/expected **days** breaks that: one stay adds many days at once, so a
provider's day total has variance about φ times its mean, where φ is the
variance-to-mean ratio of days per stay. φ is typically 5–10 for inpatient stays. The
additive τ² cannot absorb this. It adds a constant to the variance of the ratio, while
the missing variance, φθ₀/E, shrinks with volume, so the smallest providers' limits stay
far too narrow and every p- and q-value is too small (§5).

**The fix.** `within_dispersion=φ` treats the count as a Poisson count of O/φ events
against E/φ expected: the quasi-Poisson model, in which variance is φ times the mean.
The ratio is unchanged, so only the denominator the model sees moves. The limits, τ²
(Pearson z with variance θ₀φ/E), p-values (interpolated for the non-integer effective
counts, §4.11), detectability and intervals all follow from it. The echoed numerator and
denominator stay in the caller's units. Effective counts are large at length-of-stay
volumes. For φ < 1 (a binary-outcome O/E, where Σp(1 − p) < E) they would be small and
fractional, so qikit does not recommend it there.

**Estimating φ.** `within_dispersion="estimate"` takes stay-level rows (several per
unit) and computes

  φ̂ = Σⱼ Σᵢ (yᵢⱼ − θ̂ⱼnᵢⱼ)² / (θ̂ⱼnᵢⱼ) / (N − K),  θ̂ⱼ = Σᵢyᵢⱼ / Σᵢnᵢⱼ,

the Pearson dispersion of each stay around its own provider's rate. Using each
provider's own rate keeps real differences between providers out of φ̂, leaving them to
τ²; the test suite checks that a planted provider effect leaves φ̂ unchanged. A faceted
call estimates φ per facet. Long stays dominate φ̂, so cap them at a stated percentile
before aggregating, as length-of-stay benchmarks usually do.

**The diagnostic.** An agent or analyst who passes aggregated days without φ should not
get a silently wrong chart. The Pearson residuals of any funnel have variance
a + b·nᵢ/n̄, in two separable parts:

- clumping within cases inflates every provider's variance by the same factor, whatever
  its volume, so a = φ;
- real differences between providers add τ², which grows with volume on the z scale,
  so b > 0.

qikit fits both by maximum likelihood, by iteratively reweighted least squares on z²
with each residual capped at three of its own SDs. It calls the shape "within" when an
intercept above 1 is significant (likelihood ratio > χ²₁ 0.999) and estimates φ ≥ 2,
and "between" when a slope above 0 is significant at the same level. The result is
`summary["dispersion_shape"]` (`none` / `between` / `within` / `both`, or `unknown` when
the largest volume is under 1.5 times the smallest). It needs at least 30 providers, the
smallest K the thresholds were calibrated at. When the shape is "within" or "both" and
`within_dispersion` was left at 1, qikit:

- raises a `UserWarning` naming the fix;
- adds the same sentence to `summary["notes"]`;
- adds a warning line to the figure's caption.

The intercept is reported as `within_dispersion_hint`, an estimate of φ from aggregated
data alone. Because the fix is a model choice, the diagnostic never applies it.

**Estimating φ from SQL totals.** Stay-level rows need not leave the database. With
θ̂ⱼ = Yⱼ/Nⱼ, each provider's Pearson sum expands to sufficient statistics:

- counts: Σᵢ (yᵢⱼ − θ̂ⱼnᵢⱼ)²/(θ̂ⱼnᵢⱼ) = Σᵢ yᵢⱼ²/nᵢⱼ / θ̂ⱼ − Yⱼ;
- proportions: Σᵢ (yᵢⱼ − θ̂ⱼnᵢⱼ)²/nᵢⱼ = Σᵢ yᵢⱼ²/nᵢⱼ − θ̂ⱼYⱼ.

So one row per provider of (Y, N, k = cases, Σy²/n), passed as `cases=` and `sum_sq=`,
gives φ̂, the clustering check, and every downstream number equal to the case-row path to
rounding (the test suite checks both families). `sum_sq` is a raw sum, not a residual,
so SQL cannot compute it around the wrong center.

**One φ per provider: case mix.** A single φ assumes every provider's stays are equally
variable. When variability depends on what is treated (DRG, service line), a provider
with complex patients has a larger true φ. `within_dispersion="<column>"` takes one φᵢ
per provider. The natural construction is case-mix weighting: φ_g per DRG from SQL, then
φᵢ = Σⱼ φ_g(j)·eⱼ / Σⱼ eⱼ over the provider's stays. Each provider is judged on Yᵢ/φᵢ out
of Nᵢ/φᵢ, the same quasi-Poisson effective counts as above. Because no single φ maps
caller units to the model, the x axis (and `limits()`) is the effective denominator
(`effective_denominator`), so each point still sits against its own exact test.
`numerator` and `denominator` stay in the caller's units, and `summary["within_dispersion"]`
is the volume-weighted mean Σn/Σ(n/φᵢ). A φ_g estimated from few stays is noisy. Shrinking
it toward the pooled φ with the moderated-variance step of Smyth [19] (prior degrees of
freedom estimated, not fixed) is the right use of that idea; a built-in `strata=` that
does this is planned (§6).

**Declined: each provider's own variance.** A request asked for an O/E chart on which
each provider's null variance comes from its *own* stays, s²ᵢ shrunk toward the pool
(limma's moderated t [19]), tested on t with ν₀ + k − 1 degrees of freedom. That
transposes a genomics method to a setting where it fails:

- **Self-masking.** Length of stay is right-skewed, and its variance rises with its
  mean, so a provider with long stays also has a large s²ᵢ. Their own z shrinks, and the
  providers the funnel exists to find hide behind their own variability. Meta-analysis
  has the same problem. Standard methods treat estimated within-study variances as known
  and ignore their correlation with the effect estimates, which Jackson and White call
  potentially serious in small studies [20, §3.2].
- **The center leaks into the variance.** Residuals taken around θ₀ rather than the
  provider's own rate give E[s²ᵢ] = Var + (θᵢ − θ₀)²·(spread of e), so the deviation
  being tested also inflates its own variance.
- **The line stops being the test.** A funnel's null variance must describe an average
  provider treating this provider's patients [1, 21]: a function of the patients, not of
  this provider's outcomes. Contours drawn from a pooled s₀² while each point is tested
  against its own s²ᵢ break the invariant that a point beyond a line is flagged (§4.11).
- **An arbitrary prior.** ν₀ = 20 fixed, where Smyth estimates it, on top of a second
  normal approximation.

The two needs behind the request, variability that differs by case mix and no
200,000-row transfer, are met by the column and the sufficient statistics above, without
these failures.

### 4.13 Multi-item instruments: items clustered in surveys

A survey composite scored per item, such as HCAHPS "Communication with Doctors"
("Always" answers / items answered over explains, listens and respects), is a
proportion of items. The items on one survey come from one patient and mostly agree. A
binomial treats them as independent. If the m items of a survey have intraclass
correlation ρ, a provider's item count has variance

  n θ(1 − θ) · [1 + (m − 1)ρ] = n θ(1 − θ) · φ,

where φ is Kish's design effect [18]. With three items and ρ = 0.7, φ ≈ 2.4. Twelve items
from four surveys then carry about as much information as five independent ones.

**Why item counts over-flag, and why the flags move.** Left at φ = 1, the funnel makes
two errors:

- **Small providers are over-flagged.** Every provider's binomial limits are √φ too
  narrow. The additive τ² cannot correct this, because the missing variance shrinks with
  volume (§4.12). Every p-value and q-value is too small as well.
- **τ̂ is inflated.** τ̂ absorbs part of the clustering variance as if providers really
  differed, which widens the limits of high-volume providers.

Correcting φ therefore does more than remove flags. τ̂ falls, small providers drop out,
and some large providers become more clearly unusual.

**Which unit to pass.** Pass one row per survey: y = items meeting the measure, n = items
answered. Use `measure="proportion"` and `within_dispersion="estimate"`. Two other inputs
fail:

- **One row per item.** This hides the problem. A row holding a single yes/no has
  variance fixed by its mean, so it cannot show clustering, and `"estimate"` refuses
  rows whose n are all 1.
- **One row per provider.** This leaves only the provider-level shape test (§4.12), which
  a real between-provider spread can mask. In a downstream example with φ = 2.4 on both
  top-box and bottom-box, the totals read "within" on top-box but "between" on
  bottom-box.

Recoding the measure as "all items Always", one binary per survey, would be an exact
binomial. It is a different measure, though, not the published HCAHPS definition.

**The fix.** `within_dispersion=φ` gives the model y/φ events out of n/φ cases, the
Rao–Scott effective sample size for clustered binary data [17]. It is the binomial
analogue of the quasi-Poisson correction in §4.12. The proportion is unchanged.

**Estimating φ.** From survey-level rows:

  φ̂ = Σⱼ Σᵢ (yᵢⱼ − θ̂ⱼnᵢⱼ)² / nᵢⱼ / [θ̄(1 − θ̄)(N − K)],

- Residuals are taken around each provider's own θ̂ⱼ, so differences between providers
  stay out of φ̂ (§4.12).
- The variance uses the pooled θ̄, not each provider's θ̂ⱼ(1 − θ̂ⱼ). At a few surveys per
  provider many have θ̂ⱼ of 0 or 1. On a simulated bottom-box at 10% (§5), nearly one
  physician in five had no bottom-box answer at all. Their own rate would drop them,
  biasing φ̂.
- With the pooled rate, independent yes/no rows read φ̂ ≈ 1, where their own rate would
  read N/(N − K).
- The remaining bias is −τ²/[θ̄(1 − θ̄)]: under 1% at realistic τ.

**A denominator between whole numbers.** n/φ is rarely an integer, and no binomial has a
fractional size. Rounding it, the usual workaround, moves a five-item-equivalent
provider by up to 10%. The normal approximation is badly placed at these counts (§4.1).
qikit interpolates every tail linearly in ν = n/φ between m₀ = ⌊ν⌋ and m₀ + 1, at the
same proportion p:

  T(p; ν) = (1 − w)·T_m₀(p·m₀) + w·T_m₀₊₁(p·(m₀ + 1)),  w = ν − m₀.

Each T_m is the exact binomial or beta-binomial tail, itself interpolated between whole
counts (§4.11). Everything follows from this one function:

- **Contours.** The contours are where T crosses each tail probability, found by
  bisection, so "beyond the line" and "p < α" remain one statement.
- **Whole ν.** At a whole ν, T is the exact tail. The contours are then the exact ones,
  continuous through every integer and monotone in volume (both checked by the test
  suite).
- **Consistency across models.** The same holds for the binomial and the beta-binomial,
  so τ̂ = 0 still reproduces the unadjusted chart to the bit.
- **Intervals and detectability.** The 95% interval inverts the same tails in θ. That is
  Korn and Graubard's effective-sample-size Clopper–Pearson interval for survey data
  [16], with this interpolation in place of their beta form. `min_detectable`
  interpolates the chance of crossing the drawn line in the same way.
- **Labels.** `summary["limit_method"]` and `summary["p_value_method"]` read
  `"interpolated"`. The arithmetic is lgamma-free, as in §4.5.

**The case-level check.** Case-level rows are several rows per unit: stays, or surveys.
When they are present and `within_dispersion` is left at 1, qikit computes the row φ̂
above, or the count version of §4.12 for oe/rate, and tests it with Pearson χ² on N − K
degrees of freedom. It warns when φ̂ ≥ 1.25 and p < 0.001. The floor is low because the
test is powerful: at φ = 1.25 the 99.8% limits are √1.25 too narrow, which in the
normal approximation lets through nearly three times the nominal false outliers. When it fires:

- `dispersion_shape` becomes "within", or "both" if the totals also show "between";
- `within_dispersion_hint` is the row φ̂, and `within_dispersion_hint_source` is
  `"rows"` (otherwise `"totals"`);
- the warning, note and caption line of §4.12 follow, naming one row per survey as the
  fix for a proportion.

The check never applies the fix itself. Rows of one yes/no each, and rows that leave
fewer than 30 residual degrees of freedom, are not tested.

**Reading physician-level composites.** Four surveys at φ = 2.42 give about five
effective items. Against a top-box rate of 80%, the 99.8% lower contour is then 1.8%:
only a physician with almost no "Always" answers is an outlier. Against a bottom-box rate
of 10%, the upper contour is 79%. `min_detectable` and `underpowered` say so per
provider. For choosing
physicians for intervention, prefer `signal="fdr"` with a one-sided `worse=`. Top-box and
bottom-box are two tests of the same items, so a physician flagged on both has one
finding, not two.

### 4.14 Shrunk estimates and reliability

Every funnel reports, per provider:

| Column | Definition |
|---|---|
| `raw_excess` | (Y − θ₀N), signed so positive is worse: the observed excess days or events |
| `reliability` | B, the shrinkage weight below |
| `eb_rate` | B·y + (1 − B)·θ₀ (on the plotted scale) |
| `eb_excess` | (eb_rate − θ₀)·N, signed as `raw_excess` |

**The estimator is the chart's own posterior mean.** The adjusted funnels already model
true provider rates as gamma (counts) or beta (proportions) around θ₀ with variance τ²
(§4.5). For those conjugate families the posterior mean of a provider's true rate is
exactly linear in its observed rate: Bühlmann credibility [22]. For the Poisson–gamma
model with a = θ₀²/τ², b = θ₀/τ², the posterior mean is (a + O)/(b + E), so
B = τ²/(τ² + θ₀/E). For the beta-binomial with α + β = s = θ₀(1 − θ₀)/τ² − 1, it is
(α + Y)/(s + n), so B = n/(n + s). Both use the effective n/φ under `within_dispersion`.
There is no choice between a "linear" and an "exact" estimator to make: they are the
same number. B is also the reliability of the provider's score in the sense of the
physician-profiling literature, τ²/(τ² + V₀) [24]; for the beta-binomial it carries the
model's (n − 1)/n factor.

**No spread, no shrinkage target.** When τ̂ = 0, or under `overdispersion=False`, every
B is 0, every `eb_rate` is θ₀ and every `eb_excess` is 0. That is the honest answer: the
data show no between-provider spread, so no provider's difference can be told from
chance. No fallback weight is invented. With the debiased φ̂ (§4.3) this happens far
less often at physician scale.

**Why rank on `eb_excess`.** `raw_excess` scales with volume, so a high-volume provider
with a small, noisy difference outranks a mid-volume provider with a large, certain one.
`eb_excess` is the expected excess once chance is discounted. It is a defensible
prioritisation loss, the expected reducible days or events. Posterior means are not the
optimal statistic for ranks themselves [26]. The approach is the one the CMS hospital
measures and the COPSS–CMS white paper endorse [23, 21], and reliability is how
physician profiling is judged: Adams et al. found most physicians' cost profiles below
the 0.7 reliability usually asked of high-stakes use (59% of physicians), with about 22%
misclassified in a two-tier network [24]. Hofer et al. made the same point for diabetes report cards [25].
`reliability` lets an application apply that floor.

**`prob_worse`** is the posterior probability, under the same model, that the provider's
true value is worse than θ₀: the upper (or, for `worse="lower"`, lower) tail of
Gamma(a + O, b + E) or Beta(α + Y, β + n − Y) at θ₀, on effective counts, from the
regularized incomplete gamma and beta functions. It is NaN when τ = 0. It answers a
different question from `signal`; §4.16 explains which to use.

**Caveat: exchangeability.** Shrinking toward θ₀ assumes providers are alike apart from
noise and τ². A volume–outcome relationship breaks that, because small providers would
then be shrunk toward a mean that is not theirs. The volume test is still planned (§6).

### 4.15 Single-case robustness

Physician leaders ask whether a flag is "one patient". With case-level rows, every
funnel answers per provider:

- **`p_value_drop1`:** the p-value with the provider's most extreme case removed. That is
  the case with the largest y − θ₀n toward `worse=`, or toward the provider's own side
  when `worse=None`. It is tested against the same θ₀, τ² and φ. With provider rows from
  SQL, `max_case_y=`/`max_case_n=` supply that case
  (`MAX_BY(obs, obs − exp)`, with the benchmark 1.0 standing in for θ₀).
- **`flag_survives_drop1`:** for flagged providers, whether they still flag at the alert
  tier with that case removed. Under `signal="fdr"` the same p-value cutoff the step
  used is held fixed.
- **`fragility`:** case rows only. The fewest worst cases that must be removed, in order,
  before the flag goes (scanning up to min(k − 1, 50)). `summary["n_fragile"]` counts
  flagged providers at 1, and a note asks a reviewer to look at that case before acting.
  This is the provider analogue of a trial's Fragility Index [27], a number clinicians
  already read.

**No q-value.** A request asked for `q_value_loo`, the leave-one-out p substituted into
the Benjamini–Hochberg step. Choosing each provider's *worst* case is a one-sided
selection made after seeing the data, and no false discovery rate guarantee survives it.
These columns are descriptive robustness checks, not tests.

**Fragility is not a license to drop cases.** Hofer et al. showed that outlier
physicians on diabetes report cards could greatly improve their profiles by removing
their 1–3 worst-controlled patients [25]. That is exactly why a flag that hinges on one
case needs that case reviewed, not removed. Exclusions must be decided by pre-specified
rules (§4.12 trimming) before the funnel is drawn, never by fragility after it.

**What fragility means depends on the measure.** For days (length of stay), one case
contributes many units, and a fragility of 1 says one long stay carries the flag. That
is worth reviewing, as a placement delay or a coding error. For event counts (deaths,
readmissions) every event is one patient. A low-volume provider flagged on 3 events
against 1 expected will almost always have fragility 1, and that is the discreteness of
counts, not a data problem. The note says so on event-count charts.

**Trimming comes first.** Length-of-stay benchmarks cap or trim outlying stays at
DRG-specific points before aggregating (§4.12 advises the same). That is the primary
defence against single stays. These columns are a check on what remains. For a model-
based check of whole providers, the cross-validated mixed predictive p-values of
Marshall and Spiegelhalter [28] remove a provider from the estimate of θ₀ and τ² it is
judged against, the circularity of §4.2.

### 4.16 Choosing τ

τ, the spread of true values between providers, decides how wide the adjusted funnel
is, how much `eb_rate` shrinks, and what `prob_worse` means. The model itself, true
rates gamma- or beta-distributed around θ₀ with variance τ², is the one the
random-effects literature uses: Pavlou et al.'s Normal–Poisson random-effects model [9],
drawn exactly. The literature differs on where τ comes from, and qikit offers each:

| Option | τ from | Estimator | Strengths | Weaknesses | Used by |
|---|---|---|---|---|---|
| `tau_method="winsorized"` (default) | This period | Method of moments on 10%-winsorized Pearson residuals × c(0.10), then DerSimonian–Laird [1, eqs. 6–10] | Robust to the outliers being screened for; close to unbiased from K ≈ 50; one formula both engines share | Overstates τ slightly at small K with no real spread | qikit (§4.3) |
| `tau_method="spiegelhalter"` | This period | The same without c(0.10) | Reproduces published funnels exactly | Understates τ (often 0 for a real spread) and so over-flags | Spiegelhalter [1], FunnelPlotR [13], NHS/CQC |
| `tau_method="ml"` | This period | Maximum likelihood of the chart's own mixture model, θ₀ fixed; reports a 95% profile-likelihood interval (`tau_ci`) | Uses every count; on clean data returns exactly 0 under the null more often than not; quantifies its own uncertainty | Not robust: a single gross outlier among 30 providers inflates τ̂ and hides itself | Random-effects models: Pavlou [9], CMS's hierarchical models [23] |
| `tau=` (fixed) | Earlier periods, set in advance | Whatever produced it (typically the default on several prior years, reviewed) | Cannot be inflated by this period's outliers; no small-K bias; holds every period to the same yardstick | Needs clean, representative history; goes stale if coding, the risk model or attribution change | Discussed by Pavlou [9]; regulatory practice |

**Evidence.** 150 replicates, E ~ U(3, 30), Poisson–gamma provider effects. The
"fixed" τ was estimated by the default on an independent earlier period with twice the
volume and no outliers, which is the best case for that option:

| Scenario | Winsorized | ML | Fixed in advance |
|---|---|---|---|
| K = 30, τ = 0 | 0.062 (IQR 0–0.141) | 0.000 (0–0.098) | 0.000 (0–0.069) |
| K = 30, τ = 0.15 | 0.149 | 0.146 | 0.150 |
| K = 150, τ = 0.3 | 0.281 | 0.297 | 0.283 |
| K = 150, τ = 0.15, plus 3% outliers at O/E 2.5 | 0.176 | **0.249** | 0.145 |
| K = 30, τ = 0, plus **one** outlier (O/E 2.5 at E = 15) | 0.084 (0–0.147) | **0.216** (0.172–0.264) | — |
| K = 150, τ = 0, plus one outlier | 0.025 (0–0.075) | 0.095 (0.056–0.121) | — |

The last two rows are from the §5 runs, which plant one outlier in every replicate.

- **On clean data the default and ML agree,** and ML is better behaved at small K.
- **ML's advantage does not survive a single outlier.** With one gross outlier among 30
  providers and no real spread, ML's median τ̂ is 0.216, and that outlier's detection
  falls from 90% to 67%. With 3% outliers at K = 150, ML overstates τ by two-thirds.
- **The default, protected by winsorizing, overstates by a sixth or less.**
- **A fixed τ never sees the outliers, so it does not overstate at all.**

Since a screening chart cannot assume its data are free of the outliers it looks for,
ML is for data already cleaned, or for comparison with random-effects analyses.

**Why the default is `"winsorized"`.** A general-purpose default has to work for a user
who does nothing:

- It needs no history, which rules out a fixed τ as the default.
- It must not let the providers being screened for widen their own limits. Funnels exist
  to find outliers, and ML's failure there is the worst failure a screening chart can
  have.
- It must be right at the scale funnels are usually drawn at. At K in the hundreds the
  debiased estimator is close to unbiased (§4.3, §5).

Its one weakness, small K, is flagged by a note below K = 30 that recommends a fixed
`tau=` or `"ml"`.

**Using a fixed τ well.**

1. Estimate τ on several earlier periods with the default, per measure and per facet.
2. Review those periods' flags and confirm τ is stable from year to year.
3. Fix τ for the reporting period, and record the value and its source.

qikit still estimates τ from the current data and reports it as
`summary["tau_estimated"]`. When that is more than 1.5-fold away from the fixed value, a
note says the spread may have changed since τ was set. `tau=0` gives the unadjusted
chart.

**Two questions: `signal` and `prob_worse`.** Ohlssen, Sharples and Spiegelhalter [35]
distinguish *divergent* providers, unusual against the distribution of peers, from
providers whose true value differs from the average. The funnel's `signal` answers the
first: a provider is tested against θ₀ with the spread τ included. CMS's hierarchical
models answer the second [23]: a hospital is reported as worse when its shrunk estimate's
interval lies above the national rate. `prob_worse` is that second question in this
model. The two respond to τ in opposite directions. 10 replicates of K = 500,
E ~ U(3, 30), share of providers flagged:

| true τ | `signal` (one-sided 95%) | `prob_worse` > 0.975 | Truly > 20% above average |
|---|---|---|---|
| 0 | 1.7% | 0.0% | 0% |
| 0.15 | 2.2% | 0.5% | 9.9% |
| 0.30 | 2.4% | 5.2% | 24.2% |

As real variation grows, the funnel keeps flagging about 2%, because that variation is
what peers look like. The CMS-style rule flags more, because more providers really are
worse than average. Use `signal` to choose whom to review as unusual. Use `prob_worse`
when the question is whether a provider is probably worse than average, for example for
improvement targeting, and say which question was asked.

**State of the literature.** No healthcare publication found applies, recommends or
evaluates the winsorization consistency factor. Funnel guidelines [8], applied studies,
FunnelPlotR [13] and the NHS indicators use the uncorrected estimate, and one applied
paper states that it averages 1 under the null, which winsorizing makes untrue. The
default rests on eq. 9 and qikit's own simulations, not on external validation, so a
report that compares qikit with a published funnel should use
`tau_method="spiegelhalter"`. The random-effects literature [9, 23, 35] prefers
likelihood estimation or a pre-specified τ. qikit offers both, with the robustness
caveat above.

## 5. Evidence from simulation

The engine was run on simulated cohorts. To reproduce every table below, run
`uv run python scripts/simulate_funnel_dispersion.py` (qikit 0.10). All rates use the
contours as drawn: the upper contour sits at the exact test's boundary (§4.1).

**Between-provider spread.** 300 replicates per row. Volumes are E ~ U(3, 30) for
counts and n ~ U(20, 200) for proportions (base rate 12%). True provider effects are
drawn with relative SD τ, plus one planted outlier (O/E 2.5 at E = 15, or 30% at
n = 120). On proportions τ̂ is on the absolute scale, so the true value is 0.12·τ (0.018
at τ = 0.15, 0.036 at τ = 0.3). "In-distribution" is the share of non-outlier providers
flagged above the 99.8% limit (nominal 0.1%). "Outlier" is how often the planted outlier
is detected. Each adjusted chart was run with all three estimators on the same draws:
`"spiegelhalter"` (published), `"winsorized"` (the default) and `"ml"` (§4.16).

Flag rates (in-distribution / outlier):

| Family | K | τ | Unadjusted | Spiegelhalter | Winsorized (default) | ML |
|---|---|---|---|---|---|---|
| Counts | 30 | 0 | 0.02% / 90% | 0.02% / 90% | 0.01% / 83% | 0.00% / 67% |
| Counts | 30 | 0.15 | 0.20% / 90% | 0.09% / 85% | 0.03% / 71% | 0.00% / 47% |
| Counts | 30 | 0.3 | 1.89% / 90% | 0.29% / 58% | 0.05% / 33% | 0.01% / 11% |
| Counts | 150 | 0 | 0.05% / 91% | 0.05% / 91% | 0.03% / 90% | 0.02% / 90% |
| Counts | 150 | 0.15 | 0.36% / 93% | 0.31% / 92% | 0.08% / 79% | 0.03% / 75% |
| Counts | 150 | 0.3 | 2.38% / 91% | 0.54% / 70% | 0.11% / 38% | 0.06% / 30% |
| Proportions | 30 | 0.3 | 1.30% / 93% | 0.25% / 69% | 0.02% / 39% | 0.00% / 15% |
| Proportions | 150 | 0.15 | 0.30% / 97% | 0.25% / 96% | 0.05% / 88% | 0.02% / 85% |
| Proportions | 150 | 0.3 | 1.88% / 98% | 0.49% / 83% | 0.08% / 52% | 0.02% / 40% |

τ̂, median (IQR):

| Family | K | τ (true) | Spiegelhalter | Winsorized (default) | ML |
|---|---|---|---|---|---|
| Counts | 30 | 0 | 0 (0–0) | 0.084 (0–0.147) | 0.216 (0.172–0.264) |
| Counts | 30 | 0.15 | 0.014 (0–0.127) | 0.175 (0.108–0.231) | 0.258 (0.204–0.298) |
| Counts | 30 | 0.3 | 0.222 (0.168–0.272) | 0.323 (0.269–0.373) | 0.376 (0.326–0.413) |
| Counts | 150 | 0 | 0 (0–0) | 0.025 (0–0.075) | 0.095 (0.056–0.121) |
| Counts | 150 | 0.15 | 0 (0–0.046) | 0.152 (0.126–0.181) | 0.180 (0.159–0.196) |
| Counts | 150 | 0.3 | 0.196 (0.171–0.217) | 0.291 (0.270–0.313) | 0.313 (0.291–0.334) |
| Proportions | 30 | 0.3 (0.036) | 0.026 (0.019–0.032) | 0.038 (0.032–0.045) | 0.045 (0.040–0.050) |
| Proportions | 150 | 0.15 (0.018) | 0 (0–0.003) | 0.019 (0.015–0.022) | 0.022 (0.020–0.025) |
| Proportions | 150 | 0.3 (0.036) | 0.023 (0.020–0.026) | 0.035 (0.032–0.038) | 0.038 (0.035–0.040) |

- **The winsorized default is the accurate one at physician-group scale.** At K = 150
  its median is 0.152 and 0.291 for a true 0.15 and 0.3 (proportions: 0.019 and 0.035
  against 0.018 and 0.036). The published τ̂ is 0 and 0.196 (0 and 0.023): a real spread
  of 0.15 goes undetected in most replicates.
- **Accurate τ̂ is what makes the chart calibrated.** At K = 150, τ = 0.3, the default
  flags 0.11% of in-distribution providers against a nominal 0.1%. The published chart
  flags 0.54%, five times nominal, and every one of those is a provider whose only
  difference is the ordinary spread between peers.
- **ML is pulled up by the single planted outlier in every replicate.** Its τ̂ exceeds
  the truth in every row: 0.216 when the true τ is 0 at K = 30, and 0.095 at K = 150.
  Its limits are therefore the widest, and it finds the planted outlier least often
  (67% at K = 30, τ = 0, against 83% for the default). On outlier-free data ML matches
  the default and is better at small K (§4.16). This table is the case a screening chart
  must survive.
- **The planted outlier is caught less often as τ̂ rises, and that is partly correct.**
  Its detection falls from 70% (published) to 38% (default) at K = 150, τ = 0.3. The
  published chart caught it more often because it under-estimated τ and drew limits too
  narrow for the real spread, the same narrowness that produced the excess false flags.
  A provider at O/E 2.5 with 15 expected events is less unusual among peers who truly
  vary by 30% than the published chart claimed. That trade is inherent to asking
  "unusual among peers?" rather than "different from target?" (§2, §4.16). For the
  second question, use `center=1.0` with `overdispersion=False`, or read `prob_worse`.
- **At small K with no real spread, the default errs upward.** With K = 30, τ = 0, the
  published τ̂ is 0 (and its limits are then identical to the unadjusted ones). The
  default's median is 0.084, the familiar positive bias of a variance estimate truncated
  at 0 when it is noisy. It costs the planted outlier 90% → 83%, while the false-flag
  rate stays below nominal. By K = 150 the effect is small (median 0.025, detection
  91% → 90%). With a few dozen providers, prefer a pre-specified τ (§4.16).
- **With no real spread every chart runs below nominal** (0.00–0.05% against 0.1%). That
  is the exact test's conservatism at small counts: a discrete count rarely lands
  exactly on the tail.

**Clustered counts: length of stay.** 20 replicates of K = 500 providers. Each provider
has a lognormal number of stays (median 60), each stay's days are gamma with mean 5 and
variance-to-mean φ, and there is no true provider effect, so every flag is false.
`funnel(measure="oe", worse="higher")` is run with its default additive τ², once with the
debiased default and once with `tau_method="spiegelhalter"` on the same draws:

| φ | `within_dispersion` | Outlier, debiased | Alert, debiased | Outlier, published | Alert, published | φ̂ median |
|---|---|---|---|---|---|---|
| 3 | 1 (default) | 0.72% | 3.69% | 1.27% | 5.46% | |
| 3 | `"estimate"` | 0.13% | 2.07% | 0.15% | 2.25% | 3.00 |
| 8 | 1 (default) | 1.10% | 4.39% | 2.13% | 5.92% | |
| 8 | `"estimate"` | 0.10% | 1.97% | 0.12% | 2.11% | 7.96 |

Nominal rates are 0.10% (outlier) and 2.40% (alert). τ̂ absorbs part of the excess but
not the part that shrinks with volume. The debiased τ̂ absorbs more of it, but without
`within_dispersion` the chart still flags 7–11 times the nominal outlier rate (13–21
with the published estimator), all of it noise. With φ̂ the tiers hold their nominal
share under either estimator. Debiasing does not replace the within-case correction.

**The dispersion-shape warning (§4.12).** The share of runs that warn of clustered
counts (100 replicates at K = 40 and 200, 20 at K = 1000). The event-count scenarios
use E lognormal around 40: plain Poisson, a lognormal provider effect with SD 0.5, and
a binary-outcome O/E at a 15% event rate:

| Scenario | K = 40 | K = 200 | K = 1000 |
|---|---|---|---|
| Poisson, no spread | 0% | 0% | 0% |
| Between-provider spread only (lognormal, SD 0.5) | 0% | 0% | 0% |
| Binary-outcome O/E (φ ≈ 0.85) | 0% | 0% | 0% |
| Aggregated length of stay, φ = 3 | 10% | 93% | 100% |
| Aggregated length of stay, φ = 8 | 29% | 100% | 100% |

It is built never to cry wolf on event counts. It catches clustered days reliably from
about 200 providers, the scale at which length-of-stay benchmarking is usually done.

**Clustered proportions: a three-item survey composite (§4.13).** There were 20
replicates of K = 575 physicians, matching the downstream request:

- Each physician had a lognormal number of surveys (median 15, minimum 4).
- Each survey had three items sharing a beta-distributed propensity with intraclass
  correlation 0.71, so φ = 2.42.
- Base rates were 80% (top-box, `worse="lower"`) and 10% (bottom-box, `worse="higher"`).
- "No effect" draws every physician from the base rate, so every flag is false.
- "Spread" adds a true SD between physicians (0.05 top-box, 0.03 bottom-box) and plants
  10 physicians 25 points worse (top-box) or 15 points worse (bottom-box).
- Rates are among the non-planted physicians. The nominal one-sided rates are 0.1%
  outlier and 2.4% alert.

The arms are:

- **Default:** item counts per physician.
- **Rounded deflation:** y and n divided by φ̂ and rounded, the downstream workaround.
- **`"estimate"`:** survey rows.

Each arm was run with the debiased default and with `tau_method="spiegelhalter"` on the same
draws. Cells give debiased / published.

| Scenario | Arm | Outlier | Alert | Planted caught | `signal="fdr"` flags (false) |
|---|---|---|---|---|---|
| Top-box, no effect | default | 0.25% / 0.54% | 2.30% / 3.84% | | 0.6 (0.6) / 2.3 (2.3) |
| | rounded deflation | 0.05% / 0.06% | 1.38% / 1.70% | | 0 / 0 |
| | `"estimate"` | 0.03% / 0.03% | 1.27% / 1.41% | | 0 / 0 |
| Top-box, spread + planted | default | 0.14% / 0.33% | 1.94% / 3.48% | 12% / 28% | 0.5 (0.3) / 4.3 (1.9) |
| | rounded deflation | 0.03% / 0.19% | 1.08% / 2.46% | 11% / 27% | 0.3 (0.0) / 3.1 (0.7) |
| | `"estimate"` | 0.02% / 0.19% | 0.90% / 2.38% | 11% / 27% | 0.5 (0.0) / 3.2 (0.7) |
| Bottom-box, no effect | default | 0.18% / 0.50% | 2.37% / 3.70% | | 0.5 (0.5) / 2.2 (2.2) |
| | rounded deflation | 0.05% / 0.09% | 1.43% / 1.60% | | 0 / 0 |
| | `"estimate"` | 0.00% / 0.01% | 1.19% / 1.23% | | 0 / 0 |
| Bottom-box, spread + planted | default | 0.13% / 0.39% | 1.94% / 3.50% | 4% / 17% | 0.6 (0.4) / 3.3 (1.9) |
| | rounded deflation | 0.03% / 0.16% | 1.42% / 2.42% | 5% / 16% | 0.1 (0.1) / 1.9 (0.6) |
| | `"estimate"` | 0.03% / 0.13% | 1.26% / 2.01% | 8% / 12% | 0.3 (0.1) / 1.4 (0.4) |

φ̂ had a median of 2.36–2.42 against a true 2.42.

- **With no true effect, item counts over-flag.** In the default arm, outliers run at two
  to five times nominal, and FDR selection makes false picks. With φ̂, the outlier rate
  drops below nominal and FDR selects no one, under either estimator.
- **Below nominal is expected.** At about five effective items the exact test is
  conservative (§5, first table). The no-effect `"estimate"` rows (alerts 1.2–1.4%)
  are that floor.
- **With real spread, only the debiased τ̂ sees it.** On the `"estimate"` arm, a separate
  check (8 replicates per scenario) put the published τ̂ at 0.002–0.006 against a true
  0.05 on top-box, and 0 against 0.03 on bottom-box. The debiased τ̂ was 0.049–0.054 and
  0.025–0.029. With the spread modelled, in-distribution rates fall back to the
  no-effect floor (alerts 0.9–1.3%). The published chart's rates are near nominal only
  because real spread between physicians is being reported as signal.
- **The planted physicians are caught less often** (top-box 27% → 11%), for the reason
  in the first table. Physicians 25 points below a peer group that genuinely varies by
  5 points, measured on about five effective items, are not reliably distinguishable
  from that spread. The published chart caught more by under-stating it. At this panel
  size, `min_detectable` is the honest summary: most physicians cannot be flagged at
  all.
- **Rounding is close to the interpolated fix on average,** but it moves individual
  physicians.

The case-level row check (§4.13), on top-box survey rows with a between-physician SD of
0.05, warned in this share of runs (50 replicates at K = 40, 20 at K = 575):

| φ | K = 40 | K = 575 |
|---|---|---|
| 1.00 (independent items) | 0% | 0% |
| 1.10 | 0% | 0% |
| 1.25 (the floor) | 30% | 5% |
| 2.42 | 100% | 100% |

## 6. Known limitations and planned work

- **Small cohorts.** τ̂ is imprecise below about 30 providers (IQR 0.17–0.27 when
  τ = 0.3, K = 30), and the pooled center line can be pulled by one extreme provider
  (§4.2).
- **Debiasing at small K.** The consistency factor (§4.3) assumes residuals near normal,
  and with few providers and no real spread the default overstates τ slightly (median
  0.06–0.08 at K = 30, τ = 0). A note says so below K = 30. A pre-specified `tau=` is
  the remedy there (§4.16). `tau_method="ml"` is better only on clean data.
- **Maximum likelihood is not robust.** `tau_method="ml"` has no winsorizing. One gross
  outlier among 30 providers takes its median τ̂ from 0 to 0.22, and 3% outliers at
  K = 150 inflate it by two-thirds (§4.16, §5).
- **No outcome–volume test yet** [1, §4; 8, step 5]. A funnel assumes outcome does not
  depend on volume.
- **Binary outcomes on an O/E chart.** Observed counts that are sums of yes/no outcomes
  have variance Σp(1 − p) < Σp = E. Poisson limits are therefore slightly too wide for
  common outcomes: about 8% at a 15% event rate, negligible for mortality.
  `within_dispersion` below 1 would correct it, but at small counts its fractional
  effective counts make the test interpolated rather than exact (§4.12). It is left at 1.
- **Within-provider clustering.** One φ per chart (or facet), or one φᵢ per provider
  from a column the caller computes (§4.12). qikit does not yet estimate case-mix φ_g
  from stay rows itself.
- **Items clustered in surveys use a single pooled φ** (§4.13). A provider whose
  patients skip items has smaller clusters and a slightly smaller design effect,
  1 + (m̄ⱼ − 1)ρ. qikit does not model this; it is negligible when item nonresponse is
  low.
- **Item-level rows hide the clustering.** qikit cannot tell items from cases when every
  row is one yes/no. It refuses `"estimate"` on such rows and documents the unit to
  pass (§4.13).
- **Planned:** a robust likelihood estimate of τ (heavy-tailed random effects, or
  detect-then-refit [35]), the volume test, binomial variance for
  binary-outcome O/E when case counts are known, `strata=` (per-DRG φ_g from stay rows,
  shrunk toward the pool [19], combined to φᵢ), and a discrete false discovery rate step
  for bounded tails [31, 32].
- **Evaluated and declined** (so they are not proposed again without new evidence):
  - Per-provider own-variance O/E with limma-style shrinkage (§4.12): self-masking.
  - `q_value` from leave-one-out p-values (§4.15): post-selection.
  - Storey's π̂₀ and a power-screened BH (§4.11): little gain with τ² in the null, and the
    screen drops gross low-volume outliers.
  - A winsorized or median center line. At K in the hundreds no provider moves ΣO/ΣE.
    The median of ratios is not volume-weighted and is skewed at small E. A center
    other than ΣO/ΣE breaks Σ excess = 0. `cl=1.0` is already the robust anchor (§4.2).
  - Monotone "smoothed" display contours. No sawtooth was found on the drawn grid in any
    family or volume range. The proposed running minimum on upper limits would draw lines
    *inside* the exact test, showing unflagged points beyond a line. If ever needed, the
    conservative envelope u(n) = max over m ≥ n of u(m) is the correct form.
  - scipy special functions in `dist.py` (§4.5).

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
15. Benjamini Y, Hochberg Y. Controlling the false discovery rate: a practical and
    powerful approach to multiple testing. *Journal of the Royal Statistical Society,
    Series B* 1995;57(1):289–300.
16. Korn EL, Graubard BI. Confidence intervals for proportions with small expected
    number of positive counts estimated from survey data. *Survey Methodology*
    1998;24(2):193–201.
17. Rao JNK, Scott AJ. A simple method for the analysis of clustered binary data.
    *Biometrics* 1992;48(2):577–585.
18. Kish L. *Survey Sampling*. Wiley, 1965.
19. Smyth GK. Linear models and empirical Bayes methods for assessing differential
    expression in microarray experiments. *Statistical Applications in Genetics and
    Molecular Biology* 2004;3:Article 3. doi:10.2202/1544-6115.1027
20. Jackson D, White IR. When should meta-analysis avoid making hidden normality
    assumptions? *Biometrical Journal* 2018;60(6):1040–1058. doi:10.1002/bimj.201800071
21. Normand SLT, Glickman ME, Gatsonis CA. Statistical methods for profiling providers of
    medical care: issues and applications. *Journal of the American Statistical
    Association* 1997;92(439):803–814. doi:10.1080/01621459.1997.10474036
22. Morris CN. Parametric empirical Bayes inference: theory and applications. *Journal of
    the American Statistical Association* 1983;78(381):47–55. doi:10.2307/2287098
    (Bühlmann H. Experience rating and credibility. *ASTIN Bulletin* 1967;4(3):199–207.)
23. Ash AS, Fienberg SE, Louis TA, Normand SLT, Stukel TA, Utts J. *Statistical Issues in
    Assessing Hospital Performance*. Committee of Presidents of Statistical Societies,
    commissioned by the Centers for Medicare & Medicaid Services, 2012.
24. Adams JL, Mehrotra A, Thomas JW, McGlynn EA. Physician cost profiling — reliability
    and risk of misclassification. *New England Journal of Medicine*
    2010;362(11):1014–1021. doi:10.1056/NEJMsa0906323
25. Hofer TP, Hayward RA, Greenfield S, Wagner EH, Kaplan SH, Manning WG. The
    unreliability of individual physician "report cards" for assessing the costs and
    quality of care of a chronic disease. *JAMA* 1999;281(22):2098–2105.
    doi:10.1001/jama.281.22.2098
26. Lin R, Louis TA, Paddock SM, Ridgeway G. Loss function based ranking in two-stage,
    hierarchical models. *Bayesian Analysis* 2006;1(4):915–946. doi:10.1214/06-BA130
27. Walsh M, Srinathan SK, McAuley DF, et al. The statistical significance of randomized
    controlled trial results is frequently fragile: a case for a Fragility Index.
    *Journal of Clinical Epidemiology* 2014;67(6):622–628.
    doi:10.1016/j.jclinepi.2013.10.019
28. Marshall EC, Spiegelhalter DJ. Identifying outliers in Bayesian hierarchical models:
    a simulation-based approach. *Bayesian Analysis* 2007;2(2):409–444.
    doi:10.1214/07-BA218
29. Bourgon R, Gentleman R, Huber W. Independent filtering increases detection power for
    high-throughput experiments. *PNAS* 2010;107(21):9546–9551.
    doi:10.1073/pnas.0914005107
30. Tarone RE. A modified Bonferroni method for discrete data. *Biometrics*
    1990;46(2):515–522. doi:10.2307/2531456
31. Gilbert PB. A modified false discovery rate multiple-comparisons procedure for
    discrete data, applied to human immunodeficiency virus genetics. *Journal of the
    Royal Statistical Society, Series C* 2005;54(1):143–158.
    doi:10.1111/j.1467-9876.2005.00475.x
32. Döhler S, Durand G, Roquain E. New FDR bounds for discrete and heterogeneous tests.
    *Electronic Journal of Statistics* 2018;12(1):1867–1900. doi:10.1214/18-EJS1441
33. Storey JD, Tibshirani R. Statistical significance for genomewide studies. *PNAS*
    2003;100(16):9440–9445. doi:10.1073/pnas.1530509100
34. Veroniki AA, Jackson D, Viechtbauer W, et al. Methods to estimate the between-study
    variance and its uncertainty in meta-analysis. *Research Synthesis Methods*
    2016;7(1):55–79. doi:10.1002/jrsm.1164
35. Ohlssen DI, Sharples LD, Spiegelhalter DJ. A hierarchical modelling framework for
    identifying unusual performance in health care providers. *Journal of the Royal
    Statistical Society, Series A* 2007;170(4):865–890.
