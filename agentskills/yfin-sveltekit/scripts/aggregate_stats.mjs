// usage: node aggregate_stats.mjs <statsDir> <shards> [out.json]
// Sums stats_shard_<i>.json written by transform.mjs. Exit 1 if a shard file is missing or any file failed to transform.
import fs from 'node:fs'; import path from 'node:path';
const [dir, shardsArg, outFile] = process.argv.slice(2);
if (!dir || !shardsArg) { console.error('usage: node aggregate_stats.mjs <statsDir> <shards> [out.json]'); process.exit(2); }
const shards = +shardsArg; const agg = {}; const failed = []; const unmapped = {}; const unmappedLocal = []; let missing = 0;
for (let i = 0; i < shards; i++) {
  const f = path.join(dir, `stats_shard_${i}.json`);
  if (!fs.existsSync(f)) { console.error('MISSING', f); missing++; continue; }
  const s = JSON.parse(fs.readFileSync(f, 'utf8'));
  for (const [k, v] of Object.entries(s)) {
    if (k === 'failed') failed.push(...v); else if (k === 'unmappedLocalKeys') unmappedLocal.push(...v);
    else if (k === 'unmappedImports') for (const [a, b] of Object.entries(v)) unmapped[a] = (unmapped[a] || 0) + b;
    else if (typeof v === 'number') agg[k] = (agg[k] || 0) + v;
  }
}
const out = { agg, failed, unmappedLocalKeys: unmappedLocal, unmappedImports: unmapped };
if (outFile) fs.writeFileSync(outFile, JSON.stringify(out, null, 1));
console.log(JSON.stringify(agg)); console.log('failed:', failed.length, ' unmappedLocalKeys:', unmappedLocal.length, ' unmappedImports:', Object.keys(unmapped).length);
for (const f of failed.slice(0, 20)) console.log('  FAILED', f);
process.exit(missing || failed.length ? 1 : 0);
