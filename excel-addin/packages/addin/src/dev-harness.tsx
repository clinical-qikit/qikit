import React, { useState } from 'react';
import { FluentProvider, makeStyles, Button } from '@fluentui/react-components';
import { qikitLightTheme } from './theme/fluent-theme';

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

// ─── Excel / Office Mocks ────────────────────────────────────────────────────

function buildMockContext() {
  const dataset = DATASETS[_activeDataset];

  const makeRange = (values: any[][], address: string) => ({
    load: () => {},
    values,
    address,
    format: {
      font: { size: 11, bold: false },
      autofitColumns: () => {},
    },
  });

  const makeChart = () => ({
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
          delete: () => {},
        };
        this._items.push(s);
        return s;
      },
    },
  });

  const makeSheet = (name: string) => {
    const dr = makeRange(dataset.values, dataset.address);
    return {
      name,
      getRange: () => dr,
      getRangeByIndexes: () => dr,
      activate: () => {},
      charts: {
        add: () => makeChart(),
      },
    };
  };

  return {
    workbook: {
      getSelectedRange: () => makeRange(dataset.values, dataset.address),
      worksheets: {
        items: [],
        load: () => {},
        add: (name: string) => makeSheet(name),
        getItem: (name: string) => makeSheet(name),
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
};

(window as any).Office = {
  onReady: (callback: (info: any) => void) => {
    callback({ host: null, platform: 'PC' });
  },
  context: {
    document: {
      settings: {
        get: () => null,
        set: () => {},
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
    backgroundColor: '#e8eaed',
  },
  toolbar: {
    padding: '6px 16px',
    backgroundColor: '#ffffff',
    borderBottom: '1px solid #e0e3e8',
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  datasetSelect: {
    fontSize: '12px',
    border: '1px solid #e5e7eb',
    borderRadius: '6px',
    padding: '4px 8px',
    color: '#374151',
    backgroundColor: '#f9fafb',
    cursor: 'pointer',
  },
  datasetLabel: {
    fontSize: '11px',
    color: '#6b7280',
  },
  toolbarLabel: {
    flex: 1,
    textAlign: 'right',
    fontSize: '11px',
    fontWeight: '500',
    color: '#9ca3af',
    letterSpacing: '0.3px',
    textTransform: 'uppercase',
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
    backgroundColor: '#ffffff',
    borderRadius: '12px',
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

  const handleDatasetChange = (key: string) => {
    _activeDataset = key;
    setActiveKey(key);
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
          <Button size="small" appearance="subtle" onClick={() => setShowHarness(false)}
            style={{ borderRadius: '6px', marginLeft: '8px' }}>
            Hide
          </Button>
          <span className={styles.toolbarLabel}>Dev Harness — Excel Mock</span>
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
