import React, { useState } from 'react';
import { Input, Checkbox } from '@fluentui/react-components';
import { ChevronDownRegular, ChevronRightRegular } from '@fluentui/react-icons';
import { useSpcStyles } from './styles';
import { SpcOptions } from './constants';

interface LimitOptionsProps {
  options: SpcOptions;
  needsSubgroup: boolean;
  onChange: (patch: Partial<SpcOptions>) => void;
}

/** Limit-related settings: freeze, target, subgroup size, warning lines, and advanced overrides. */
export const LimitOptions: React.FC<LimitOptionsProps> = ({ options, needsSubgroup, onChange }) => {
  const styles = useSpcStyles();
  const [moreOpen, setMoreOpen] = useState(false);

  const setOpt = (key: keyof SpcOptions) => (_: any, data: { value: string }) =>
    onChange({ [key]: data.value });

  return (
    <>
      <div className={styles.settingRow}>
        <span className={styles.settingLabel}>Freeze at</span>
        <Input size="small" placeholder="e.g. 20" value={options.freeze} onChange={setOpt('freeze')} />
      </div>
      <div className={styles.settingRow}>
        <span className={styles.settingLabel}>Target line</span>
        <Input size="small" placeholder="value" value={options.target} onChange={setOpt('target')} />
      </div>
      {needsSubgroup && (
        <div className={styles.settingRow}>
          <span className={styles.settingLabel}>Subgroup size</span>
          <Input size="small" placeholder="2–25" value={options.subgroupN} onChange={setOpt('subgroupN')} />
        </div>
      )}
      <div className={styles.settingRow}>
        <span className={styles.settingLabel}>95% warning lines</span>
        <Checkbox checked={options.show95}
          onChange={(_, d) => onChange({ show95: !!d.checked })} />
      </div>

      <div className={styles.divider} />

      <button className={styles.settingsToggle} onClick={() => setMoreOpen(o => !o)}>
        {moreOpen ? <ChevronDownRegular style={{ fontSize: '12px' }} /> : <ChevronRightRegular style={{ fontSize: '12px' }} />}
        More options
      </button>

      {moreOpen && (
        <>
          <div className={styles.settingRow}>
            <span className={styles.settingLabel}>Part boundaries</span>
            <Input size="small" placeholder="e.g. 10, 20" value={options.part} onChange={setOpt('part')} />
          </div>
          <div className={styles.settingRow}>
            <span className={styles.settingLabel}>Part labels</span>
            <Input size="small" placeholder="e.g. Pre, Post" value={options.partLabels} onChange={setOpt('partLabels')} />
          </div>
          <div className={styles.settingRow}>
            <span className={styles.settingLabel}>Exclude points</span>
            <Input size="small" placeholder="e.g. 3, 7" value={options.exclude} onChange={setOpt('exclude')} />
          </div>
          <div className={styles.settingRow}>
            <span className={styles.settingLabel}>CL override</span>
            <Input size="small" placeholder="value" value={options.clOverride} onChange={setOpt('clOverride')} />
          </div>
          <div className={styles.settingRow}>
            <span className={styles.settingLabel}>Multiply</span>
            <Input size="small" placeholder="1" value={options.multiply} onChange={setOpt('multiply')} />
          </div>
        </>
      )}
    </>
  );
};
