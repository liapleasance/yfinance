// usage: node stack.mjs <root> <relPath>   -> loads ONE module in headless Chromium (network blocked) and prints 'ok' or the error stack. Debug helper for runtime_cmp diffs.
import fs from 'node:fs'; import path from 'node:path'; import http from 'node:http';
import { chromium } from 'playwright';
const [root, rel] = process.argv.slice(2);
const server = http.createServer((req, res) => { const u = decodeURIComponent(req.url.split('?')[0]); if (u === '/blank') { res.setHeader('content-type','text/html'); return res.end('<!doctype html><body></body>'); } const fp = path.join(root, u); if (!fs.existsSync(fp)) { res.statusCode=404; return res.end(); } res.setHeader('content-type','text/javascript'); res.end(fs.readFileSync(fp)); });
await new Promise(r => server.listen(0,'127.0.0.1',r)); const base = `http://127.0.0.1:${server.address().port}`;
let b; try { b = await chromium.launch({ headless: true, args:['--no-sandbox'] }); }
catch (e) { if (!/Executable doesn't exist|playwright install/i.test(String(e && e.message))) throw e; b = await chromium.launch({ headless: true, channel:'chrome', args:['--no-sandbox'] }); }   // system Chrome, same engine, no download
const p = await b.newPage(); await p.route('**/*', r => r.request().url().startsWith(base) ? r.continue() : r.abort()); await p.goto(base+'/blank');
console.log(await p.evaluate(async (u) => { try { await import(u); return 'ok'; } catch (e) { return e.stack; } }, base + '/' + rel));
await b.close(); server.close();
