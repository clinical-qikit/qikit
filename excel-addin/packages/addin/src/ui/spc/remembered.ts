// The SPC panel's choices, remembered per workbook in the document's own settings, so
// reopening the task pane on the same workbook brings back the chart type and options.
// Column choices are not kept: they mean nothing against a different selection.

import { ChartType } from '@qikit/engine';
import { DataGrain, DEFAULT_OPTIONS, SpcOptions, CORE_CHARTS, ADDITIONAL_CHARTS } from './constants';

const KEY = 'qikit.spc.settings';

export interface RememberedSpcSettings {
  chartType: ChartType;
  dataGrain: DataGrain;
  options: SpcOptions;
  includeDataTable: boolean;
}

const CHARTS = new Set<string>([...CORE_CHARTS, ...ADDITIONAL_CHARTS]);

function settingsStore(): Office.Settings | null {
  try {
    return (typeof Office !== 'undefined' && Office.context?.document?.settings) || null;
  } catch {
    return null;
  }
}

/** What this workbook remembers, or null. Anything malformed is ignored, never thrown. */
export function loadSpcSettings(): Partial<RememberedSpcSettings> | null {
  const store = settingsStore();
  if (!store) return null;
  try {
    const raw = store.get(KEY);
    if (typeof raw !== 'string') return null;
    const parsed = JSON.parse(raw);
    const out: Partial<RememberedSpcSettings> = {};
    if (CHARTS.has(parsed.chartType)) out.chartType = parsed.chartType;
    if (parsed.dataGrain === 'summarized' || parsed.dataGrain === 'individual') out.dataGrain = parsed.dataGrain;
    if (parsed.options && typeof parsed.options === 'object') {
      // Only known keys, with the default's type; a newer or older layout cannot inject others.
      const options: Record<string, unknown> = { ...DEFAULT_OPTIONS };
      for (const [k, v] of Object.entries(DEFAULT_OPTIONS)) {
        if (typeof parsed.options[k] === typeof v) options[k] = parsed.options[k];
      }
      out.options = options as unknown as SpcOptions;
    }
    if (typeof parsed.includeDataTable === 'boolean') out.includeDataTable = parsed.includeDataTable;
    return out;
  } catch {
    return null;
  }
}

/** Remember these settings in the workbook. Best effort: a failure only loses the memory. */
export function saveSpcSettings(settings: RememberedSpcSettings): void {
  const store = settingsStore();
  if (!store) return;
  try {
    const next = JSON.stringify(settings);
    if (store.get(KEY) === next) return;
    store.set(KEY, next);
    store.saveAsync(() => {});
  } catch {
    // Nothing to do: the pane works the same without remembered settings.
  }
}
