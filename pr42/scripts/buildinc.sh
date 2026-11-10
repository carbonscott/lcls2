#!/bin/bash
# buildinc.sh TREE: an incremental build_all.sh -d of TREE with CUDA 12.9 on PATH (as logs/proof45/build.sh, without -f)
W=$1; R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2
source $R/logs/proof45/env.sh $W
export UV_NO_CACHE=1 CUDA_ROOT=$R/work/gpu1/cuda-12.9 PATH=$PATH:$R/work/gpu1/cuda-12.9/bin
hdr "incremental build (CUDA 12.9)"
./build_all.sh -d -j 12 > $R/work/proof15/buildinc-$W.log 2>&1; echo "BUILD_EXIT=$?"
tail -2 $R/work/proof15/buildinc-$W.log | c
echo "drp_gpu $(ls -la --time-style=+%T install/bin/drp_gpu | awk '{print $6}')  sim files match: $(for f in coverage.py simxpm.py matrix.py daq_sim.py; do cmp -s psdaq/psdaq/sim/$f install/lib/python3.9/site-packages/psdaq/sim/$f && echo -n "$f "; done)"
