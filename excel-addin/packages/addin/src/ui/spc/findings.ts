// Plain-language findings for an SPC result, computed from what the engine returns.
// The verdicts and the notes use the same wording as the Python package (SPCResult's
// __str__ and qic()'s summary["notes"], src/qikit/spc.py), so the two read alike.

import { SPCResult } from '@qikit/engine';

/** Fewer baseline points than this and the chart cannot be called stable (Python MIN_POINTS). */
export const MIN_POINTS = 12;
/** Fewer than this and control limits are provisional (Python MIN_LIMIT_POINTS). */
export const MIN_LIMIT_POINTS = 20;

export interface Findings {
  /** One sentence: signal, no signal, or too few points to say. */
  verdict: string;
  /** True when a signal was found. */
  signal: boolean;
  /** What was found, one sentence each. */
  details: string[];
  /** What limits how far the chart can be trusted. */
  notes: string[];
}

interface FindingsContext {
  /** x-axis labels, one per point, when there are any. */
  xLabels?: string[];
  /** The Freeze baseline setting (points used for the center line), if set. */
  freeze?: number;
  /** Phase boundaries (1-based start points), if set. */
  part?: number[];
}

function pointName(i: number, labels?: string[]): string {
  const label = labels?.[i];
  return label ? label : `point ${i + 1}`;
}

function listNames(idx: number[], labels?: string[], max = 4): string {
  const names = idx.slice(0, max).map(i => pointName(i, labels));
  const more = idx.length - names.length;
  return more > 0 ? `${names.join(', ')} and ${more} more` : names.join(', ');
}

/** Number of baseline points: those that set the center line of the last phase. */
export function baselineCount(result: SPCResult, ctx: FindingsContext): number {
  const finite = result.data.map(d => typeof d.y === 'number' && isFinite(d.y));
  if (ctx.freeze) return finite.slice(0, ctx.freeze).filter(Boolean).length;
  const starts = (ctx.part ?? []).filter(p => p > 0 && p <= finite.length);
  const lastStart = starts.length ? Math.max(...starts) - 1 : 0;
  return finite.slice(lastStart).filter(Boolean).length;
}

/** Consecutive runs of points flagged by the runs rules, with their side of the center line. */
function flaggedRuns(result: SPCResult): { start: number; end: number; side: 'above' | 'below' }[] {
  const runs: { start: number; end: number; side: string }[] = [];
  result.data.forEach((d: any, i) => {
    if (!d.runs_signal_localized) return;
    const side = d.y > d.cl ? 'above' : 'below';
    const last = runs[runs.length - 1];
    if (last && last.end === i - 1 && last.side === side) last.end = i;
    else runs.push({ start: i, end: i, side });
  });
  return runs.map(r => ({ ...r, side: r.side as 'above' | 'below' }));
}

export function describeFindings(result: SPCResult, ctx: FindingsContext = {}): Findings {
  const s = result.summary ?? {};
  const labels = ctx.xLabels;
  const details: string[] = [];

  const beyond = result.data.flatMap((d: any, i) => (d.sigma_signal ? [i] : []));
  if (beyond.length === 1) {
    details.push(`1 point is outside the control limits: ${listNames(beyond, labels)}.`);
  } else if (beyond.length > 1) {
    details.push(`${beyond.length} points are outside the control limits: ${listNames(beyond, labels)}.`);
  }

  if (result.method === 'anhoej') {
    // Anhøj marks exactly the points in runs longer than the limit: each is a shift.
    for (const run of flaggedRuns(result)) {
      const n = run.end - run.start + 1;
      const span = `${pointName(run.start, labels)} to ${pointName(run.end, labels)}`;
      details.push(`A shift: ${n} points in a row ${run.side} the center line, ${span}.`);
    }
    if (s.crossings_signal) {
      const crosses = s.n_crossings === 0 ? 'never crosses the center line'
        : s.n_crossings === 1 ? 'crosses the center line only once'
        : `crosses the center line only ${s.n_crossings} times`;
      details.push(
        `The line ${crosses} (fewer than ` +
        `${s.n_crossings_min} is a signal): the points cluster or drift rather than vary at random.`);
    }
  } else {
    // Other rule sets mix shifts, trends and zone patterns; name the points, not the pattern.
    const flagged = result.data.flatMap((d: any, i) => (d.runs_signal ? [i] : []));
    if (flagged.length > 0) {
      details.push(
        `${flagged.length} point(s) form a pattern the ${result.method.toUpperCase()} rules flag: ` +
        `${listNames(flagged, labels)}.`);
    }
  }

  const nBaseline = baselineCount(result, ctx);
  const provisional = nBaseline < MIN_POINTS;
  const notes: string[] = [];
  if (provisional) {
    notes.push(
      `Only ${nBaseline} point(s) set the center line: too few to judge whether the ` +
      `process is stable. Collect at least ${MIN_POINTS} before reading this chart as ` +
      `stable or as changed.`);
  } else if (result.chart_type !== 'run' && nBaseline < MIN_LIMIT_POINTS) {
    notes.push(
      `The control limits rest on ${nBaseline} points: treat them as provisional ` +
      `until there are ${MIN_LIMIT_POINTS} or more.`);
  }
  if (ctx.freeze) {
    notes.push(
      `The center line and limits come from the first ${ctx.freeze} points ` +
      `(Freeze baseline); later points are judged against them.`);
  }

  const signal = !!result.signals;
  const verdict = signal ? 'Signal.'
    : provisional ? 'No signal so far, with too few points to call the process stable.'
    : 'No signal: the process looks stable.';
  return { verdict, signal, details, notes };
}
