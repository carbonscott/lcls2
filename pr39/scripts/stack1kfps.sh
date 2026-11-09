#!/bin/bash
# stack1kfps.sh <secs>: rogue_drive epixquad1kfps (inside one srun step); after <secs> SIGABRT makes
# python's faulthandler print every thread's stack, showing where epixquad1kfps_init waits.
# Seeds: logs/types2/epixquad1kfps-seeds.json (the card's image name and FpgaVersion).
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/proof39/env.sh
export QT_QPA_PLATFORM=offscreen PYTHONFAULTHANDLER=1
export PSDAQ_SIM_ROGUE_SEEDS=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/types2/epixquad1kfps-seeds.json
echo "host=$(hostname) job=$SLURM_JOB_ID step=$SLURM_STEP_ID head=$(git rev-parse --short HEAD) dirty=$(git status --porcelain --untracked-files=no | wc -l) date=$(date -Is)"
timeout -s ABRT -k 5 ${1:-150} python -B -m psdaq.sim.rogue_drive --type epixquad1kfps 2>&1 | grep -v '^Rogue/pyrogue version\|cannot tell\|^INFO'
echo DRIVE_EXIT=${PIPESTATUS[0]}
