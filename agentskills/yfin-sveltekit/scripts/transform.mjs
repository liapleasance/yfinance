// Stage 2: scope-safe renaming + Svelte structure annotations, applied on top of Wakaru output.
// usage: node transform.mjs <srcRoot> <outRoot> <componentExports.json> <shardIdx> <shardCount> <statsOut> [buildRoot]
//   buildRoot (default: srcRoot) is a tree that contains entry/start.*.js and entry/app.*.js of the ORIGINAL build; it is used to refuse
//   a names map that belongs to another build (BUILD_ID guard). env: NAMES_MAP=<file> (required),
//   YFIN_RESUME=1 (skip outputs that already exist; default is to overwrite), YFIN_VENDOR_DIRS=<regex alternation> (default: every top-level directory of the build except SvelteKit's own: entry, nodes, chunks, pages, assets, _app, immutable = third-party code).
// Renames only *local bindings* (Babel scope.rename). Exported/imported names are never changed,
// so every module interface stays identical to the original build.
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { parse } from '@babel/parser';
import _traverse from '@babel/traverse';
import _generate from '@babel/generator';
import * as t from '@babel/types';
import * as prettier from 'prettier';
if (!process.env.NAMES_MAP) { console.error('REFUSING: set NAMES_MAP=<names map .mjs> (make_map.mjs generates one for THIS build; run_auto_pipeline.sh does it for you).'); process.exit(2); }
const mapFile = path.resolve(process.env.NAMES_MAP);
const { IMPORT_MAPS, LOCAL_MAPS, BUILD_ID, ROLES = {} } = await import(pathToFileURL(mapFile).href);
// ROLES (optional, build-specific; see detect_roles.mjs / make_map.mjs): { init:{chunk,export}, component_subscribe:{chunk,export}, app_lib:{chunk,getStore,isFeatureEnabled,getSession,loadSession,loadStores} }.
// A role that is absent simply disables the annotations that depend on it.
const roleCall = (scope, node, role) => !!ROLES[role] && isCall(scope, node, ROLES[role].chunk, ROLES[role].export);

