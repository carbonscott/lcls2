#!/bin/bash
# A cycle that must fail: SIGKILL the DRP once control reports running.
WD=$1
daq_sim cycle -w $WD --events 1000 --timeout 30 > $WD.kill-cycle.log 2>&1 & CY=$!
for i in $(seq 1 120); do grep -q 'setState running' $WD.kill-cycle.log && break; sleep 0.5; done
DRP=$(python -c "import json;print(json.load(open('$WD/daq_sim.state.json'))['procs']['fakecam_0'])")
echo "$(date -Is) kill -9 $DRP (the DRP, fakecam_0)"; kill -9 $DRP
wait $CY; echo CYCLE_EXIT=$?
grep -E '\[error\]|FAIL|final state' $WD.kill-cycle.log | head -8
