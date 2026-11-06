// Shared route-dictionary decoding for annotate_routes.mjs, reports.mjs, select_routes.mjs and kit_intel.mjs.
// Works on the RAW minified build AND on a prettified one.
//
// VERIFIED format (decoded from the kit-client runtime of real finance.yahoo.com builds + the official kit
// manifest generator; full evidence in references/kit-internals.md):
//   dictionary: "route": [leaf, layouts, errors]
//     leaf:     page node id, ENCODED when the page has a +page.server.js load: kit's own source writes the
//               expression ~N (bitwise NOT) and the site's minifier constant-folds it to -N-1. So "~183" and
//               "-184" BOTH mean node 183 with a server load. Math.abs(-184)=184 is the classic off-by-one
//               (on a real build 184 is a DIFFERENT page, and -198 -> 197 collides with +198 -> 198).
//     layouts:  layout node ids BELOW the root layout. The ROOT LAYOUT (node 0) is IMPLICIT: the kit client
//               prepends it to every route (layouts:[0,...f||[]]), so current dictionaries never list it and
//               frequency-counting node 0 across the dictionary returns 0. Older formats listed it.
//     errors:   (optional 3rd array) +error boundary ids below the root error boundary (node 1, also implicit:
//               errors:[1,...d||[]]). Holes (",,") mean "no boundary at that nesting level", NOT node 0.
//     Holes in layouts mean "no layout at that level" and must never decode to 0.
//   server_loads (separate export): ids of the LAYOUTS that have a +layout.server.js load.
//   matchers (separate export): { name: (param) => boolean } used by [param=name] route keys.
import fs from 'node:fs'; import path from 'node:path';

export function decodeLeaf(tok) {              // "-184" | "~183" | "183" -> { node, hasServerLoad } | null
  const s = String(tok).trim();
  if (s.startsWith('~')) { const n = +s.slice(1); return Number.isFinite(n) ? { node: n, hasServerLoad: true } : null; }
  const n = +s;
  if (!Number.isFinite(n) || !/^-?\d+$/.test(s)) return null;
  return n < 0 ? { node: ~n, hasServerLoad: true } : { node: n, hasServerLoad: false };
}

