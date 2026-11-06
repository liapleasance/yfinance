// usage: node decode_devalue.mjs <payload.json> [--entry N] [--node N] [--max-chars K] [--api-map FILE]
// --api-map FILE: also write a Markdown inventory of every API URL and hostname found in the decoded payload strings
//   (the layout-2 payload carries the kit's master service table: query1/query2.finance.yahoo.com, yfc-server-query, ...)
//   to FILE (e.g. reports/API_ENDPOINTS.md). Nothing is fetched: only strings already in the payload are collected.
// Decodes the DATA WIRE FORMAT of SvelteKit server loads (the "devalue" format) from a file the user already
// has on disk — a __data.json ({ "type": "data", "nodes": [...] }, as downloaded beside the pages) or a bare
// root array (the payload of a node, or the array inside the inline hydration <script> of a page). Static,
// offline, no network, nothing is fetched here.
//
// VERIFIED wire format (see references/kit-internals.md):
//   data = [entry0, entry1, ...]   entry0 = the payload root.
//   Numbers INSIDE objects/arrays are REFERENCES (indices into the root array), never literals — a literal
//   number always gets its own entry. Special values arrive as ["Date", iso] / ["Set", [...]] /
//   ["Map", [k, v, ...]] / ["RegExp", src] / ["Infinity"] / ["-Infinity"] / ["NaN"] / ["-0"] /
//   ["undefined"] / ["bigint", digits].
//   In a __data.json, nodes[i] is null/"skip" exactly where the route's tree position has no server load
//   (root layout, layouts without +layout.server.js, leaf without ~marker).
//
// Output: readable JSON on stdout (redirect to a file for big payloads). Special values are marked as
// {"$":"Date","v":...} etc so nothing is lost. Node positions mirror the route's component tree:
// [root layout, layout..., leaf].
import fs from 'node:fs';
const argv = process.argv.slice(2);
const file = argv.find((a, i) => !a.startsWith('--') && !(i > 0 && argv[i - 1].startsWith('--')));   // the payload is the first token that is not a flag or a flag's value
const opt = n => { const i = argv.indexOf('--' + n); return i >= 0 ? argv[i + 1] : null; };
if (!file) { console.error('usage: node decode_devalue.mjs <payload.json> [--entry N] [--node N] [--max-chars K] [--api-map FILE]'); process.exit(2); }
const maxChars = +(opt('max-chars') || 0);
const apiMapFile = opt('api-map');
const apiUrls = new Set(); const apiHosts = new Set();
function collectEndpoints(v, seen = new WeakSet(), depth = 0) {   // static string inventory of the decoded payload: URLs with a scheme, plus bare hostnames that look like kit services
  if (v == null || depth > 60) return;
  if (typeof v === 'string') {
    for (const m of v.matchAll(/https?:\/\/[A-Za-z0-9._~:/?#@!$&'()*+,;=%-]+/g)) {
      const u = m[0].replace(/[.,;:)\]]+$/, '');
      if (u.length > 8) { apiUrls.add(u); try { apiHosts.add(new URL(u).hostname); } catch {} }
    }
    if (v.length < 100 && /^[a-z0-9_-]+(\.[a-z0-9_-]+)+\.[a-z]{2,}$/i.test(v) && /yahoo|yimg|oath|finance|quant|grpc|query|api|cdn/i.test(v)) apiHosts.add(v);
    return;
  }
  if (typeof v === 'object' && !seen.has(v)) { seen.add(v); for (const x of Object.values(v)) collectEndpoints(x, seen, depth + 1); }
}

