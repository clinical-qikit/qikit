import { writeToSheetRange } from './excel-io';
import { recompute, PanelKind, LiveConfig } from './recompute';

/* global Excel, Office */

const SETTINGS_KEY = 'qikit.liveUpdates';
const DEBOUNCE_MS = 800;

export interface LiveUpdateMeta {
  bindingId: string;
  panel: PanelKind;
  sourceAddress: string;
  outputSheet: string;
  outputRowCount: number;
  config: LiveConfig;
}

export type LiveUpdateEvent =
  | { type: 'updated'; bindingId: string; panel: PanelKind; outputSheet: string }
  | { type: 'recompute-error'; bindingId: string; panel: PanelKind; message: string }
  | { type: 'source-deleted'; bindingId: string; panel: PanelKind; sourceAddress: string };

type Listener = (event: LiveUpdateEvent) => void;
const listeners = new Set<Listener>();

export function subscribeLiveUpdateEvents(cb: Listener): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

function emit(event: LiveUpdateEvent) {
  listeners.forEach(cb => cb(event));
}

// ─── Metadata persistence (workbook-scoped via Office document settings) ─────

function readMetaStore(): Record<string, LiveUpdateMeta> {
  try {
    const raw = Office.context.document.settings.get(SETTINGS_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function writeMetaStore(store: Record<string, LiveUpdateMeta>): Promise<void> {
  Office.context.document.settings.set(SETTINGS_KEY, JSON.stringify(store));
  return new Promise(resolve => {
    Office.context.document.settings.saveAsync(() => resolve());
  });
}

async function saveMeta(meta: LiveUpdateMeta): Promise<void> {
  const store = readMetaStore();
  store[meta.bindingId] = meta;
  await writeMetaStore(store);
}

async function updateMetaRowCount(bindingId: string, outputRowCount: number): Promise<void> {
  const store = readMetaStore();
  if (!store[bindingId]) return;
  store[bindingId].outputRowCount = outputRowCount;
  await writeMetaStore(store);
}

async function forgetMeta(bindingId: string): Promise<void> {
  const store = readMetaStore();
  delete store[bindingId];
  await writeMetaStore(store);
}

// ─── Debounce ──────────────────────────────────────────────────────────────

const debounceTimers = new Map<string, ReturnType<typeof setTimeout>>();

function debounced(bindingId: string, fn: () => void) {
  const existing = debounceTimers.get(bindingId);
  if (existing) clearTimeout(existing);
  debounceTimers.set(bindingId, setTimeout(() => {
    debounceTimers.delete(bindingId);
    fn();
  }, DEBOUNCE_MS));
}

// ─── Registration ──────────────────────────────────────────────────────────

export interface LiveUpdateRegistration {
  panel: PanelKind;
  sourceAddress: string;
  outputSheet: string;
  outputRowCount: number;
  config: LiveConfig;
}

/** Registers a workbook binding over the source range and attaches a debounced onDataChanged handler. Returns the binding id. */
export async function registerLiveUpdate(reg: LiveUpdateRegistration): Promise<string> {
  const bindingId = `qikit-${reg.panel}-${Date.now()}`;

  await Excel.run(async (context) => {
    let address = reg.sourceAddress;
    if (!address.includes('!')) {
      const active = context.workbook.worksheets.getActiveWorksheet();
      active.load('name');
      await context.sync();
      address = `${active.name}!${address}`;
    }
    context.workbook.bindings.add(address, Excel.BindingType.range, bindingId);
    await context.sync();

    const meta: LiveUpdateMeta = { ...reg, sourceAddress: address, bindingId };
    await saveMeta(meta);
    attachHandler(context, bindingId);
    await context.sync();
  });

  return bindingId;
}

function attachHandler(context: Excel.RequestContext, bindingId: string) {
  const binding = context.workbook.bindings.getItemOrNullObject(bindingId);
  binding.onDataChanged.add(() => {
    debounced(bindingId, () => { void handleDataChanged(bindingId); });
    return Promise.resolve();
  });
}

/** Re-attaches onDataChanged handlers for every persisted binding. Called once at add-in startup. */
export async function reattachLiveUpdates(): Promise<void> {
  const store = readMetaStore();
  const ids = Object.keys(store);
  if (ids.length === 0) return;

  await Excel.run(async (context) => {
    const bindings = ids.map(id => ({ id, binding: context.workbook.bindings.getItemOrNullObject(id) }));
    bindings.forEach(b => b.binding.load('id'));
    await context.sync();

    const toForget: string[] = [];
    for (const { id, binding } of bindings) {
      if ((binding as any).isNullObject) {
        toForget.push(id);
      } else {
        attachHandler(context, id);
      }
    }
    await context.sync();

    for (const id of toForget) await forgetMeta(id);
  });
}

async function unregisterLiveUpdate(bindingId: string): Promise<void> {
  await forgetMeta(bindingId);
  try {
    await Excel.run(async (context) => {
      const binding = context.workbook.bindings.getItemOrNullObject(bindingId);
      binding.delete();
      await context.sync();
    });
  } catch {
    // Binding already gone — nothing to clean up.
  }
}

// ─── Recompute on change ───────────────────────────────────────────────────

async function handleDataChanged(bindingId: string): Promise<void> {
  const store = readMetaStore();
  const meta = store[bindingId];
  if (!meta) return;

  let values: any[][];
  try {
    values = await Excel.run(async (context) => {
      const binding = context.workbook.bindings.getItemOrNullObject(bindingId);
      const range = binding.getRange();
      range.load('values');
      await context.sync();
      return range.values as any[][];
    });
  } catch {
    // The bound range (or its sheet) was deleted — drop the live link gracefully.
    await unregisterLiveUpdate(bindingId);
    emit({ type: 'source-deleted', bindingId, panel: meta.panel, sourceAddress: meta.sourceAddress });
    return;
  }

  let outcome;
  try {
    outcome = recompute(meta.panel, values, meta.config);
  } catch (err) {
    emit({
      type: 'recompute-error', bindingId, panel: meta.panel,
      message: err instanceof Error ? err.message : 'Recomputation failed.',
    });
    return;
  }

  try {
    await Excel.run(async (context) => {
      const sheet = context.workbook.worksheets.getItemOrNullObject(meta.outputSheet);
      sheet.load('name');
      await context.sync();
      if ((sheet as any).isNullObject) throw new Error('output-sheet-deleted');
    });

    const rowCountChanged = outcome.sheetData.length !== meta.outputRowCount;
    if (rowCountChanged) {
      await Excel.run(async (context) => {
        const sheet = context.workbook.worksheets.getItem(meta.outputSheet);
        sheet.charts.load('items');
        await context.sync();
        sheet.charts.items.forEach(c => c.delete());
        await context.sync();
      });
    }

    const { rangeAddress } = await writeToSheetRange(meta.outputSheet, outcome.sheetData, meta.outputRowCount);

    if (rowCountChanged) {
      await outcome.writeChart(meta.outputSheet, rangeAddress);
      await updateMetaRowCount(bindingId, outcome.sheetData.length);
    }

    emit({ type: 'updated', bindingId, panel: meta.panel, outputSheet: meta.outputSheet });
  } catch (err) {
    if (err instanceof Error && err.message === 'output-sheet-deleted') {
      await unregisterLiveUpdate(bindingId);
      emit({ type: 'source-deleted', bindingId, panel: meta.panel, sourceAddress: meta.sourceAddress });
      return;
    }
    emit({
      type: 'recompute-error', bindingId, panel: meta.panel,
      message: err instanceof Error ? err.message : 'Failed to write recomputed results.',
    });
  }
}
