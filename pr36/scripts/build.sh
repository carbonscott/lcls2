#!/bin/bash
# build.sh: build wt-xpm at its HEAD, in one srun step on the node (RUNBOOK.md section 1)
source /sdf/scratch/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/redo/p36/env.sh
cd $R/wt-xpm || exit 2
source ./setup_env_daq.sh >/dev/null 2>&1
echo "host=$(hostname) head=$(git rev-parse HEAD) dirty=$(git status --porcelain --untracked-files=no | wc -l) date=$(date -Is) job=$SLURM_JOB_ID step=$SLURM_STEP_ID"
time ./build_all.sh -d -j 16
echo BUILD_EXIT=$?
date -Is