const TAGS = new Set(['Date', 'Set', 'Map', 'RegExp', 'Infinity', '-Infinity', 'NaN', '-0', 'undefined', 'bigint', 'hole']);
function decode(root, i, memo = new Map(), depth = 0) {
  if (memo.has(i)) return memo.get(i);
  if (depth > 500) return { $: 'MAX-DEPTH' };
  const out = walk(root[i], depth);
  memo.set(i, out);
  return out;
  function walk(v, d) {
    if (v === null || typeof v === 'string' || typeof v === 'boolean') return v;
    if (typeof v === 'number') return v;                      // a bare entry IS a literal
    if (Array.isArray(v)) {
      if (typeof v[0] === 'string' && TAGS.has(v[0])) {
        switch (v[0]) {
          case 'Date': return { $: 'Date', v: v[1] };
          case 'Set': return { $: 'Set', v: (v[1] || []).map(x => sub(x, d)) };
          case 'Map': return { $: 'Map', v: (v[1] || []).reduce((a, x, k, arr) => (k % 2 === 0 ? (a.push([sub(x, d), sub(arr[k + 1], d)]), a) : a), []) };
          case 'RegExp': return { $: 'RegExp', v: v[1] };
          case 'bigint': return { $: 'bigint', v: v[1] };
          default: return { $: v[0] };                        // Infinity, -Infinity, NaN, -0, undefined, hole
        }
      }
      return v.map(x => sub(x, d));
    }
    if (typeof v === 'object') {
      const o = {};
      for (const [k, val] of Object.entries(v)) o[k] = sub(val, d);
      return o;
    }
    return v;
  }
  function sub(x, d) { return typeof x === 'number' ? decode(root, x, memo, d + 1) : walk(x, d + 1); }
}

const raw = JSON.parse(fs.readFileSync(file, 'utf8'));
if (Array.isArray(raw)) {
  const entry = +(opt('entry') || 0);
  const dec = decode(raw, entry); if (apiMapFile) collectEndpoints(dec);
  print(dec, `bare array: ${raw.length} entries, root = entry ${entry}`);
} else if (raw && Array.isArray(raw.nodes)) {
  const only = opt('node');
  for (let i = 0; i < raw.nodes.length; i++) {
    const nd = raw.nodes[i];
    if (nd === null) { if (!only) console.log(`node[${i}]: null (no server load at this position)`); continue; }
    if (nd.type === 'skip') { if (!only) console.log(`node[${i}]: skip`); continue; }
    if (nd.type !== 'data') { if (!only) console.log(`node[${i}]: type=${nd.type}`); continue; }
    if (only != null && +only !== i) continue;
    const arr = nd.data;
    if (!Array.isArray(arr)) { console.log(`node[${i}]: data is ${typeof arr} (not a devalue array)`); continue; }
    const dec = decode(arr, +(opt('entry') || 0)); if (apiMapFile) collectEndpoints(dec);
    print(dec, `node[${i}]: type=data, ${arr.length} devalue entries, uses=${JSON.stringify(nd.uses ?? null)}`);
  }
} else { console.error('ERROR: not a devalue payload (expected {type:"data",nodes:[...]} or a bare array)'); process.exit(2); }

if (apiMapFile && (apiUrls.size || apiHosts.size)) {
  const lines = ['# Yahoo Finance - API endpoints & hosts (decoded from the devalue payload)', '',
    `- source: ${file.split(/[\\/]/).pop()} | URLs: ${apiUrls.size} | hosts: ${apiHosts.size} | static inventory, nothing fetched`, '',
    '## Hosts', '', ...[...apiHosts].sort().map(x => `- ${x}`), '',
    '## Endpoints (URLs found in payload strings)', '', ...[...apiUrls].sort().map(x => `- ${x}`), ''];
  fs.writeFileSync(apiMapFile, lines.join('\n') + '\n');
  console.log(`\n=== API map written to ${apiMapFile} (${apiUrls.size} URLs, ${apiHosts.size} hosts) ===`);
}

function print(obj, header) {
  const s = JSON.stringify(obj, null, 1);
  console.log(`\n=== ${header} ===`);
  console.log(maxChars ? (s.length > maxChars ? s.slice(0, maxChars) + `\n... (${s.length} chars total; --max-chars ${maxChars})` : s) : s);
}
