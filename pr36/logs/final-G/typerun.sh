#!/bin/bash
# usage (inside ONE srun step on the node): typerun.sh <type> <tag> [<fault>] [-- up args...]
# up --detach --det <type>, cycle --events 1000, xtc2_check (and its self-test offset 1, which
# must FAIL), down; then with <fault>: the same with PSDAQ_SIM_ROGUE_FAULT=<fault>, whose cycle
# must fail.  Everything it starts is taken down by 'daq_sim down'.
T=$1; TAG=$2; FAULT=$3; shift 3; [ "$1" = "--" ] && shift
B=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/xpm
source $B/env.sh
echo "host=$(hostname) head=$(git rev-parse --short HEAD) dirty=$(git status --porcelain --untracked-files=no | wc -l) date=$(date -Is) job=$SLURM_JOB_ID step=$SLURM_STEP_ID"
WD=$B/wd-$T-$TAG; rm -rf $WD
echo "== up --det $T $*"
timeout -k 5 300 daq_sim up -w $WD --det $T --detach "$@"; echo UP_EXIT=$?
echo "== cycle"
timeout -k 5 400 daq_sim cycle -w $WD --events 1000; echo CYCLE_EXIT=$?
F=$(ls $WD/data/tst/tstx00001/xtc/tstx00001-r0001-s000-c000.xtc2 2>/dev/null)
SEED=$(python -c "import json,glob;print(hex(json.load(open(glob.glob('$WD/*state*.json')[0]))['seed']))" 2>/dev/null || echo 0x1234)
if [ -n "$F" ]; then
  for a in '' '--self-test-offset 1'; do
    echo "== xtc2_check $F --det $T --seed $SEED $a"
    timeout -k 5 600 python -m psdaq.sim.xtc2_check $F --det $T --seed $SEED $a 2>&1 | grep -v '^Rogue'; echo rc=${PIPESTATUS[0]}
  done
fi
echo "== down"
timeout -k 5 120 daq_sim down -w $WD; echo DOWN_EXIT=$?
if [ -n "$FAULT" ] && [ "$FAULT" != "-" ]; then
  WD=$B/wd-$T-$TAG-fault; rm -rf $WD
  echo "== FAULT up --det $T PSDAQ_SIM_ROGUE_FAULT=$FAULT"
  PSDAQ_SIM_ROGUE_FAULT="$FAULT" timeout -k 5 300 daq_sim up -w $WD --det $T --detach "$@"; echo UP_EXIT=$?
  echo "== FAULT cycle"
  timeout -k 5 400 daq_sim cycle -w $WD --events 1000; echo CYCLE_EXIT=$?
  echo "== FAULT drp log lines naming the fault"
  grep -h -i -E 'fault|verify|illegal|Traceback|Error|abort|signal' $(ls $WD/pmlogs/*/*/*${T}_0*.log 2>/dev/null) 2>/dev/null | grep -v 'Inadequate RTPRIO' | head -20
  echo "== FAULT down"
  timeout -k 5 120 daq_sim down -w $WD; echo DOWN_EXIT=$?
fi
echo TYPERUN_DONE
