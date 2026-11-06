// usage: node verify_pair.mjs <origRoot> <newRoot> <report.tsv>   (exit 1 on any problem)
// Per file: parses, import/export specifiers identical to the original, no string literal of the original missing. Part of verify_all.sh.
import fs from 'node:fs'; import path from 'node:path'; import { parse } from '@babel/parser'; import _t from '@babel/traverse';
const traverse = _t.default ?? _t;
const [origRoot, newRoot, reportFile] = process.argv.slice(2);
if (!origRoot || !newRoot || !reportFile) { console.error('usage: node verify_pair.mjs <origRoot> <newRoot> <report.tsv>'); process.exit(2); }
const files = []; (function walk(d){ for (const e of fs.readdirSync(d,{withFileTypes:true})) { const p=path.join(d,e.name); if(e.isDirectory()) walk(p); else if(/\.m?js$/.test(e.name)) files.push(path.relative(origRoot,p)); } })(origRoot);
function sig(ast) {
  const imports = [], exportsL = [];
  for (const n of ast.program.body) {
    if (n.type==='ImportDeclaration') for (const s of n.specifiers) imports.push(n.source.value+'::'+(s.type==='ImportSpecifier'?(s.imported.name??s.imported.value):s.type));
    if (n.type==='ExportNamedDeclaration') for (const s of n.specifiers) exportsL.push(s.exported.name??s.exported.value);
    if (n.type==='ExportDefaultDeclaration') exportsL.push('default');
    if (n.type==='ExportNamedDeclaration' && n.declaration) { const d=n.declaration; if (d.id) exportsL.push(d.id.name); else if (d.declarations) for (const x of d.declarations) { (function g(p){ if(p.type==='Identifier') exportsL.push(p.name); else if(p.type==='ObjectPattern') p.properties.forEach(q=>g(q.value??q.argument)); else if(p.type==='ArrayPattern') p.elements.forEach(q=>q&&g(q)); })(x.id); } }
    if (n.type==='ExportAllDeclaration') exportsL.push('*'+n.source.value);
  }
  return { imports: imports.sort().join('|'), exports: exportsL.sort().join('|') };
}
function strings(ast, minLen=4) { const s = new Set(); traverse(ast,{ StringLiteral(p){ if (p.node.value.length>=minLen) s.add(p.node.value); }, TemplateLiteral(p){ for (const q of p.node.quasis) if ((q.value.cooked??'').length>=minLen) s.add(q.value.cooked); }, JSXText(p){ if (p.node.value.length>=minLen) s.add(p.node.value); } }); return s; }
let problems = []; let ok = 0, parseFail = 0, i = 0;
for (const rel of files) {
  const a = fs.readFileSync(path.join(origRoot,rel),'utf8'); let b;
  try { b = fs.readFileSync(path.join(newRoot,rel),'utf8'); } catch { problems.push([rel,'missing output']); continue; }
  let A, B; try { A = parse(a,{sourceType:'module',plugins:['jsx']}); } catch(e){ problems.push([rel,'orig parse fail']); continue; }
  try { B = parse(b,{sourceType:'module',plugins:['jsx']}); } catch(e){ parseFail++; problems.push([rel,'OUTPUT PARSE FAIL '+e.message]); continue; }
  const sa = sig(A), sb = sig(B);
  if (sa.imports !== sb.imports) problems.push([rel,'imports differ']);
  if (sa.exports !== sb.exports) problems.push([rel,'exports differ']);
  const strA = strings(A); let miss = 0; const missEx = [];
  const joinedB = [...strings(B,1)].join('\u0001');
  for (const s of strA) if (!joinedB.includes(s) && !b.includes(s)) { miss++; if (missEx.length<2) missEx.push(s.slice(0,40)); }
  if (miss) problems.push([rel,`${miss} string literals not found in output, e.g. ${JSON.stringify(missEx)}`]);
  else if (sa.imports===sb.imports && sa.exports===sb.exports) ok++;
}
fs.writeFileSync(reportFile, problems.map(p=>p.join('\t')).join('\n'));
console.log({ total: files.length, fully_ok: ok, parseFail, problems: problems.length });
console.log(problems.slice(0,15).map(p=>p.join('  ')).join('\n'));
process.exit(problems.length ? 1 : 0);
