/**
 * stats.ts — exact quantile helpers for funnel limits.
 *
 * Twin of src/qikit/spc/dist.py. The shared fixtures assert both engines to ~1e-6,
 * so keep every summation in the same order here as there: changing the order
 * changes the float error. JavaScript has no Math.lgamma, hence the Lanczos
 * approximation below (agreement with C's lgamma is ~1e-13, far inside tolerance).
 *
 * Numbered references are those of docs/methods.md.
 *
 * References
 * ----------
 * [1] Spiegelhalter DJ. Funnel plots for comparing institutional performance.
 *     Statistics in Medicine 2005;24(8):1185-1202. (Appendix A.1.1, A.2.1)
 * [4] Breslow NE, Day NE. Statistical Methods in Cancer Research, Vol II. IARC, 1987.
 * [5] Garwood F. Fiducial limits for the Poisson distribution. Biometrika 1936;28:437-442.
 * [7] Clayton D, Kaldor J. Empirical Bayes estimates of age-standardized relative risks
 *     for use in disease mapping. Biometrics 1987;43:671-681.
 */

/** Above this mean the exact loop stops earning its cost; Byar is within 1e-4 relative. */
export const EXACT_MAX_LAMBDA = 1e5;

/**
 * Ceiling for the mean-inversion solves. Distinct from EXACT_MAX_LAMBDA because
 * bisection multiplies the sweep cost by its iteration count.
 */
export const MEAN_SOLVE_MAX_K = 1e4;

/** Fixed so both ports perform an identical sequence of operations. */
const BISECT_ITERS = 50;

/**
 * Grid every lgamma-derived result is quantized to, so it does not depend on the
 * host's libm. Both routines below accumulate many lgamma terms and inherit their
 * last-ulp platform differences; the committed fixture snapshots are compared byte
 * for byte. 1e-9 is far below anything displayed and far above the noise it erases.
 * Mirrors _QUANTIZE_DECIMALS in dist.py.
 */
const QUANTIZE_DECIMALS = 9;

/** Round to the QUANTIZE_DECIMALS grid. */
function quantize(v: number): number {
  const scale = Math.pow(10, QUANTIZE_DECIMALS);
  return Math.round(v * scale) / scale;
}

const LANCZOS_G = 7;
const LANCZOS_C = [
  0.99999999999980993, 676.5203681218851, -1259.1392167224028,
  771.32342877765313, -176.61502916214059, 12.507343278686905,
  -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7,
];

/** log Γ(x) via the Lanczos approximation, with the reflection formula below 0.5. */
export function lgamma(x: number): number {
  if (x < 0.5) {
    // Γ(x)Γ(1−x) = π/sin(πx)
    return Math.log(Math.PI / Math.abs(Math.sin(Math.PI * x))) - lgamma(1 - x);
  }
  const z = x - 1;
  let series = LANCZOS_C[0];
  for (let i = 1; i < LANCZOS_G + 2; i++) {
    series += LANCZOS_C[i] / (z + i);
  }
  const t = z + LANCZOS_G + 0.5;
  return 0.5 * Math.log(2 * Math.PI) + (z + 0.5) * Math.log(t) - t + Math.log(series);
}

/**
 * Byar's approximation to a Poisson quantile at normal deviate z.
 *
 * q = λ·(1 − 1/(9λ) ± z/(3√λ))³, the Wilson-Hilferty cube-root transform. The lower
 * cube root is floored at 0 — for small λ the bracket goes negative, and cubing a
 * negative would put the limit below zero rather than at it.
 */
export function byarQuantile(lam: number, z: number, upper: boolean): number {
  if (!(lam > 0) || Number.isNaN(lam)) return NaN;
  const root = 1 - 1 / (9 * lam);
  const half = z / (3 * Math.sqrt(lam));
  if (upper) return lam * Math.pow(root + half, 3);
  return lam * Math.pow(Math.max(0, root - half), 3);
}

