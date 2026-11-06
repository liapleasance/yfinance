#!/usr/bin/env bash
# usage: run_transform.sh <srcRoot> <outRoot> <componentExports.json> <buildRoot> <statsDir> [shards=2]
# Stage 2: renames + Svelte annotations + prettier, in N parallel shards. LONG-RUNNING (minutes): launch with nohup ... & and poll
# <statsDir>/log_shard_*.txt; the last line of the run is "TRANSFORM OK" or "TRANSFORM FAILED".
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${1:?usage}"; OUT="${2:?}"; COMP="${3:?}"; BUILD="${4:?}"; STATS="${5:?}"; N="${6:-2}"
mkdir -p "$STATS" "$OUT"; rm -f "$STATS"/stats_shard_*.json
pids=(); for ((i=0;i<N;i++)); do
  node --max-old-space-size=3500 "$HERE/transform.mjs" "$SRC" "$OUT" "$COMP" "$i" "$N" "$STATS/stats_shard_$i.json" "$BUILD" > "$STATS/log_shard_$i.txt" 2>&1 & pids+=($!)
done
rc=0; for p in "${pids[@]}"; do wait "$p" || rc=1; done
node "$HERE/aggregate_stats.mjs" "$STATS" "$N" "$STATS/aggregate.json" || rc=1
if [ $rc -eq 0 ]; then echo "TRANSFORM OK"; else echo "TRANSFORM FAILED (see $STATS/log_shard_*.txt)"; exit 1; fi
