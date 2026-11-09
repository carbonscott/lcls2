#!/bin/bash
# On sdfiana025: web37_session.sh in its own Slurm step on the node (a fresh DAQ, the simulators, the web GUI); returns
# once the web GUI listens.  web37_readback.sh and web37_down.sh talk to that step through files in D.
source /sdf/scratch/users/c/cwang31/proof37/penv.sh
NAME=$1; [ -n "$NAME" ] || { echo "usage: web37_up.sh <run name>"; exit 2; }
D=$Q/$NAME; [ -e $D ] && { echo "$D exists: pick a new run name"; exit 2; }
mkdir -p $D
setsid nohup timeout -k 30 7200 srun --jobid=$JOB --overlap --ntasks=1 --cpus-per-task=16 --mem=32G bash $Q/web37_session.sh $D > $D/session.log 2>&1 < /dev/null &
for i in $(seq 1 300); do grep -qE 'SESSION_UP|SESSION_DONE' $D/session.log 2>/dev/null && break; sleep 1; done
cut -c1-150 $D/session.log
