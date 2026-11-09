#!/bin/bash
# usage (DAQ env, one Slurm step): forge.sh <evidence dir> <out dir>: each forged evidence dir that mutreal.py
# writes goes through 'daq_sim coverage'; the rows the case names must drop, and every other proven row stay.
# (logs/covbind/forge.sh, with the job and step in the header, and a new out dir instead of rm -rf.)
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/covbind/p38b/env.sh
EV=$1; OUT=$2
[ -e "$OUT" ] && { echo "out dir exists: $OUT"; exit 3; }
mkdir -p "$OUT"
hdr
daq_sim coverage --evidence $EV > $OUT/base.out; echo "base exit=$?"
BASE_OK=$(grep -E '^(det|prog):' $OUT/base.out | grep -v -E 'NO VALID|no status entry|UNPROVEN|N/A ' | awk '{print $1}' | sort)
echo "base proven rows: $(echo $BASE_OK | wc -w): $(echo $BASE_OK)"
python $(dirname $0)/mutreal.py $EV $OUT | while read -r _ NAME DROPS DIR; do
  daq_sim coverage --evidence $DIR > $DIR.out; RC=$?
  echo "CASE $NAME (must drop: $DROPS)"
  OK=$(grep -E '^(det|prog):' $DIR.out | grep -v -E 'NO VALID|no status entry|UNPROVEN|N/A ' | awk '{print $1}' | sort)
  DROPPED=$(comm -23 <(echo "$BASE_OK" | tr ' ' '\n' | sort) <(echo "$OK" | tr ' ' '\n' | sort) | tr '\n' ' ')
  for R in ${DROPS//,/ }; do [ "$R" != "-" ] && grep -E "^$R " $DIR.out | sed -E 's#/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/#<root>/#g' | cut -c1-600; done
  grep -E '^[0-9]+ rows,' $DIR.out
  WANT=$(echo ${DROPS//,/ } | tr ' ' '\n' | grep -v '^-$' | sort | tr '\n' ' ')
  echo "RESULT $NAME dropped=[${DROPPED% }] want=[${WANT% }] $([ "$DROPPED" = "$WANT" ] && echo OK || echo MISMATCH) exit=$RC"
done
echo FORGE_DONE
