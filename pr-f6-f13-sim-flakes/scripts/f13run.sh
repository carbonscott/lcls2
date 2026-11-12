#!/bin/bash
# f13pr f13run.sh BUILD TAG PROG DET MODE SECS DELAY [matrix args...]: one matrix run (one.sh) with drpwatch.py acting on one DRP
B=$1; TAG=$2; PROG=$3; DET=$4; MODE=$5; SECS=$6; DELAY=$7; shift 7
F=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-daq-hardening/work/f13pr
[ -e $F/$TAG ] && { echo "$TAG exists"; exit 2; }
rm -f $F/$TAG.done
python3 $F/drpwatch.py $F/$TAG/ $PROG $DET $MODE $SECS $DELAY $F/$TAG.done > $F/$TAG.watch 2>&1 & WP=$!
bash $F/one.sh $B $TAG "$@" > $F/$TAG.log 2>&1
touch $F/$TAG.done; wait $WP
echo "$TAG $(tail -1 $F/$TAG.log)"
