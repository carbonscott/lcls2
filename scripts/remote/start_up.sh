#!/bin/bash
# On sdfiana025: start `daq_sim up --webgui` in its own Slurm step (runbook section 2), detached.
source /sdf/scratch/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/redo/env.sh
[ -n "$1" ] && [ -n "$2" ] || { echo "usage: start_up.sh <worktree> <run name>"; exit 2; }
TREE=$R/redo/$1; WD=$R/redo/out/$2; mkdir -p $R/redo/out
[ -e $WD ] && { echo "$WD exists: pick a new run name"; exit 2; }
setsid nohup srun --jobid=$JOB --ntasks=1 --cpus-per-task=32 --mem=64G \
  bash -c "cd $TREE && source ./setup_env_daq.sh >/dev/null 2>&1 && daq_sim up --webgui -w $WD" > $WD.up.log 2>&1 < /dev/null &
for i in $(seq 1 180); do grep -qE 'daq_sim: UP\.|Error|error' $WD.up.log 2>/dev/null && break; sleep 1; done
grep -E 'PREFLIGHT|web GUI up|UP\.|webgui +http|Error|error' $WD.up.log | cut -c1-160
