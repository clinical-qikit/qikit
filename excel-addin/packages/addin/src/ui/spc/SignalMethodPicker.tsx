import React from 'react';
import { Select } from '@fluentui/react-components';
import { useSpcStyles } from './styles';
import { SpcOptions } from './constants';

interface SignalMethodPickerProps {
  value: SpcOptions['method'];
  onChange: (method: SpcOptions['method']) => void;
}

export const SignalMethodPicker: React.FC<SignalMethodPickerProps> = ({ value, onChange }) => {
  const styles = useSpcStyles();
  return (
    <div className={styles.settingRow}>
      <label className={styles.settingLabel} htmlFor="spc-signal-method"
        title="Rule set used to flag non-random variation (runs, crossings, sigma violations).">
        Signal method
      </label>
      <Select size="small" id="spc-signal-method" value={value} onChange={(_, d) => onChange(d.value as SpcOptions['method'])}>
        <option value="anhoej">Anhoej</option>
        <option value="ihi">IHI</option>
        <option value="weco">WECO</option>
        <option value="nelson">Nelson</option>
      </Select>
    </div>
  );
};
