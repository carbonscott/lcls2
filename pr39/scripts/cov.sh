#!/bin/bash
# cov.sh <rundir> [<row>]: daq_sim coverage at this HEAD over <rundir>/ev (inside one srun step).
# With <row>: over a copy of <rundir>/ev without the records that list <row> (<rundir>/ev-no-<x>).
P=$1; ROW=$2
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/proof39/env.sh
echo "on $(hostname), Slurm job $SLURM_JOB_ID step $SLURM_STEP_ID, HEAD $(git rev-parse --short HEAD), local changes $(git status --short --untracked-files=no | wc -l)"
E=$P/ev; OUT=$P/cov.txt
if [ -n "$ROW" ]; then
  E=$P/ev-no-${ROW##*:}; OUT=$P/cov-no-${ROW##*:}.txt; rm -rf $E; mkdir -p $E; cp $P/ev/*.json $E/
  for f in $(grep -l "\"$ROW\"" $E/*.json); do echo "removed $(basename $f) (it lists $ROW)"; rm $f; done
  echo "records: $(ls $P/ev | wc -l) in ev, $(ls $E | wc -l) in $(basename $E)"
fi
timeout -k 5 1500 daq_sim coverage --evidence $E > $OUT 2>&1; echo COVERAGE_EXIT=$?
echo "$(wc -l < $OUT) lines in $(basename $OUT)"
