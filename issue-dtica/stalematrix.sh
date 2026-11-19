#!/bin/bash
# usage: stalematrix.sh REPS SECS   alternates plain and --keep stalecheck runs; one summary line per run
REPS=$1; SECS=$2; cd /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/dtica-upstream
for i in $(seq $REPS); do
  for mode in plain keep; do
    tag=m$i-$mode; port=$((47400 + 4 * i + (mode == keep ? 0 : 0)))
    [ $mode = keep ] && port=$((port + 2)) && flag=--keep || flag=
    bash stalerun.sh $port $SECS $tag $flag > /dev/null 2>&1
    awk -v t=$tag '$1=="PvIntRow"{ir=$3"/"$2" alive, "$5" upd"} $1=="PvMask"{m=$3"/"$2" alive, "$5" upd"}
         $1=="PvEditCheckList"{e=$3"/"$2} $1=="PvLabel"{l=$3"/"$2} $1=="total"{tot=$3"/"$2}
         END{printf "%-9s PvIntRow %-18s PvMask %-16s PvEditCheckList %-6s PvLabel %-6s total %s\n", t, ir, m, e, l, tot}' runs/stale-$tag.txt
  done
done
