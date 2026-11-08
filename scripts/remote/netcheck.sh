#!/bin/bash
# One cycle; while it is RUNNING, list the established TCP connections of the DAQ's processes.
WD=$1
daq_sim cycle -w $WD --events 1000 > $WD.net-cycle.log 2>&1 & CY=$!
for i in $(seq 1 120); do grep -q 'setState running' $WD.net-cycle.log && break; sleep 0.5; done; sleep 1
PIDS=$(python -c "import json;d=json.load(open('$WD/daq_sim.state.json'));print(' '.join(str(v) for v in d['procs'].values()))")
ss -tnpH state established > $WD.ss.txt
tot=0; off=0
for p in $PIDS; do
  n=$(grep -c "pid=$p," $WD.ss.txt); tot=$((tot+n))
  m=$(grep "pid=$p," $WD.ss.txt | awk '{print $3" "$4}' | grep -v -E '^127\.0\.0\.1:[0-9]+ 127\.0\.0\.1:[0-9]+$' | wc -l); off=$((off+m))
done
echo "while RUNNING: DAQ pids $PIDS: $tot established TCP connections, $off not on loopback"
wait $CY; echo CYCLE_EXIT=$?
grep -E 'simxpm NumL0Acc|TEB_WrtCt|psana2 events|equal|cycle (PASS|FAIL)' $WD.net-cycle.log
