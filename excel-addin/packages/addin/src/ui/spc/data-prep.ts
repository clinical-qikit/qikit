import { ChartType, SPCInput, SPCResult } from '@qikit/engine';
import { GRAIN_CHARTS, NEEDS_N, SpcOptions, DataGrain } from './constants';

// ─── Date/aggregation helpers ─────────────────────────────────────────────────

export function isLikelyDate(val: any): boolean {
  if (val == null || val === '') return false;
  if (typeof val === 'number' && val > 25569 && val < 60000) return true; // Excel serial date range
  if (typeof val === 'string') {
    const d = new Date(val);
    return !isNaN(d.getTime());
  }
  return false;
}

export function toDate(val: any): Date | null {
  if (typeof val === 'number' && val > 25569 && val < 60000) {
    return new Date((val - 25569) * 86400000);
  }
  if (typeof val === 'string') {
    const d = new Date(val);
    return isNaN(d.getTime()) ? null : d;
  }
  return null;
}

export function periodKey(d: Date, period: string): string {
  const y = d.getUTCFullYear();
  const m = d.getUTCMonth() + 1;
  const day = d.getUTCDate();
  if (period === 'day')     return `${y}-${String(m).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
  if (period === 'week') {
    // ISO week: Monday-based
    const tmp = new Date(Date.UTC(y, m-1, day));
    const dayOfWeek = tmp.getUTCDay() || 7;
    tmp.setUTCDate(tmp.getUTCDate() + 4 - dayOfWeek);
    const yearStart = new Date(Date.UTC(tmp.getUTCFullYear(), 0, 1));
    const week = Math.ceil(((tmp.getTime() - yearStart.getTime()) / 86400000 + 1) / 7);
    return `${tmp.getUTCFullYear()}-W${String(week).padStart(2,'0')}`;
  }
  if (period === 'month')   return `${y}-${String(m).padStart(2,'0')}`;
  if (period === 'quarter') return `${y}-Q${Math.ceil(m / 3)}`;
  if (period === 'year')    return `${y}`;
  return `${y}-${String(m).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
}

const MONTH_SHORT = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

export function periodFirstDate(key: string, period: string): Date {
  if (period === 'day') return new Date(key + 'T00:00:00Z');
  if (period === 'month') return new Date(key + '-01T00:00:00Z');
  if (period === 'quarter') {
    const [y, q] = key.split('-Q');
    const month = (parseInt(q) - 1) * 3;
    return new Date(Date.UTC(parseInt(y), month, 1));
  }
  if (period === 'year') return new Date(Date.UTC(parseInt(key), 0, 1));
  if (period === 'week') {
    // Parse YYYY-Www → Monday of that ISO week
    const [yearStr, wStr] = key.split('-W');
    const y = parseInt(yearStr);
    const w = parseInt(wStr);
    // Jan 4 is always in week 1
    const jan4 = new Date(Date.UTC(y, 0, 4));
    const dayOfWeek = jan4.getUTCDay() || 7;
    const week1Mon = new Date(jan4.getTime() - (dayOfWeek - 1) * 86400000);
    return new Date(week1Mon.getTime() + (w - 1) * 7 * 86400000);
  }
  return new Date(key);
}

export function formatPeriodLabel(d: Date, period: string): string {
  const day = d.getUTCDate();
  const mon = MONTH_SHORT[d.getUTCMonth()];
  const year = d.getUTCFullYear();
  if (period === 'day')     return `${day} ${mon}`;
  if (period === 'week')    return `${day} ${mon}`;
  if (period === 'month')   return `${mon} ${year}`;
  if (period === 'quarter') return `${mon} ${year}`;
  if (period === 'year')    return `${year}`;
  return `${day} ${mon}`;
}

export function aggregateByPeriod(
  dates: (Date | null)[],
  yValues: number[],
  nValues: (number | null)[] | undefined,
  period: string,
  aggFn: string,
  isAttribute: boolean
): { labels: string[]; y: number[]; n?: number[] } {
  const groups = new Map<string, { ys: number[]; ns: number[] }>();
  dates.forEach((d, i) => {
    if (!d || isNaN(yValues[i])) return;
    const key = periodKey(d, period);
    if (!groups.has(key)) groups.set(key, { ys: [], ns: [] });
    groups.get(key)!.ys.push(yValues[i]);
    if (nValues) groups.get(key)!.ns.push(nValues[i] ?? 0);
  });
  const keys = [...groups.keys()].sort();
  const labels = keys.map(k => formatPeriodLabel(periodFirstDate(k, period), period));
  const y = keys.map(k => {
    const { ys } = groups.get(k)!;
    if (isAttribute || aggFn === 'sum') return ys.reduce((a, b) => a + b, 0);
    if (aggFn === 'median') {
      const sorted = [...ys].sort((a, b) => a - b);
      const mid = Math.floor(sorted.length / 2);
      return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
    }
    return ys.reduce((a, b) => a + b, 0) / ys.length; // mean
  });
  const n = nValues
    ? keys.map(k => groups.get(k)!.ns.reduce((a, b) => a + b, 0))
    : undefined;
  return { labels, y, n };
}

// ─── Column helpers ───────────────────────────────────────────────────────────

export function colLetter(index: number): string {
  let result = '';
  let n = index;
  do {
    result = String.fromCharCode(65 + (n % 26)) + result;
    n = Math.floor(n / 26) - 1;
  } while (n >= 0);
  return result;
}

export interface ParsedColumns {
  hasHeaders: boolean;
  headers: string[];
  numericCols: number[];
  labelCols: number[];
  dateCols: number[];
}

export function parseColumns(rawData: any[][]): ParsedColumns {
  if (rawData.length < 2) return { hasHeaders: false, headers: [], numericCols: [], labelCols: [], dateCols: [] };
  const firstRow = rawData[0];
  const hasHeaders = firstRow.some(v => typeof v === 'string' && String(v).trim() !== '');
  const dataRows = hasHeaders ? rawData.slice(1) : rawData;
  const headers = hasHeaders
    ? firstRow.map((h: any, i: number) => String(h || colLetter(i)))
    : firstRow.map((_: any, i: number) => colLetter(i));
  const numericCols: number[] = [];
  const labelCols: number[] = [];
  const dateCols: number[] = [];
  for (let col = 0; col < headers.length; col++) {
    const vals = dataRows.map(row => row[col]);
    const isNumeric = vals.some(v => typeof v === 'number');
    const isDate = !isNumeric && vals.filter(v => v != null && v !== '').length > 0
      && vals.filter(v => v != null && v !== '').every(v => isLikelyDate(v));
    if (isNumeric) numericCols.push(col);
    else if (isDate) dateCols.push(col);
    else labelCols.push(col);
  }
  return { hasHeaders, headers, numericCols, labelCols, dateCols };
}

// ─── Compute-input assembly ───────────────────────────────────────────────────

export interface SpcDataSelection {
  rawData: any[][];
  hasHeaders: boolean;
  dateCols: number[];
  xCol: number | null;
  yCol: number;
  nCol: number | null;
  notesCol: number | null;
  chartType: ChartType;
  dataGrain: DataGrain;
  xPeriod: string;
  options: SpcOptions;
}

export interface PreparedSpcInput {
  input: SPCInput;
  xLabels?: string[];
  partLabels?: string[];
}

/** Build the engine input from the selected range and options. Returns null when the Y column has no numeric data. */
export function buildSpcInput(sel: SpcDataSelection): PreparedSpcInput | null {
  const { rawData, hasHeaders, dateCols, xCol, yCol, nCol, chartType, dataGrain, xPeriod, options } = sel;
  const dataRows = hasHeaders ? rawData.slice(1) : rawData;
  const isDateX = xCol !== null && dateCols.includes(xCol);
  const isAttr = NEEDS_N.includes(chartType);
  const isIndividual = GRAIN_CHARTS.includes(chartType) && dataGrain === 'individual';

  let computeY: number[];
  let computeN: number[] | undefined;
  let xLabels: string[] | undefined;

  if (isDateX) {
    const dates = dataRows.map(row => toDate(row[xCol!]));
    const rawY = dataRows.map(row => Number(row[yCol]));
    // Individual mode: derive n from row count (each row = one patient/unit)
    const rawN = (isIndividual && isAttr)
      ? dataRows.map(() => 1 as number | null)
      : (nCol !== null)
        ? dataRows.map(row => typeof row[nCol!] === 'number' ? row[nCol!] : null)
        : undefined;
    const derivedAggFn = isAttr || chartType === 'c' ? 'sum' : 'mean';
    const agg = aggregateByPeriod(dates, rawY, rawN, xPeriod, derivedAggFn, isAttr);
    computeY = agg.y;
    computeN = agg.n;
    xLabels = agg.labels;
  } else {
    computeY = dataRows.map(row => row[yCol]).filter(v => typeof v === 'number') as number[];
    if (isIndividual && isAttr) {
      // Each row is one patient/unit — n = 1 per row
      computeN = computeY.map(() => 1);
    } else if (nCol !== null) {
      const nVals = dataRows.filter(row => typeof row[yCol] === 'number').map(row => row[nCol as number]);
      if (nVals.every(v => typeof v === 'number')) computeN = nVals as number[];
    }
    if (xCol !== null) {
      xLabels = dataRows.map(row => row[xCol!] != null ? String(row[xCol!]) : '');
    }
  }

  if (computeY.length === 0) return null;

  const input: SPCInput = {
    y: computeY,
    n: computeN,
    chart: chartType,
    method: options.method,
    freeze: options.freeze ? parseInt(options.freeze) : undefined,
    part: options.part ? options.part.split(',').map(s => parseInt(s.trim())).filter(v => !isNaN(v)) : undefined,
    exclude: options.exclude ? options.exclude.split(',').map(s => parseInt(s.trim())).filter(v => !isNaN(v)) : undefined,
    clOverride: options.clOverride ? parseFloat(options.clOverride) : undefined,
    multiply: options.multiply ? parseFloat(options.multiply) : undefined,
    subgroupN: options.subgroupN ? parseInt(options.subgroupN) : undefined,
  };

  const partLabels = options.partLabels
    ? options.partLabels.split(',').map(s => s.trim()).filter(Boolean)
    : undefined;

  return { input, xLabels, partLabels };
}

/** Notes read from a data column, keyed by point index. Only for non-date X (aggregation discards row identity). */
export function buildNoteMap(sel: SpcDataSelection): Record<number, string> {
  const { rawData, hasHeaders, dateCols, xCol, yCol, notesCol } = sel;
  const noteMap: Record<number, string> = {};
  if (notesCol === null) return noteMap;
  const dataRows = hasHeaders ? rawData.slice(1) : rawData;
  const isDateX = xCol !== null && dateCols.includes(xCol);
  const noteRows = isDateX ? [] : dataRows.filter(row => typeof row[yCol] === 'number');
  noteRows.forEach((row, i) => {
    const note = row[notesCol!];
    if (note != null && String(note).trim() !== '') noteMap[i] = String(note).trim();
  });
  return noteMap;
}

// ─── Sheet output assembly ────────────────────────────────────────────────────

export function buildSheetRows(
  result: SPCResult,
  annotations: Record<number, string>,
  rawData: any[][],
  hasHeaders: boolean,
  headers: string[],
  includeDataTable: boolean,
): { finalCols: string[]; rows: any[][] } {
  const hasAnnot = Object.keys(annotations).length > 0;
  const cols = ['Point', 'Value', 'CL', 'UCL', 'LCL', 'Signal'];
  if (hasAnnot) cols.push('Note');

  const sourceCols = includeDataTable && rawData.length > 0
    ? (hasHeaders ? rawData[0] : headers).map(String)
    : [];

  const finalCols = includeDataTable ? [...sourceCols, ...cols] : cols;

  const dataRows = hasHeaders ? rawData.slice(1) : rawData;
  const rows = result.data.map((d: any, i: number) => {
    const spcRow: any[] = [
      i + 1, d.y,
      isNaN(d.cl) ? null : d.cl,
      isNaN(d.ucl) ? null : d.ucl,
      isNaN(d.lcl) ? null : d.lcl,
      (d.sigma_signal || d.runs_signal) ? 1 : null,
    ];
    if (hasAnnot) spcRow.push(annotations[i] || null);
    if (includeDataTable && dataRows[i]) {
      return [...dataRows[i], ...spcRow];
    }
    return spcRow;
  });

  return { finalCols, rows };
}
