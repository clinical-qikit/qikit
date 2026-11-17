import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { loadSpcSettings, saveSpcSettings } from '../src/ui/spc/remembered';
import { DEFAULT_OPTIONS } from '../src/ui/spc/constants';

const store = new Map<string, string>();
let saves = 0;

beforeEach(() => {
  store.clear();
  saves = 0;
  (globalThis as any).Office = {
    context: { document: { settings: {
      get: (k: string) => (store.has(k) ? store.get(k) : null),
      set: (k: string, v: string) => { store.set(k, v); },
      saveAsync: (cb: () => void) => { saves++; cb(); },
    } } },
  };
});
afterEach(() => { delete (globalThis as any).Office; });

describe('remembered SPC settings', () => {
  it('round-trips through the workbook settings', () => {
    const options = { ...DEFAULT_OPTIONS, method: 'ihi' as const, freeze: '12' };
    saveSpcSettings({ chartType: 'p', dataGrain: 'individual', options, includeDataTable: true });
    expect(loadSpcSettings()).toEqual({ chartType: 'p', dataGrain: 'individual', options, includeDataTable: true });
    expect(saves).toBe(1);
  });

  it('does not save again when nothing changed', () => {
    const s = { chartType: 'i' as const, dataGrain: 'summarized' as const, options: DEFAULT_OPTIONS, includeDataTable: false };
    saveSpcSettings(s);
    saveSpcSettings(s);
    expect(saves).toBe(1);
  });

  it('ignores malformed or unknown values', () => {
    store.set('qikit.spc.settings', JSON.stringify({ chartType: 'funnel', dataGrain: 'x', options: { freeze: 3, method: 'nelson', evil: 1 } }));
    const loaded = loadSpcSettings()!;
    expect(loaded.chartType).toBeUndefined();
    expect(loaded.dataGrain).toBeUndefined();
    expect(loaded.options!.freeze).toBe('');
    expect(loaded.options!.method).toBe('nelson');
    expect((loaded.options as any).evil).toBeUndefined();
    store.set('qikit.spc.settings', '{not json');
    expect(loadSpcSettings()).toBeNull();
  });

  it('returns null outside Office', () => {
    delete (globalThis as any).Office;
    expect(loadSpcSettings()).toBeNull();
    expect(() => saveSpcSettings({ chartType: 'run', dataGrain: 'summarized', options: DEFAULT_OPTIONS, includeDataTable: false })).not.toThrow();
  });
});
