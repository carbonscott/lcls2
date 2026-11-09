#!/bin/bash
# gpurun.sh <type> <rundir> [<fault register>]: in ONE srun step that holds a GPU.  A fresh simulated DAQ
# with the GPU DRP: daq_sim up --det <type> --drp drp_gpu --detach, cycle --events 1000, down (under the
# node's DAQ lock); then its drp_gpu log lines and xtc2_check --drp drp_gpu on the file the cycle names
# (as written: must PASS; --self-test-offset 1: must FAIL).  With <fault>: a second fresh DAQ with
# PSDAQ_SIM_ROGUE_FAULT=<fault>, whose cycle must fail and whose drp_gpu log must name the register.
T=$1; P=$2; FAULT=$3
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/proof45/env.sh wt-gpu
export DAQ_SIM_EVIDENCE=$P/ev; mkdir -p $DAQ_SIM_EVIDENCE
hdr "$T (drp_gpu)"
echo "the step's GPU: $(nvidia-smi --query-gpu=index,name,uuid --format=csv,noheader | cut -c1-60)"
W=$P/wd-gpu-$T
( flock -w 5400 9 || { echo "node lock not taken"; exit 3; }
  echo "node lock held from $(date +%T): up, cycle, down"
  timeout -k 5 300 daq_sim up -w $W --det $T --drp drp_gpu --detach > $P/up-gpu-$T.log 2>&1; echo UP_EXIT=$?
  grep -E 'PREFLIGHT|config DB seeded: tst/BEAM/'$T $P/up-gpu-$T.log | sed 's/^[0-9T:.+-]* //' | c
  timeout -k 5 400 daq_sim cycle -w $W --events 1000 > $P/cycle-gpu-$T.log 2>&1; echo CYCLE_EXIT=$?
  grep -E '^  (simxpm NumL0Acc|TEB_WrtCt|DRP_Damage|psana2 (events|with data|checks)|equal) |evidence |cycle (PASS|FAIL)' $P/cycle-gpu-$T.log | sed -E "s/^[0-9T:.+-]{29} //" | c
  timeout -k 5 120 daq_sim down -w $W > $P/down-gpu-$T.log 2>&1; echo DOWN_EXIT=$?; tail -1 $P/down-gpu-$T.log | c
) 9>$LOCK
echo "-- $T drp_gpu log:"
grep -h -E "^# CMDLINE|Simulated PGP device|MemPoolGpu: simulated device|MemPoolSim: simxpm registered|XpmDetector: (xpmdet_config runs|emulated RxId)|Built with CUDA|Final SM resources|timing link is|SimDetector: timing|EpixUHRsim: wrote|payload seed|calibSerNo" $W/pmlogs/*/*/*:${T}_0.log \
  | awk '!s[$0]++' | sed -E 's/^tst-drp_gpu\[[0-9]+\]: //; s#'$P'/##g; s/ -k ep_domain=lo,ep_provider=tcp,/ -k /; s/ -M [^ ]*//' | head -14 | c
F=$(awk '/^  xtc2 file/{print $3}' $P/cycle-gpu-$T.log)
REF=; [ $T = epixuhrsim ] && REF="--ref $W/epixuhrsim-ref.bin"
for a in '' '--self-test-offset 1'; do
  echo "== xtc2_check $(basename $F) --drp drp_gpu --det $T --seed 0x1234 ${REF:+--ref epixuhrsim-ref.bin }$a"
  timeout -k 5 900 python -m psdaq.sim.xtc2_check $F --drp drp_gpu --det $T --seed 0x1234 $REF $a 2>&1 | quiet | grep -v -E '^  problem: event [3-9]' | head -6 | c
  echo rc=${PIPESTATUS[0]}
done
if [ -n "$FAULT" ]; then
  echo "-- $T fault run: PSDAQ_SIM_ROGUE_FAULT='$FAULT'; evidence records before it: $(ls $DAQ_SIM_EVIDENCE | wc -l)"
  W=$P/wd-gpu-$T-fault
  ( flock -w 5400 9 || { echo "node lock not taken"; exit 3; }
    PSDAQ_SIM_ROGUE_FAULT="$FAULT" timeout -k 5 300 daq_sim up -w $W --det $T --drp drp_gpu --detach > $P/up-gpu-$T-fault.log 2>&1; echo UP_EXIT=$?
    timeout -k 5 400 daq_sim cycle -w $W --events 1000 > $P/cycle-gpu-$T-fault.log 2>&1; echo CYCLE_EXIT=$?
    grep -E 'setState (allocated|connected|configured) |\[error\] .* did not respond to (connect|configure)|cycle (PASS|FAIL)' $P/cycle-gpu-$T-fault.log | sed -E 's/^[0-9T:.+-]{29} //' | c
    timeout -k 5 120 daq_sim down -w $W > $P/down-gpu-$T-fault.log 2>&1; echo DOWN_EXIT=$?; tail -1 $P/down-gpu-$T-fault.log | c
  ) 9>$LOCK
  grep -h -o -E 'rogue_dev: FAULT .*|Verify error for block [^ ]*|xpmdet_config.py", line [0-9]+, in [a-z_]+|\*\*\*\* python error|killed by signal [0-9]+' $W/pmlogs/*/*/*:${T}_0.log | sort | uniq -c | c
  echo "evidence records after the fault run: $(ls $DAQ_SIM_EVIDENCE | wc -l)"
fi
echo "GPURUN_DONE $T $(date +%T)"
