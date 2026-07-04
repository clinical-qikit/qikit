# Excel Add-in Improvement Roadmap

*Status: proposed — 2026-07-04*

This roadmap covers the next stretch of work on the QI Kit Excel add-in
(`excel-addin/`). It prioritizes three things, in order: (1) landing the
in-flight Phase 4 work, (2) closing the feature gap with the Python package
(clinical-qikit v0.1.1), and (3) paying down UX and testing debt so the add-in
can evolve safely.

Guiding principle, unchanged from the rest of the project: **the engine math is
the contract, and shared JSON fixtures in `fixtures/` prove it on both
languages.** New engine behavior lands with a fixture before it lands with a UI.

---

## Phase 0 — Land the in-flight work (baseline hygiene)

The working tree currently carries a large uncommitted diff: the SpcPanel
rewrite (~+800 lines), new Pareto and B-chart panels, the expanded
`chart-builder.ts`, dev-harness mock datasets, engine refinements, and the
untracked `data/examples/` datasets. Everything after this phase builds on that
code, so it needs to be verified and committed first.

**Tasks**

1. Verify green before committing:
   - `npm test` in `excel-addin/` (engine + DOE conformance suites, vitest)
   - `tsc --noEmit` in both packages
   - `uv run pytest tests/` at the repo root (confirms no shared-fixture drift)
2. Resolve the `show95` option in `SpcPanel.tsx` — it appears wired into state
   but unused by the renderer. Finish it (draw 1σ/2σ bands in ChartViewer) or
   remove it; don't commit dead UI state.
3. Commit in logical units rather than one blob:
   - engine changes (`packages/engine/src/spc-core.ts`, `signals.ts`, `doe-core.ts`)
   - SpcPanel rewrite + `App.tsx` navigation redesign
   - new `ui/pareto/ParetoPanel.tsx` and `ui/bchart/BChartPanel.tsx` panels
   - `excel/chart-builder.ts` expansion
   - `dev-harness.tsx` mock datasets
   - `data/examples/` sample datasets (plus their READMEs)

**Acceptance:** clean `git status`, all three test/typecheck commands green,
no dead options in the SPC panel.

---

## Phase 1 — Engine parity with Python v0.1.1

The Python package gained several capabilities in v0.1.1 that the TypeScript
engine lacks or hasn't proven. Math first; UI exposure comes in Phase 2.

**Tasks**

1. **Funnel plot mode.** Port from `src/qikit/spc.py` into
   `packages/engine/src/spc-core.ts` for the p/pp/u/up chart types:
   - sort points by denominator ascending (x becomes the unit label)
   - suppress runs-based signals (Anhoej/IHI runs rules don't apply to
     cross-sectional data); sigma signals only
   - add a shared JSON fixture under `fixtures/spc/` exercised by both
     `tests/test_conformance.py` and
     `excel-addin/packages/engine/tests/conformance.test.ts`. The CMS
     infections sample in `data/examples/` is the natural demo dataset.
2. **Laney p′/u′ σ_z validation.** The TS pp/up implementations exist but
   cross-language equality of the σ_z overdispersion calculation has never
   been fixture-proven. Add (or extend) a fixture with known-good `check`
   values; fix the TS side if it drifts.
3. **`connect` and y-percent semantics.** Port the v0.1.1 `connect` parameter
   (explicit line-connectivity control) and y_percent handling into
   `SPCInput`/`SPCResult` (`spc-types.ts`) so the UI can consume them without
   re-deriving.

**Acceptance:** new fixtures pass on both Python and TypeScript; zero snapshot
drift in existing fixtures; `SPCResult` carries everything Phase 2 needs.

---

## Phase 2 — SPC panel UX & robustness

**Tasks**

1. **Expose the parity features.**
   - Funnel-mode toggle in the SPC panel, auto-suggested when the chart type
     is p/pp/u/up and the x column looks categorical rather than temporal.
   - y-percent axis option in `shared/ChartViewer.tsx` and in the native Excel
     charts built by `excel/chart-builder.ts`.
