#!/bin/bash
# f13pr fc.sh SHA: item 2's documented single-node S3DF command (MAINTAINING.md step 8) at H'', from the immutable build,
# env as the doc's simenv.sh (= the full-check script's), campaign lock name. In a step on sdfada016 (job 44243826), no GPU.
R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-daq-hardening; ROOT=$R; SHA=$1
cd $R/builds/$SHA || exit 9
export XDG_CACHE_HOME=$R/cache/xdg UV_CACHE_DIR=$R/cache/uv PYTHONDONTWRITEBYTECODE=1
source ./setup_env_daq.sh >/dev/null 2>&1; source psdaq/psdaq/sim/sim_env.sh
export DAQ_SIM_CUDA_LIB=$R/tools/cuda-12.9/targets/x86_64-linux/lib
unset PSDAQ_SIM_PYTHONPATH
LOCK=/tmp/sdh-daq-ada016.lock
echo "=== $(hostname -s) job $SLURM_JOB_ID step $SLURM_STEP_ID builds/$SHA HEAD $(git rev-parse HEAD) dirty $(git status --porcelain --untracked-files=no | wc -l) $(date -u +%FT%TZ)"
W=$ROOT/work/f13pr/cheap-$(date -u +%m%dT%H%M) && mkdir -p $W-ev && t0=$(date +%s) &&
daq_sim matrix -w $W --only types --types fakecam --lock $LOCK --evidence $W-ev; echo "MATRIX_EXIT=$? in $(( $(date +%s)-t0 )) s $(date -u +%FT%TZ)";
t0=$(date +%s); daq_sim matrix -w $W --break corrupt --lock $LOCK; echo "MATRIX_EXIT=$? in $(( $(date +%s)-t0 )) s $(date -u +%FT%TZ)"
