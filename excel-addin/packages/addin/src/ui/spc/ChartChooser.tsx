import React, { useState } from 'react';
import { Button } from '@fluentui/react-components';
import { ChartType } from '@qikit/engine';
import { CHART_LABELS } from './constants';
import { qikit } from '../../theme/tokens';

// "Help me choose": a few plain questions that pick the chart, for someone who does
// not know an I chart from a U chart. Unsure at any step means a run chart, which
// needs no assumptions about the data (the advice in the Python docs).

type Kind = 'measure' | 'count' | 'unsure';
type Count = 'none' | 'cases' | 'exposure' | 'unsure';
type Size = 'one' | 'several' | 'unsure';

export interface ChartChoice {
  chart: ChartType;
  why: string;
}

/** The chart the answers point to, or null until enough has been answered. */
export function chooseChart(kind: Kind | null, count: Count | null, size: Size | null): ChartChoice | null {
  if (kind === null) return null;
  if (kind === 'unsure') {
    return { chart: 'run', why: 'A run chart works for any measure over time and makes no assumptions about the data.' };
  }
  if (kind === 'measure') {
    if (size === null) return null;
    if (size === 'several') {
      return { chart: 'xbar', why: 'Each value is the average of several measurements: an X̄ chart, with the S chart for their spread.' };
    }
    if (size === 'one') {
      return { chart: 'i', why: 'One measurement per period: an I chart (individuals).' };
    }
    return { chart: 'run', why: 'When unsure, a run chart is the safe start: it makes no assumptions about the data.' };
  }
  if (count === null) return null;
  if (count === 'cases') {
    return { chart: 'p', why: 'Cases out of a total, each case counted once (patients with an infection out of patients): a P chart. Choose the total as the denominator.' };
  }
  if (count === 'exposure') {
    return { chart: 'u', why: 'Events per amount of exposure (falls per patient day, infections per device day): a U chart. Choose the exposure as the denominator.' };
  }
  if (count === 'none') {
    return { chart: 'c', why: 'A count with no denominator, where the opportunity is about the same each period: a C chart.' };
  }
  return { chart: 'run', why: 'When unsure, a run chart is the safe start: it makes no assumptions about the data.' };
}

interface Option<T> { value: T; label: string }

function Question<T extends string>({ label, options, value, onChange }: {
  label: string; options: Option<T>[]; value: T | null; onChange: (v: T) => void;
}) {
  return (
    <fieldset style={{ border: 'none', margin: '0 0 10px', padding: 0 }}>
      <legend style={{ fontSize: '12px', fontWeight: 600, color: qikit.color.ink, marginBottom: '6px', padding: 0 }}>
        {label}
      </legend>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
        {options.map(o => (
          <label key={o.value} style={{ display: 'flex', gap: '6px', alignItems: 'flex-start', fontSize: '12px', color: qikit.color.text, cursor: 'pointer' }}>
            <input type="radio" checked={value === o.value} onChange={() => onChange(o.value)} style={{ marginTop: '2px' }} />
            {o.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

interface ChartChooserProps {
  onChoose: (chart: ChartType) => void;
  onClose: () => void;
}

export const ChartChooser: React.FC<ChartChooserProps> = ({ onChoose, onClose }) => {
  const [kind, setKind] = useState<Kind | null>(null);
  const [count, setCount] = useState<Count | null>(null);
  const [size, setSize] = useState<Size | null>(null);
  const choice = chooseChart(kind, count, size);

  return (
    <div id="spc-chart-chooser" style={{
      marginTop: '10px', padding: '12px', borderRadius: qikit.radius.md,
      border: `1px solid ${qikit.color.brandTintBorder}`, backgroundColor: qikit.color.brandTint,
    }}>
      <Question<Kind>
        label="What does each value in your data record?"
        value={kind}
        onChange={v => { setKind(v); setCount(null); setSize(null); }}
        options={[
          { value: 'measure', label: 'A measurement: minutes, days, a score, a weight' },
          { value: 'count', label: 'A count of events or cases' },
          { value: 'unsure', label: 'Not sure' },
        ]}
      />
      {kind === 'count' && (
        <Question<Count>
          label="Is there a denominator?"
          value={count}
          onChange={setCount}
          options={[
            { value: 'cases', label: 'Yes: out of a number of patients or cases (each counted once)' },
            { value: 'exposure', label: 'Yes: per amount of exposure, such as patient days or device days' },
            { value: 'none', label: 'No: just the count each period' },
            { value: 'unsure', label: 'Not sure' },
          ]}
        />
      )}
      {kind === 'measure' && (
        <Question<Size>
          label="Is each value one measurement, or the average of several?"
          value={size}
          onChange={setSize}
          options={[
            { value: 'one', label: 'One measurement per row or period' },
            { value: 'several', label: 'The average of several, with how many in another column' },
            { value: 'unsure', label: 'Not sure' },
          ]}
        />
      )}
      {choice && (
        <div role="status" style={{ fontSize: '12px', color: qikit.color.ink, lineHeight: 1.45, marginBottom: '8px' }}>
          <strong>{CHART_LABELS[choice.chart]}.</strong> {choice.why}
        </div>
      )}
      <div style={{ display: 'flex', gap: '8px' }}>
        <Button size="small" appearance="primary" disabled={!choice}
          onClick={() => { if (choice) { onChoose(choice.chart); onClose(); } }}
          style={{ borderRadius: qikit.radius.md }}>
          Use this chart
        </Button>
        <Button size="small" appearance="subtle" onClick={onClose} style={{ borderRadius: qikit.radius.md }}>
          Close
        </Button>
      </div>
    </div>
  );
};
