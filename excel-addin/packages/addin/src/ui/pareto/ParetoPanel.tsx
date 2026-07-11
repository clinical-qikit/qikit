import React, { useState, useCallback } from 'react';
import { Button, Select, Spinner, makeStyles } from '@fluentui/react-components';
import { DocumentRegular, ArrowSyncRegular, ArrowDownloadRegular } from '@fluentui/react-icons';
import { paretochart } from '@qikit/engine';
import { getSelectedRangeValues, writeToNewSheet } from '../../excel/excel-io';
import { colLetter } from '../shared/col-letter';
import { qikit } from '../../theme/tokens';
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
    borderBottom: `1px solid ${qikit.color.border}`,
  },
  sectionLabel: {
    fontSize: '11px',
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: '0.6px',
    color: qikit.color.textMuted,
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
    borderRadius: qikit.radius.lg,
    backgroundColor: qikit.color.brandTint,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    color: qikit.color.brand,
    fontSize: '20px',
  },
  dataSourceHint: {
    fontSize: '12px',
    color: qikit.color.textMuted,
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
    fontFamily: qikit.font.mono,
    color: qikit.color.text,
    backgroundColor: qikit.color.surfaceAlt,
    padding: '6px 10px',
    borderRadius: qikit.radius.sm,
    border: `1px solid ${qikit.color.border}`,
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
    fontSize: '11.5px',
    fontWeight: '600',
    color: qikit.color.text,
    minWidth: '50px',
  },
  chartContainer: {
    height: '240px',
    padding: '8px 16px',
  },
  actions: {
    padding: '14px 16px',
    borderTop: `1px solid ${qikit.color.border}`,
    marginTop: 'auto',
  },
  error: {
    margin: '0 16px',
    padding: '8px 12px',
    backgroundColor: qikit.color.dangerBg,
    color: qikit.color.danger,
    borderRadius: qikit.radius.sm,
    border: `1px solid ${qikit.color.dangerBorder}`,
    fontSize: '12px',
    lineHeight: '1.4',
  },
});

export const ParetoPanel: React.FC = () => {
  const styles = useStyles();
  const [rangeAddress, setRangeAddress] = useState<string | null>(null);
  const [rawData, setRawData] = useState<any[][]>([]);
  const [headers, setHeaders] = useState<string[]>([]);
  const [hasHeaders, setHasHeaders] = useState(false);
  const [xCol, setXCol] = useState<number>(0);
  const [result, setResult] = useState<ReturnType<typeof paretochart> | null>(null);
  const [isWriting, setIsWriting] = useState(false);
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
    setIsWriting(true);
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
    } finally {
      setIsWriting(false);
    }
  }, [result]);

  const hasData = rawData.length > 1;

  return (
    <div className={styles.panel}>
      {!rangeAddress ? (
        <div className={styles.dataSourceEmpty}>
          <div className={styles.dataSourceIcon}><DocumentRegular /></div>
          <Button appearance="primary" size="medium" onClick={handleSelectData}
            style={{ borderRadius: '6px', minWidth: '180px' }}>
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
              onClick={handleSelectData} title="Re-read selection" aria-label="Re-read selection"
              style={{ borderRadius: '6px' }} />
          </div>
        </div>
      )}

      {hasData && (
        <div className={styles.section}>
          <div className={styles.sectionLabel}>Category Column</div>
          <div className={styles.colRow}>
            <label className={styles.colLabel} htmlFor="pareto-col">Column</label>
            <Select size="small" id="pareto-col" value={String(xCol)}
              onChange={(_, d) => setXCol(parseInt(d.value))}
              style={{ flex: 1 }}>
              {headers.map((h, i) => <option key={i} value={i}>{h}</option>)}
            </Select>
          </div>
        </div>
      )}

      {error && <div className={styles.error} role="alert">{error}</div>}

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
                    backgroundColor: qikit.chart.brand,
                    borderRadius: 3,
                    yAxisID: 'y',
                    order: 2,
                  },
                  {
                    type: 'line' as const,
                    label: 'Cumulative %',
                    data: result.data.map((d: any) => d.cum_percent),
                    borderColor: qikit.chart.accent,
                    pointBackgroundColor: qikit.chart.accent,
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
                  tooltip: { backgroundColor: qikit.color.ink, cornerRadius: 6, padding: 8 },
                },
                scales: {
                  y: {
                    display: true,
                    title: { display: true, text: 'Frequency', font: { size: 11 }, color: qikit.chart.axisText },
                    grid: { color: qikit.chart.grid },
                    ticks: { font: { size: 10 }, color: qikit.chart.axisText },
                  },
                  y2: {
                    display: true,
                    position: 'right' as const,
                    min: 0,
                    max: 105,
                    title: { display: true, text: 'Cumulative %', font: { size: 11 }, color: qikit.chart.accent },
                    grid: { display: false },
                    ticks: {
                      font: { size: 10 }, color: qikit.chart.accent,
                      callback: (v: any) => `${v}%`,
                    },
                  },
                  x: {
                    grid: { display: false },
                    ticks: { font: { size: 10 }, color: qikit.chart.axisText },
                  },
                },
              }}
            />
          </div>
          <div className={styles.actions}>
            <Button appearance="primary" disabled={isWriting}
              icon={isWriting ? <Spinner size="tiny" /> : <ArrowDownloadRegular />}
              onClick={handleWriteToSheet} style={{ borderRadius: '6px', width: '100%' }}>
              {isWriting ? 'Writing…' : 'Write to Sheet'}
            </Button>
          </div>
        </>
      )}
    </div>
  );
};
