import React, { useState } from 'react';
import {
  Button, makeStyles, Badge, Select,
} from '@fluentui/react-components';
import {
  CheckmarkCircleFilled, CircleRegular,
  ArrowLeftRegular, ArrowDownloadRegular, ArrowResetRegular,
} from '@fluentui/react-icons';
import { design, analyze, DOEDesign, DOEResult, DesignType } from '@qikit/engine';
import { getSelectedRangeValues, writeToNewSheet } from '../../excel/excel-io';
import { FactorEditor, Factor } from './FactorEditor';
import { ChartViewer } from '../shared/ChartViewer';
import { DesignConfigurator } from './DesignConfigurator';

const useStyles = makeStyles({
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    overflowY: 'auto',
  },

  // Stepper
  stepper: {
    display: 'flex',
    alignItems: 'center',
    gap: '0',
    padding: '16px 16px 0',
  },
  step: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    fontSize: '12px',
    color: '#9ca3af',
    fontWeight: '500',
  },
  stepActive: {
    color: '#4f46e5',
  },
  stepDone: {
    color: '#059669',
  },
  stepIcon: {
    fontSize: '18px',
    display: 'flex',
  },
  stepLine: {
    flex: 1,
    height: '1px',
    backgroundColor: '#e5e7eb',
    margin: '0 10px',
    minWidth: '16px',
  },
  stepLineActive: {
    backgroundColor: '#4f46e5',
  },

  // Content areas
  stepContent: {
    display: 'flex',
    flexDirection: 'column',
    gap: '16px',
    padding: '20px 16px',
    flex: 1,
  },
  stepTitle: {
    fontSize: '15px',
    fontWeight: '600',
    color: '#1a1a2e',
    letterSpacing: '-0.2px',
  },
  stepDescription: {
    fontSize: '13px',
    color: '#6b7280',
    lineHeight: '1.5',
  },

  // Design summary card
  designCard: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '14px 16px',
    backgroundColor: '#f0fdf4',
    borderRadius: '10px',
    border: '1px solid #bbf7d0',
  },
  designCardLabel: {
    fontSize: '13px',
    fontWeight: '500',
    color: '#166534',
  },

  // Chart type selector
  chartTypeRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  chartTypeLabel: {
    fontSize: '12px',
    color: '#6b7280',
    flexShrink: 0,
  },

  // Stats row
  statsRow: {
    display: 'flex',
    gap: '12px',
  },
  statBox: {
    flex: 1,
    padding: '8px 10px',
    backgroundColor: '#f9fafb',
    borderRadius: '8px',
    border: '1px solid #f0f1f3',
    textAlign: 'center' as const,
  },
  statValue: {
    fontSize: '14px',
    fontWeight: '600',
    color: '#1a1a2e',
  },
  statLabel: {
    fontSize: '10px',
    color: '#9ca3af',
    marginTop: '2px',
  },

  // Actions
  actions: {
    display: 'flex',
    gap: '8px',
    padding: '16px',
    borderTop: '1px solid #f0f1f3',
    marginTop: 'auto',
  },

  // Error
  error: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    margin: '0 16px',
    padding: '10px 12px',
    backgroundColor: '#fef2f2',
    color: '#dc2626',
    borderRadius: '8px',
    border: '1px solid #fecaca',
    fontSize: '12px',
    lineHeight: '1.4',
  },
});

type DoeChartType = 'effects' | 'run_order' | 'single_factor' | 'interaction' | 'dot_diagram';

const DOE_CHART_OPTIONS: { value: DoeChartType; label: string }[] = [
  { value: 'effects',       label: 'Effects' },
  { value: 'run_order',     label: 'Run Order' },
  { value: 'single_factor', label: 'Single Factor' },
  { value: 'interaction',   label: 'Interaction' },
  { value: 'dot_diagram',   label: 'Dot Diagram' },
];

const DESIGN_TYPE_LABELS: Record<DesignType, string> = {
  full_factorial: 'Full Factorial',
  fractional: 'Fractional Factorial',
  one_factor: 'OFAT',
};

