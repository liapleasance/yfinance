// usage: node reports.mjs <finalRoot> <statsDir> <outDir> [shards=2]
// Writes <outDir>/ROUTES.md (route -> page node + server load + layouts + error boundaries, from the decoded
// `dictionary` of entry/app.*.js — VERIFIED semantics, see references/kit-internals.md) and <outDir>/UNMAPPED_IMPORTS.md
// (chunk::export still without a semantic name, by number of importing files; counts come from transform stats, so they are
// underestimates if a transform run was resumed/interrupted).
import fs from 'node:fs'; import path from 'node:path';
const [finalRoot, statsDir, outDir, shardsArg] = process.argv.slice(2);
if (!finalRoot || !statsDir || !outDir) { console.error('usage: node reports.mjs <finalRoot> <statsDir> <outDir> [shards=2]'); process.exit(2); }
const shards = +shardsArg || 2; fs.mkdirSync(outDir, { recursive: true });
const un = {};
for (let i = 0; i < shards; i++) { const f = path.join(statsDir, `stats_shard_${i}.json`); if (!fs.existsSync(f)) continue; for (const [k, v] of Object.entries(JSON.parse(fs.readFileSync(f, 'utf8')).unmappedImports || {})) un[k] = (un[k] || 0) + v; }
const rows = Object.entries(un).sort((a, b) => b[1] - a[1]);
fs.writeFileSync(path.join(outDir, 'UNMAPPED_IMPORTS.md'), '# Imports still without a semantic name\n\nFormat `chunk::export` -> number of importing files. Map the most used first.\n\n| chunk::export | uses |\n|---|---|\n' + rows.map(([k, v]) => `| ${k} | ${v} |`).join('\n') + '\n');
import { parseRoutes, detectImplicitRoot } from './routes_lib.mjs';
const { appFile, nodeFiles, routes } = parseRoutes(finalRoot);
const implicit = detectImplicitRoot(finalRoot);
const fileOf = Object.fromEntries(nodeFiles);
let r = '# Routes -> nodes\n\nFrom `entry/' + appFile + '` (`dictionary`), decoded with the VERIFIED semantics (see `references/kit-internals.md`):\n\n- a **negative leaf** (or `~N`) = the page **has a server load** (`+page.server.js`); its node is `~value` (bitwise: `-184` -> node 183). `Math.abs` is wrong (off by one, and it collides: `-198` -> node 197 while `+198` -> node 198 are different pages).\n- the **root layout (node 0) is implicit**: the runtime prepends it to every route (`layouts:[0,...]`), so current dictionaries never list it' + (implicit.detected ? ' — **detected in this build** from the kit client chunk' : '') + '. The root error boundary (node 1) is implicit the same way.\n- `server_loads` (a separate export of app.*.js) lists the LAYOUTS with a server load; the leaf marker above covers pages.\n\n| Route | Page (node) | Server load | Layouts (below the root) | Error boundaries (below the root) |\n|---|---|---|---|---|\n';
for (const x of routes) {
  r += `| \`${x.route}\` | ${fileOf[x.pageNode] ?? x.pageNode} | ${x.hasServerLoad ? 'yes' : 'no'} | ${x.layouts.filter(l => l != null).map(l => fileOf[l] ?? l).join(', ')} | ${(x.errors || []).filter(e => e != null).map(e => fileOf[e] ?? e).join(', ')} |\n`;
}
r += `\n${routes.length} routes; ${routes.filter(x => x.hasServerLoad).length} pages with a server load; ${routes.filter(x => (x.errors || []).some(e => e != null)).length} routes with error boundaries below the root.\n`;
fs.writeFileSync(path.join(outDir, 'ROUTES.md'), r);
console.log(JSON.stringify({ routes: routes.length, nodes: nodeFiles.length, unmappedImports: rows.length, implicitRootLayout: implicit.detected }));
if (!routes.length || !nodeFiles.length) { console.error('WARNING: no routes/nodes parsed - the entry/app format may have changed'); process.exit(1); }
