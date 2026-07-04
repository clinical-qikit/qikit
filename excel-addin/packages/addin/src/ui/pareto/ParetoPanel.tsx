import React, { useState, useCallback } from 'react';
import { Button, Select, makeStyles } from '@fluentui/react-components';
import { DocumentRegular, ArrowSyncRegular, ArrowDownloadRegular } from '@fluentui/react-icons';
import { paretochart } from '@qikit/engine';
import { getSelectedRangeValues, writeToNewSheet } from '../../excel/excel-io';
import {
  Chart as ChartJS, CategoryScale, LinearScale, BarElement,
  PointElement, LineElement, Title, Tooltip, Legend,
} from 'chart.js';
import { Chart } from 'react-chartjs-2';

ChartJS.register(CategoryScale, LinearScale, BarElement, PointElement, LineElement, Title, Tooltip, Legend);

const useStyles = makeStyles({
  panel: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    overflowY: 'auto',
  },
  section: {
    padding: '14px 16px',
    borderBottom: '1px solid #f0f1f3',
  },
  sectionLabel: {
    fontSize: '11px',
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
    color: '#9ca3af',
    marginBottom: '10px',
  },
  dataSourceEmpty: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '10px',
    padding: '20px 16px',
    textAlign: 'center',
  },
  dataSourceIcon: {
    width: '40px',
    height: '40px',
    borderRadius: '10px',
    backgroundColor: '#f3f0ff',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    color: '#7c3aed',
    fontSize: '20px',
  },
  dataSourceHint: {
    fontSize: '12px',
    color: '#9ca3af',
    lineHeight: '1.4',
  },
  dataSourceBar: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  address: {
    flex: 1,
    fontSize: '12px',
    fontFamily: "'SF Mono', 'Cascadia Code', 'Consolas', monospace",
    color: '#6b7280',
    backgroundColor: '#f9fafb',
    padding: '6px 10px',
    borderRadius: '6px',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  colRow: {
    display: 'flex',
    gap: '10px',
    alignItems: 'center',
  },
  colLabel: {
    fontSize: '11px',
    fontWeight: '600',
    color: '#6b7280',
    minWidth: '50px',
  },
  chartContainer: {
    height: '240px',
    padding: '8px 16px',
  },
  actions: {
    padding: '14px 16px',
    borderTop: '1px solid #f0f1f3',
    marginTop: 'auto',
  },
  error: {
    margin: '0 16px',
    padding: '8px 12px',
    backgroundColor: '#fef2f2',
    color: '#dc2626',
    borderRadius: '8px',
    border: '1px solid #fecaca',
    fontSize: '12px',
  },
});

function colLetter(i: number): string {
  let r = '';
  let n = i;
  do { r = String.fromCharCode(65 + (n % 26)) + r; n = Math.floor(n / 26) - 1; } while (n >= 0);
  return r;
}

