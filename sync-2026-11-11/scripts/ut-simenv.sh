#!/bin/bash
# ut.sh: every psdaq/psdaq/tests/test_sim*.py (shell glob) at wt-sync HEAD, CI env
R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-daq-hardening
cd $R/wt-sync
source ./setup_env_daq.sh >/dev/null 2>&1
export XDG_CACHE_HOME=$R/cache/xdg UV_CACHE_DIR=$R/cache/uv PYTHONDONTWRITEBYTECODE=1
export PATH=$(pwd)/install/bin:${PATH}
pyver=$(python -V 2>&1 | grep -oP '\d+\.\d+' | head -1)
export PYTHONPATH=$(pwd)/install/lib/python${pyver}/site-packages:${PYTHONPATH}
export QT_QPA_PLATFORM=offscreen; source psdaq/psdaq/sim/sim_env.sh; echo SIM_ENV_SOURCED=$SIM_ENV_SOURCED
files=(psdaq/psdaq/tests/test_sim*.py)
echo "=== ut on $(hostname) job $SLURM_JOB_ID step $SLURM_STEP_ID HEAD $(git rev-parse --short HEAD) $(date -u +%FT%TZ) files ${#files[@]}"
printf '%s\n' "${files[@]}"
t0=$(date +%s)
pytest -rs -p no:cacheprovider "${files[@]}"
echo "PYTEST_EXIT=$? in $(( $(date +%s) - t0 )) s $(date -u +%FT%TZ)"
