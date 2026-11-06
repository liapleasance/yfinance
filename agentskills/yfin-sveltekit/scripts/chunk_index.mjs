// usage: node chunk_index.mjs <finalRoot> <out.md> [roles.json] [component_exports.json]
// A navigation index of chunks/*.js: size, number of exports, how many files import it, what it imports, and a kind only when there is EVIDENCE
// (svelte runtime / sveltekit client from the roles file, svelte component from the component prescan). Sorted by importers: the most shared
// code first. It does not guess what a chunk "is" from its name.
import fs from 'node:fs'; import path from 'node:path';
const [root, out, rolesFile, compFile] = process.argv.slice(2); if (!root || !out) { console.error('usage: node chunk_index.mjs <finalRoot> <out.md> [roles.json] [component_exports.json]'); process.exit(2); }
const roles = rolesFile && fs.existsSync(rolesFile) ? JSON.parse(fs.readFileSync(rolesFile, 'utf8')).roles || {} : {};
const comps = compFile && fs.existsSync(compFile) ? JSON.parse(fs.readFileSync(compFile, 'utf8')) : {};
let kitChunkFile = null; try { const st = fs.readdirSync(path.join(root, 'entry')).find(f => /^start\.[A-Za-z0-9_-]{8}\.js$/.test(f)); kitChunkFile = fs.readFileSync(path.join(root, 'entry', st), 'utf8').match(/from\s*["']\.\.\/chunks\/([^"']+\.js)["']/)?.[1] || null; } catch {}
const kindOf = (file) => { const b = file.replace(/\.[A-Za-z0-9_-]{8}\.js$/, ''); const k = []; if (file === kitChunkFile) k.push('sveltekit client (imported by entry/start)');
  if (roles.init && roles.init.chunk === b) k.push('svelte runtime (init)'); if (roles.component_subscribe && roles.component_subscribe.chunk === b) k.push('svelte runtime');
  if (roles.safe_not_equal && roles.safe_not_equal.chunk === b) k.push('svelte runtime');
  if (comps[file]) k.push('svelte component'); return [...new Set(k)].join(', '); };
const all = []; (function walk(d) { for (const e of fs.readdirSync(d, { withFileTypes: true })) { const p = path.join(d, e.name); if (e.isDirectory()) walk(p); else if (/\.m?js$/.test(e.name)) all.push(path.relative(root, p).split(path.sep).join('/')); } })(root);   // '/' always: rows are filtered by the 'chunks/' prefix
const importers = {}, imports = {};
for (const rel of all) { const src = fs.readFileSync(path.join(root, rel), 'utf8');
  const specs = new Set([...src.matchAll(/(?:from|import)\s*\(?\s*["'](\.{1,2}\/[^"']+\.m?js)["']/g)].map(m => path.normalize(path.join(path.dirname(rel), m[1]))));
  imports[rel] = specs.size; for (const s of specs) (importers[s] ??= new Set()).add(rel); }
const rows = all.filter(r => r.startsWith('chunks/')).map(r => { const src = fs.readFileSync(path.join(root, r), 'utf8'); const ex = (src.match(/^export\s*\{([^}]*)\}/m)?.[1] || '').split(',').filter(x => x.trim()).length + (src.match(/^export\s+(?:async\s+)?(?:function|class|const|let|var)\s/gm) || []).length;
  return { r: path.basename(r), kb: Math.round(src.length / 1024), ex, imp: importers[r]?.size || 0, deps: imports[r], kind: kindOf(path.basename(r)) }; }).sort((a, b) => b.imp - a.imp || b.kb - a.kb);
fs.writeFileSync(out, '# Chunk index\n\nSorted by number of importing files (most shared first). `kind` only where there is evidence (code-signature roles or component prescan); empty = unknown, read the code.\n\n| chunk | KB | exports | imported by | imports | kind |\n|---|---|---|---|---|---|\n' + rows.map(x => `| ${x.r} | ${x.kb} | ${x.ex} | ${x.imp} | ${x.deps} | ${x.kind} |`).join('\n') + '\n');
console.log(JSON.stringify({ chunks: rows.length }));
