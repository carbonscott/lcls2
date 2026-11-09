#!/bin/bash
# faults.sh: in ONE srun step on the node (up --detach lives as long as the step), at wt-beb HEAD:
# the per-sample self-test of take1's wave8 and wave8he files, then a fault run of each:
# the IOC's TriggerDelay PV reads back 0, so wave8_config's own check must fail Configure.
source /sdf/scratch/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/redo/p34b/env.sh
cd $R/wt-beb && source ./setup_env_daq.sh >/dev/null 2>&1 && source psdaq/psdaq/sim/sim_env.sh
P=$Q/take1
echo "host=$(hostname) job=$SLURM_JOB_ID step=$SLURM_STEP_ID head=$(git rev-parse HEAD) local changes=$(git status --short | wc -l) date=$(date -Is)"
for T in wave8 wave8he; do
  F=$P/wd-$T/data/tst/tstx00001/xtc/tstx00001-r0001-s000-c000.xtc2
  for a in '' '--self-test-offset 1'; do
    echo "== xtc2_check $T --seed 0x1234 $a"
    python -m psdaq.sim.xtc2_check $F --det $T --seed 0x1234 $a 2>&1 | grep -v '^Rogue'; echo rc=${PIPESTATUS[0]}
  done
done
for T in wave8 wave8he; do
  W=$P/wd-$T-fault
  echo "== fault run $T: PSDAQ_SIM_ROGUE_FAULT='pv:{prefix}:Top:TriggerEventManager:TriggerEventBuffer[0]:TriggerDelay=0'"
  PSDAQ_SIM_ROGUE_FAULT='pv:{prefix}:Top:TriggerEventManager:TriggerEventBuffer[0]:TriggerDelay=0' daq_sim up -w $W --det $T --detach > $P/up-$T-fault.log 2>&1; echo UP_EXIT=$?
  daq_sim cycle -w $W --events 1000 > $P/cycle-$T-fault.log 2>&1; echo CYCLE_EXIT=$?
  grep -E 'setState|\[error\]|cycle (PASS|FAIL)' $P/cycle-$T-fault.log
  echo "-- the DRP log:"; grep -h -E 'FAULT|TriggerDelay|Error' $W/pmlogs/*/*/*:${T}_0.log | sort | uniq -c | head -8
  daq_sim down -w $W > $P/down-$T-fault.log 2>&1; echo DOWN_EXIT=$?; tail -1 $P/down-$T-fault.log
done
echo "evidence records (fault runs must add none): $(ls $P/ev | wc -l)"
echo "FAULTS_DONE $(date -Is)"