// Locate the dictionary OBJECT. A regex over single entries silently drops routes (entries with a third
// array break naive matching), so we brace-match the object itself, string-aware (route keys contain [ ]).
function findDictionaryObject(app) {
  let start = -1;
  const alias = /export\s*\{\s*(\w+)\s+as\s+dictionary\b/.exec(app) || /\b(\w+)\s+as\s+dictionary\b/.exec(app);
  if (alias) {
    const re = new RegExp('(?:^|[^\\w$.])' + alias[1].replace(/[$]/g, '\\$&') + '\\s*=\\s*\\{');
    const m = re.exec(app);
    if (m) start = app.indexOf('{', m.index + m[0].length - 1);
  }
  if (start < 0) {
    const m = /export\s+const\s+dictionary\s*=\s*\{/.exec(app) || /(?:^|[^.\w])dictionary\s*=\s*\{/.exec(app);
    if (m) start = app.indexOf('{', m.index + m[0].length - 1);
  }
  if (start < 0) return null;
  let depth = 0, inStr = false, q = '', esc = false;
  for (let i = start; i < app.length; i++) {
    const c = app[i];
    if (inStr) { if (esc) esc = false; else if (c === '\\') esc = true; else if (c === q) inStr = false; continue; }
    if (c === '"' || c === "'") { inStr = true; q = c; continue; }
    if (c === '{') depth++;
    else if (c === '}') { depth--; if (!depth) return app.slice(start, i + 1); }
  }
  return null;
}

export function splitTopLevel(s) {             // "a, [1, 2], [, 3]" -> ["a","[1, 2]","[, 3]"] (string-aware)
  return splitKeep(s).map(x => x.trim()).filter(Boolean);
}

function splitKeep(s) {                         // like splitTopLevel but KEEPS empty slots (index-true)
  const out = []; let depth = 0, inStr = false, q = '', esc = false, cur = '';
  for (const c of s) {                          // parens count too: nodes-array entries are
    if (inStr) { cur += c; if (esc) esc = false; else if (c === '\\') esc = true; else if (c === q) inStr = false; continue; }   // ()=>r(()=>import(PATH).then(p=>p._),
    if (c === '"' || c === "'") { inStr = true; q = c; cur += c; continue; }                                                        // __vite__mapDeps([i,j]),import.meta.url)
    if (c === '[' || c === '{' || c === '(') depth++;
    else if (c === ']' || c === '}' || c === ')') depth--;
    if (c === ',' && !depth) { out.push(cur); cur = ''; continue; }
    cur += c;
  }
  out.push(cur);
  return out;
}

// The `nodes` array (lazy imports, indexed by node id). Slots normally point at ../nodes/N.<hash>.js, but a
// real build proved Vite can FUSE a node into an existing chunk: nodes[96] was import("../chunks/96.<hash>.js")
// (the kit client itself!) and nodes[197] another chunk — the leaf of /(app)/quote/[symbol]/[...catchall].
// A ../nodes/-only regex silently loses such slots (and every route whose leaf is one of them). Parse the
// array positionally: entry i of the array IS node i, whatever file it imports.
export function parseNodesArray(app) {          // -> { nodeFiles: [[id, relPath]], nodeOf: {id: relPath} } | null
  let start = -1;
  const alias = /export\s*\{\s*(\w+)\s+as\s+nodes\b/.exec(app) || /\b(\w+)\s+as\s+nodes\b/.exec(app);
  if (alias) {
    const re = new RegExp('(?:^|[^\\w$.])' + alias[1].replace(/[$]/g, '\\$&') + '\\s*=\\s*\\[');
    const m = re.exec(app);
    if (m) start = app.indexOf('[', m.index + m[0].length - 1);
  }
  if (start < 0) {
    const m = /export\s+const\s+nodes\s*=\s*\[/.exec(app);
    if (m) start = app.indexOf('[', m.index + m[0].length - 1);
  }
  if (start < 0) return null;
  let depth = 0, inStr = false, q = '', esc = false, end = -1;
  for (let i = start; i < app.length; i++) {
    const c = app[i];
    if (inStr) { if (esc) esc = false; else if (c === '\\') esc = true; else if (c === q) inStr = false; continue; }
    if (c === '"' || c === "'") { inStr = true; q = c; continue; }
    if (c === '[') depth++;
    else if (c === ']') { depth--; if (!depth) { end = i; break; } }
  }
  if (end < 0) return null;
  const entries = splitKeep(app.slice(start + 1, end));
  const nodeFiles = []; const nodeDepsIdx = {};
  entries.forEach((e, i) => {
    const m = /import\(\s*["'](\.\.\/[^"']+\.m?js)["']\s*\)/.exec(e);
    if (m) nodeFiles.push([i, m[1].replace(/^\.\.\//, '')]);
    // preload deps are attached per entry: import(PATH).then(p=>p.X),__vite__mapDeps([i,j]),import.meta.url
    // (also for chunk slots: nodes[96] had __vite__mapDeps([4,2]) on a real build)
    const d = /__vite__mapDeps\(\s*\[([^\]]*)\]/.exec(e);
    if (d && d[1].trim()) nodeDepsIdx[i] = d[1];
  });
  return { nodeFiles, nodeOf: Object.fromEntries(nodeFiles), nodeDepsIdx };
}

function parseNodeList(arrLiteral) {           // "[2, , 39]" -> [2, null, 39] (holes preserved as null)
  const inner = arrLiteral.replace(/^\[/, '').replace(/\]$/, '');
  return splitTopLevel(inner).map(x => { const d = decodeLeaf(x); return d ? d.node : null; });
}

export function parseDictionary(app) {         // -> [{ route, leafRaw, pageNode, hasServerLoad, layouts, errors }]
  const obj = findDictionaryObject(app);
  if (!obj) return [];
  const routes = [];
  for (const entry of splitTopLevel(obj.slice(1, -1))) {
    const m = /^["']([^"']+)["']\s*:\s*(\[.*)$/s.exec(entry);
    if (!m) continue;
    const parts = splitTopLevel(m[2].replace(/^\[/, '').replace(/\]$/, ''));
    if (!parts.length) continue;
    const leaf = decodeLeaf(parts[0]);
    if (!leaf) continue;
    const layouts = parts[1] ? parseNodeList(parts[1]) : [];
    const errors = parts[2] ? parseNodeList(parts[2]) : [];
    routes.push({ route: m[1], leafRaw: parts[0], pageNode: leaf.node, hasServerLoad: leaf.hasServerLoad, layouts, errors });
  }
  return routes;
}

// The kit client chunk (entry/start.<hash>.js imports it) prepends node 0 to every route in current builds
// ("layouts:[0,..."). Detect it; never assume it (older formats list the root layout in the dictionary).
export function detectImplicitRoot(root) {     // -> { detected, chunk }
  try {
    const ent = fs.readdirSync(path.join(root, 'entry'));
    const startFile = ent.find(f => /^start\.[A-Za-z0-9_-]{8}\.js$/.test(f));
    if (!startFile) return { detected: false, chunk: null };
    const start = fs.readFileSync(path.join(root, 'entry', startFile), 'utf8');
    const m = /from\s*["']\.\.\/chunks\/([^"']+\.m?js)["']/.exec(start);
    if (!m) return { detected: false, chunk: null };
    let code = null; try { code = fs.readFileSync(path.join(root, 'chunks', m[1]), 'utf8'); } catch { }
    return { detected: !!code && /layouts\s*:\s*\[\s*0\s*,/.test(code), chunk: m[1] };
  } catch { return { detected: false, chunk: null }; }
}

export function parseRoutes(root) {            // -> { appFile, nodeFiles, routes } (raw or prettified tree)
  const appFile = fs.readdirSync(path.join(root, 'entry')).find(f => /^app\.[A-Za-z0-9_-]{8}\.js$/.test(f));
  if (!appFile) throw new Error('no entry/app.<hash>.js under ' + root);
  const app = fs.readFileSync(path.join(root, 'entry', appFile), 'utf8');
  const parsed = parseNodesArray(app);
  const nodeFiles = parsed ? parsed.nodeFiles : [...app.matchAll(/import\(\s*["']\.\.\/nodes\/(\d+)\.([A-Za-z0-9_-]+)\.js["']\s*\)/g)].map(m => [+m[1], `nodes/${m[1]}.${m[2]}.js`]);
  const routes = parseDictionary(app);
  return { appFile, nodeFiles, routes };
}
