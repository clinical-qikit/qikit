import React, { useEffect, useState } from 'react';
import { FluentProvider, makeStyles, Button } from '@fluentui/react-components';
import { qikitLightTheme } from './theme/fluent-theme';
import { qikit } from './theme/tokens';
import { colLetter } from './ui/shared/col-letter';
import { subscribeLiveUpdateEvents } from './excel/live-update';

// ─── Mock Datasets ────────────────────────────────────────────────────────────

const DATASETS: Record<string, { label: string; values: any[][]; address: string }> = {
  continuous: {
    label: 'Individual Measurements',
    address: 'Sheet1!A1:B31',
    values: [
      ['Date', 'Value'],
      ['2024-01-02', 10.3], ['2024-01-03', 11.1], ['2024-01-04', 9.8], ['2024-01-05', 10.7],
      ['2024-01-08', 11.5], ['2024-01-09', 10.2], ['2024-01-10', 9.5], ['2024-01-11', 10.9],
      ['2024-01-12', 11.8], ['2024-01-15', 10.4], ['2024-01-16', 9.7], ['2024-01-17', 10.1],
      ['2024-01-18', 12.3], ['2024-01-19', 10.6], ['2024-01-22', 9.9], ['2024-01-23', 11.2],
      ['2024-01-24', 10.5], ['2024-01-25', 11.0], ['2024-01-26', 9.6], ['2024-01-29', 10.8],
      ['2024-01-30', 11.4], ['2024-01-31', 10.0], ['2024-02-01', 9.3], ['2024-02-02', 11.7],
      ['2024-02-05', 10.2], ['2024-02-06', 11.9], ['2024-02-07', 10.4], ['2024-02-08', 9.8],
      ['2024-02-09', 10.6], ['2024-02-12', 11.1],
    ],
  },
  subgroup: {
    label: 'Subgroup (p-chart)',
    address: 'Sheet1!A1:C21',
    values: [
      ['Sample', 'Defectives', 'Total'],
      [1, 3, 50], [2, 5, 50], [3, 2, 50], [4, 8, 50], [5, 4, 50],
      [6, 3, 50], [7, 6, 50], [8, 2, 50], [9, 5, 50], [10, 7, 50],
      [11, 4, 50], [12, 3, 50], [13, 9, 50], [14, 2, 50], [15, 5, 50],
      [16, 6, 50], [17, 3, 50], [18, 4, 50], [19, 7, 50], [20, 2, 50],
    ],
  },
  binary: {
    label: 'Binary Outcomes (CUSUM)',
    address: 'Sheet1!A1:B51',
    values: [
      ['Patient', 'Adverse Event'],
      ...(Array.from({ length: 50 }, (_, i) => [
        i + 1,
        // ~10% rate with a cluster of events mid-sequence (simulating a shift)
        (i < 20 ? (Math.sin(i * 7.3) > 0.8 ? 1 : 0) : i < 35 ? (Math.sin(i * 2.1) > 0.3 ? 1 : 0) : (Math.sin(i * 7.3) > 0.8 ? 1 : 0)) as number
      ]) as any[][]),
    ],
  },
  categorical: {
    label: 'Defect Categories (Pareto)',
    address: 'Sheet1!A1:B61',
    values: [
      ['Defect Type'],
      ...([
        'Surface scratch', 'Surface scratch', 'Dimensional', 'Surface scratch', 'Color variation',
        'Surface scratch', 'Dimensional', 'Surface scratch', 'Color variation', 'Surface scratch',
        'Weld defect', 'Surface scratch', 'Dimensional', 'Color variation', 'Surface scratch',
        'Weld defect', 'Surface scratch', 'Surface scratch', 'Dimensional', 'Color variation',
        'Surface scratch', 'Contamination', 'Surface scratch', 'Weld defect', 'Surface scratch',
        'Dimensional', 'Surface scratch', 'Color variation', 'Surface scratch', 'Contamination',
        'Surface scratch', 'Surface scratch', 'Weld defect', 'Surface scratch', 'Dimensional',
        'Surface scratch', 'Color variation', 'Surface scratch', 'Surface scratch', 'Contamination',
        'Dimensional', 'Surface scratch', 'Weld defect', 'Surface scratch', 'Color variation',
        'Surface scratch', 'Surface scratch', 'Dimensional', 'Packaging', 'Surface scratch',
        'Surface scratch', 'Color variation', 'Weld defect', 'Surface scratch', 'Dimensional',
        'Surface scratch', 'Contamination', 'Surface scratch', 'Color variation', 'Packaging',
      ].map(v => [v]) as any[][]),
    ],
  },
};

