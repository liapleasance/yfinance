// usage: node dump_exports.mjs <chunk.js> <importCounts.json> <chunkBase> <out.tsv> [maxCodeChars=160]
// Lists every export of one chunk with how many files import it (from scan_imports.mjs output) and the start of its code: a worklist for naming by hand.
import fs from 'node:fs'; import { parse } from '@babel/parser'; import _t from '@babel/traverse'; import gen from '@babel/generator';
const traverse = _t.default ?? _t; const generate = gen.default ?? gen;
const [file, countsFile, chunk, outFile, limitArg] = process.argv.slice(2);
const counts = JSON.parse(fs.readFileSync(countsFile,'utf8'));
const src = fs.readFileSync(file,'utf8'); const ast = parse(src,{sourceType:'module'});
const exp = {}; // exported -> local
for (const n of ast.program.body) if (n.type==='ExportNamedDeclaration' && n.specifiers.length) for (const s of n.specifiers) exp[s.exported.name||s.exported.value]=s.local.name;
const decl = {};
traverse(ast,{ Program(p){ for (const [name,b] of Object.entries(p.scope.bindings)) { const node=b.path.node; let code; try{ code = generate(b.path.parentPath?.isVariableDeclaration()? b.path.node : node,{minified:true,compact:true}).code; }catch{code=''}; decl[name]=code; } } });
const rows = Object.entries(exp).map(([e,l])=>({e,l,n:counts[chunk+'::'+e]||0,c:(decl[l]||'').slice(0,+limitArg||160)})).sort((a,b)=>b.n-a.n);
fs.writeFileSync(outFile, rows.map(r=>`${r.e}\t(n=${r.n})\tlocal=${r.l}\t${r.c}`).join('\n'));
console.log(rows.length,'exports');
