# env.sh: the DAQ env of worktree $W (default wt-types2), sourced by every proof39 script that
# runs on the node: setup_env_daq.sh, then the sim isolation env (sim_env.sh).
A=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2
cd $A/${W:-wt-types2}
export XDG_CACHE_HOME=/sdf/scratch/users/c/cwang31/.cache-agentify
export UV_CACHE_DIR=/sdf/scratch/users/c/cwang31/.cache-agentify
source setup_env_daq.sh >/dev/null 2>&1
source psdaq/psdaq/sim/sim_env.sh
export PYTHONDONTWRITEBYTECODE=1
