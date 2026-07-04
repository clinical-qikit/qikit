import React, { useState, useEffect, useCallback } from 'react';
import {
  Button, Select, Input, Checkbox, makeStyles,
} from '@fluentui/react-components';
import {
  ChevronDownRegular, ChevronRightRegular,
  ArrowSyncRegular, SettingsRegular,
  ArrowDownloadRegular, DocumentRegular,
} from '@fluentui/react-icons';
import { ChartType, compute, SPCResult, SPCInput } from '@qikit/engine';
import { getSelectedRangeValues, writeToNewSheet } from '../../excel/excel-io';
import { ChartViewer } from '../shared/ChartViewer';
import { DataPreview } from '../shared/DataPreview';

// ─── Chart type definitions ──────────────────────────────────────────────────

const CORE_CHARTS: ChartType[] = ['run', 'i', 'mr', 'xbar', 's', 'p', 'u', 'c'];
const ADDITIONAL_CHARTS: ChartType[] = ['ip', 'g', 't', 'pp', 'up'];
const NEEDS_N: ChartType[] = ['p', 'u', 'pp', 'up', 'ip'];
const NEEDS_SUBGROUP: ChartType[] = ['xbar', 's'];
const GRAIN_CHARTS: ChartType[] = ['p', 'u', 'pp', 'up', 'ip', 'c'];

const CHART_LABELS: Record<string, string> = {
  i:    'I \u2013 Individuals',
  mr:   'MR \u2013 Moving Range',
  xbar: 'X\u0304 \u2013 Subgroup Mean',
  s:    'S \u2013 Subgroup Std Dev',
  p:    'P \u2013 Proportion',
  u:    'U \u2013 Count per Unit',
  c:    'C \u2013 Count',
  run:  'Run \u2013 Median',
  ip:   'IP \u2013 Individuals (Proportions)',
  g:    'G \u2013 Gap',
  t:    'T \u2013 Time Between Events',
  pp:   "P\u2032 \u2013 Laney P\u2032",
  up:   "U\u2032 \u2013 Laney U\u2032",
};

// ─── Types ───────────────────────────────────────────────────────────────────

