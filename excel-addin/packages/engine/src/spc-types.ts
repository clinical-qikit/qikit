export type ChartType =
  | 'run' | 'i' | 'ip' | 'mr' | 's' | 'p' | 'u' | 'c' | 'g'
  | 'pp' | 'up' | 'xbar' | 't' | 'oe' | 'oep';

/** Quantile method for the oe chart's Poisson funnel limits. */
export type LimitMethod = 'exact' | 'byar';

export type SignalMethod = 'anhoej' | 'ihi' | 'weco' | 'nelson';

export interface SPCInput {
  y: number[];
  /** Denominators for p/pp/u/up. A scalar is broadcast to every point — the
   *  constant-subgroup-size case, which the shared fixtures use throughout. */
  n?: number[] | number;
  chart: ChartType;
  method?: SignalMethod;
  freeze?: number;
  /** 1-based index (or list) where a new phase begins. A bare index is accepted. */
  part?: number[] | number;
  /** 1-based index (or list) to ghost from the baseline *and* from signal
   *  detection. A bare index is accepted, as for part. */
  exclude?: number[] | number;
  clOverride?: number;
  multiply?: number;
  /** Arithmetic mean of subgroup SDs — xbar/s with equal subgroup sizes. */
  sBar?: number;
  /** Pooled σ̂ — xbar/s with unequal subgroup sizes. Mutually exclusive with sBar.
   *  When neither is given, compute() derives one from the subgrouped data. */
  sigmaHat?: number;
  /** Fallback subgroup size, used only when no per-point n array is available.
   *  Not a constraint — any size >= 2 is valid. */
  subgroupN?: number;
  /** Funnel plot mode (p/pp/u/up/oe only): sort by denominator ascending, sigma signals only. */
  funnel?: boolean;
  /** Quantile method for the oe chart's funnel limits, and valid only there.
   *  "exact" (default) inverts the Poisson CDF with Spiegelhalter's continuity
   *  interpolation; "byar" is the closed-form Wilson-Hilferty approximation, which
   *  drifts below expected counts of ~20 — exactly where per-provider volumes live. */
  limitMethod?: LimitMethod;
  /** Point connectivity: true = lines+markers, false = markers only.
   *  Undefined = renderer infers from the x-axis. Funnel mode forces false. */
  connect?: boolean;
  /** Display the y-axis as percent. Undefined = default by chart type (true for p/pp). */
  yPercent?: boolean;
}

export interface SPCResult {
  chart_type: string;
  method: string;
  signals: boolean;
  summary: Record<string, any>;
  data: Array<Record<string, any>>;
  /** Resolved connectivity hint: true/false as requested (funnel forces false); null = infer from x-axis. */
  connect: boolean | null;
  /** Resolved percent-axis hint (defaults to true for p/pp charts). */
  y_percent: boolean;
  to_dict(): Record<string, any>;
}

export interface ChartSpec {
  center: (yBase: number[], nBase?: number[]) => number;
  /**
   * Returns [ucl, lcl] — or [ucl, lcl, cl] for a chart whose center line varies per
   * point (S chart with unequal subgroup sizes, CL = c4(nᵢ)·σ̂). The optional third
   * element overrides the scalar `center` above; an explicit clOverride still wins.
   */
  limits: (cl: number, y: number[], n: number[] | undefined,
           mask: boolean[], subgroupN?: number, sBar?: number,
           sigmaHat?: number, limitMethod?: LimitMethod) => [number[], number[]] | [number[], number[], number[]];
  /**
   * The 95% band, for charts whose inner band is a genuine probability contour
   * rather than two thirds of the outer one — see the oe chart. Undefined means the
   * caller derives that band arithmetically from the 3σ spread, which is exact only
   * because those limits are symmetric about the center line.
   */
  limits95?: (cl: number, y: number[], n: number[] | undefined,
              mask: boolean[], subgroupN?: number, sBar?: number,
              sigmaHat?: number, limitMethod?: LimitMethod) => [number[], number[]];
  needsN: boolean;
  isAttribute: boolean;
  floorLcl: boolean;
}
