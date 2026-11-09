#!/bin/bash
# usage: build.sh <worktree>: build_all.sh in that worktree with the DAQ env (one srun step)
W=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/$1
cd $W
export XDG_CACHE_HOME=/sdf/scratch/users/c/cwang31/.cache-agentify
export UV_CACHE_DIR=/sdf/scratch/users/c/cwang31/.cache-agentify
source setup_env_daq.sh >/dev/null 2>&1
source psdaq/psdaq/sim/sim_env.sh
export PYTHONDONTWRITEBYTECODE=1
echo "host=$(hostname) wt=$1 head=$(git rev-parse --short HEAD) dirty=$(git status --short --untracked-files=no | wc -l) date=$(date -Is) job=$SLURM_JOB_ID step=$SLURM_STEP_ID"
time ./build_all.sh -d -j 16
echo BUILD_EXIT=$?
date -Is
