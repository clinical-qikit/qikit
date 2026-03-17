import React from 'react';
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement,
  BarElement, Title, Tooltip, Legend, ChartOptions, ChartData, Plugin,
} from 'chart.js';
import { Line, Bar } from 'react-chartjs-2';
import { makeStyles, tokens } from '@fluentui/react-components';
import { SPCResult, DOEResult } from '@qikit/engine';

ChartJS.register(
  CategoryScale, LinearScale, PointElement, LineElement, BarElement,
  Title, Tooltip, Legend
);

// ─── Annotation label plugin ─────────────────────────────────────────────────
// Draws a small flag marker above annotated points.

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
      const y = point.y - 10;
      ctx.fillStyle = '#f0a500';
      ctx.font = `10px sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'bottom';
      // Small flag line
      ctx.beginPath();
      ctx.moveTo(x, point.y - 5);
      ctx.lineTo(x, y - 2);
      ctx.strokeStyle = '#f0a500';
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.fillText(text.length > 12 ? text.slice(0, 11) + '…' : text, x, y);
    });
    ctx.restore();
  },
};

ChartJS.register(annotationLabelPlugin);

// ─── Styles ──────────────────────────────────────────────────────────────────

const useStyles = makeStyles({
  container: {
    height: '220px',
    width: '100%',
    backgroundColor: tokens.colorNeutralBackground1,
    padding: '8px 4px',
    boxSizing: 'border-box',
  },
});

// ─── Props ───────────────────────────────────────────────────────────────────

interface ChartViewerProps {
  result: SPCResult | DOEResult;
  type: 'spc' | 'doe';
  annotations?: Record<number, string>;
  onPointClick?: (index: number) => void;
  target?: number;
}

// ─── Component ───────────────────────────────────────────────────────────────

export const ChartViewer: React.FC<ChartViewerProps> = ({
  result, type, annotations = {}, onPointClick, target,
}) => {
  const styles = useStyles();

  if (type === 'spc') {
    const res = result as SPCResult;
    const labels = res.data.map((_: any, i: number) => (i + 1).toString());

    const pointColors = res.data.map((d: any, i: number) => {
      if (d.sigma_signal) return '#d62728';
      if (d.runs_signal)  return '#ff7f0e';
      if (annotations[i]) return '#f0a500';
      return tokens.colorNeutralForeground1;
    });

    const pointStyles = res.data.map((_: any, i: number) =>
      annotations[i] ? 'rectRot' : 'circle'
    );

    const pointRadii = res.data.map((d: any, i: number) =>
      (d.sigma_signal || d.runs_signal || annotations[i]) ? 5 : 3
    );

    const datasets: ChartData<'line'>['datasets'] = [
      {
        label: 'Data',
        data: res.data.map((d: any) => d.y),
        borderColor: tokens.colorNeutralForeground1,
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
        borderColor: '#888888',
        borderDash: [5, 5],
        pointRadius: 0,
        borderWidth: 1,
        order: 2,
      },
      {
        label: 'UCL',
        data: res.data.map((d: any) => isNaN(d.ucl) ? null : d.ucl),
        borderColor: '#888888',
        pointRadius: 0,
        borderWidth: 1,
        order: 2,
      },
      {
        label: 'LCL',
        data: res.data.map((d: any) => isNaN(d.lcl) ? null : d.lcl),
        borderColor: '#888888',
        pointRadius: 0,
        borderWidth: 1,
        order: 2,
      },
    ];

    if (target !== undefined && !isNaN(target)) {
      datasets.push({
        label: 'Target',
        data: new Array(labels.length).fill(target),
        borderColor: '#2ca02c',
        borderDash: [4, 4],
        pointRadius: 0,
        borderWidth: 1.5,
        order: 3,
      });
    }

    const options: ChartOptions<'line'> = {
      responsive: true,
      maintainAspectRatio: false,
      onClick(_event, elements) {
        if (elements.length > 0 && onPointClick) {
          onPointClick(elements[0].index);
        }
      },
      onHover(_event, elements, chart) {
        const canvas = chart.canvas;
        canvas.style.cursor = elements.length > 0 ? 'pointer' : 'default';
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            afterBody(context) {
              const idx = context[0].dataIndex;
              const note = annotations[idx];
              return note ? [`Note: ${note}`] : [];
            },
          },
        },
        // Pass annotations to the custom plugin via chart options
        ...({ _annotations: annotations } as any),
      },
      scales: {
        x: { display: true, grid: { display: false } },
        y: { display: true, grid: { color: tokens.colorNeutralStroke2 } },
      },
    };

    // Attach annotations to options for the custom plugin
    (options as any)._annotations = annotations;

    return (
      <div className={styles.container}>
        <Line data={{ labels, datasets }} options={options} />
      </div>
    );
  } else {
    // DOE bar chart — unchanged
    const res = result as DOEResult;
    const sortedEffects = [...res.effects].sort((a, b) => b.abs_effect - a.abs_effect);

    const data: ChartData<'bar'> = {
      labels: sortedEffects.map(e => e.term),
      datasets: [
        {
          label: 'Absolute Effect',
          data: sortedEffects.map(e => e.abs_effect),
          backgroundColor: tokens.colorBrandBackground,
        },
      ],
    };

    const options: ChartOptions<'bar'> = {
      indexAxis: 'y' as const,
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { enabled: true },
      },
      scales: {
        x: { display: true, title: { display: true, text: 'Absolute Effect' } },
        y: { display: true },
      },
    };

    return (
      <div className={styles.container}>
        <Bar data={data} options={options} />
      </div>
    );
  }
};