// Module-level active dataset key so the mock can read it without React
let _activeDataset = 'continuous';

// ─── Mutable workbook state ───────────────────────────────────────────────────
// Everything below models "the workbook" for the mock: a single source sheet
// (whichever mock dataset is active) plus whatever output sheets/bindings the
// add-in has created. It resets whenever the dev harness switches datasets.

interface OutputSheetState {
  values: any[][];
  address: string;
  charts: any[];
}

interface MockBindingRecord {
  id: string;
  address: string; // sheet-qualified, e.g. "Sheet1!A1:B31"
  getValues: () => any[][];
  handlers: Array<() => any>;
  poisoned?: boolean;
}

let sourceState: { values: any[][]; address: string };
const outputSheets = new Map<string, OutputSheetState>();
const mockBindings = new Map<string, MockBindingRecord>();
const settingsStore = new Map<string, string>();

function sourceSheetName(): string {
  return sourceState.address.split('!')[0];
}

function resetWorkbookState() {
  const dataset = DATASETS[_activeDataset];
  sourceState = { values: dataset.values.map(row => [...row]), address: dataset.address };
  outputSheets.clear();
  mockBindings.clear();
  settingsStore.clear();
}
resetWorkbookState();

function resolveStoreValues(address: string): () => any[][] {
  const sheetName = address.includes('!') ? address.split('!')[0].replace(/^'|'$/g, '') : sourceSheetName();
  if (sheetName === sourceSheetName()) return () => sourceState.values;
  return () => outputSheets.get(sheetName)?.values ?? [];
}

/** Bumps a value in the active source dataset and, for datasets where it changes the derived
 *  row count (a new date bucket, a new Pareto category), makes that kind of edit — so the dev
 *  harness can exercise both the in-place-update and row-count-change recompute paths. */
function mutateActiveDataset() {
  const values = sourceState.values;
  const rows = values.slice(1);
  if (rows.length === 0) return;
  const lastIdx = rows.length - 1;

  if (_activeDataset === 'continuous') {
    const [dateStr, val] = rows[lastIdx];
    const d = new Date(dateStr as string);
    d.setUTCDate(d.getUTCDate() + 40); // shifts into a new month bucket
    rows[lastIdx] = [d.toISOString().slice(0, 10), Number(((val as number) + 0.7).toFixed(1))];
  } else if (_activeDataset === 'subgroup') {
    const [sample, defectives, total] = rows[lastIdx];
    rows[lastIdx] = [sample, Math.min((defectives as number) + 2, (total as number)), total];
  } else if (_activeDataset === 'binary') {
    const [patient, event] = rows[lastIdx];
    rows[lastIdx] = [patient, event ? 0 : 1];
  } else if (_activeDataset === 'categorical') {
    rows[lastIdx] = [`New defect ${Date.now() % 1000}`]; // introduces a new Pareto category
  }

  sourceState.values = [values[0], ...rows];
}

function fireSourceBindingHandlers() {
  mockBindings.forEach(rec => {
    if (!rec.poisoned && rec.address.split('!')[0] === sourceSheetName()) {
      rec.handlers.forEach(h => h());
    }
  });
}

function poisonMostRecentBinding(): boolean {
  const ids = [...mockBindings.keys()];
  const lastId = ids[ids.length - 1];
  if (!lastId) return false;
  const rec = mockBindings.get(lastId)!;
  rec.poisoned = true;
  rec.handlers.forEach(h => h());
  return true;
}

