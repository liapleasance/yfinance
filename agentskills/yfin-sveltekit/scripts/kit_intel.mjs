// usage: node kit_intel.mjs <buildRoot> <outDir>
// Reads the SELF-DESCRIPTION of a SvelteKit build — only entry/*.js + chunks/ (never any other file, never
// the network) — and writes <outDir>/KIT_INTEL.md + <outDir>/kit_intel.json. This is the map you read BEFORE
// deobfuscating: the build declares its own routes, server loads, matchers, hydration global and node table.
// Every rule below is VERIFIED on real finance.yahoo.com builds (runtime + official kit source); the full
// evidence and the reasoning live in references/kit-internals.md.
import fs from 'node:fs'; import path from 'node:path';
import { parseDictionary, parseNodesArray, detectImplicitRoot, splitTopLevel } from './routes_lib.mjs';
const [root, outDir] = process.argv.slice(2);
if (!root || !outDir) { console.error('usage: node kit_intel.mjs <buildRoot> <outDir>'); process.exit(2); }
fs.mkdirSync(outDir, { recursive: true });

const ent = fs.readdirSync(path.join(root, 'entry'));
const appFile = ent.find(f => /^app\.[A-Za-z0-9_-]{8}\.js$/.test(f));
const startFile = ent.find(f => /^start\.[A-Za-z0-9_-]{8}\.js$/.test(f));
if (!appFile || !startFile) { console.error('ERROR: no entry/app.<hash>.js + entry/start.<hash>.js under ' + root); process.exit(2); }
const app = fs.readFileSync(path.join(root, 'entry', appFile), 'utf8');

// --- nodes table (positional; rare slots import ../chunks/*.js — Vite fused the node into a chunk) ---
const pn = parseNodesArray(app);
const nodeOf = pn ? pn.nodeOf : {};
const chunkSlots = pn ? pn.nodeFiles.filter(([, p]) => p.startsWith('chunks/')) : [];

// --- routes (verified decoding) ---
const routes = parseDictionary(app);
if (!routes.length) { console.error('ERROR: no route table (dictionary) in entry/' + appFile); process.exit(2); }

// --- server_loads (layouts with a +layout.server.js load) ---
const parseNumList = s => s.split(',').map(x => x.trim()).filter(x => x !== '').map(Number).filter(Number.isInteger);
let server_loads = null;
const slAnchor = /export\s+const\s+server_loads\s*=\s*\[([^\]]*)\]/.exec(app);
if (slAnchor) server_loads = parseNumList(slAnchor[1]);
else {
  const alias = /\b(\w+)\s+as\s+server_loads\b/.exec(app);
  if (alias) {
    const m = new RegExp('(?:^|[^\\w$.])' + alias[1].replace(/[$]/g, '\\$&') + '\\s*=\\s*\\[').exec(app);
    if (m) { const j = app.indexOf(']', app.indexOf('[', m.index + m[0].length - 1)); server_loads = parseNumList(app.slice(app.indexOf('[', m.index + m[0].length - 1) + 1, j)); }
  }
}

