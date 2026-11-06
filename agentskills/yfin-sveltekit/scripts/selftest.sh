#!/usr/bin/env bash
# usage: selftest.sh [--no-browser]
# Proves, on a tiny synthetic build, that every tool of this skill works in THIS environment AND that the verifiers really fail when they
# should (planted bugs). Run it after setup.sh and before trusting any verification result on a real build.
# Exit 0 only if all checks behave as expected. --no-browser skips the Chromium checks (then runtime verification is NOT validated).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FX="$HERE/tests/fixtures"; NOBROWSER=0; [ "${1:-}" = "--no-browser" ] && NOBROWSER=1
T="$(mktemp -d "${TMPDIR:-/tmp}/yfin-selftest.XXXXXX")"; fails=0; total=0
ok()   { total=$((total+1)); echo "  PASS  $*"; }
bad()  { total=$((total+1)); fails=$((fails+1)); echo "  FAIL  $*"; }
expect_ok()   { local d="$1"; shift; if "$@" >"$T/last.log" 2>&1; then ok "$d"; else bad "$d (expected success) :: $(tail -2 "$T/last.log" | tr '\n' ' ')"; fi; }
# expect_fail <exit-code> <description> <command...>: the command must exit with EXACTLY that code (1 = verifier found a problem,
# 2 = usage/guard refusal); any other code (e.g. a crash) is a test failure, so a broken script cannot masquerade as a "caught bug".
expect_fail() { local code="$1" d="$2"; shift 2; "$@" >"$T/last.log" 2>&1; local rc=$?; if [ $rc -eq "$code" ]; then ok "$d"; else bad "$d (expected exit $code, got $rc) :: $(tail -2 "$T/last.log" | tr '\n' ' ')"; fi; }
cd "$HERE"

echo "== 1. Wakaru stage on the fixture (real Wakaru binary)"
expect_ok "wakaru_run.sh processes every file and keeps the tree complete" bash ./wakaru_run.sh "$FX/orig" "$T/wakaru" 2
[ -f "$T/wakaru/yimg/v.js" ] && cmp -s "$FX/orig/yimg/v.js" "$T/wakaru/yimg/v.js" && ok "vendor dir copied verbatim (not rewritten by Wakaru)" || bad "vendor dir was not copied verbatim"

echo "== 2. Hazard scan (original vs hand-written Wakaru stand-in)"
expect_ok "scan_hazards.mjs runs" node scan_hazards.mjs "$FX/orig" "$FX/stage1" "$T/hz.json"
if [ "$(sort "$T/hz.json.list.txt" | tr '\n' ' ')" = "chunks/interop.IIIIIIII.js chunks/jsx.JJJJJJJJ.js chunks/lib.LLLLLLLL.js " ]; then ok "flags exactly interop, jsx and lib (not ok.*, nodes, vendor)"; else bad "unexpected hazard list: $(tr '\n' ' ' < "$T/hz.json.list.txt")"; fi
grep -q 'class-called-without-new' "$T/hz.json" && grep -q 'new-classes' "$T/hz.json" && grep -q '"jsx"' "$T/hz.json" && grep -q 'interop-helper' "$T/hz.json" && ok "reasons reported (new-classes, class-called-without-new, jsx, interop-helper)" || bad "missing hazard reasons"

echo "== 3. Name-map guard + stage 2 transform"
expect_fail 2 "transform refuses a names map from another build (BUILD_ID guard)" env NAMES_MAP="$FX/names_map.mini.mjs" node transform.mjs "$FX/stage1" "$T/guard_out" "$FX/component_exports.json" 0 1 "$T/guard_stats.json" "$FX/roles"
expect_fail 2 "transform refuses to run without NAMES_MAP" node transform.mjs "$FX/stage1" "$T/guard_out2" "$FX/component_exports.json" 0 1 "$T/guard_stats2.json"
expect_ok "run_transform.sh (2 shards) on fixture" env NAMES_MAP="$FX/names_map.mini.mjs" bash ./run_transform.sh "$FX/stage1" "$T/final" "$FX/component_exports.json" "$FX/orig" "$T/stats" 2
grep -q "safe_not_equal" "$T/final/nodes/0.NNNNNNNN.js" && ok "imported alias renamed to its semantic name" || bad "alias not renamed"
grep -q "import { a as safe_not_equal" "$T/final/nodes/0.NNNNNNNN.js" && ok "import specifier (module interface) unchanged" || bad "import specifier changed"
expect_ok "apply_fallback.sh rebuilds flagged files from the ORIGINAL" env NAMES_MAP="$FX/names_map.mini.mjs" bash ./apply_fallback.sh "$FX/orig" "$T/final" "$T/hz.json.list.txt" "$FX/component_exports.json" 1
ls -d "$T/final"_fbsrc.* >/dev/null 2>&1 && bad "apply_fallback left its temp dir next to the output (must be removed on success)" || ok "apply_fallback cleans its temp dir on success"
grep -q "function Foo" "$T/final/chunks/lib.LLLLLLLL.js" && ! grep -q "class Foo" "$T/final/chunks/lib.LLLLLLLL.js" && ok "fallback file comes from the original (function Foo, no class)" || bad "fallback file is not from the original"
expect_ok "reports.mjs extracts routes" node reports.mjs "$T/final" "$T/stats" "$T/rep" 2
grep -q '/about' "$T/rep/ROUTES.md" && ok "ROUTES.md contains the fixture routes" || bad "ROUTES.md incomplete"