export const ParetoPanel: React.FC = () => {
  const styles = useStyles();
  const [rangeAddress, setRangeAddress] = useState<string | null>(null);
  const [rawData, setRawData] = useState<any[][]>([]);
  const [headers, setHeaders] = useState<string[]>([]);
  const [hasHeaders, setHasHeaders] = useState(false);
  const [xCol, setXCol] = useState<number>(0);
  const [result, setResult] = useState<ReturnType<typeof paretochart> | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSelectData = useCallback(async () => {
    setError(null);
    try {
      const res = await getSelectedRangeValues();
      const data = res.values;
      const firstRow = data[0];
      const hdr = firstRow.some(v => typeof v === 'string' && String(v).trim() !== '');
      setHasHeaders(hdr);
      setHeaders(hdr ? firstRow.map((h: any, i: number) => String(h || colLetter(i))) : firstRow.map((_: any, i: number) => colLetter(i)));
      setRawData(data);
      setRangeAddress(res.address);
      setXCol(0);
      setResult(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to read selection.');
    }
  }, []);

  const handleCompute = useCallback(() => {
    setError(null);
    try {
      const rows = hasHeaders ? rawData.slice(1) : rawData;
      const values = rows.map(row => String(row[xCol] ?? '')).filter(v => v !== '' && v !== 'null');
      if (values.length === 0) throw new Error('No values found in selected column.');
      setResult(paretochart({ x: values }));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Computation failed.');
    }
  }, [rawData, hasHeaders, xCol]);

  // Auto-compute when column changes
  React.useEffect(() => {
    if (rawData.length > 1) handleCompute();
  }, [xCol, rawData]);

  const handleWriteToSheet = useCallback(async () => {
    if (!result) return;
    setError(null);
    try {
      const sheetData = [
        ['Category', 'Count', 'Cumulative Sum', 'Cumulative %'],
        ...result.data.map((d: any) => [d.category, d.count, d.cum_sum, d.cum_percent]),
      ];
      const { sheetName, rangeAddress: ra } = await writeToNewSheet('Pareto', sheetData);
      const { createParetoChart } = await import('../../excel/chart-builder');
      await createParetoChart(result, sheetName, ra);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to write to sheet.');
    }
  }, [result]);

  const hasData = rawData.length > 1;

  return (
    <div className={styles.panel}>
      {!rangeAddress ? (
        <div className={styles.dataSourceEmpty}>
          <div className={styles.dataSourceIcon}><DocumentRegular /></div>
          <Button appearance="primary" size="medium" onClick={handleSelectData}
            style={{ borderRadius: '8px', minWidth: '180px' }}>
            Use Current Selection
          </Button>
          <span className={styles.dataSourceHint}>Select a column of categories in Excel</span>
        </div>
      ) : (
        <div className={styles.section}>
          <div className={styles.sectionLabel}>Data Source</div>
          <div className={styles.dataSourceBar}>
            <span className={styles.address}>{rangeAddress}</span>
            <Button size="small" icon={<ArrowSyncRegular />} appearance="subtle"
              onClick={handleSelectData} style={{ borderRadius: '6px' }} />
          </div>
        </div>
      )}

      {hasData && (
        <div className={styles.section}>
          <div className={styles.sectionLabel}>Category Column</div>
          <div className={styles.colRow}>
            <span className={styles.colLabel}>Column</span>
            <Select size="small" value={String(xCol)}
              onChange={(_, d) => setXCol(parseInt(d.value))}
              style={{ flex: 1 }}>
              {headers.map((h, i) => <option key={i} value={i}>{h}</option>)}
            </Select>
          </div>
        </div>
      )}

      {error && <div className={styles.error}>{error}</div>}

      {result && (
        <>
          <div className={styles.chartContainer}>
            <Chart
              type="bar"
              data={{
                labels: result.data.map((d: any) => d.category),
                datasets: [
                  {
                    type: 'bar' as const,
                    label: 'Count',
                    data: result.data.map((d: any) => d.count),
                    backgroundColor: '#4f46e5',
                    borderRadius: 3,
                    yAxisID: 'y',
                    order: 2,
                  },
                  {
                    type: 'line' as const,
                    label: 'Cumulative %',
                    data: result.data.map((d: any) => d.cum_percent),
                    borderColor: '#f97316',
                    pointBackgroundColor: '#f97316',
                    pointRadius: 3,
                    borderWidth: 2,
                    tension: 0,
                    yAxisID: 'y2',
                    order: 1,
                  },
                ],
              }}
              options={{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                  legend: { display: false },
                  tooltip: { backgroundColor: '#1a1a2e', cornerRadius: 6, padding: 8 },
                },
                scales: {
                  y: {
                    display: true,
                    title: { display: true, text: 'Frequency', font: { size: 11 }, color: '#6b7280' },
                    grid: { color: '#f1f5f9' },
                    ticks: { font: { size: 10 }, color: '#9ca3af' },
                  },
                  y2: {
                    display: true,
                    position: 'right' as const,
                    min: 0,
                    max: 105,
                    title: { display: true, text: 'Cumulative %', font: { size: 11 }, color: '#f97316' },
                    grid: { display: false },
                    ticks: {
                      font: { size: 10 }, color: '#f97316',
                      callback: (v: any) => `${v}%`,
                    },
                  },
                  x: {
                    grid: { display: false },
                    ticks: { font: { size: 10 }, color: '#9ca3af' },
                  },
                },
              }}
            />
          </div>
          <div className={styles.actions}>
            <Button appearance="primary" icon={<ArrowDownloadRegular />}
              onClick={handleWriteToSheet} style={{ borderRadius: '8px', width: '100%' }}>
              Write to Sheet
            </Button>
          </div>
        </>
      )}
    </div>
  );
};
