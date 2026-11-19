#!/bin/bash
# W13: build one checkout ($1) on the roma node of job 45757390 (no CUDA); run on sdfiana025 under nohup
export ROOT=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/sim-main-sync
export XDG_CACHE_HOME=$ROOT/cache/xdg UV_CACHE_DIR=$ROOT/cache/uv PIP_CACHE_DIR=$ROOT/cache/pip
WT=$1; JOB=45757390; N=sdfrome046
t0=$(date +%s); echo "=== build start $(date -u +%FT%TZ) WT=$WT HEAD $(git -C $WT rev-parse HEAD) dirty $(git -C $WT status --porcelain --untracked-files=no | wc -l) node $N job $JOB"
(cd $WT && source ./setup_env_daq.sh >/dev/null 2>&1 && meson subprojects download lc pfpl sleek; echo SUBPROJ_EXIT=$?)
srun --jobid=$JOB --overlap -w $N --ntasks=1 --cpus-per-task=32 --mem=64G bash -c \
  "cd $WT && source ./setup_env_daq.sh && unset CUDA_ROOT && echo nvcc: \$(command -v nvcc || echo none) && ./build_all.sh -d -j 32; echo BUILD_EXIT=\$?"
rc=$?
echo "SRUN_EXIT=$rc wall $(( $(date +%s)-t0 )) s end $(date -u +%FT%TZ)"
ls -la $WT/install/bin/{drp,teb,control,drp_pva} 2>&1; ls $WT/install/bin/drp_gpu 2>&1
echo "dirty $(git -C $WT status --porcelain --untracked-files=no | wc -l) HEAD $(git -C $WT rev-parse HEAD)"
exit $rc