echo "== 4. Verification ladder: correct output must PASS"
mkdir -p "$T/work_ok"; cp "$T/hz.json.list.txt" "$T/fallback.txt"
if [ $NOBROWSER = 1 ]; then
  bash ./make_base.sh "$FX/stage1" "$FX/orig" "$T/fallback.txt" "$T/base" >/dev/null
  expect_ok "verify_pair on correct output" node verify_pair.mjs "$FX/orig" "$T/final" "$T/vp.tsv"
  expect_ok "ast_equiv on correct output" node ast_equiv.mjs "$T/base" "$T/final" 0 1 "$T/ast.json"
else
  expect_ok "verify_all.sh passes on correct output (verify_pair + ast_equiv + Chromium runtime)" bash ./verify_all.sh "$FX/orig" "$FX/stage1" "$T/final" "$T/fallback.txt" "$T/work_ok"
  bash ./make_base.sh "$FX/stage1" "$FX/orig" "$T/fallback.txt" "$T/base" >/dev/null
fi

echo "== 5. Planted bugs: every one must be CAUGHT"
# 5a rename bug: a reference ends up pointing at a different binding (what a careless rename causes)
cp -r "$T/final" "$T/bad_capture"; sed -i 's/safe_not_equal(1, 2)/noop(1, 2)/' "$T/bad_capture/nodes/0.NNNNNNNN.js"
grep -q 'noop(1, 2)' "$T/bad_capture/nodes/0.NNNNNNNN.js" || bad "test setup: could not plant the wrong-binding bug"
expect_fail 1 "ast_equiv catches a reference bound to the wrong variable" node ast_equiv.mjs "$T/base" "$T/bad_capture" 0 1 "$T/ast_bad1.json"
# 5b lost string
cp -r "$T/final" "$T/bad_string"; sed -i 's/an ok label string/an ok label/' "$T/bad_string/chunks/ok.OOOOOOOO.js"
expect_fail 1 "verify_pair catches a lost/changed string literal" node verify_pair.mjs "$FX/orig" "$T/bad_string" "$T/vp_bad.tsv"
# 5c changed global
cp -r "$T/final" "$T/bad_global"; echo 'export const g = window;' >> "$T/bad_global/chunks/ok.OOOOOOOO.js"
expect_fail 1 "ast_equiv catches added/changed code (global reference)" node ast_equiv.mjs "$T/base" "$T/bad_global" 0 1 "$T/ast_bad3.json"
# 5d export removed
cp -r "$T/final" "$T/bad_export"; sed -i 's/export const flag/const flag/' "$T/bad_export/chunks/ok.OOOOOOOO.js"
expect_fail 1 "verify_pair catches a removed export" node verify_pair.mjs "$FX/orig" "$T/bad_export" "$T/vp_bad2.tsv"
if [ $NOBROWSER = 0 ]; then
  # 5e Wakaru-style class conversion left in the output (what really happened on the real build)
  cp -r "$T/final" "$T/bad_class"; cp "$FX/stage1/chunks/lib.LLLLLLLL.js" "$T/bad_class/chunks/lib.LLLLLLLL.js"
  expect_fail 1 "runtime_cmp catches function->class conversion that breaks at load" node runtime_cmp.mjs "$FX/orig" "$T/bad_class" "$T/bad_class" "$T/rt_bad.json" 0 1
  node rt_report.mjs "$FX/orig" "$T/rt_bad.json" --culprits 2>/dev/null | grep -q "chunks/lib.LLLLLLLL.js" && ok "rt_report --culprits names the root-cause file" || bad "rt_report --culprits did not name lib"
  # 5e2 semantic change that does NOT show at module load (only calling the function reveals it)
  cp -r "$T/final" "$T/bad_sem"; sed -i -E 's/(const \w+ = \w+) \+ (\w+;)/\1 - \2/' "$T/bad_sem/chunks/ok.OOOOOOOO.js"
  grep -q 'n - e' "$T/bad_sem/chunks/ok.OOOOOOOO.js" || bad "test setup: could not plant the semantic bug"
  expect_fail 1 "runtime_cmp catches a semantic change visible only when the function is CALLED (differential calls)" node runtime_cmp.mjs "$FX/orig" "$T/bad_sem" "$T/bad_sem" "$T/rt_sem.json" 0 1
  expect_ok "(control) the same bug passes the load-time-only comparison, so the calls are what catch it" env YFIN_FUZZ=0 node runtime_cmp.mjs "$FX/orig" "$T/bad_sem" "$T/bad_sem" "$T/rt_sem0.json" 0 1
  # 5f JSX left in the output
  cp -r "$T/final" "$T/bad_jsx"; cp "$FX/stage1/chunks/jsx.JJJJJJJJ.js" "$T/bad_jsx/chunks/jsx.JJJJJJJJ.js"
  expect_fail 1 "runtime_cmp catches JSX that is not executable" node runtime_cmp.mjs "$FX/orig" "$T/bad_jsx" "$T/bad_jsx" "$T/rt_bad2.json" 0 1
