#!/bin/bash
# On sdfiana025: web40_session.sh in its own Slurm step on the node, under the node lock (a fresh DAQ, the device
# simulators, the web GUI); returns once the web GUI listens.  web40_readback.sh and web40_down.sh talk to that step
# through files in D.
source /sdf/scratch/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/proof40/penv.sh
NAME=$1; [ -n "$NAME" ] || { echo "usage: web40_up.sh <run name>"; exit 2; }
D=$Q/$NAME; [ -e $D ] && { echo "$D exists: pick a new run name"; exit 2; }
mkdir -p $D
setsid nohup timeout -k 30 7200 srun --jobid=$JOB --overlap --ntasks=1 --cpus-per-task=16 --mem=32G flock -w 5400 /tmp/agentify-daq-milan120.lock bash $Q/web40_session.sh $D > $D/session.log 2>&1 < /dev/null &
for i in $(seq 1 5600); do grep -qE 'SESSION_UP|SESSION_DONE' $D/session.log 2>/dev/null && break; sleep 1; done
cut -c1-150 $D/session.log
