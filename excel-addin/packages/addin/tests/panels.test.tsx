// @vitest-environment jsdom
//
// Component tests: the whole task pane, rendered inside the demo harness (whose import
// installs the mock workbook), driven the way a user would. Chart.js needs a real canvas,
// so its React wrappers are stubbed; everything else is the shipped code.

import React from 'react';
import { describe, it, expect, vi, afterEach, beforeAll } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react';

vi.mock('react-chartjs-2', () => {
  const Stub = (props: any) => <div data-testid="chart" data-type={props.type ?? ''} />;
  return { Line: Stub, Bar: Stub, Chart: Stub, Scatter: Stub };
});

import { DevHarness } from '../src/dev-harness';
import { Root } from '../src/root';
import { PanelErrorBoundary } from '../src/ui/shared/PanelErrorBoundary';
import { errorDetails, panelError } from '../src/ui/shared/error-report';
import { VERSION } from '../src/version';

beforeAll(() => {
  // jsdom lacks these; Fluent UI and the panels touch them.
  (window as any).ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} };
  window.matchMedia ??= ((q: string) => ({
    matches: false, media: q, onchange: null, addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {}, dispatchEvent: () => false,
  })) as any;
  window.HTMLElement.prototype.scrollIntoView ??= () => {};
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

function renderPane(dataset: string) {
  render(<DevHarness><Root /></DevHarness>);
  // Choosing a dataset also resets the mock workbook, so each test starts clean.
  // The harness's dataset menu is the first select on the page.
  fireEvent.change(screen.getAllByRole('combobox')[0], { target: { value: dataset } });
}

function openTab(name: string) {
  fireEvent.click(screen.getByRole('tab', { name }));
}

const noAlerts = () => expect(screen.queryByRole('alert')).toBeNull();