else
  echo "  SKIP  Chromium checks (--no-browser): runtime verification is NOT validated in this environment"
fi

echo "== 6. Role detection by code signature (names of chunks/exports change on every build)"
expect_ok "detect_roles.mjs runs on the roles fixture" node detect_roles.mjs "$FX/roles" "$T/roles.json"
node -e 'const r=require(process.argv[1]).roles; const ok=r.init?.chunk==="beta"&&r.init.export==="i"&&r.component_subscribe?.chunk==="alpha"&&r.component_subscribe.export==="q"&&r.safe_not_equal?.chunk==="alpha"&&r.safe_not_equal.export==="s"; process.exit(ok?0:1)' "$T/roles.json" && ok "finds init, component_subscribe, safe_not_equal in the right chunk/export (and not the decoy functions)" || bad "role detection result wrong: $(cat "$T/roles.json" | tr -d '\n' | cut -c1-200)"
expect_ok "make_map.mjs writes a names map with BUILD_ID + ROLES" node make_map.mjs "$FX/roles" "$T/map_roles.mjs" "$T/roles.json" --no-svelte-names
grep -q 'SSSSSSSS' "$T/map_roles.mjs" && grep -q 'PPPPPPPP' "$T/map_roles.mjs" && ok "BUILD_ID read from entry/ file names" || bad "BUILD_ID missing from generated map"

if npm view svelte@4.2.19 version >/dev/null 2>&1; then
  expect_ok "svelte_names.mjs matches a scrambled copy of the Svelte runtime against the official source" node svelte_names.mjs "$FX/svelte_rt" "$T/sn.json"
  node -e 'const sn=require(process.argv[1]).rtfix, tr=require(process.argv[2]); let n=0,bad=0; for(const [k,[name]] of Object.entries(sn)){n++; if(tr[k]!==name)bad++;} process.exit(n>=60&&bad===0?0:1)' "$T/sn.json" "$FX/svelte_rt/truth.json" && ok "every matched name is the true one (and at least 60 matched)" || bad "svelte_names result wrong: $(head -c 200 "$T/sn.json" | tr -d '\n')"
  expect_ok "kit_names.mjs names a SvelteKit-client chunk found through entry/start.*.js" node kit_names.mjs "$FX/kit_fx" "$T/kit.json" 2.8.0
  node -e 'const k=require(process.argv[1]), t=require(process.argv[2]); let ok=0,bad=0; for(const [e,[n]] of Object.entries(k.exports)){ if(n.endsWith(t[e])) ok++; else bad++; } process.exit(ok>=15&&bad===0?0:1)' "$T/kit.json" "$FX/kit_fx/truth.json" && ok "kit_names: every named export is the true source function (>= 15 named)" || bad "kit_names result wrong: $(head -c 200 "$T/kit.json" | tr -d '\n')"
