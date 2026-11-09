#!/bin/bash
# pytest.sh: the sim unit tests (psdaq/psdaq/tests/test_sim*.py) with the DAQ env, in one srun step
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/proof39/env.sh
echo "on $(hostname), Slurm job $SLURM_JOB_ID step $SLURM_STEP_ID, HEAD $(git rev-parse --short HEAD), local changes $(git status --short --untracked-files=no | wc -l), $(date '+%F %T %Z')"
ls psdaq/psdaq/tests/test_sim*.py | xargs -n1 basename | tr '\n' ' '; echo
timeout -k 5 900 python -m pytest -q -p no:cacheprovider psdaq/psdaq/tests/test_sim*.py 2>&1 | grep -v Warning | tail -3
echo PYTEST_EXIT=${PIPESTATUS[0]}
