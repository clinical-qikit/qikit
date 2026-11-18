// What a user can paste into an issue when something goes wrong: the add-in and Excel
// versions, the panel, and the error. Built on demand and only ever copied to the
// clipboard; nothing is sent anywhere. No cell values are included, though an error
// message can name a column.

import { VERSION } from '../../version';

/** An error shown in a panel: the message the user sees, and what caused it. */
export interface PanelError {
  message: string;
  cause?: unknown;
}

/** What panels keep in their error state: a plain message, or one with its cause. */
export type ErrorState = string | PanelError | null;

/** For a catch block: the error's message (or `fallback`), keeping the error for details. */
export function panelError(err: unknown, fallback: string): PanelError {
  const message = err instanceof Error && err.message ? err.message : fallback;
  return { message, cause: err };
}

export function errorMessage(error: ErrorState): string {
  return error == null ? '' : typeof error === 'string' ? error : error.message;
}

function officeInfo(): string {
  try {
    const d = typeof Office !== 'undefined' ? Office.context?.diagnostics : undefined;
    if (d) return `${d.host} ${d.platform} ${d.version}`;
  } catch {
    // Outside Office, or Office.js not ready.
  }
  return 'not reported (outside Excel?)';
}

function causeText(cause: unknown, depth = 0): string[] {
  if (cause == null || depth > 3) return [];
  const label = depth === 0 ? 'Error' : 'Caused by';
  if (cause instanceof Error) {
    const lines = [`${label}: ${cause.name}: ${cause.message}`];
    // Office.js errors carry a code and debug info that say which call failed.
    const office = cause as Error & { code?: string; debugInfo?: unknown; cause?: unknown };
    if (office.code) lines.push(`Code: ${office.code}`);
    if (office.debugInfo) {
      try { lines.push(`Debug info: ${JSON.stringify(office.debugInfo)}`); } catch { /* circular */ }
    }
    if (cause.stack) lines.push('', 'Stack:', cause.stack);
    // excel-io rewraps Office.js errors in a plainer message and keeps the original here.
    if (office.cause != null) lines.push('', ...causeText(office.cause, depth + 1));
    return lines;
  }
  return [`${label}: ${String(cause)}`];
}

export function errorDetails(opts: {
  panel: string;
  error: ErrorState;
  componentStack?: string | null;
  now?: Date;
}): string {
  const cause = typeof opts.error === 'object' && opts.error ? opts.error.cause : undefined;
  const lines = [
    `QI Kit for Excel ${VERSION}`,
    `Panel: ${opts.panel}`,
    `Message: ${errorMessage(opts.error)}`,
    `Excel: ${officeInfo()}`,
    `Browser: ${typeof navigator !== 'undefined' ? navigator.userAgent : 'unknown'}`,
    `Time: ${(opts.now ?? new Date()).toISOString()}`,
    ...causeText(cause),
  ];
  if (opts.componentStack) lines.push('', 'Components:', opts.componentStack.trim());
  return lines.join('\n');
}

/** Copies text to the clipboard; false when the browser refuses (some Office hosts do). */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Fall through: the async clipboard is often blocked inside Office's web view.
  }
  try {
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(area);
    return ok;
  } catch {
    return false;
  }
}
