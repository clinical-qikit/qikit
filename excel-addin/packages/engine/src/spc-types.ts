export type ChartType =
  | 'run' | 'i' | 'ip' | 'mr' | 's' | 'p' | 'u' | 'c' | 'g'
  | 'pp' | 'up' | 'xbar' | 't';

export type SignalMethod = 'anhoej' | 'ihi' | 'weco' | 'nelson';

export interface SPCInput {
  y: number[];
  /** Denominators for p/pp/u/up. A scalar is broadcast to every point — the
   *  constant-subgroup-size case, which the shared fixtures use throughout. */
  n?: number[] | number;
  chart: ChartType;
  method?: SignalMethod;
  freeze?: number;
  part?: number[];
  exclude?: number[];
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
  /** Funnel plot mode (p/pp/u/up only): sort by denominator ascending, sigma signals only. */
  funnel?: boolean;
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
           sigmaHat?: number) => [number[], number[]] | [number[], number[], number[]];
  needsN: boolean;
  isAttribute: boolean;
  floorLcl: boolean;
}
