# env for every proof38 script that runs in the DAQ env (on the node, in a Slurm step)
cd /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/wt-covbind
export XDG_CACHE_HOME=/sdf/scratch/users/c/cwang31/.cache-agentify UV_CACHE_DIR=/sdf/scratch/users/c/cwang31/.cache-agentify
source ./setup_env_daq.sh >/dev/null 2>&1
source psdaq/psdaq/sim/sim_env.sh
export PYTHONDONTWRITEBYTECODE=1
export Q=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/covbind/p38b
export DAQ_SIM_EVIDENCE=$Q/evidence
hdr() { echo "host=$(hostname) head=$(git rev-parse HEAD) dirty=$(git status --porcelain --untracked-files=no | wc -l) job=$SLURM_JOB_ID step=$SLURM_STEP_ID date=$(date -Is)"; }
