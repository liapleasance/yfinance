# Workflow - exact commands

`SK` = this skill folder. `W` = a writable work directory. `T=$W/tools`. `ORIG` = the SCOPED build: `bash $T/scope_build.sh <buildFolder> $W/src` finds `<site>/assets/_app/immutable` (give it that folder or any folder above it; it refuses when it finds none or more than one build) and copies ONLY the `.js`/`.mjs` files of `entry/`, `nodes/`, `chunks/` into `$W/src`, which is `ORIG` from here on. It prints `ROOT`, `FILES`, `OUT_OF_SCOPE` (names only), `NONJS`, `MAPS`. Everything else (other directories, `manifest.json`, service workers, non-JS files) is out of scope: never read, never copied. Never put credential files (session, cookie, token dumps) into any tree you copy or zip.

## Fast path
`bash $T/run_auto_pipeline.sh <buildFolder> $OUT 2` (step 0 = `scope_build.sh`) runs sections 1-6 automatically: per-build names map, up to 3 verification rounds (runtime culprits move to the fallback list), reports, VERIFICATION.md. Poll `$OUT/STATUS.txt`. Also does: route comments on `nodes/*.js` (`annotate_routes.mjs`, comments only, re-applied after fallback rebuilds) and `reports/CHUNK_INDEX.md` (`chunk_index.mjs`). Use it first; the manual sections below are for debugging a FAILED run. `YFIN_MAKE_MAP_FLAGS="--no-svelte-names"` (or `--no-kit-names`) works offline with fewer names.

