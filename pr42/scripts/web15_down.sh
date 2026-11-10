#!/bin/bash
# web15_down.sh NAME (on sdfiana025): daq_sim status (simxpm's counters, read on the node), then daq_sim down, in one
# step on sdfada011; then the up step's last lines (it ends, and releases the node lock)
R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2; Q=$R/work/proof15; WD=$Q/web-$1
[ -e $WD ] || { echo "no session $WD"; exit 2; }
timeout -k 5 400 srun --jobid=44016690 --overlap -w sdfada011 -N 1 --ntasks=1 --cpus-per-task=2 --mem=4G bash -c "
  cd $R/wt-final && source ./setup_env_daq.sh >/dev/null 2>&1 && source psdaq/psdaq/sim/sim_env.sh
  echo \"== daq_sim status on \$(hostname) step \$SLURM_STEP_ID\"; daq_sim status -w $WD 2>&1 | grep -iE 'state|NumL0|L0Acc|L1|events|webgui'
  echo '== daq_sim down'; daq_sim down -w $WD; echo DOWN_EXIT=\$?" < /dev/null 2>&1 | grep -vE '^Rogue' | sed "s#$R#\$R#g" | cut -c1-138
for i in $(seq 1 120); do grep -q SESSION_DONE $WD.up.log && break; sleep 1; done
echo "== the up step:"; grep -E 'UP_EXIT|SESSION_DONE' $WD.up.log
