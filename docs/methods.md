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
count model for counts that clump within cases (§4.12). `qic()` keeps p/u with 3σ
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
| Winsorizing debiasing factor w(q) | Derived (eq. 9), not adopted in his example | Not applied (§4.3) |
| Multiplicative model | φ̂, applied if φ̂ > 1 + 2√(2/I) | Not used (§4.4) |
| Additive model | τ̂² by method of moments (eq. 10), 0 if φ̂ < (I−1)/I | Same |
| Adjusted limits | θ₀ ± z√(V + τ²), normal (eq. 11) | **Differs**: same variance, exact mixture quantiles (§4.5) |
| Under-dispersion | Never narrow the limits | Same |
| X-axis | Indicator against precision ρ, smooth pre-drawn limits (§2) | Same in effect: against volume (n, or E), which is proportional to ρ, with smooth contours (§4.9) |
| Outcome–volume association | Formal regression test (§4) | **Not yet** (§6) |
| Multiple comparisons | Small P values; FDR "best carried out separately" (§6) | Exact p-values and Benjamini–Hochberg q-values on every funnel; `signal="fdr"` tiers on q instead of the contours, at `fdr_levels` (§4.11). `expected_false_flags` reports chance flags per tier |
| Counts that clump within cases (days per stay) | Not covered | Extension: `within_dispersion=φ`, effective counts O/φ against E/φ, with a diagnostic that warns when it is missing (§4.12) |
| Change data, continuous outcomes | A.1.2, A.2.2, A.3 | Not offered |
| Per-point power and intervals | Not part of the method | Extension on every funnel (§4.8) |

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
A non-integer denominator (an averaged or weighted n) has no binomial description,
which is why its limits fall back to the normal approximation. For the same reason its
detectability and interval are NaN rather than approximated.

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

**Binomial charts step in whole numbers.** A non-integer n has no binomial
description and falls back to the normal approximation (§4.8, "Edge cases"), so a grid
of fractional steps would mix the two. On p/pp the grid is rounded to integers. The
Poisson and Poisson–gamma charts take any positive n.

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
- **Normal fallback.** Where the limits fall back to the normal approximation, the
  p-values do too, with the same mean and variance and no continuity correction:
  - a non-integer binomial denominator;
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

## 5. Evidence from simulation

The engine was run on simulated cohorts. To reproduce every table below, run
`uv run python scripts/simulate_funnel_dispersion.py`. All rates use the contours as
drawn: the upper contour sits at the exact test's boundary (§4.1).

**Between-provider spread.** 300 replicates per row. Volumes are E ~ U(3, 30) for
counts and n ~ U(20, 200) for proportions (base rate 12%). True provider effects are
drawn with relative SD τ, plus one planted outlier (O/E 2.5 at E = 15, or 30% at
n = 120). "In-distribution" is the share of non-outlier providers flagged above the
99.8% limit (nominal 0.1%). "Outlier" is how often the planted outlier is detected.

| Family | K | τ | Unadjusted, in-distribution | Unadjusted, outlier | Adjusted, in-distribution | Adjusted, outlier | τ̂ median (IQR) |
|---|---|---|---|---|---|---|---|
| Counts | 30 | 0 | 0.02% | 90% | 0.02% | 90% | 0 (0–0) |
| Counts | 30 | 0.15 | 0.20% | 90% | 0.09% | 85% | 0.01 (0–0.13) |
| Counts | 30 | 0.3 | 1.89% | 90% | 0.29% | 58% | 0.22 (0.17–0.27) |
| Counts | 150 | 0.3 | 2.38% | 91% | 0.54% | 70% | 0.20 (0.17–0.22) |
| Proportions | 30 | 0.3 | 1.30% | 93% | 0.25% | 69% | 0.026 (0.019–0.032) |
| Proportions | 150 | 0.3 | 1.88% | 98% | 0.49% | 83% | 0.023 (0.020–0.026) |

- **τ̂ = 0 is common at physician scale.** That happened in 86% of K = 30 replicates at
  τ = 0. In every one of those, the adjusted limits were identical to the unadjusted
  limits.
- **With no real spread the chart runs below nominal** (0.02% against 0.1% at K = 30).
  That is the exact test's conservatism at small counts: a discrete count rarely lands
  exactly on the tail.
- **When τ is real, the adjustment cuts in-distribution flags four- to sixfold.** They
  stay above nominal because the published estimator runs low (§4.3).
- **The cost is detection of a genuine outlier.** It falls as the spread it is judged
  against widens. That trade is inherent to asking "unusual among peers?" rather than
  "different from target?" (§2).

**Clustered counts: length of stay.** 20 replicates of K = 500 providers. Each provider
has a lognormal number of stays (median 60), each stay's days are gamma with mean 5 and
variance-to-mean φ, and there is no true provider effect, so every flag is false.
`funnel(measure="oe", worse="higher")` is run with its default additive τ²:

| φ | `within_dispersion` | Outlier rate (nominal 0.10%) | Alert rate (nominal 2.40%) | φ̂ median |
|---|---|---|---|---|
| 3 | 1 (default) | 1.27% | 5.46% | |
| 3 | `"estimate"` | 0.15% | 2.25% | 3.00 |
| 8 | 1 (default) | 2.13% | 5.92% | |
| 8 | `"estimate"` | 0.12% | 2.11% | 7.96 |

τ̂ absorbs part of the excess but not the part that shrinks with volume. Without the fix
the chart flags 13–21 times the nominal outlier rate, all of it noise. With φ̂ the
tiers hold their nominal share.

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

## 6. Known limitations and planned work

- **Small cohorts.** τ̂ is imprecise below about 30 providers (IQR 0.17–0.27 when
  τ = 0.3, K = 30), and the pooled center line can be pulled by one extreme provider
  (§4.2).
- **Downward bias.** The published φ̂ is biased low, so the method under-adjusts (§4.3).
- **No outcome–volume test yet** [1, §4; 8, step 5]. A funnel assumes outcome does not
  depend on volume.
- **Binary outcomes on an O/E chart.** Observed counts that are sums of yes/no outcomes
  have variance Σp(1 − p) < Σp = E. Poisson limits are therefore slightly too wide for
  common outcomes: about 8% at a 15% event rate, negligible for mortality.
  `within_dispersion` below 1 would correct it, but at small counts its fractional
  effective counts make the test interpolated rather than exact (§4.12). It is left at 1.
- **Within-provider clustering is a single φ per chart (or facet).** Case mix that
  changes how variable stays are between providers is not modelled. Facet by service
  line where φ̂ differs.
- **Planned:** a pre-specified τ [9], the volume test, and binomial variance for
  binary-outcome O/E when case counts are known.

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
