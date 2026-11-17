import { ChartType, SPCInput, SPCResult } from '@qikit/engine';
import { GRAIN_CHARTS, NEEDS_N, SpcOptions, DataGrain } from './constants';
import { colLetter } from '../shared/col-letter';

// ─── Summary formatting ───────────────────────────────────────────────────────

/**
 * Format a limit column (cl / ucl / lcl) for a readout with no position attached.
 *
 * Reading row 0 and calling it "the" CL is only honest when the line is flat. It
 * isn't for p/u charts with variable denominators, for xbar/s with unequal subgroup
 * sizes, or for an S chart center line (c4(nᵢ)·σ̂). Those get a range instead.
 */
export function formatLimit(rows: any[], key: string, decimals = 3): string {
  const vals = rows.map(r => r?.[key]).filter(v => typeof v === 'number' && !isNaN(v));
  if (vals.length === 0) return '—';

  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  // Below the displayed precision the two ends would print identically anyway.
  const tol = Math.pow(10, -decimals) / 2;
  if (hi - lo < tol) return lo.toFixed(decimals);
  return `${lo.toFixed(decimals)}–${hi.toFixed(decimals)}`;
}

// ─── Date/aggregation helpers ─────────────────────────────────────────────────

// Text that reads as a date: ISO (2024-01-31, 2024-01), US or European numeric
// (1/31/2024, 31.01.2024), or with a month name (Jan 2024, 31 Jan 2024, January 31, 2024).
// Bare numbers and labels such as "Ward 3" are not dates, whatever new Date() says.
const DATE_TEXT = [
  /^\d{4}-\d{1,2}(-\d{1,2})?([T ].*)?$/,
  /^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}$/,
  /^(\d{1,2} )?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?[ -](\d{1,2},? )?\d{2,4}$/i,
];

/** True for text that reads as a date. Numbers are dates only by their cell format: see isDateFormat. */
export function isLikelyDate(val: any): boolean {
  if (typeof val !== 'string') return false;
  const s = val.trim();
  return DATE_TEXT.some(re => re.test(s)) && !isNaN(new Date(s).getTime());
}

/**
 * True for an Excel number format that displays a date (m/d/yyyy, mmm-yy, yyyy-mm-dd,
 * d-mmm). Excel hands a date cell to an add-in as its serial number; the format is
 * the only thing that says it is a date. Quoted text, escapes, and [colour]/[$-locale]
 * sections are ignored; elapsed-time formats ([h]:mm) and plain numbers are not dates.
 */
export function isDateFormat(fmt: unknown): boolean {
  if (typeof fmt !== 'string') return false;
  const core = fmt.split(';')[0]
    .replace(/"[^"]*"/g, '')
    .replace(/\\./g, '')
    .replace(/\[[^\]]*\]/g, '');
  if (/^general$/i.test(core.trim())) return false;
  return /[dy]/i.test(core) || /m{3,}/i.test(core) || (/m/i.test(core) && !/[hs]/i.test(core));
}

/** Excel serial number (days since 1899-12-30) or date text to a UTC date. */
export function toDate(val: any): Date | null {
  if (typeof val === 'number' && isFinite(val) && val > 0) {
    return new Date(Math.round((val - 25569) * 86400000));
  }
  if (typeof val === 'string' && isLikelyDate(val)) {
    const s = val.trim();
    // A bare ISO date parses as UTC midnight already; anything else parses as local
    // time, so take its calendar date into UTC to keep period keys stable.
    const d = new Date(s);
    if (/^\d{4}-\d{1,2}(-\d{1,2})?$/.test(s)) return d;
    return new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  }
  return null;
}

/**
 * The reporting period that matches how far apart the dates are: daily data stays
 * daily, monthly data monthly. Aggregating daily data to months by default would turn
 * sixty points into two.
 */
