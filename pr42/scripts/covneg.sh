#!/bin/bash
# covneg.sh EVDIR ROW: coverage over a copy of EVDIR without the records that list ROW (must exit nonzero naming it),
# and over EVDIR itself (as the matrix ran it), at wt-final's HEAD
EV=$1; ROW=$2
R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2; F=$R/work/proof15
cd $R/wt-final
export XDG_CACHE_HOME=/sdf/scratch/users/c/cwang31/.cache-agentify UV_CACHE_DIR=/sdf/scratch/users/c/cwang31/.cache-agentify
source ./setup_env_daq.sh >/dev/null 2>&1; source psdaq/psdaq/sim/sim_env.sh
export PYTHONDONTWRITEBYTECODE=1
N=$F/covneg-ev; rm -rf $N; cp -a $EV $N
echo "=== coverage negative at wt-final HEAD $(git rev-parse --short HEAD) dirty $(git status --porcelain --untracked-files=no | wc -l): $(ls $EV | wc -l) records in $EV"
for f in $(grep -l "\"$ROW\"" $N/*.json); do echo "removed $(basename $f) (it lists $ROW; rows: $(python -c "import json,sys; print(len(json.load(open(sys.argv[1]))['rows']))" $f))"; rm $f; done
daq_sim coverage --evidence $N > $F/covneg.log 2>&1; rc=$?
echo "COVERAGE without $ROW: exit $rc"
grep -E "^$ROW |FAIL|PASS|rows" $F/covneg.log | head -8 | cut -c1-240
daq_sim coverage --evidence $EV > $F/covpos.log 2>&1; echo "COVERAGE over the matrix's evidence: exit $?"; tail -3 $F/covpos.log | cut -c1-240
