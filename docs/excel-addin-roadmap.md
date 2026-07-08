# Excel Add-in Improvement Roadmap

*Status: in progress — 2026-07-04, updated 2026-07-07. Phase 0 landed; CI
(Phase 3, task 3) is live — see [Phase 3](#phase-3--testing--code-health);
the SpcPanel decomposition (Phase 2, task 2) is done.*

This roadmap covers the next stretch of work on the QI Kit Excel add-in
(`excel-addin/`). It prioritizes three things, in order: (1) landing the
in-flight Phase 4 work, (2) closing the feature gap with the Python package
(clinical-qikit v0.1.1), and (3) paying down UX and testing debt so the add-in
can evolve safely.

Guiding principle, unchanged from the rest of the project: **the engine math is
the contract, and shared JSON fixtures in `fixtures/` prove it on both
languages.** New engine behavior lands with a fixture before it lands with a UI.

---

## Phase 0 — Land the in-flight work (baseline hygiene) ✅ Done

The working tree carried a large uncommitted diff (SpcPanel rewrite, new
Pareto/B-chart panels, expanded `chart-builder.ts`, dev-harness mock datasets,
`data/examples/` datasets). This has since landed across several commits
(`1085626` through `b66c616`), `show95` is fully wired into `ChartViewer.tsx`
(1σ/2σ bands render when the checkbox is on), and `git status` is clean.

**Tasks (all complete)**

1. ~~Verify green before committing~~ — `npm test`, `tsc --noEmit` (both
   packages), and `uv run pytest tests/` are all green, and are now enforced
   automatically by CI (see Phase 3).
2. ~~Resolve the `show95` option~~ — finished, not removed: `ChartViewer.tsx`
   draws the bands when `show95` is set.
3. ~~Commit in logical units~~ — done via the commit history above.

**Acceptance:** met — clean `git status`, all three test/typecheck commands
green, no dead options in the SPC panel.

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
2. ~~**Decompose `SpcPanel.tsx`**~~ ✅ Done — pulled forward ahead of task 1 so
   the funnel/y-percent toggles land in small components instead of growing
   the monolith. `SpcPanel.tsx` is now a ~300-line orchestrator; the roadmap's
   named subcomponents (`ColumnSelector`, `DateAggregationOptions`,
   `LimitOptions`, `SignalMethodPicker`) plus `ChartTypePicker`,
   `AnnotationEditor`, and `SummaryPanel` live alongside it in `ui/spc/`.
   Pure logic (date bucketing, column parsing, `buildSpcInput`,
   `buildSheetRows`) moved to `ui/spc/data-prep.ts` with no React imports —
   that module is the target surface for the Phase 3 component tests.
   Verified in the dev harness: chart-type switching, settings, annotation
   round-trip, and summary all behave as before; `tsc --noEmit` and vitest
   green.
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
in sideloaded Excel; ~~SpcPanel file under ~400 LOC with logic pushed into
subcomponents~~ (met — 297 lines); settings survive closing and reopening the
task pane.

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
3. ~~**CI.**~~ ✅ Done — [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
   runs a `python` job (`uv sync --extra dev` + `uv run pytest tests/`) and a
   `node` job (`tsc --noEmit` in both `packages/engine` and `packages/addin`,
   then `npm test`) on every push/PR to `main`. Cross-language fixture drift
   is now caught automatically instead of manually. Pulled forward ahead of
   items 1–2 since it was cheap and everything else in this roadmap is safer
   with it in place.

**Acceptance:** CI green on main ✅; UI test suite exists and runs in CI
(pending — items 1–2 above); invalid data produces a readable message in the
panel, never a NaN chart (pending).

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
| UI | `excel-addin/packages/addin/src/ui/spc/` (SpcPanel + subcomponents, `data-prep.ts`), `ui/shared/ChartViewer.tsx` |
| Excel integration | `excel-addin/packages/addin/src/excel/chart-builder.ts`, `excel/excel-io.ts` |
| Dev | `excel-addin/packages/addin/src/dev-harness.tsx` |
| Python reference | `src/qikit/spc.py` (funnel + Laney logic), `tests/test_conformance.py` |

## Verification strategy

- **Phase 1:** cross-language fixture passes are the acceptance gate — no
  eyeballing chart output as proof of math.
- **Phases 2–3:** dev-harness manual checks plus the new component tests;
  sideload into Excel (`npm run sideload`) for a final end-to-end pass per
  phase.
- **Ongoing:** the Phase 3 CI workflow (`.github/workflows/ci.yml`) is live
  and is now the standing gate for all subsequent work — Phase 1 and Phase 2
  PRs get pytest/vitest/tsc verification for free.
