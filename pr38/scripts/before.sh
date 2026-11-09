#!/bin/bash
# the forged dirs of forge.sh under agentify's coverage.py (8830147da, before this PR), at this HEAD (one Slurm step)
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/covbind/p38b/env.sh
hdr
git show 8830147da:psdaq/psdaq/sim/coverage.py > $Q/coverage_8830147da.py
python $Q/before.py $Q/coverage_8830147da.py $PWD $Q/evidence $Q/forged $Q/forge.log; echo BEFORE_EXIT=$?