// ─── Harness event log (visible feedback without opening devtools) ───────────

interface HarnessLogEntry { ts: number; text: string }
let harnessLog: HarnessLogEntry[] = [];
const harnessLogListeners = new Set<() => void>();

function logHarness(text: string) {
  harnessLog = [...harnessLog.slice(-4), { ts: Date.now(), text }];
  console.log('[Harness]', text);
  harnessLogListeners.forEach(l => l());
}

// ─── Excel / Office Mocks ────────────────────────────────────────────────────

function makeRange(store: { get(): any[][]; set(v: any[][]): void }, address: string) {
  return {
    load: () => {},
    get values() { return store.get(); },
    set values(v: any[][]) { store.set(v); },
    address,
    format: {
      font: { size: 11, bold: false },
      autofitColumns: () => {},
    },
    clear: () => {},
  };
}

function makeChart(ownerCharts?: any[]) {
  const chart: any = {
    title: { text: '', format: { font: { size: 13, bold: true, color: '' } } },
    top: 0, left: 0, width: 0, height: 0,
    legend: { visible: true, position: '' },
    axes: {
      valueAxis: { title: { text: '', format: { font: { size: 11 } } }, crossesAt: 0 },
      categoryAxis: { title: { text: '', format: { font: { size: 11 } } } },
      seriesAxis: { title: { text: '', format: { font: { size: 11 } } } },
    },
    series: {
      _items: [] as any[],
      getItemAt(i: number) { return this._items[i]; },
      add(name: string) {
        const s = {
          name,
          chartType: '',
          axisGroup: '',
          markerStyle: '',
          markerSize: 0,
          markerForegroundColor: '',
          markerBackgroundColor: '',
          format: {
            line: { color: '', dashStyle: '' },
            fill: { setSolidColor: () => {} },
          },
          setValues: () => {},
          setXAxisValues: () => {},
          delete: () => {
            const i = this._items.indexOf(s);
            if (i >= 0) this._items.splice(i, 1);
          },
        };
        this._items.push(s);
        return s;
      },
    },
    delete: () => {
      if (ownerCharts) {
        const i = ownerCharts.indexOf(chart);
        if (i >= 0) ownerCharts.splice(i, 1);
      }
    },
  };
  // Real Excel auto-creates a default series when a chart is added from a
  // range; chart-builder.ts immediately deletes it before adding its own.
  chart.series.add('Series1');
  return chart;
}

function ensureOutputSheet(name: string): OutputSheetState {
  if (!outputSheets.has(name)) {
    outputSheets.set(name, { values: [], address: `${name}!A1`, charts: [] });
  }
  return outputSheets.get(name)!;
}

function makeSheet(name: string) {
  const isSource = name === sourceSheetName();
  const outState = isSource ? null : outputSheets.get(name);
  const exists = isSource || !!outState;

  const store = isSource
    ? { get: () => sourceState.values, set: (v: any[][]) => { sourceState.values = v; } }
    : { get: () => outState?.values ?? [], set: (v: any[][]) => { if (outState) outState.values = v; } };

  return {
    name,
    isNullObject: !exists,
    load: () => {},
    getRange: (addr?: string) => makeRange(store, isSource ? sourceState.address : `${name}!${addr ?? 'A1'}`),
    getRangeByIndexes: (_startRow: number, _startCol: number, rowCount: number, colCount: number) => {
      const addr = `${name}!A1:${colLetter(colCount - 1)}${rowCount}`;
      if (!isSource && outState) outState.address = addr;
      return makeRange(store, addr);
    },
    activate: () => {},
    charts: {
      get items() { return isSource ? [] : (outState?.charts ?? []); },
      load: () => {},
      add: () => {
        const target = isSource ? undefined : outState;
        const chart = makeChart(target?.charts);
        target?.charts.push(chart);
        return chart;
      },
    },
    delete: () => { if (!isSource) outputSheets.delete(name); },
  };
}

