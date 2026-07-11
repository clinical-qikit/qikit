import React, { useState } from 'react';
import { Input, Checkbox } from '@fluentui/react-components';
import { ChevronDownRegular, ChevronRightRegular } from '@fluentui/react-icons';
import { useSpcStyles } from './styles';
import { SpcOptions } from './constants';
import { NumericField } from '../shared/NumericField';

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
        <label className={styles.settingLabel} htmlFor="spc-opt-freeze"
          title="Compute the centre line and limits from only the first N points, then extend them — useful for before/after comparisons.">
          Freeze at
        </label>
        <NumericField id="spc-opt-freeze" placeholder="e.g. 20" integer min={1}
          value={options.freeze} onChange={v => onChange({ freeze: v })} />
      </div>
      <div className={styles.settingRow}>
        <label className={styles.settingLabel} htmlFor="spc-opt-target"
          title="Draw a horizontal reference line at this value (e.g. an improvement goal).">
          Target line
        </label>
        <NumericField id="spc-opt-target" placeholder="value"
          value={options.target} onChange={v => onChange({ target: v })} />
      </div>
      {needsSubgroup && (
        <div className={styles.settingRow}>
          <label className={styles.settingLabel} htmlFor="spc-opt-subgroup"
            title="Number of measurements per subgroup used to compute X̄/S limits.">
            Subgroup size
          </label>
          <NumericField id="spc-opt-subgroup" placeholder="2–25" integer min={2} max={25}
            value={options.subgroupN} onChange={v => onChange({ subgroupN: v })} />
        </div>
      )}
      <div className={styles.settingRow}>
        <span className={styles.settingLabel}>95% warning lines</span>
        <Checkbox checked={options.show95} aria-label="Show 95% warning lines"
          onChange={(_, d) => onChange({ show95: !!d.checked })} />
      </div>

      <div className={styles.divider} />

      <button className={styles.settingsToggle} onClick={() => setMoreOpen(o => !o)}
        aria-expanded={moreOpen} aria-controls="spc-more-options">
        {moreOpen ? <ChevronDownRegular style={{ fontSize: '12px' }} /> : <ChevronRightRegular style={{ fontSize: '12px' }} />}
        More options
      </button>

      {moreOpen && (
        <div id="spc-more-options" style={{ display: 'contents' }}>
          <div className={styles.settingRow}>
            <label className={styles.settingLabel} htmlFor="spc-opt-part"
              title="Point numbers where the process changed — limits are recomputed for each part (e.g. 10, 20).">
              Part boundaries
            </label>
            <Input size="small" id="spc-opt-part" placeholder="e.g. 10, 20" value={options.part} onChange={setOpt('part')} />
          </div>
          <div className={styles.settingRow}>
            <label className={styles.settingLabel} htmlFor="spc-opt-part-labels"
              title="One label per part, shown on the chart (e.g. Pre, Post).">
              Part labels
            </label>
            <Input size="small" id="spc-opt-part-labels" placeholder="e.g. Pre, Post" value={options.partLabels} onChange={setOpt('partLabels')} />
          </div>
          <div className={styles.settingRow}>
            <label className={styles.settingLabel} htmlFor="spc-opt-exclude"
              title="Point numbers left out of the limit calculation but still plotted (e.g. known special causes).">
              Exclude points
            </label>
            <Input size="small" id="spc-opt-exclude" placeholder="e.g. 3, 7" value={options.exclude} onChange={setOpt('exclude')} />
          </div>
          <div className={styles.settingRow}>
            <label className={styles.settingLabel} htmlFor="spc-opt-cl"
              title="Use this value as the centre line instead of computing it from the data (e.g. a historical baseline).">
              CL override
            </label>
            <NumericField id="spc-opt-cl" placeholder="value"
              value={options.clOverride} onChange={v => onChange({ clOverride: v })} />
          </div>
          <div className={styles.settingRow}>
            <label className={styles.settingLabel} htmlFor="spc-opt-multiply"
              title="Scale factor applied to y values — e.g. 100 to show proportions as percentages, or 1000 for rates per 1,000.">
              Multiply
            </label>
            <NumericField id="spc-opt-multiply" placeholder="1"
              value={options.multiply} onChange={v => onChange({ multiply: v })} />
          </div>
        </div>
      )}
    </>
  );
};