interface SpcOptions {
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

const DEFAULT_OPTIONS: SpcOptions = {
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

// ─── Date/aggregation helpers ─────────────────────────────────────────────────

function isLikelyDate(val: any): boolean {
  if (val == null || val === '') return false;
  if (typeof val === 'number' && val > 25569 && val < 60000) return true; // Excel serial date range
  if (typeof val === 'string') {
    const d = new Date(val);
    return !isNaN(d.getTime());
  }
  return false;
}

function toDate(val: any): Date | null {
  if (typeof val === 'number' && val > 25569 && val < 60000) {
    return new Date((val - 25569) * 86400000);
  }
  if (typeof val === 'string') {
    const d = new Date(val);
    return isNaN(d.getTime()) ? null : d;
  }
  return null;
}

function periodKey(d: Date, period: string): string {
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

function periodFirstDate(key: string, period: string): Date {
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

function formatPeriodLabel(d: Date, period: string): string {
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

function aggregateByPeriod(
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

function colLetter(index: number): string {
  let result = '';
  let n = index;
  do {
    result = String.fromCharCode(65 + (n % 26)) + result;
    n = Math.floor(n / 26) - 1;
  } while (n >= 0);
  return result;
}

function parseColumns(rawData: any[][]): {
  hasHeaders: boolean;
  headers: string[];
  numericCols: number[];
  labelCols: number[];
  dateCols: number[];
} {
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

// ─── Styles ──────────────────────────────────────────────────────────────────

// ─── Palette: clinical teal, Excel-native neutrals ───────────────────────────
// Primary teal #107C6C — professional, clinical, distinct from AI purple
// Neutrals drawn from Fluent Design: warm grays that feel native to Office

const useStyles = makeStyles({
  panel: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0',
    overflowY: 'auto',
    height: '100%',
    fontFamily: "'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif",
    backgroundColor: '#ffffff',
  },
  section: {
    padding: '14px 16px',
    borderBottom: '1px solid #e8e6e3',
  },
  sectionLabel: {
    fontSize: '11px',
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: '0.6px',
    color: '#8e8e96',
    marginBottom: '10px',
  },
  dataSourceEmpty: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '12px',
    padding: '28px 16px',
    textAlign: 'center',
  },
  dataSourceIcon: {
    width: '42px',
    height: '42px',
    borderRadius: '8px',
    backgroundColor: '#e8f5f2',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    color: '#107C6C',
    fontSize: '20px',
  },
  dataSourceHint: {
    fontSize: '12px',
    color: '#8e8e96',
    lineHeight: '1.4',
  },
  dataSourceBar: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  address: {
    flex: 1,
    fontSize: '11.5px',
    fontFamily: "'Cascadia Code', 'SF Mono', 'Consolas', monospace",
    color: '#5c5c65',
    backgroundColor: '#f6f6f8',
    padding: '6px 10px',
    borderRadius: '4px',
    border: '1px solid #e8e6e3',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  colRow: {
    display: 'flex',
    gap: '10px',
    alignItems: 'center',
    marginBottom: '2px',
  },
  colLabel: {
    fontSize: '11.5px',
    fontWeight: '600',
    color: '#5c5c65',
    minWidth: '14px',
  },
  chartTypeRow: {
    display: 'flex',
    gap: '3px',
    alignItems: 'center',
    flexWrap: 'wrap',
  },
  chartBtn: {
    padding: '5px 10px',
    borderRadius: '4px',
    border: '1px solid #d0ceca',
    backgroundColor: '#ffffff',
    color: '#5c5c65',
    fontSize: '12px',
    fontWeight: '600',
    fontFamily: 'inherit',
    cursor: 'pointer',
    letterSpacing: '0.3px',
    textTransform: 'uppercase',
    transition: 'all 0.12s ease',
    '&:hover': {
      borderTopColor: '#107C6C',
      borderRightColor: '#107C6C',
      borderBottomColor: '#107C6C',
      borderLeftColor: '#107C6C',
      color: '#0A6B5C',
      backgroundColor: '#e8f5f2',
    },
  },
  chartBtnActive: {
    backgroundColor: '#107C6C',
    borderTopColor: '#0A6B5C',
    borderRightColor: '#0A6B5C',
    borderBottomColor: '#0A6B5C',
    borderLeftColor: '#0A6B5C',
    color: '#ffffff',
    boxShadow: '0 1px 2px rgba(16,124,108,0.25)',
  },
  chartBtnMore: {
    padding: '5px 10px',
    borderRadius: '4px',
    border: '1px dashed #c8c6c4',
    backgroundColor: 'transparent',
    color: '#8e8e96',
    fontSize: '11px',
    fontWeight: '500',
    fontFamily: 'inherit',
    cursor: 'pointer',
    transition: 'all 0.12s ease',
    '&:hover': {
      borderTopColor: '#107C6C',
      borderRightColor: '#107C6C',
      borderBottomColor: '#107C6C',
      borderLeftColor: '#107C6C',
      color: '#0A6B5C',
    },
  },
  chartMorePanel: {
    display: 'flex',
    gap: '3px',
    flexWrap: 'wrap',
    marginTop: '6px',
    paddingTop: '8px',
    borderTop: '1px solid #e8e6e3',
  },
  settingsToggle: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    padding: '0',
    border: 'none',
    background: 'none',
    cursor: 'pointer',
    fontSize: '12px',
    fontWeight: '500',
    color: '#5c5c65',
    fontFamily: 'inherit',
    '&:hover': {
      color: '#107C6C',
    },
  },
  settingsPanel: {
    display: 'flex',
    flexDirection: 'column',
    gap: '10px',
    marginTop: '10px',
    padding: '12px',
    backgroundColor: '#f6f6f8',
    borderRadius: '6px',
    border: '1px solid #e8e6e3',
  },
  settingRow: {
    display: 'grid',
    gridTemplateColumns: '100px 1fr',
    alignItems: 'center',
    gap: '8px',
  },
  settingLabel: {
    fontSize: '12px',
    color: '#5c5c65',
  },
  divider: {
    height: '1px',
    backgroundColor: '#e8e6e3',
    margin: '2px 0',
  },
  // Summary
  summaryTable: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: '6px 12px',
  },
  summaryItem: {
    fontSize: '12px',
    color: '#323130',
  },
  summaryKey: {
    fontSize: '11px',
    color: '#8e8e96',
    marginBottom: '1px',
  },
  summaryVal: {
    fontSize: '13px',
    fontWeight: '600',
    color: '#1B1B1F',
  },
  signalBadge: {
    display: 'inline-flex',
    alignItems: 'center',
    padding: '4px 10px',
    borderRadius: '4px',
    fontSize: '12px',
    fontWeight: '600',
    marginBottom: '8px',
  },
  emptyChart: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '8px',
    height: '180px',
    margin: '0 16px 16px',
    backgroundColor: '#f6f6f8',
    borderRadius: '6px',
    border: '1px dashed #d0ceca',
    color: '#8e8e96',
    fontSize: '13px',
  },
  annotBar: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    padding: '8px 12px',
    margin: '0 16px',
    backgroundColor: '#fdf8ee',
    borderRadius: '4px',
    border: '1px solid #e8d5a8',
  },
  annotBarLabel: {
    fontSize: '12px',
    fontWeight: '600',
    color: '#7a5c1e',
    flexShrink: 0,
    whiteSpace: 'nowrap',
  },
  annotList: {
    display: 'flex',
    flexDirection: 'column',
    gap: '3px',
    padding: '0 16px',
  },
  annotItem: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    padding: '5px 10px',
    backgroundColor: '#fdf8ee',
    borderRadius: '4px',
    fontSize: '12px',
  },
  annotItemText: {
    flex: 1,
    color: '#5c5c65',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  actions: {
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
    padding: '14px 16px',
    borderTop: '1px solid #e8e6e3',
    marginTop: 'auto',
  },
  error: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    margin: '0 16px',
    padding: '8px 12px',
    backgroundColor: '#fdf2f2',
    color: '#c4314b',
    borderRadius: '4px',
    border: '1px solid #f0c8c8',
    fontSize: '12px',
    lineHeight: '1.4',
  },
});

// ─── Component ───────────────────────────────────────────────────────────────

export const SpcPanel: React.FC = () => {
  const styles = useStyles();

  // Data
  const [rangeAddress, setRangeAddress] = useState<string | null>(null);
  const [rawData, setRawData] = useState<any[][]>([]);
  const [hasHeaders, setHasHeaders] = useState(false);
  const [headers, setHeaders] = useState<string[]>([]);
  const [numericCols, setNumericCols] = useState<number[]>([]);
  const [_labelCols, setLabelCols] = useState<number[]>([]);
  const [dateCols, setDateCols] = useState<number[]>([]);
  const [yCol, setYCol] = useState<number>(0);
  const [nCol, setNCol] = useState<number | null>(null);
  const [dataGrain, setDataGrain] = useState<'summarized' | 'individual'>('summarized');
  const [xCol, setXCol] = useState<number | null>(null);
  const [notesCol, setNotesCol] = useState<number | null>(null);

  // Date aggregation
  const [xPeriod, setXPeriod] = useState<string>('month');

  // Chart
  const [chartType, setChartType] = useState<ChartType>('run');
  const [result, setResult] = useState<SPCResult | null>(null);

  // Annotations
  const [annotations, setAnnotations] = useState<Record<number, string>>({});
  const [activeAnnotIdx, setActiveAnnotIdx] = useState<number | null>(null);
  const [annotText, setAnnotText] = useState('');

  // UI
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [moreChartsOpen, setMoreChartsOpen] = useState(false);
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [includeDataTable, setIncludeDataTable] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Options
  const [options, setOptions] = useState<SpcOptions>(DEFAULT_OPTIONS);

  const setOpt = (key: keyof SpcOptions) => (_: any, data: { value: string }) =>
    setOptions(o => ({ ...o, [key]: data.value }));

  // Parse columns when data loaded
  useEffect(() => {
    if (rawData.length === 0) return;
    const parsed = parseColumns(rawData);
    setHasHeaders(parsed.hasHeaders);
    setHeaders(parsed.headers);
    setNumericCols(parsed.numericCols);
    setLabelCols(parsed.labelCols);
    setDateCols(parsed.dateCols);
    if (parsed.numericCols.length > 0) setYCol(parsed.numericCols[0]);
    setNCol(null);
    setNotesCol(null);
    // Auto-select first date or label col as X
    const firstDate = parsed.dateCols[0] ?? null;
    const firstLabel = parsed.labelCols[0] ?? null;
    setXCol(firstDate ?? firstLabel ?? null);
  }, [rawData]);

  // Auto-compute
  useEffect(() => {
    if (rawData.length < 2) {
      setResult(null);
      return;
    }
    setError(null);
    try {
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

      if (computeY.length === 0) {
        setError('No numeric data in selected column.');
        setResult(null);
        return;
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

      const res = compute(input);

      // Attach xLabels and partLabels to result for ChartViewer
      (res as any)._xLabels = xLabels;
      (res as any)._partBoundaries = input.part;
      (res as any)._partLabels = options.partLabels
        ? options.partLabels.split(',').map(s => s.trim()).filter(Boolean)
        : undefined;

      setResult(res);

      // Notes from data column
      if (notesCol !== null) {
        const noteRows = isDateX ? [] : dataRows.filter(row => typeof row[yCol] === 'number');
        const noteMap: Record<number, string> = {};
        noteRows.forEach((row, i) => {
          const note = row[notesCol!];
          if (note != null && String(note).trim() !== '') noteMap[i] = String(note).trim();
        });
        setAnnotations(prev => ({ ...noteMap, ...prev }));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Computation failed.');
      setResult(null);
    }
  }, [rawData, hasHeaders, chartType, yCol, nCol, xCol, notesCol, xPeriod, options, dateCols, dataGrain]);

  const handleSelectData = useCallback(async () => {
    setError(null);
    try {
      const res = await getSelectedRangeValues();
      setRawData(res.values);
      setRangeAddress(res.address);
      setAnnotations({});
      setActiveAnnotIdx(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to read selection.');
    }
  }, []);

  const handlePointClick = useCallback((idx: number) => {
    setActiveAnnotIdx(idx);
    setAnnotText('');
    setAnnotations(current => { setAnnotText(current[idx] || ''); return current; });
  }, []);

  const handleSaveAnnotation = useCallback(() => {
    if (activeAnnotIdx === null) return;
    setAnnotations(a => {
      const next = { ...a };
      if (annotText.trim()) next[activeAnnotIdx] = annotText.trim();
      else delete next[activeAnnotIdx];
      return next;
    });
    setActiveAnnotIdx(null);
    setAnnotText('');
  }, [activeAnnotIdx, annotText]);

  const handleRemoveAnnotation = useCallback((idx: number) => {
    setAnnotations(a => { const next = { ...a }; delete next[idx]; return next; });
  }, []);

  const handleWriteToSheet = useCallback(async () => {
    if (!result) return;
    setError(null);
    try {
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

      const sheetLabel = `SPC ${result.chart_type.toUpperCase()}`;
      const { sheetName, rangeAddress: ra } = await writeToNewSheet(sheetLabel, [finalCols, ...rows]);
      const { createSPCChart } = await import('../../excel/chart-builder');
      await createSPCChart(result, sheetName, ra);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to write to sheet.');
    }
  }, [result, annotations, rawData, hasHeaders, headers, includeDataTable]);

  const needsN = NEEDS_N.includes(chartType);
  const needsSubgroup = NEEDS_SUBGROUP.includes(chartType);
  const supportsGrain = GRAIN_CHARTS.includes(chartType);
  const isIndividual = supportsGrain && dataGrain === 'individual';
  const nLabel = ['u', 'up'].includes(chartType) ? 'Exposure' : 'Sample size';
  const nTooltip = ['u', 'up'].includes(chartType)
    ? 'Exposure units per period (e.g. catheter-days, patient-days). The chart divides your count by this to get a rate.'
    : 'Sample size per period (e.g. number of discharges). The chart divides your count by this to get a proportion.';
  const yTooltip = isIndividual
    ? (['p', 'pp', 'ip'].includes(chartType)
        ? 'Binary outcome: 1 if the event occurred, 0 if not. Do not pre-aggregate — the chart sums these per period.'
        : ['u', 'up'].includes(chartType)
          ? 'Defect or event count for this unit (often 0 or 1). The chart will sum per period and divide by unit count.'
          : 'Event count per row. Rows will be summed per period.')
    : undefined;
  const hasData = rawData.length > 1;
  const target = options.target ? parseFloat(options.target) : undefined;
  const allCols = headers.map((_, i) => i);
  const isDateX = xCol !== null && dateCols.includes(xCol);
  const xLabels = (result as any)?._xLabels as string[] | undefined;
  const partBoundaries = (result as any)?._partBoundaries as number[] | undefined;
  const partLabels = (result as any)?._partLabels as string[] | undefined;

  return (
    <div className={styles.panel}>
      {/* ── Data source ── */}
      {!rangeAddress ? (
        <div className={styles.dataSourceEmpty}>
          <div className={styles.dataSourceIcon}><DocumentRegular /></div>
          <Button appearance="primary" size="medium" onClick={handleSelectData}
            style={{ borderRadius: '6px', minWidth: '180px', backgroundColor: '#107C6C', borderColor: '#0A6B5C' }}>
            Use Current Selection
          </Button>
          <span className={styles.dataSourceHint}>Select a data range in Excel, then click above</span>
        </div>
      ) : (
        <div className={styles.section}>
          <div className={styles.sectionLabel}>Data Source</div>
          <div className={styles.dataSourceBar}>
            <span className={styles.address}>{rangeAddress}</span>
            <Button size="small" icon={<ArrowSyncRegular />} appearance="subtle"
              onClick={handleSelectData} title="Re-read selection" style={{ borderRadius: '6px' }} />
          </div>
          {hasData && (
            <button className={styles.settingsToggle} onClick={() => setPreviewOpen(o => !o)}
              style={{ marginTop: '8px' }}>
              {previewOpen ? <ChevronDownRegular style={{ fontSize: '12px' }} /> : <ChevronRightRegular style={{ fontSize: '12px' }} />}
              Data preview
            </button>
          )}
          {previewOpen && hasData && (
            <div style={{ marginTop: '8px' }}>
              <DataPreview data={rawData} hasHeaders={hasHeaders} />
            </div>
          )}
        </div>
      )}

      {/* ── Chart type ── */}
      {hasData && (
        <div className={styles.section}>
          <div className={styles.sectionLabel}>Chart Type</div>
          <div className={styles.chartTypeRow}>
            {CORE_CHARTS.map(ct => (
              <button
                key={ct}
                className={`${styles.chartBtn} ${chartType === ct ? styles.chartBtnActive : ''}`}
                onClick={() => { setChartType(ct); setMoreChartsOpen(false); }}
              >{ct}</button>
            ))}
            <button
              className={`${styles.chartBtnMore} ${ADDITIONAL_CHARTS.includes(chartType) ? styles.chartBtnActive : ''}`}
              onClick={() => setMoreChartsOpen(o => !o)}
            >{ADDITIONAL_CHARTS.includes(chartType) ? chartType : 'more\u2026'}</button>
          </div>
          {moreChartsOpen && (
            <div className={styles.chartMorePanel}>
              {ADDITIONAL_CHARTS.map(ct => (
                <button
                  key={ct}
                  className={`${styles.chartBtn} ${chartType === ct ? styles.chartBtnActive : ''}`}
                  onClick={() => { setChartType(ct); setMoreChartsOpen(false); }}
                >{ct}</button>
              ))}
            </div>
          )}
          {CHART_LABELS[chartType] && (
            <div style={{ fontSize: '11.5px', color: '#8e8e96', marginTop: '8px', fontStyle: 'italic' }}>
              {CHART_LABELS[chartType]}
            </div>
          )}
        </div>
      )}

      {/* ── Column mapping ── */}
      {hasData && (
        <div className={styles.section}>
          <div className={styles.sectionLabel}>Columns</div>

          {/* Data grain (attribute + count charts) */}
          {supportsGrain && (
            <div className={styles.colRow}>
              <span className={styles.colLabel} style={{ minWidth: '62px' }}>Each row is</span>
              <Select size="small" value={dataGrain}
                onChange={(_, d) => setDataGrain(d.value as 'summarized' | 'individual')}
                style={{ flex: 1 }}>
                <option value="summarized">Period summary</option>
                <option value="individual">Individual record</option>
              </Select>
            </div>
          )}

          {/* X */}
          <div className={styles.colRow}>
            <span className={styles.colLabel} style={{ minWidth: supportsGrain ? '62px' : undefined }}>X</span>
            <Select size="small" value={xCol !== null ? String(xCol) : ''}
              onChange={(_, d) => setXCol(d.value !== '' ? parseInt(d.value) : null)}
              style={{ flex: 1 }}>
              <option value="">— index</option>
              {allCols.map(ci => (
                <option key={ci} value={ci}>{headers[ci]}</option>
              ))}
            </Select>
          </div>

          {/* Y */}
          <div className={styles.colRow}>
            <span className={styles.colLabel} style={{ minWidth: supportsGrain ? '62px' : undefined }} title={yTooltip}>Y</span>
            <Select size="small" value={String(yCol)}
              onChange={(_, d) => setYCol(parseInt(d.value))} style={{ flex: 1 }}>
              {numericCols.map(ci => (
                <option key={ci} value={ci}>{headers[ci]}</option>
              ))}
            </Select>
          </div>

          {/* N (attribute charts, summarized mode only) */}
          {needsN && !isIndividual && (
            <div className={styles.colRow}>
              <span className={styles.colLabel} style={{ minWidth: '62px' }} title={nTooltip}>{nLabel}</span>
              <Select size="small" value={nCol !== null ? String(nCol) : ''}
                onChange={(_, d) => setNCol(d.value !== '' ? parseInt(d.value) : null)}
                style={{ flex: 1 }}>
                <option value="">— none</option>
                {numericCols.map(ci => (
                  <option key={ci} value={ci}>{headers[ci]}</option>
                ))}
              </Select>
            </div>
          )}

          {/* Date Subgroup (only when X is a date column) */}
          {isDateX && (
            <div className={styles.colRow}>
              <span className={styles.colLabel} style={{ minWidth: '62px' }}>Period</span>
              <Select size="small" value={xPeriod} onChange={(_, d) => setXPeriod(d.value)} style={{ flex: 1 }}>
                <option value="day">Day</option>
                <option value="week">Week</option>
                <option value="month">Month</option>
                <option value="quarter">Quarter</option>
                <option value="year">Year</option>
              </Select>
            </div>
          )}

          {/* Notes column */}
          <div className={styles.colRow} style={{ marginTop: '2px' }}>
            <span className={styles.colLabel} style={{ fontSize: '11px', color: '#9ca3af', minWidth: supportsGrain ? '62px' : undefined }}>Notes</span>
            <Select size="small" value={notesCol !== null ? String(notesCol) : ''}
              onChange={(_, d) => setNotesCol(d.value !== '' ? parseInt(d.value) : null)}
              style={{ flex: 1 }}>
              <option value="">— none</option>
              {allCols.map(ci => (
                <option key={ci} value={ci}>{headers[ci]}</option>
              ))}
            </Select>
          </div>
        </div>
      )}

      {/* ── Settings ── */}
      {hasData && (
        <div className={styles.section}>
          <button className={styles.settingsToggle} onClick={() => setSettingsOpen(o => !o)}>
            <SettingsRegular style={{ fontSize: '14px' }} />
            Settings
            {settingsOpen ? <ChevronDownRegular style={{ fontSize: '12px' }} /> : <ChevronRightRegular style={{ fontSize: '12px' }} />}
          </button>

          {settingsOpen && (
            <div className={styles.settingsPanel}>
              <div className={styles.settingRow}>
                <span className={styles.settingLabel}>Signal method</span>
                <Select size="small" value={options.method} onChange={setOpt('method')}>
                  <option value="anhoej">Anhoej</option>
                  <option value="ihi">IHI</option>
                  <option value="weco">WECO</option>
                  <option value="nelson">Nelson</option>
                </Select>
              </div>
              <div className={styles.settingRow}>
                <span className={styles.settingLabel}>Freeze at</span>
                <Input size="small" placeholder="e.g. 20" value={options.freeze} onChange={setOpt('freeze')} />
              </div>
              <div className={styles.settingRow}>
                <span className={styles.settingLabel}>Target line</span>
                <Input size="small" placeholder="value" value={options.target} onChange={setOpt('target')} />
              </div>
              {needsSubgroup && (
                <div className={styles.settingRow}>
                  <span className={styles.settingLabel}>Subgroup size</span>
                  <Input size="small" placeholder="2\u201325" value={options.subgroupN} onChange={setOpt('subgroupN')} />
                </div>
              )}
              <div className={styles.settingRow}>
                <span className={styles.settingLabel}>95% warning lines</span>
                <Checkbox checked={options.show95}
                  onChange={(_, d) => setOptions(o => ({ ...o, show95: !!d.checked }))} />
              </div>

              <div className={styles.divider} />

              <button className={styles.settingsToggle} onClick={() => setMoreOpen(o => !o)}>
                {moreOpen ? <ChevronDownRegular style={{ fontSize: '12px' }} /> : <ChevronRightRegular style={{ fontSize: '12px' }} />}
                More options
              </button>

              {moreOpen && (
                <>
                  <div className={styles.settingRow}>
                    <span className={styles.settingLabel}>Part boundaries</span>
                    <Input size="small" placeholder="e.g. 10, 20" value={options.part} onChange={setOpt('part')} />
                  </div>
                  <div className={styles.settingRow}>
                    <span className={styles.settingLabel}>Part labels</span>
                    <Input size="small" placeholder="e.g. Pre, Post" value={options.partLabels} onChange={setOpt('partLabels')} />
                  </div>
                  <div className={styles.settingRow}>
                    <span className={styles.settingLabel}>Exclude points</span>
                    <Input size="small" placeholder="e.g. 3, 7" value={options.exclude} onChange={setOpt('exclude')} />
                  </div>
                  <div className={styles.settingRow}>
                    <span className={styles.settingLabel}>CL override</span>
                    <Input size="small" placeholder="value" value={options.clOverride} onChange={setOpt('clOverride')} />
                  </div>
                  <div className={styles.settingRow}>
                    <span className={styles.settingLabel}>Multiply</span>
                    <Input size="small" placeholder="1" value={options.multiply} onChange={setOpt('multiply')} />
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Error ── */}
      {error && <div className={styles.error}>{error}</div>}

      {/* ── Chart ── */}
      {result ? (
        <>
          <div style={{ padding: '8px 16px 0' }}>
            <ChartViewer
              result={result}
              type="spc"
              annotations={annotations}
              onPointClick={handlePointClick}
              target={target}
              xLabels={xLabels}
              show95={options.show95}
              partBoundaries={partBoundaries}
              partLabels={partLabels}
              chartType={chartType}
            />
          </div>

          {/* Annotation input */}
          {activeAnnotIdx !== null && (
            <div className={styles.annotBar} style={{ marginTop: '8px' }}>
              <span className={styles.annotBarLabel}>Pt {activeAnnotIdx + 1}</span>
              <Input size="small" style={{ flex: 1 }} placeholder="Add a note\u2026"
                value={annotText} onChange={(_, d) => setAnnotText(d.value)}
                onKeyDown={e => { if (e.key === 'Enter') handleSaveAnnotation(); if (e.key === 'Escape') setActiveAnnotIdx(null); }}
                autoFocus />
              <Button size="small" appearance="primary" onClick={handleSaveAnnotation} style={{ borderRadius: '6px' }}>Save</Button>
              <Button size="small" appearance="subtle" onClick={() => setActiveAnnotIdx(null)} style={{ borderRadius: '6px' }}>\u2715</Button>
            </div>
          )}

          {/* Annotation list */}
          {Object.keys(annotations).length > 0 && (
            <div className={styles.annotList} style={{ marginTop: '8px' }}>
              {Object.entries(annotations).sort(([a], [b]) => parseInt(a) - parseInt(b)).map(([idx, text]) => (
                <div key={idx} className={styles.annotItem}>
                  <span style={{ fontWeight: '600', color: '#7a5c1e', fontSize: '11px' }}>{parseInt(idx) + 1}</span>
                  <span className={styles.annotItemText}>{text}</span>
                  <Button size="small" appearance="transparent" onClick={() => handleRemoveAnnotation(parseInt(idx))}
                    style={{ minWidth: '24px', padding: '2px' }}>\u2715</Button>
                </div>
              ))}
            </div>
          )}

          {/* Summary */}
          <div style={{ padding: '0 16px', marginTop: '8px' }}>
            <button className={styles.settingsToggle} onClick={() => setSummaryOpen(o => !o)}>
              {summaryOpen ? <ChevronDownRegular style={{ fontSize: '12px' }} /> : <ChevronRightRegular style={{ fontSize: '12px' }} />}
              Analysis summary
            </button>
            {summaryOpen && (
              <div style={{ marginTop: '8px', padding: '10px', backgroundColor: '#f6f6f8', borderRadius: '6px', border: '1px solid #e8e6e3' }}>
                <div style={{
                  display: 'inline-flex', alignItems: 'center', padding: '4px 10px', borderRadius: '4px',
                  fontSize: '12px', fontWeight: '600', marginBottom: '10px',
                  backgroundColor: result.signals ? '#fdf2f2' : '#e8f5f2',
                  color: result.signals ? '#c4314b' : '#107C6C',
                }}>
                  {result.signals ? '\u26a0\ufe0f Signal detected' : '\u2713 No signal'}
                </div>
                <div className={styles.summaryTable}>
                  <div className={styles.summaryItem}>
                    <div className={styles.summaryKey}>Observations</div>
                    <div className={styles.summaryVal}>{result.summary.n_obs ?? '—'}</div>
                  </div>
                  <div className={styles.summaryItem}>
                    <div className={styles.summaryKey}>Method</div>
                    <div className={styles.summaryVal}>{result.method}</div>
                  </div>
                  {result.summary.longest_run !== undefined && (
                    <>
                      <div className={styles.summaryItem}>
                        <div className={styles.summaryKey}>Longest run</div>
                        <div className={styles.summaryVal}>{result.summary.longest_run} (lim {result.summary.run_threshold})</div>
                      </div>
                      <div className={styles.summaryItem}>
                        <div className={styles.summaryKey}>Crossings</div>
                        <div className={styles.summaryVal}>{result.summary.n_crossings} (lim {result.summary.crossings_threshold})</div>
                      </div>
                    </>
                  )}
                  {result.summary.weco_rules_triggered && (
                    <div className={styles.summaryItem} style={{ gridColumn: '1 / -1' }}>
                      <div className={styles.summaryKey}>WECO rules triggered</div>
                      <div className={styles.summaryVal}>
                        {result.summary.weco_rules_triggered.length > 0 ? result.summary.weco_rules_triggered.join(', ') : 'None'}
                      </div>
                    </div>
                  )}
                  {result.summary.nelson_rules_triggered && (
                    <div className={styles.summaryItem} style={{ gridColumn: '1 / -1' }}>
                      <div className={styles.summaryKey}>Nelson rules triggered</div>
                      <div className={styles.summaryVal}>
                        {result.summary.nelson_rules_triggered.length > 0 ? result.summary.nelson_rules_triggered.join(', ') : 'None'}
                      </div>
                    </div>
                  )}
                  {result.data[0] && !isNaN(result.data[0].cl) && (
                    <>
                      <div className={styles.summaryItem}>
                        <div className={styles.summaryKey}>CL</div>
                        <div className={styles.summaryVal}>{result.data[0].cl.toFixed(3)}</div>
                      </div>
                      <div className={styles.summaryItem}>
                        <div className={styles.summaryKey}>UCL</div>
                        <div className={styles.summaryVal}>{isNaN(result.data[0].ucl) ? '—' : result.data[0].ucl.toFixed(3)}</div>
                      </div>
                    </>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Write actions */}
          <div className={styles.actions}>
            <Checkbox label="Include source data" checked={includeDataTable}
              onChange={(_, d) => setIncludeDataTable(!!d.checked)} />
            <Button appearance="primary" icon={<ArrowDownloadRegular />}
              onClick={handleWriteToSheet} style={{ borderRadius: '6px', backgroundColor: '#107C6C', borderColor: '#0A6B5C' }}>
              Write to Sheet
            </Button>
          </div>
        </>
      ) : hasData ? (
        <div className={styles.emptyChart}>Computing chart\u2026</div>
      ) : null}
    </div>
  );
};
