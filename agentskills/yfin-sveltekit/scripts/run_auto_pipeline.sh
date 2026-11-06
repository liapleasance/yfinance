#!/usr/bin/env bash
# usage: run_auto_pipeline.sh <buildFolder> <outDir> [shards]   (env YFIN_ROUTES="filter..." for route-family scoping)
#        shards default: min(nproc, MemAvailable/3.5GB) — the verification workers are memory-hungry; an explicit value always wins.
# One command for ANY finance.yahoo.com build (hashes change daily; nothing here depends on them). Needs setup.sh done (this script lives in <workdir>/tools).
# <buildFolder> = the SvelteKit "immutable" folder (<site>/assets/_app/immutable: entry/, nodes/, chunks/) or ANY folder above it; the script finds it.
# SCOPE: only the .js files of entry/, nodes/ and chunks/ are processed. Everything else in the folder (other directories, manifest.json, service workers,
#        non-JS files) is out of scope: never read, never copied, never in the output. The three folders must be import-closed (checked on real builds).
# YFIN_ROUTES (optional): focused scoping — "the parts that run on every page" is the skill's objective, not the whole build.
#        "@universal" = the layouts that run on >=95% of ALL routes of THIS build's dictionary (frequency, never node numbers)
#        plus the entries and their import closure; no page nodes. Substrings (e.g. "quote/") = route families: the union of
#        the matched routes' layouts (the backbone), their page/redirect leaves, the static-import closure, the __vite__mapDeps
#        preloads and the dynamic imports of everything except app.<hash>.js. "*" = whole build (the default when YFIN_ROUTES
#        is unset). Everything else in entry/nodes/chunks is not read, not copied (SKIPPED in scope.txt). VERIFICATION.md then
#        says exactly which scope was verified.
# LONG-RUNNING (typically 20-45 min on 2 cores for the whole build; a single family such as quote/ is proportionally faster): launch with nohup ... & and poll <outDir>/STATUS.txt.
# Steps: 0 locate + scope -> stage1 Wakaru -> hazard scan -> per-build names map (BUILD_ID, Svelte roles, Svelte + SvelteKit names from the official sources)
#        -> stage 2 -> fallback -> verification loop (verify_pair + ast_equiv + runtime_cmp; runtime culprits go to fallback and it re-verifies, max 3 rounds)
#        -> reports. Output: <outDir>/final (tree), <outDir>/reports/{ROUTES.md,UNMAPPED_IMPORTS.md,CHUNK_INDEX.md}, <outDir>/VERIFICATION.md, <outDir>/work/* (logs).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IN="$(cd "${1:?usage: run_auto_pipeline.sh <buildFolder> <outDir> [shards]}" && pwd)"; mkdir -p "${2:?}"; OUT="$(cd "$2" && pwd)"; N="${3:-}"
W="$OUT/work"; mkdir -p "$W" "$OUT/reports"; ST="$OUT/STATUS.txt"
if [ -z "$N" ]; then   # shards not given: min(nproc, MemAvailable/3.5GB) — each verification worker loads a full Chromium page; RAM is the real ceiling
  N=$( { nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2; } | head -1)
  if [ -r /proc/meminfo ]; then
    avail_mb=$(awk '/MemAvailable/{print int($2 / 1024)}' /proc/meminfo 2>/dev/null)
    case "$avail_mb" in ''|*[!0-9]*) avail_mb='' ;; esac
    if [ -n "$avail_mb" ] && [ "$avail_mb" -ge 1024 ]; then
      ram_shards=$((avail_mb / 3500)); [ "$ram_shards" -ge 1 ] || ram_shards=1
      [ "$N" -gt "$ram_shards" ] && N="$ram_shards"
      echo "shards: min(nproc, MemAvailable/3.5GB) = $N (MemAvailable ${avail_mb} MB)" | tee -a "$OUT/PIPELINE.log"
    fi
  fi
  case "$N" in ''|*[!0-9]*) N=2 ;; esac
fi
echo "shards: $N" | tee -a "$OUT/PIPELINE.log"
sc() { sed -n "s/^$1=//p" "$W/scope.txt"; }   # must exist BEFORE step 0: the scoping log line reads MODE/ROUTES/BACKBONE_COVERAGE/SKIPPED from scope.txt
step() { echo "RUNNING $*" > "$ST"; echo "[$(date +%H:%M:%S)] $*" | tee -a "$OUT/PIPELINE.log"; }
fail() { echo "FAILED $*" > "$ST"; echo "FAILED: $*" | tee -a "$OUT/PIPELINE.log"; exit 1; }
[ -d "$HERE/node_modules" ] || fail "run setup.sh first (node_modules missing in $HERE)"
cred=$(find "$IN" -maxdepth 6 -path "$OUT" -prune -o -type f ! -name '*.js' ! -name '*.mjs' \( -iname '*session*' -o -iname '*cookie*' -o -iname '*token*' -o -iname '*.pem' -o -iname '.env*' \) -print 2>/dev/null | head -5); [ -n "$cred" ] && echo "NOTE: credential-like files found and IGNORED (never read or copied): $cred" | tee -a "$OUT/PIPELINE.log"
step "0/7 locate the build and keep only entry, nodes, chunks"
if [ -n "${YFIN_ROUTES:-}" ]; then
  # route-family / universal-backbone scoping: YFIN_ROUTES = space-separated dictionary-key substrings
  # ("quote/"), "@universal" (the layouts that run on >=95% of all routes), or "*" (whole build)
  bash "$HERE/scope_routes.sh" "$IN" "$W/src" -- $YFIN_ROUTES > "$W/scope.txt" 2> "$W/scope.err" || fail "$(cat "$W/scope.err")"
  echo "route scoping: filters='${YFIN_ROUTES}' mode=$(sc MODE) | $(sc ROUTES) routes considered | backbone $(sc BACKBONE_COVERAGE) | $(sc SKIPPED) files of entry/nodes/chunks not selected (not read, not copied)" | tee -a "$OUT/PIPELINE.log"
