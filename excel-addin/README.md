# QI Kit — Excel Add-in

Task-pane add-in bringing [clinical-qikit](../README.md)'s SPC charts, Pareto
analysis, Bernoulli CUSUM, and planned experimentation (DOE) into Excel.

npm-workspaces monorepo:

| Package | What it is |
|---|---|
| `packages/engine` | TypeScript port of the Python engine's math. Pure, no Office.js. Proven equivalent to Python via the shared JSON fixtures in [`../fixtures/`](../fixtures). |
| `packages/addin` | React 18 + Fluent UI v9 task pane. Reads ranges and writes sheets/charts via Office.js. |

## Development

```bash
npm install

# Browser dev harness — no Excel needed (mocks Office.js, 4 sample datasets)
npm run dev:no-https        # http://localhost:3000
npm run dev                 # same, with HTTPS via mkcert (needed for sideload)

# Tests + type checks (same gates CI runs)
npm test
npx tsc --noEmit -p packages/engine
npx tsc --noEmit -p packages/addin
```

The dev harness (`packages/addin/src/dev-harness.tsx`) renders the task pane
in a 370px emulator with mock datasets for every panel — it is the fastest way
to iterate on UI.

## Sideloading into Excel

```bash
npm run dev        # HTTPS dev server on :3000 (the manifest points here)
npm run sideload   # opens Excel with manifest.json registered
```

`sideload`/`validate` use the `office-addin-debugging` / `office-addin-manifest`
CLIs (run them via `npx` if not installed). See
[`../docs/deployment.md`](../docs/deployment.md) for production hosting.

## Design tokens

All colors, fonts, and radii live in `packages/addin/src/theme/`:
`tokens.ts` (the `qikit` object — the only place hex values are allowed),
`palette.ts` (Fluent `BrandVariants` teal ramp), and `fluent-theme.ts`.
Chart.js previews and the native Excel charts in `src/excel/chart-builder.ts`
import the same `qikit.chart` colors, which is what keeps the written
workbook chart matching the task-pane preview. Icons are generated from
`assets/icon.svg` by `node scripts/make-icons.mjs` (PNGs are committed).

## Engine parity

The engine math is the contract: Python (`src/qikit/`) is authoritative, the
TS engine conforms, and `fixtures/**/*.json` prove it on both sides
(`tests/test_conformance.py` in Python, `packages/engine/tests/conformance.test.ts`
here). Regenerate snapshots with `python scripts/update_snapshots.py` from the
repo root after intentional engine changes.
