# Excel add-in: scope and plan for broad use

*Written 2026-11-16. Replaces the July 2026 improvement roadmap, whose finished phases
are in the git history.*

## Scope: the engine is frozen

The TypeScript engine (`excel-addin/packages/engine`) does not follow the Python package
any further. Python is where new methods go; the add-in is a fixed, supported subset.

**In the add-in:** run and control charts (run, I, MR, X̄, S, P, U, C, IP, G, T, Laney
P′ and U′) with the Anhøj, IHI, WECO and Nelson rules; Pareto charts; Bernoulli CUSUM;
two-level designed experiments.

**Python only, and staying there:** `funnel()` and everything built on it (p-values and
FDR, shrinkage estimates, reliability and minimum denominators, benchmarks, rollups),
NHS Making Data Count rules, faceting, and `brief()`/`to_table()`. The engine still
contains an early funnel mode; it is not shown in the task pane and should not be, since
its answers no longer match `funnel()`.

**What frozen still requires:**

- The shared fixtures (`fixtures/spc`, `fixtures/experiment`) keep passing in both
  languages. CI runs both.
- A bug in math the two engines share is fixed in both, in one change, with a fixture.
- A Python-only feature adds no fixture to the shared directories.

## Where the add-in stands

Working: four panels, native Excel charts that match the preview, live updates when the
source range changes, a browser dev harness, 258 tests, type checks and tests in CI. The
production build is about 190 kB gzipped.

What stops someone outside this repository from using it:

1. **Nothing is hosted.** The manifest points at `https://localhost:3000`. There is no
   published task pane, so installing means cloning the repo and running a dev server.
2. **The manifest is a development one.** It is a unified (JSON) manifest on the
   `devPreview` schema with a non-GUID id. Microsoft's support table
   (unified-manifest-overview, October 2026) lists Excel on the web, Windows Microsoft
   365 from version 2501 and Mac from 16.103, and says no for perpetual Office on
   Windows and for mobile. The intended users are all on Microsoft 365, so the JSON
   manifest is enough once it is on a released schema.
3. **The build is not deployable as it stands.** `vite build` emits the task pane but
   not the icons or a manifest, and nothing in CI builds or publishes it.
4. **`docs/deployment.md` describes a different add-in**: an XML `<SourceLocation>` and
   a `taskpane.html` that do not exist here.
5. **First-run experience.** A new user gets an empty pane and "Use Current Selection".
   There is no sample data, no guidance on which chart fits their data, and settings are
   forgotten when the pane closes.
6. **Input handling.** Dates are recognized by a serial-number range (25569–60000), so a
   column of large counts can be read as dates. Dropped non-numeric cells and zero
   denominators are not reported.
7. **No way to hear about failures**, and no privacy statement, which an IT reviewer will
   ask for. The add-in sends no data anywhere; that needs saying where they will look.

## Plan

Ordered so that each step is usable on its own. Steps 1 and 2 are what "broad use"
actually depends on; the rest make it good.

### 1. Make it installable (about a week)

- **Host the task pane on GitHub Pages** from a workflow that builds on each release tag
  and publishes `dist/` with the icons. A versioned path per release plus `latest`, so
  an organization can pin.
- **Keep the unified (JSON) manifest only** and make it a production one: a released
  schema version instead of `devPreview`, a real GUID, the hosted URLs, a support URL,
  and ExcelApi requirement sets that match the APIs used (bindings and chart series
  need ExcelApi 1.7 or so; confirm by test). No XML manifest: every intended user is on
  Microsoft 365, and perpetual Office and mobile are out of scope.
- **Generate the manifest from one template** (dev → localhost, production → Pages)
  and validate both outputs in CI with `office-addin-manifest validate`.
- **Rewrite `docs/deployment.md`** around three routes: sideload from the hosted
  manifest (one person), Microsoft 365 admin center centralized deployment (an
  organization), and self-hosting `dist/` on an intranet.
- **Version the add-in with the package**, shown in the task pane footer.

Done when a person with no repository access can install from a URL in five minutes on
Windows, Mac and Excel on the web.

### 2. Make the first five minutes work (about a week)

- **Sample data.** "Try with sample data" writes one of the `data/examples` sets to a
  new sheet and charts it. The dev harness already carries the datasets.
- **Chart chooser.** Three plain questions (counting events or measuring? is there a
  denominator? subgroups?) pick the chart type, with the full list still available.
  Default to a run chart when unsure, as the Python docs advise.
- **Plain-language findings.** The summary panel says what was found ("a shift of 9
  points below the median starting March") and warns under 12 baseline points, the
  same wording as Python's `summary["notes"]`.
- **Remember settings** per workbook (`Office.context.document.settings`), with
  `localStorage` in the harness.
- **Honest input handling.** Use the range's number formats to recognize dates; list
  the rows that were skipped and why; refuse a zero denominator with a message.

Done when a quality-improvement nurse with a two-column sheet gets a correct chart and
a sentence about it without reading documentation.

### 3. Make it trustworthy to IT and to the next maintainer (several days)

- **Privacy and security page**: all computation is local to the task pane, no network
  calls after load, no telemetry. Link it from the manifest.
- **Content Security Policy** on the hosted page, and Office.js as the only external
  script.
- **Component tests** (`@testing-library/react` + jsdom) for the four panels, and one
  end-to-end pass through the dev harness in CI.
- **Drop the dev harness from the production bundle**, or keep it deliberately as the
  public demo at a separate path. The second is the better use: a live demo needs no
  Excel.
- **An error panel with "copy details"** so a user can paste what went wrong into an
  issue.

### 4. Reach (optional, after 1–3)

- **Microsoft Marketplace (AppSource) listing.** It is the only route for individuals
  whose organization blocks sideloading, and it requires validation, a support URL and
  a privacy policy, which steps 1 and 3 produce.
- **PNG export** of the preview, and y-axis percent on proportion charts.
- **Tables that grow**: bind live updates to an Excel table so appended rows are picked
  up, instead of a fixed range.

### Not planned

Funnels, NHS rules, faceted charts, custom functions (`=QIKIT.*`), EWMA and short-run
charts. Funnels and NHS rules live in Python by decision; the rest have no evidence of
demand yet.

## Key files

| Area | Files |
|---|---|
| Engine | `excel-addin/packages/engine/src/` |
| Shared fixtures | `fixtures/spc/`, `fixtures/experiment/` |
| Task pane | `excel-addin/packages/addin/src/ui/` |
| Excel integration | `excel-addin/packages/addin/src/excel/` |
| Manifest and build | `excel-addin/manifest.json`, `excel-addin/vite.config.ts` |
| Deployment guide | `docs/deployment.md` |