// --- matchers ({ name: (param) => boolean }, for [param=name] route keys) ---
function extractMatchers() {
  const out = {};
  let obj = null;
  const named = /export\s+const\s+matchers\s*=\s*\{/.exec(app);
  const alias = /\b(\w+)\s+as\s+matchers\b/.exec(app);
  if (named) obj = braceObject(app, named.index + named[0].length - 1);
  else if (alias) { const m = new RegExp('(?:^|[^\\w$.])' + alias[1].replace(/[$]/g, '\\$&') + '\\s*=\\s*\\{').exec(app); if (m) obj = braceObject(app, app.indexOf('{', m.index + m[0].length - 1)); }
  if (!obj) return out;
  for (const pair of splitTopLevel(obj.slice(1, -1))) {
    const pm = /^(\w+)\s*:\s*(.+)$/s.exec(pair);
    if (!pm) continue;
    out[pm[1]] = fnSource(pm[2], app);
  }
  return out;
}
function braceObject(s, from) {                 // s[from] === '{' -> the matched object text
  let depth = 0, inStr = false, q = '', esc = false;
  for (let i = from; i < s.length; i++) {
    const c = s[i];
    if (inStr) { if (esc) esc = false; else if (c === '\\') esc = true; else if (c === q) inStr = false; continue; }
    if (c === '"' || c === "'") { inStr = true; q = c; continue; }
    if (c === '{') depth++;
    else if (c === '}') { depth--; if (!depth) return s.slice(from, i + 1); }
  }
  return null;
}
function fnSource(ref, whole) {                 // "zt" -> "function zt(p){...}" (or the raw expression)
  const t = ref.trim().replace(/,$/, '');
  const id = /^([A-Za-z_$][\w$]*)$/.exec(t);
  if (!id) return t.slice(0, 300);              // inline arrow / expression: report as-is
  let m = new RegExp('function\\s+' + id[1].replace(/[$]/g, '\\$&') + '\\s*\\(([^)]*)\\)\\s*\\{').exec(whole);
  if (m) { const body = braceObject(whole, whole.indexOf('{', m.index + m[0].length - 1)); if (body) return `(${m[1]}) => ${body}`.slice(0, 300); }
  m = new RegExp('(?:^|[^\\w$.])' + id[1].replace(/[$]/g, '\\$&') + '\\s*=\\s*').exec(whole);
  if (m) { const rhs = whole.slice(m.index + m[0].length, m.index + m[0].length + 240); return rhs.split(/[;,]/)[0]; }
  return t;
}
const matchers = extractMatchers();

// --- the kit client chunk: hydration global + build constant ---
const implicit = detectImplicitRoot(root);
const kit = { file: implicit.chunk, hydrationGlobal: null, buildConstant: null, buildTimeIso: null };
if (implicit.chunk) {
  let kc = null; try { kc = fs.readFileSync(path.join(root, 'chunks', implicit.chunk), 'utf8'); } catch { }
  if (kc) {
    const hy = /__sveltekit_([A-Za-z0-9]+)/.exec(kc);
    if (hy) kit.hydrationGlobal = '__sveltekit_' + hy[1];
    const bid = /"(\d{12,14})"/.exec(kc);
    if (bid) { kit.buildConstant = bid[1]; try { kit.buildTimeIso = new Date(+bid[1]).toISOString(); } catch { } }
  }
}

// --- stale files of older builds (same node number, different hash) ---
const diskNodes = {};
try { for (const f of fs.readdirSync(path.join(root, 'nodes'))) { const n = f.split('.')[0]; if (/^\d+$/.test(n)) (diskNodes[n] ??= []).push(f); } } catch { }
const stale = Object.entries(diskNodes).filter(([, v]) => v.length > 1);

// --- layout frequency + naive-Math.abs damage report ---
const freq = {}; for (const r of routes) for (const n of new Set(r.layouts.filter(x => x != null))) freq[n] = (freq[n] || 0) + 1;
const misattributed = routes.filter(r => r.hasServerLoad);   // every ~N leaf: |−(N+1)| = N+1 ≠ N
const naiveNodes = new Set(routes.map(r => Math.abs(r.leafRaw.startsWith('~') ? +r.leafRaw.slice(1) + 1 : +r.leafRaw)));
const collisions = routes.filter(r => { const n = r.hasServerLoad ? r.pageNode : null; return n != null && naiveNodes.has(n) && routes.some(o => o !== r && !o.hasServerLoad && o.pageNode === n); });

const report = {
  appFile, startFile, kitClient: kit, implicitRootLayout: implicit.detected ? { node: 0, file: nodeOf[0] ?? null, detectedFrom: 'chunks/' + implicit.chunk } : null,
  nodesTotal: pn ? pn.nodeFiles.length : null, chunkSlots, staleNodeFiles: stale,
  server_loads, matchers,
  routesTotal: routes.length,
  staticRoutes: routes.filter(r => !r.route.includes('[')).length,
  paramRoutes: routes.filter(r => r.route.includes('[')).length,
  serverLoadLeaves: routes.filter(r => r.hasServerLoad).length,
  errorBoundaryRoutes: routes.filter(r => (r.errors || []).some(e => e != null)).length,
  layoutFrequency: Object.entries(freq).sort((a, b) => b[1] - a[1]).slice(0, 12).map(([n, c]) => ({ node: +n, file: nodeOf[n] ?? null, routes: c, pct: +(100 * c / routes.length).toFixed(1) })),
  naiveMathAbs: { misattributedLeaves: misattributed.length, misattributedRoutes: misattributed.map(r => r.route).slice(0, 30), collisions },
};
fs.writeFileSync(path.join(outDir, 'kit_intel.json'), JSON.stringify(report, null, 2));

// --- KIT_INTEL.md ---
let md = '# SvelteKit self-description of this build\n\n';
md += `Read (statically) from \`entry/${appFile}\` + the kit client chunk only. Semantics VERIFIED on real finance.yahoo.com builds — see \`references/kit-internals.md\`.\n\n`;
md += `## Identity\n\n- kit client chunk: \`${kit.file ?? '?'}\` (imported by \`entry/${startFile}\`)\n- hydration global: \`${kit.hydrationGlobal ?? 'not found'}\` — every server-rendered page's inline <script> sets it; a mismatch between an HTML file and this chunk means they come from DIFFERENT builds (mixed download)\n`;
if (kit.buildConstant) md += `- build constant: \`${kit.buildConstant}\`${kit.buildTimeIso ? ` (epoch ms -> ${kit.buildTimeIso}; exact meaning is a hypothesis (H))` : ''}\n`;
md += `- implicit root layout: ${implicit.detected ? `**yes** — the runtime prepends node 0 to every route (\`layouts:[0,...]\`), and the dictionary never lists it (node file: ${nodeOf[0] ?? '?'})` : 'not detected (older format: the dictionary lists the root layout explicitly)'}\n\n`;
md += `## Routes (${routes.length})\n\n- static: ${report.staticRoutes} | with params: ${report.paramRoutes} | pages with a server load (negative leaf, \`~N\`): ${report.serverLoadLeaves} | with error boundaries below the root: ${report.errorBoundaryRoutes}\n`;
md += `- \`server_loads\` (layouts with a \`+layout.server.js\` load): ${server_loads ? JSON.stringify(server_loads) : 'not found'}\n\n`;
md += `### Layouts by route coverage\n\n| node | file | routes | % |\n|---|---|---|---|\n`;
for (const l of report.layoutFrequency) md += `| ${l.node} | ${l.file ?? '?'} | ${l.routes} | ${l.pct}% |\n`;
md += `\n### Pages with a server load (negative leaf -> node ~value)\n\n| route | leaf | node | file |\n|---|---|---|---|\n`;
for (const r of routes.filter(x => x.hasServerLoad)) md += `| \`${r.route}\` | ${r.leafRaw} | ${r.pageNode} | ${nodeOf[r.pageNode] ?? '?'} |\n`;
if (Object.keys(matchers).length) {
  md += `\n### Matchers ([param=name] route keys)\n\n| name | function (raw, from app.*.js) |\n|---|---|\n`;
  for (const [n, src] of Object.entries(matchers)) md += `| ${n} | \`${String(src).replace(/\|/g, '\\|').slice(0, 200)}\` |\n`;
}
if (chunkSlots.length) { md += `\n### Node slots that import chunks/ (Vite fused the node into a chunk)\n\n| slot | file |\n|---|---|\n`; for (const [i, p] of chunkSlots) md += `| ${i} | ${p} |\n`; }
if (stale.length) { md += `\n### Stale files of older builds on disk (same node number, different hash — ignored by the current app.*.js)\n\n`; for (const [n, v] of stale.slice(0, 10)) md += `- nodes/${n}.*.js x${v.length}\n`; if (stale.length > 10) md += `- ... and ${stale.length - 10} more node numbers with duplicates (${stale.reduce((a, [, v]) => a + v.length, 0)} stale files in total; the current build uses ${pn ? pn.nodeFiles.length : '?'} node slots)\n`; }
md += `\n## Reading warnings\n\n- A naive \`Math.abs(leaf)\` reading misattributes **${misattributed.length}** routes (off by one: \`-184\` -> node 183, not 184)`;
if (collisions.length) md += ` and collides on **${collisions.length}** (\`|leaf|\` of one route equals the real node of another)`;
md += `.\n- To scope "the markets pages", match the DICTIONARY KEY (\`/(app)/[page=markets]\`), not the URL — localized URLs (\`/mercados\`, \`/marchés\`...) all match that one route via its matcher.\n`;
fs.writeFileSync(path.join(outDir, 'KIT_INTEL.md'), md);
console.log(JSON.stringify({ routes: routes.length, serverLoadLeaves: report.serverLoadLeaves, matchers: Object.keys(matchers).length, hydrationGlobal: kit.hydrationGlobal, buildConstant: kit.buildConstant, implicitRootLayout: implicit.detected, chunkSlots: chunkSlots.length, staleNodeGroups: stale.length, naiveMathAbsMisattributed: misattributed.length }));