/**
 * Continuity-interpolated Poisson quantile (Spiegelhalter 2005, Appendix A.1.1).
 *
 * The raw quantile is the smallest integer r with F(r; λ) ≥ p. Taking r itself would
 * make the funnel a staircase — the limit only moves when the integer quantile jumps.
 * Spiegelhalter interpolates within the jump:
 *
 *     δ = (F(r) − p) / (F(r) − F(r−1)),   q = max(0, r − δ)
 *
 * so q lies in [r−1, r] and varies smoothly with λ. This is deliberately not what R's
 * qpois returns (that is r, uninterpolated).
 *
 * Returns NaN for a non-positive or non-finite λ. Callers must fall back to
 * byarQuantile above EXACT_MAX_LAMBDA.
 */
/**
 * Poisson CDF F(k; λ) = P(X ≤ k), summed ascending in k.
 * Twin of poisson_cdf in dist.py — same term expression as the quantile loop below.
 */
export function poissonCdf(k: number, lam: number): number {
  if (Number.isNaN(lam) || lam < 0) return NaN;
  if (k < 0) return 0.0;
  if (lam === 0) return 1.0; // all mass at zero

  const logLam = Math.log(lam);
  let cdf = 0.0;
  const kk = Math.floor(k);
  for (let j = 0; j <= kk; j++) {
    cdf += Math.exp(j * logLam - lam - lgamma(j + 1.0));
  }
  return Math.min(1.0, cdf);
}

/**
 * The Poisson mean μ satisfying F(k; μ) = p, by bisection. Twin of
 * poisson_mean_for_cdf in dist.py.
 *
 * F(k; μ) is strictly decreasing in μ, so the root is unique. The bracket
 * [0, k + 10√(k+1) + 20] holds it for every p used here (F(k; hi) < 1e-10).
 * Throws above MEAN_SOLVE_MAX_K; callers pre-check and use a closed form.
 *
 * The result is quantized (see QUANTIZE_DECIMALS): lgamma's last ulp is
 * platform-dependent and bisection amplifies it into a ~1e-13 difference, which the
 * byte-exact fixture snapshots will not tolerate.
 */
export function poissonMeanForCdf(k: number, p: number): number {
  if (Number.isNaN(p) || !(p > 0 && p < 1)) return NaN;
  if (k < 0) return NaN;
  if (k > MEAN_SOLVE_MAX_K) {
    throw new Error(
      `poissonMeanForCdf: k=${k} exceeds the solve ceiling (${MEAN_SOLVE_MAX_K}); ` +
      `the caller should use a closed-form approximation.`
    );
  }

  let lo = 0.0;
  let hi = k + 10.0 * Math.sqrt(k + 1.0) + 20.0;
  for (let i = 0; i < BISECT_ITERS; i++) {
    const mid = 0.5 * (lo + hi);
    if (poissonCdf(k, mid) > p) {
      lo = mid; // still too much mass at or below k — the mean must rise
    } else {
      hi = mid;
    }
  }
  return quantize(0.5 * (lo + hi));
}

export function poissonQuantileInterp(p: number, lam: number): number {
  if (!(lam > 0) || Number.isNaN(lam)) return NaN;
  if (lam > EXACT_MAX_LAMBDA) {
    throw new Error(
      `poissonQuantileInterp: lambda=${lam} exceeds the exact-method ceiling ` +
      `(${EXACT_MAX_LAMBDA}); the caller should fall back to byarQuantile.`
    );
  }

  const logLam = Math.log(lam);
  // Far enough above the mode that the remaining mass is below double precision.
  const maxK = Math.floor(lam + 20 * Math.sqrt(lam) + 100);

  let cdf = 0;
  let prev = 0;
  let k = 0;
  while (k <= maxK) {
    prev = cdf;
    cdf += Math.exp(k * logLam - lam - lgamma(k + 1));
    if (cdf >= p) break;
    k++;
  }

  // p sits in the float plateau at the top of the CDF; the cap is the answer.
  if (k > maxK) return maxK;

  const jump = cdf - prev;
  const delta = jump > 0 ? (cdf - p) / jump : 0;
  return quantize(Math.max(0, k - delta));
}

// ---------------------------------------------------------------------------
// Binomial, Poisson–gamma and beta-binomial quantiles
// ---------------------------------------------------------------------------
//
// Twins of the same-named functions in dist.py, which explains the method: each pmf
// is built from its term ratio f(k+1)/f(k) outward from the mode and normalised at the
// end, using only + − × ÷. That makes these bit-identical to the Python side and free
// of lgamma cancellation as τ² → 0. Keep the operation order exactly as there.

