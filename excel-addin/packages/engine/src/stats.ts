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
 */

/** Above this mean the exact loop stops earning its cost; Byar is within 1e-4 relative. */
export const EXACT_MAX_LAMBDA = 1e5;

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
  return Math.max(0, k - delta);
}
