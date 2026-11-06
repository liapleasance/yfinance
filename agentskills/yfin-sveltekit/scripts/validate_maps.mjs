import fs from 'node:fs'; import path from 'node:path'; import { parse } from '@babel/parser';
// usage: NAMES_MAP=<map.mjs> node validate_maps.mjs <buildRoot>/chunks   - checks a names map against the build: every mapped export exists, new names are valid and unique per chunk.
import { pathToFileURL } from 'node:url';
if (!process.env.NAMES_MAP) { console.error('set NAMES_MAP=<names map .mjs>'); process.exit(2); }
const { IMPORT_MAPS, LOCAL_MAPS } = await import(pathToFileURL(path.resolve(process.env.NAMES_MAP)).href);
const chunksDir = process.argv[2]; let bad = 0;
const files = fs.readdirSync(chunksDir);
for (const [chunk, map] of Object.entries(IMPORT_MAPS)) {
  const re = new RegExp('^' + chunk.replace(/[.*+?^${}()|[\]\\]/g,'\\$&') + '\\.[A-Za-z0-9_-]{8}\\.js$');
  const f = files.filter(x => re.test(x)); if (f.length !== 1) { console.log('!! chunk file not unique/found', chunk, f); bad++; continue; }
  const ast = parse(fs.readFileSync(path.join(chunksDir, f[0]), 'utf8'), { sourceType: 'module' });
  const exps = new Set(); for (const n of ast.program.body) if (n.type === 'ExportNamedDeclaration') for (const s of n.specifiers) exps.add(s.exported.name ?? s.exported.value);
  const names = new Map();
  for (const [e, [nm, conf]] of Object.entries(map)) {
    if (!exps.has(e)) { console.log(`!! ${chunk}: export "${e}" (-> ${nm}) does not exist`); bad++; }
    if (names.has(nm)) { console.log(`!! ${chunk}: duplicate new name ${nm} for exports ${names.get(nm)} and ${e}`); bad++; }
    names.set(nm, e);
    if (!/^[A-Za-z_$][\w$]*$/.test(nm)) { console.log('!! invalid identifier', nm); bad++; }
  }
  const B = Object.values(map).filter(v => v[1] === 'B').length;
  console.log(`${chunk.padEnd(22)} ${String(Object.keys(map).length).padStart(4)} names (${B} confirmed, ${Object.keys(map).length - B} hypothesis) / ${exps.size} exports`);
}
for (const [file, map] of Object.entries(LOCAL_MAPS)) {
  const ast = parse(fs.readFileSync(path.join(chunksDir, file), 'utf8'), { sourceType: 'module' });
  const decl = new Set(); for (const n of ast.program.body) {
    if (n.type === 'FunctionDeclaration' || n.type === 'ClassDeclaration') decl.add(n.id.name);
    if (n.type === 'VariableDeclaration') for (const d of n.declarations) { const ids = []; (function g(p){ if(p.type==='Identifier') ids.push(p.name); else if(p.type==='ObjectPattern') p.properties.forEach(x=>g(x.value??x.argument)); else if(p.type==='ArrayPattern') p.elements.forEach(x=>x&&g(x)); })(d.id); ids.forEach(i=>decl.add(i)); }
    if (n.type === 'ImportDeclaration') n.specifiers.forEach(s => decl.add(s.local.name));
  }
  const seen = new Map();
  for (const [l, [nm]] of Object.entries(map)) { if (!decl.has(l)) { console.log(`!! ${file}: local "${l}" (-> ${nm}) not top-level`); bad++; } if (seen.has(nm)) { console.log('!! dup local name', nm, seen.get(nm), l); bad++; } seen.set(nm, l); }
  console.log(`${file}: ${Object.keys(map).length} local names`);
}
console.log(bad ? `${bad} PROBLEMS` : 'maps OK');
