// usage: node annotate_routes.mjs <finalRoot>
// Adds a 3-line comment at the top of every nodes/N.<hash>.js saying which route(s) it is the page of and
// which routes it wraps as a layout, taken from the route table in entry/app.<hash>.js — decoded with the
// VERIFIED dictionary semantics (references/kit-internals.md): a NEGATIVE leaf (or ~N) is a page WITH a
// server load and its node is ~value (bitwise: -184 -> 183), never Math.abs(value); node 0 is the root
// layout the runtime prepends to every route (detected, not assumed). COMMENTS ONLY (the verifiers ignore
// comments); idempotent (marker "@routes").
// Run it after stage 2 + fallback and before verify_all.sh (apply_fallback rebuilds a node from the original
// and drops its comment: re-run it).
import fs from 'node:fs'; import path from 'node:path';
import { parseRoutes, detectImplicitRoot } from './routes_lib.mjs';
const root = process.argv[2]; if (!root) { console.error('usage: node annotate_routes.mjs <finalRoot>'); process.exit(2); }
const { appFile, nodeFiles, routes } = parseRoutes(root);
const implicit = detectImplicitRoot(root);
const fileOf = Object.fromEntries(nodeFiles);
const page = {}, layout = {};
for (const r of routes) {
  (page[r.pageNode] ??= []).push((r.hasServerLoad ? '(server load) ' : '') + r.route);
  for (const l of r.layouts) if (l != null) (layout[l] ??= []).push(r.route);
}
const list = a => a.length <= 6 ? a.join(', ') : a.slice(0, 6).join(', ') + ` (+${a.length - 6} more)`;
let n = 0, skipped = 0;
for (const [i, rel] of nodeFiles) {
  const f = path.join(root, rel); if (!fs.existsSync(f)) continue; const src = fs.readFileSync(f, 'utf8');
  if (/^\/\/ @routes/.test(src)) { skipped++; continue; }
  const lines = [`// @routes (from entry/${appFile}; comment added by yfin-sveltekit)`];
  if (i === 0 && implicit.detected) {
    lines.push(`// root layout: EVERY route (implicit — the runtime prepends node 0; the dictionary never lists it)`);
    lines.push(layout[i] ? `// also layout of ${layout[i].length} route(s): ${list(layout[i])}` : '// page of: (none)');
  } else {
    lines.push(page[i] ? `// page of: ${list(page[i])}` : '// page of: (none)');
    lines.push(layout[i] ? `// layout of ${layout[i].length} route(s): ${list(layout[i])}` : '// layout of: (none)');
  }
  fs.writeFileSync(f, lines.join('\n') + '\n' + src); n++;
}
console.log(JSON.stringify({ annotated: n, alreadyAnnotated: skipped, nodes: nodeFiles.length, implicitRootLayout: implicit.detected }));
