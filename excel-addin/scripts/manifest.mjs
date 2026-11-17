// Generates the add-in manifest from manifest.template.json.
// Run from excel-addin/.
//
//   node scripts/manifest.mjs dev            write manifest.json (https://localhost:3000/)
//   node scripts/manifest.mjs dev --check    fail if manifest.json is out of date
//   node scripts/manifest.mjs prod <base-url> <out-dir>
//       write <out-dir>/manifest.json and <out-dir>/qikit-excel-addin.zip, the package
//       that the Microsoft 365 admin center and Teams "Upload a custom app" accept
//       (manifest.json plus the two app icons).
//
// The version is the Python package's (src/qikit/__init__.py), so one tag versions both.
// Dev and production use different ids and names so a developer can sideload the dev
// add-in beside an installed release.
import { execFileSync } from 'node:child_process';
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');

const IDS = {
  prod: 'a3880040-4930-41dc-8eab-b2f2c56252e8',
  dev: 'cfdedcc5-e8c1-49b8-9c8f-95003049476a',
};
const APP_ICONS = ['icon-color-192.png', 'icon-outline-32.png'];

export function packageVersion() {
  const init = readFileSync(path.join(root, '..', 'src', 'qikit', '__init__.py'), 'utf8');
  const match = init.match(/^__version__ = "(\d+\.\d+\.\d+)"$/m);
  if (!match) throw new Error('No n.n.n __version__ in src/qikit/__init__.py');
  return match[1];
}

export function renderManifest(env, baseUrl) {
  if (!/^https:\/\/.+\/$/.test(baseUrl)) {
    throw new Error(`Base URL must be https and end with "/": ${baseUrl}`);
  }
  const values = {
    VERSION: packageVersion(),
    ID: IDS[env],
    NAME_SUFFIX: env === 'dev' ? ' (dev)' : '',
    BASE_URL: baseUrl,
  };
  const template = readFileSync(path.join(root, 'manifest.template.json'), 'utf8');
  const text = template.replace(/\{\{(\w+)\}\}/g, (_, key) => {
    if (!(key in values)) throw new Error(`Unknown placeholder {{${key}}}`);
    return values[key];
  });
  JSON.parse(text); // the template must stay valid JSON after substitution
  return text;
}

function main(argv) {
  const [env, ...rest] = argv;
  if (env === 'dev') {
    const target = path.join(root, 'manifest.json');
    const text = renderManifest('dev', 'https://localhost:3000/');
    if (rest.includes('--check')) {
      const current = readFileSync(target, 'utf8');
      if (current !== text) {
        console.error('manifest.json is out of date; run: node scripts/manifest.mjs dev');
        process.exit(1);
      }
      return;
    }
    writeFileSync(target, text);
    console.log(`wrote ${target}`);
    return;
  }
  if (env === 'prod' && rest.length === 2) {
    const [baseUrl, outDir] = rest;
    const text = renderManifest('prod', baseUrl);
    mkdirSync(outDir, { recursive: true });
    writeFileSync(path.join(outDir, 'manifest.json'), text);

    // Zip with the files at the archive root, as the package format requires.
    const staging = mkdtempSync(path.join(tmpdir(), 'qikit-manifest-'));
    try {
      writeFileSync(path.join(staging, 'manifest.json'), text);
      for (const icon of APP_ICONS) copyFileSync(path.join(root, 'assets', icon), path.join(staging, icon));
      const zip = path.resolve(outDir, 'qikit-excel-addin.zip');
      rmSync(zip, { force: true });
      execFileSync('zip', ['-q', '-X', zip, 'manifest.json', ...APP_ICONS], { cwd: staging });
      console.log(`wrote ${path.join(outDir, 'manifest.json')} and ${zip}`);
    } finally {
      rmSync(staging, { recursive: true, force: true });
    }
    return;
  }
  console.error('usage: manifest.mjs dev [--check] | manifest.mjs prod <base-url> <out-dir>');
  process.exit(2);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) main(process.argv.slice(2));
