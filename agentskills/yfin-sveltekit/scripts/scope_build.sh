#!/usr/bin/env bash
# usage: scope_build.sh <buildFolder> <scopedDir> [excludeDir]
# Finds the SvelteKit build under <buildFolder> and copies ONLY the .js/.mjs files of its entry/, nodes/ and chunks/ into <scopedDir>.
# <buildFolder> may be the build itself (<site>/assets/_app/immutable) or ANY folder above it; exactly one build must be found
# (a folder that holds entry/start.<hash>.js AND entry/app.<hash>.js). <excludeDir> (optional) is never searched (e.g. the output folder).
# Everything else (other directories, manifest.json, service workers, non-JS files, credential-like files) is out of scope: it is never read or copied.
# stdout on success (key=value): ROOT, FILES, OUT_OF_SCOPE (names only: siblings of entry/nodes/chunks and, if a parent folder was given, its other top-level entries), NONJS (count inside the 3 folders), MAPS (.map count inside the 3 folders)
# exit 1 + message on stderr when no build / more than one build / incomplete build is found.
set -uo pipefail
IN="$(cd "${1:?usage: scope_build.sh <buildFolder> <scopedDir> [excludeDir]}" 2>/dev/null && pwd)" || { echo "ERROR: $1 is not a folder" >&2; exit 1; }
DEST="${2:?usage: scope_build.sh <buildFolder> <scopedDir> [excludeDir]}"; EXC="${3:-/nonexistent/excluded/path}"
roots=$(find "$IN" -maxdepth 8 -path "$EXC" -prune -o -type f -path '*/entry/start.*.js' -print 2>/dev/null | while IFS= read -r f; do r="$(dirname "$(dirname "$f")")"; ls "$r"/entry/app.*.js >/dev/null 2>&1 && echo "$r"; done | sort -u)
n=$(printf '%s' "$roots" | grep -c .)
[ "$n" -ge 1 ] || { echo "ERROR: no SvelteKit build found under $IN: expected <folder>/entry/start.<hash>.js and entry/app.<hash>.js (normally <site>/assets/_app/immutable)" >&2; exit 1; }
[ "$n" -eq 1 ] || { echo "ERROR: $n builds found under $IN; point to ONE of them: $(printf '%s' "$roots" | tr '\n' ';')" >&2; exit 1; }
ROOT="$roots"
[ -d "$ROOT/nodes" ] && [ -d "$ROOT/chunks" ] || { echo "ERROR: $ROOT has entry/ but no nodes/ and chunks/: not a complete SvelteKit build folder" >&2; exit 1; }
rm -rf "$DEST"; mkdir -p "$DEST"
(cd "$ROOT" && find entry nodes chunks -type f \( -name '*.js' -o -name '*.mjs' \) -print0 | tar --null -T - -cf -) | tar -xf - -C "$DEST" || { echo "ERROR: could not copy the files of entry/nodes/chunks" >&2; exit 1; }
echo "ROOT=$ROOT"
echo "FILES=$(find "$DEST" -type f | wc -l)"
# names only: siblings of entry/nodes/chunks inside the build folder + (when a parent folder was given) everything next to the path that leads to it
oos=$(ls -A "$ROOT" | grep -vxE 'entry|nodes|chunks')
rel="${ROOT#"$IN"}"; rel="${rel#/}"
if [ -n "$rel" ]; then
  cur="$IN"; pre=""; IFS=/ read -ra parts <<< "$rel"
  for part in "${parts[@]}"; do
    side=$(ls -A "$cur" | grep -vxF "$part"); [ "$cur" = "$(dirname "$EXC")" ] && side=$(printf '%s\n' "$side" | grep -vxF "$(basename "$EXC")")
    oos=$(printf '%s\n%s\n' "$oos" "$(printf '%s\n' "$side" | grep . | sed "s#^#$pre#")"); cur="$cur/$part"; pre="$pre$part/"
  done
fi
echo "OUT_OF_SCOPE=$(printf '%s\n' "$oos" | grep . | sort | tr '\n' ' ')"
echo "NONJS=$(cd "$ROOT" && find entry nodes chunks -type f ! -name '*.js' ! -name '*.mjs' | wc -l)"
echo "MAPS=$(cd "$ROOT" && find entry nodes chunks -type f -name '*.map' | wc -l)"