else
  bash "$HERE/scope_build.sh" "$IN" "$W/src" "$OUT" > "$W/scope.txt" 2> "$W/scope.err" || fail "$(cat "$W/scope.err")"
fi
BUILD="$W/src"; nfiles=$(sc FILES); ignored_top=$(sc OUT_OF_SCOPE)
echo "scope: $nfiles .js files from entry/ nodes/ chunks/ of $(sc ROOT) | out of scope, not read and not copied: ${ignored_top:-nothing} | non-JS files inside the 3 folders ignored: $(sc NONJS)" | tee -a "$OUT/PIPELINE.log"
[ "$(sc MAPS)" -gt 0 ] && echo "NOTE: $(sc MAPS) .map file(s) exist in the build; 'wakaru extract' could recover original sources from them (not used here)." | tee -a "$OUT/PIPELINE.log"
step "1/7 stage 1 (Wakaru)";      bash "$HERE/wakaru_run.sh" "$BUILD" "$W/stage1" 2 > "$W/s1.log" 2>&1 || fail "wakaru_run (see $W/s1.log)"; tail -1 "$W/s1.log" | tee -a "$OUT/PIPELINE.log"
step "2/7 hazard scan";           node "$HERE/scan_hazards.mjs" "$BUILD" "$W/stage1" "$W/hz.json" > "$W/scan.log" 2>&1 || fail "scan_hazards (see $W/scan.log)"; cat "$W/scan.log" | tee -a "$OUT/PIPELINE.log"; cp "$W/hz.json.list.txt" "$W/fallback.txt"
[ -n "${YFIN_TEST_IGNORE_SCAN:-}" ] && : > "$W/fallback.txt"   # TEST ONLY (selftest): pretend the scanner flagged nothing, to exercise the runtime-culprit loop
step "3/7 names map for THIS build"; node "$HERE/make_map.mjs" "$BUILD" "$W/names_map.mjs" ${YFIN_MAKE_MAP_FLAGS:-} > "$W/map.log" 2>&1 || fail "make_map (see $W/map.log)"; tail -3 "$W/map.log" | cut -c1-300 | tee -a "$OUT/PIPELINE.log"
node "$HERE/prescan_components.mjs" "$BUILD" "$W/component_exports.json" "$W/names_map.mjs.roles.json" > "$W/prescan.log" 2>&1 || fail "prescan_components (see $W/prescan.log)"; tail -1 "$W/prescan.log" | tee -a "$OUT/PIPELINE.log"
export NAMES_MAP="$W/names_map.mjs"
step "4/7 stage 2 (renames, Svelte annotations, prettier)"; bash "$HERE/run_transform.sh" "$W/stage1" "$OUT/final" "$W/component_exports.json" "$BUILD" "$W/stats" "$N" > "$W/s2.log" 2>&1; tail -1 "$W/s2.log" | grep -q "TRANSFORM OK" || fail "run_transform (see $W/s2.log)"
step "5/7 fallback to original code for flagged files"; if [ -s "$W/fallback.txt" ]; then bash "$HERE/apply_fallback.sh" "$BUILD" "$OUT/final" "$W/fallback.txt" "$W/component_exports.json" "$N" > "$W/fb.log" 2>&1 || fail "apply_fallback (see $W/fb.log)"; fi
step "5b/7 route comments on nodes (comments only)"; node "$HERE/annotate_routes.mjs" "$OUT/final" > "$W/annotate.log" 2>&1 || echo "NOTE: annotate_routes failed (see $W/annotate.log); continuing without route comments" | tee -a "$OUT/PIPELINE.log"
res=FAIL
for round in 1 2 3; do
  step "6/7 verification round $round"; rm -rf "$W/verify"; bash "$HERE/verify_all.sh" "$BUILD" "$W/stage1" "$OUT/final" "$W/fallback.txt" "$W/verify" > "$W/v$round.log" 2>&1 && { res=PASS; break; }
  grep -q "^FAIL runtime_cmp" "$W/verify/VERIFY_SUMMARY.txt" && ! grep -q "^FAIL verify_pair\|^FAIL ast_equiv" "$W/verify/VERIFY_SUMMARY.txt" || fail "verification failed in a check that fallback cannot fix (see $W/verify/VERIFY_SUMMARY.txt)"
  node "$HERE/rt_report.mjs" "$BUILD" "$W/verify"/rt_*.json --culprits > "$W/culprits_$round.txt" 2>/dev/null; [ -s "$W/culprits_$round.txt" ] || fail "runtime differences without identifiable culprit (see $W/verify/rt_report.txt)"
  echo "round $round: moving to fallback: $(tr '\n' ' ' < "$W/culprits_$round.txt")" | tee -a "$OUT/PIPELINE.log"
  bash "$HERE/apply_fallback.sh" "$BUILD" "$OUT/final" "$W/culprits_$round.txt" "$W/component_exports.json" "$N" > "$W/fb_$round.log" 2>&1 || fail "apply_fallback round $round"
  node "$HERE/annotate_routes.mjs" "$OUT/final" >> "$W/annotate.log" 2>&1 || true   # a rebuilt node loses its comment
  cat "$W/culprits_$round.txt" >> "$W/fallback.txt"; sort -u "$W/fallback.txt" -o "$W/fallback.txt"
