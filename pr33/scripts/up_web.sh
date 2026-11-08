#!/bin/bash
# On sdfiana025: in its own Slurm step on the node, `daq_sim up --webgui --segments 2 --detach` in wt-pr34.
# --detach returns once everything is up; srun ends a step's processes when its task exits, so the step
# then waits until `daq_sim down` has run (down_web.sh).
source /sdf/scratch/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/redo/p2/env.sh
[ -n "$1" ] || { echo "usage: up_web.sh <run name>"; exit 2; }
WD=$P/$1; [ -e $WD ] && { echo "$WD exists: pick a new run name"; exit 2; }
CMD="daq_sim up -w $WD --webgui --segments 2 --rate 200 --detach"
echo "+ srun --jobid=$JOB --overlap ... in wt-pr34 ($(git -C $R/wt-pr34 rev-parse HEAD)): $CMD"
setsid nohup srun --jobid=$JOB --overlap --ntasks=1 --cpus-per-task=16 --mem=32G bash -c "
  cd $R/wt-pr34 && source ./setup_env_daq.sh >/dev/null 2>&1 && source psdaq/psdaq/sim/sim_env.sh
  export PYTHONPATH=\$PWD/psdaq:\$PYTHONPATH
  echo \"on \$(hostname), Slurm job \$SLURM_JOB_ID step \$SLURM_STEP_ID\"
  $CMD; echo UP_EXIT=\$?
  while python -c 'import json,sys; sys.exit(json.load(open(sys.argv[1])).get(\"down\") == \"done\")' $WD/daq_sim.state.json 2>/dev/null; do sleep 2; done
  echo 'down seen: step ends'" > $WD.up.log 2>&1 < /dev/null &
for i in $(seq 1 240); do grep -qE 'UP_EXIT=|rror' $WD.up.log 2>/dev/null && break; sleep 1; done
grep -E '^on sdf|PREFLIGHT|web GUI up|UP\.|^  (webgui|control|fakecam)|UP_EXIT|rror' $WD.up.log | cut -c1-170