describe('SPC panel', () => {
  it('charts the selection, says what it found, and writes to a sheet', async () => {
    renderPane('continuous');
    fireEvent.click(screen.getByRole('button', { name: 'Use Current Selection' }));
    expect(await screen.findByText('No signal: the process looks stable.')).toBeTruthy();
    expect(screen.getAllByTestId('chart').length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole('button', { name: 'Write to Sheet' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Write to Sheet' })).toHaveProperty('disabled', false));
    noAlerts();
  });

  it('loads the sample data and finds its shifts', async () => {
    renderPane('continuous');
    fireEvent.click(screen.getByRole('button', { name: 'Try with sample data' }));
    expect(await screen.findByText('Signal.')).toBeTruthy();
    expect(screen.getByText(/A shift: 12 points in a row above the center line, Jan 2025 to Dec 2025\./)).toBeTruthy();
    noAlerts();
  });

  it('shows a failed Excel call with Copy details', async () => {
    renderPane('continuous');
    const run = (window as any).Excel.run;
    vi.spyOn((window as any).Excel, 'run').mockImplementationOnce(async () => {
      const err = new Error('The requested resource does not exist.') as Error & { code: string };
      err.code = 'ItemNotFound';
      throw err;
    });
    fireEvent.click(screen.getByRole('button', { name: 'Use Current Selection' }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('The requested resource does not exist.');

    fireEvent.click(within(alert).getByRole('button', { name: 'Show details' }));
    const details = (within(alert).getByLabelText('Error details') as HTMLTextAreaElement).value;
    expect(details).toContain(`QI Kit for Excel ${VERSION}`);
    expect(details).toContain('Panel: SPC');
    expect(details).toContain('Code: ItemNotFound');
    (window as any).Excel.run = run;
  });
});

describe('Pareto panel', () => {
  it('counts the categories and writes to a sheet', async () => {
    renderPane('categorical');
    openTab('Pareto');
    fireEvent.click(screen.getByRole('button', { name: 'Use Current Selection' }));
    await screen.findByRole('button', { name: 'Write to Sheet' });
    expect(screen.getByTestId('chart')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Write to Sheet' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Write to Sheet' })).toHaveProperty('disabled', false));
    noAlerts();
  });
});

describe('Bernoulli CUSUM panel', () => {
  it('computes from 0/1 outcomes and writes to a sheet', async () => {
    renderPane('binary');
    openTab('Bernoulli CUSUM');
    fireEvent.click(screen.getByRole('button', { name: 'Use Current Selection' }));
    expect((await screen.findByRole('status')).textContent).toMatch(/Signal detected|No signal/);
    fireEvent.click(screen.getByRole('button', { name: 'Write to Sheet' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Write to Sheet' })).toHaveProperty('disabled', false));
    noAlerts();
  });
});

describe('Planned Experimentation panel', () => {
  it('designs a 2×2 experiment, writes the template, and analyzes the results', async () => {
    renderPane('continuous');
    openTab('Planned Experimentation');
    fireEvent.click(screen.getByRole('button', { name: 'Generate Design' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Write Template' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Write Template' })).toHaveProperty('disabled', false));
    noAlerts();

    // The user fills in Response and selects the table: A has an effect of 10.
    const filled = [
      ['RunOrder', 'A', 'B', 'Response'],
      [1, -1, -1, 10], [2, 1, -1, 20], [3, -1, 1, 12], [4, 1, 1, 22],
    ];
    const excel = (window as any).Excel;
    const run = excel.run;
    vi.spyOn(excel, 'run').mockImplementationOnce((cb: any) => run(async (ctx: any) => {
      ctx.workbook.getSelectedRange = () => ({
        load() {}, values: filled, numberFormat: filled.map(r => r.map(() => 'General')),
        address: "'DOE 2F'!A1:D5",
      });
      return cb(ctx);
    }));
    fireEvent.click(screen.getByRole('button', { name: 'Read Results' }));
    await screen.findByRole('button', { name: 'Write to Sheet' });
    noAlerts();
    fireEvent.click(screen.getByRole('button', { name: 'Write to Sheet' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Write to Sheet' })).toHaveProperty('disabled', false));
    noAlerts();
  });

  it('says why when the selection does not match the design', async () => {
    renderPane('continuous');
    openTab('Planned Experimentation');
    fireEvent.click(screen.getByRole('button', { name: 'Generate Design' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Read Results' }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain("No 'Response' column found");
    expect(within(alert).getByRole('button', { name: 'Copy details' })).toBeTruthy();
  });
});

describe('PanelErrorBoundary', () => {
  it('replaces a crashed panel with the error, Copy details and Reload panel', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const Boom = () => { throw new Error('kaboom'); };
    render(<PanelErrorBoundary panel="Pareto"><Boom /></PanelErrorBoundary>);
    const alert = screen.getByRole('alert');
    expect(alert.textContent).toContain('Something went wrong in this panel: kaboom');
    fireEvent.click(within(alert).getByRole('button', { name: 'Show details' }));
    const details = (within(alert).getByLabelText('Error details') as HTMLTextAreaElement).value;
    expect(details).toContain('Panel: Pareto');
    expect(details).toContain('Components:');
    expect(screen.getByRole('button', { name: 'Reload panel' })).toBeTruthy();
  });
});

describe('errorDetails', () => {
  it('lists versions, panel and message, and nothing from the workbook', () => {
    const text = errorDetails({
      panel: 'SPC', error: panelError(new TypeError('x is undefined'), 'fallback'),
      now: new Date('2026-11-17T12:00:00Z'),
    });
    expect(text.split('\n').slice(0, 3)).toEqual([`QI Kit for Excel ${VERSION}`, 'Panel: SPC', 'Message: x is undefined']);
    expect(text).toContain('Excel: not reported (outside Excel?)');
    expect(text).toContain('Time: 2026-11-17T12:00:00.000Z');
    expect(text).toContain('Error: TypeError: x is undefined');
  });

  it('uses the fallback when the error has no message', () => {
    expect(panelError('nope', 'Computation failed.').message).toBe('Computation failed.');
  });
});
