import React from 'react';
import { 
  Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, 
  BarElement, Title, Tooltip, Legend, ChartOptions, ChartData 
} from 'chart.js';
import { Line, Bar } from 'react-chartjs-2';
import { makeStyles, tokens } from '@fluentui/react-components';
import { SPCResult, DOEResult } from '@qikit/engine';

ChartJS.register(
  CategoryScale, LinearScale, PointElement, LineElement, BarElement, 
  Title, Tooltip, Legend
);

const useStyles = makeStyles({
  container: {
    height: '250px',
    width: '100%',
    backgroundColor: tokens.colorNeutralBackground1,
    padding: '12px 4px',
    boxSizing: 'border-box',
  }
});

interface ChartViewerProps {
  result: SPCResult | DOEResult;
  type: 'spc' | 'doe';
}

export const ChartViewer: React.FC<ChartViewerProps> = ({ result, type }) => {
  const styles = useStyles();

  if (type === 'spc') {
    const res = result as SPCResult;
    const labels = res.data.map((_, i) => (i + 1).toString());
    const data: ChartData<'line'> = {
      labels,
      datasets: [
        {
          label: 'Data',
          data: res.data.map(d => d.y),
          borderColor: tokens.colorNeutralForeground1,
          pointBackgroundColor: res.data.map(d => (d.sigma_signal || d.runs_signal) ? tokens.colorPaletteRedForeground1 : tokens.colorNeutralForeground1),
          pointRadius: res.data.map(d => (d.sigma_signal || d.runs_signal) ? 5 : 3),
          borderWidth: 1.5,
          tension: 0,
        },
        {
          label: 'CL',
          data: res.data.map(d => d.cl),
          borderColor: tokens.colorNeutralStroke2,
          borderDash: [5, 5],
          pointRadius: 0,
          borderWidth: 1,
        },
        {
          label: 'UCL',
          data: res.data.map(d => d.ucl),
          borderColor: tokens.colorNeutralStroke2,
          pointRadius: 0,
          borderWidth: 1,
        },
        {
          label: 'LCL',
          data: res.data.map(d => d.lcl),
          borderColor: tokens.colorNeutralStroke2,
          pointRadius: 0,
          borderWidth: 1,
        }
      ]
    };

    const options: ChartOptions<'line'> = {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { enabled: true }
      },
      scales: {
        x: { display: true, grid: { display: false } },
        y: { display: true, grid: { color: tokens.colorNeutralStroke2 } }
      }
    };

    return (
      <div className={styles.container}>
        <Line data={data} options={options} />
      </div>
    );
  } else {
    const res = result as DOEResult;
    // Sort by absolute effect
    const sortedEffects = [...res.effects].sort((a, b) => b.abs_effect - a.abs_effect);
    
    const data: ChartData<'bar'> = {
      labels: sortedEffects.map(e => e.term),
      datasets: [
        {
          label: 'Absolute Effect',
          data: sortedEffects.map(e => e.abs_effect),
          backgroundColor: tokens.colorBrandBackground,
        }
      ]
    };

    const options: ChartOptions<'bar'> = {
      indexAxis: 'y' as const,
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { enabled: true }
      },
      scales: {
        x: { display: true, title: { display: true, text: 'Absolute Effect' } },
        y: { display: true }
      }
    };

    return (
      <div className={styles.container}>
        <Bar data={data} options={options} />
      </div>
    );
  }
};
