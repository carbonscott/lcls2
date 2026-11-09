#!/bin/bash
# The final evidence at wt-xpm HEAD: build, every type's cycle (+ fault run), coverage (and with
# one RUN row's evidence removed), unit tests, hardware path base (wt-cov) vs head.
B=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/xpm
S="srun --jobid=43839059 --overlap --ntasks=1 --cpus-per-task=32 --mem=64G"
TAG=${1:-F}
cd /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/wt-xpm; echo "final at $(git rev-parse HEAD) dirty=$(git status --porcelain --untracked-files=no | wc -l) $(date -Is)"
X='DrpTDet.PcieControl.DevPcie.TDetSemi.Length_0'
W='pv:{prefix}:Top:TriggerEventManager:TriggerEventBuffer[0]:TriggerDelay=0'
if [ "$NOBUILD" != 1 ]; then timeout -k 5 600 $S $B/build.sh > $B/build-$TAG.log 2>&1; tail -2 $B/build-$TAG.log; fi
for TF in "fakecam:$X" "cspad:$X" "epixhremu:$X" "jungfrauemu:$X" "ts:$X" \
          "hrencoder:Root.App.TimingRx.TriggerEventManager.TriggerEventBuffer[0].TriggerDelay" \
          "epixm320:Root.App.TimingRx.TriggerEventManager.TriggerEventBuffer[0].TriggerDelay" "epix100:ePixBoard.ePix100aFPGA.EpixFpgaRegisters.DaqTriggerDelay" "wave8:$W" "wave8he:$W"; do
  T=${TF%%:*}; F=${TF#*:}
  timeout -k 5 1500 $S $B/typerun.sh $T $TAG "$F" > $B/tr-$T-$TAG.log 2>&1
  echo "$T done $(date -Is)"
done
timeout -k 5 1500 $S $B/typerun.sh fakecam $TAG-seg2 - -- --segments 2 > $B/tr-fakecam-$TAG-seg2.log 2>&1; echo "fakecam --segments 2 done $(date -Is)"
timeout -k 5 300 $S $B/onnode.sh bash -c 'echo host=$(hostname) head=$(git rev-parse HEAD) dirty=$(git status --porcelain --untracked-files=no | wc -l); daq_sim coverage; echo COVERAGE_EXIT=$?' > $B/final-coverage-$TAG.log 2>&1
timeout -k 5 300 $S $B/onnode.sh bash -c 'E=/tmp/xpm-ev-$$; mkdir -p $E; cp .daq_sim/evidence/*.json $E/; for f in $(grep -l "det:drp:ts\"" $E/*.json); do echo "removed $(basename $f)"; rm $f; done; daq_sim coverage --evidence $E | grep -E "^det:drp:ts |rows,|claims|^FAIL|^PASS|^  det:drp:ts"; echo COVERAGE_EXIT=${PIPESTATUS[0]}; rm -rf $E' > $B/final-coverage-removed-$TAG.log 2>&1
timeout -k 5 1000 $S $B/pytest.sh > $B/final-pytest-$TAG.log 2>&1
TYPES="fakecam cspad epixhremu jungfrauemu ts hrencoder epixm320 epix100 wave8 wave8he epixhr2x2"
timeout -k 5 600 $S $B/hwpath.sh wt-cov $TYPES > $B/final-hwpath-base-$TAG.log 2>&1
timeout -k 5 600 $S $B/hwpath.sh wt-xpm $TYPES > $B/final-hwpath-head-$TAG.log 2>&1
diff <(tail -n +2 $B/final-hwpath-base-$TAG.log) <(tail -n +2 $B/final-hwpath-head-$TAG.log) > $B/final-hwpath-$TAG.diff; echo "HWPATH_DIFF_EXIT=$?" >> $B/final-hwpath-$TAG.diff
echo FINAL_DONE