function buildMockContext() {
  const makeBindingObject = (rec: MockBindingRecord | undefined, id: string) => ({
    id,
    isNullObject: !rec,
    load: () => {},
    onDataChanged: {
      add: (handler: () => any) => {
        if (rec) rec.handlers.push(handler);
        return { remove: () => {} };
      },
    },
    getRange: () => {
      if (!rec || rec.poisoned) throw new Error("ItemNotFound: The requested resource doesn't exist.");
      return makeRange({ get: rec.getValues, set: () => {} }, rec.address);
    },
    delete: () => { if (rec) mockBindings.delete(id); },
  });

  return {
    workbook: {
      getSelectedRange: () => makeRange(
        { get: () => sourceState.values, set: (v: any[][]) => { sourceState.values = v; } },
        sourceState.address,
      ),
      worksheets: {
        get items() {
          return [sourceSheetName(), ...outputSheets.keys()].map(n => ({ name: n }));
        },
        load: () => {},
        add: (name: string) => { ensureOutputSheet(name); return makeSheet(name); },
        getItem: (name: string) => makeSheet(name),
        getItemOrNullObject: (name: string) => makeSheet(name),
        getActiveWorksheet: () => makeSheet(sourceSheetName()),
      },
      bindings: {
        add: (rangeOrAddress: any, _bindingType: any, id: string) => {
          const address = typeof rangeOrAddress === 'string' ? rangeOrAddress : (rangeOrAddress?.address ?? '');
          const rec: MockBindingRecord = { id, address, getValues: resolveStoreValues(address), handlers: [] };
          mockBindings.set(id, rec);
          return makeBindingObject(rec, id);
        },
        getItem: (id: string) => makeBindingObject(mockBindings.get(id), id),
        getItemOrNullObject: (id: string) => makeBindingObject(mockBindings.get(id), id),
      },
    },
    sync: async () => {},
  };
}

(window as any).Excel = {
  run: async (callback: (context: any) => Promise<any>) => {
    return callback(buildMockContext());
  },
  ChartType: {
    line: 'Line', barClustered: 'BarClustered', columnClustered: 'ColumnClustered',
    xyscatter: 'Scatter', xyscatterLines: 'ScatterLines',
  },
  ChartSeriesBy: { columns: 'Columns', rows: 'Rows' },
  ChartLegendPosition: { bottom: 'bottom', right: 'right', top: 'top' },
  ChartMarkerStyle: { none: 'none', circle: 'circle', triangle: 'triangle', diamond: 'diamond' },
  ChartLineDashStyle: { dash: 'dash', dot: 'dot', dashDot: 'dashDot', solid: 'solid' },
  ChartAxisGroup: { primary: 'primary', secondary: 'secondary' },
  BindingType: { range: 'Range', table: 'Table', text: 'Text' },
  ClearApplyTo: { all: 'All', contents: 'Contents', formats: 'Formats' },
};

(window as any).Office = {
  onReady: (callback: (info: any) => void) => {
    callback({ host: null, platform: 'PC' });
  },
  context: {
    document: {
      settings: {
        get: (key: string) => (settingsStore.has(key) ? settingsStore.get(key) : null),
        set: (key: string, value: string) => { settingsStore.set(key, value); },
        saveAsync: (cb: any) => cb(),
      },
    },
  },
};

// ─── Harness Styles ──────────────────────────────────────────────────────────

