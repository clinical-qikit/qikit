/**
 * stats.ts — Poisson quantile helpers for O/E (SMR) funnel limits.
 *
 * Twin of src/qikit/spc/dist.py. The shared fixtures assert both engines to ~1e-6,
 * so keep the CDF summation ascending in k here as it is there: changing the order
 * changes the float error. JavaScript has no Math.lgamma, hence the Lanczos
 * approximation below (agreement with C's lgamma is ~1e-13, far inside tolerance).
 *
 * References
 * ----------
 * 1. Spiegelhalter DJ. Funnel plots for comparing institutional performance.
 *    Statistics in Medicine 2005;24(8):1185-1202. (Appendix A.1.1)
 * 2. Breslow NE, Day NE. Statistical Methods in Cancer Research, Vol II. IARC, 1987.
 * 3. Garwood F. Fiducial limits for the Poisson distribution. Biometrika 1936;28:437-442.
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