/** Terms below this fraction of the largest are dropped. Mirrors _TAIL_EPS. */
const TAIL_EPS = 1e-20;

/** Safety net for absurdly wide distributions; mirrors _MAX_TERMS. */
const MAX_TERMS = 100_000;

/**
 * Unnormalised pmf terms from a term ratio, as [kLo, terms, total]. Twin of
 * _walk_terms; null when the walk exceeds MAX_TERMS.
 */
function walkTerms(
  ratio: (k: number) => number, start: number, upper: number | null
): [number, number[], number] | null {
  const up: number[] = [1.0];
  let peak = 1.0;
  let u = 1.0;
  let k = start;
  while (upper === null || k < upper) {
    u = u * ratio(k);
    k += 1;
    if (u > peak) peak = u;
    if (u < TAIL_EPS * peak) break;
    up.push(u);
    if (up.length > MAX_TERMS) return null;
  }
  const down: number[] = [];
  u = 1.0;
  k = start;
  while (k > 0) {
    u = u / ratio(k - 1);
    k -= 1;
    if (u > peak) peak = u;
    if (u < TAIL_EPS * peak) break;
    down.push(u);
    if (down.length > MAX_TERMS) return null;
  }

  const terms = down.slice().reverse().concat(up);
  const kLo = start - down.length;
  let total = 0.0;
  for (const t of terms) total += t;
  return [kLo, terms, total];
}

/** Continuity-interpolated quantiles from a term ratio. Twin of _walk_quantiles. */
function walkQuantiles(
  probs: readonly number[], ratio: (k: number) => number, start: number, upper: number | null
): number[] | null {
  const walk = walkTerms(ratio, start, upper);
  if (walk === null) return null;
  const [kLo, terms, total] = walk;

  const out: number[] = [];
  for (const p of probs) {
    let cdf = 0.0;
    let prev = 0.0;
    let r = kLo;
    let found = false;
    for (const t of terms) {
      prev = cdf;
      cdf += t / total;
      if (cdf >= p) {
        found = true;
        break;
      }
      r += 1;
    }
    if (!found) {
      // p sits in the float plateau at the top of the CDF.
      out.push(kLo + terms.length - 1);
      continue;
    }
    const jump = cdf - prev;
    const delta = jump > 0 ? (cdf - p) / jump : 0.0;
    out.push(quantize(Math.max(0.0, r - delta)));
  }
  return out;
}

/** [1] eq. 3 / eq. 11 on the count scale, for the fallbacks. Twin of _normal_quantiles. */
function normalQuantiles(mean: number, variance: number, zs: readonly number[]): number[] {
  const sd = Math.sqrt(variance);
  return zs.map(z => Math.max(0.0, mean + z * sd));
}

/** Quantiles plus whether they are exact (false = normal-approximation fallback). */
export type QuantileResult = [number[], boolean];

/**
 * Continuity-interpolated Binomial(n, θ) quantiles on the count scale, [1] A.1.1.
 * Twin of binomial_quantiles. A non-integer n falls back to [1] eq. 3.
 */
export function binomialQuantiles(
  probs: readonly number[], n: number, theta: number, zs: readonly number[]
): QuantileResult {
  if (!(n > 0) || Number.isNaN(n) || Number.isNaN(theta)) return [probs.map(() => NaN), true];
  if (theta <= 0.0) return [probs.map(() => 0.0), true];
  if (theta >= 1.0) return [probs.map(() => n), true];
  if (Math.abs(n - Math.round(n)) > 1e-9 * Math.max(1.0, n)) {
    return [normalQuantiles(n * theta, n * theta * (1.0 - theta), zs), false];
  }
  const m = Math.round(n);
  const odds = theta / (1.0 - theta);
  const ratio = (k: number) => (m - k) / (k + 1) * odds;
  const start = Math.min(m, Math.floor((m + 1) * theta));
  const out = walkQuantiles(probs, ratio, start, m);
  if (out === null) return [normalQuantiles(m * theta, m * theta * (1.0 - theta), zs), false];
  return [out, true];
}

