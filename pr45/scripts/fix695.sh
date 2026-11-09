#!/bin/bash
# fix695.sh <worktree> <rundir>: the same command at any build: daq_sim up --det fakecam --drp drp_gpu,
# cycle --events 1000, down (one GPU step, node lock), then what drp_gpu logged about CUDA errors
W=$1; P=$2
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/proof45/env.sh $W
export DAQ_SIM_EVIDENCE=$P/ev-695-$W; mkdir -p $DAQ_SIM_EVIDENCE
hdr "fakecam (drp_gpu)"
git log -1 --format='  %h %s' | c
grep -n -E '(pedestals|gains)_d\(\) +const override' psdaq/drpGpu/AreaDetector.hh | sed 's/^/  AreaDetector.hh:/' | c
WD=$P/wd-695-$W
( flock -w 5400 9 || { echo "node lock not taken"; exit 3; }
  timeout -k 5 300 daq_sim up -w $WD --det fakecam --drp drp_gpu --detach > $P/up-695-$W.log 2>&1; echo UP_EXIT=$?
  timeout -k 5 400 daq_sim cycle -w $WD --events 1000 > $P/cycle-695-$W.log 2>&1; echo CYCLE_EXIT=$?
  grep -E 'NumL0Acc = |did not respond to|^  (simxpm NumL0Acc|TEB_WrtCt|DRP_Damage|psana2 events|xtc2 file) |cycle (PASS|FAIL)' $P/cycle-695-$W.log | sed -E "s/^[0-9T:.+-]{29} //; s#$P/##" | c
  timeout -k 5 60 daq_sim status -w $WD 2>&1 | grep -E 'NumL0Acc|TEB_WrtCt' | sed -E 's/\{[^}]*\}//; s/ = [A-Z][a-z]{2} [A-Z][a-z]{2} +[0-9]+ [0-9:]+ [0-9]{4} / = /' | sed 's/^/  status: /' | c
  timeout -k 5 120 daq_sim down -w $WD > $P/down-695-$W.log 2>&1; echo DOWN_EXIT=$?; tail -1 $P/down-695-$W.log | c
) 9>$LOCK
D=$(ls $WD/pmlogs/*/*/*:fakecam_0.log)
echo "drp_gpu log: $(grep -c 'cudaError' $D) lines with a cudaError, $(grep -c cudaErrorIllegalAddress $D) of them cudaErrorIllegalAddress:"
grep -E 'Recorder +saw +Enable|cudaError|killed by signal|GPU threads per SM' $D | awk '!s[substr($0,1,60)]++' | sed -E 's/^tst-drp_gpu\[[0-9]+\]: //; s/ @ [0-9.]+ \([0-9a-f]+\)//' | head -5 | c
echo "FIX695_DONE $W $(date +%T)"