done
[ "$res" = PASS ] || fail "still failing after 3 rounds (see $W/verify/VERIFY_SUMMARY.txt); do NOT present the result as verified"
step "7/7 reports"; node "$HERE/reports.mjs" "$OUT/final" "$W/stats" "$OUT/reports" "$N" > "$W/reports.log" 2>&1 || fail "reports (see $W/reports.log)"
node "$HERE/kit_intel.mjs" "$W/src" "$OUT/reports" > "$W/kit_intel.log" 2>&1 || echo "NOTE: kit_intel failed (see $W/kit_intel.log)" | tee -a "$OUT/PIPELINE.log"   # the decoded self-description (routes, server loads, matchers, hydration global) — read it FIRST
node "$HERE/chunk_index.mjs" "$OUT/final" "$OUT/reports/CHUNK_INDEX.md" "$W/names_map.mjs.roles.json" "$W/component_exports.json" > "$W/chunk_index.log" 2>&1 || echo "NOTE: chunk_index failed (see $W/chunk_index.log)" | tee -a "$OUT/PIPELINE.log"
cp "$W/fallback.txt" "$OUT/FALLBACK_FILES.txt"
{ echo "# Verification - build $(ls "$BUILD"/entry | grep -E '^(start|app)\.' | tr '\n' ' ')"; echo; echo '```'; cat "$W/verify/VERIFY_SUMMARY.txt"; echo '```'; echo
  echo "- Scope: only the $nfiles .js files of entry/, nodes/ and chunks/. Out of scope (not read, not copied, not in final/): ${ignored_top:-nothing}."
  if [ -n "${YFIN_ROUTES:-}" ]; then
    if [ "$(sc MODE)" = "universal" ]; then
  echo "- Universal-backbone scoping (YFIN_ROUTES='@universal'): the implicit root layout (node 0, detected from the kit client chunk) plus the layouts that run on at least 95% of all routes (nodes $(sc BACKBONE_COVERAGE) of $(sc ROUTES) routes), plus the entries and their import closure. NO page nodes were selected: the verification covers ONLY the code that runs on (nearly) every page; the pages themselves and route-specific loaders were neither transformed nor verified. Full list: work/src.selection.json."
    else
  echo "- Route-family scoping (YFIN_ROUTES='${YFIN_ROUTES}'): $(sc ROUTES) matched routes -> $(sc LEAVES) page nodes (a negative leaf = a page WITH a server load); backbone (the shared layouts of the matched routes, plus node 0 when detected as the implicit root layout) nodes $(sc BACKBONE); $(sc SKIPPED) other files of entry/nodes/chunks were NOT processed (not read, not copied). The verification below covers ONLY the selected route family: code that runs only on other routes was neither transformed nor verified. Full list: work/src.selection.json (or work/scope.txt)."
    fi
  fi
  echo "- Files using the ORIGINAL code instead of Wakaru output (flagged by the scanner or by the runtime check): $(wc -l < "$OUT/FALLBACK_FILES.txt") (FALLBACK_FILES.txt)"
  echo "- Names: Svelte runtime / SvelteKit client names come from structural matches with the official source (confidence B); everything else keeps its minified name. See work/map.log."
  echo "- Runtime check: modules loaded in both trees, Svelte components rendered with empty props, and every exported plain function CALLED with a fixed battery of arguments in both trees (see the runtime_cmp line above for the counts)."
  echo "- Limits: not the whole app (no real data, no interaction, no network); functions that only register callbacks or return closures are not exercised inside; Wakaru rewrites of non-flagged files are tested, not proven."; } > "$OUT/VERIFICATION.md"
echo "DONE" > "$ST"; echo "DONE: $OUT/final  $OUT/reports  $OUT/VERIFICATION.md" | tee -a "$OUT/PIPELINE.log"