/**
 * Binomial CDF F(k; m, θ) = P(X ≤ k) from the same lgamma-free walk as
 * binomialQuantiles. Twin of binomial_cdf in dist.py: normalised by the terms' own
 * total, so (1 − θ)^m, which underflows at hospital volumes, is never formed.
 */
export function binomialCdf(k: number, m: number, theta: number): number {
  if (Number.isNaN(theta) || !(theta >= 0.0 && theta <= 1.0)) return NaN;
  if (k < 0) return 0.0;
  if (k >= m || theta <= 0.0) return 1.0;
  if (theta >= 1.0) return 0.0;
  const odds = theta / (1.0 - theta);
  const ratio = (j: number) => (m - j) / (j + 1) * odds;
  const start = Math.min(m, Math.floor((m + 1) * theta));
  const walk = walkTerms(ratio, start, m);
  if (walk === null) return NaN;
  const [kLo, terms, total] = walk;
  let cdf = 0.0;
  const last = Math.min(k - kLo + 1, terms.length);
  for (let j = 0; j < last; j++) cdf += terms[j];
  return Math.min(1.0, cdf / total);
}

/**
 * The θ satisfying F(k; m, θ) = p, by bisection on [0, 1]. Twin of
 * binomial_theta_for_cdf. Not quantized: binomialCdf uses only + − × ÷, so the
 * bisection path is already identical across platforms and languages.
 * NaN outside 0 ≤ k < m or for p outside (0, 1).
 */
export function binomialThetaForCdf(k: number, m: number, p: number): number {
  if (Number.isNaN(p) || !(p > 0 && p < 1) || k < 0 || k >= m) return NaN;
  let lo = 0.0;
  let hi = 1.0;
  for (let i = 0; i < BISECT_ITERS; i++) {
    const mid = 0.5 * (lo + hi);
    if (binomialCdf(k, m, mid) > p) {
      lo = mid; // still too much mass at or below k — θ must rise
    } else {
      hi = mid;
    }
  }
  return 0.5 * (lo + hi);
}

/**
 * Continuity-interpolated Poisson–gamma (negative binomial) quantiles [7], mean λ and
 * variance λ + λ²/size. Twin of poisson_gamma_quantiles.
 */
export function poissonGammaQuantiles(
  probs: readonly number[], lam: number, size: number, zs: readonly number[]
): QuantileResult {
  if (!(lam > 0) || Number.isNaN(lam) || !(size > 0)) return [probs.map(() => NaN), true];
  const q = lam / (size + lam);
  const ratio = (k: number) => (k + size) / (k + 1) * q;
  const start = size > 1.0 ? Math.floor((size - 1.0) * lam / size) : 0;
  const out = walkQuantiles(probs, ratio, start, null);
  if (out === null) return [normalQuantiles(lam, lam + lam * lam / size, zs), false];
  return [out, true];
}

/**
 * Continuity-interpolated beta-binomial quantiles on the count scale. Twin of
 * beta_binomial_quantiles; a non-integer n falls back to the normal approximation.
 */
export function betaBinomialQuantiles(
  probs: readonly number[], n: number, alpha: number, beta: number, zs: readonly number[]
): QuantileResult {
  if (!(n > 0) || Number.isNaN(n) || !(alpha > 0) || !(beta > 0)) {
    return [probs.map(() => NaN), true];
  }
  const m = Math.round(n);
  const theta = alpha / (alpha + beta);
  if (Math.abs(n - m) > 1e-9 * Math.max(1.0, n)) {
    const v = n * theta * (1.0 - theta) * (alpha + beta + n) / (alpha + beta + 1.0);
    return [normalQuantiles(n * theta, v, zs), false];
  }
  const ratio = (k: number) => (m - k) * (alpha + k) / ((k + 1) * (beta + m - k - 1));
  const start = Math.min(m, Math.floor(m * theta));
  const out = walkQuantiles(probs, ratio, start, m);
  if (out === null) {
    const v = m * theta * (1.0 - theta) * (alpha + beta + m) / (alpha + beta + 1.0);
    return [normalQuantiles(m * theta, v, zs), false];
  }
  return [out, true];
}
