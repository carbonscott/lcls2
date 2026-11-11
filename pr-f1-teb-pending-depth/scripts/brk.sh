#!/bin/bash
# prf1: modelled on work/sync/brk.sh. brk.sh TAG: the matrix's three deliberate breaks at builds/cee776d3c
# on this node under its lock (RUNBOOK §3p): register, kill-drp, corrupt; each must exit 1
TAG=$1
R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-daq-hardening; F=$R/work/prf1
cd $R/builds/cee776d3c
export XDG_CACHE_HOME=$R/cache/xdg UV_CACHE_DIR=$R/cache/uv
source ./setup_env_daq.sh >/dev/null 2>&1; source psdaq/psdaq/sim/sim_env.sh
export PYTHONDONTWRITEBYTECODE=1 DAQ_SIM_EVIDENCE=$F/brk-$TAG-ev
H=$(hostname -s)
echo "=== breaks $TAG on $H job $SLURM_JOB_ID step $SLURM_STEP_ID builds/cee776d3c HEAD $(git --no-optional-locks rev-parse --short HEAD) dirty $(git --no-optional-locks status --porcelain --untracked-files=no | wc -l) $(date -u +%FT%TZ)"
for k in register kill-drp corrupt; do
  daq_sim matrix -w $F/brk-$TAG --break $k --lock /tmp/sdh-daq-${H#sdf}.lock --lock-timeout 5400 > $F/brk-$TAG-$k.log 2>&1
  rc=$?
  echo "BREAK $k exit $rc: $(grep -E '^MATRIX (PASS|FAIL)' $F/brk-$TAG-$k.log | tail -1)"
  grep '^FAILED ' $F/brk-$TAG-$k.log | cut -c1-260
done
echo "=== breaks done $(date -u +%FT%TZ)"
