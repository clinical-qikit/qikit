# Installing QI Kit for Excel

QI Kit for Excel is a task pane add-in. The task pane is a static web page hosted on
GitHub Pages; Excel loads it from there. Installing the add-in means giving Excel a
manifest that points at that page.

## Requirements

Microsoft 365 (subscription) Excel:

- Excel on the web
- Excel on Windows, version 2501 or later
- Excel on Mac, version 16.103 or later

Perpetual Office (Office 2019, 2021, 2024, LTSC), iPad and phones are out of scope.

## What is published

Each release `vX.Y.Z` publishes two copies of the add-in:

| Folder | Changes | Use it to |
|---|---|---|
| `https://clinical-qikit.github.io/qikit/latest/` | on every release | get fixes without doing anything |
| `https://clinical-qikit.github.io/qikit/vX.Y.Z/` | never | pin a version your organization has reviewed |

Each folder holds:

- `qikit-excel-addin.zip`: the app package (manifest plus two icons), for the admin
  center and Teams.
- `manifest.json`: the manifest inside that package, for reading.
- `manifest.xml`: the same add-in as an add-in-only (XML) manifest, for installing
  without an administrator (below).
- the task pane itself (`index.html`, scripts, icons). Opened in a browser it says it
  runs in Excel and links to the demo.
- `demo.html`: the task pane against a mock workbook, to try in a browser without Excel:
  <https://clinical-qikit.github.io/qikit/latest/demo.html>.

## Install for an organization (Microsoft 365 admin center)

This is the route Microsoft recommends for distributing an add-in inside a tenant, and it
needs a Microsoft 365 administrator.

1. Download `qikit-excel-addin.zip` from `latest/` or from a pinned `vX.Y.Z/` folder.
2. In the [Microsoft 365 admin center](https://admin.microsoft.com), go to
   **Settings → Integrated apps → Upload custom apps**.
3. Upload the zip and choose who gets it: specific users, groups, or everyone.
4. Users find **QI Kit** as a tab on the Excel ribbon. It may not appear immediately;
   closing and reopening Excel helps.

With the `latest/` package, new releases reach users automatically: the manifest
points at `latest/`, so the task pane updates with no new upload. With a pinned package,
users stay on that version until an administrator uploads a newer pinned package.

## Install for yourself

Many organizations, hospitals especially, turn off installing add-ins without IT. Each
route below depends on a different setting, so one may work where another is blocked. If
none does, ask IT to use the admin center route above.

**Teams upload** (uses `qikit-excel-addin.zip`). In Teams, open **Apps → Manage your
apps → Upload an app → Upload a custom app** and choose the zip, then open Excel. If
there is no **Upload an app** button, or it offers only **Submit an app to your org**
(which sends it to IT for approval), personal uploads are off.

**Upload in Excel** (uses `manifest.xml`). In a workbook, **Home → Add-ins → More
Add-ins → My Add-ins → Upload My Add-in**, and choose `manifest.xml` from `latest/`. If
**More Add-ins** is greyed out with a workbook open and you signed in, your organization
has turned this off.

**Sideload on a Mac** (uses `manifest.xml`). Save `manifest.xml` into
`~/Library/Containers/com.microsoft.Excel/Data/Documents/wef` (create the `wef` folder if
it is missing) and restart Excel.

**Sideload on Windows** (uses `manifest.xml`). This is the developer route Microsoft's
tools use; it needs no admin rights but works around the add-in settings above, so check
your organization's policy first. Save `manifest.xml` somewhere on the computer, then in
Command Prompt:

```
reg add "HKCU\Software\Microsoft\Office\16.0\WEF\Developer" /v a3880040-4930-41dc-8eab-b2f2c56252e8 /t REG_SZ /d "C:\path\to\manifest.xml"
```

Restart Excel. To remove it, delete that registry value. An organization that blocks web
add-ins entirely blocks this too.

In every route the QI Kit tab appears on the ribbon and the task pane loads from
`latest/`, so it updates with each release.

## Host it yourself

To keep everything on your own servers (an intranet, Azure Static Web Apps, IIS):

```bash
cd excel-addin
npm ci
npm run build
node scripts/manifest.mjs prod https://your.server/qikit/ dist
```

Copy `dist/` to `https://your.server/qikit/`. The build uses relative paths, so any
folder works. The server must use HTTPS with a certificate your users' machines trust.
The last command writes `dist/manifest.json`, `dist/qikit-excel-addin.zip` and
`dist/manifest.xml` pointing at your URL; distribute them by the routes above.

## Develop

```bash
cd excel-addin
npm install
npm run dev        # HTTPS dev server on https://localhost:3000
npm run sideload   # opens Excel with manifest.json (the dev manifest) installed
```

Without Excel, open `https://localhost:3000/demo.html` (or `npm run dev:no-https` and
`http://localhost:3000/demo.html`) for the task pane against a mock workbook. The mock
replaces Office.js's globals when it loads, so only `demo.html` may import
`dev-harness.tsx`; `npm run build` fails if the task pane's scripts contain it.

The dev manifest has its own id and is named "QI Kit (dev)", so it installs beside a
released copy. `manifest.json` is generated from `manifest.template.json`: edit the
template, then run `npm run manifest`. `npm run validate` checks that `manifest.json` is
current and passes Microsoft's validator and the published schema; CI runs it.

## Releasing

Pushing a release tag `vX.Y.Z` (see the root README) runs
`.github/workflows/addin-pages.yml`, which tests, builds, and publishes `vX.Y.Z/` and
`latest/` to the `gh-pages` branch. The add-in's version is the Python package's version.

One-time setup: in the repository's **Settings → Pages**, choose **Deploy from a
branch**, branch `gh-pages`, folder `/ (root)`. The branch exists after the workflow's
first run. To publish a tag that existed before Pages was enabled, run the workflow by
hand with that tag.

## Privacy

QI Kit for Excel does all its calculation in the task pane, on your computer. It sends no
workbook data anywhere: it makes no network requests of its own, has no telemetry, and
uses no accounts or sign-in.

- The task pane's files come from GitHub Pages (or your own server, if you host it).
  GitHub serves them like any website and sees the request, not your data.
- Office.js, Microsoft's add-in library, is loaded from Microsoft's CDN
  (`appsforoffice.microsoft.com`), as for every Office add-in.
- Live updates store which ranges are linked to which charts in the workbook's own
  settings, so the information travels with the workbook and nowhere else.

The source is open at <https://github.com/clinical-qikit/qikit> for review.

## Troubleshooting

- **Blank task pane**: the page did not load. Open the task pane's URL from the manifest
  in a browser; if it fails there, the hosting is the problem.
- **QI Kit tab missing**: check the Excel version against the requirements above, then
  close and reopen Excel. Admin center deployments can take a while to reach users.
- **Old version after a release**: GitHub Pages caches pages for a few minutes. Closing
  and reopening the task pane picks up the new version, shown next to the title.
