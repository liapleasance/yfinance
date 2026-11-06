// usage: node ast_equiv.mjs <rootA> <rootB> <shardIdx> <shardCount> <out.json>
// Compares ASTs ignoring: positions, comments, quote style, shorthand flag and the NAMES of bound identifiers
// (bindings are canonicalized by order of first appearance). Free (global) identifiers and property names must match.
import fs from 'node:fs'; import path from 'node:path';
import * as T from '@babel/types'; import { parse } from '@babel/parser'; import _t from '@babel/traverse';
const traverse = _t.default ?? _t;
const [rootA, rootB, si = '0', sc = '1', outFile] = process.argv.slice(2);
if (!rootA || !rootB || !outFile) { console.error('usage: node ast_equiv.mjs <baseRoot> <finalRoot> <shardIdx> <shardCount> <out.json>'); process.exit(2); }
const files = []; (function walk(d){ for (const e of fs.readdirSync(d,{withFileTypes:true})) { const p=path.join(d,e.name); if(e.isDirectory()) walk(p); else if(/\.m?js$/.test(e.name)) files.push(path.relative(rootA,p).split(path.sep).join('/')); } })(rootA);   // '/' always: rels go into the error report
files.sort();
const SKIP = new Set(['start','end','loc','range','extra','comments','leadingComments','trailingComments','innerComments','tokens','errors','shorthand']);
function canon(code) {
  const ast = parse(code, { sourceType:'module', plugins:['jsx'], errorRecovery:false });
  const ids = new Map(); // Binding -> index
  const idOf = (b) => { let i = ids.get(b); if (i === undefined) { i = ids.size; ids.set(b, i); } return i; };
  // map Identifier node -> canonical token
  const tok = new Map();
  traverse(ast, {
    Identifier(p) {
      const n = p.node;
      if (p.parentPath.isExportSpecifier({exported:n}) || p.parentPath.isImportSpecifier({imported:n})) { if (!(p.parentPath.isExportSpecifier() && p.parentPath.node.local === n)) return; }
      if (p.isReferencedIdentifier() || p.isBindingIdentifier() || p.parentPath.isAssignmentExpression({left:n}) || p.parentPath.isUpdateExpression() || p.parentPath.isForXStatement({left:n}) || p.parentPath.isExportSpecifier({local:n}) || (p.parentPath.isAssignmentPattern({left:n})) || p.parentPath.isArrayPattern() || p.parentPath.isRestElement() ) {
        const par = p.parentPath;
        const sc = ((par.isFunctionDeclaration() || par.isClassDeclaration()) && par.node.id === n) ? par.scope.parent : p.scope;
        const b = sc.getBinding(n.name);
        if (b) tok.set(n, '#'+idOf(b));
        else if (p.parentPath.isExportSpecifier({exported:n}) || p.parentPath.isImportSpecifier({imported:n})) {}
        else tok.set(n, '@'+n.name);
      }
    },
    JSXIdentifier(p) { const b = p.scope.getBinding(p.node.name); if (b && p.isReferencedIdentifier()) tok.set(p.node, '#'+idOf(b)); },
  });
  // Normalise export forms: `export <decl>` vs `<decl>; export {local as name}` -> compare exports as a sorted set (exportedName:bindingToken)
  const exportsList = []; const newBody = [];
  for (const st of ast.program.body) {
    if (st.type === 'ExportNamedDeclaration' && !st.source) {
      if (st.declaration) { newBody.push(st.declaration); for (const [name, node] of Object.entries(T.getBindingIdentifiers(st.declaration, false, true))) exportsList.push(name + ':' + tok.get(Array.isArray(node) ? node[0] : node)); }
      for (const sp of st.specifiers) exportsList.push((sp.exported.name ?? sp.exported.value) + ':' + tok.get(sp.local));
    } else newBody.push(st);
  }
  ast.program.body = newBody; exportsList.sort();
  const ser = (n) => {
    if (typeof n === 'bigint') return '"bigint:' + n.toString() + '"';   // BigIntLiteral.extra.rawValue is a native bigint: JSON.stringify throws on it
    if (n === null || typeof n !== 'object') return JSON.stringify(n);
    if (Array.isArray(n)) return '['+n.filter(x=>!(x && (x.type==='EmptyStatement' || (x.type==='JSXText' && x.value.trim()==='' && /\n/.test(x.value))))).map(ser).join(',')+']';
    if (tok.has(n)) return '"'+tok.get(n)+'"';
    if ((n.type === 'JSXElement' || n.type === 'JSXFragment') && Array.isArray(n.children)) {
      const kids = []; let buf = null;
      const flush = () => { if (buf !== null) { const v = buf.replace(/\s+/g, ' ').trim(); if (v) kids.push('"JSXT:' + v + '"'); buf = null; } };
      for (const c of n.children) {
        if (c.type === 'JSXText') buf = (buf ?? '') + c.value;
        else if (c.type === 'JSXExpressionContainer' && c.expression.type === 'StringLiteral' && /^\s*$/.test(c.expression.value)) buf = (buf ?? '') + c.expression.value;
        else { flush(); kids.push(ser(c)); }
      }
      flush();
      const rest = Object.keys(n).filter(k=>!SKIP.has(k) && k!=='children').sort();
      return '{children:['+kids.join(',')+'],'+rest.map(k=>k+':'+ser(n[k])).join(',')+'}';
    }
    if (n.type === 'JSXText') return '"JSXT:' + n.value.replace(/\s+/g, ' ').trim() + '"';
    if (n.type === 'LogicalExpression') { const ops = []; const flat = (x) => { if (x.type === 'LogicalExpression' && x.operator === n.operator && !x.extra?.parenthesized) { flat(x.left); flat(x.right); } else ops.push(x); }; const flat2 = (x) => { if (x.type === 'LogicalExpression' && x.operator === n.operator) { flat2(x.left); flat2(x.right); } else ops.push(x); }; flat2(n); return '{logical:' + JSON.stringify(n.operator) + ',ops:[' + ops.map(ser).join(',') + ']}'; }
    if ((n.type === 'ObjectProperty' || n.type === 'ObjectMethod' || n.type === 'ClassMethod' || n.type === 'ClassProperty') && !n.computed && (n.key.type === 'StringLiteral' || n.key.type === 'Identifier' || n.key.type === 'NumericLiteral') && !tok.has(n.key)) { const kn = n.key.type === 'StringLiteral' ? n.key.value : n.key.type === 'NumericLiteral' ? String(n.key.value) : n.key.name; const keys0 = Object.keys(n).filter(k => !SKIP.has(k) && k !== 'key').sort(); return '{key:' + JSON.stringify(kn) + ',' + keys0.map(k => k + ':' + ser(n[k])).join(',') + '}'; }
    if (n.type === 'RegExpLiteral') return '/' + n.pattern + '/' + n.flags.split('').sort().join('');
    const WRAP = new Set(['consequent','alternate','body']);
    const keys = Object.keys(n).filter(k=>!SKIP.has(k)).sort();
    if (['IfStatement','ForStatement','ForInStatement','ForOfStatement','WhileStatement','DoWhileStatement','LabeledStatement'].includes(n.type)) {
      return '{'+keys.map(k=>k+':'+((WRAP.has(k) && n[k] && n[k].type && /Statement$|Declaration$/.test(n[k].type) && n[k].type!=='BlockStatement' && n.type!=='LabeledStatement') ? ser({type:'BlockStatement',body:[n[k]],directives:[]}) : ser(n[k]))).join(',')+'}';
    }
    return '{'+keys.map(k=>k+':'+ser(n[k])).join(',')+'}';
  };
  return ser(ast.program) + '\nEXPORTS:' + exportsList.join(',');
}
const res = { total:0, equal:0, differ:[], error:[] };
for (let i=0;i<files.length;i++) {
  if (i % +sc !== +si) continue;
  const rel = files[i]; res.total++;
  try {
    const a = canon(fs.readFileSync(path.join(rootA,rel),'utf8'));
    const b = canon(fs.readFileSync(path.join(rootB,rel),'utf8'));
    if (a === b) res.equal++; else {
      let k=0; while (k<a.length && a[k]===b[k]) k++;
      res.differ.push({ file: rel, at:k, a:a.slice(Math.max(0,k-80),k+80), b:b.slice(Math.max(0,k-80),k+80) });
    }
  } catch (e) { res.error.push({ file: rel, err: String(e.message).slice(0,200) }); }
}
fs.writeFileSync(outFile, JSON.stringify(res));
console.log(JSON.stringify({total:res.total,equal:res.equal,differ:res.differ.length,error:res.error.length}));
process.exit(res.differ.length || res.error.length ? 1 : 0);
