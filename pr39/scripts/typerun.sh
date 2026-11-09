#!/bin/bash
# typerun.sh <type> <rundir> [<fault>]: run inside ONE srun step on the node.  A fresh simulated
# DAQ for <type>: daq_sim up --det <type> --detach, cycle --events 1000, the DRP log lines of the
# type's config code, xtc2_check on the file the cycle names (as written: must PASS; with
# --self-test-offset 1: must FAIL), down.  With <fault>: a second fresh DAQ with
# PSDAQ_SIM_ROGUE_FAULT=<fault>, whose cycle must fail and whose DRP log must name the register;
# down.  Records go to <rundir>/ev; work dirs and full logs stay in <rundir>.
T=$1; P=$2; FAULT=$3
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/proof39/env.sh
export DAQ_SIM_EVIDENCE=$P/ev; mkdir -p $DAQ_SIM_EVIDENCE
c() { cut -c1-138; }
echo "$T on $(hostname), Slurm job $SLURM_JOB_ID step $SLURM_STEP_ID, HEAD $(git rev-parse --short HEAD), local changes $(git status --short --untracked-files=no | wc -l), $(date '+%F %T %Z')"
case $T in
  fakecam|cspad|epixhremu|jungfrauemu|ts)
     PAT='XpmDetector:|XPM remote link id|MemPoolSim: (readout group|ts data)|payload seed|rxready|RxLink locked|link enables|(EpixHRemu|JungfrauEmulator) configure';;
  hrencoder) PAT='config runs against|^hrencoder_(init|connect|config)$|StartRun|delay_clks|link id .* from simxpm|sim payload seed';;
  epixm320)  PAT='config runs against|rxId .* found|link id .* from simxpm|sim payload seed|Init ASIC script|Initialization routine|Triggers sent|config_expert complete';;
  epix100)   PAT='config runs against|FpgaVersion|check clock rate|Loading camera|sim payload seed';;
  wave8|wave8he) PAT='config runs against|_connect returning|sim payload seed|^base ';;
  opal)      PAT='config runs against|^opal_init|UartOpal1000: recvString|^opalid|check clock rate|link id .* from simxpm|sim payload seed|StartRun';;
  piranha4)  PAT='config runs against|^piranha4_init|UartPiranha4: recvString|^model|^serno|check clock rate|link id .* from simxpm|sim payload seed';;
  tb)        PAT='config runs against|Found image|init_feb lane|ConfigLclsTimingV2|RxId|link id .* from simxpm|sim payload seed|TimingBEB';;
  epixquad)  PAT='config runs against|AxiMemMap\(sim|rogue_dev: .*seed|epixquad_(init|connect|config|unconfig)|link id .* from simxpm|sim payload seed|pixel_map|config_expert|EpixQuad';;
esac
W=$P/wd-$T
timeout -k 5 300 daq_sim up -w $W --det $T --detach > $P/up-$T.log 2>&1; echo UP_EXIT=$?
grep -E 'PREFLIGHT|daq_sim: UP\.| frame \(|config DB seeded: tst/BEAM/'$T $P/up-$T.log | c
timeout -k 5 400 daq_sim cycle -w $W --events 1000 > $P/cycle-$T.log 2>&1; echo CYCLE_EXIT=$?
grep -E '^  (simxpm NumL0Acc|TEB_WrtCt|DRP_Damage|psana2 (events|with data|checks)|equal) |evidence |cycle (PASS|FAIL)' $P/cycle-$T.log | c
echo "-- $T DRP log: its config code"
grep -h -E "$PAT" $W/pmlogs/*/*/*:${T}_0.log | awk '!s[$0]++' | head -14 | c
F=$(awk '/^  xtc2 file/{print $3}' $P/cycle-$T.log)
for a in '' '--self-test-offset 1'; do
  echo "== xtc2_check $(basename $F) --det $T --seed 0x1234 $a"
  timeout -k 5 600 python -m psdaq.sim.xtc2_check $F --det $T --seed 0x1234 $a 2>&1 | grep -v -E '^Rogue|^Problem reading dgram|^xtc2_check: /' | head -7 | c
  echo rc=${PIPESTATUS[0]}
done
timeout -k 5 120 daq_sim down -w $W > $P/down-$T.log 2>&1; echo DOWN_EXIT=$?; tail -1 $P/down-$T.log | c
if [ -n "$FAULT" ]; then
  echo "-- $T fault run: PSDAQ_SIM_ROGUE_FAULT='$FAULT'; evidence records before it: $(ls $DAQ_SIM_EVIDENCE | wc -l)"
  W=$P/wd-$T-fault
  PSDAQ_SIM_ROGUE_FAULT="$FAULT" timeout -k 5 300 daq_sim up -w $W --det $T --detach > $P/up-$T-fault.log 2>&1; echo UP_EXIT=$?
  grep -E 'PREFLIGHT' $P/up-$T-fault.log | c
  timeout -k 5 400 daq_sim cycle -w $W --events 1000 > $P/cycle-$T-fault.log 2>&1; echo CYCLE_EXIT=$?
  grep -E 'setState (configured|connected) |\[error\] .* did not respond to (connect|configure)|cycle (PASS|FAIL)' $P/cycle-$T-fault.log | c
  grep -h -o -E 'rogue_dev: FAULT .*|Verify error for block [^ ]*|\*\*\*\* python error|killed by signal [0-9]+' $W/pmlogs/*/*/*:${T}_0.log | sort | uniq -c | c
  timeout -k 5 120 daq_sim down -w $W > $P/down-$T-fault.log 2>&1; echo DOWN_EXIT=$?; tail -1 $P/down-$T-fault.log | c
  echo "evidence records after the fault run: $(ls $DAQ_SIM_EVIDENCE | wc -l)"
fi
echo "TYPERUN_DONE $T $(date '+%T')"
