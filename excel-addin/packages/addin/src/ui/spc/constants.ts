import { ChartType } from '@qikit/engine';

// ─── Chart type definitions ──────────────────────────────────────────────────

export const CORE_CHARTS: ChartType[] = ['run', 'i', 'mr', 'xbar', 's', 'p', 'u', 'c'];
export const ADDITIONAL_CHARTS: ChartType[] = ['ip', 'g', 't', 'pp', 'up'];
export const NEEDS_N: ChartType[] = ['p', 'u', 'pp', 'up', 'ip'];
export const NEEDS_SUBGROUP: ChartType[] = ['xbar', 's'];
export const GRAIN_CHARTS: ChartType[] = ['p', 'u', 'pp', 'up', 'ip', 'c'];

export const CHART_LABELS: Record<string, string> = {
  i:    'I – Individuals',
  mr:   'MR – Moving Range',
  xbar: 'X̄ – Subgroup Mean',
  s:    'S – Subgroup Std Dev',
  p:    'P – Proportion',
  u:    'U – Count per Unit',
  c:    'C – Count',
  run:  'Run – Median',
  ip:   'IP – Individuals (Proportions)',
  g:    'G – Gap',
  t:    'T – Time Between Events',
  pp:   "P′ – Laney P′",
  up:   "U′ – Laney U′",
};

// ─── Options ─────────────────────────────────────────────────────────────────

export interface SpcOptions {
  method: 'anhoej' | 'ihi' | 'weco' | 'nelson';
  freeze: string;
  target: string;
  part: string;
  partLabels: string;
  exclude: string;
  clOverride: string;
  multiply: string;
  subgroupN: string;
  show95: boolean;
}

export const DEFAULT_OPTIONS: SpcOptions = {
  method: 'anhoej',
  freeze: '',
  target: '',
  part: '',
  partLabels: '',
  exclude: '',
  clOverride: '',
  multiply: '',
  subgroupN: '',
  show95: false,
};

export type DataGrain = 'summarized' | 'individual';
