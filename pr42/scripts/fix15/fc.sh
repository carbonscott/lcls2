#!/bin/bash
# fc.sh N: feature c (the MEB serving AMI) N times at wt-final's HEAD on this node, under its DAQ lock, as the matrix runs
# it (daq_sim feature c -w WD -p 5 --ami-src AMI, then down): a diagnostic of run h2's features/c failure (MEB_EvtCt None)
R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2; F=$R/work/fix15; cd $R/wt-final
export XDG_CACHE_HOME=/sdf/scratch/users/c/cwang31/.cache-agentify UV_CACHE_DIR=/sdf/scratch/users/c/cwang31/.cache-agentify
source ./setup_env_daq.sh >/dev/null 2>&1; source psdaq/psdaq/sim/sim_env.sh
export PYTHONDONTWRITEBYTECODE=1 DAQ_SIM_EVIDENCE=$F/fc-ev
H=$(hostname -s); LOCK=/tmp/agentify-daq-${H#sdf}.lock
exec 9>>$LOCK; flock -w 3600 9 || { echo "lock $LOCK not free"; exit 2; }
echo "=== feature c x$1 on $H job $SLURM_JOB_ID step $SLURM_STEP_ID HEAD $(git rev-parse --short HEAD) dirty $(git status --porcelain --untracked-files=no | wc -l) $(date -u +%FT%TZ)"
for k in $(seq 1 $1); do
  WD=$F/fc-$k
  daq_sim feature c -w $WD -p 5 --ami-src /sdf/group/lcls/ds/ana/sw/conda2/rel/ami_091526 > $F/fc-$k.log 2>&1; rc=$?
  daq_sim down -w $WD > $F/fc-$k.down.log 2>&1; rd=$?
  echo "feature c run $k: exit $rc, down exit $rd ($(tail -1 $F/fc-$k.down.log | cut -c1-60)); $(grep -o "MEB_EvtCt  *[0-9A-Za-z]*" $F/fc-$k.log | head -1); $(grep -o "'MEB_EvtCt': [0-9]*" $F/fc-$k.log | head -1); $(grep -E '^FEATURE c' $F/fc-$k.log | tail -1)"
done
echo "=== done $(date -u +%FT%TZ)"