## Fast path, focused scoping (@universal / route family / whole build)
`YFIN_ROUTES="@universal" bash $T/run_auto_pipeline.sh <buildFolder> $OUT 2` — the RECOMMENDED scope (the skill's objective is readability of the code that runs on every page, not coverage): step 0 becomes `scope_routes.sh` with `@universal`, which selects the implicit root layout (node 0 — detected from the kit client chunk: the runtime prepends it to every route and the dictionary never lists it) plus the layouts that run on >=95% of ALL routes of THIS build's dictionary (frequency — never a node number; on a real build: node 2, 96.3% of 219 routes), plus the entries and their import closure (SvelteKit client included), NO page nodes. On a real build that is ~115 files (~5.8% of the folder).
`YFIN_ROUTES="quote/" bash $T/run_auto_pipeline.sh <buildFolder> $OUT 2` — a route family: entries + the union of the matched routes' layouts (the backbone, plus node 0 when detected as the implicit root layout) + the page nodes of the matched routes (a NEGATIVE leaf = a page WITH a server load, node = `~value`) + their static-import closure + their `__vite__mapDeps` preloads + the dynamic imports of everything except `app.<hash>.js`. Everything else in entry/nodes/chunks is not read, not copied (`SKIPPED` in `work/scope.txt`). Multiple filters: `YFIN_ROUTES="quote/ markets/"`; `YFIN_ROUTES="*"` = whole build (identical to the default fast path). VERIFICATION.md then states exactly which scope was verified. Manual equivalents of step 0:
```
bash $T/scope_routes.sh <buildFolder> $W/src -- @universal  # prints ROOT/MODE/FILES/ROUTES/BACKBONE/BACKBONE_COVERAGE/LEAVES/SKIPPED/... ; writes $W/src.selection.{txt,json}
bash $T/scope_routes.sh <buildFolder> $W/src -- quote/       # same contract for a route family
node $T/select_routes.mjs <root> $W/sel quote/ --static-only # selection only (no copy); --static-only = tighter set, still closed
```
`select_routes.mjs` refuses (exit 1) a build whose selected files statically import something missing on disk (files DO disappear between builds — re-download) or outside entry/nodes/chunks, and resolves node files through the `nodes` array of `app.<hash>.js` (stale same-number files of older builds are ignored and counted). The selection JSON carries the `hubChunks` report (chunks most imported by the current nodes with `inSelection` flags) — use it when a chunk that "obviously runs on every page" is missing from the backbone (FooterV2/loadMarketTime moved from the master layout to per-node imports between two real builds); a family scope pulls such chunks in transitively. Use `$W/src` as `ORIG` for every manual section below; nothing else changes.

## 0. Setup (once per session)
```
bash $SK/scripts/setup.sh $W          # copies scripts to $W/tools, npm ci (pinned), checks Node>=22 + Chromium; prints TOOLS=...
bash $W/tools/selftest.sh             # must print SELFTEST PASS. A SKIP line means that guard was NOT validated here (no Chromium / no npm registry); --no-browser skips the Chromium checks
```
Chromium: Playwright uses PLAYWRIGHT_BROWSERS_PATH (usually /opt/pw-browsers). Never run `playwright install`.

## 1. Stage 1 - Wakaru
```
bash $T/wakaru_run.sh $ORIG $W/stage1 2        # `*.min.*`/`*.worker.*` files copied verbatim; a file Wakaru fails on (180 s timeout) is copied from ORIG and listed in _failures.txt
```
On the scoped tree the only third-party code left is `*.min.*` / `*.worker.*` files inside `chunks/` (override: `WAKARU_SKIP_REGEX`); the script also skips every top-level directory that is not SvelteKit's, which only matters if you run it on an unscoped tree. Long (minutes): `nohup bash ... > $W/s1.log 2>&1 &`, poll `tail -2 $W/s1.log`.

## 2. Hazard scan
```
node $T/scan_hazards.mjs $ORIG $W/stage1 $W/hz.json     # -> hz.json, hz.json.list.txt (FALLBACK LIST), hz.json.info.json
```
Read `byReason` in the printed summary. The scanner is not complete: some files are only caught by the runtime check (Function.length drift). `--strict-length` also falls back on any Function.length drift (about 100 files on a full build, harmless in practice, so off by default).

## 3. Name map (per build; never reuse another build's)
```
node $T/make_map.mjs $ORIG $W/names_map.mjs     # BUILD_ID + ROLES + Svelte runtime names + SvelteKit client names; also writes names_map.mjs.roles.json
node $T/prescan_components.mjs $ORIG $W/component_exports.json $W/names_map.mjs.roles.json
export NAMES_MAP=$W/names_map.mjs               # required by run_transform.sh / apply_fallback.sh
```
Check the printed ROLES: `init` and `component_subscribe` should be present; a role in `notFoundOrAmbiguous` disables only the annotations that depend on it (say so). Without network use `--no-svelte-names`.

## 4. Stage 2
```
nohup bash $T/run_transform.sh $W/stage1 $W/final $W/component_exports.json $ORIG $W/stats 2 > $W/s2.log 2>&1 &
# poll: tail -1 $W/s2.log  -> TRANSFORM OK | TRANSFORM FAILED  (resume: YFIN_RESUME=1)
bash $T/apply_fallback.sh $ORIG $W/final $W/hz.json.list.txt $W/component_exports.json 2
```
`apply_fallback.sh` deletes the flagged outputs and rebuilds them from ORIG (renames + prettier, no Wakaru). Run `reports.mjs` only on the stats of ONE uninterrupted `run_transform.sh` run (a resumed run undercounts).

## 5. Verification (see `verification.md`)
```
nohup bash $T/verify_all.sh $ORIG $W/stage1 $W/final $W/hz.json.list.txt $W/verify > $W/v.log 2>&1 &
cat $W/verify/VERIFY_SUMMARY.txt          # last line OVERALL PASS|FAIL
```
On runtime FAIL:
```
node $T/rt_report.mjs $ORIG $W/verify/rt_*.json --culprits > $W/culprits.txt   # root-cause files (a failing dependency makes importers fail too)
cat $W/culprits.txt >> $W/hz.json.list.txt; sort -u $W/hz.json.list.txt -o $W/hz.json.list.txt
bash $T/apply_fallback.sh $ORIG $W/final $W/culprits.txt $W/component_exports.json 2
# re-run verify_all with the updated list
```
Never loosen a verifier to get PASS.

## 6. Reports and delivery
```
node $T/reports.mjs $W/final $W/stats $W/reports 2     # ROUTES.md (route -> node -> layouts, decoded), UNMAPPED_IMPORTS.md
node $T/kit_intel.mjs $W/src $W/reports               # KIT_INTEL.md (the build's self-description: routes, server loads, matchers, hydration global, stale files)
```
Zip `final/` + reports + VERIFICATION.md (numbers from VERIFY_SUMMARY.txt, fallback list, limits) with `zip -r` and send with SendUserFile.

## Decoding data payloads the user provides (offline, no fetching)
A `__data.json` (downloaded beside the pages) or the array inside a page's inline hydration `<script>` is devalue wire format — numbers inside containers are references into the root array:
```
node $T/decode_devalue.mjs <file.json>                 # all data nodes of a __data.json
node $T/decode_devalue.mjs <file.json> --node 1        # one tree position (root layout=0, layouts..., leaf=last)
node $T/decode_devalue.mjs <file.json> --entry 0       # a bare devalue array
node $T/decode_devalue.mjs <file.json> --api-map $W/reports/API_ENDPOINTS.md   # + static inventory of every API URL/hostname in the payload strings
```
The layout-2 payload is the site's own service table (every API host) — `--api-map` turns it into a report (hosts + URLs, sorted, nothing fetched) instead of hand-copying hosts while reading the code.

## Practical limits and typical numbers
Tool calls die at ~10 min; stage 2 uses up to ~3.5 GB per shard, so shards default to `min(nproc, MemAvailable/3.5GB)` (run_auto_pipeline.sh computes it when the 3rd argument is omitted; an explicit value always wins — on 2 cores that is still 2). Chromium runtime check: 5 s import timeout per module, network blocked, Math.random/Date/performance.now fixed, fresh context per module, ~10 min on a full build with the differential calls (set `YFIN_FUZZ=0` for a ~1 min load-only pass while debugging; `YFIN_FUZZ_ISOLATE=1` additionally gives each exported function's battery its own fresh page, so one call mutating module state cannot skew the next call's results — much slower).
Three real builds (2 cores) took 20-45 min end to end with the fast path; the last one, with the scope fixed to `entry/`, `nodes/`, `chunks/`, had 1016 in-scope `.js` files (the full downloaded folder had 1092, the other 76 being out-of-scope third-party files) and took about 36 min. Each ended `OVERALL PASS` with 11-13 files on the original-code fallback (the scanner flags about 11; the runtime check found 1 more each time), and about 219 routes / 282 nodes. On that last build the three folders came out byte-identical to the earlier run that still processed the whole folder, so narrowing the scope changed nothing inside them. If your numbers are far from these, look at `work/*.log` before trusting the result.
Debug helper: `node $T/stack.mjs <root> <relPath>` loads ONE module in headless Chromium (network blocked) and prints `ok` or the error stack; use it on a module the runtime check reports as a load difference.
SvelteKit-client naming tries kit 2.5-2.60 and 3.0-3.1 and keeps the version with the most structural matches (`YFIN_KIT_VERSIONS=a,b,c` overrides the list). A build from a kit version not in the list normally just gets fewer names (a name needs a unique structural match on both sides, so it degrades towards "unnamed", not towards guesses); this was checked on real builds only for 2.8.x.
