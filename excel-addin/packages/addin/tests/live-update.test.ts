import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

/**
 * Minimal Excel/Office mock — just enough surface for live-update.ts's binding,
 * settings, and output-sheet-write paths. Lighter than dev-harness.tsx since this
 * only needs to prove the pure coordination logic (debounce, metadata persistence,
 * reattachment), not render a task pane.
 */
function installMockOffice() {
  const settingsStore = new Map<string, string>();
  const bindings = new Map<string, {
    id: string; address: string; getValues: () => any[][];
    handlers: Array<() => any>; poisoned?: boolean;
  }>();
  const sheets = new Map<string, { values: any[][]; charts: any[] }>();
  sheets.set('Sheet1', { values: [['Defect Type'], ['Scratch'], ['Scratch'], ['Dent']], charts: [] });

  function makeRange(get: () => any[][], set: (v: any[][]) => void, address: string) {
    return {
      load: () => {},
      get values() { return get(); },
      set values(v: any[][]) { set(v); },
      address,
      clear: () => {},
    };
  }

  function makeSheet(name: string) {
    const state = sheets.get(name);
    return {
      name,
      isNullObject: !state,
      load: () => {},
      getRangeByIndexes: (_r: number, _c: number, rowCount: number, colCount: number) => {
        const addr = `${name}!A1:${String.fromCharCode(64 + colCount)}${rowCount}`;
        return makeRange(() => state?.values ?? [], (v) => { if (state) state.values = v; }, addr);
      },
      charts: { get items() { return state?.charts ?? []; }, load: () => {} },
    };
  }

  function makeBinding(id: string) {
    const rec = bindings.get(id);
    return {
      id,
      isNullObject: !rec,
      load: () => {},
      onDataChanged: { add: (h: () => any) => { rec?.handlers.push(h); } },
      getRange: () => {
        if (!rec || rec.poisoned) throw new Error("ItemNotFound: The requested resource doesn't exist.");
        return makeRange(rec.getValues, () => {}, rec.address);
      },
      delete: () => { bindings.delete(id); },
    };
  }

  (globalThis as any).Excel = {
    run: async (cb: (context: any) => Promise<any>) => cb({
      workbook: {
        worksheets: {
          getActiveWorksheet: () => makeSheet('Sheet1'),
          getItem: (name: string) => makeSheet(name),
          getItemOrNullObject: (name: string) => makeSheet(name),
        },
        bindings: {
          add: (address: string, _type: any, id: string) => {
            bindings.set(id, {
              id, address,
              getValues: () => sheets.get(address.split('!')[0])?.values ?? [],
              handlers: [],
            });
            return makeBinding(id);
          },
          getItem: (id: string) => makeBinding(id),
          getItemOrNullObject: (id: string) => makeBinding(id),
        },
      },
      sync: async () => {},
    }),
    BindingType: { range: 'Range' },
    ClearApplyTo: { contents: 'Contents' },
  };

  (globalThis as any).Office = {
    context: {
      document: {
        settings: {
          get: (key: string) => (settingsStore.has(key) ? settingsStore.get(key) : null),
          set: (key: string, value: string) => { settingsStore.set(key, value); },
          saveAsync: (cb: any) => cb(),
        },
      },
    },
  };

  return { settingsStore, bindings, sheets };
}

describe('live-update', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('persists binding metadata that reattachLiveUpdates can read back without pruning it', async () => {
    const mock = installMockOffice();
    const { registerLiveUpdate, reattachLiveUpdates } = await import('../src/excel/live-update');

    const bindingId = await registerLiveUpdate({
      panel: 'pareto',
      sourceAddress: 'Sheet1!A1:A4',
      outputSheet: 'Pareto',
      outputRowCount: 3,
      config: { xCol: 0 },
    });

    const stored = JSON.parse(mock.settingsStore.get('qikit.liveUpdates')!);
    expect(stored[bindingId]).toMatchObject({ panel: 'pareto', outputSheet: 'Pareto' });

    await reattachLiveUpdates();
    expect(mock.bindings.has(bindingId)).toBe(true);
    expect(JSON.parse(mock.settingsStore.get('qikit.liveUpdates')!)[bindingId]).toBeDefined();
  });

  it('prunes metadata for bindings whose range no longer exists on reattach', async () => {
    const mock = installMockOffice();
    const { registerLiveUpdate, reattachLiveUpdates } = await import('../src/excel/live-update');

    const bindingId = await registerLiveUpdate({
      panel: 'pareto', sourceAddress: 'Sheet1!A1:A4', outputSheet: 'Pareto',
      outputRowCount: 3, config: { xCol: 0 },
    });
    mock.bindings.delete(bindingId); // simulate the user deleting the binding out-of-band

    await reattachLiveUpdates();
    const stored = JSON.parse(mock.settingsStore.get('qikit.liveUpdates')!);
    expect(stored[bindingId]).toBeUndefined();
  });

  it('debounces rapid onDataChanged firings into a single recompute', async () => {
    const mock = installMockOffice();
    mock.sheets.set('Pareto', { values: [], charts: [] });
    const { registerLiveUpdate, subscribeLiveUpdateEvents } = await import('../src/excel/live-update');

    const bindingId = await registerLiveUpdate({
      panel: 'pareto', sourceAddress: 'Sheet1!A1:A4', outputSheet: 'Pareto',
      outputRowCount: 3, config: { xCol: 0 },
    });

    const events: any[] = [];
    subscribeLiveUpdateEvents(e => events.push(e));

    const handlers = mock.bindings.get(bindingId)!.handlers;
    expect(handlers.length).toBeGreaterThan(0);
    handlers.forEach(h => h()); // fire the same handler twice in quick succession
    handlers.forEach(h => h());

    await vi.advanceTimersByTimeAsync(1000);

    const updates = events.filter(e => e.type === 'updated');
    expect(updates).toHaveLength(1);
  });

  it('emits source-deleted and forgets the binding when the bound range is gone', async () => {
    const mock = installMockOffice();
    mock.sheets.set('Pareto', { values: [], charts: [] });
    const { registerLiveUpdate, subscribeLiveUpdateEvents } = await import('../src/excel/live-update');

    const bindingId = await registerLiveUpdate({
      panel: 'pareto', sourceAddress: 'Sheet1!A1:A4', outputSheet: 'Pareto',
      outputRowCount: 3, config: { xCol: 0 },
    });

    const events: any[] = [];
    subscribeLiveUpdateEvents(e => events.push(e));

    mock.bindings.get(bindingId)!.poisoned = true;
    mock.bindings.get(bindingId)!.handlers.forEach(h => h());

    await vi.advanceTimersByTimeAsync(1000);

    expect(events.some(e => e.type === 'source-deleted' && e.bindingId === bindingId)).toBe(true);
    expect(JSON.parse(mock.settingsStore.get('qikit.liveUpdates')!)[bindingId]).toBeUndefined();
  });
});
