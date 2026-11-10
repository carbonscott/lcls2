#!/bin/bash
# pyt.sh MODE [ARGS]: in wt-final, under this node's DAQ lock: 'files F...' pytest of those files; 'old REV MODULE TESTFILE KW'
# the new test on the old code (oldcode.py); 'all' the sim tests + test_walk_guard (as proof15 pyt2.sh)
R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2; T=$R/wt-final; cd $T
H=$(hostname -s); LOCK=/tmp/agentify-daq-${H#sdf}.lock
export XDG_CACHE_HOME=/sdf/scratch/users/c/cwang31/.cache-agentify UV_CACHE_DIR=/sdf/scratch/users/c/cwang31/.cache-agentify
source setup_env_daq.sh >/dev/null 2>&1; source psdaq/psdaq/sim/sim_env.sh
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/sdf/group/lcls/ds/ana/sw/conda2/rel/ami_091526:$PYTHONPATH
exec 9>>$LOCK; flock -w 5400 9 || { echo "lock $LOCK not free"; exit 2; }
echo "pytest on $H job $SLURM_JOB_ID step $SLURM_STEP_ID wt-final HEAD $(git rev-parse --short HEAD) dirty $(git status --porcelain --untracked-files=no | wc -l) $(date -u +%FT%TZ)"
python -c 'import psdaq.sim.coverage as c; print(c.__file__)'
mode=$1; shift
case $mode in
  files) timeout -k 5 2400 python -m pytest -q -p no:cacheprovider "$@" 2>&1 | tail -25; echo PYTEST_EXIT=${PIPESTATUS[0]} $(date -u +%FT%TZ);;
  old) timeout -k 5 600 python $R/work/fix15/oldcode.py "$@" 2>&1 | tail -30; echo OLD_EXIT=${PIPESTATUS[0]};;
  all) timeout -k 5 2400 python -m pytest -q -p no:cacheprovider psdaq/psdaq/tests/test_sim*.py psdaq/psdaq/webgui/tests/test_walk_guard.py 2>&1 | tail -25; echo PYTEST_EXIT=${PIPESTATUS[0]} $(date -u +%FT%TZ);;
esac
