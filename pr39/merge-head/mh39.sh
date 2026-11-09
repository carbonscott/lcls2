#!/bin/bash
# mh39.sh: merge-head checks for PR #39 at wt-types2 HEAD (pr/types2 + agentify b593f5ea1), one srun step.
# DAQ spans hold the node lock /tmp/agentify-daq-milan048.lock one type at a time.
A=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2; L=$A/logs/proof39; P=$L/mh; rm -rf $P; mkdir -p $P
echo "mh39 on $(hostname) job $SLURM_JOB_ID step $SLURM_STEP_ID start $(date -Is)"
bash $L/build.sh wt-types2 2>&1 | grep -E "host=|BUILD_EXIT"
bash $L/pytest.sh 2>&1 | tail -3
for T in opal piranha4 tb epixquad fakecam cspad epixhremu jungfrauemu ts hrencoder epixm320 epix100 wave8 wave8he; do
  flock -w 5400 /tmp/agentify-daq-milan048.lock bash $L/typerun.sh $T $P > $P/tr-$T.log 2>&1
  echo "$T: $(grep -cE 'cycle PASS' $P/tr-$T.log) cycle-PASS; $(grep -E 'L1Accept|NumL0Acc|events' $P/tr-$T.log | head -2 | tr '\n' ' ' | cut -c1-200); down: $(grep -c 'down: clean' $P/tr-$T.log)"
done
bash $L/cov.sh $P 2>&1 | tail -2; grep -E "rows|RESULT" $P/cov.txt | tail -3
bash $L/cov.sh $P det:drp:tb 2>&1 | tail -2; grep -E "det:drp:tb|rows" $P/cov-no-tb.txt | head -3
echo "MH39_DONE $(date -Is)"
