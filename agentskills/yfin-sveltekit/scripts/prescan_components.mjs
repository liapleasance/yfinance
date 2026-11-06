// usage: node prescan_components.mjs <buildRoot> <out.json> <roles.json>   (roles.json = output of detect_roles.mjs, e.g. <names_map>.mjs.roles.json written by make_map.mjs)
// For each chunk file: which exports are Svelte components (class that calls init() of the Svelte runtime)?
// Output: { "<chunk file name>": { "<exportName>": "<suggested readable name>" } }
import fs from 'node:fs'; import path from 'node:path';
import { parse } from '@babel/parser'; import _traverse from '@babel/traverse';
const traverse = _traverse.default ?? _traverse;
const [root, outFile, rolesFile] = process.argv.slice(2);
if (!root || !outFile || !rolesFile) { console.error('usage: node prescan_components.mjs <buildRoot> <out.json> <roles.json>'); process.exit(2); }
const INIT = JSON.parse(fs.readFileSync(rolesFile, 'utf8')).roles.init;
if (!INIT) { console.error('WARNING: no init role in ' + rolesFile + ' (not a Svelte 4 build?): no components can be recognised; writing {}'); fs.writeFileSync(outFile, '{}'); console.log({ scanned: 0, chunksWithComponents: 0 }); process.exit(0); }
const dir = path.join(root, 'chunks');
const CHUNK_RE = /([^/]+?)\.[A-Za-z0-9_-]{8}\.js$/;
const sanitize = s => s.replace(/[^A-Za-z0-9_$]/g, '_');
const result = {}; let scanned = 0;
for (const f of fs.readdirSync(dir)) {
  if (!f.endsWith('.js')) continue; const m = f.match(CHUNK_RE); if (!m) continue;
  const base = m[1]; if (!/^[A-Z]/.test(base)) continue;            // components are PascalCase file names
  const code = fs.readFileSync(path.join(dir, f), 'utf8'); if (!code.includes('extends')) continue;
  let ast; try { ast = parse(code, { sourceType: 'module', plugins: ['jsx'] }); } catch { continue; }
  scanned++; let prog; traverse(ast, { Program(p) { prog = p; p.stop(); } });
  const comps = new Set(); // binding names of component classes
  traverse(ast, { CallExpression(p) {
    const c = p.node.callee; if (c.type !== 'Identifier') return; const b = p.scope.getBinding(c.name);
    if (!b || !b.path.isImportSpecifier()) return; const src = b.path.parent.source.value;
    const imp = b.path.node.imported.name ?? b.path.node.imported.value;
    if (imp !== INIT.export || !new RegExp('(^|/)' + INIT.chunk.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\.[A-Za-z0-9_-]{8}\\.js$').test(src)) return;
    const cls = p.findParent(q => q.isClassDeclaration() || q.isClassExpression()); if (!cls) return;
    if (cls.node.id) comps.add(cls.node.id.name);
    else if (cls.parentPath.isVariableDeclarator() && cls.parent.id.type === 'Identifier') comps.add(cls.parent.id.name);
  } });
  if (!comps.size) continue;
  const exps = []; // [exportName, localName]
  for (const n of prog.node.body) if (n.type === 'ExportNamedDeclaration') {
    for (const s of n.specifiers) exps.push([s.exported.name ?? s.exported.value, s.local.name]);
    if (n.declaration) { const d = n.declaration; if (d.id) exps.push([d.id.name, d.id.name]); else if (d.declarations) for (const x of d.declarations) if (x.id.type === 'Identifier') exps.push([x.id.name, x.id.name]); }
  }
  const compExps = exps.filter(([, l]) => comps.has(l)); if (!compExps.length) continue;
  const distinctLocals = new Set(compExps.map(([, l]) => l));
  const map = {};
  for (const [e, l] of compExps) map[e] = distinctLocals.size === 1 ? sanitize(base) : sanitize(base) + '_' + sanitize(e);
  result[f] = map;
}
fs.writeFileSync(outFile, JSON.stringify(result, null, 1));
console.log({ scanned, chunksWithComponents: Object.keys(result).length });
console.log(Object.entries(result).slice(0, 8).map(([k, v]) => k + ' ' + JSON.stringify(v)).join('\n'));
