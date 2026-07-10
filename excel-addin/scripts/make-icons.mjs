// Renders assets/icon.svg to the PNG sizes referenced by manifest.json.
// Run from excel-addin/: node scripts/make-icons.mjs
// The PNGs are committed, so this only needs re-running when icon.svg changes.
import sharp from 'sharp';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const assets = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'assets');
const svg = path.join(assets, 'icon.svg');

for (const size of [16, 32, 80]) {
  const out = path.join(assets, `icon-${size}.png`);
  await sharp(svg, { density: (72 * size) / 80 }).resize(size, size).png().toFile(out);
  console.log(`wrote ${out}`);
}
