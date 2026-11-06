#!/usr/bin/env bash
# usage: verify_all.sh <origRoot> <stage1Root> <finalRoot> <fallbackList> <workDir>
# Runs the whole verification ladder and writes <workDir>/VERIFY_SUMMARY.txt (one PASS/FAIL line per check, last line OVERALL PASS|FAIL).
# LONG-RUNNING (~10-20 min on a full build with 2 cores): launch with nohup ... & and poll VERIFY_SUMMARY.txt.
#   1 verify_pair : parses, import/export specifiers identical to the ORIGINAL, no string literal lost            (final vs original)
#   2 ast_equiv   : AST equal except names of bound variables                                                       (final vs base = Wakaru, or original for fallback files)
#   3 runtime_cmp : every module loaded in headless Chromium (network blocked); outcome, export shapes and rendered Svelte
#                   components identical                                                                            (final vs original)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORIG="$(cd "${1:?usage}" && pwd)"; S1="$(cd "${2:?}" && pwd)"; FINAL="$(cd "${3:?}" && pwd)"; LIST="${4:?}"; WORK="${5:?}"
mkdir -p "$WORK"; SUM="$WORK/VERIFY_SUMMARY.txt"; : > "$SUM"; overall=PASS
note() { echo "$*" | tee -a "$SUM"; }
"$HERE/make_base.sh" "$S1" "$ORIG" "$LIST" "$WORK/base" >/dev/null || { note "FAIL make_base"; echo "OVERALL FAIL" >> "$SUM"; exit 1; }
# 1
if node --max-old-space-size=4000 "$HERE/verify_pair.mjs" "$ORIG" "$FINAL" "$WORK/verify_pair.tsv" > "$WORK/verify_pair.log" 2>&1; then note "PASS verify_pair  $(grep -o 'fully_ok: [0-9]*' "$WORK/verify_pair.log")"; else note "FAIL verify_pair  (see $WORK/verify_pair.tsv)"; overall=FAIL; fi
# 2 (2 shards)
for i in 0 1; do node --max-old-space-size=3000 "$HERE/ast_equiv.mjs" "$WORK/base" "$FINAL" $i 2 "$WORK/ast_$i.json" > "$WORK/ast_$i.log" 2>&1 & done; wait
if node -e 'const f=require("fs");let t=0,e=0,d=0,x=0;for(const i of [0,1]){const r=JSON.parse(f.readFileSync(process.argv[1]+"/ast_"+i+".json"));t+=r.total;e+=r.equal;d+=r.differ.length;x+=r.error.length}console.log(`total ${t} equal ${e} differ ${d} error ${x}`);process.exit(d||x||e!==t?1:0)' "$WORK" > "$WORK/ast_total.log" 2>&1; then note "PASS ast_equiv     $(cat "$WORK/ast_total.log")"; else note "FAIL ast_equiv     $(cat "$WORK/ast_total.log") (see $WORK/ast_*.json)"; overall=FAIL; fi
# 3 (2 shards)
for i in 0 1; do node "$HERE/runtime_cmp.mjs" "$ORIG" "$FINAL" "$FINAL" "$WORK/rt_$i.json" $i 2 > "$WORK/rt_$i.log" 2>&1 & done; wait
if [ -f "$WORK/rt_0.json" ] && [ -f "$WORK/rt_1.json" ] && node "$HERE/rt_report.mjs" "$ORIG" "$WORK/rt_0.json" "$WORK/rt_1.json" > "$WORK/rt_report.txt" 2>&1 && ! grep -q '=>' "$WORK/rt_report.txt"; then note "PASS runtime_cmp   $(tail -1 "$WORK/rt_report.txt")"; else note "FAIL runtime_cmp   (see $WORK/rt_report.txt; root causes: node rt_report.mjs $ORIG $WORK/rt_*.json --culprits)"; overall=FAIL; fi
echo "OVERALL $overall" | tee -a "$SUM"; [ "$overall" = PASS ]
