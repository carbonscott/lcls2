#!/bin/bash
cd /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/wt-final
export XDG_CACHE_HOME=/sdf/scratch/users/c/cwang31/.cache-agentify UV_CACHE_DIR=/sdf/scratch/users/c/cwang31/.cache-agentify
source ./setup_env_daq.sh >/dev/null 2>&1; source psdaq/psdaq/sim/sim_env.sh >/dev/null 2>&1
export PYTHONDONTWRITEBYTECODE=1
python /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/work/fix15/brscan.py "$@"
