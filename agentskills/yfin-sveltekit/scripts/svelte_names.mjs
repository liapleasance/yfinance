// usage: node svelte_names.mjs <buildRoot> <out.json> [svelteVersion=4.2.19]
// Names the Svelte runtime exports of ANY build by matching them structurally against the OFFICIAL Svelte source (npm pack svelte@<ver>, bundled and
// minified with esbuild like Vite does). A match is only used when the shape is unique on both sides, so a name is evidence (confidence B), never a guess.
// Needs network access to the npm registry (npm works through the sandbox proxy). Unmatched exports stay unnamed.
// out.json: { "<chunk base>": { "<export letter>": ["<svelte name>", "B"] }, ... , "_report": {version, chunksWithMatches, matched} }
import fs from 'node:fs'; import path from 'node:path'; import os from 'node:os'; import { execFileSync } from 'node:child_process'; import { fileURLToPath, pathToFileURL } from 'node:url';
import { build as esbuildBuild } from 'esbuild';   // JS API: the .bin shim is a unix shell script and .cmd spawn needs shell:true — this works on every OS
import { exportShapes } from './shape_match.mjs';
const [root, outFile, ver = '4.2.19'] = process.argv.slice(2);
if (!root || !outFile) { console.error('usage: node svelte_names.mjs <buildRoot> <out.json> [svelteVersion]'); process.exit(2); }
const here = path.dirname(fileURLToPath(import.meta.url));
const NPM = process.platform === 'win32' ? 'npm.cmd' : 'npm';   // spawnSync cannot exec the npm shell wrapper on Windows
const NPM_SHELL = process.platform === 'win32';   // and .cmd/.bat spawn requires shell:true on Node >= 18 (EINVAL otherwise)
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'svelte-src-'));
execFileSync(NPM, ['pack', 'svelte@' + ver, '--silent'], { cwd: tmp, stdio: ['ignore', 'pipe', 'inherit'], shell: NPM_SHELL });
execFileSync('tar', ['xzf', fs.readdirSync(tmp).find(f => f.endsWith('.tgz'))], { cwd: tmp });
fs.writeFileSync(path.join(tmp, 'entry.js'), `export * from './package/src/runtime/internal/index.js';
export { writable, readable, derived, readonly, get } from './package/src/runtime/store/index.js';
export { onMount, onDestroy, beforeUpdate, afterUpdate, setContext, getContext, getAllContexts, hasContext, tick, createEventDispatcher } from './package/src/runtime/index.js';\n`);
await esbuildBuild({ entryPoints: [path.join(tmp, 'entry.js')], bundle: true, format: 'esm', minify: true, outfile: path.join(tmp, 'rt.min.js'), logLevel: 'error' });
const ref = exportShapes(fs.readFileSync(path.join(tmp, 'rt.min.js'), 'utf8')); const by = new Map();
for (const [n, s] of Object.entries(ref)) (by.get(s) ?? by.set(s, []).get(s)).push(n);
const CHUNK_RE = /([^/]+?)\.[A-Za-z0-9_-]{8}\.js$/; const dir = path.join(root, 'chunks'); const out = {}; let matched = 0, chunks = 0;
for (const f of fs.readdirSync(dir)) {
  const m = f.match(CHUNK_RE); if (!m) continue; const code = fs.readFileSync(path.join(dir, f), 'utf8');
  if (code.length < 3000 || !/\$\$|createElement|Object\.create\(null\)/.test(code)) continue;  // cheap pre-filter: the runtime chunks are big and DOM-related
  let got; try { got = exportShapes(code); } catch (e) { console.error('WARNING: cannot parse ' + f + ': ' + String(e.message).split('\n')[0]); continue; }
  const gotCount = {}; for (const s of Object.values(got)) gotCount[s] = (gotCount[s] || 0) + 1;
  const res = {}; for (const [e, s] of Object.entries(got)) { const c = by.get(s); if (c && c.length === 1 && gotCount[s] === 1 && s.length > 40) res[e] = [c[0], 'B']; }
  if (Object.keys(res).length >= 5) { out[m[1]] = res; matched += Object.keys(res).length; chunks++; }
}
out._report = { svelteVersion: ver, chunksWithMatches: chunks, matchedExports: matched };
fs.writeFileSync(outFile, JSON.stringify(out, null, 1)); fs.rmSync(tmp, { recursive: true, force: true });
console.log(JSON.stringify(out._report), Object.entries(out).filter(([k]) => k !== '_report').map(([k, v]) => k + ':' + Object.keys(v).length).join(' '));
