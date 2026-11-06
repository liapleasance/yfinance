// usage: node scan_hazards.mjs <origRoot> <stage1Root> <out.json> [--no-strings] [--strict-length]
// Compares the ORIGINAL build with the Wakaru output (stage1) file by file and flags every file whose Wakaru rewrite is not safe to trust.
// Writes <out.json> ({ "<rel>": ["reason", ...] }) and <out.json>.list.txt (one relative path per line = the FALLBACK list: those files
// must be rebuilt from the original instead of from Wakaru output; see references/wakaru-hazards.md).
//
// Reasons (each one corresponds to a real breakage found on the finance.yahoo.com build):
//   jsx                    stage1 contains JSX that the original did not (not executable in a browser)
//   new-classes a->b       Wakaru turned ES5 constructor functions into `class` (a class cannot be called without `new`)
//   class-called-without-new / class-call-apply  same file calls/.call()s a class it declares
//   interop-helper         original uses TS/Babel interop helpers (__importDefault ...) that Wakaru simplifies unsafely
//   function-length-drift  (INFO ONLY unless --strict-length; on the real build 111 files drift, harmless in practice, so it does NOT force a fallback)
//                          the multiset of Function.length values changed (Wakaru turned `a===void 0&&(a=x)` into a default parameter, which
//                          changes `fn.length`; found on the floating-ui helpers of the `approval` chunk)
//   strings-lost n         string literals present in the original are missing from stage1 (helper code was inlined/removed)
//   imports-differ / exports-differ / stage1-parse-fail / orig-parse-fail
import fs from 'node:fs'; import path from 'node:path';
import { parse } from '@babel/parser'; import _t from '@babel/traverse';
const traverse = _t.default ?? _t;
const args = process.argv.slice(2); const flags = args.filter(a => a.startsWith('--')); const [origRoot, s1Root, outFile] = args.filter(a => !a.startsWith('--'));
if (!origRoot || !s1Root || !outFile) { console.error('usage: node scan_hazards.mjs <origRoot> <stage1Root> <out.json> [--no-strings] [--strict-length]'); process.exit(2); }
const DO_STRINGS = !flags.includes('--no-strings'); const STRICT = flags.includes('--strict-length');
const files = []; (function walk(d) { for (const e of fs.readdirSync(d, { withFileTypes: true })) { const p = path.join(d, e.name); if (e.isDirectory()) walk(p); else if (/\.m?js$/.test(e.name)) files.push(path.relative(s1Root, p).split(path.sep).join('/')); } })(s1Root);   // '/' always: the list feeds apply_fallback and the reports
files.sort();
const INTEROP = /__importDefault|__importStar|__createBinding|__setModuleDefault/;
function sig(ast) {
  const imports = [], exportsL = [];
  const ids = (p, out) => { if (p.type === 'Identifier') out.push(p.name); else if (p.type === 'ObjectPattern') p.properties.forEach(q => ids(q.value ?? q.argument, out)); else if (p.type === 'ArrayPattern') p.elements.forEach(q => q && ids(q, out)); };
  for (const n of ast.program.body) {
    if (n.type === 'ImportDeclaration') for (const s of n.specifiers) imports.push(n.source.value + '::' + (s.type === 'ImportSpecifier' ? (s.imported.name ?? s.imported.value) : s.type));
    if (n.type === 'ExportNamedDeclaration') for (const s of n.specifiers) exportsL.push(s.exported.name ?? s.exported.value);
    if (n.type === 'ExportDefaultDeclaration') exportsL.push('default');
    if (n.type === 'ExportNamedDeclaration' && n.declaration) { const d = n.declaration; if (d.id) exportsL.push(d.id.name); else if (d.declarations) for (const x of d.declarations) ids(x.id, exportsL); }
    if (n.type === 'ExportAllDeclaration') exportsL.push('*' + n.source.value);
  }
  return imports.sort().join('|') + '##' + exportsL.sort().join('|');
}
const strings = (ast, min = 4) => { const s = new Set(); traverse(ast, { StringLiteral(p) { if (p.node.value.length >= min) s.add(p.node.value); }, TemplateLiteral(p) { for (const q of p.node.quasis) if ((q.value.cooked ?? '').length >= min) s.add(q.value.cooked); }, JSXText(p) { if (p.node.value.length >= min) s.add(p.node.value); } }); return s; };
const arity = (fn) => { let n = 0; for (const p of fn.params) { if (p.type === 'AssignmentPattern' || p.type === 'RestElement') break; n++; } return n; };
const countKinds = (ast) => { let cls = 0, jsx = 0; const len = {}; traverse(ast, { Class() { cls++; }, JSXElement() { jsx++; }, JSXFragment() { jsx++; }, Function(p) { const k = arity(p.node); len[k] = (len[k] || 0) + 1; } }); return { cls, jsx, len }; };
const res = {}, info = {}; let identical = 0, checked = 0;
for (const rel of files) {
  let o; try { o = fs.readFileSync(path.join(origRoot, rel), 'utf8'); } catch { res[rel] = ['no-original']; continue; }
  const n = fs.readFileSync(path.join(s1Root, rel), 'utf8');
  if (o === n) { identical++; continue; }
  checked++;
  const reasons = [];
  let A, B;
  try { A = parse(o, { sourceType: 'module', plugins: ['jsx'] }); } catch { res[rel] = ['orig-parse-fail']; continue; }
  try { B = parse(n, { sourceType: 'module', plugins: ['jsx'] }); } catch { res[rel] = ['stage1-parse-fail']; continue; }
  const ka = countKinds(A), kb = countKinds(B);
  if (kb.jsx > ka.jsx) reasons.push('jsx');
  if (kb.cls > ka.cls) reasons.push(`new-classes ${ka.cls}->${kb.cls}`);
  if (INTEROP.test(o)) reasons.push('interop-helper');
  { const ks = new Set([...Object.keys(ka.len), ...Object.keys(kb.len)]); const d = []; for (const k of ks) if ((ka.len[k] || 0) !== (kb.len[k] || 0)) d.push(`${k}:${ka.len[k] || 0}->${kb.len[k] || 0}`); if (d.length) { info[rel] = ['function-length-drift ' + d.slice(0, 4).join(',')]; if (STRICT) reasons.push('function-length-drift ' + d.slice(0, 4).join(',')); }
  }
  if (sig(A) !== sig(B)) reasons.push(sig(A).split('##')[0] !== sig(B).split('##')[0] ? 'imports-differ' : 'exports-differ');
  traverse(B, {
    'ClassDeclaration|ClassExpression'(p) {
      const id = p.node.id; if (!id) return;
      const b = p.scope.getBinding(id.name) ?? p.scope.parent?.getBinding(id.name); if (!b) return;
      for (const rp of b.referencePaths) {
        const par = rp.parentPath;
        if (par.isCallExpression({ callee: rp.node })) { reasons.push('class-called-without-new ' + id.name); break; }
        if (par.isMemberExpression({ object: rp.node }) && !par.node.computed && ['call', 'apply'].includes(par.node.property.name) && !p.node.superClass) { reasons.push('class-call-apply ' + id.name); break; }
      }
    },
  });
  if (DO_STRINGS) {
    const sb = strings(B, 1); const joined = [...sb].join('\u0001'); let miss = 0;
    for (const s of strings(A)) if (!joined.includes(s) && !n.includes(s)) miss++;
    if (miss) reasons.push(`strings-lost ${miss}`);
  }
  if (reasons.length) res[rel] = [...new Set(reasons)].slice(0, 6);
}
fs.writeFileSync(outFile, JSON.stringify(res, null, 1));
fs.writeFileSync(outFile + '.info.json', JSON.stringify(info, null, 1));
fs.writeFileSync(outFile + '.list.txt', Object.keys(res).sort().join('\n') + (Object.keys(res).length ? '\n' : ''));
const kinds = {}; for (const v of Object.values(res)) for (const r of v) { const k = r.split(' ')[0]; kinds[k] = (kinds[k] || 0) + 1; }
console.log(JSON.stringify({ files: files.length, identicalToOriginal: identical, compared: checked, flagged: Object.keys(res).length, lengthDriftInfoOnly: Object.keys(info).length, byReason: kinds }));