else
  echo "  SKIP  svelte_names check (npm registry not reachable): Svelte runtime auto-naming NOT validated in this environment"
fi
echo "== 7. Scope (entry/nodes/chunks only) and the one-command pipeline (run_auto_pipeline.sh) incl. the runtime-culprit loop"
# a realistic site layout: the build sits in <site>/assets/_app/immutable, next to things that are OUT of scope (other dirs, manifest, credential-like file)
SITE="$T/site/finance.yahoo.com"; IMM="$SITE/assets/_app/immutable"; mkdir -p "$IMM" "$SITE/webcore/js"
cp -r "$FX/orig/entry" "$FX/orig/nodes" "$FX/orig/chunks" "$IMM/"; cp -r "$FX/orig/yimg" "$SITE/yimg"
echo 'throw new Error("out-of-scope file was executed");' > "$SITE/webcore/js/decoy.js"
echo '{"build":{"sessao":"PLACEHOLDER-NOT-A-REAL-CREDENTIAL"}}' > "$SITE/manifest.json"
echo 'PLACEHOLDER-NOT-A-REAL-CREDENTIAL' > "$SITE/session_cookie.txt"
bash ./scope_build.sh "$SITE" "$T/sc_site" > "$T/sc_site.txt" 2>&1; bash ./scope_build.sh "$IMM" "$T/sc_imm" > "$T/sc_imm.txt" 2>&1
[ "$(sed -n 's/^FILES=//p' "$T/sc_site.txt")" = "$(find "$FX/orig/entry" "$FX/orig/nodes" "$FX/orig/chunks" -type f | wc -l)" ] && [ "$(sed -n 's/^ROOT=//p' "$T/sc_site.txt")" = "$IMM" ] && ok "scope_build finds assets/_app/immutable from the site folder and keeps every .js of the 3 folders" || bad "scope_build did not find/copy the build: $(cat "$T/sc_site.txt")"
diff -r "$IMM" "$T/sc_site" >/dev/null 2>&1 && ok "scoped copy is byte-identical to entry/nodes/chunks of the original" || bad "scoped copy differs from the original"
grep -qE "^OUT_OF_SCOPE=.*webcore" "$T/sc_site.txt" && grep -qE "^OUT_OF_SCOPE=.*yimg" "$T/sc_site.txt" && grep -qE "^OUT_OF_SCOPE=.*manifest.json" "$T/sc_site.txt" && [ ! -e "$T/sc_site/yimg" ] && [ ! -e "$T/sc_site/webcore" ] && [ ! -e "$T/sc_site/manifest.json" ] && ok "out-of-scope folders and files are named in the report and not copied" || bad "out-of-scope handling wrong: $(cat "$T/sc_site.txt")"
grep -q "^OUT_OF_SCOPE=$" "$T/sc_imm.txt" && ok "pointing straight at immutable/ works too" || bad "immutable/ itself was not accepted: $(cat "$T/sc_imm.txt")"
mkdir -p "$T/empty" "$T/two/a" "$T/two/b" "$T/partial/entry"; for d in a b; do cp -r "$FX/orig/entry" "$FX/orig/nodes" "$FX/orig/chunks" "$T/two/$d/"; done; cp "$FX/orig/entry/"* "$T/partial/entry/"
expect_fail 1 "scope_build refuses a folder with no SvelteKit build" bash ./scope_build.sh "$T/empty" "$T/sc_x"
grep -q "no SvelteKit build found" "$T/last.log" && ok "...with a clear message" || bad "unclear message: $(cat "$T/last.log")"
expect_fail 1 "scope_build refuses a folder that holds two builds (never guesses)" bash ./scope_build.sh "$T/two" "$T/sc_x"
grep -q "2 builds found" "$T/last.log" && ok "...and lists them" || bad "unclear message: $(cat "$T/last.log")"
expect_fail 1 "scope_build refuses a build without nodes/ and chunks/" bash ./scope_build.sh "$T/partial" "$T/sc_x"
bash ./run_auto_pipeline.sh "$T/empty" "$T/auto_empty" 2 > "$T/auto_empty.log" 2>&1; head -c 6 "$T/auto_empty/STATUS.txt" 2>/dev/null | grep -q FAILED && ok "pipeline stops at step 0 with FAILED on a folder without a build" || bad "pipeline did not fail cleanly on an empty folder"
YFIN_TEST_IGNORE_SCAN=1 YFIN_MAKE_MAP_FLAGS="--no-svelte-names" bash ./run_auto_pipeline.sh "$SITE" "$T/auto" 2 > "$T/auto.log" 2>&1
if [ "$(cat "$T/auto/STATUS.txt" 2>/dev/null)" = "DONE" ]; then ok "pipeline ends DONE on the fixture (site layout, parent folder given)"; else bad "pipeline did not finish: $(tail -3 "$T/auto.log" | tr '\n' ' ')"; fi
[ "$(ls "$T/auto/final" 2>/dev/null | tr '\n' ' ')" = "chunks entry nodes " ] && ok "final/ holds exactly entry, nodes and chunks" || bad "final/ has unexpected content: $(ls "$T/auto/final" | tr '\n' ' ')"
grep -q "out of scope" "$T/auto/PIPELINE.log" && grep -q "Scope: only" "$T/auto/VERIFICATION.md" && grep -q "yimg" "$T/auto/VERIFICATION.md" && ok "scope and the ignored names are reported in PIPELINE.log and VERIFICATION.md" || bad "scope not reported"
grep -q "credential-like files found" "$T/auto/PIPELINE.log" && ! grep -rq "PLACEHOLDER-NOT-A-REAL-CREDENTIAL" "$T/auto" && ! grep -rq "out-of-scope file was executed" "$T/auto" && ok "credential-like file only reported; no out-of-scope content (manifest, decoy) reached the output" || bad "credential/out-of-scope content leaked into the output folder"
grep -q "round 1: moving to fallback" "$T/auto/PIPELINE.log" && grep -q "chunks/lib.LLLLLLLL.js" "$T/auto/work/culprits_1.txt" && ok "scanner ignored on purpose: round 1 failed at runtime and the culprit (lib) moved to fallback" || bad "runtime-culprit loop did not trigger as expected"
grep -q "OVERALL PASS" "$T/auto/VERIFICATION.md" && [ -s "$T/auto/reports/ROUTES.md" ] && ok "final verification PASS, VERIFICATION.md and ROUTES.md written" || bad "pipeline outputs missing"

