// usage: node detect_roles.mjs <buildRoot> <out.json>
// Finds, by CODE SIGNATURE (not by chunk name: Rollup renames chunks and re-letters exports on every build), which chunk/export plays each Svelte 4 runtime role:
//   init                 function with an object literal holding {fragment, ctx, props, on_mount, on_destroy, skip_bound, ...}
//   component_subscribe  3-param function whose body is `x.$$.on_destroy.push(...)`
//   safe_not_equal       2-param function `a != a ? b == b : a !== b || (a && typeof a == "object") || typeof a == "function"`
// out.json: { "<role>": { "chunk": "<chunk base name>", "export": "<export letter>", "candidates": n }, ... }  (only roles found exactly once)
// A role that is not found exactly once is omitted (never guessed); transform.mjs then skips the annotations that depend on it.
import fs from 'node:fs'; import path from 'node:path';
import { parse } from '@babel/parser'; import _t from '@babel/traverse';
const traverse = _t.default ?? _t;
const [root, outFile] = process.argv.slice(2);
if (!root || !outFile) { console.error('usage: node detect_roles.mjs <buildRoot> <out.json>'); process.exit(2); }
const dir = path.join(root, 'chunks'); const CHUNK_RE = /([^/]+?)\.[A-Za-z0-9_-]{8}\.js$/;
const found = { init: [], component_subscribe: [], safe_not_equal: [] };
const svelte5Files = new Set();
const INIT_KEYS = ['fragment', 'ctx', 'props', 'update', 'not_equal', 'bound', 'on_mount', 'on_destroy', 'before_update', 'after_update', 'context', 'callbacks', 'dirty', 'skip_bound', 'root'];
for (const f of fs.readdirSync(dir)) {
  const m = f.match(CHUNK_RE); if (!m) continue;
  const code = fs.readFileSync(path.join(dir, f), 'utf8');
  // Svelte 5 (Runes) builds use a different runtime ($.template/$.state/$.effect/$.props)
  // and no Svelte 4 lifecycle — report the suspicion instead of failing silently.
  if (/\$\.(?:template|state|derived|effect|props)\s*\(/.test(code)) svelte5Files.add(f);
  if (!code.includes('$$') && !code.includes('skip_bound') && !code.includes('typeof')) continue;
  if (!(code.includes('skip_bound') || code.includes('on_destroy') || /!=\w+\?\w+==\w+:/.test(code))) continue;
  let ast; try { ast = parse(code, { sourceType: 'module', plugins: ['jsx'] }); } catch { continue; }
  let prog; traverse(ast, { Program(p) { prog = p; p.stop(); } });
  const exps = new Map(); // local -> exported
  for (const n of prog.node.body) if (n.type === 'ExportNamedDeclaration') {
    for (const s of n.specifiers) exps.set(s.local.name, s.exported.name ?? s.exported.value);
    if (n.declaration?.id) exps.set(n.declaration.id.name, n.declaration.id.name);
  }
  const fnOf = (name) => { const b = prog.scope.getBinding(name); if (!b) return null; const n = b.path.node;
    if (n.type === 'FunctionDeclaration') return n;
    if (n.type === 'VariableDeclarator' && /^(FunctionExpression|ArrowFunctionExpression)$/.test(n.init?.type)) return n.init; return null; };
  for (const [local, exported] of exps) {
    const fn = fnOf(local); if (!fn) continue; const src = code.slice(fn.start, fn.end);
    const stmt0 = fn.body.type === 'BlockStatement' && fn.body.body.length === 1 ? code.slice(fn.body.body[0].start, fn.body.body[0].end) : '';
    if (fn.params.length === 3 && /^\w+\.\$\$\.on_destroy\.push\(/.test(stmt0)) found.component_subscribe.push({ chunk: m[1], export: exported, file: f });
    if (fn.params.length === 2 && src.length < 160 && /(\w+)!=\1\?(\w+)==\2:\1!==\2\|\|\1&&typeof \1==["']object["']\|\|typeof \1==["']function["']/.test(src)) found.safe_not_equal.push({ chunk: m[1], export: exported, file: f });
    if (fn.params.length >= 5 && src.length < 4000 && INIT_KEYS.filter(k => new RegExp('\\b' + k + '\\s*:').test(src) || (k === 'bound' && /\bbound\s*:/.test(src))).length >= 12) found.init.push({ chunk: m[1], export: exported, file: f });
  }
}
const out = {}; const notes = {};
for (const [role, list] of Object.entries(found)) {
  const uniq = [...new Map(list.map(x => [x.chunk + '::' + x.export, x])).values()];
  if (uniq.length === 1) out[role] = { chunk: uniq[0].chunk, export: uniq[0].export, file: uniq[0].file };
  else notes[role] = uniq.length === 0 ? 'not found' : 'ambiguous: ' + uniq.map(x => x.chunk + '::' + x.export).join(', ');
}
if (!Object.keys(out).length && svelte5Files.size) {
  notes.svelte5Suspect = svelte5Files.size + ' chunk(s) contain Svelte 5 runtime primitives '
    + '($.template/$.state/$.effect/$.props) and no Svelte 4 lifecycle signatures — role detection '
    + 'does not apply to Svelte 5; the pipeline degrades to renames-only.';
  console.error('WARNING: ' + notes.svelte5Suspect);
}
fs.writeFileSync(outFile, JSON.stringify({ roles: out, notFoundOrAmbiguous: notes, svelte5Chunks: svelte5Files.size }, null, 1));
console.log(JSON.stringify({ roles: out, notFoundOrAmbiguous: notes, svelte5Chunks: svelte5Files.size }));
