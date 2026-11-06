#!/usr/bin/env bash
# usage: apply_fallback.sh <origRoot> <outRoot> <listFile> <componentExports.json> [shards=2]
# Rebuilds the files named in <listFile> (relative paths, one per line) in <outRoot> from the ORIGINAL (no Wakaru): same stage 2
# (renames + prettier), but starting from the untouched original code. Use for every file flagged by scan_hazards.mjs / runtime_cmp.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORIG="$(cd "${1:?usage}" && pwd)"; OUT="$(cd "${2:?}" && pwd)"; LIST="${3:?}"; COMP="${4:?}"; N="${5:-2}"
TMP="$(mktemp -d "${OUT%/}_fbsrc.XXXXXX")"
while IFS= read -r f; do [ -z "$f" ] && continue
  [ -f "$ORIG/$f" ] || { echo "ERROR: $f not in original build" >&2; exit 1; }
  mkdir -p "$TMP/$(dirname "$f")"; cp "$ORIG/$f" "$TMP/$f"; rm -f "$OUT/$f"
done < "$LIST"
"$HERE/run_transform.sh" "$TMP" "$OUT" "$COMP" "$ORIG" "$TMP/_stats" "$N"; rc=$?
for f in $(cat "$LIST"); do [ -f "$OUT/$f" ] || { echo "ERROR: $f was not rebuilt" >&2; rc=1; }; done
echo "fallback rebuilt: $(grep -c . "$LIST") files from original"
if [ "$rc" -eq 0 ]; then rm -rf "$TMP"; else echo "kept tmp for debugging: $TMP" >&2; fi
exit $rc
