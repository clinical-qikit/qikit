// Renders the PNG icons the manifest references.
// Run from excel-addin/: node scripts/make-icons.mjs
// The PNGs are committed, so this only needs re-running when an SVG changes.
//
//   icon-{16,32,80}.png    ribbon button (absolute URLs, served with the task pane)
//   icon-color-192.png     app icon "color" (packaged in the manifest zip)
//   icon-outline-32.png    app icon "outline": white on transparent (packaged in the zip)
import sharp from 'sharp';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const assets = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'assets');

async function render(svgName, size, outName) {
  const out = path.join(assets, outName);
  await sharp(path.join(assets, svgName), { density: (72 * size) / 80 })
    .resize(size, size)
    .png()
    .toFile(out);
  console.log(`wrote ${out}`);
}

for (const size of [16, 32, 80]) await render('icon.svg', size, `icon-${size}.png`);
await render('icon.svg', 192, 'icon-color-192.png');
await render('icon-outline.svg', 32, 'icon-outline-32.png');
