#!/bin/bash
# build.sh <worktree> 12.9|13.3|none: a fresh build of <worktree> by build_all.sh -f -d -j 12 (-f: it removes
# builddir and install first; the CI's Build step runs -d in a new checkout); with 12.9 or 13.3 that conda-forge
# toolkit is CUDA_ROOT and its nvcc is on PATH (meson builds drpGpu only if it finds nvcc)
W=$1; V=$2
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/proof45/env.sh $W
export UV_NO_CACHE=1
case $V in 12.9|13.3) export CUDA_ROOT=$R/work/gpu1/cuda-$V PATH=$PATH:$R/work/gpu1/cuda-$V/bin;; none) ;; *) echo "bad CUDA $V"; exit 2;; esac
hdr "build (CUDA $V)"
p=$(command -v nvcc); echo "nvcc on PATH: ${p:-none}" | sed "s#$R#\$R#"
LOG=${P:-$L/rec}/build-$W.log
t0=$(date +%s)
./build_all.sh -f -d -j 12 > $LOG 2>&1
rc=$?
echo "BUILD_EXIT=$rc in $(( $(date +%s) - t0 )) s; log $(basename $LOG)"
grep -m1 -E '^Program nvcc found' $LOG | sed "s#$R#\$R#g"; grep -m1 -E '^Cuda compiler for the host machine' $LOG | c
echo "drp: $(ls install/bin/drp 2>&1 | sed 's#.*/install#install#;s/.*cannot access .*: //')   drp_gpu: $(ls install/bin/drp_gpu 2>&1 | sed 's#.*/install#install#;s/.*cannot access .*: //')   GPU libs (install/lib/*_gpu.so): $(ls install/lib | grep -c '_gpu\.so$')"
exit $rc
