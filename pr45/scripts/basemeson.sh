#!/bin/bash
# basemeson.sh <worktree> 12.9|13.3: meson setup as build_all.sh runs it, with that toolkit's nvcc on PATH,
# into a scratch build dir that is removed after: does drpGpu configure at this commit?
W=$1; V=$2
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/proof45/env.sh $W
export CUDA_ROOT=$R/work/gpu1/cuda-$V PATH=$PATH:$R/work/gpu1/cuda-$V/bin LDFLAGS= CXXFLAGS=
hdr "meson setup (CUDA $V)"
B=${P:-$L/rec}/setup-$W-$V
rm -rf $B
meson setup $B -Dconda_prefix=$CONDA_PREFIX -Dprefix=$B-inst -Depics_base=$EPICS_BASE -Depics_host_arch=$EPICS_HOST_ARCH \
  -Dpython.bytecompile=-1 -Dbuildtype=debugoptimized -Dbuild_daq=true -Dcustom_cuda_path=$CUDA_ROOT > $B.log 2>&1
echo "SETUP_EXIT=$?"
grep -m1 -E '^Program nvcc found' $B.log | sed "s#$R#\$R#g"; grep -E 'ERROR' $B.log | sed "s#$R/##g" | c
rm -rf $B $B-inst
