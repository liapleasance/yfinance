// usage: node select_routes.mjs <root> <outPrefix> <routeFilter...> [--static-only]
// Route-family ("genealogy") selection over a SvelteKit build root (entry/ + nodes/ + chunks/, raw or prettified).
// SvelteKit pages do not exist in a vacuum: they inherit layouts in cascade. entry/app.<hash>.js holds the family tree
// (dictionary: route -> [leaf, layouts, errors]; VERIFIED decoding in routes_lib.mjs / references/kit-internals.md);
// the SHARED layouts of the matched routes are the backbone that runs on nearly every page of that family, and each
// matched route's page node is a light leaf that adds its own loaders.
// Filters: substrings matched against dictionary keys ("quote/"), "@universal" (the layouts that run on >=95% of ALL
// routes — no page leaves), or "*" (whole build: every node of the nodes array is a seed).
// This script keeps the routes whose dictionary KEY contains any <routeFilter> as a substring and
// resolves the CLOSED file set that runs on those routes:
//   seeds  = entry/start.<hash>.js + entry/app.<hash>.js + union of the layouts of the matched routes
//            (the backbone) + the page node of every matched route (leaf; a NEGATIVE leaf = a page WITH a
//            +page.server.js load — node = ~value, kept like any other leaf)
//            + node 0 when the kit client chunk prepends it to every route (implicit root layout, detected)
//   files  = transitive closure of the seeds under STATIC imports, plus the __vite__mapDeps(...) preload deps (.js only)
//            attached to each selected node import in app.<hash>.js, plus (unless --static-only) the dynamic import()
//            targets of every selected file EXCEPT entry/app.<hash>.js (its dynamic imports ARE the route table — that is
//            exactly what the filter replaces).
// Node numbers are NEVER hard-coded. Node 0 is included only when DETECTED as the implicit root layout (current builds:
// the runtime prepends layouts:[0,...] and the dictionary never lists it — see references/kit-internals.md); older
// formats list the root layout in the dictionary and frequency finds it. If tomorrow's build makes node 42 the quote
// layout, this still selects the right files. Node files are resolved through the `nodes` array of app.<hash>.js — a
// folder can hold leftovers of older builds with the same node number and a different hash; those are ignored (and
// counted in the report), because only the current app.<hash>.js can load them.
// Output: <outPrefix>.txt (one relative path per selected file, sorted — the closed list for the deobfuscator),
//         <outPrefix>.json (stats: matched routes, backbone with per-node route coverage, hubChunks report, file
//         counts, closure check) and a one-line JSON on stdout.
// exit 1 when a static import of a selected file is missing on disk or leaves entry/nodes/chunks (broken or incomplete
//        build: do NOT deobfuscate a set that is not closed); exit 2 on usage error, no route matching, or no universal backbone.
import fs from 'node:fs'; import path from 'node:path';
import { parseDictionary, detectImplicitRoot, parseNodesArray } from './routes_lib.mjs';
const staticOnly = process.argv.includes('--static-only');
const argv = process.argv.slice(2).filter(a => a !== '--static-only');
const [root, outPrefix, ...filters] = argv;
if (!root || !outPrefix || !filters.length) { console.error('usage: node select_routes.mjs <root> <outPrefix> <routeFilter...> [--static-only]'); process.exit(2); }
const inScope = f => f === 'entry' || f === 'nodes' || f === 'chunks' || f.startsWith('entry/') || f.startsWith('nodes/') || f.startsWith('chunks/');
const fail1 = msg => { console.error('ERROR: ' + msg); process.exit(1); };

const ent = fs.readdirSync(path.join(root, 'entry'));
const appFile = ent.find(f => /^app\.[A-Za-z0-9_-]{8}\.js$/.test(f));
const startFile = ent.find(f => /^start\.[A-Za-z0-9_-]{8}\.js$/.test(f));
if (!appFile || !startFile) { console.error('ERROR: no entry/app.<hash>.js + entry/start.<hash>.js under ' + root); process.exit(2); }
const app = fs.readFileSync(path.join(root, 'entry', appFile), 'utf8');

