import React, { useState } from 'react';
import {
  Button, makeStyles, Badge, Select, Spinner,
} from '@fluentui/react-components';
import {
  CheckmarkCircleFilled, CircleRegular,
  ArrowLeftRegular, ArrowDownloadRegular, ArrowResetRegular,
} from '@fluentui/react-icons';
import { design, analyze, DOEDesign, DOEResult, DesignType } from '@qikit/engine';
import { qikit } from '../../theme/tokens';
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
    color: qikit.color.textMuted,
    fontWeight: '500',
  },
  stepActive: {
    color: qikit.color.brand,
  },
  stepDone: {
    color: qikit.color.brand,
  },
  stepIcon: {
    fontSize: '18px',
    display: 'flex',
  },
  stepLine: {
    flex: 1,
    height: '1px',
    backgroundColor: qikit.color.border,
    margin: '0 10px',
    minWidth: '16px',
  },
  stepLineActive: {
    backgroundColor: qikit.color.brand,
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
    color: qikit.color.ink,
    letterSpacing: '-0.2px',
  },
  stepDescription: {
    fontSize: '13px',
    color: qikit.color.text,
    lineHeight: '1.5',
  },

  // Design summary card
  designCard: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '14px 16px',
    backgroundColor: qikit.color.brandTint,
    borderRadius: qikit.radius.lg,
    border: `1px solid ${qikit.color.brandTintBorder}`,
  },
  designCardLabel: {
    fontSize: '13px',
    fontWeight: '500',
    color: qikit.color.brand,
  },

  // Chart type selector
  chartTypeRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  chartTypeLabel: {
    fontSize: '12px',
    color: qikit.color.text,
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
    backgroundColor: qikit.color.surfaceAlt,
    borderRadius: qikit.radius.md,
    border: `1px solid ${qikit.color.borderSubtle}`,
    textAlign: 'center' as const,
  },
  statValue: {
    fontSize: '14px',
    fontWeight: '600',
    color: qikit.color.ink,
  },
  statLabel: {
    fontSize: '10px',
    color: qikit.color.textMuted,
    marginTop: '2px',
  },

  // Actions
  actions: {
    display: 'flex',
    gap: '8px',
    padding: '16px',
    borderTop: `1px solid ${qikit.color.border}`,
    marginTop: 'auto',
  },

  // Error
  error: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    margin: '0 16px',
    padding: '10px 12px',
    backgroundColor: qikit.color.dangerBg,
    color: qikit.color.danger,
    borderRadius: qikit.radius.sm,
    border: `1px solid ${qikit.color.dangerBorder}`,
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
  const [isWriting, setIsWriting] = useState(false);
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
    setIsWriting(true);
    try {
      const headers = ['RunOrder', ...currentDesign.factors, 'Response'];
      const rows = currentDesign.matrix.map(row => headers.map(h => row[h]));
      await writeToNewSheet(`DOE ${currentDesign.n_factors}F`, [headers, ...rows]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to write template.");
    } finally {
      setIsWriting(false);
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
          throw new Error(
            `The design has ${currentDesign.n_runs} runs but the selection contains ` +
            `${response.length} numeric response value${response.length === 1 ? '' : 's'}. ` +
            `Select the filled-in Response column (with its header) — one value per run.`
          );
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
    setIsWriting(true);
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
    } finally {
      setIsWriting(false);
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

      {error && <div className={styles.error} role="alert" style={{ marginTop: '12px' }}>{error}</div>}

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
            <Button appearance="primary" onClick={onGenerate} style={{ flex: 1, borderRadius: '6px' }}>
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
              <Badge appearance="tint" color="brand" shape="rounded">
                {currentDesign.n_runs} runs
              </Badge>
            </div>

            <div style={{ display: 'flex', gap: '8px' }}>
              <Button
                icon={isWriting ? <Spinner size="tiny" /> : <ArrowDownloadRegular />}
                disabled={isWriting}
                onClick={onWriteTemplate}
                style={{ flex: 1, borderRadius: '6px' }}
              >
                {isWriting ? 'Writing…' : 'Write Template'}
              </Button>
              <Button
                appearance="primary"
                onClick={onReadResults}
                style={{ flex: 1, borderRadius: '6px' }}
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
              style={{ borderRadius: '6px' }}
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
              <label className={styles.chartTypeLabel} htmlFor="doe-chart-view">View:</label>
              <Select
                size="small"
                id="doe-chart-view"
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
              icon={isWriting ? <Spinner size="tiny" /> : <ArrowDownloadRegular />}
              disabled={isWriting}
              onClick={onWriteResults}
              style={{ flex: 1, borderRadius: '6px' }}
            >
              {isWriting ? 'Writing…' : 'Write to Sheet'}
            </Button>
            <Button
              icon={<ArrowResetRegular />}
              appearance="subtle"
              onClick={onReset}
              style={{ borderRadius: '6px' }}
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

const BRAND = qikit.chart.brand;
const GRID_COLOR = qikit.chart.grid;

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
      tooltip: { backgroundColor: qikit.color.ink, cornerRadius: 6, padding: 8 },
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
        x: { type: 'linear' as const, title: { display: true, text: 'Run Order', font: { size: 11 }, color: qikit.chart.axisText }, grid: { display: false }, ticks: { font: { size: 10 }, color: qikit.chart.axisText } },
        y: { title: { display: true, text: 'Response', font: { size: 11 }, color: qikit.chart.axisText }, grid: { color: GRID_COLOR }, ticks: { font: { size: 10 }, color: qikit.chart.axisText } },
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
        x: { grid: { display: false }, ticks: { font: { size: 11 }, color: qikit.color.text } },
        y: { title: { display: true, text: 'Mean Response', font: { size: 11 }, color: qikit.chart.axisText }, grid: { color: GRID_COLOR }, ticks: { font: { size: 10 }, color: qikit.chart.axisText } },
      },
    };
    return (
      <div>
        {factors.length > 1 && (
          <div style={{ padding: '0 12px 8px', display: 'flex', gap: '6px', alignItems: 'center' }}>
            <span style={{ fontSize: '11px', color: qikit.color.text }}>Factor:</span>
            <Select
              size="small"
              value={String(selectedFactor)}
              onChange={(_, d) => setSelectedFactor(parseInt(d.value))}
              style={{ flex: 1 }}
            >
              {factors.map((f, i) => <option key={i} value={i}>{f}</option>)}
            </Select>
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
        { label: `${factors[fj]} High`, data: [getResp(-1, 1), getResp(1, 1)], borderColor: qikit.chart.accent, pointBackgroundColor: qikit.chart.accent, pointRadius: 4, borderWidth: 2, tension: 0, borderDash: [4, 3] },
      ],
    };
    const pairs: [number, number][] = [];
    for (let i = 0; i < factors.length; i++) for (let j = i + 1; j < factors.length; j++) pairs.push([i, j]);
    const opts = {
      ...baseOptions,
      plugins: { ...baseOptions.plugins, legend: { display: true, labels: { font: { size: 10 }, boxWidth: 20 } } },
      scales: {
        x: { grid: { display: false }, ticks: { font: { size: 11 }, color: qikit.color.text } },
        y: { title: { display: true, text: 'Mean Response', font: { size: 11 }, color: qikit.chart.axisText }, grid: { color: GRID_COLOR }, ticks: { font: { size: 10 }, color: qikit.chart.axisText } },
      },
    };
    return (
      <div>
        {pairs.length > 1 && (
          <div style={{ padding: '0 12px 8px', display: 'flex', gap: '6px', alignItems: 'center' }}>
            <span style={{ fontSize: '11px', color: qikit.color.text }}>Pair:</span>
            <Select
              size="small"
              value={`${selectedPair[0]},${selectedPair[1]}`}
              onChange={(_, d) => { const [a, b] = d.value.split(',').map(Number); setSelectedPair([a, b]); }}
              style={{ flex: 1 }}
            >
              {pairs.map(([a, b]) => <option key={`${a},${b}`} value={`${a},${b}`}>{factors[a]} × {factors[b]}</option>)}
            </Select>
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
        backgroundColor: `${BRAND}aa`,
        pointRadius: 5,
      }],
    };
    const opts = {
      ...baseOptions,
      scales: {
        x: { title: { display: true, text: 'Response', font: { size: 11 }, color: qikit.chart.axisText }, grid: { color: GRID_COLOR }, ticks: { font: { size: 10 }, color: qikit.chart.axisText } },
        y: { display: false, min: 0, max: 1 },
      },
    };
    return <div style={containerStyle}><ScatterChart data={data} options={opts} /></div>;
  }

  return null;
};
