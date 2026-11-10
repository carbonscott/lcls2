#!/bin/bash
# build.sh TAG: an incremental build_all.sh -d of wt-final with CUDA 12.9 on PATH (as proof15 buildinc.sh), log work/fix15/build-TAG.log
W=wt-final; R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2
source $R/logs/proof45/env.sh $W
export UV_NO_CACHE=1 CUDA_ROOT=$R/work/gpu1/cuda-12.9 PATH=$PATH:$R/work/gpu1/cuda-12.9/bin
hdr "incremental build (CUDA 12.9)"
t0=$(date +%s)
./build_all.sh -d -j 12 > $R/work/fix15/build-$1.log 2>&1; rc=$?
echo "BUILD_EXIT=$rc in $(( $(date +%s) - t0 )) s"
tail -2 $R/work/fix15/build-$1.log | c
grep -m1 -E "^Program nvcc found" $R/work/fix15/build-$1.log | sed "s#$R#\$R#g"
echo "drp: $(ls install/bin/drp 2>&1 | sed s#.*/install#install#)   drp_gpu: $(ls -la --time-style=+%T install/bin/drp_gpu | awk "{print \$6, \$7}" | sed s#.*/install#install#)   GPU libs: $(ls install/lib | grep -c "_gpu\.so$")"
echo "sim files match the checkout: $(for f in coverage.py simxpm.py matrix.py daq_sim.py; do cmp -s psdaq/psdaq/sim/$f install/lib/python3.9/site-packages/psdaq/sim/$f && echo -n "$f "; done)"
exit $rc
