#!/bin/bash
# onnode.sh <cmd...>: run <cmd> in the DAQ env of $W (default wt-types2), inside one srun step
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/proof39/env.sh
echo "on $(hostname), Slurm job $SLURM_JOB_ID step $SLURM_STEP_ID, ${W:-wt-types2} HEAD $(git rev-parse --short HEAD), local changes $(git status --short --untracked-files=no | wc -l), $(date '+%F %T %Z')"
eval "$@"
