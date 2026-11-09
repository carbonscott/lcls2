#!/bin/bash
# build_all.sh at the checkout's HEAD, in the DAQ env (one Slurm step)
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/covbind/p38b/env.sh
hdr
time ./build_all.sh -d -j 16
echo BUILD_EXIT=$?