export function inferPeriod(dates: (Date | null)[]): string {
  const times = dates.filter((d): d is Date => d !== null).map(d => d.getTime()).sort((a, b) => a - b);
  const gaps: number[] = [];
  for (let i = 1; i < times.length; i++) {
    const g = (times[i] - times[i - 1]) / 86400000;
    if (g > 0) gaps.push(g);
  }
  if (gaps.length === 0) return 'month';
  gaps.sort((a, b) => a - b);
  const median = gaps[Math.floor(gaps.length / 2)];
  if (median <= 3) return 'day';
  if (median <= 10) return 'week';
  if (median <= 45) return 'month';
  if (median <= 120) return 'quarter';
  return 'year';
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

export { colLetter };

export interface ParsedColumns {
  hasHeaders: boolean;
  headers: string[];
  numericCols: number[];
  labelCols: number[];
  dateCols: number[];
}

/**
 * Classify the selected columns as numeric, date, or label. `numberFormats` (the
 * range's formats, same shape as rawData) is what identifies a date cell, since Excel
 * reports dates as serial numbers; without it only date text is recognized.
 */
export function parseColumns(rawData: any[][], numberFormats?: any[][]): ParsedColumns {
  if (rawData.length < 2) return { hasHeaders: false, headers: [], numericCols: [], labelCols: [], dateCols: [] };
  const firstRow = rawData[0];
  const hasHeaders = firstRow.some(v => typeof v === 'string' && String(v).trim() !== '');
  const start = hasHeaders ? 1 : 0;
  const dataRows = rawData.slice(start);
  const formatRows = numberFormats?.slice(start);
  const headers = hasHeaders
    ? firstRow.map((h: any, i: number) => String(h || colLetter(i)))
    : firstRow.map((_: any, i: number) => colLetter(i));
  const numericCols: number[] = [];
  const labelCols: number[] = [];
  const dateCols: number[] = [];
  for (let col = 0; col < headers.length; col++) {
    const filled = dataRows
      .map((row, r) => ({ v: row[col], fmt: formatRows?.[r]?.[col] }))
      .filter(c => c.v != null && c.v !== '');
    const numbers = filled.filter(c => typeof c.v === 'number');
    const isDate = filled.length > 0 && filled.every(c =>
      typeof c.v === 'number' ? isDateFormat(c.fmt) : isLikelyDate(c.v));
    if (isDate) dateCols.push(col);
    else if (numbers.length > 0) numericCols.push(col);
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
  /** Worksheet row number of the selection's first row, so skipped rows can be named. Default 1. */
  firstRow?: number;
}

/** A row of the selection left out of the chart, and why. `row` is the worksheet row number. */
export interface SkippedRow {
  row: number;
  reason: string;
}

export interface PreparedSpcInput {
  input: SPCInput;
  xLabels?: string[];
  partLabels?: string[];
  /** Rows left out, in sheet order. Empty when every row was used. */
  skipped: SkippedRow[];
  /** For each point, the index into the data rows it came from (undefined when points are periods). */
  pointRows?: number[];
}

function describeValue(v: unknown): string {
  const s = String(v).trim();
  return s.length > 20 ? `"${s.slice(0, 19)}…"` : `"${s}"`;
}

function isBlank(v: unknown): boolean {
  return v == null || (typeof v === 'string' && v.trim() === '');
}

/** Why a row's value cannot be used, or null when it can. */
function valueProblem(v: unknown, what: string): string | null {
  if (isBlank(v)) return `no ${what}`;
  if (typeof v !== 'number' || !isFinite(v)) return `${what} ${describeValue(v)} is not a number`;
  return null;
}

function denominatorProblem(v: unknown): string | null {
  const p = valueProblem(v, 'denominator');
  if (p) return p;
  if ((v as number) === 0) return 'denominator is 0';
  if ((v as number) < 0) return 'denominator is negative';
  return null;
}

/**
 * Build the engine input from the selected range and options. Rows with no usable
 * value, denominator or date are left out and listed in `skipped`; a denominator is
 * never read as zero. Returns null when no row is usable.
 */
export function buildSpcInput(sel: SpcDataSelection): PreparedSpcInput | null {
  const { rawData, hasHeaders, dateCols, xCol, yCol, nCol, chartType, dataGrain, xPeriod, options } = sel;
  const dataRows = hasHeaders ? rawData.slice(1) : rawData;
  const sheetRow = (i: number) => (sel.firstRow ?? 1) + (hasHeaders ? 1 : 0) + i;
  const isDateX = xCol !== null && dateCols.includes(xCol);
  const isAttr = NEEDS_N.includes(chartType);
  const isIndividual = GRAIN_CHARTS.includes(chartType) && dataGrain === 'individual';
  // Individual grain: each row is one patient or unit, so n is 1 per row.
  const usesNCol = nCol !== null && !(isIndividual && isAttr);

  const skipped: SkippedRow[] = [];
  const used: number[] = [];
  dataRows.forEach((row, i) => {
    if (row.every(isBlank)) return; // an empty row is not data, so not worth listing
    const problem =
      (isDateX && (isBlank(row[xCol!]) ? 'no date'
        : toDate(row[xCol!]) === null ? `date ${describeValue(row[xCol!])} is not a date` : null))
      || valueProblem(row[yCol], 'value')
      || (usesNCol ? denominatorProblem(row[nCol!]) : null);
    if (problem) skipped.push({ row: sheetRow(i), reason: problem });
    else used.push(i);
  });

  if (used.length === 0) return null;

  let computeY: number[];
  let computeN: number[] | undefined;
  let xLabels: string[] | undefined;
  let pointRows: number[] | undefined;

  const ys = used.map(i => dataRows[i][yCol] as number);
  const ns = (isIndividual && isAttr) ? used.map(() => 1)
    : usesNCol ? used.map(i => dataRows[i][nCol!] as number)
    : undefined;

  if (isDateX) {
    const dates = used.map(i => toDate(dataRows[i][xCol!]));
    const derivedAggFn = isAttr || chartType === 'c' ? 'sum' : 'mean';
    const agg = aggregateByPeriod(dates, ys, ns, xPeriod, derivedAggFn, isAttr);
    computeY = agg.y;
    computeN = agg.n;
    xLabels = agg.labels;
  } else {
    computeY = ys;
    computeN = ns;
    pointRows = used;
    if (xCol !== null) {
      xLabels = used.map(i => dataRows[i][xCol!] != null ? String(dataRows[i][xCol!]) : '');
    }
  }

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

  return { input, xLabels, partLabels, skipped, pointRows };
}

/**
 * Notes read from a data column, keyed by point index. Only for non-date X (aggregation
 * discards row identity). `pointRows` (from buildSpcInput) maps points to the rows used.
 */
export function buildNoteMap(sel: SpcDataSelection, pointRows?: number[]): Record<number, string> {
  const { rawData, hasHeaders, dateCols, xCol, yCol, notesCol } = sel;
  const noteMap: Record<number, string> = {};
  if (notesCol === null) return noteMap;
  const dataRows = hasHeaders ? rawData.slice(1) : rawData;
  const isDateX = xCol !== null && dateCols.includes(xCol);
  const noteRows = isDateX ? []
    : pointRows ? pointRows.map(i => dataRows[i])
    : dataRows.filter(row => typeof row[yCol] === 'number');
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
  pointRows?: number[],
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
    // Skipped rows have no point, so a point's source row is pointRows[i], not row i.
    const source = dataRows[pointRows ? pointRows[i] : i];
    if (includeDataTable && source) {
      return [...source, ...spcRow];
    }
    return spcRow;
  });

  return { finalCols, rows };
}