// --- route table of THIS build (routes_lib.mjs: scanner-based, raw and prettified; drops nothing — entries
// with a third (errors) array, holes and the ~N expression form all parse; leaf decoding is VERIFIED). The
// nodes array is parsed POSITIONALLY: rare slots import ../chunks/*.js instead of ../nodes/*.js (Vite fused
// the node into a chunk — seen on a real build: nodes[96] was the kit-client chunk), and a nodes-only regex
// would lose every route whose leaf is such a slot. ---
const parsedNodes = parseNodesArray(app);
const nodeOf = parsedNodes ? parsedNodes.nodeOf : {};
const routes = parseDictionary(app);
if (!routes.length) { console.error('ERROR: entry/' + appFile + ' has no SvelteKit route table (dictionary)'); process.exit(2); }

// --- __vite__mapDeps preload table: global dep array (m.f=[...]) + per-node import associations ---
// The per-node deps come from the nodes array entries themselves (positional — routes_lib.parseNodesArray):
// entry = ()=>r(()=>import(PATH).then(p=>p.X),__vite__mapDeps([i,j]),import.meta.url). The old
// import(PATH),__vite__mapDeps regex NEVER matched this shape (the .then(p=>p.X) sits between the two), so
// preloads were silently never added on real builds; chunk slots (nodes[i] -> chunks/*.js) carry them too.
const depArr = [];
const mf = app.match(/m\.f\s*=\s*\[/);
if (mf) {
  let j = app.indexOf('[', mf.index) + 1;
  while (app[j] !== ']' && j < app.length) {
    if (app[j] === '"' || app[j] === "'") { const q = app[j]; const k = app.indexOf(q, j + 1); if (k < 0) fail1('unterminated string in the __vite__mapDeps array of entry/' + appFile); depArr.push(app.slice(j + 1, k)); j = k + 1; }
    else j++;
  }
}
const nodeDeps = {};
if (parsedNodes) {
  for (const [n, raw] of Object.entries(parsedNodes.nodeDepsIdx)) {
    const idxs = raw.split(',').map(x => +x.trim()).filter(x => Number.isInteger(x));
    nodeDeps[n] = idxs.map(i => depArr[i]).filter(Boolean);
  }
} else for (const m of app.matchAll(/import\(\s*["']\.\.\/nodes\/(\d+)\.[A-Za-z0-9_-]+\.js["']\s*\)\s*,\s*__vite__mapDeps\(\s*\[([^\]]*)\]/g)) {
  const idxs = m[2].split(',').map(x => +x.trim()).filter(x => Number.isInteger(x));
  nodeDeps[+m[1]] = idxs.map(i => depArr[i]).filter(Boolean);
}

// --- filter the family (or pick the universal backbone) ---
// '@universal' = the layouts that run on (nearly) EVERY page: the implicit root layout (when the kit client
// chunk prepends it — current builds) plus the layouts with >=95% frequency across ALL routes of THIS
// build's dictionary (threshold, never an intersection: measured on a real build the /(app) master layout
// runs on 211/219 routes and the strict intersection of all routes is EMPTY). No page leaves are selected.
const UNIVERSAL = '@universal'; const THRESH = 0.95;
const isUniversal = filters.includes(UNIVERSAL);
const implicit = detectImplicitRoot(root);
const freq = {}; for (const r of routes) for (const n of new Set(r.layouts.filter(x => x != null))) freq[n] = (freq[n] || 0) + 1;
const want = (isUniversal || filters.includes('*')) ? routes : routes.filter(r => filters.some(f => r.route.includes(f)));
if (!want.length) { console.error('ERROR: no route in the dictionary of entry/' + appFile + ' matches the filter(s): ' + filters.join(' ')); process.exit(2); }
const fullBuild = filters.includes('*'); // '*' = the WHOLE build: every node of the nodes array is a seed, including the ones the
// dictionary never references (+error.svelte boundaries, orphan endpoints) — that is what scope_build.sh used to copy.
const backbone = isUniversal
  ? new Set(Object.keys(freq).map(Number).filter(n => freq[n] / routes.length >= THRESH && nodeOf[n] !== undefined))
  : new Set([...new Set(want.flatMap(r => r.layouts.filter(x => x != null)))].filter(n => nodeOf[n] !== undefined)); // union of the matched routes' layouts
if (implicit.detected && nodeOf[0] !== undefined && !backbone.has(0)) backbone.add(0); // current format: the runtime prepends node 0 to EVERY route (layouts:[0,...f||[]]) — the dictionary never lists it, so frequency alone would MISS the root layout. Detected from the kit client chunk, not assumed: older formats list it and frequency finds it.
for (const n of backbone) if (nodeOf[n] === undefined) fail1(`dictionary references node ${n} but the nodes array of entry/${appFile} has no such entry (mixed or truncated build)`);
const leaves = isUniversal ? [] : want.map(r => ({ route: r.route, page: r.leafRaw, node: r.pageNode, serverLoad: r.hasServerLoad, file: nodeOf[r.pageNode] }));
if (isUniversal && !backbone.size) { console.error('ERROR: no layout of entry/' + appFile + ' runs on >= ' + Math.round(THRESH * 100) + '% of the routes (top: ' + Object.entries(freq).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([n, c]) => `node ${n} ${c}/${routes.length}`).join(', ') + '); this app has no universal backbone — use route-family filters instead'); process.exit(2); }

// --- resolve the closed set ---
const sel = new Set(); const scanned = new Set(); const dynFollowed = new Set(); const dynUnresolved = []; const mapDepsAdded = new Set();
const read = f => { try { return fs.readFileSync(path.join(root, f), 'utf8'); } catch { fail1(`selected file ${f} is missing on disk (incomplete build: re-download it before deobfuscating)`); } };
const push = f => { if (!scanned.has(f) && !sel.has(f)) { sel.add(f); queue.push(f); } };
const queue = [`entry/${startFile}`, `entry/${appFile}`];
for (const n of backbone) push(nodeOf[n]);
for (const l of leaves) push(l.file);
if (fullBuild) for (const f of Object.values(nodeOf)) push(f);
for (const n of backbone) for (const d of nodeDeps[n] || []) if (/\.m?js$/.test(d)) {
  const t = path.posix.normalize(path.posix.join('entry', d));
  if (inScope(t)) { mapDepsAdded.add(t); push(t); }
}
const STIMP = /(?:^|[^\w.$])from\s*["'](\.{1,2}\/[^"']+\.m?js)["']/g;   // static: import x from "..", export .. from ".."
const SDEXP = /(?:^|[^\w.$])import\s*["'](\.{1,2}\/[^"']+\.m?js)["']/g; // static side-effect: import ".."
const DYIMP = /import\(\s*["'](\.{1,2}\/[^"']+\.m?js)["']\s*\)/g;       // dynamic: import("..")
while (queue.length) {
  const f = queue.pop(); if (scanned.has(f)) continue; scanned.add(f); sel.add(f);
  const src = read(f); const base = path.posix.dirname(f); const isApp = f === `entry/${appFile}`;
  const statics = [...src.matchAll(STIMP), ...src.matchAll(SDEXP)].map(m => m[1]);
  const dynamics = staticOnly ? [] : [...src.matchAll(DYIMP)].map(m => m[1]);
  for (const spec of statics) {
    const t = path.posix.normalize(path.posix.join(base, spec));
    if (!inScope(t)) fail1(`static import "${spec}" of ${f} resolves to ${t}, outside entry/nodes/chunks — this build breaks the import-closure guarantee of the skill`);
    push(t);
  }
  for (const spec of dynamics) {
    const t = path.posix.normalize(path.posix.join(base, spec));
    if (isApp && t.startsWith('nodes/')) continue; // app.<hash>.js dynamic imports = the route table itself (the filter replaces it)
    if (!inScope(t)) { dynUnresolved.push(`${f} -> ${t}`); continue; }
    dynFollowed.add(`${f} -> ${t}`); push(t);
  }
}

// --- closure guarantee (BFS already gives it; this re-check makes it an assertion, not an assumption) ---
for (const f of sel) {
  const src = fs.readFileSync(path.join(root, f), 'utf8'); const base = path.posix.dirname(f);
  for (const m of src.matchAll(STIMP)) { const t = path.posix.normalize(path.posix.join(base, m[1])); if (!sel.has(t)) fail1(`closure broken: ${f} statically imports ${t} which is not in the selection`); }
}

// --- hubChunks (informational, never selected): chunks most imported by the CURRENT page/layout nodes.
// A chunk can run on most pages because every PAGE imports it (FooterV2/loadMarketTime moved from the master
// layout to per-node imports between real finance.yahoo.com builds); the backbone closure cannot see that, so
// this report surfaces the drift with numbers instead of guessing. `inSelection` tells whether it is already in.
const hubCnt = {}; const curNodes = Object.values(nodeOf);
for (const f of curNodes) {
  let s; try { s = fs.readFileSync(path.join(root, f), 'utf8'); } catch { continue; }
  const bases = new Set();
  for (const m of s.matchAll(/from\s*["']\.\.\/chunks\/([^.\/"']+)\.[A-Za-z0-9_-]+\.js["']/g)) bases.add(m[1]);
  for (const b of bases) hubCnt[b] = (hubCnt[b] || 0) + 1;
}
const selList = [...sel];
const hubChunks = Object.entries(hubCnt).sort((a, b) => b[1] - a[1]).slice(0, 12)
  .map(([base, c]) => ({ chunk: base, importedByCurrentNodes: c, ofCurrentNodes: curNodes.length, inSelection: selList.some(f => f.startsWith(`chunks/${base}.`)) }));

// --- what was NOT taken (report only; never read those files) ---
let diskTotal = 0; const diskNodes = {};
for (const d of ['entry', 'nodes', 'chunks']) {
  const dir = path.join(root, d); if (!fs.existsSync(dir)) continue;
  for (const f of fs.readdirSync(dir)) if (/\.m?js$/.test(f)) { diskTotal++; if (d === 'nodes') { const n = f.split('.')[0]; (diskNodes[n] ??= []).push(f); } }
}
const dupNodes = Object.entries(diskNodes).filter(([, v]) => v.length > 1);
const kb = Math.round([...sel].reduce((a, f) => a + fs.statSync(path.join(root, f)).size, 0) / 1024);
const out = {
  filters, appFile, startFile, staticOnly, fullBuild, mode: isUniversal ? 'universal' : (fullBuild ? 'full' : 'family'),
  routesTotal: routes.length, routesMatched: want.length,
  matchedRoutes: want.map(r => r.route),
  backbone: [...backbone].sort((a, b) => a - b).map(n => {
    const implicitRoot = n === 0 && implicit.detected;
    return { node: n, file: nodeOf[n], coveragePct: implicitRoot ? 100 : +(100 * (freq[n] || 0) / routes.length).toFixed(1), runsOn: implicitRoot ? `every route — implicit root layout (the kit client prepends node 0; the dictionary never lists it; detected from ${implicit.chunk})` : (isUniversal ? `${freq[n]}/${routes.length} routes (${(100 * freq[n] / routes.length).toFixed(1)}%) — universal backbone` : `${[...new Set(want.filter(r => r.layouts.includes(n)).map(r => r.route))].length} matched routes`) };
  }),
  implicitRootLayout: implicit.detected ? { node: 0, file: nodeOf[0] ?? null, detectedFrom: 'chunks/' + implicit.chunk, note: 'the runtime prepends node 0 to every route (layouts:[0,...]); the dictionary never lists it' } : null,
  leaves: leaves.map(l => ({ ...l, kind: l.serverLoad ? 'server load' : 'page' })),
  files: sel.size, kb, diskTotal, sharePct: +(100 * sel.size / Math.max(diskTotal, 1)).toFixed(1),
  dynamicImportsFollowed: dynFollowed.size, dynamicImportsUnresolvedOutOfScope: dynUnresolved.length,
  mapDepsPreloadsAdded: mapDepsAdded.size, mapDepsTable: depArr.length,
  hubChunks,
  staleNodeFilesIgnored: dupNodes.map(([n, v]) => `nodes/${n}.*.js x${v.length}`),
  closure: 'PASS (every static import of every selected file is in the selection and stays inside entry/nodes/chunks)',
};
const list = [...sel].sort();
fs.writeFileSync(outPrefix + '.txt', list.join('\n') + '\n');
fs.writeFileSync(outPrefix + '.json', JSON.stringify(out, null, 2));
console.log(JSON.stringify({ mode: out.mode, files: out.files, kb: out.kb, diskTotal: out.diskTotal, sharePct: out.sharePct, routesMatched: out.routesMatched, backbone: out.backbone.map(b => b.node + (isUniversal ? `(${b.coveragePct}%)` : '')), dynamicImportsFollowed: out.dynamicImportsFollowed, closure: 'PASS' }));