export const DoeWizard: React.FC = () => {
  const styles = useStyles();
  const [step, setStep] = useState(1);
  const [factors, setFactors] = useState<Factor[]>([
    { name: 'A', low: '-1', high: '1' },
    { name: 'B', low: '-1', high: '1' }
  ]);
  const [designType, setDesignType] = useState<DesignType>('full_factorial');
  const [replicates, setReplicates] = useState(1);
  const [centerPoints, setCenterPoints] = useState(0);
  const [randomize, setRandomize] = useState<'none' | 'full'>('none');
  const [seed, setSeed] = useState(42);
  const [currentDesign, setCurrentDesign] = useState<DOEDesign | null>(null);
  const [result, setResult] = useState<DOEResult | null>(null);
  const [doeChartType, setDoeChartType] = useState<DoeChartType>('effects');
  const [error, setError] = useState<string | null>(null);

  const onGenerate = () => {
    setError(null);
    try {
      if (factors.length < 2) throw new Error("At least 2 factors are required.");
      if (factors.some(f => !f.name.trim() || isNaN(parseFloat(f.low)) || isNaN(parseFloat(f.high)))) {
        throw new Error("All factors must have valid names and numeric levels.");
      }
      const d = design({
        factors: factors.map(f => f.name),
        lows: factors.map(f => parseFloat(f.low)),
        highs: factors.map(f => parseFloat(f.high)),
        design_type: designType,
        replicates,
        center_points: centerPoints,
        randomize,
        seed,
      });
      setCurrentDesign(d);
      setStep(2);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate design.");
    }
  };

  const onWriteTemplate = async () => {
    setError(null);
    if (!currentDesign) return;
    try {
      const headers = ['RunOrder', ...currentDesign.factors, 'Response'];
      const rows = currentDesign.matrix.map(row => headers.map(h => row[h]));
      await writeToNewSheet(`DOE ${currentDesign.n_factors}F`, [headers, ...rows]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to write template.");
    }
  };

  const onReadResults = async () => {
    setError(null);
    try {
      const resData = await getSelectedRangeValues();
      const headers = resData.values[0];
      const respIdx = headers.indexOf('Response');
      if (respIdx === -1) throw new Error("No 'Response' column found. Include headers in your selection.");
      const response = resData.values.slice(1).map(row => row[respIdx]).filter(v => typeof v === 'number') as number[];
      if (currentDesign) {
        if (response.length !== currentDesign.n_runs) {
          throw new Error(`Expected ${currentDesign.n_runs} responses, found ${response.length}.`);
        }
        const res = analyze(currentDesign, response);
        setResult(res);
        setDoeChartType('effects');
        setStep(3);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to read or analyze results.");
    }
  };

  const onWriteResults = async () => {
    if (!result) return;
    setError(null);
    try {
      const sheetData = [
        ['Term', 'Effect', 'SS', '% Contribution'],
        ...result.effects.map(e => [e.term, e.effect, e.ss, e.pct_contribution]),
      ];
      const { sheetName, rangeAddress } = await writeToNewSheet(`DOE Effects`, sheetData);
      const { createEffectsChart } = await import('../../excel/chart-builder');
      await createEffectsChart(result, sheetName, rangeAddress);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to write results.");
    }
  };

  const onReset = () => {
    setStep(1);
    setFactors([
      { name: 'A', low: '-1', high: '1' },
      { name: 'B', low: '-1', high: '1' }
    ]);
    setDesignType('full_factorial');
    setReplicates(1);
    setCenterPoints(0);
    setRandomize('none');
    setSeed(42);
    setCurrentDesign(null);
    setResult(null);
    setError(null);
  };

  const stepLabels = ['Define', 'Run', 'Results'];

  const renderStepper = () => (
    <div className={styles.stepper}>
      {stepLabels.map((label, i) => {
        const num = i + 1;
        const isDone = step > num;
        const isActive = step === num;
        return (
          <React.Fragment key={num}>
            {i > 0 && (
              <div className={`${styles.stepLine} ${step > num ? styles.stepLineActive : ''}`} />
            )}
            <div className={`${styles.step} ${isActive ? styles.stepActive : ''} ${isDone ? styles.stepDone : ''}`}>
              <span className={styles.stepIcon}>
                {isDone ? <CheckmarkCircleFilled /> : <CircleRegular />}
              </span>
              {label}
            </div>
          </React.Fragment>
        );
      })}
    </div>
  );

  // Build chart data for non-effects DOE chart types
  const renderDoeChart = () => {
    if (!result) return null;
    if (doeChartType === 'effects') {
      return <ChartViewer result={result} type="doe" />;
    }
    // For other chart types, render inline with Chart.js directly
    return <DoeAltChart result={result} chartType={doeChartType} />;
  };

  return (
    <div className={styles.container}>
      {renderStepper()}

      {error && <div className={styles.error} style={{ marginTop: '12px' }}>{error}</div>}

      {step === 1 && (
        <>
          <div className={styles.stepContent}>
            <div>
              <div className={styles.stepTitle}>Define Factors</div>
              <div className={styles.stepDescription}>
                Set up the factors and levels for your experiment.
              </div>
            </div>
            <FactorEditor factors={factors} onChange={setFactors} />
            <DesignConfigurator
              nFactors={factors.length}
              designType={designType}
              replicates={replicates}
              centerPoints={centerPoints}
              randomize={randomize}
              seed={seed}
              onDesignTypeChange={setDesignType}
              onReplicatesChange={setReplicates}
              onCenterPointsChange={setCenterPoints}
              onRandomizeChange={setRandomize}
              onSeedChange={setSeed}
            />
          </div>
          <div className={styles.actions}>
            <Button appearance="primary" onClick={onGenerate} style={{ flex: 1, borderRadius: '8px' }}>
              Generate Design
            </Button>
          </div>
        </>
      )}

      {step === 2 && currentDesign && (
        <>
          <div className={styles.stepContent}>
            <div>
              <div className={styles.stepTitle}>Run Experiment</div>
              <div className={styles.stepDescription}>
                Write the template to a sheet, run your experiment, fill in the Response column, then read results back.
              </div>
            </div>

            <div className={styles.designCard}>
              <span className={styles.designCardLabel}>
                {DESIGN_TYPE_LABELS[currentDesign.design_type]}
                {currentDesign.n_replicates > 1 && ` · ${currentDesign.n_replicates}×`}
                {currentDesign.n_center_points > 0 && ` · ${currentDesign.n_center_points} center`}
              </span>
              <Badge appearance="tint" color="success" shape="rounded">
                {currentDesign.n_runs} runs
              </Badge>
            </div>

            <div style={{ display: 'flex', gap: '8px' }}>
              <Button
                icon={<ArrowDownloadRegular />}
                onClick={onWriteTemplate}
                style={{ flex: 1, borderRadius: '8px' }}
              >
                Write Template
              </Button>
              <Button
                appearance="primary"
                onClick={onReadResults}
                style={{ flex: 1, borderRadius: '8px' }}
              >
                Read Results
              </Button>
            </div>
          </div>
          <div className={styles.actions}>
            <Button
              icon={<ArrowLeftRegular />}
              appearance="subtle"
              onClick={() => setStep(1)}
              style={{ borderRadius: '8px' }}
            >
              Back
            </Button>
          </div>
        </>
      )}

      {step === 3 && result && (
        <>
          <div className={styles.stepContent}>
            <div>
              <div className={styles.stepTitle}>Analysis Results</div>
            </div>

            <div className={styles.statsRow}>
              <div className={styles.statBox}>
                <div className={styles.statValue}>{(result.r_squared * 100).toFixed(1)}%</div>
                <div className={styles.statLabel}>R²</div>
              </div>
              <div className={styles.statBox}>
                <div className={styles.statValue}>{(result.adj_r_squared * 100).toFixed(1)}%</div>
                <div className={styles.statLabel}>Adj. R²</div>
              </div>
              <div className={styles.statBox}>
                <div className={styles.statValue}>{result.grand_mean.toFixed(2)}</div>
                <div className={styles.statLabel}>Grand Mean</div>
              </div>
            </div>

            <div className={styles.chartTypeRow}>
              <span className={styles.chartTypeLabel}>View:</span>
              <Select
                size="small"
                value={doeChartType}
                onChange={(_, d) => setDoeChartType(d.value as DoeChartType)}
                style={{ flex: 1 }}
              >
                {DOE_CHART_OPTIONS.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </Select>
            </div>

            {renderDoeChart()}
          </div>
          <div className={styles.actions}>
            <Button
              appearance="primary"
              icon={<ArrowDownloadRegular />}
              onClick={onWriteResults}
              style={{ flex: 1, borderRadius: '8px' }}
            >
              Write to Sheet
            </Button>
            <Button
              icon={<ArrowResetRegular />}
              appearance="subtle"
              onClick={onReset}
              style={{ borderRadius: '8px' }}
            >
              Start Over
            </Button>
          </div>
        </>
      )}
    </div>
  );
};

// ─── Alternative DOE chart types ─────────────────────────────────────────────

import {
  Chart as ChartJS2, CategoryScale, LinearScale, PointElement,
  LineElement, BarElement, Tooltip, Legend,
} from 'chart.js';
import { Line as LineChart, Scatter as ScatterChart } from 'react-chartjs-2';

ChartJS2.register(CategoryScale, LinearScale, PointElement, LineElement, BarElement, Tooltip, Legend);

const BRAND = '#4f46e5';
const GRID_COLOR = '#f1f5f9';

interface DoeAltChartProps {
  result: DOEResult;
  chartType: DoeChartType;
}

const DoeAltChart: React.FC<DoeAltChartProps> = ({ result, chartType }) => {
  const [selectedFactor, setSelectedFactor] = useState(0);
  const [selectedPair, setSelectedPair] = useState<[number, number]>([0, 1]);
  const containerStyle: React.CSSProperties = { height: '220px', padding: '12px', boxSizing: 'border-box' };
  const factors = result.design.factors;

  const baseOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: { backgroundColor: '#1a1a2e', cornerRadius: 6, padding: 8 },
    },
  } as const;

  if (chartType === 'run_order') {
    const data = {
      datasets: [{
        label: 'Response',
        data: result.response.map((y, i) => ({ x: i + 1, y })),
        backgroundColor: BRAND,
        pointRadius: 4,
      }],
    };
    const opts = {
      ...baseOptions,
      scales: {
        x: { type: 'linear' as const, title: { display: true, text: 'Run Order', font: { size: 11 }, color: '#6b7280' }, grid: { display: false }, ticks: { font: { size: 10 }, color: '#9ca3af' } },
        y: { title: { display: true, text: 'Response', font: { size: 11 }, color: '#6b7280' }, grid: { color: GRID_COLOR }, ticks: { font: { size: 10 }, color: '#9ca3af' } },
      },
    };
    return <div style={containerStyle}><ScatterChart data={data} options={opts} /></div>;
  }

  if (chartType === 'single_factor') {
    // Mean response at low vs high for selected factor
    const fIdx = selectedFactor;
    const lows = result.design.matrix.filter(r => r[factors[fIdx]] === -1);
    const highs = result.design.matrix.filter(r => r[factors[fIdx]] === 1);
    const runOrders = result.design.matrix.map(r => r.RunOrder as number);
    const meanAt = (rows: any[]) => {
      const respVals = rows.map(r => result.response[runOrders.indexOf(r.RunOrder)]).filter(v => v !== undefined);
      return respVals.length ? respVals.reduce((a, b) => a + b, 0) / respVals.length : 0;
    };
    const data = {
      labels: [`${factors[fIdx]} Low`, `${factors[fIdx]} High`],
      datasets: [{ label: 'Mean Response', data: [meanAt(lows), meanAt(highs)], borderColor: BRAND, pointBackgroundColor: BRAND, pointRadius: 5, borderWidth: 2, tension: 0 }],
    };
    const opts = {
      ...baseOptions,
      plugins: { ...baseOptions.plugins, legend: { display: false } },
      scales: {
        x: { grid: { display: false }, ticks: { font: { size: 11 }, color: '#374151' } },
        y: { title: { display: true, text: 'Mean Response', font: { size: 11 }, color: '#6b7280' }, grid: { color: GRID_COLOR }, ticks: { font: { size: 10 }, color: '#9ca3af' } },
      },
    };
    return (
      <div>
        {factors.length > 1 && (
          <div style={{ padding: '0 12px 8px', display: 'flex', gap: '6px', alignItems: 'center' }}>
            <span style={{ fontSize: '11px', color: '#6b7280' }}>Factor:</span>
            <select
              value={selectedFactor}
              onChange={e => setSelectedFactor(parseInt(e.target.value))}
              style={{ fontSize: '12px', border: '1px solid #e5e7eb', borderRadius: '6px', padding: '2px 6px', color: '#374151' }}
            >
              {factors.map((f, i) => <option key={i} value={i}>{f}</option>)}
            </select>
          </div>
        )}
        <div style={containerStyle}><LineChart data={data} options={opts} /></div>
      </div>
    );
  }

  if (chartType === 'interaction') {
    // Interaction plot for selected factor pair
    const [fi, fj] = selectedPair;
    const runOrders = result.design.matrix.map(r => r.RunOrder as number);
    // Two lines: fj=low and fj=high, x-axis = fi level
    const getResp = (fiVal: number, fjVal: number) => {
      const rows = result.design.matrix.filter(r => r[factors[fi]] === fiVal && r[factors[fj]] === fjVal);
      const vals = rows.map(r => result.response[runOrders.indexOf(r.RunOrder)]).filter(v => v !== undefined);
      return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
    };
    const data = {
      labels: [`${factors[fi]} Low`, `${factors[fi]} High`],
      datasets: [
        { label: `${factors[fj]} Low`, data: [getResp(-1, -1), getResp(1, -1)], borderColor: BRAND, pointBackgroundColor: BRAND, pointRadius: 4, borderWidth: 2, tension: 0 },
        { label: `${factors[fj]} High`, data: [getResp(-1, 1), getResp(1, 1)], borderColor: '#f97316', pointBackgroundColor: '#f97316', pointRadius: 4, borderWidth: 2, tension: 0, borderDash: [4, 3] },
      ],
    };
    const pairs: [number, number][] = [];
    for (let i = 0; i < factors.length; i++) for (let j = i + 1; j < factors.length; j++) pairs.push([i, j]);
    const opts = {
      ...baseOptions,
      plugins: { ...baseOptions.plugins, legend: { display: true, labels: { font: { size: 10 }, boxWidth: 20 } } },
      scales: {
        x: { grid: { display: false }, ticks: { font: { size: 11 }, color: '#374151' } },
        y: { title: { display: true, text: 'Mean Response', font: { size: 11 }, color: '#6b7280' }, grid: { color: GRID_COLOR }, ticks: { font: { size: 10 }, color: '#9ca3af' } },
      },
    };
    return (
      <div>
        {pairs.length > 1 && (
          <div style={{ padding: '0 12px 8px', display: 'flex', gap: '6px', alignItems: 'center' }}>
            <span style={{ fontSize: '11px', color: '#6b7280' }}>Pair:</span>
            <select
              value={`${selectedPair[0]},${selectedPair[1]}`}
              onChange={e => { const [a, b] = e.target.value.split(',').map(Number); setSelectedPair([a, b]); }}
              style={{ fontSize: '12px', border: '1px solid #e5e7eb', borderRadius: '6px', padding: '2px 6px', color: '#374151' }}
            >
              {pairs.map(([a, b]) => <option key={`${a},${b}`} value={`${a},${b}`}>{factors[a]} × {factors[b]}</option>)}
            </select>
          </div>
        )}
        <div style={containerStyle}><LineChart data={data} options={opts as any} /></div>
      </div>
    );
  }

  if (chartType === 'dot_diagram') {
    const data = {
      datasets: [{
        label: 'Response',
        data: result.response.map((y, i) => ({ x: y, y: 0.5 + (i % 3) * 0.1 })),
        backgroundColor: BRAND + 'aa',
        pointRadius: 5,
      }],
    };
    const opts = {
      ...baseOptions,
      scales: {
        x: { title: { display: true, text: 'Response', font: { size: 11 }, color: '#6b7280' }, grid: { color: GRID_COLOR }, ticks: { font: { size: 10 }, color: '#9ca3af' } },
        y: { display: false, min: 0, max: 1 },
      },
    };
    return <div style={containerStyle}><ScatterChart data={data} options={opts} /></div>;
  }

  return null;
};
