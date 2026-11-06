// usage: node rt_report.mjs <origRoot> <rt_0.json> [rt_1.json ...] [--culprits]
// Summarises runtime_cmp.mjs results. Without --culprits: one line per differing module. With --culprits: prints only the ROOT-CAUSE files
// (differing modules none of whose static imports is itself a differing module) = the ones to move to the fallback list; their dependents
// usually heal by themselves, so rerun runtime_cmp after rebuilding them and iterate.
import fs from 'node:fs'; import path from 'node:path';
const args = process.argv.slice(2); const culprits = args.includes('--culprits'); const [origRoot, ...files] = args.filter(a => a !== '--culprits');
if (!origRoot || !files.length) { console.error('usage: node rt_report.mjs <origRoot> <rt_0.json> [rt_1.json ...] [--culprits]'); process.exit(2); }
const diffs = []; let tested = 0, identical = 0, origFail = 0, fns = 0, comps = 0, unst = 0, inc = 0;
for (const f of files) { const r = JSON.parse(fs.readFileSync(f, 'utf8')); diffs.push(...r.diffs); tested += r.summary.tested; identical += r.summary.identical; fns += r.summary.functionsCalled || 0; comps += r.summary.componentsTried || 0; unst += r.summary.nondeterministicFunctionsIgnored || 0; inc += r.summary.callsInconclusiveModules || 0; for (const v of Object.values(r.orig)) if (!v.ok) origFail++; }
const why = d => { const a = d.a, b = d.b, w = [];
  if (a.ok !== b.ok || a.err !== b.err) w.push(`ok:${a.ok}->${b.ok} ${a.err || ''} | ${b.err || ''}`);
  if (a.shape && b.shape) for (const k of new Set([...Object.keys(a.shape), ...Object.keys(b.shape)])) if (a.shape[k] !== b.shape[k]) w.push(`shape ${k} ${a.shape[k]}->${b.shape[k]}`);
  if (a.comp && b.comp) for (const k of Object.keys(a.comp)) if (a.comp[k] !== b.comp[k]) w.push(`comp ${k}: ${String(a.comp[k]).slice(0, 70)} || ${String(b.comp[k]).slice(0, 70)}`);
  if (a.fzDiff) for (const [k, v] of Object.entries(a.fzDiff)) w.push(`call ${k}(argvec ${v.argvec}): ${v.a} || ${v.b}`);
  return w.join(' ; ').slice(0, 300); };
if (culprits) {
  const set = new Set(diffs.map(d => d.rel)); const out = [];
  for (const d of diffs) {
    let code = ''; try { code = fs.readFileSync(path.join(origRoot, d.rel), 'utf8'); } catch {}
    const deps = [...code.matchAll(/(?:from|import)\s*\(?\s*["'](\.{1,2}\/[^"']+)["']/g)].map(m => path.normalize(path.join(path.dirname(d.rel), m[1])));
    if (!deps.some(x => set.has(x) && x !== d.rel)) out.push(d.rel);
  }
  console.log(out.sort().join('\n'));
} else {
  for (const d of diffs) console.log(d.rel, '=>', why(d));
  console.log(JSON.stringify({ tested, identical, differ: diffs.length, modulesFailingToLoadInOriginalToo: origFail, componentsRendered: comps, functionsCalled: fns, nondeterministicFunctionsIgnored: unst, modulesWithoutCalls: inc }));
}
