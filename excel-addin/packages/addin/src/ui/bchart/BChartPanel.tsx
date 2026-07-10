import React, { useState, useCallback } from 'react';
import { Button, Select, Input, makeStyles } from '@fluentui/react-components';
import { DocumentRegular, ArrowSyncRegular, ArrowDownloadRegular } from '@fluentui/react-icons';
import { bchart } from '@qikit/engine';
import { colLetter } from '../shared/col-letter';
import { qikit } from '../../theme/tokens';
import { getSelectedRangeValues, writeToNewSheet } from '../../excel/excel-io';
import {
  Chart as ChartJS, CategoryScale, LinearScale,
  PointElement, LineElement, Tooltip, Legend,
} from 'chart.js';
import { Line } from 'react-chartjs-2';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend);

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
  settingRow: {
    display: 'grid',
    gridTemplateColumns: '100px 1fr',
    alignItems: 'center',
    gap: '8px',
  },
  settingLabel: {
    fontSize: '12px',
    color: qikit.color.text,
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
  signalBadge: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '6px',
    padding: '6px 10px',
    margin: '0 16px 8px',
    borderRadius: qikit.radius.sm,
    fontSize: '12px',
    fontWeight: '600',
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

export const BChartPanel: React.FC = () => {
  const styles = useStyles();
  const [rangeAddress, setRangeAddress] = useState<string | null>(null);
  const [rawData, setRawData] = useState<any[][]>([]);
  const [headers, setHeaders] = useState<string[]>([]);
  const [hasHeaders, setHasHeaders] = useState(false);
  const [xCol, setXCol] = useState<number>(0);
  const [targetStr, setTargetStr] = useState('');
  const [orRatioStr, setOrRatioStr] = useState('2.0');
  const [limitStr, setLimitStr] = useState('3.5');
  const [result, setResult] = useState<ReturnType<typeof bchart> | null>(null);
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
      const values = rows.map(row => Number(row[xCol])).filter(v => !isNaN(v));
      if (values.length === 0) throw new Error('No numeric values found in selected column.');
      const target = targetStr ? parseFloat(targetStr) : undefined;
      const or_ratio = parseFloat(orRatioStr) || 2.0;
      const limit = parseFloat(limitStr) || 3.5;
      setResult(bchart({ x: values, target, or_ratio, limit }));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Computation failed.');
      setResult(null);
    }
  }, [rawData, hasHeaders, xCol, targetStr, orRatioStr, limitStr]);

  React.useEffect(() => {
    if (rawData.length > 1) handleCompute();
  }, [xCol, rawData, targetStr, orRatioStr, limitStr]);

  const handleWriteToSheet = useCallback(async () => {
    if (!result) return;
    setError(null);
    try {
      const sheetData = [
        ['Point', 'Value', 'CUSUM Up', 'CUSUM Down', 'Signal Up', 'Signal Down', 'Limit'],
        ...result.data.map((d: any) => [d.x, d.y, d.cusum_up, d.cusum_down, d.signal_up ? 1 : 0, d.signal_down ? 1 : 0, d.limit]),
      ];
      const { sheetName, rangeAddress: ra } = await writeToNewSheet('CUSUM', sheetData);
      const { createBChartChart } = await import('../../excel/chart-builder');
      await createBChartChart(result, sheetName, ra);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to write to sheet.');
    }
  }, [result]);

  const hasData = rawData.length > 1;
  const anySignal = result?.data.some((d: any) => d.signal_up || d.signal_down);

  return (
    <div className={styles.panel}>
      {!rangeAddress ? (
        <div className={styles.dataSourceEmpty}>
          <div className={styles.dataSourceIcon}><DocumentRegular /></div>
          <Button appearance="primary" size="medium" onClick={handleSelectData}
            style={{ borderRadius: '6px', minWidth: '180px' }}>
            Use Current Selection
          </Button>
          <span className={styles.dataSourceHint}>Select a column of binary (0/1) outcomes</span>
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
        <>
          <div className={styles.section}>
            <div className={styles.sectionLabel}>Data Column</div>
            <div className={styles.colRow}>
              <span className={styles.colLabel}>Column</span>
              <Select size="small" value={String(xCol)}
                onChange={(_, d) => setXCol(parseInt(d.value))}
                style={{ flex: 1 }}>
                {headers.map((h, i) => <option key={i} value={i}>{h}</option>)}
              </Select>
            </div>
          </div>
          <div className={styles.section}>
            <div className={styles.sectionLabel}>Parameters</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div className={styles.settingRow}>
                <span className={styles.settingLabel}>Baseline risk</span>
                <Input size="small" placeholder="auto" value={targetStr}
                  onChange={(_, d) => setTargetStr(d.value)} />
              </div>
              <div className={styles.settingRow}>
                <span className={styles.settingLabel}>Odds ratio</span>
                <Input size="small" placeholder="2.0" value={orRatioStr}
                  onChange={(_, d) => setOrRatioStr(d.value)} />
              </div>
              <div className={styles.settingRow}>
                <span className={styles.settingLabel}>Decision limit</span>
                <Input size="small" placeholder="3.5" value={limitStr}
                  onChange={(_, d) => setLimitStr(d.value)} />
              </div>
            </div>
          </div>
        </>
      )}

      {error && <div className={styles.error}>{error}</div>}

      {result && (
        <>
          {anySignal !== undefined && (
            <div className={styles.signalBadge} style={{
              backgroundColor: anySignal ? qikit.color.dangerBg : qikit.color.brandTint,
              color: anySignal ? qikit.color.danger : qikit.color.brand,
            }}>
              {anySignal ? '⚑ Signal detected' : '✓ No signal'}
            </div>
          )}
          <div className={styles.chartContainer}>
            <Line
              data={{
                labels: result.data.map((d: any) => d.x),
                datasets: [
                  {
                    label: 'CUSUM Up',
                    data: result.data.map((d: any) => d.cusum_up),
                    borderColor: qikit.chart.brand,
                    pointBackgroundColor: result.data.map((d: any) => d.signal_up ? qikit.chart.signal : qikit.chart.brand),
                    pointRadius: result.data.map((d: any) => d.signal_up ? 5 : 2),
                    borderWidth: 1.5,
                    tension: 0,
                  },
                  {
                    label: 'CUSUM Down',
                    data: result.data.map((d: any) => d.cusum_down),
                    borderColor: qikit.chart.limit,
                    borderDash: [5, 3],
                    pointBackgroundColor: result.data.map((d: any) => d.signal_down ? qikit.chart.signal : qikit.chart.limit),
                    pointRadius: result.data.map((d: any) => d.signal_down ? 5 : 2),
                    borderWidth: 1.5,
                    tension: 0,
                  },
                  {
                    label: '+Limit',
                    data: new Array(result.data.length).fill(result.limit),
                    borderColor: qikit.chart.accent,
                    borderDash: [4, 4],
                    pointRadius: 0,
                    borderWidth: 1,
                  },
                  {
                    label: '\u2212Limit',
                    data: new Array(result.data.length).fill(-result.limit),
                    borderColor: qikit.chart.accent,
                    borderDash: [4, 4],
                    pointRadius: 0,
                    borderWidth: 1,
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
                  x: { grid: { display: false }, ticks: { font: { size: 10 }, color: qikit.chart.axisText } },
                  y: { grid: { color: qikit.chart.grid }, ticks: { font: { size: 10 }, color: qikit.chart.axisText } },
                },
              }}
            />
          </div>
          <div className={styles.actions}>
            <Button appearance="primary" icon={<ArrowDownloadRegular />}
              onClick={handleWriteToSheet} style={{ borderRadius: '6px', width: '100%' }}>
              Write to Sheet
            </Button>
          </div>
        </>
      )}
    </div>
  );
};
