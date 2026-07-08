import React from 'react';
import { Select } from '@fluentui/react-components';
import { useSpcStyles } from './styles';

interface DateAggregationOptionsProps {
  xPeriod: string;
  onChange: (period: string) => void;
}

/** Period picker shown when the X column is a date — controls date bucketing. */
export const DateAggregationOptions: React.FC<DateAggregationOptionsProps> = ({ xPeriod, onChange }) => {
  const styles = useSpcStyles();
  return (
    <div className={styles.colRow}>
      <span className={styles.colLabel} style={{ minWidth: '62px' }}>Period</span>
      <Select size="small" value={xPeriod} onChange={(_, d) => onChange(d.value)} style={{ flex: 1 }}>
        <option value="day">Day</option>
        <option value="week">Week</option>
        <option value="month">Month</option>
        <option value="quarter">Quarter</option>
        <option value="year">Year</option>
      </Select>
    </div>
  );
};
