// Fails if the task pane page (dist/index.html) loads any script containing the dev
// harness, whose import replaces Office.js's globals with mocks. 1.4.2 and 1.4.3 shipped
// that way: in Excel the pane showed the demo and never touched the workbook.
//
//   node scripts/check-bundle.mjs [distDir]
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';

const dist = process.argv[2] ?? 'dist';
const MARKER = 'qikit-mock-workbook';

function scriptsOf(page) {
  const html = readFileSync(join(dist, page), 'utf8');
  return [...html.matchAll(/<(?:script|link)[^>]+(?:src|href)="(?!https?:)\.?\/?([^"]+\.js)"/g)].map(m => m[1]);
}

// Follow static imports from each entry script, so a shared chunk counts too.
function closure(entries) {
  const seen = new Set();
  const queue = [...entries];
  while (queue.length) {
    const file = queue.pop();
    if (seen.has(file)) continue;
    seen.add(file);
    const code = readFileSync(join(dist, file), 'utf8');
    for (const m of code.matchAll(/(?:import|from)\s*["']\.\/([^"']+\.js)["']/g)) {
      queue.push(join(dirname(file), m[1]));
    }
  }
  return [...seen];
}

const taskpane = closure(scriptsOf('index.html'));
const leaking = taskpane.filter(f => readFileSync(join(dist, f), 'utf8').includes(MARKER));
if (leaking.length) {
  console.error(`The task pane loads the dev harness (mock Office.js) via: ${leaking.join(', ')}`);
  process.exit(1);
}
const demo = closure(scriptsOf('demo.html'));
if (!demo.some(f => readFileSync(join(dist, f), 'utf8').includes(MARKER))) {
  console.error('demo.html does not load the dev harness; check-bundle.mjs is not looking where it should.');
  process.exit(1);
}
console.log(`ok: task pane loads ${taskpane.length} scripts without the harness; demo has it.`);
