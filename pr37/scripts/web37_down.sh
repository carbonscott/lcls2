#!/bin/bash
# On sdfiana025: stop the session step of web37_up.sh <run name>: web GUI, simulators, then daq_sim down.
source /sdf/scratch/users/c/cwang31/proof37/penv.sh
D=$Q/$1; [ -n "$1" ] && [ -f $D/session.log ] || { echo "no session in $D"; exit 2; }
touch $D/stop
for i in $(seq 1 360); do grep -q SESSION_DONE $D/session.log && break; sleep 1; done
sed -n '/^stopping/,$p' $D/session.log | cut -c1-150
