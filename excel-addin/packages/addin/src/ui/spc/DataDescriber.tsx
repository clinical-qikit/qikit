import React, { useState } from 'react';
import { 
  RadioGroup, Radio, Text, makeStyles, tokens, Card, Button 
} from '@fluentui/react-components';
import { ChartType } from '@qikit/engine';
import { TooltipHelp } from '../shared/TooltipHelp';

const useStyles = makeStyles({
  container: {
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
    padding: '12px 0',
  },
  question: {
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  },
  result: {
    marginTop: '12px',
    padding: '12px',
    backgroundColor: tokens.colorNeutralBackground2,
    border: `1px solid ${tokens.colorBrandStroke1}`,
  }
});

interface DataDescriberProps {
  onChartResolved: (chart: ChartType) => void;
}

export const DataDescriber: React.FC<DataDescriberProps> = ({ onChartResolved }) => {
  const styles = useStyles();
  const [measurementType, setMeasurementType] = useState<string>('');
  const [sampleSize, setSampleSize] = useState<string>('');
  const [obsPerSample, setObsPerSample] = useState<string>('');

  const resolveChart = (): ChartType | null => {
    if (measurementType === 'continuous') {
      if (obsPerSample === '1') return 'i';
      if (obsPerSample === '2-25') return 'xbar';
      return 'i'; // Fallback
    }
    if (measurementType === 'proportions') {
      if (sampleSize === 'constant') return 'p';
      return 'p'; // Both p and u can handle variable n, but p is more common for proportions
    }
    if (measurementType === 'counts') {
      if (sampleSize === 'constant') return 'c';
      return 'u';
    }
    if (measurementType === 'time') return 't';
    return null;
  };

  const resolved = resolveChart();

  return (
    <div className={styles.container}>
      <div className={styles.question}>
        <Text weight="semibold">What are you measuring?</Text>
        <RadioGroup value={measurementType} onChange={(_, data) => setMeasurementType(data.value)}>
          <Radio value="continuous" label="Continuous (Time, length, cost)" />
          <Radio value="proportions" label="Proportions (Defective %)" />
          <Radio value="counts" label="Counts (Defects per unit)" />
          <Radio value="time" label="Time between events" />
        </RadioGroup>
      </div>

      {measurementType === 'proportions' || measurementType === 'counts' ? (
        <div className={styles.question}>
          <Text weight="semibold">Is your sample size constant?</Text>
          <RadioGroup value={sampleSize} onChange={(_, data) => setSampleSize(data.value)}>
            <Radio value="constant" label="Yes" />
            <Radio value="variable" label="No (Varies per sample)" />
          </RadioGroup>
        </div>
      ) : null}

      {measurementType === 'continuous' ? (
        <div className={styles.question}>
          <Text weight="semibold">How many observations per sample?</Text>
          <RadioGroup value={obsPerSample} onChange={(_, data) => setObsPerSample(data.value)}>
            <Radio value="1" label="Single observation (1)" />
            <Radio value="2-25" label="Small subgroup (2-25)" />
          </RadioGroup>
        </div>
      ) : null}

      {resolved && (
        <Card className={styles.result}>
          <Text weight="semibold">Recommended: {resolved.toUpperCase()} Chart</Text>
          <Text size={200}>
            {resolved === 'i' && 'I-MR chart: for individual continuous measurements.'}
            {resolved === 'xbar' && 'Xbar-S chart: for continuous data in subgroups.'}
            {resolved === 'p' && 'P-chart: for proportions of defective items.'}
            {resolved === 'u' && 'U-chart: for counts of defects per unit.'}
            {resolved === 'c' && 'C-chart: for counts of defects in a constant area.'}
            {resolved === 't' && 'T-chart: for time between rare events.'}
          </Text>
          <Button 
            appearance="primary" 
            size="small" 
            style={{ marginTop: '8px' }}
            onClick={() => onChartResolved(resolved)}
          >
            Use this chart
          </Button>
        </Card>
      )}
    </div>
  );
};
