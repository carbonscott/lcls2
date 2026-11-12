#!/bin/bash
# f13pr one.sh BUILD TAG [matrix args...]: one single-node matrix run from builds/BUILD, env as hrun2/mx.sh, under this node's DAQ lock
B=$1; TAG=$2; shift 2
R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-daq-hardening
F=$R/work/f13pr
cd $R/builds/$B
export XDG_CACHE_HOME=$R/cache/xdg UV_CACHE_DIR=$R/cache/uv
source ./setup_env_daq.sh >/dev/null 2>&1; source psdaq/psdaq/sim/sim_env.sh
export PYTHONDONTWRITEBYTECODE=1
export DAQ_SIM_EVIDENCE=$F/$TAG-ev; mkdir -p $DAQ_SIM_EVIDENCE
export DAQ_SIM_CUDA_LIB=$R/tools/cuda-12.9/targets/x86_64-linux/lib
export PSDAQ_SIM_WAVE8PVS_ENV=/sdf/group/lcls/ds/ana/sw/conda2/inst/envs/ps-4.5.16
export PSDAQ_SIM_WAVE8PVS_SRC=/sdf/group/lcls/ds/ana/sw/source_files/wave8-1.0.1.tar.gz
export PSDAQ_SIM_PYTHONPATH_tt='$SUBMODULEDIR/lcls2-pgp-pcie-apps/firmware/submodules/surf/python'
H='$SUBMODULEDIR/lcls2-epix-hr-pcie/firmware'; E='$SUBMODULEDIR/epix-hr-single-10k'
export PSDAQ_SIM_PYTHONPATH_epixhr2x2="$H/python:$H/submodules/surf/python:$H/submodules/axi-pcie-core/python:$H/submodules/lcls2-pgp-fw-lib/python:$H/submodules/lcls-timing-core/python:$H/submodules/l2si-core/python:$E/firmware/python:$E/software/scripts:$E/firmware/submodules/epix-hr-core/python"
unset PSDAQ_SIM_PYTHONPATH
AMI=/sdf/group/lcls/ds/ana/sw/conda2/rel/ami_091526
N=$(hostname -s); N=${N#sdf}
echo "=== $TAG on $(hostname) job $SLURM_JOB_ID step $SLURM_STEP_ID builds/$B HEAD $(git --no-optional-locks rev-parse --short HEAD) dirty $(git --no-optional-locks status --porcelain --untracked-files=no | wc -l) $(date -u +%FT%TZ)"
echo "+ daq_sim matrix -w $F/$TAG --lock /tmp/sdh-daq-$N.lock --ami-src $AMI --evidence $DAQ_SIM_EVIDENCE $*"
T0=$(date +%s)
daq_sim matrix -w $F/$TAG --lock /tmp/sdh-daq-$N.lock --ami-src $AMI --evidence $DAQ_SIM_EVIDENCE "$@"
echo "MATRIX_EXIT=$? $(date -u +%FT%TZ) wall $(( $(date +%s) - T0 )) s"
