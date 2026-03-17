import React, { useState, useEffect, useCallback } from 'react';
import {
  Button, Select, Input, Checkbox, makeStyles, tokens,
} from '@fluentui/react-components';
import { SettingsRegular, ArrowClockwiseRegular } from '@fluentui/react-icons';
import { ChartType, compute, SPCResult, SPCInput } from '@qikit/engine';
import { getSelectedRangeValues, writeToNewSheet } from '../../excel/excel-io';
import { ChartViewer } from '../shared/ChartViewer';

// ─── Chart type definitions ──────────────────────────────────────────────────

const CORE_CHARTS: ChartType[] = ['i', 'mr', 'xbar', 's', 'p', 'u', 'c', 'run'];
const ADDITIONAL_CHARTS: ChartType[] = ['g', 't', 'pp', 'up'];
const NEEDS_N: ChartType[] = ['p', 'u', 'pp', 'up'];
const NEEDS_SUBGROUP: ChartType[] = ['xbar', 's'];

const CHART_LABELS: Record<string, string> = {
  i:    'I – Individuals',
  mr:   'MR – Moving Range',
  xbar: 'Xbar – Subgroup Mean',
  s:    'S – Subgroup Std Dev',
  p:    'P – Proportion',
  u:    'U – Count per Unit',
  c:    'C – Count',
  run:  'Run – Median',
  g:    'G – Gap',
  t:    'T – Time Between Events',
  pp:   "PP – Laney P'",
  up:   "UP – Laney U'",
};

// ─── Types ───────────────────────────────────────────────────────────────────

interface SpcOptions {
  method: 'anhoej' | 'ihi' | 'weco' | 'nelson';
  freeze: string;
  target: string;
  part: string;
  exclude: string;
  clOverride: string;
  multiply: string;
  subgroupN: string;
}

