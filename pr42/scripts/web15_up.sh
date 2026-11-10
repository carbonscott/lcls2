#!/bin/bash
# web15_up.sh NAME (on sdfiana025): web15_step.sh in its own Slurm step on sdfada011 (job 44016690), detached; waits for UP
R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2; Q=$R/work/proof15; WD=$Q/web-$1
[ -e $WD ] && { echo "$WD exists: pick a new name"; exit 2; }
setsid nohup srun --jobid=44016690 --overlap -w sdfada011 -N 1 --ntasks=1 --cpus-per-task=16 --mem=32G \
  bash $Q/web15_step.sh $WD > $WD.up.log 2>&1 < /dev/null &
for i in $(seq 1 1500); do grep -qE 'daq_sim: UP\.|SESSION_DONE' $WD.up.log 2>/dev/null && break; sleep 1; done
grep -E '^=== web|PREFLIGHT|web GUI up|UP\.|webgui +http|rror|SESSION_DONE' $WD.up.log | sed "s#$R#\$R#g" | cut -c1-138
grep -q 'daq_sim: UP\.' $WD.up.log && echo SESSION_UP