echo "== 8. Route comments and chunk index"
cp -r "$T/final" "$T/annot"; node annotate_routes.mjs "$T/annot" > "$T/annot.log" 2>&1
grep -rq "^// @routes" "$T/annot/nodes" && grep -rq "page of: /" "$T/annot/nodes" && ok "annotate_routes writes route comments into nodes/*.js" || bad "no route comments written: $(cat "$T/annot.log")"
expect_ok "ast_equiv still equal after the comments (comments never change the code)" node ast_equiv.mjs "$T/base" "$T/annot" 0 1 "$T/ast_annot.json"
node annotate_routes.mjs "$T/annot" 2>&1 | grep -q '"annotated":0' && ok "annotate_routes is idempotent" || bad "annotate_routes not idempotent"
expect_ok "chunk_index.mjs writes the index" node chunk_index.mjs "$T/final" "$T/chunks.md"
grep -q "ok.OOOOOOOO.js" "$T/chunks.md" && ok "CHUNK_INDEX lists the chunks" || bad "chunk index missing rows"

echo "== 9. Route-family scoping (select_routes.mjs / scope_routes.sh / YFIN_ROUTES)"
expect_ok "select_routes.mjs selects the /about family on the fixture" node select_routes.mjs "$FX/orig" "$T/sr" "about"
[ "$(wc -l < "$T/sr.txt")" = "5" ] && grep -q "^chunks/mini_rt.RRRRRRRR.js$" "$T/sr.txt" && grep -q "^nodes/1.MMMMMMMM.js$" "$T/sr.txt" && ok "selection = 2 entries + node 0 (root layout) + node 1 (leaf of /about; negative leaf -2 = page with a server load, node ~(-2)) + mini_rt closure" || bad "unexpected selection: $(tr "\n" " " < "$T/sr.txt")"
node -p 'JSON.parse(require("fs").readFileSync(process.argv[1],"utf8")).backbone.map(b=>b.node).join(",")' "$T/sr.json" | grep -qx "0" && ok "backbone of /about = root layout 0 (derived from the dictionary, not hard-coded)" || bad "backbone wrong: $(head -c 200 "$T/sr.json")"
node -p 'JSON.parse(require("fs").readFileSync(process.argv[1],"utf8")).leaves[0].kind' "$T/sr.json" | grep -qx "server load" && node -p 'JSON.parse(require("fs").readFileSync(process.argv[1],"utf8")).leaves[0].node' "$T/sr.json" | grep -qx "1" && ok "negative leaf (-2) reported as a page WITH a server load, node = ~value = 1 (never Math.abs)" || bad "leaf kind/node wrong"
# the ~N EXPRESSION form (kit's own source writes ~N; the site's minifier folds it to -N-1): same decoding
rm -rf "$T/tilde"; cp -r "$FX/orig" "$T/tilde"
sed 's|"/about": \[-2, \[0\]\]|"/about": [~1, [0]]|' "$FX/orig/entry/app.BBBBBBBB.js" > "$T/tilde/entry/app.BBBBBBBB.js"
expect_ok "select_routes decodes the ~N expression form" node select_routes.mjs "$T/tilde" "$T/td" "about"
grep -q "^nodes/1.MMMMMMMM.js$" "$T/td.txt" && node -p 'JSON.parse(require("fs").readFileSync(process.argv[1],"utf8")).leaves[0].node' "$T/td.json" | grep -qx "1" && ok "~1 (unfolded form of -2) also decodes to node 1 with a server load" || bad "tilde decoding wrong: $(tr "\n" " " < "$T/td.txt")"
# the CURRENT dictionary format: node 0 (root layout) is NEVER listed — the kit client prepends it (layouts:[0,...).
# Detection-based inclusion; frequency alone would silently drop the root layout.
rm -rf "$T/newfmt"; cp -r "$FX/orig" "$T/newfmt"
sed -e 's|"/": \[1, \[0\]\]|"/": [1, []]|' -e 's|"/about": \[-2, \[0\]\]|"/about": [-2, []]|' "$FX/orig/entry/app.BBBBBBBB.js" > "$T/newfmt/entry/app.BBBBBBBB.js"
printf 'import{s as t}from"../chunks/mini_rt.RRRRRRRR.js";export{t as start};\n' > "$T/newfmt/entry/start.AAAAAAAA.js"   # realistic start: imports the kit client chunk
printf '\n/*kit-client marker*/ const decodeTree = { layouts:[0, 1, 2] };\n' >> "$T/newfmt/chunks/mini_rt.RRRRRRRR.js"
expect_ok "select_routes runs on the new-format fixture (root layout implicit, layouts empty)" node select_routes.mjs "$T/newfmt" "$T/nf" "@universal"
node -p 'JSON.parse(require("fs").readFileSync(process.argv[1],"utf8")).implicitRootLayout !== null' "$T/nf.json" | grep -qx "true" && ok "implicit root layout detected from the kit client chunk (layouts:[0, ...)" || bad "implicit root not detected: $(head -c 200 "$T/nf.json")"
grep -q "^nodes/0.NNNNNNNN.js$" "$T/nf.txt" && node -p 'JSON.parse(require("fs").readFileSync(process.argv[1],"utf8")).backbone.map(b=>b.node).join(",")' "$T/nf.json" | grep -qx "0" && ok "@universal includes node 0 although the dictionary never lists it (frequency alone would MISS the root layout)" || bad "node 0 missing on the new format: $(tr "\n" " " < "$T/nf.txt")"
expect_fail 2 "select_routes refuses a filter that matches no route" node select_routes.mjs "$FX/orig" "$T/sr2" "no-such-route"
grep -q "no route in the dictionary" "$T/last.log" && ok "...with a clear message" || bad "unclear message: $(cat "$T/last.log")"
# resilience: renumber the leaf of /about from node 1 to a NEW node 3 — the selection must follow the dictionary, not the numbers.
# The nodes array is DENSE in real builds (nodes[i] is node i — that is how chunk slots resolve), so the fixture adds node 2 too.
rm -rf "$T/rn"; cp -r "$FX/orig" "$T/rn"
printf 'export const d=2;\n' > "$T/rn/nodes/2.YYYYYYYY.js"
printf 'import{a}from"../chunks/ok.OOOOOOOO.js";export const c=1;\n' > "$T/rn/nodes/3.ZZZZZZZZ.js"
sed 's|)=>import("../nodes/1.MMMMMMMM.js")\];|)=>import("../nodes/1.MMMMMMMM.js"),()=>import("../nodes/2.YYYYYYYY.js"),()=>import("../nodes/3.ZZZZZZZZ.js")];|' "$FX/orig/entry/app.BBBBBBBB.js" | sed 's|"/about": \[-2, \[0\]\]|"/about": [3, [0]]|' > "$T/rn/entry/app.BBBBBBBB.js"
expect_ok "select_routes runs on the renumbered fixture" node select_routes.mjs "$T/rn" "$T/rn_sel" "about"
grep -q "^nodes/3.ZZZZZZZZ.js$" "$T/rn_sel.txt" && grep -q "^chunks/ok.OOOOOOOO.js$" "$T/rn_sel.txt" && ! grep -q "^nodes/1.MMMMMMMM.js$" "$T/rn_sel.txt" && ok "renumbered dictionary: node 3 + ok.* selected, old node 1 dropped (follows the dictionary, not the node number)" || bad "renumbering not followed: $(tr "\n" " " < "$T/rn_sel.txt")"
expect_ok "scope_routes.sh end-to-end on the fixture site" bash ./scope_routes.sh "$T/site" "$T/sr_site" "about"
grep -q "^FILES=5$" "$T/last.log" && ok "scope_routes copies exactly the 5 selected files (contract FILES=5)" || bad "FILES contract wrong: $(grep "^FILES=" "$T/last.log")"
grep -q "^SKIPPED=4$" "$T/last.log" && ok "SKIPPED=4 (interop/jsx/lib/ok not read, not copied)" || bad "SKIPPED wrong: $(grep "^SKIPPED=" "$T/last.log")"
diff <(cd "$T/sr_site" && find entry nodes chunks -type f | sort) <(sort "$T/sr_site.selection.txt") >/dev/null 2>&1 && ok "copied tree equals the selection" || bad "copied tree differs from the selection"
rm -rf "$T/miss"; cp -r "$FX/orig" "$T/miss"; rm "$T/miss/chunks/mini_rt.RRRRRRRR.js"
expect_fail 1 "select_routes refuses an incomplete build (selected file missing on disk)" node select_routes.mjs "$T/miss" "$T/miss_sel" "about"
grep -q "missing on disk" "$T/last.log" && ok "...with a clear message" || bad "unclear message: $(cat "$T/last.log")"
rm -rf "$T/esc"; cp -r "$FX/orig" "$T/esc"; printf 'import x from "../../escape.ELSERUNS.js";\n' > "$T/esc/nodes/0.NNNNNNNN.js"
expect_fail 1 "select_routes refuses a static import that leaves entry/nodes/chunks" node select_routes.mjs "$T/esc" "$T/esc_sel" "about"
grep -q "outside entry/nodes/chunks" "$T/last.log" && ok "...with a clear message" || bad "unclear message: $(cat "$T/last.log")"
# full pipeline with YFIN_ROUTES on the fixture: the wiring (env -> scope_routes -> VERIFICATION.md) must hold end to end
YFIN_ROUTES="about" YFIN_TEST_IGNORE_SCAN=1 YFIN_MAKE_MAP_FLAGS="--no-svelte-names" bash ./run_auto_pipeline.sh "$T/site" "$T/auto_route" 2 > "$T/auto_route.log" 2>&1
[ "$(cat "$T/auto_route/STATUS.txt" 2>/dev/null)" = "DONE" ] && ok "YFIN_ROUTES pipeline ends DONE on the fixture" || bad "YFIN_ROUTES pipeline failed: $(tail -3 "$T/auto_route.log" | tr "\n" " ")"
[ ! -e "$T/auto_route/final/chunks/lib.LLLLLLLL.js" ] && [ ! -e "$T/auto_route/final/chunks/ok.OOOOOOOO.js" ] && [ -e "$T/auto_route/final/chunks/mini_rt.RRRRRRRR.js" ] && ok "final/ holds ONLY the /about family (lib/ok never copied)" || bad "final/ has out-of-family files: $(ls "$T/auto_route/final/chunks" 2>/dev/null | tr "\n" " ")"
grep -q "route scoping: filters='about' mode=family" "$T/auto_route/PIPELINE.log" && grep -q "Route-family scoping (YFIN_ROUTES='about')" "$T/auto_route/VERIFICATION.md" && grep -q "ONLY the selected route family" "$T/auto_route/VERIFICATION.md" && ok "scoping is reported in PIPELINE.log and VERIFICATION.md (honest limits)" || bad "scoping not reported"

