#!/bin/bash
# brk-cov.sh TAG: the three breaks, then coverage over mx-TAG's evidence
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-daq-hardening/pr60/env.sh
TAG=$1
srun --jobid=$JOB --overlap -w $A --ntasks=1 --cpus-per-task=16 --mem=32G bash -c '
  source $ROOT/simenv.sh $WT && W=$P/work/brk-$(date -u +%m%dT%H%M)
  for k in register kill-drp corrupt; do
    daq_sim matrix -w $W --break $k --lock $LOCK --lock-timeout 5400 > $W-$k.log 2>&1
    echo "BREAK $k exit $?: $(grep -E "^MATRIX (PASS|FAIL)" $W-$k.log | tail -1) $(date -u +%FT%TZ)"; grep "^FAILED " $W-$k.log
  done' > $P/work/brk-$TAG.log 2>&1
srun --jobid=$JOB --overlap -w $A --ntasks=1 --cpus-per-task=4 --mem=8G bash -c \
  "source \$ROOT/simenv.sh \$WT && daq_sim coverage --evidence $P/work/mx-$TAG-ev; echo COV_EXIT=\$?" > $P/work/cov-$TAG.log 2>&1
