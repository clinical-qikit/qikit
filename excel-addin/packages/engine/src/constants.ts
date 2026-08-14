export const D2: Record<number, number> = { 2: 1.128 };
export const D4: Record<number, number> = { 2: 3.267 };

export const B3: Record<number, number> = {
  2: 0.000, 3: 0.000, 4: 0.000, 5: 0.000, 6: 0.030, 7: 0.118, 8: 0.185,
  9: 0.239, 10: 0.284, 11: 0.321, 12: 0.354, 13: 0.382, 14: 0.406,
  15: 0.428, 16: 0.448, 17: 0.466, 18: 0.482, 19: 0.497, 20: 0.510,
  21: 0.523, 22: 0.534, 23: 0.545, 24: 0.555, 25: 0.565,
};

export const B4: Record<number, number> = {
  2: 3.267, 3: 2.568, 4: 2.266, 5: 2.089, 6: 1.970, 7: 1.882, 8: 1.815,
  9: 1.761, 10: 1.716, 11: 1.679, 12: 1.646, 13: 1.618, 14: 1.594,
  15: 1.572, 16: 1.552, 17: 1.534, 18: 1.518, 19: 1.503, 20: 1.490,
  21: 1.477, 22: 1.466, 23: 1.455, 24: 1.445, 25: 1.435,
};

export const A3: Record<number, number> = {
  2: 2.659, 3: 1.954, 4: 1.628, 5: 1.427, 6: 1.287, 7: 1.182, 8: 1.099,
  9: 1.032, 10: 0.975, 11: 0.927, 12: 0.886, 13: 0.850, 14: 0.817,
  15: 0.789, 16: 0.763, 17: 0.739, 18: 0.718, 19: 0.698, 20: 0.680,
  21: 0.663, 22: 0.647, 23: 0.633, 24: 0.619, 25: 0.606,
};

export const C4: Record<number, number> = {
  2: 0.7979, 3: 0.8862, 4: 0.9213, 5: 0.9400, 6: 0.9515, 7: 0.9594,
  8: 0.9650, 9: 0.9693, 10: 0.9727, 11: 0.9754, 12: 0.9776, 13: 0.9794,
  14: 0.9810, 15: 0.9823, 16: 0.9835, 17: 0.9845, 18: 0.9854, 19: 0.9862,
  20: 0.9869, 21: 0.9876, 22: 0.9882, 23: 0.9887, 24: 0.9892, 25: 0.9896,
};

// ---------------------------------------------------------------------------
// Constant accessors — tabulated for n = 2..25, analytic above.
// Mirrors src/qikit/spc/constants.py.
//
// The tables stay authoritative below n = 26: the series form for c4 is a poor
// substitute at small n, putting c4(2) at 0.8203 vs the tabulated 0.7979 (+2.8%),
// which in turn skews A3(2) to 2.586 vs 2.659 (-2.7%) and B4(2) to 3.092 vs 3.267
// (-5.4%). By n = 25 the two agree to four decimals, so the seam is smooth and
// the series takes over from there.
//
// Do not "simplify" the tables away — small-n charts would move.
// ---------------------------------------------------------------------------

function tabulated(n: number, table: Record<number, number>): number | undefined {
  return n >= 2 && n <= 25 && Number.isInteger(n) ? table[n] : undefined;
}

/** Unbiasing constant: E[s] = c4(n)·σ. NaN for n < 2. */
export function c4(n: number): number {
  if (!(n >= 2)) return NaN;
  const hit = tabulated(n, C4);
  if (hit !== undefined) return hit;
  return 1 - 1 / (4 * n) - 7 / (32 * n * n);
}

/** 3·√(1 − c4²)/c4 — the half-width shared by B3 and B4. */
function bSpread(n: number): number {
  const c = c4(n);
  return Number.isNaN(c) ? NaN : (3 * Math.sqrt(Math.max(0, 1 - c * c))) / c;
}

/** A3 = 3/(c4·√n) for the Xbar chart. NaN for n < 2. */
export function a3(n: number): number {
  const hit = tabulated(n, A3);
  if (hit !== undefined) return hit;
  const c = c4(n);
  return Number.isNaN(c) ? NaN : 3 / (c * Math.sqrt(n));
}

/** B3 = max(0, 1 − 3√(1 − c4²)/c4) for the S chart. NaN for n < 2. */
export function b3(n: number): number {
  const hit = tabulated(n, B3);
  if (hit !== undefined) return hit;
  const spread = bSpread(n);
  return Number.isNaN(spread) ? NaN : Math.max(0, 1 - spread);
}

/** B4 = 1 + 3√(1 − c4²)/c4 for the S chart. NaN for n < 2. */
export function b4(n: number): number {
  const hit = tabulated(n, B4);
  if (hit !== undefined) return hit;
  const spread = bSpread(n);
  return Number.isNaN(spread) ? NaN : 1 + spread;
}

// ---------------------------------------------------------------------------
// Normal deviates for the funnel probability contours (Spiegelhalter 2005).
//
// Funnel plots are drawn at 95% and 99.8% rather than at 2σ/3σ: 99.8% keeps the
// expected number of false alarms near one even across a few hundred providers.
// Only Byar's approximation consumes these — the exact method inverts the Poisson
// CDF directly, so no Φ⁻¹ implementation is needed anywhere.
// ---------------------------------------------------------------------------

/** Φ⁻¹(0.975) */
export const Z_95 = 1.959963984540054;
/** Φ⁻¹(0.999) */
export const Z_998 = 3.090232306167813;
/**
 * Φ⁻¹(0.8) — the power convention for the detectability column, not a limit.
 * Used only by the large-count normal fallback in oeDetectableRatio.
 */
export const Z_80 = 0.8416212335729143;
