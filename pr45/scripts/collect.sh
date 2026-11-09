#!/bin/bash
# collect.sh <rundir> <stage>: the recording's logs, records and outputs, with flat names, for pr-assets/pr45
P=$1; ST=$2
R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2; L=$R/logs/proof45
rm -rf $ST; mkdir -p $ST/logs/earlier $ST/logs/nocuda $ST/hwpath $ST/evidence $ST/evidence-forged $ST/scripts
cp $P/build-*.log $P/setup-*.log $P/pytest.log $ST/logs/ 2>/dev/null
cp $L/rec/build-wt-gpu-r695.log $ST/logs/build-wt-gpu-r695.log; cp $L/prebuild.log $ST/logs/prebuild.log
cp $P/targets-*.txt $P/commands-*.txt $ST/logs/nocuda/
for f in $P/up-*.log $P/cycle-*.log $P/down-*.log $P/check-*.log; do cp $f $ST/logs/; done
for T in fakecam epixuhremu epixuhrsim; do
  for s in '' -fault; do d=$(ls $P/wd-gpu-$T$s/pmlogs/*/*/*:${T}_0.log 2>/dev/null) && cp $d $ST/logs/drp_gpu-$T$s.log; done
done
for W in wt-gpu-r695 wt-gpu; do cp $(ls $P/wd-695-$W/pmlogs/*/*/*:fakecam_0.log) $ST/logs/drp_gpu-695-$W.log; done
for d in $P/wd-drp-*; do T=${d##*/wd-drp-}; cp $(ls $d/pmlogs/*/*/*:${T}_0.log) $ST/logs/drp-$T.log; done
cp $P/cov.txt $ST/coverage.txt; cp $P/cov-no-gpu-fakecam.txt $ST/coverage-no-gpu-fakecam.txt; cp $P/cov-forged.txt $ST/coverage-forged.txt
cp $P/ev/*.json $ST/evidence/; cp $P/ev-forged/forged-*.json $ST/evidence-forged/
cp $P/hw-*.log $P/hw-diff-*.txt $ST/hwpath/
cp $R/work/gpu1/runs/t2.log $ST/logs/earlier/dev-t2.log; cp $R/work/gpu1/runs/t3.log $ST/logs/earlier/dev-t3.log
cp $L/zerotail-earlier.txt $ST/logs/earlier/
cp $L/*.sh $L/*.py $ST/scripts/; rm -f $ST/scripts/reh*.sh
du -sh $ST; find $ST -type f | wc -l; find $ST -type f -size +5M -exec ls -la {} \;
