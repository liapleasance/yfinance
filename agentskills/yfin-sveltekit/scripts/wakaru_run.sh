#!/usr/bin/env bash
# usage: wakaru_run.sh <origRoot> <outRoot> [jobs=2]
# Stage 1: runs Wakaru (--level standard) on every .js/.mjs of the ORIGINAL build into <outRoot> (same relative paths).
#  - vendor directories (every top-level directory of the build except entry/nodes/chunks/pages/assets/_app/immutable: third-party code) are NOT given to Wakaru: they are copied verbatim (stage 2 only prettifies them),
#    because Wakaru's rewrites broke them in practice (see references/wakaru-hazards.md). Files named *.min.* or *.worker.* (pre-built third-party
#    libraries) are skipped the same way. Override with WAKARU_SKIP_REGEX.
#  - if Wakaru fails or times out on a file, the ORIGINAL is copied instead and the file is listed in <outRoot>/_failures.txt.
# Safe to re-run: existing outputs are overwritten.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SELF="$HERE/wakaru_run.sh"
WK="$HERE/node_modules/@wakaru/cli/bin/wakaru"
SKIP_RE="${WAKARU_SKIP_REGEX:-}"   # default is computed from the build layout below
if [ "${1:-}" = "--one" ]; then   # internal: process a single file
  ORIG="$2"; OUT="$3"; REL="$4"; mkdir -p "$OUT/$(dirname "$REL")"
  if [[ "$REL" =~ $SKIP_RE ]]; then cp "$ORIG/$REL" "$OUT/$REL"; echo "$REL" >> "$OUT/_skipped_vendor.txt"; exit 0; fi
  if timeout 180 "$WK" "$ORIG/$REL" --level standard -o "$OUT/$REL" >/dev/null 2>"$OUT/$REL.err"; then rm -f "$OUT/$REL.err"; else cp "$ORIG/$REL" "$OUT/$REL"; echo "$REL" >> "$OUT/_failures.txt"; fi
  exit 0
fi
ORIG="$(cd "${1:?usage: wakaru_run.sh <origRoot> <outRoot> [jobs]}" && pwd)"; mkdir -p "${2:?}"; OUT="$(cd "$2" && pwd)"; JOBS="${3:-2}"
[ -x "$WK" ] || { echo "ERROR: Wakaru not installed; run setup.sh first" >&2; exit 1; }
rm -f "$OUT/_failures.txt" "$OUT/_skipped_vendor.txt"
if [ -z "$SKIP_RE" ]; then   # default: every top-level directory except SvelteKit's own is third-party code; plus *.min.* / *.worker.* files
  VD=$(cd "$ORIG" && find . -mindepth 1 -maxdepth 1 -type d | sed 's|^\./||' | grep -Ev '^(entry|nodes|chunks|pages|assets|_app|immutable)$' | sed 's/\./\\./g' | paste -sd'|')
  SKIP_RE="${VD:+^($VD)/|}\.min\.|\.worker\."
fi
export WAKARU_SKIP_REGEX="$SKIP_RE"
(cd "$ORIG" && find . -type f \( -name '*.js' -o -name '*.mjs' \) -print0 | sed -z 's|^\./||' | xargs -0 -P "$JOBS" -I{} "$SELF" --one "$ORIG" "$OUT" "{}")
N_IN=$(cd "$ORIG" && find . -type f \( -name '*.js' -o -name '*.mjs' \) | wc -l); N_OUT=$(cd "$OUT" && find . -type f \( -name '*.js' -o -name '*.mjs' \) | wc -l)
echo "input js files: $N_IN   output js files: $N_OUT   vendor-skipped: $( [ -f "$OUT/_skipped_vendor.txt" ] && wc -l < "$OUT/_skipped_vendor.txt" || echo 0 )   wakaru-failed: $( [ -f "$OUT/_failures.txt" ] && wc -l < "$OUT/_failures.txt" || echo 0 )"
[ "$N_IN" = "$N_OUT" ] || { echo "ERROR: file count mismatch" >&2; exit 1; }
