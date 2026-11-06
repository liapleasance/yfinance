#!/usr/bin/env bash
# usage: make_base.sh <stage1Root> <origRoot> <fallbackList> <baseOut>
# Builds the "base" tree that ast_equiv.mjs compares the final output against: Wakaru output, except that the fallback files are the original.
set -euo pipefail
S1="$(cd "${1:?usage}" && pwd)"; ORIG="$(cd "${2:?}" && pwd)"; LIST="${3:?}"; BASE="${4:?}"
rm -rf "$BASE"; mkdir -p "$BASE"; (cd "$S1" && tar -cf - .) | (cd "$BASE" && tar -xf -)
while IFS= read -r f; do [ -z "$f" ] && continue; mkdir -p "$BASE/$(dirname "$f")"; cp "$ORIG/$f" "$BASE/$f"; done < "$LIST"
echo "base tree: $BASE"