2. **Decompose `SpcPanel.tsx`** (~1,100 LOC) into focused subcomponents:
   `ColumnSelector`, `DateAggregationOptions`, `LimitOptions` (freeze / target
   / manual CL), `SignalMethodPicker`. This is a prerequisite for the Phase 3
   component tests, not just tidiness.
3. **Sturdier data detection.** Replace the Excel-serial-range date heuristic
   (25569–60000) in the column type detector with Office.js
   `Range.valueTypes` + `numberFormat`, and handle blank/NA cells explicitly
   before data reaches the engine.
4. **State persistence.** Persist last-used chart type, signal method, and
   options via `Office.context.document.settings` (workbook-scoped), with a
   localStorage fallback so the dev harness behaves the same.
5. **Consistent styling.** Extract shared design tokens; today SPC uses teal
   `#107C6C` while Pareto/B-chart use purple `#7c3aed`. One palette, one
   spacing scale, applied across all four panels.
6. **Chart export.** PNG export of the Chart.js preview (canvas `toBlob` →
   download) alongside the existing write-to-sheet output.
7. **Error recovery.** Graceful message when the bound range has been deleted
   or moved (instead of a raw Office.js error), and a React error boundary
   around each panel so one crash doesn't blank the task pane.

**Acceptance:** funnel and y-percent usable end-to-end in the dev harness and
in sideloaded Excel; SpcPanel file under ~400 LOC with logic pushed into
subcomponents; settings survive closing and reopening the task pane.

---

## Phase 3 — Testing & code health

**Tasks**

1. **UI component tests.** Add `@testing-library/react` + jsdom environment to
   `packages/addin`'s vitest config. Cover: column auto-detection against the
   dev-harness mock datasets, option changes propagating to `compute()` input,
   and error states — for the SpcPanel subcomponents, `ParetoPanel`, and
   `BChartPanel`. The dev-harness datasets double as test data.
2. **Input validation layer.** Validate at the panel→engine boundary rather
   than letting the engine emit NaNs: numeric coercion with reporting of
   dropped cells, non-negative counts for the CUSUM b-chart, denominator > 0
   for p/u-family charts. Surface failures as user-facing messages.
3. **CI.** GitHub Actions workflow running `tsc --noEmit`, engine + addin
   vitest, and Python pytest on every push, so cross-language fixture drift is
   caught automatically instead of manually.

**Acceptance:** CI green on main; UI test suite exists and runs in CI; invalid
data produces a readable message in the panel, never a NaN chart.

---

## Backlog (not prioritized now)

Worth keeping visible, deliberately out of scope for this roadmap:

- EWMA and short-run SPC chart types
- User-configurable signal thresholds (Nelson/WECO rule parameters)
- Analysis templates (pre-configured chart + method bundles)
- PDF report export
- Faceted (per-group subplot) charts in the task pane

---

## Key files

| Area | Files |
|------|-------|
| Engine | `excel-addin/packages/engine/src/spc-core.ts`, `signals.ts`, `spc-types.ts` |
| Fixtures | `fixtures/spc/` (shared Python ⇄ TypeScript contract) |
| UI | `excel-addin/packages/addin/src/ui/spc/SpcPanel.tsx`, `ui/shared/ChartViewer.tsx` |
| Excel integration | `excel-addin/packages/addin/src/excel/chart-builder.ts`, `excel/excel-io.ts` |
| Dev | `excel-addin/packages/addin/src/dev-harness.tsx` |
| Python reference | `src/qikit/spc.py` (funnel + Laney logic), `tests/test_conformance.py` |

## Verification strategy

- **Phase 1:** cross-language fixture passes are the acceptance gate — no
  eyeballing chart output as proof of math.
- **Phases 2–3:** dev-harness manual checks plus the new component tests;
  sideload into Excel (`npm run sideload`) for a final end-to-end pass per
  phase.
- **Ongoing:** the Phase 3 CI workflow becomes the standing gate for all
  subsequent work.
