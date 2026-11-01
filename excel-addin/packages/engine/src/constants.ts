import { lgamma } from './stats';

export const D2: Record<number, number> = { 2: 1.128 };
export const D4: Record<number, number> = { 2: 3.267 };

// c4 and the constants built from it are computed exactly, as qicharts2 does; the
// textbook tables are these values rounded. Twin of constants.py.

/** Unbiasing constant E[s] = c4(n)·σ: √(2/(n − 1))·Γ(n/2)/Γ((n − 1)/2). NaN for n < 2. */
export function c4(n: number): number {
  if (!(n >= 2)) return NaN;
  return Math.sqrt(2 / (n - 1)) * Math.exp(lgamma(n / 2) - lgamma((n - 1) / 2));
}

/** 3·√(1 − c4²)/c4 — the half-width shared by B3 and B4. */
function bSpread(n: number): number {
  const c = c4(n);
  return Number.isNaN(c) ? NaN : (3 * Math.sqrt(Math.max(0, 1 - c * c))) / c;
}

/** A3 = 3/(c4·√n) for the Xbar chart. NaN for n < 2. */
export function a3(n: number): number {
  const c = c4(n);
  return Number.isNaN(c) ? NaN : 3 / (c * Math.sqrt(n));
}

/** B3 = max(0, 1 − 3√(1 − c4²)/c4) for the S chart. NaN for n < 2. */
export function b3(n: number): number {
  const spread = bSpread(n);
  return Number.isNaN(spread) ? NaN : Math.max(0, 1 - spread);
}

/** B4 = 1 + 3√(1 − c4²)/c4 for the S chart. NaN for n < 2. */
export function b4(n: number): number {
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
