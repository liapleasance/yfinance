// usage: node kit_names.mjs <buildRoot> <out.json> [versions=comma list]
// Names the functions of the SvelteKit CLIENT chunk of ANY build by matching them structurally (shape_match.mjs) against the OFFICIAL @sveltejs/kit source.
//  - The chunk is found from the build itself: entry/start.<hash>.js always imports it (`import{s as t}from"../chunks/<chunk>.js";export{t as start}`).
//  - Source files: every non-server .js under src/runtime and src/utils of the packed package, minified with esbuild's syntax minifier (like Vite).
//  - Several kit versions are tried (npm pack); the one with the most unique matches wins and is reported (the build does not state its kit version).
//  - A name is used only when the shape is unique on both sides and long enough to be distinctive (>= 60 shape nodes). Never guessed.
// out.json: { chunk, file, kitVersion, tried:{ver:matches}, exports:{ "<export letter>":["name","B"] }, locals:{ "<local>":["name","B"] } }
// Needs the npm registry. Names that are very short/generic in the source (get, set, escape...) get the source file stem as prefix (session_storage_get).
import fs from 'node:fs'; import path from 'node:path'; import os from 'node:os'; import { execFileSync } from 'node:child_process'; import { fileURLToPath } from 'node:url';
import { transformSync } from 'esbuild'; import { parse } from '@babel/parser';
import { topShapes } from './shape_match.mjs';
const [root, outFile, versArg] = process.argv.slice(2);
if (!root || !outFile) { console.error('usage: node kit_names.mjs <buildRoot> <out.json> [versions]'); process.exit(2); }
const NPM = process.platform === 'win32' ? 'npm.cmd' : 'npm';   // spawnSync cannot exec the npm shell wrapper on Windows
const NPM_SHELL = process.platform === 'win32';   // and .cmd/.bat spawn requires shell:true on Node >= 18 (EINVAL otherwise)
const VERSIONS = (versArg || process.env.YFIN_KIT_VERSIONS || '2.5.0,2.8.0,2.12.0,2.16.0,2.20.0,2.30.0,2.40.0,2.50.0,2.60.0,3.0.0,3.1.0').split(',');
const entryDir = path.join(root, 'entry'); const startFile = fs.readdirSync(entryDir).find(f => /^start\.[A-Za-z0-9_-]{8}\.js$/.test(f));
if (!startFile) { console.error('no entry/start.<hash>.js'); process.exit(2); }
const startSrc = fs.readFileSync(path.join(entryDir, startFile), 'utf8'); const imp = startSrc.match(/from\s*["']\.\.\/chunks\/([^"']+\.js)["']/);
if (!imp) { console.error('start.*.js has no import from ../chunks/ (unexpected layout)'); process.exit(2); }
const chunkFile = imp[1]; const chunkCode = fs.readFileSync(path.join(root, 'chunks', chunkFile), 'utf8'); const chunkBase = chunkFile.match(/^(.+?)\.[A-Za-z0-9_-]{8}\.js$/)[1];
const gotAll = topShapes(chunkCode); const gotCount = {}; for (const s of Object.values(gotAll)) gotCount[s] = (gotCount[s] || 0) + 1;
// exported letters of the chunk: local -> [export names]
const ast = parse(chunkCode, { sourceType: 'module' }); const expOf = {};
for (const n of ast.program.body) if (n.type === 'ExportNamedDeclaration') { for (const s of n.specifiers) (expOf[s.local.name] ??= []).push(s.exported.name ?? s.exported.value); }
function refFor(ver) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-src-'));
  execFileSync(NPM, ['pack', '@sveltejs/kit@' + ver, '--silent'], { cwd: tmp, stdio: ['ignore', 'pipe', 'inherit'], shell: NPM_SHELL });
  execFileSync('tar', ['xzf', fs.readdirSync(tmp).find(f => f.endsWith('.tgz'))], { cwd: tmp });
  const base = path.join(tmp, 'package', 'src'); const files = [];
  (function walk(d) { for (const e of fs.readdirSync(d, { withFileTypes: true })) { const p = path.join(d, e.name); if (e.isDirectory()) { if (!/^(server|telemetry|types|exports|core|cli|vite|node)$/.test(e.name)) walk(p); } else if (/\.js$/.test(e.name)) files.push(p); } })(base);
  const ref = new Map();
  for (const f of files) { const rel = path.relative(base, f).split(path.sep).join('/'); if (!/^(runtime|utils)\//.test(rel)) continue;   // '/' always: the filter regex and the reports use forward slashes
    let code; try { code = transformSync(fs.readFileSync(f, 'utf8').replace(/^import\s*\{[^}]*\}\s*from\s*['"]esm-env['"];?/gm, ''), { minifySyntax: true, minifyWhitespace: true, format: 'esm', loader: 'js', target: 'es2022', define: { DEV: 'false', BROWSER: 'true', BUILDING: 'false' } }).code; } catch { continue; }
    let sh; try { sh = topShapes(code); } catch { continue; }
    for (const [n, s] of Object.entries(sh)) { if (s.length < 60) continue; (ref.get(s) ?? ref.set(s, []).get(s)).push({ name: n, stem: path.basename(rel, '.js') }); } }
  fs.rmSync(tmp, { recursive: true, force: true }); return ref;
}
function matchWith(ref) { const res = {}; for (const [l, s] of Object.entries(gotAll)) { const c = ref.get(s); if (c && c.length === 1 && gotCount[s] === 1) res[l] = c[0]; } return res; }
let best = null; const tried = {};
for (const v of VERSIONS) { let r; try { r = matchWith(refFor(v)); } catch (e) { console.error('WARNING: kit@' + v + ' unavailable: ' + String(e.message).split('\n')[0]); continue; } tried[v] = Object.keys(r).length; if (!best || tried[v] > best.n) best = { v, n: tried[v], r }; }
if (!best || best.n === 0) { fs.writeFileSync(outFile, JSON.stringify({ chunk: chunkBase, file: chunkFile, kitVersion: null, tried, exports: {}, locals: {} }, null, 1)); console.log(JSON.stringify({ chunk: chunkBase, kitVersion: null, tried })); process.exit(0); }
const GENERIC = new Set(['get', 'set', 'escape', 'hash', 'find', 'parse', 'run', 'init', 'start', 'stop', 'noop']);
const used = new Map(); const nameFor = (m) => { let nm = m.name; if (nm.length <= 4 || GENERIC.has(nm)) nm = m.stem.replace(/[^A-Za-z0-9_$]/g, '_') + '_' + nm; let k = nm, i = 2; while (used.has(k)) k = nm + '_' + i++; used.set(k, 1); return k; };
const exportsOut = {}, localsOut = {};
for (const [l, m] of Object.entries(best.r)) { const nm = nameFor(m); if (expOf[l]) { for (const e of expOf[l]) exportsOut[e] = [nm, 'B']; } else localsOut[l] = [nm, 'B']; }
const out = { chunk: chunkBase, file: chunkFile, kitVersion: best.v, tried, exports: exportsOut, locals: localsOut };
fs.writeFileSync(outFile, JSON.stringify(out, null, 1));
console.log(JSON.stringify({ chunk: chunkBase, kitVersion: best.v, tried, exports: Object.keys(exportsOut).length, locals: Object.keys(localsOut).length, totalFunctions: Object.keys(gotAll).length }));
