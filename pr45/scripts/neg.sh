#!/bin/bash
# neg.sh <rundir>: the coverage negatives (forge45.py), then daq_sim coverage over each copy
P=$1
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/proof45/env.sh wt-gpu
python $L/forge45.py $P/ev $P | c
for t in no-gpu-fakecam forged; do
  timeout -k 5 1500 daq_sim coverage --evidence $P/ev-$t > $P/cov-$t.txt 2>&1; echo "COVERAGE_EXIT=$? ($t)"
done
