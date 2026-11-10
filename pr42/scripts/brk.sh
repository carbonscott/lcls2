#!/bin/bash
# brk.sh TAG: the matrix's three deliberate breaks at wt-final's HEAD on this node under its lock (RUNBOOK §3p):
# register, kill-drp, corrupt; each must exit 1 naming the failed assertion
TAG=$1
R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2; F=$R/work/proof15
cd $R/wt-final
export XDG_CACHE_HOME=/sdf/scratch/users/c/cwang31/.cache-agentify UV_CACHE_DIR=/sdf/scratch/users/c/cwang31/.cache-agentify
source ./setup_env_daq.sh >/dev/null 2>&1; source psdaq/psdaq/sim/sim_env.sh
export PYTHONDONTWRITEBYTECODE=1 DAQ_SIM_EVIDENCE=$F/brk-$TAG-ev
H=$(hostname -s)
echo "=== breaks $TAG on $H job $SLURM_JOB_ID step $SLURM_STEP_ID wt-final HEAD $(git rev-parse --short HEAD) dirty $(git status --porcelain --untracked-files=no | wc -l) $(date -u +%FT%TZ)"
for k in register kill-drp corrupt; do
  daq_sim matrix -w $F/brk-$TAG --break $k --lock /tmp/agentify-daq-${H#sdf}.lock --lock-timeout 5400 > $F/brk-$TAG-$k.log 2>&1
  rc=$?
  echo "BREAK $k exit $rc: $(grep -E '^MATRIX (PASS|FAIL)' $F/brk-$TAG-$k.log | tail -1)"
  grep '^FAILED ' $F/brk-$TAG-$k.log | cut -c1-260
done
echo "=== breaks done $(date -u +%FT%TZ)"
