// Validates manifests against the published Microsoft 365 app manifest schema named in
// their "$schema". Strict: unknown properties and malformed ids fail. Needs network.
// Run from excel-addin/: node scripts/validate-manifest.mjs manifest.json [more.json ...]
//
// office-addin-manifest validate (the npm "validate" script) runs too, in CI; it checks
// add-in specifics the schema cannot, such as a ribbon button's required supertip.
import Ajv from 'ajv-draft-04';
import { readFileSync } from 'node:fs';

const files = process.argv.slice(2);
if (files.length === 0) {
  console.error('usage: validate-manifest.mjs <manifest.json> [...]');
  process.exit(2);
}

const schemas = new Map();
let failed = false;
for (const file of files) {
  const manifest = JSON.parse(readFileSync(file, 'utf8'));
  const url = manifest.$schema;
  if (!schemas.has(url)) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
    const ajv = new Ajv({ allErrors: true, strict: false, validateFormats: false });
    schemas.set(url, ajv.compile(await response.json()));
  }
  const validate = schemas.get(url);
  if (validate(manifest)) {
    console.log(`${file}: valid against ${url}`);
  } else {
    failed = true;
    for (const error of validate.errors) {
      console.error(`${file}: ${error.instancePath || '/'} ${error.message}`, error.params);
    }
  }
}
process.exit(failed ? 1 : 0);
