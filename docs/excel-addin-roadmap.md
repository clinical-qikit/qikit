# Excel Add-in Improvement Roadmap

*Status: in progress — 2026-07-04, updated 2026-07-10. Phase 0 and Phase 1
are complete; CI (Phase 3, task 3) is live — see
[Phase 3](#phase-3--testing--code-health); the SpcPanel decomposition
(Phase 2, task 2) and consistent styling (Phase 2, task 5 — design tokens,
teal Fluent theme, matching native Excel charts, a11y pass) are done;
Phase 3 tasks 1–2 are partially done (data-prep unit tests, inline numeric
validation). Next up: Phase 2 task 1 (expose funnel/y-percent in the UI) and
the remaining halves of Phase 3 tasks 1–2.*

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

## Phase 1 — Engine parity with Python v0.1.1 ✅ Done

The Python package gained several capabilities in v0.1.1 that the TypeScript
engine lacked or hadn't proven. All three parity items landed 2026-07-08.

**Tasks (all complete)**

1. ~~**Funnel plot mode.**~~ ✅ Ported into `spc-core.ts` (`SPCInput.funnel`):
   stable sort by denominator ascending, runs signals suppressed
   (`runs_disabled` in the summary), p/pp/u/up only. Proven by two shared
   fixtures — `fixtures/spc/funnel_p_chart.json` (clinic readmissions, one
   UCL breach at large n) and `funnel_u_chart.json` (CAUTI per catheter-day,
   one breach at small n) — exercised by both conformance suites. Note: the
   roadmap originally pointed at the CMS sample in `data/examples/` as demo
   data, but that file turned out to contain a provider directory, not
   infections data; the fixtures use crafted clinical scenarios instead.
   (Since fixed: `cms_hospital_infections_sample.csv` now holds real CMS HAI
   data — CLABSI/CAUTI observed cases + device days for 25 hospitals —
   suitable as funnel-plot demo data.)
2. ~~**Laney p′/u′ σ_z validation.**~~ ✅ Audit found this was already proven:
   both Laney fixtures are genuinely overdispersed (implied σ_z ≈ 3.2 / 3.6 —
   plain p/u limits would differ by >2×) and the TS snapshot comparison pins
   every row's UCL/LCL to 5 decimals. Tightened the `check` UCL tolerances
   from ±0.01 to ±0.0001 so the check block pins σ_z explicitly too.
3. ~~**`connect` and y-percent semantics.**~~ ✅ `SPCInput.connect`/`yPercent`
   in, resolved hints out as `SPCResult.connect` (null = infer from x-axis;
   funnel forces false) and `SPCResult.y_percent` (defaults true for p/pp).
   Resolution rules pinned by `packages/engine/tests/display-hints.test.ts`.

**Acceptance:** met — new fixtures pass on both Python and TypeScript, zero
snapshot drift in existing fixtures, `SPCResult` carries everything Phase 2
needs.

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
5. ~~**Consistent styling.**~~ ✅ Done — `src/theme/` now holds a teal
   `BrandVariants` ramp (Fluent controls pick up the brand natively), a
   `qikit` token module (one palette, one gray ramp, one error palette,
   radius/spacing scales, Segoe UI everywhere — Inter/Google Fonts removed),
   and every panel, `ChartViewer`, the dev harness, and
   `excel/chart-builder.ts` import from it, so the native Excel charts match
   the task-pane preview. Manifest `accentColor` aligned to `#107C6C` and the
   previously missing icon PNGs generated (`assets/icon.svg` +
   `scripts/make-icons.mjs`). An accessibility pass (tablist roles, label
   association, `aria-expanded`, named icon buttons) and micro-UX fixes
   (busy states on writes, inline numeric validation via
   `ui/shared/NumericField.tsx`, tooltips on cryptic fields, notes/date
   aggregation limitation surfaced) landed alongside.
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

1. **UI component tests.** *(partially done)* The pure logic layer is now
   covered: `tests/data-prep.test.ts` exercises `parseColumns`,
   `aggregateByPeriod`, `buildSpcInput`, `buildNoteMap`, and `buildSheetRows`
   against the dev-harness dataset shapes (19 tests, no jsdom needed).
   Still open: `@testing-library/react` + jsdom for the components themselves
   (SpcPanel subcomponents, `ParetoPanel`, `BChartPanel`).
2. **Input validation layer.** *(partially done)* `ui/shared/NumericField.tsx`
   now validates numeric option inputs inline (freeze, target, subgroup 2–25,
   CL override, multiply, CUSUM baseline/odds-ratio/limit) instead of silent
   `parseInt`/`parseFloat` coercion. Still open: reporting dropped non-numeric
   cells and denominator > 0 checks at the panel→engine boundary.
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
| Python reference | `src/qikit/spc/` (funnel + Laney logic), `tests/test_conformance.py` |

## Verification strategy

- **Phase 1:** cross-language fixture passes are the acceptance gate — no
  eyeballing chart output as proof of math.
- **Phases 2–3:** dev-harness manual checks plus the new component tests;
  sideload into Excel (`npm run sideload`) for a final end-to-end pass per
  phase.
- **Ongoing:** the Phase 3 CI workflow (`.github/workflows/ci.yml`) is live
  and is now the standing gate for all subsequent work — Phase 1 and Phase 2
  PRs get pytest/vitest/tsc verification for free.