echo "== 10. Universal-backbone scoping (@universal)"
expect_ok "select_routes.mjs @universal on the fixture (both routes use layout 0)" node select_routes.mjs "$FX/orig" "$T/uni" "@universal"
[ "$(wc -l < "$T/uni.txt")" = "4" ] && grep -q "^nodes/0.NNNNNNNN.js$" "$T/uni.txt" && ! grep -q "^nodes/1.MMMMMMMM.js$" "$T/uni.txt" && ok "@universal = 2 entries + node 0 (100% of the 2 routes) + mini_rt closure; NO page node (node 1 dropped)" || bad "unexpected universal selection: $(tr "\n" " " < "$T/uni.txt")"
node -p 'JSON.parse(require("fs").readFileSync(process.argv[1],"utf8")).mode' "$T/uni.json" | grep -qx "universal" && ok "mode = universal in the report" || bad "mode wrong: $(head -c 120 "$T/uni.json")"
node -p 'JSON.parse(require("fs").readFileSync(process.argv[1],"utf8")).backbone[0].coveragePct' "$T/uni.json" | grep -qx "100" && ok "backbone coverage reported (100%)" || bad "coverage wrong"
node -p 'JSON.parse(require("fs").readFileSync(process.argv[1],"utf8")).hubChunks.length' "$T/uni.json" | grep -qx "1" && node -p 'JSON.parse(require("fs").readFileSync(process.argv[1],"utf8")).hubChunks[0].inSelection' "$T/uni.json" | grep -qx "true" && ok "hubChunks report present (mini_rt, inSelection=true)" || bad "hubChunks wrong: $(node -p 'JSON.stringify(JSON.parse(require("fs").readFileSync(process.argv[1],"utf8")).hubChunks)' "$T/uni.json")"
# no universal backbone: give /about a different layout -> nothing covers >=95% of routes -> exit 2 with the measured top nodes
rm -rf "$T/nouniv"; cp -r "$FX/orig" "$T/nouniv"
sed 's|"/about": \[-2, \[0\]\]|"/about": [3, [1]]|' "$FX/orig/entry/app.BBBBBBBB.js" > "$T/nouniv/entry/app.BBBBBBBB.js"
expect_fail 2 "@universal refuses a build with no layout on >=95% of the routes" node select_routes.mjs "$T/nouniv" "$T/uni2" "@universal"
grep -q "no universal backbone" "$T/last.log" && grep -q "node 0 1/2" "$T/last.log" && ok "...and reports the measured top nodes (node 0 1/2)" || bad "unclear message: $(cat "$T/last.log")"
expect_ok "scope_routes.sh end-to-end with @universal" bash ./scope_routes.sh "$T/site" "$T/uni_site" "@universal"
grep -q "^MODE=universal$" "$T/last.log" && grep -q "^LEAVES=0$" "$T/last.log" && grep -q "^FILES=4$" "$T/last.log" && ok "scope_routes contract: MODE=universal, LEAVES=0, FILES=4" || bad "contract wrong: $(grep -E '^(MODE|LEAVES|FILES|BACKBONE)' "$T/last.log" | tr "\n" " ")"
# full pipeline with YFIN_ROUTES=@universal on the fixture
YFIN_ROUTES="@universal" YFIN_TEST_IGNORE_SCAN=1 YFIN_MAKE_MAP_FLAGS="--no-svelte-names" bash ./run_auto_pipeline.sh "$T/site" "$T/auto_uni" 2 > "$T/auto_uni.log" 2>&1
[ "$(cat "$T/auto_uni/STATUS.txt" 2>/dev/null)" = "DONE" ] && ok "YFIN_ROUTES=@universal pipeline ends DONE" || bad "universal pipeline failed: $(tail -3 "$T/auto_uni.log" | tr "\n" " ")"
[ ! -e "$T/auto_uni/final/nodes/1.MMMMMMMM.js" ] && [ -e "$T/auto_uni/final/nodes/0.NNNNNNNN.js" ] && ok "final/ holds the universal backbone only (page node 1 never copied)" || bad "final/ wrong: $(ls "$T/auto_uni/final/nodes" 2>/dev/null | tr "\n" " ")"
grep -q "Universal-backbone scoping" "$T/auto_uni/VERIFICATION.md" && grep -q "NO page nodes" "$T/auto_uni/VERIFICATION.md" && ok "VERIFICATION.md states the universal scope and its limits" || bad "universal scope not reported"

echo
if [ $fails -eq 0 ]; then echo "SELFTEST PASS ($total checks)"; rm -rf "$T"; exit 0; else echo "SELFTEST FAIL ($fails of $total checks failed) - logs kept in $T"; exit 1; fi
