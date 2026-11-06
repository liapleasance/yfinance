// Structural fingerprint of exported functions/classes: AST node types, operators, literals and property names; bound identifiers by first-occurrence index
// (so renaming/minifying does not matter), free identifiers as G, let/const/var treated alike. Used to match build exports against the official Svelte source.
import { parse } from '@babel/parser';
// structural hash of a function/class: node types + operators + literals + property names; bound identifiers by first-occurrence index, free identifiers as G
function shape(node, code) {
  const ids = new Map(); const out = [];
  const walk = (n, bound) => {
    if (!n || typeof n !== 'object') return;
    if (Array.isArray(n)) { n.forEach(x => walk(x, bound)); return; }
    if (!n.type) return;
    switch (n.type) {
      case 'Identifier': out.push(ids.has(n.name) ? 'v' + ids.get(n.name) : 'G'); return;
      case 'StringLiteral': out.push('s:' + n.value); return;
      case 'NumericLiteral': out.push('n:' + n.value); return;
      case 'BooleanLiteral': out.push('b:' + n.value); return;
    }
    out.push(n.type + (n.operator ? n.operator : '') + '' + (n.computed ? 'C' : ''));
    // register declared names (params, var declarators, function ids) in order
    if (n.type === 'FunctionDeclaration' || n.type === 'FunctionExpression' || n.type === 'ArrowFunctionExpression') for (const p of n.params) reg(p);
    if (n.type === 'VariableDeclarator') reg(n.id);
    if (n.type === 'CatchClause' && n.param) reg(n.param);
    for (const k of Object.keys(n)) {
      if (['type','start','end','loc','extra','leadingComments','trailingComments','innerComments','range'].includes(k)) continue;
      if (k === 'key' && !n.computed && n.key.type === 'Identifier') { out.push('k:' + n.key.name); continue; }
      if (k === 'property' && !n.computed && n.property.type === 'Identifier') { out.push('p:' + n.property.name); continue; }
      walk(n[k], bound);
    }
  };
  const reg = p => { if (!p) return; if (p.type === 'Identifier') { if (!ids.has(p.name)) ids.set(p.name, ids.size); } else if (p.type === 'AssignmentPattern') reg(p.left); else if (p.type === 'RestElement') reg(p.argument); else if (p.type === 'ObjectPattern') p.properties.forEach(q => reg(q.value ?? q.argument)); else if (p.type === 'ArrayPattern') p.elements.forEach(reg); };
  // pre-register all declarations inside so references before declaration (hoisting) are consistent
  const pre = n => { if (!n || typeof n !== 'object') return; if (Array.isArray(n)) return n.forEach(pre); if (!n.type) return;
    if (/^Function|^Arrow/.test(n.type)) { if (n.id) reg(n.id); n.params.forEach(reg); } if (n.type === 'VariableDeclarator') reg(n.id); if (n.type === 'ClassDeclaration' && n.id) reg(n.id);
    for (const k of Object.keys(n)) if (!['type','start','end','loc','extra'].includes(k)) pre(n[k]); };
  pre(node); walk(node, null); return out.join('|');
}
export function exportShapes(code) {
  const ast = parse(code, { sourceType: 'module' }); const top = new Map(); const exps = [];
  for (const n of ast.program.body) {
    if (n.type === 'FunctionDeclaration') top.set(n.id.name, n);
    else if (n.type === 'ClassDeclaration') top.set(n.id.name, n);
    else if (n.type === 'VariableDeclaration') { for (const d of n.declarations) if (d.id.type === 'Identifier' && d.init) top.set(d.id.name, d.init); }
    else if (n.type === 'ExportNamedDeclaration') { for (const s of n.specifiers) exps.push([s.exported.name ?? s.exported.value, s.local.name]); if (n.declaration?.id) { top.set(n.declaration.id.name, n.declaration); exps.push([n.declaration.id.name, n.declaration.id.name]); } }
    if (n.type === 'VariableDeclaration') {}
  }
  const res = {}; for (const [e, l] of exps) { const f = top.get(l); if (f) res[e] = shape(f, code); } return res;
}

// Shapes of ALL top-level functions/classes of a module (not only exported ones): { localName: shape }. Used to name non-exported helpers of a chunk.
export function topShapes(code) {
  const ast = parse(code, { sourceType: 'module' }); const res = {};
  for (const n of ast.program.body) {
    const d = n.type === 'ExportNamedDeclaration' && n.declaration ? n.declaration : n;
    if (d.type === 'FunctionDeclaration' || d.type === 'ClassDeclaration') { if (d.id) res[d.id.name] = shape(d, code); }
    else if (d.type === 'VariableDeclaration') for (const x of d.declarations) if (x.id.type === 'Identifier' && x.init && /^(FunctionExpression|ArrowFunctionExpression|ClassExpression)$/.test(x.init.type)) res[x.id.name] = shape(x.init, code);
  }
  return res;
}