const traverse = _traverse.default ?? _traverse;
const generate = _generate.default ?? _generate;
const [srcRoot, outRoot, compFile, shardIdxArg, shardCountArg, statsOut, buildRootArg] = process.argv.slice(2);
if (!srcRoot || !outRoot || !compFile || !statsOut) { console.error('usage: node transform.mjs <srcRoot> <outRoot> <componentExports.json> <shardIdx> <shardCount> <statsOut> [buildRoot]'); process.exit(2); }
// ---- BUILD_ID guard: a names map is only valid for the build it was derived from --------------------------------------
{
  const buildRoot = buildRootArg || srcRoot; const entryDir = path.join(buildRoot, 'entry');
  const find = k => fs.existsSync(entryDir) ? fs.readdirSync(entryDir).map(f => f.match(new RegExp('^' + k + '\\.([A-Za-z0-9_-]{8})\\.js$'))?.[1]).filter(Boolean) : [];
  const got = { start: find('start'), app: find('app') };
  if (!BUILD_ID || !BUILD_ID.start || !BUILD_ID.app) { console.error('REFUSING: names map ' + mapFile + ' does not export BUILD_ID = { start, app }.'); process.exit(2); }
  if (got.start.length !== 1 || got.app.length !== 1) { console.error('REFUSING: cannot identify the build: expected exactly one entry/start.<hash>.js and entry/app.<hash>.js under ' + entryDir + ' (pass the ORIGINAL build root as 7th argument).'); process.exit(2); }
  if (got.start[0] !== BUILD_ID.start || got.app[0] !== BUILD_ID.app) { console.error(`REFUSING: names map is for build start.${BUILD_ID.start}/app.${BUILD_ID.app} but this tree is start.${got.start[0]}/app.${got.app[0]}. Derive a new map (references/naming-method.md); applying a foreign map would mislabel code silently.`); process.exit(2); }
}
const RESUME = process.env.YFIN_RESUME === '1';
const KIT_DIRS = new Set(['entry', 'nodes', 'chunks', 'pages', 'assets', '_app', 'immutable']);
const vendorDirs = process.env.YFIN_VENDOR_DIRS || fs.readdirSync(buildRootArg || srcRoot, { withFileTypes: true }).filter(e => e.isDirectory() && !KIT_DIRS.has(e.name)).map(e => e.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
const VENDOR_RE = vendorDirs ? new RegExp('^(' + vendorDirs + ')/') : /^$never/;
const shardIdx = +shardIdxArg || 0, shardCount = +shardCountArg || 1;
const COMP_EXPORTS = fs.existsSync(compFile) ? JSON.parse(fs.readFileSync(compFile, 'utf8')) : {};

const CHUNK_RE = /([^/]+?)\.[A-Za-z0-9_-]{8}\.js$/;
const RESERVED = new Set(('break case catch class const continue debugger default delete do else enum export extends false finally for function if import in instanceof new null return super switch this throw true try typeof var void while with yield let static implements interface package private protected public await async of arguments eval undefined NaN Infinity').split(' '));
const sanitize = s => s.replace(/[^A-Za-z0-9_$]/g, '_').replace(/^(\d)/, '_$1');
const readable = n => typeof n === 'string' && n.length > 2 && !/^[a-z]{1,2}\d?$/.test(n) && !/_\d+$/.test(n);

const stats = { files: 0, importRenames: 0, exportRenames: 0, localRenames: 0, semanticRenames: 0, moduleKeyRenames: 0,
  components: 0, blocks: 0, methodParams: 0, ctxComments: 0, dirtyComments: 0, unmappedLocalKeys: [], failed: [], unmappedImports: {} };

function conflicts(b, cand) {
  const prog = b.scope.getProgramParent();
  if (prog.hasGlobal(cand)) return true;
  if (b.scope.hasOwnBinding(cand)) return true;
  for (const p of [...b.referencePaths, ...b.constantViolations]) for (let s = p.scope; s; s = s.parent) if (s.hasOwnBinding(cand)) return true;
  return false;
}
function renameBinding(b, desired, cat) {
  if (!b || !desired) return null;
  const old = b.identifier.name;
  if (old === desired) return old;
  if (!/^[A-Za-z_$][\w$]*$/.test(desired) || RESERVED.has(desired)) return null;
  let cand = desired, i = 0;
  while (conflicts(b, cand)) { if (++i > 60) return null; cand = `${desired}_${i}`; }
  b.scope.rename(old, cand);
  if (cat) stats[cat]++;
  return cand;
}
const chunkIdOf = src => (src.includes('/nodes/') || src.includes('/entry/') || src.includes('/pages/')) ? null : (src.match(CHUNK_RE)?.[1] ?? null);
const importInfo = b => b && b.path.isImportSpecifier() ? { src: b.path.parent.source.value, chunk: chunkIdOf(b.path.parent.source.value), imported: b.path.node.imported.name ?? b.path.node.imported.value } : null;
const calleeInfo = (scope, node) => node && node.type === 'Identifier' ? importInfo(scope.getBinding(node.name)) : null;
const isCall = (scope, node, chunk, imp) => { if (!node || node.type !== 'CallExpression') return false; const i = calleeInfo(scope, node.callee); return !!i && i.chunk === chunk && i.imported === imp; };

function declaredNames(decl) {
  if (decl.id) return [decl.id.name];
  if (decl.declarations) return decl.declarations.flatMap(d => d.id.type === 'Identifier' ? [d.id.name] : []);
  return [];
}
// `export function i(){}` -> `function i(){}; export { i }`  so that the local alias can be renamed freely
function splitExportDeclarations(prog, wanted) {
  let changed = false;
  const body = prog.node.body, out = [];
  for (const n of body) {
    if (t.isExportNamedDeclaration(n) && n.declaration) {
      const names = declaredNames(n.declaration);
      if (names.length && names.some(x => wanted.has(x))) {
        out.push(n.declaration);
        out.push(t.exportNamedDeclaration(null, names.map(x => t.exportSpecifier(t.identifier(x), t.identifier(x)))));
        changed = true; continue;
      }
    }
    out.push(n);
  }
  if (changed) { prog.node.body = out; prog.scope.crawl(); }
}
function exportsOfLocal(prog, local) {
  const r = [];
  for (const n of prog.node.body) if (t.isExportNamedDeclaration(n)) {
    for (const s of n.specifiers) if (s.local.name === local) r.push(s.exported.name ?? s.exported.value);
    if (n.declaration && declaredNames(n.declaration).includes(local)) r.push(local);
  }
  return r;
}
const isDeclExported = (prog, local) => prog.node.body.some(n => t.isExportNamedDeclaration(n) && n.declaration && declaredNames(n.declaration).includes(local));

function transformCode(code, relPath) {
  const ast = parse(code, { sourceType: 'module', plugins: ['jsx'] });
  let prog; traverse(ast, { Program(p) { prog = p; p.stop(); } });
  const dir = relPath.split('/')[0], base = path.basename(relPath);
  const chunkId = dir === 'chunks' ? (base.match(CHUNK_RE)?.[1] ?? null) : null;
  const defMap = chunkId ? IMPORT_MAPS[chunkId] : null;
  const compMap = dir === 'chunks' ? COMP_EXPORTS[base] : null;
  const fileBase = dir === 'nodes' ? 'Node' + base.split('.')[0] : (chunkId ? sanitize(chunkId) : sanitize(base.split('.')[0]));

  // ---- A. defining chunk: give local aliases of mapped exports a readable name -------------
  const wantedExports = new Set([...(defMap ? Object.keys(defMap) : []), ...(compMap ? Object.keys(compMap) : [])]);
  if (wantedExports.size) {
    splitExportDeclarations(prog, wantedExports);
    for (const n of prog.node.body) if (t.isExportNamedDeclaration(n)) for (const s of n.specifiers) {
      const e = s.exported.name ?? s.exported.value;
      const nm = defMap?.[e]?.[0] ?? compMap?.[e];
      if (nm) { const r = renameBinding(prog.scope.getBinding(s.local.name), nm, 'exportRenames'); if (r) s.local.name = r; }
    }
  }
  // ---- B. importing files: rename aliases of imports by imported name ----------------------
  for (const n of [...prog.node.body]) if (t.isImportDeclaration(n)) {
    const src = n.source.value, cid = chunkIdOf(src), map = cid ? IMPORT_MAPS[cid] : null, comp = COMP_EXPORTS[path.basename(src)];
    for (const s of n.specifiers) if (t.isImportSpecifier(s)) {
      const imp = s.imported.name ?? s.imported.value;
      const nm = map?.[imp]?.[0] ?? comp?.[imp];
      if (nm) renameBinding(prog.scope.getBinding(s.local.name), nm, 'importRenames');
      else if (map) { const k = cid + '::' + imp; stats.unmappedImports[k] = (stats.unmappedImports[k] || 0) + 1; }
    }
  }
  // ---- C. module-local names (hash specific) -------------------------------------------------
  if (dir === 'chunks' && LOCAL_MAPS[base]) for (const [old, [nm]] of Object.entries(LOCAL_MAPS[base])) {
    const b = prog.scope.getBinding(old);
    if (!b) { stats.unmappedLocalKeys.push(base + ':' + old); continue; }
    if (isDeclExported(prog, old)) continue;
    renameBinding(b, nm, 'localRenames');
  }
  // ---- D. semantic renames from well known calls ----------------------------------------------
  const AL = ROLES.app_lib; const sa = AL?.chunk ?? null;
  const alCall = (scope, call, k) => !!AL && isCall(scope, call, AL.chunk, AL[k]);
  const nameFromCall = (scope, call) => {
    if (alCall(scope, call, 'getStore') && call.arguments[0]?.type === 'StringLiteral') return call.arguments[0].value + 'Store';
    if (alCall(scope, call, 'isFeatureEnabled') && call.arguments[1]?.type === 'StringLiteral') return call.arguments[1].value;
    if (alCall(scope, call, 'getSession')) return 'session';
    if (alCall(scope, call, 'loadSession')) return 'session';
    return null;
  };
  traverse(ast, { VariableDeclarator(p) {
    const { id, init } = p.node; if (!init) return;
    const unwrap = init.type === 'AwaitExpression' ? init.argument : init;
    if (id.type === 'Identifier') {
      const nm = nameFromCall(p.scope, unwrap); if (nm) renameBinding(p.scope.getBinding(id.name), nm, 'semanticRenames');
    } else if (id.type === 'ArrayPattern') {
      if (alCall(p.scope, unwrap, 'loadStores') && unwrap.arguments[0]?.type === 'ArrayExpression') {
        id.elements.forEach((el, i) => { const lit = unwrap.arguments[0].elements[i]; if (el?.type === 'Identifier' && lit?.type === 'StringLiteral') renameBinding(p.scope.getBinding(el.name), lit.value + 'Store', 'semanticRenames'); });
      } else if (unwrap.type === 'CallExpression' && unwrap.callee.type === 'MemberExpression' && unwrap.callee.object.name === 'Promise' && unwrap.callee.property.name === 'all' && unwrap.arguments[0]?.type === 'ArrayExpression') {
        id.elements.forEach((el, i) => {
          const c = unwrap.arguments[0].elements[i]; if (!el || !c) return;
          if (el.type === 'Identifier') { const nm = nameFromCall(p.scope, c); if (nm) renameBinding(p.scope.getBinding(el.name), nm, 'semanticRenames'); }
          else if (el.type === 'ArrayPattern' && alCall(p.scope, c, 'loadStores') && c.arguments[0]?.type === 'ArrayExpression')
            el.elements.forEach((e2, j) => { const lit = c.arguments[0].elements[j]; if (e2?.type === 'Identifier' && lit?.type === 'StringLiteral') renameBinding(p.scope.getBinding(e2.name), lit.value + 'Store', 'semanticRenames'); });
        });
      }
    }
  } });
  // ---- E. SvelteKit module objects: { __proto__:null, load: x, _config: y } -> name x/y ------
  traverse(ast, { ObjectExpression(p) {
    const props = p.node.properties;
    if (!props.some(q => t.isObjectProperty(q) && !q.computed && q.key.name === '__proto__' && t.isNullLiteral(q.value))) return;
    if (!(p.parentPath.isCallExpression() && p.parent.callee.type === 'MemberExpression' && p.parent.callee.property.name === 'defineProperty')) return;
    for (const q of props) if (t.isObjectProperty(q) && !q.computed && t.isIdentifier(q.key) && q.key.name !== '__proto__' && t.isIdentifier(q.value)) {
      const key = q.key.name === 'default' ? null : q.key.name; if (!key) continue;
      const b = p.scope.getBinding(q.value.name); if (!b || b.path.isImportSpecifier() || isDeclExported(prog, q.value.name)) continue;
      renameBinding(b, key, 'moduleKeyRenames');
    }
  } });
  // module object bound to exported alias: `const X = Object.freeze(...)` exported as `universal` -> universal
  for (const n of prog.node.body) if (t.isExportNamedDeclaration(n)) for (const s of n.specifiers) {
    const e = s.exported.name ?? s.exported.value, l = s.local.name;
    if (e.length >= 5 && /^[a-z]/.test(e) && !readable(l)) { const b = prog.scope.getBinding(l); if (b && !b.path.isImportSpecifier()) { const r = renameBinding(b, e, 'semanticRenames'); if (r) s.local.name = r; } }
  }

  // ---- F. Svelte components -------------------------------------------------------------------
  const topFns = new Map(); // name -> FunctionDeclaration path
  for (const p of prog.get('body')) { if (p.isFunctionDeclaration()) topFns.set(p.node.id.name, p); else if (p.isExportNamedDeclaration() && p.get('declaration').isFunctionDeclaration()) topFns.set(p.node.declaration.id.name, p.get('declaration')); }
  const comps = []; // { classBinding, instanceName, fragName, props, exportedAs, name }
  traverse(ast, { CallExpression(p) {
    if (!roleCall(p.scope, p.node, 'init')) return;
    const cls = p.findParent(q => q.isClassDeclaration() || q.isClassExpression()); if (!cls) return;
    let cname = cls.node.id?.name ?? (cls.parentPath.isVariableDeclarator() && cls.parent.id.type === 'Identifier' ? cls.parent.id.name : null);
    if (!cname) return;
    const a = p.node.arguments;
    comps.push({ cname, cls, instance: a[2]?.type === 'Identifier' ? a[2].name : null, frag: a[3]?.type === 'Identifier' ? a[3].name : null,
      props: a[5]?.type === 'ObjectExpression' ? a[5].properties.filter(q => t.isObjectProperty(q) && t.isNumericLiteral(q.value)).map(q => [q.key.name ?? q.key.value, q.value.value]) : [] });
  } });
  const compNames = new Set();
  comps.forEach((c, k) => {
    stats.components++;
    const exp = exportsOfLocal(prog, c.cname);
    let cn;
    if (dir === 'nodes') cn = exp.includes('component') ? fileBase : `${fileBase}_Component${k + 1}`;
    else cn = (compMap && exp.map(e => compMap[e]).find(Boolean)) || `${fileBase}_Component${k + 1}`;
    if (!isDeclExported(prog, c.cname)) { const r = renameBinding(prog.scope.getBinding(c.cname), cn, null); if (r) { c.cname = r; cn = r; } }
    c.base = cn; compNames.add(cn);
    if (c.instance && topFns.has(c.instance)) { const r = renameBinding(prog.scope.getBinding(c.instance), 'instance_' + cn, null); if (r) c.instance = r; }
    if (c.frag && topFns.has(c.frag)) { const r = renameBinding(prog.scope.getBinding(c.frag), 'create_fragment_' + cn, null); if (r) c.frag = r; }
  });
  topFns.clear();
  for (const p of prog.get('body')) { if (p.isFunctionDeclaration()) topFns.set(p.node.id.name, p); else if (p.isExportNamedDeclaration() && p.get('declaration').isFunctionDeclaration()) topFns.set(p.node.declaration.id.name, p.get('declaration')); }

  // blocks = top level functions returning { c, m, d, ... } lifecycle objects
  const isBlockFn = fp => {
    const body = fp.node.body.body; const ret = body[body.length - 1];
    if (!ret || !t.isReturnStatement(ret) || !t.isObjectExpression(ret.argument)) return false;
    const keys = new Set(ret.argument.properties.filter(q => t.isObjectMethod(q) && t.isIdentifier(q.key)).map(q => q.key.name));
    return keys.has('c') && keys.has('d') && (keys.has('m') || keys.has('l'));
  };
  const isEachCtxFn = fp => { const b = fp.node.body.body; return b.length >= 2 && t.isVariableDeclaration(b[0]) && b[0].declarations[0]?.init?.type === 'CallExpression' && b[0].declarations[0].init.callee?.property?.name === 'slice' && t.isReturnStatement(b[b.length - 1]); };
  const blocks = [...topFns.entries()].filter(([, fp]) => isBlockFn(fp));
  const eachCtx = new Set([...topFns.entries()].filter(([, fp]) => isEachCtxFn(fp)).map(([n]) => n));
  const used = new Map(); const uniq = (k) => { const n = used.get(k) || 0; used.set(k, n + 1); return n ? `${k}_${n}` : k; };
  let ecN = 0;
  for (const n of [...eachCtx]) { const r = renameBinding(prog.scope.getBinding(n), uniq('get_each_context'), null); if (r) { eachCtx.delete(n); eachCtx.add(r); } }
  const fragNames = new Set(comps.map(c => c.frag));
  for (const [name, fp] of blocks) {
    if (fragNames.has(name)) continue;
    const b = prog.scope.getBinding(name); if (!b) continue;
    let kind = 'block';
    for (const ref of b.referencePaths) {
      const par = ref.parentPath;
      if (par.isCallExpression() && par.node.callee === ref.node) {
        const arg0 = par.node.arguments[0];
        if (arg0?.type === 'CallExpression' && arg0.callee.type === 'Identifier' && eachCtx.has(arg0.callee.name)) { kind = 'each_block'; break; }
        if (par.parentPath.isLogicalExpression({ operator: '&&' }) || par.parentPath.isConditionalExpression()) { kind = 'if_block'; break; }
      } else if (par.isArrayExpression()) {
        const gp = par.parentPath;
        if (gp.isObjectProperty() && !gp.node.computed) { kind = `${gp.node.key.name ?? gp.node.key.value}_slot`; break; }
        kind = 'if_block'; break;
      }
    }
    const r = renameBinding(b, uniq('create_' + sanitize(kind)), null); if (r) stats.blocks++;
  }
  topFns.clear();
  for (const p of prog.get('body')) { if (p.isFunctionDeclaration()) topFns.set(p.node.id.name, p); else if (p.isExportNamedDeclaration() && p.get('declaration').isFunctionDeclaration()) topFns.set(p.node.declaration.id.name, p.get('declaration')); }

  // ---- G. lifecycle method params + comments, ctx / dirty annotations -----------------------------
  const METHOD = { c: ['create', []], l: ['claim', ['nodes']], h: ['hydrate', []], m: ['mount', ['target', 'anchor']], p: ['update', ['new_ctx', 'dirty']], i: ['intro', ['local']], o: ['outro', ['local']], d: ['destroy', ['detaching']] };
  const blockFns = [...topFns.entries()].filter(([, fp]) => isBlockFn(fp));
  const blockInfo = new Map(); // name -> { ctxB, newCtxB, dirtyB }
  for (const [name, fp] of blockFns) {
    const info = {}; const p0 = fp.get('params.0');
    if (p0 && p0.isIdentifier()) { const r = renameBinding(fp.scope.getBinding(p0.node.name), 'ctx', null); if (r) info.ctxB = fp.scope.getBinding(r); }
    const ret = fp.get('body.body').slice(-1)[0];
    for (const mp of ret.get('argument.properties')) {
      if (!mp.isObjectMethod() || !t.isIdentifier(mp.node.key) || !METHOD[mp.node.key.name]) continue;
      const [label, names] = METHOD[mp.node.key.name];
      t.addComment(mp.node, 'leading', ` ${label} `, false);
      names.forEach((nm, i) => {
        const prm = mp.get(`params.${i}`); if (!prm || !prm.node) return;
        let idp = prm; if (prm.isArrayPattern()) idp = prm.get('elements.0'); if (!idp?.node || !idp.isIdentifier()) return;
        const r = renameBinding(mp.scope.getBinding(idp.node.name), nm, 'methodParams');
        if (r && mp.node.key.name === 'p') { if (i === 0) info.newCtxB = mp.scope.getBinding(r); else info.dirtyB = mp.scope.getBinding(r); }
      });
    }
    blockInfo.set(name, info);
  }
  // ownership graph: component fragment -> blocks it references (transitively)
  const owners = new Map();
  for (const c of comps) {
    if (!c.frag || !blockInfo.has(c.frag)) continue;
    const seen = new Set(), stack = [c.frag];
    while (stack.length) { const n = stack.pop(); if (seen.has(n)) continue; seen.add(n); const fp = topFns.get(n); if (!fp) continue;
      fp.traverse({ Identifier(q) { const nn = q.node.name; if ((blockInfo.has(nn) || eachCtx.has(nn)) && !seen.has(nn) && q.isReferencedIdentifier()) stack.push(nn); } }); }
    for (const n of seen) { if (!owners.has(n)) owners.set(n, new Set()); owners.get(n).add(c); }
  }
  const nameMask = (names, mask) => { const r = []; for (let i = 0; i < 31; i++) if (mask & (1 << i) && names[i]) r.push(names[i]); return r; };
  const addDirty = (np, names) => {
    const mask = np.node.value; const r = nameMask(names, mask); if (!r.length) return;
    t.addComment(np.node, 'leading', ' ' + (r.length > 4 ? r.slice(0, 4).join(', ') + ', …' : r.join(', ')) + ' ', false); stats.dirtyComments++;
  };
  for (const c of comps) {
    const inst = c.instance && topFns.get(c.instance); if (!inst) continue;
    const names = [];
    for (const [k, i] of c.props) names[i] = k;
    const ps = ['$$self', '$$props', '$$invalidate'];
    const prm = [0, 1, 2].map(i => inst.get(`params.${i}`));
    const bind = [];
    prm.forEach((pp, i) => { if (pp && pp.node && pp.isIdentifier()) { const r = renameBinding(inst.scope.getBinding(pp.node.name), ps[i], null); bind[i] = inst.scope.getBinding(r ?? pp.node.name); } });
    const ret = inst.get('body.body').slice(-1)[0];
    if (ret.isReturnStatement() && t.isArrayExpression(ret.node.argument))
      ret.node.argument.elements.forEach((el, i) => { if (el && el.type === 'Identifier' && !names[i] && readable(el.name)) names[i] = el.name; });
    inst.traverse({ CallExpression(q) {  // component_subscribe($$self, store, v => $$invalidate(idx, x = v))
      if (!roleCall(q.scope, q.node, 'component_subscribe')) return;
      const [, store, cb] = q.node.arguments; if (store?.type !== 'Identifier' || !cb || !t.isArrowFunctionExpression(cb)) return;
      const bd = t.isBlockStatement(cb.body) ? null : cb.body;
      if (bd && bd.type === 'CallExpression' && bd.arguments[0]?.type === 'NumericLiteral' && !names[bd.arguments[0].value]) names[bd.arguments[0].value] = '$' + store.name;
    } });
    c.names = names;
    inst.traverse({ BinaryExpression(q) {   // $$self.$$.dirty & MASK
      if (q.node.operator !== '&' || !t.isNumericLiteral(q.node.right)) return;
      const l = q.node.left; if (l.type === 'MemberExpression' && l.property.name === 'dirty' && l.object.type === 'MemberExpression' && l.object.property.name === '$$') addDirty(q.get('right'), names);
    } });
  }
  for (const [name, fp] of blockFns) {
    const own = owners.get(name); if (!own || own.size !== 1) continue; const comp = [...own][0]; const names = comp.names; if (!names) continue;
    const info = blockInfo.get(name);
    fp.traverse({
      MemberExpression(q) {
        if (!q.node.computed || !t.isNumericLiteral(q.node.property) || q.node.object.type !== 'Identifier') return;
        const b = q.scope.getBinding(q.node.object.name); if (!b || (b !== info.ctxB && b !== info.newCtxB)) return;
        const nm = names[q.node.property.value]; if (!nm) return;
        t.addComment(q.node.property, 'leading', ` ${nm} `, false); stats.ctxComments++;
      },
      BinaryExpression(q) {
        if (q.node.operator !== '&' || !t.isNumericLiteral(q.node.right) || q.node.left.type !== 'Identifier' || !info.dirtyB) return;
        if (q.scope.getBinding(q.node.left.name) === info.dirtyB) addDirty(q.get('right'), names);
      },
    });
  }
  return generate(ast, { comments: true, retainLines: false, compact: false, jsescOption: { minimal: true } }, code).code;
}

// ---------------------------------------------------------------------------------------------------
const files = []; (function walk(d) { for (const e of fs.readdirSync(d, { withFileTypes: true })) { const p = path.join(d, e.name); if (e.isDirectory()) walk(p); else if (/\.m?js$/.test(e.name)) files.push(path.relative(srcRoot, p)); } })(srcRoot);
files.sort();
for (let i = 0; i < files.length; i++) {
  if (i % shardCount !== shardIdx) continue;
  const rel = files[i]; stats.files++;
  const dst0 = path.join(outRoot, rel);
  if (RESUME && fs.existsSync(dst0)) { stats.skippedExisting = (stats.skippedExisting || 0) + 1; continue; }
  if (VENDOR_RE.test(rel)) { fs.mkdirSync(path.dirname(dst0), { recursive: true }); { const raw = fs.readFileSync(path.join(srcRoot, rel), 'utf8'); let pretty = raw; try { pretty = await prettier.format(raw, { parser: 'babel', printWidth: 110 }); } catch (e) { stats.failed.push(rel + ' [prettier-3p]: ' + String(e.message).slice(0, 80)); } fs.writeFileSync(dst0, pretty); } stats.copiedThirdParty = (stats.copiedThirdParty || 0) + 1; continue; }
  const t0 = Date.now();
  const code = fs.readFileSync(path.join(srcRoot, rel), 'utf8');
  let out = code;
  try { out = transformCode(code, rel); } catch (e) { stats.failed.push(rel + ': ' + String(e.message).slice(0, 160)); out = code; }
  try { out = await prettier.format(out, { parser: 'babel', printWidth: 110, singleQuote: false }); } catch (e) { stats.failed.push(rel + ' [prettier]: ' + String(e.message).slice(0, 100)); }
  const dst = path.join(outRoot, rel); fs.mkdirSync(path.dirname(dst), { recursive: true }); fs.writeFileSync(dst, out);
  console.error(rel, code.length, Date.now() - t0, 'ms');
}
fs.writeFileSync(statsOut, JSON.stringify(stats));
