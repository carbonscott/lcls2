# source env.sh <worktree>: the DAQ env of that worktree's build, on the node
export R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2
export L=$R/logs/proof45
cd $R/${1:-wt-gpu} || exit 2
export XDG_CACHE_HOME=/sdf/scratch/users/c/cwang31/.cache-agentify UV_CACHE_DIR=/sdf/scratch/users/c/cwang31/.cache-agentify
source ./setup_env_daq.sh >/dev/null 2>&1
source psdaq/psdaq/sim/sim_env.sh >/dev/null 2>&1
export PYTHONDONTWRITEBYTECODE=1
export CU12=$R/work/gpu1/cuda-12.9 CU13=$R/work/gpu1/cuda-13.3
export DAQ_SIM_CUDA_LIB=$CU12/targets/x86_64-linux/lib    # procServ resets LD_LIBRARY_PATH: daq_sim up passes this as drp_gpu's env
LOCK=/tmp/agentify-daq-ada013.lock                        # the node's DAQ lock: held around each up..down (two DAQs on one node would share ports)
c() { cut -c1-138; }
hdr() { echo "$1 on $(hostname), Slurm job $SLURM_JOB_ID step $SLURM_STEP_ID, $(basename $PWD) HEAD $(git rev-parse --short HEAD), local changes $(git status --short --untracked-files=no | wc -l), $(date '+%F %T %Z')"; }
quiet() { grep -v -E '^Rogue|^Problem reading dgram|^xtc2_check: /|shmem: mmap|create_and_attach|^\[sdfada'; }
