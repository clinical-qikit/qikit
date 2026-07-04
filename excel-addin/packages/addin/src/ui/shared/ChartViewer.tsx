import React from 'react';
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement,
  BarElement, Title, Tooltip, Legend, ChartOptions, ChartData, Plugin,
} from 'chart.js';
import { Line, Bar } from 'react-chartjs-2';
import { makeStyles } from '@fluentui/react-components';
import { SPCResult, DOEResult, ChartType } from '@qikit/engine';

ChartJS.register(
  CategoryScale, LinearScale, PointElement, LineElement, BarElement,
  Title, Tooltip, Legend
);

// ─── Annotation label plugin ─────────────────────────────────────────────────

const annotationLabelPlugin: Plugin<'line'> = {
  id: 'annotationLabels',
  afterDatasetsDraw(chart) {
    const annotations: Record<number, string> = (chart.options as any)._annotations;
    if (!annotations || Object.keys(annotations).length === 0) return;
    const meta = chart.getDatasetMeta(0);
    const ctx = chart.ctx;
    ctx.save();
    Object.entries(annotations).forEach(([idxStr, text]) => {
      const idx = parseInt(idxStr);
      const point = meta.data[idx];
      if (!point) return;
      const x = point.x;
      const y = point.y - 12;
      ctx.beginPath();
      ctx.moveTo(x, point.y - 5);
      ctx.lineTo(x, y - 2);
      ctx.strokeStyle = '#f59e0b';
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.fillStyle = '#92400e';
      ctx.font = `500 10px Inter, sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'bottom';
      ctx.fillText(text.length > 12 ? text.slice(0, 11) + '\u2026' : text, x, y);
    });
    ctx.restore();
  },
};

// ─── Part boundary lines plugin ──────────────────────────────────────────────

const partBoundaryPlugin: Plugin<'line'> = {
  id: 'partBoundaries',
  afterDatasetsDraw(chart) {
    const boundaries: number[] = (chart.options as any)._partBoundaries;
    const labels: string[] = (chart.options as any)._partLabels ?? [];
    if (!boundaries || boundaries.length === 0) return;
    const { ctx, chartArea, scales } = chart;
    if (!chartArea) return;
    ctx.save();
    boundaries.forEach((boundaryIdx, i) => {
      const xPx = scales.x.getPixelForValue(boundaryIdx);
      if (xPx < chartArea.left || xPx > chartArea.right) return;
      ctx.beginPath();
      ctx.moveTo(xPx, chartArea.top);
      ctx.lineTo(xPx, chartArea.bottom);
      ctx.strokeStyle = 'rgba(16, 124, 108, 0.35)';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 3]);
      ctx.stroke();
      ctx.setLineDash([]);
      const label = labels[i];
      if (label) {
        ctx.fillStyle = '#107C6C';
        ctx.font = `500 9px 'Segoe UI', sans-serif`;
        ctx.textAlign = 'left';
        ctx.textBaseline = 'top';
        ctx.fillText(label, xPx + 3, chartArea.top + 2);
      }
    });
    ctx.restore();
  },
};

// ─── Right-edge CL/UCL/LCL labels plugin ─────────────────────────────────────

const limitLabelsPlugin: Plugin<'line'> = {
  id: 'limitLabels',
  afterDatasetsDraw(chart) {
    const limitVals: { cl?: number; ucl?: number; lcl?: number } = (chart.options as any)._limitVals ?? {};
    if (!limitVals.cl && !limitVals.ucl && !limitVals.lcl) return;
    const { ctx, chartArea, scales } = chart;
    if (!chartArea) return;
    const rightX = chartArea.right + 4;
    ctx.save();
    ctx.font = `500 9px Inter, sans-serif`;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    const entries: { label: string; value: number; color: string }[] = [];
    if (limitVals.ucl !== undefined && !isNaN(limitVals.ucl)) entries.push({ label: 'UCL', value: limitVals.ucl, color: '#94a3b8' });
    if (limitVals.cl  !== undefined && !isNaN(limitVals.cl))  entries.push({ label: 'CL',  value: limitVals.cl,  color: '#94a3b8' });
    if (limitVals.lcl !== undefined && !isNaN(limitVals.lcl)) entries.push({ label: 'LCL', value: limitVals.lcl, color: '#94a3b8' });
    // Prevent overlap: sort by y-pixel, then nudge
    const positioned = entries.map(e => ({ ...e, yPx: scales.y.getPixelForValue(e.value) }));
    positioned.sort((a, b) => a.yPx - b.yPx);
    const MIN_GAP = 11;
    for (let i = 1; i < positioned.length; i++) {
      if (positioned[i].yPx - positioned[i - 1].yPx < MIN_GAP) {
        positioned[i].yPx = positioned[i - 1].yPx + MIN_GAP;
      }
    }
    positioned.forEach(({ label, value, yPx, color }) => {
      if (yPx < chartArea.top - 2 || yPx > chartArea.bottom + 2) return;
      const valStr = Math.abs(value) < 1 ? value.toFixed(3) : value.toFixed(1);
      ctx.fillStyle = color;
      ctx.fillText(`${label}=${valStr}`, rightX, yPx);
    });
    ctx.restore();
  },
};

ChartJS.register(annotationLabelPlugin, partBoundaryPlugin, limitLabelsPlugin);

// ─── Styles ──────────────────────────────────────────────────────────────────

const useStyles = makeStyles({
  container: {
    height: '220px',
    width: '100%',
    padding: '12px 44px 12px 12px',   // right padding for CL/UCL/LCL labels
    backgroundColor: '#ffffff',
    borderRadius: '10px',
    border: '1px solid #f0f1f3',
    boxSizing: 'border-box',
  },
});

// ─── Smart defaults by chart type ────────────────────────────────────────────

const PERCENT_CHARTS: ChartType[] = ['p', 'pp', 'ip'];
const Y_AXIS_LABELS: Partial<Record<ChartType, string>> = {
  p: 'Proportion', pp: 'Proportion', ip: 'Proportion',
  c: 'Count', u: 'Rate', up: 'Rate',
  i: 'Value', mr: 'Moving Range', xbar: 'Mean', s: 'Std Dev',
  run: 'Value', g: 'Opportunities', t: 'Time',
};

// ─── Props ───────────────────────────────────────────────────────────────────

interface ChartViewerProps {
  result: SPCResult | DOEResult;
  type: 'spc' | 'doe';
  annotations?: Record<number, string>;
  onPointClick?: (index: number) => void;
  target?: number;
  xLabels?: string[];
  show95?: boolean;
  partBoundaries?: number[];
  partLabels?: string[];
  chartType?: ChartType;
}

// ─── Color palette ──────────────────────────────────────────────────────────

const COLORS = {
  data: '#1a1a2e',
  signal: '#ef4444',
  runsSignal: '#f97316',
  annotation: '#f59e0b',
  cl: '#94a3b8',
  target: '#10b981',
  brand: '#107C6C',
  grid: '#f1f5f9',
  warn95: '#f59e0b',
};

// ─── Component ───────────────────────────────────────────────────────────────

export const ChartViewer: React.FC<ChartViewerProps> = ({
  result, type, annotations = {}, onPointClick, target, xLabels,
  show95 = false, partBoundaries, partLabels, chartType,
}) => {
  const styles = useStyles();

  if (type === 'spc') {
    const res = result as SPCResult;
    const labels = xLabels ?? res.data.map((_: any, i: number) => (i + 1).toString());
    const isPercent = chartType ? PERCENT_CHARTS.includes(chartType) : false;
    const yAxisLabel = chartType ? (Y_AXIS_LABELS[chartType] ?? 'Value') : 'Value';

    const pointColors = res.data.map((d: any, i: number) => {
      if (d.sigma_signal) return COLORS.signal;
      if (d.runs_signal)  return COLORS.runsSignal;
      if (annotations[i]) return COLORS.annotation;
      return COLORS.data;
    });

    const pointStyles = res.data.map((_: any, i: number) =>
      annotations[i] ? 'rectRot' : 'circle'
    );

    const pointRadii = res.data.map((d: any, i: number) =>
      (d.sigma_signal || d.runs_signal || annotations[i]) ? 5 : 2.5
    );

    const datasets: ChartData<'line'>['datasets'] = [
      {
        label: 'Data',
        data: res.data.map((d: any) => d.y),
        borderColor: COLORS.data,
        pointBackgroundColor: pointColors,
        pointStyle: pointStyles as any,
        pointRadius: pointRadii,
        borderWidth: 1.5,
        tension: 0,
        order: 1,
      },
      {
        label: 'CL',
        data: res.data.map((d: any) => isNaN(d.cl) ? null : d.cl),
        borderColor: COLORS.cl,
        borderDash: [6, 4],
        pointRadius: 0,
        borderWidth: 1,
        order: 2,
      },
      {
        label: 'UCL',
        data: res.data.map((d: any) => isNaN(d.ucl) ? null : d.ucl),
        borderColor: COLORS.cl,
        pointRadius: 0,
        borderWidth: 1,
        order: 2,
      },
      {
        label: 'LCL',
        data: res.data.map((d: any) => isNaN(d.lcl) ? null : d.lcl),
        borderColor: COLORS.cl,
        pointRadius: 0,
        borderWidth: 1,
        order: 2,
      },
    ];

    if (show95 && res.data[0]?.ucl_95 !== undefined) {
      datasets.push({
        label: 'UCL 95%',
        data: res.data.map((d: any) => d.ucl_95 == null || isNaN(d.ucl_95) ? null : d.ucl_95),
        borderColor: COLORS.warn95,
        borderDash: [3, 3],
        pointRadius: 0,
        borderWidth: 1,
        order: 3,
      });
      datasets.push({
        label: 'LCL 95%',
        data: res.data.map((d: any) => d.lcl_95 == null || isNaN(d.lcl_95) ? null : d.lcl_95),
        borderColor: COLORS.warn95,
        borderDash: [3, 3],
        pointRadius: 0,
        borderWidth: 1,
        order: 3,
      });
    }

    if (target !== undefined && !isNaN(target)) {
      datasets.push({
        label: 'Target',
        data: new Array(labels.length).fill(target),
        borderColor: COLORS.target,
        borderDash: [4, 4],
        pointRadius: 0,
        borderWidth: 1.5,
        order: 4,
      });
    }

    // Compute representative limit values from last non-null point
    const lastPoint = [...res.data].reverse().find((d: any) => !isNaN(d.cl));
    const limitVals = lastPoint
      ? { cl: lastPoint.cl, ucl: lastPoint.ucl, lcl: lastPoint.lcl < 0 ? undefined : lastPoint.lcl }
      : {};

    const options: ChartOptions<'line'> = {
      responsive: true,
      maintainAspectRatio: false,
      layout: { padding: { right: 0 } },
      onClick(_event, elements) {
        if (elements.length > 0 && onPointClick) {
          onPointClick(elements[0].index);
        }
      },
      onHover(_event, elements, chart) {
        chart.canvas.style.cursor = elements.length > 0 ? 'pointer' : 'default';
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1a1a2e',
          titleFont: { family: 'Inter, sans-serif', size: 12 },
          bodyFont: { family: 'Inter, sans-serif', size: 11 },
          cornerRadius: 6,
          padding: 8,
          callbacks: {
            afterBody(context: any) {
              const idx = context[0].dataIndex;
              const note = annotations[idx];
              return note ? [`Note: ${note}`] : [];
            },
          },
        },
      } as any,
      scales: {
        x: {
          display: true,
          grid: { display: false },
          ticks: { font: { family: 'Inter, sans-serif', size: 10 }, color: '#9ca3af' },
        },
        y: {
          display: true,
          grid: { color: COLORS.grid },
          ticks: {
            font: { family: 'Inter, sans-serif', size: 10 },
            color: '#9ca3af',
            ...(isPercent ? { callback: (v: any) => `${(v * 100).toFixed(1)}%` } : {}),
          },
          title: {
            display: true,
            text: yAxisLabel,
            font: { family: 'Inter, sans-serif', size: 10 },
            color: '#9ca3af',
          },
        },
      },
    };

    (options as any)._annotations = annotations;
    (options as any)._partBoundaries = partBoundaries ?? [];
    (options as any)._partLabels = partLabels ?? [];
    (options as any)._limitVals = limitVals;

    return (
      <div className={styles.container}>
        <Line data={{ labels, datasets }} options={options} />
      </div>
    );
  } else {
    // DOE bar chart
    const res = result as DOEResult;
    const sortedEffects = [...res.effects].sort((a, b) => b.abs_effect - a.abs_effect);

    const data: ChartData<'bar'> = {
      labels: sortedEffects.map(e => e.term),
      datasets: [
        {
          label: 'Absolute Effect',
          data: sortedEffects.map(e => e.abs_effect),
          backgroundColor: COLORS.brand,
          borderRadius: 4,
        },
      ],
    };

    const options: ChartOptions<'bar'> = {
      indexAxis: 'y' as const,
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1a1a2e',
          titleFont: { family: 'Inter, sans-serif', size: 12 },
          bodyFont: { family: 'Inter, sans-serif', size: 11 },
          cornerRadius: 6,
          padding: 8,
        },
      },
      scales: {
        x: {
          display: true,
          title: {
            display: true,
            text: 'Absolute Effect',
            font: { family: 'Inter, sans-serif', size: 11, weight: 500 },
            color: '#6b7280',
          },
          grid: { color: COLORS.grid },
          ticks: { font: { family: 'Inter, sans-serif', size: 10 }, color: '#9ca3af' },
        },
        y: {
          display: true,
          ticks: { font: { family: 'Inter, sans-serif', size: 11, weight: 500 }, color: '#374151' },
        },
      },
    };

    return (
      <div className={styles.container}>
        <Bar data={data} options={options} />
      </div>
    );
  }
};
