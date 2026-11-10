#!/bin/bash
# cov.sh EVDIR LOG: daq_sim coverage over EVDIR at wt-final's HEAD (the installed code), its summary lines
R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2; cd $R/wt-final
export XDG_CACHE_HOME=/sdf/scratch/users/c/cwang31/.cache-agentify UV_CACHE_DIR=/sdf/scratch/users/c/cwang31/.cache-agentify
source ./setup_env_daq.sh >/dev/null 2>&1; source psdaq/psdaq/sim/sim_env.sh
export PYTHONDONTWRITEBYTECODE=1
echo "=== coverage over $(ls $1/*.json | wc -l) records in $1 at wt-final HEAD $(git rev-parse --short HEAD) dirty $(git status --porcelain --untracked-files=no | wc -l) on $(hostname -s) $(date -u +%FT%TZ)"
daq_sim coverage --evidence $1 > $2 2>&1; rc=$?
echo "COVERAGE exit $rc"; grep -E '^[0-9]+ rows|^(PASS|FAIL)' $2 | cut -c1-240; grep -c 'BeginRuns' $2
