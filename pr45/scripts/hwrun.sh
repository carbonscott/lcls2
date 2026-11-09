#!/bin/bash
# hwrun.sh <rundir> <base wt> <head wt> cuda|nocuda: hwpath.sh from each build (one GPU step, node lock), then the diff
P=$1; B=$2; H=$3; M=$4
L=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/proof45; LOCK=/tmp/agentify-daq-ada013.lock
c() { cut -c1-138; }
( flock -w 5400 9 || { echo "node lock not taken"; exit 3; }
  for w in $B $H; do bash $L/hwpath.sh $w $M $P > $P/hw-$w.log 2>&1; head -1 $P/hw-$w.log; done
) 9>$LOCK
diff <(tail -n +2 $P/hw-$B.log) <(tail -n +2 $P/hw-$H.log) > $P/hw-diff-$M.txt; echo "HWPATH_DIFF_EXIT=$? ($B vs $H; $(wc -l < $P/hw-$H.log) lines each)"

