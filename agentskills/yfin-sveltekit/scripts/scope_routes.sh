#!/usr/bin/env bash
# usage: scope_routes.sh <buildFolder> <scopedDir> [excludeDir] -- <routeFilter...>
#        (the "--" separates the exclude dir from the route filters; filters may also be given without "--" when there is no exclude dir:
#         scope_routes.sh <buildFolder> <scopedDir> <routeFilter...>)
# Route-family / universal scoping: finds the SvelteKit build under <buildFolder> (same rules as scope_build.sh: exactly one
# entry/start.<hash>.js + entry/app.<hash>.js with nodes/ and chunks/ beside it) and copies ONLY the .js/.mjs files that
# RUN on the selected scope: the entries, the shared layouts of the matched routes (the "backbone" that runs on nearly
# every page of the family), the page/redirect nodes of the matched routes (light leaves), their static import closure,
# their __vite__mapDeps preloads and the dynamic imports of everything except app.<hash>.js. Filters: dictionary-key
# substrings ("quote/"), "@universal" (the layouts that run on >=95% of ALL routes, computed by frequency — no page
# leaves), or "*" (whole build). Everything else in entry/nodes/chunks is NOT read and NOT copied (reported as SKIPPED).
# Ground rules unchanged: no manifest, no service worker, no non-JS file, no credential-like file is ever read or copied
# (select_routes.mjs only touches .js/.mjs under the three folders).
# Node numbers are never hard-coded and no "node 0 is the root layout" convention is assumed (in one real build node 0
# wrapped every route; in the next it covered 5 of 205): the backbone is discovered from THIS build's dictionary.
# stdout on success (key=value): ROOT, FILES, ROUTES, BACKBONE, LEAVES, SKIPPED, OUT_OF_SCOPE, NONJS, MAPS, SELECTION_JSON.
# exit 1 + message on stderr when the build is not found / not unique / incomplete / not import-closed; exit 2 on bad usage / no route matches.
set -uo pipefail
usage='usage: scope_routes.sh <buildFolder> <scopedDir> [excludeDir] -- <routeFilter...>'
args=(); for a in "$@"; do args+=("$a"); done
IN="${args[0]:?}"; DEST="${args[1]:?}"; shift 2 2>/dev/null
rest=("$@"); filters=(); EXC="/nonexistent/excluded/path"
# unambiguous forms: <build> <dest> <filter...>  |  <build> <dest> -- <filter...>  |  <build> <dest> <excludeDir> -- <filter...>
if [ ${#rest[@]} -gt 0 ] && [ "${rest[0]}" = "--" ]; then filters=("${rest[@]:1}");
elif [ ${#rest[@]} -gt 1 ] && [ "${rest[1]}" = "--" ]; then EXC="${rest[0]}"; filters=("${rest[@]:2}");
elif [ ${#rest[@]} -gt 0 ]; then filters=("${rest[@]}"); fi
[ ${#filters[@]} -ge 1 ] || { echo "ERROR: no route filter given (e.g. quote/ ; '*' = all routes)" >&2; echo "$usage" >&2; exit 2; }
IN="$(cd "$IN" 2>/dev/null && pwd)" || { echo "ERROR: $IN is not a folder" >&2; exit 1; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
roots=$(find "$IN" -maxdepth 8 -path "$EXC" -prune -o -type f -path '*/entry/start.*.js' -print 2>/dev/null | while IFS= read -r f; do r="$(dirname "$(dirname "$f")")"; ls "$r"/entry/app.*.js >/dev/null 2>&1 && echo "$r"; done | sort -u)
n=$(printf '%s' "$roots" | grep -c .)
[ "$n" -ge 1 ] || { echo "ERROR: no SvelteKit build found under $IN: expected <folder>/entry/start.<hash>.js and entry/app.<hash>.js (normally <site>/assets/_app/immutable)" >&2; exit 1; }
[ "$n" -eq 1 ] || { echo "ERROR: $n builds found under $IN; point to ONE of them: $(printf '%s' "$roots" | tr '\n' ';')" >&2; exit 1; }
ROOT="$roots"
[ -d "$ROOT/nodes" ] && [ -d "$ROOT/chunks" ] || { echo "ERROR: $ROOT has entry/ but no nodes/ and chunks/: not a complete SvelteKit build folder" >&2; exit 1; }
rm -rf "$DEST"; mkdir -p "$DEST"
node "$HERE/select_routes.mjs" "$ROOT" "$DEST.selection" "${filters[@]}" || exit $?
(cd "$ROOT" && tar -cf - -T "$DEST.selection.txt") | tar -xf - -C "$DEST" || { echo "ERROR: could not copy the selected files" >&2; exit 1; }
echo "ROOT=$ROOT"
echo "MODE=$(node -p 'JSON.parse(require("fs").readFileSync(process.argv[1],"utf8")).mode' "$DEST.selection.json")"
echo "FILES=$(find "$DEST" -type f -name '*.js' -o -type f -name '*.mjs' | wc -l)"
echo "ROUTES=$(node -p 'JSON.parse(require("fs").readFileSync(process.argv[1],"utf8")).routesMatched' "$DEST.selection.json")"
echo "BACKBONE=$(node -p 'JSON.parse(require("fs").readFileSync(process.argv[1],"utf8")).backbone.map(b=>b.node).join(",")' "$DEST.selection.json")"
echo "BACKBONE_COVERAGE=$(node -p 'JSON.parse(require("fs").readFileSync(process.argv[1],"utf8")).backbone.map(b=>b.node+":"+b.coveragePct+"%").join(",")' "$DEST.selection.json")"
echo "LEAVES=$(node -p 'JSON.parse(require("fs").readFileSync(process.argv[1],"utf8")).leaves.length' "$DEST.selection.json")"
echo "SKIPPED=$(( $(cd "$ROOT" && find entry nodes chunks -type f \( -name '*.js' -o -name '*.mjs' \) | wc -l) - $(wc -l < "$DEST.selection.txt") ))"
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
echo "SELECTION_JSON=$DEST.selection.json"
