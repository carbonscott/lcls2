#!/bin/bash
# hwall.sh: the hardware path, base wt-base-t4 (5aaf09617, origin/agentify) vs head wt-final (pr/final), the union of
# the branches' scripts: types4/typesfix hw.sh (every drp type and drp_gpu, a GPU step), hwx.sh, tthw.sh;
# uhrgpu hw.sh (drp_gpu epixuhr3x2 ...); uhr3x2 hwpath.sh (its types); iter11-stack hwpath.sh (the stack's
# programs); the base/head scripts of progtail (tpr::Client), tail2 (lclsBldServer), tail3 (HPS chain, wave8pvs)
# with base and head names replaced.  Run in one GPU step on sdfada013 under its DAQ lock.
R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2; W=$R/work; F=$W/proof15; O=$F/hw; mkdir -p $O
exec 9>>/tmp/agentify-daq-ada013.lock; flock -w 5400 9 || { echo "lock not free"; exit 2; }
echo "=== hwall on $(hostname) job $SLURM_JOB_ID step $SLURM_STEP_ID base $(git -C $R/wt-base-t4 rev-parse --short HEAD) head $(git -C $R/wt-final rev-parse --short HEAD) dirty $(git -C $R/wt-final status --porcelain --untracked-files=no | wc -l) $(date -u +%FT%TZ)"
TYPES3="epixuhr3x2 epixUHR epix100 wave8 wave8he hrencoder epixm320 opal piranha4 tb epixquad epixquad1kfps hsd fakecam epixhr2x2 jungfrau tt"
run2() {  # name script [args]: base and head, diff without the first and last line
  local n=$1 s=$2; shift 2
  timeout -k 5 1800 bash $s wt-base-t4 "$@" > $O/$n-base.log 2>&1 < /dev/null
  timeout -k 5 1800 bash $s wt-final "$@" > $O/$n-head.log 2>&1 < /dev/null
  diff <(sed '1d;$d' $O/$n-base.log) <(sed '1d;$d' $O/$n-head.log) > $O/$n.diff
  echo "$n: DIFF_EXIT=$? ($(wc -l < $O/$n.diff) diff lines; base $(wc -l < $O/$n-base.log) lines, head $(wc -l < $O/$n-head.log))"
}
run2 typesfix-hw $W/typesfix/hw.sh
run2 typesfix-hwx $W/typesfix/hwx.sh
run2 typesfix-tthw $W/typesfix/tthw.sh
run2 uhrgpu-hw $W/uhrgpu/hw.sh
run2 uhr3x2-hwpath $W/uhr3x2/hwpath.sh $TYPES3
run2 stack-hwpath $W/iter11-stack/hwpath.sh
for b in progtail tail2 tail3 tail3_w8; do
  timeout -k 5 1800 bash $F/bh_$b.sh > $O/bh-$b.log 2>&1 < /dev/null; echo "bh_$b: exit $? ($(grep -c 'DIFF_EXIT=0\|: same' $O/bh-$b.log) same, $(grep -c 'DIFF_EXIT=[1-9]\|diff .*: [^s]' $O/bh-$b.log) differ)"
done
flock -u 9
echo "=== hwall done $(date -u +%FT%TZ)"
