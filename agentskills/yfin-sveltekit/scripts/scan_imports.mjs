// usage: node scan_imports.mjs <root> <out.json>   -> { "<chunkBase>::<exportName>": <number of importing files> } over all .js/.mjs under <root>.
import fs from 'node:fs'; import path from 'node:path';
import { parse } from '@babel/parser';
const root = process.argv[2]; const out = process.argv[3];
const files = []; (function walk(d){ for (const e of fs.readdirSync(d,{withFileTypes:true})) { const p=path.join(d,e.name); if(e.isDirectory()) walk(p); else if(/\.m?js$/.test(e.name)) files.push(p);} })(root);
const counts = {}; let fail = 0, ok = 0;
for (const f of files) {
  const src = fs.readFileSync(f,'utf8');
  let ast; try { ast = parse(src,{sourceType:'module',errorRecovery:true}); ok++; } catch(e){ fail++; continue; }
  for (const n of ast.program.body) if (n.type==='ImportDeclaration') {
    const m = n.source.value.match(/([^/]+?)\.[A-Za-z0-9_-]{8}\.js$/); const chunk = m? m[1] : n.source.value;
    for (const s of n.specifiers) if (s.type==='ImportSpecifier') { const k = chunk+'::'+(s.imported.name||s.imported.value); counts[k]=(counts[k]||0)+1; }
  }
}
fs.writeFileSync(out, JSON.stringify(counts));
console.log({files: files.length, ok, fail});
