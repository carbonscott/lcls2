#!/bin/bash
# pyt2.sh TREE [FILES...]: the sim unit tests and test_walk_guard at TREE (AMI on PYTHONPATH, RUNBOOK), under
# this node's DAQ lock (tests start stand-ins on loopback)
T=$1; shift; cd $T
H=$(hostname -s); LOCK=/tmp/agentify-daq-${H#sdf}.lock
export XDG_CACHE_HOME=/sdf/scratch/users/c/cwang31/.cache-agentify UV_CACHE_DIR=/sdf/scratch/users/c/cwang31/.cache-agentify
source setup_env_daq.sh >/dev/null 2>&1; source psdaq/psdaq/sim/sim_env.sh
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/sdf/group/lcls/ds/ana/sw/conda2/rel/ami_091526:$PYTHONPATH
exec 9>>$LOCK; flock -w 5400 9 || { echo "lock $LOCK not free"; exit 2; }
echo "pytest on $H job $SLURM_JOB_ID step $SLURM_STEP_ID $(basename $T) HEAD $(git rev-parse --short HEAD) dirty $(git status --porcelain --untracked-files=no | wc -l) $(date -u +%FT%TZ)"
python -c 'import psdaq.sim.coverage as c; print(c.__file__)'
F="$@"; [ -z "$F" ] && F="psdaq/psdaq/tests/test_sim*.py psdaq/psdaq/webgui/tests/test_walk_guard.py"
timeout -k 5 2400 python -m pytest -q -p no:cacheprovider $F 2>&1 | tail -25
echo PYTEST_EXIT=${PIPESTATUS[0]} $(date -u +%FT%TZ)