const DEFAULT_OPTIONS: SpcOptions = {
  method: 'anhoej',
  freeze: '',
  target: '',
  part: '',
  exclude: '',
  clOverride: '',
  multiply: '',
  subgroupN: '',
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function parseColumns(rawData: any[][]): {
  hasHeaders: boolean;
  headers: string[];
  numericCols: number[];
} {
  if (rawData.length < 2) return { hasHeaders: false, headers: [], numericCols: [] };
  const firstRow = rawData[0];
  const hasHeaders = firstRow.some(v => typeof v === 'string' && String(v).trim() !== '');
  const dataRows = hasHeaders ? rawData.slice(1) : rawData;
  const headers = hasHeaders
    ? firstRow.map((h: any, i: number) => String(h || `Col${i + 1}`))
    : firstRow.map((_: any, i: number) => `Col${i + 1}`);
  const numericCols: number[] = [];
  for (let col = 0; col < headers.length; col++) {
    if (dataRows.some((row: any[]) => typeof row[col] === 'number')) {
      numericCols.push(col);
    }
  }
  return { hasHeaders, headers, numericCols };
}

// ─── Styles ──────────────────────────────────────────────────────────────────

const useStyles = makeStyles({
  panel: {
    display: 'flex',
    flexDirection: 'column',
    padding: '12px',
    gap: '10px',
    overflowY: 'auto',
    height: '100%',
    boxSizing: 'border-box',
  },
  row: {
    display: 'flex',
    gap: '8px',
    alignItems: 'center',
  },
  address: {
    flex: 1,
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground3,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    fontFamily: 'monospace',
  },
  chartTypeRow: {
    display: 'flex',
    gap: '6px',
    alignItems: 'center',
  },
  settingsPanel: {
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
    padding: '10px',
    backgroundColor: tokens.colorNeutralBackground2,
    borderRadius: '6px',
  },
  settingRow: {
    display: 'grid',
    gridTemplateColumns: '110px 1fr',
    alignItems: 'center',
    gap: '8px',
  },
  settingLabel: {
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground2,
  },
  moreToggle: {
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground3,
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    gap: '4px',
    userSelect: 'none',
    padding: '2px 0',
  },
  moreSection: {
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  },
  emptyChart: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    height: '180px',
    backgroundColor: tokens.colorNeutralBackground2,
    borderRadius: '4px',
    color: tokens.colorNeutralForeground4,
    fontSize: tokens.fontSizeBase200,
    textAlign: 'center',
    padding: '16px',
    boxSizing: 'border-box',
  },
  annotBar: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    padding: '6px 8px',
    backgroundColor: tokens.colorNeutralBackground2,
    borderRadius: '4px',
  },
  annotBarLabel: {
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground2,
    flexShrink: 0,
    whiteSpace: 'nowrap',
  },
  annotList: {
    display: 'flex',
    flexDirection: 'column',
    gap: '4px',
  },
  annotItem: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    padding: '4px 8px',
    backgroundColor: tokens.colorNeutralBackground2,
    borderRadius: '4px',
    fontSize: tokens.fontSizeBase200,
  },
  annotItemText: {
    flex: 1,
    color: tokens.colorNeutralForeground2,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  actions: {
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  },
  error: {
    padding: '6px 8px',
    backgroundColor: tokens.colorPaletteRedBackground1,
    color: tokens.colorPaletteRedForeground1,
    borderRadius: '4px',
    fontSize: tokens.fontSizeBase200,
  },
  colRow: {
    display: 'flex',
    gap: '8px',
    alignItems: 'center',
  },
  colLabel: {
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground2,
    flexShrink: 0,
    minWidth: '16px',
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
  const [yCol, setYCol] = useState<number>(0);
  const [nCol, setNCol] = useState<number | null>(null);

  // Chart
  const [chartType, setChartType] = useState<ChartType>('i');
  const [result, setResult] = useState<SPCResult | null>(null);

  // Annotations
  const [annotations, setAnnotations] = useState<Record<number, string>>({});
  const [activeAnnotIdx, setActiveAnnotIdx] = useState<number | null>(null);
  const [annotText, setAnnotText] = useState('');

  // UI
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
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
    if (parsed.numericCols.length > 0) setYCol(parsed.numericCols[0]);
    setNCol(null);
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
      const y: number[] = dataRows
        .map((row: any[]) => row[yCol])
        .filter(v => typeof v === 'number') as number[];

      if (y.length === 0) {
        setError('No numeric data in selected column.');
        setResult(null);
        return;
      }

      const needsN = NEEDS_N.includes(chartType);
      let n: number[] | undefined;
      if (needsN && nCol !== null) {
        const nVals = dataRows
          .filter((row: any[]) => typeof row[yCol] === 'number')
          .map((row: any[]) => row[nCol as number]);
        if (nVals.length === y.length && nVals.every(v => typeof v === 'number')) {
          n = nVals as number[];
        }
      }

      const input: SPCInput = {
        y,
        n,
        chart: chartType,
        method: options.method,
        freeze: options.freeze ? parseInt(options.freeze) : undefined,
        part: options.part
          ? options.part.split(',').map(s => parseInt(s.trim())).filter(v => !isNaN(v))
          : undefined,
        exclude: options.exclude
          ? options.exclude.split(',').map(s => parseInt(s.trim())).filter(v => !isNaN(v))
          : undefined,
        clOverride: options.clOverride ? parseFloat(options.clOverride) : undefined,
        multiply: options.multiply ? parseFloat(options.multiply) : undefined,
        subgroupN: options.subgroupN ? parseInt(options.subgroupN) : undefined,
      };

      setResult(compute(input));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Computation failed.');
      setResult(null);
    }
  }, [rawData, hasHeaders, chartType, yCol, nCol, options]);

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
    setAnnotText(prev => {
      // We need current annotations here, use functional form
      return '';
    });
    // Use the annotations ref pattern via setter
    setAnnotations(current => {
      setAnnotText(current[idx] || '');
      return current;
    });
  }, []);

  const handleSaveAnnotation = useCallback(() => {
    if (activeAnnotIdx === null) return;
    setAnnotations(a => {
      const next = { ...a };
      if (annotText.trim()) {
        next[activeAnnotIdx] = annotText.trim();
      } else {
        delete next[activeAnnotIdx];
      }
      return next;
    });
    setActiveAnnotIdx(null);
    setAnnotText('');
  }, [activeAnnotIdx, annotText]);

  const handleRemoveAnnotation = useCallback((idx: number) => {
    setAnnotations(a => {
      const next = { ...a };
      delete next[idx];
      return next;
    });
  }, []);

  const handleWriteToSheet = useCallback(async () => {
    if (!result) return;
    setError(null);
    try {
      const hasAnnot = Object.keys(annotations).length > 0;
      const cols = ['Point', 'Value', 'CL', 'UCL', 'LCL', 'Signal'];
      if (hasAnnot) cols.push('Note');

      const rows = result.data.map((d: any, i: number) => {
        const row: any[] = [
          i + 1,
          d.y,
          isNaN(d.cl) ? null : d.cl,
          isNaN(d.ucl) ? null : d.ucl,
          isNaN(d.lcl) ? null : d.lcl,
          (d.sigma_signal || d.runs_signal) ? 1 : null,
        ];
        if (hasAnnot) row.push(annotations[i] || null);
        return row;
      });

      const sheetLabel = `SPC ${result.chart_type.toUpperCase()}`;
      const { sheetName, rangeAddress: ra } = await writeToNewSheet(sheetLabel, [cols, ...rows]);
      const { createSPCChart } = await import('../../excel/chart-builder');
      await createSPCChart(result, sheetName, ra);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to write to sheet.');
    }
  }, [result, annotations]);

  const needsN = NEEDS_N.includes(chartType);
  const needsSubgroup = NEEDS_SUBGROUP.includes(chartType);
  const hasData = rawData.length > 1;
  const multiNumCols = numericCols.length > 1;
  const target = options.target ? parseFloat(options.target) : undefined;

  return (
    <div className={styles.panel}>
      {/* ── Data selection ── */}
      <div className={styles.row}>
        {rangeAddress ? (
          <>
            <span className={styles.address}>{rangeAddress}</span>
            <Button
              size="small"
              icon={<ArrowClockwiseRegular />}
              onClick={handleSelectData}
              title="Re-read selection"
            />
          </>
        ) : (
          <Button appearance="primary" size="small" onClick={handleSelectData} style={{ width: '100%' }}>
            Use Current Selection
          </Button>
        )}
      </div>

      {/* ── Column selectors ── */}
      {hasData && (multiNumCols || needsN) && (
        <div className={styles.colRow}>
          {multiNumCols && (
            <>
              <span className={styles.colLabel}>Y</span>
              <Select
                size="small"
                value={String(yCol)}
                onChange={(_, d) => setYCol(parseInt(d.value))}
                style={{ flex: 1 }}
              >
                {numericCols.map(ci => (
                  <option key={ci} value={ci}>{headers[ci] || `Col${ci + 1}`}</option>
                ))}
              </Select>
            </>
          )}
          {needsN && (
            <>
              <span className={styles.colLabel}>N</span>
              <Select
                size="small"
                value={nCol !== null ? String(nCol) : ''}
                onChange={(_, d) => setNCol(d.value !== '' ? parseInt(d.value) : null)}
                style={{ flex: 1 }}
              >
                <option value="">—</option>
                {numericCols.map(ci => (
                  <option key={ci} value={ci}>{headers[ci] || `Col${ci + 1}`}</option>
                ))}
              </Select>
            </>
          )}
        </div>
      )}

      {/* ── Chart type + settings ── */}
      <div className={styles.chartTypeRow}>
        <Select
          value={chartType}
          onChange={(_, d) => setChartType(d.value as ChartType)}
          size="small"
          style={{ flex: 1 }}
        >
          <optgroup label="Core">
            {CORE_CHARTS.map(ct => (
              <option key={ct} value={ct}>{CHART_LABELS[ct]}</option>
            ))}
          </optgroup>
          <optgroup label="Additional">
            {ADDITIONAL_CHARTS.map(ct => (
              <option key={ct} value={ct}>{CHART_LABELS[ct]}</option>
            ))}
          </optgroup>
        </Select>
        <Button
          size="small"
          icon={<SettingsRegular />}
          appearance={settingsOpen ? 'primary' : 'subtle'}
          onClick={() => setSettingsOpen(o => !o)}
          title="Settings"
        />
      </div>

      {/* ── Settings panel ── */}
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
              <Input size="small" placeholder="2–25" value={options.subgroupN} onChange={setOpt('subgroupN')} />
            </div>
          )}

          <div className={styles.moreToggle} onClick={() => setMoreOpen(o => !o)}>
            {moreOpen ? '▾' : '▸'} More
          </div>

          {moreOpen && (
            <div className={styles.moreSection}>
              <div className={styles.settingRow}>
                <span className={styles.settingLabel}>Part boundaries</span>
                <Input size="small" placeholder="e.g. 10, 20" value={options.part} onChange={setOpt('part')} />
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
            </div>
          )}
        </div>
      )}

      {/* ── Error ── */}
      {error && <div className={styles.error}>{error}</div>}

      {/* ── Chart + annotations ── */}
      {result ? (
        <>
          <ChartViewer
            result={result}
            type="spc"
            annotations={annotations}
            onPointClick={handlePointClick}
            target={target}
          />

          {/* Annotation input */}
          {activeAnnotIdx !== null && (
            <div className={styles.annotBar}>
              <span className={styles.annotBarLabel}>Pt {activeAnnotIdx + 1}:</span>
              <Input
                size="small"
                style={{ flex: 1 }}
                placeholder="note..."
                value={annotText}
                onChange={(_, d) => setAnnotText(d.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter') handleSaveAnnotation();
                  if (e.key === 'Escape') setActiveAnnotIdx(null);
                }}
                autoFocus
              />
              <Button size="small" appearance="primary" onClick={handleSaveAnnotation}>✓</Button>
              <Button size="small" appearance="subtle" onClick={() => setActiveAnnotIdx(null)}>✕</Button>
            </div>
          )}

          {/* Annotation list */}
          {Object.keys(annotations).length > 0 && (
            <div className={styles.annotList}>
              {Object.entries(annotations)
                .sort(([a], [b]) => parseInt(a) - parseInt(b))
                .map(([idx, text]) => (
                  <div key={idx} className={styles.annotItem}>
                    <span className={styles.annotItemText}>
                      Pt {parseInt(idx) + 1}: {text}
                    </span>
                    <Button
                      size="small"
                      appearance="subtle"
                      onClick={() => handleRemoveAnnotation(parseInt(idx))}
                    >✕</Button>
                  </div>
                ))}
            </div>
          )}

          {/* Write actions */}
          <div className={styles.actions}>
            <Checkbox
              label="Include data table"
              checked={includeDataTable}
              onChange={(_, d) => setIncludeDataTable(!!d.checked)}
            />
            <Button appearance="primary" onClick={handleWriteToSheet}>
              Write to Sheet
            </Button>
          </div>
        </>
      ) : (
        <div className={styles.emptyChart}>
          {hasData ? 'Select a chart type above' : 'Select data in Excel to begin'}
        </div>
      )}
    </div>
  );
};