const useStyles = makeStyles({
  harness: {
    display: 'flex',
    flexDirection: 'column',
    height: '100vh',
    backgroundColor: qikit.color.shell,
  },
  toolbar: {
    padding: '6px 16px',
    backgroundColor: qikit.color.surface,
    borderBottom: `1px solid ${qikit.color.border}`,
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    flexWrap: 'wrap',
  },
  datasetSelect: {
    fontSize: '12px',
    border: `1px solid ${qikit.color.border}`,
    borderRadius: qikit.radius.md,
    padding: '4px 8px',
    color: qikit.color.text,
    backgroundColor: qikit.color.surfaceAlt,
    cursor: 'pointer',
  },
  datasetLabel: {
    fontSize: '11px',
    color: qikit.color.text,
  },
  toolbarLabel: {
    fontSize: '11px',
    fontWeight: '500',
    color: qikit.color.textMuted,
    letterSpacing: '0.3px',
    textTransform: 'uppercase',
  },
  logLine: {
    flexBasis: '100%',
    fontSize: '11px',
    fontFamily: qikit.font.mono,
    color: qikit.color.brand,
    padding: '2px 0 0',
  },
  content: {
    flex: 1,
    overflow: 'auto',
    display: 'flex',
    justifyContent: 'center',
    padding: '24px',
  },
  taskPaneEmulator: {
    width: '370px',
    height: '100%',
    backgroundColor: qikit.color.surface,
    borderRadius: qikit.radius.lg,
    boxShadow: '0 4px 24px rgba(0, 0, 0, 0.08), 0 1px 4px rgba(0, 0, 0, 0.04)',
    overflow: 'hidden',
    position: 'relative',
  },
});

// ─── Harness Component ───────────────────────────────────────────────────────

interface DevHarnessProps {
  children: React.ReactNode;
}

export const DevHarness: React.FC<DevHarnessProps> = ({ children }) => {
  const styles = useStyles();
  const [showHarness, setShowHarness] = useState(true);
  const [activeKey, setActiveKey] = useState(_activeDataset);
  const [lastLog, setLastLog] = useState<string | null>(null);

  useEffect(() => {
    const notify = () => {
      const last = harnessLog[harnessLog.length - 1];
      if (last) setLastLog(last.text);
    };
    harnessLogListeners.add(notify);
    return () => { harnessLogListeners.delete(notify); };
  }, []);

  useEffect(() => subscribeLiveUpdateEvents((event) => {
    if (event.type === 'updated') logHarness(`Live update: recomputed ${event.panel} → ${event.outputSheet}`);
    else if (event.type === 'recompute-error') logHarness(`Live update error (${event.panel}): ${event.message}`);
    else if (event.type === 'source-deleted') logHarness(`Live link removed (${event.panel}): source range gone`);
  }), []);

  const handleDatasetChange = (key: string) => {
    _activeDataset = key;
    resetWorkbookState();
    setActiveKey(key);
    logHarness(`Switched mock dataset to "${DATASETS[key].label}" — workbook state reset.`);
  };

  const handleEditSource = () => {
    mutateActiveDataset();
    fireSourceBindingHandlers();
    logHarness(`Edited source data (${sourceState.address}) — waiting for debounced recompute…`);
  };

  const handleSimulateDeleted = () => {
    const ok = poisonMostRecentBinding();
    logHarness(ok
      ? 'Simulated the most recently linked source range being deleted…'
      : 'No live update is registered yet — write a chart to sheet first.');
  };

  if (!showHarness) return <>{children}</>;

  return (
    <FluentProvider theme={qikitLightTheme}>
      <div className={styles.harness}>
        <div className={styles.toolbar}>
          <span className={styles.datasetLabel}>Mock data:</span>
          <select
            className={styles.datasetSelect}
            value={activeKey}
            onChange={e => handleDatasetChange(e.target.value)}
          >
            {Object.entries(DATASETS).map(([key, ds]) => (
              <option key={key} value={key}>{ds.label}</option>
            ))}
          </select>
          <Button size="small" appearance="secondary" onClick={handleEditSource}
            style={{ borderRadius: '6px' }}>
            Edit source data
          </Button>
          <Button size="small" appearance="secondary" onClick={handleSimulateDeleted}
            style={{ borderRadius: '6px' }}>
            Simulate source deleted
          </Button>
          <Button size="small" appearance="subtle" onClick={() => setShowHarness(false)}
            style={{ borderRadius: '6px' }}>
            Hide
          </Button>
          <span className={styles.toolbarLabel} style={{ marginLeft: 'auto' }}>Dev Harness — Excel Mock</span>
          {lastLog && <span className={styles.logLine}>{lastLog}</span>}
        </div>
        <div className={styles.content}>
          <div className={styles.taskPaneEmulator}>
            {children}
          </div>
        </div>
      </div>
    </FluentProvider>
  );
};
