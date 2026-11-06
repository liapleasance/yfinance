// usage: node runtime_cmp.mjs <origRoot> <newRoot> <fileListRoot> <out.json> [shardIdx shardCount]
// Loads every module of both trees in headless Chromium (network blocked except localhost), compares outcome + export shape,
// tries to instantiate exported Svelte components with empty props (comparing the rendered DOM text), and DIFFERENTIALLY CALLS every exported
// plain function with a fixed battery of argument vectors (undefined, 0, 1, strings, arrays, objects...), comparing return values / thrown error
// class / promise state between the two trees. This is what catches a semantic change that does not show at load time. Disable with YFIN_FUZZ=0.
// Error MESSAGES are not compared for calls (they can quote renamed local variables); Date/Math.random/performance.now are fixed.
// Isolation: every MODULE gets a fresh page; YFIN_FUZZ_ISOLATE=1 additionally gives each exported FUNCTION's battery its own fresh
// page, so a call that mutates shared module state cannot contaminate the next call's results (much slower: one context per function;
// the default still filters order-dependent effects via the orig2 self-baseline below).
import fs from 'node:fs'; import path from 'node:path'; import http from 'node:http';
import { chromium } from 'playwright';
const [origRoot, newRoot, listRoot, outFile, si = '0', sc = '1'] = process.argv.slice(2);
if (!origRoot || !newRoot || !listRoot || !outFile) { console.error('usage: node runtime_cmp.mjs <origRoot> <newRoot> <fileListRoot> <out.json> [shardIdx shardCount]'); process.exit(2); }
const files = []; (function walk(d){ for (const e of fs.readdirSync(d,{withFileTypes:true})) { const p=path.join(d,e.name); if(e.isDirectory()) walk(p); else if(/\.m?js$/.test(e.name)) files.push(path.relative(listRoot,p).split(path.sep).join('/')); } })(listRoot);   // '/' always: these rels feed the reports and the fallback list
files.sort();
const roots = { '/o/': path.resolve(origRoot) + path.sep, '/n/': path.resolve(newRoot) + path.sep };   // absolute + final sep: the traversal guard below compares string prefixes, and mixed separators (C:/ vs C:\) would 404 every request
const server = http.createServer((req, res) => {
  const u = decodeURIComponent(req.url.split('?')[0]);
  if (u === '/blank') { res.setHeader('content-type','text/html'); return res.end('<!doctype html><html><body><div id="root"></div></body></html>'); }
  for (const [pre, root] of Object.entries(roots)) if (u.startsWith(pre)) {
    const fp = path.join(root, u.slice(pre.length));
    if (!fp.startsWith(root) || !fs.existsSync(fp) || fs.statSync(fp).isDirectory()) { res.statusCode = 404; return res.end(); }
    res.setHeader('content-type', 'text/javascript'); return res.end(fs.readFileSync(fp));
  }
  res.statusCode = 404; res.end();
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const port = server.address().port, base = `http://127.0.0.1:${port}`;
const launchChromium = async () => { try { return await chromium.launch({ headless: true, args: ['--no-sandbox'] }); }
  catch (e) { if (!/Executable doesn't exist|playwright install/i.test(String(e && e.message))) throw e;
    return await chromium.launch({ headless: true, channel: 'chrome', args: ['--no-sandbox'] }); } };   // system Chrome, same engine, no download (never run playwright install)
const browser = await launchChromium();
const FUZZ = process.env.YFIN_FUZZ !== '0';
const ISOLATE = FUZZ && process.env.YFIN_FUZZ_ISOLATE === '1';
const INIT = `(() => { let s = 12345; Math.random = () => (s = (s * 1664525 + 1013904223) % 4294967296) / 4294967296; const T = 1700000000000; const D = Date;
  class FD extends D { constructor(...a) { if (a.length) super(...a); else super(T); } static now() { return T; } } globalThis.Date = FD;
  performance.now = () => 1000; window.alert = window.confirm = window.prompt = () => undefined; window.open = () => null; })();`;
async function newPage() {
  const ctx = await browser.newContext(); await ctx.addInitScript(INIT);
  await ctx.route('**/*', r => { const u = r.request().url(); (u.startsWith(base) || u.startsWith('data:') || u.startsWith('blob:')) ? r.continue() : r.abort(); });
  const page = await ctx.newPage(); page.on('pageerror', () => {}); page.on('console', () => {});
  await page.goto(base + '/blank'); return { ctx, page };
}
const FN = async ({ url, fuzz, only }) => {
  const out = { ok: false };
  const timeout = (ms) => new Promise(r => setTimeout(() => r('__timeout__'), ms));
  try {
    const m = await Promise.race([import(url), timeout(5000)]);
    if (m === '__timeout__') { out.err = 'TIMEOUT'; return out; }
    out.ok = true; out.shape = {}; out.comp = {};
    const fz = {}; let fzCount = 0;
    const ser = (v, d = 0) => { try {
      if (v === undefined) return 'u'; if (v === null) return 'n'; const t = typeof v;
      if (t === 'number') return Object.is(v, -0) ? '-0' : String(v); if (t === 'boolean' || t === 'bigint') return t[0] + String(v);
      if (t === 'string') return JSON.stringify(v.slice(0, 60)) + (v.length > 60 ? '+' + v.length : ''); if (t === 'symbol') return 'sym'; if (t === 'function') return 'fn' + v.length;
      if (v === globalThis) return 'globalThis'; if (typeof Node !== 'undefined' && v instanceof Node) return 'node:' + v.nodeName;
      if (d > 3) return '..'; if (Array.isArray(v)) return '[' + v.length + ':' + v.slice(0, 8).map(x => ser(x, d + 1)).join(',') + ']';
      if (v instanceof Map) return 'Map' + v.size; if (v instanceof Set) return 'Set' + v.size; if (v instanceof Date) return 'D' + v.getTime(); if (v instanceof RegExp) return String(v);
      const ks = Object.keys(v).sort(); return cname(v) + '{' + ks.slice(0, 8).map(k => k + ':' + ser(v[k], d + 1)).join(',') + (ks.length > 8 ? '+' + ks.length : '') + '}';
    } catch (e) { return 'SERERR'; } };
    // class names of NON-native classes are not compared (the pipeline renames local classes, which changes constructor.name); native ones are.
    const isNative = c => { try { return /\{\s*\[native code\]\s*\}/.test(Function.prototype.toString.call(c)); } catch { return false; } };
    const cname = v => { const c = v && v.constructor; return c && isNative(c) ? c.name : 'Obj'; };
    const ename = e => { if (!(e instanceof Error)) return ser(e); let p = Object.getPrototypeOf(e); while (p && p.constructor && !isNative(p.constructor)) p = Object.getPrototypeOf(p); return p && p.constructor ? p.constructor.name : 'Error'; };
    const ARGS = () => [[], [undefined], [0], [1], [-1], ['abc'], [''], [null], [[]], [[1, 2, 3]], [{}], [{ a: 1, b: 'x', c: [1, 2] }], [1, 2], ['a', 'b'], [[3, 1, 2], 0], [{ a: 1 }, { b: 2 }], [1700000000000], [true, false], [10, 20, 30]];
    for (const k of Object.keys(m).sort()) {
      const v = m[k]; const t = typeof v; if (v === globalThis) { out.shape[k] = 'globalThis'; continue; }
      out.shape[k] = t === 'function' ? 'fn' + v.length + (/^class\b/.test(Function.prototype.toString.call(v)) ? 'C' : '') : t === 'object' ? (v === null ? 'null' : Array.isArray(v) ? 'arr' + v.length : 'obj:' + Object.keys(v).length) : t === 'string' ? 'str' + v.length : t;
      if (t === 'function' && !/^class\b/.test(Function.prototype.toString.call(v))) (out.keys = out.keys || []).push(k);   // fuzzable exports (used by YFIN_FUZZ_ISOLATE to fuzz each one in its own page)
      if (t === 'function' && v.prototype && typeof v.prototype.$set === 'function' && typeof v.prototype.$destroy === 'function') {
        const div = document.createElement('div'); document.body.appendChild(div);
        try { const c = new v({ target: div, props: {} }); out.comp[k] = 'OK:' + div.textContent.replace(/\s+/g, ' ').slice(0, 300) + '|' + div.querySelectorAll('*').length; try { c.$destroy(); } catch {} }
        catch (e) { out.comp[k] = 'ERR:' + (e && e.constructor && e.constructor.name); }
        div.remove();
      } else if (fuzz && t === 'function' && !/^class\b/.test(Function.prototype.toString.call(v)) && (only == null || k === only) && fzCount < 300) {
        fzCount++; const outs = [];
        for (const args of ARGS()) { let r; try { r = v(...args); if (r && typeof r.then === 'function') { const x = await Promise.race([r.then(val => ({ val }), er => ({ er })), new Promise(res => setTimeout(res, 0, { pending: 1 }))]); r = x.pending ? 'PENDING' : x.er !== undefined ? 'REJ:' + ename(x.er) : 'RES:' + ser(x.val); } else r = ser(r); } catch (e) { r = 'THROW:' + ename(e); } outs.push(r.slice(0, 120)); }
        fz[k] = outs;
      }
    }
    if (Object.keys(fz).length) out.fz = fz;
  } catch (e) { out.err = (e && e.constructor && e.constructor.name) + ':' + String(e && e.message).replace(/https?:\/\/[^\s)]+/g, '<url>').slice(0, 160); }
  return out;
};
const results = {}; 
async function run(prefix) {
  let { ctx, page } = await newPage(); const res = {};
  for (let i = 0; i < files.length; i++) {
    if (i % +sc !== +si) continue; const rel = files[i];
    if (FUZZ && i > 0) { try { await ctx.close(); } catch {} ({ ctx, page } = await newPage()); }   // calling functions can leave global state behind: isolate every module
    let r; 
    try { r = await Promise.race([page.evaluate(FN, { url: base + prefix + rel, fuzz: FUZZ }), new Promise(rj => setTimeout(() => rj(new Error('HANG')), 20000))]); }
    catch (e) { r = { ok: false, err: 'HARNESS:' + String(e.message).slice(0, 60) }; try { await ctx.close(); } catch {} ({ ctx, page } = await newPage());
      if (FUZZ) { try { r = await Promise.race([page.evaluate(FN, { url: base + prefix + rel, fuzz: false }), new Promise(rj => setTimeout(() => rj(new Error('HANG')), 20000))]); r.noFuzz = true; } catch (e2) { r = { ok: false, err: 'HARNESS:' + String(e2.message).slice(0, 60), noFuzz: true }; try { await ctx.close(); } catch {} ({ ctx, page } = await newPage()); } } }
    if (r.ok && ISOLATE && r.keys && r.keys.length) {   // intra-module state isolation: a fresh page per exported function, so a call that mutates module state cannot skew the next call's results
      for (const k of r.keys) {
        try { await ctx.close(); } catch {} ({ ctx, page } = await newPage());
        let r1;
        try { r1 = await Promise.race([page.evaluate(FN, { url: base + prefix + rel, fuzz: true, only: k }), new Promise(rj => setTimeout(() => rj(new Error('HANG')), 20000))]); }
        catch (e2) { r1 = { err: 'HARNESS' }; }
        if (r1 && r1.fz && r1.fz[k]) { r.fz = r.fz || {}; r.fz[k] = r1.fz[k]; }
        else { r.fz = r.fz || {}; r.fz[k] = ['HARNESS']; r.noFuzz = true; }
      }
    }
    res[rel] = r;
  }
  try { await ctx.close(); } catch {}
  return res;
}
results.orig = await run('/o/'); results.new = await run('/n/');
if (FUZZ) results.orig2 = await run('/o/');   // baseline: the ORIGINAL against itself; calls whose results differ between two runs are nondeterministic and are not compared
await browser.close(); server.close();
let same = 0; const diffs = []; let fnsCalled = 0; const inconclusive = []; let unstable = 0;
// settled results are compared exactly; a call that was still PENDING in one tree and settled in the other is a timing difference, not a semantic one
const eqCall = (x, y) => x === y || (x === 'PENDING' && /^(RES|REJ):/.test(y)) || (y === 'PENDING' && /^(RES|REJ):/.test(x));
for (const rel of Object.keys(results.orig)) {
  const a = results.orig[rel], b = results.new[rel];
  let fa = a.fz || {}, fb = b.fz || {}; const fa2 = results.orig2?.[rel]?.fz || {};
  for (const k of Object.keys(fa)) { const x = fa[k], y = fa2[k] || []; if (x.some((v, i) => !eqCall(v, y[i]))) { delete fa[k]; delete fb[k]; unstable++; } }
  if (a.noFuzz || b.noFuzz) { fa = {}; fb = {}; inconclusive.push(rel); }   // the module hit a harness error (e.g. navigation) while calling functions: only load-time comparison for it
  fnsCalled += Object.keys(fa).length;
  const sa = { ...a }, sb = { ...b }; for (const o of [sa, sb]) { delete o.fz; delete o.noFuzz; }
  const fzd = {};
  for (const k of new Set([...Object.keys(fa), ...Object.keys(fb)])) { const x = fa[k] || [], y = fb[k] || []; const n = Math.max(x.length, y.length); let bad = -1;
    for (let i = 0; i < n; i++) if (!eqCall(x[i], y[i])) { bad = i; break; }
    if (bad >= 0) fzd[k] = { argvec: bad, a: x[bad], b: y[bad] }; }
  if (JSON.stringify(sa) === JSON.stringify(sb) && !Object.keys(fzd).length) same++;
  else { if (Object.keys(fzd).length) { sa.fzDiff = fzd; sb.fzDiff = fzd; } diffs.push({ rel, a: sa, b: sb }); }
}
const okCount = Object.values(results.orig).filter(x => x.ok).length;
const summary = { tested: Object.keys(results.orig).length, identical: same, differ: diffs.length, origLoadedOk: okCount, componentsTried: Object.values(results.orig).reduce((n, x) => n + Object.keys(x.comp || {}).length, 0), functionsCalled: fnsCalled, fuzz: FUZZ, callsInconclusiveModules: inconclusive.length, nondeterministicFunctionsIgnored: unstable };
for (const x of Object.values(results.orig)) delete x.fz;
fs.writeFileSync(outFile, JSON.stringify({ summary, diffs, orig: results.orig }, null, 0));
console.log(JSON.stringify(summary));
process.exit(diffs.length ? 1 : 0);
