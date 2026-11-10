#!/bin/bash
# web15_step.sh WD: in one Slurm step on sdfada011, under its DAQ lock: daq_sim up --webgui at wt-final's HEAD
# (a CPU DAQ: control, teb0, fakecam_0, simxpm; the web GUI on 127.0.0.1:31053), in the foreground until web15_down.sh
WD=$1; R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2
cd $R/wt-final
export XDG_CACHE_HOME=/sdf/scratch/users/c/cwang31/.cache-agentify UV_CACHE_DIR=/sdf/scratch/users/c/cwang31/.cache-agentify
source ./setup_env_daq.sh >/dev/null 2>&1; source psdaq/psdaq/sim/sim_env.sh
export PYTHONDONTWRITEBYTECODE=1
H=$(hostname -s); LOCK=/tmp/agentify-daq-${H#sdf}.lock
exec 9>>$LOCK; flock -w 3000 9 || { echo "lock $LOCK not free"; echo SESSION_DONE; exit 2; }
echo "=== web GUI DAQ on $H, Slurm job $SLURM_JOB_ID step $SLURM_STEP_ID, wt-final HEAD $(git rev-parse --short HEAD), local changes $(git status --porcelain --untracked-files=no | wc -l), lock $LOCK held, $(date -u +%FT%TZ)"
daq_sim up --webgui -w $WD 9>&-
echo "UP_EXIT=$? $(date -u +%FT%TZ)"
flock -u 9
echo SESSION_DONE
