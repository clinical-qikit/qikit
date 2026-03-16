export type ChartType =
  | 'run' | 'i' | 'ip' | 'mr' | 's' | 'p' | 'u' | 'c' | 'g'
  | 'pp' | 'up' | 'xbar' | 't';

export type SignalMethod = 'anhoej' | 'ihi' | 'weco' | 'nelson';

export interface SPCInput {
  y: number[];
  n?: number[];
  chart: ChartType;
  method?: SignalMethod;
  freeze?: number;
  part?: number[];
  exclude?: number[];
  clOverride?: number;
  multiply?: number;
  sBar?: number;
  subgroupN?: number;
}

export interface SPCResult {
  chart_type: string;
  method: string;
  signals: boolean;
  summary: Record<string, any>;
  data: Array<Record<string, any>>;
  to_dict(): Record<string, any>;
}

export interface ChartSpec {
  center: (yBase: number[], nBase?: number[]) => number;
  limits: (cl: number, y: number[], n: number[] | undefined,
           mask: boolean[], subgroupN?: number, sBar?: number) => [number[], number[]];
  needsN: boolean;
  isAttribute: boolean;
  floorLcl: boolean;
}
