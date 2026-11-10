# source env.sh: fix15b's DAQ env of wt-final on the node (as skeptic15b's env.sh)
export R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2
export W=$R/work/fix15b
cd $R/wt-final || exit 2
export XDG_CACHE_HOME=/sdf/scratch/users/c/cwang31/.cache-agentify UV_CACHE_DIR=/sdf/scratch/users/c/cwang31/.cache-agentify
source ./setup_env_daq.sh >/dev/null 2>&1
source psdaq/psdaq/sim/sim_env.sh >/dev/null 2>&1
export PYTHONDONTWRITEBYTECODE=1
export CU12=$R/work/gpu1/cuda-12.9
export DAQ_SIM_CUDA_LIB=$CU12/targets/x86_64-linux/lib
H=$(hostname -s); export LOCK=/tmp/agentify-daq-${H#sdf}.lock
hdr() { echo "=== $1 on $(hostname -s) job $SLURM_JOB_ID step $SLURM_STEP_ID $(basename $PWD) HEAD $(git rev-parse --short HEAD) dirty $(git status --porcelain --untracked-files=no | wc -l) $(date -u +%FT%TZ)"; }
