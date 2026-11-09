#!/bin/bash
# cputypes.sh <rundir> <type>...: in ONE srun step (no GPU), each type on a fresh simulated DAQ with the CPU
# DRP: daq_sim up --det <type> --detach, cycle --events 1000, down (each under the node's DAQ lock); then
# xtc2_check on the file the cycle names (as written: must PASS; --self-test-offset 1: must FAIL)
P=$1; shift
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/proof45/env.sh wt-gpu
export DAQ_SIM_EVIDENCE=$P/ev; mkdir -p $DAQ_SIM_EVIDENCE
hdr "the CPU DRP's types"
for T in "$@"; do
  W=$P/wd-drp-$T
  ( flock -w 5400 9 || { echo "node lock not taken"; exit 3; }
    timeout -k 5 300 daq_sim up -w $W --det $T --detach > $P/up-drp-$T.log 2>&1; echo $? > $P/rc-up-$T
    timeout -k 5 400 daq_sim cycle -w $W --events 1000 > $P/cycle-drp-$T.log 2>&1; echo $? > $P/rc-cycle-$T
    timeout -k 5 120 daq_sim down -w $W > $P/down-drp-$T.log 2>&1; echo $? > $P/rc-down-$T
  ) 9>$LOCK
  v() { awk -v k="$1" 'index($0, "  " k " ") == 1 {print $NF; exit}' $P/cycle-drp-$T.log; }
  ev=$(grep -o -E 'evidence [0-9T]+-cycle-[0-9a-f]+-[0-9]+' $P/cycle-drp-$T.log | awk '{print $2}')
  echo "$T: up $(cat $P/rc-up-$T), cycle $(cat $P/rc-cycle-$T) $(grep -o -E 'cycle (PASS|FAIL)' $P/cycle-drp-$T.log | tail -1 | cut -d' ' -f2), down $(cat $P/rc-down-$T) $(tail -1 $P/down-drp-$T.log | grep -o 'clean'); NumL0Acc $(v 'simxpm NumL0Acc'), TEB_WrtCt $(v TEB_WrtCt), psana2 $(v 'psana2 events'), with data $(v 'psana2 with data'), Damage $(v DRP_Damage)" | c
  F=$(awk '/^  xtc2 file/{print $3}' $P/cycle-drp-$T.log)
  timeout -k 5 900 python -m psdaq.sim.xtc2_check $F --det $T --seed 0x1234 > $P/check-$T.log 2>&1; r1=$?
  timeout -k 5 900 python -m psdaq.sim.xtc2_check $F --det $T --seed 0x1234 --self-test-offset 1 > $P/check-$T-offset.log 2>&1; r2=$?
  echo "   record ${ev:-none}; xtc2_check: $(grep -m1 -E '^  (PASS|FAIL)$' $P/check-$T.log | tr -d ' ') rc=$r1; --self-test-offset 1: $(grep -m1 -E '^  (PASS|FAIL)$' $P/check-$T-offset.log | tr -d ' ') rc=$r2, $(grep -m1 '^  problem: ' $P/check-$T-offset.log | sed 's/^  problem: //')" | c
done
echo "CPUTYPES_DONE $(date +%T)"
