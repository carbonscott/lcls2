#!/bin/bash
# cov.sh <rundir> [<evidence dir> <out>]: daq_sim coverage at this HEAD over <rundir>/ev (or <evidence dir>)
P=$1; E=${2:-$P/ev}; OUT=${3:-$P/cov.txt}
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/proof45/env.sh wt-gpu
hdr coverage
echo "records in $(basename $E): $(ls $E | wc -l)"
timeout -k 5 1500 daq_sim coverage --evidence $E > $OUT 2>&1; echo COVERAGE_EXIT=$?
echo "$(wc -l < $OUT) lines in $(basename $OUT)"
