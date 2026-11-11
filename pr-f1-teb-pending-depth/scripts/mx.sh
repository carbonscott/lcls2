#!/bin/bash
# prf1: modelled on work/sync/mx.sh. mx.sh TAG [extra matrix args...]: the documented full check (RUNBOOK §3p)
# at the immutable build R/builds/cee776d3c, in one step on sdfmilan031: types shared with sdfmilan082,
# the GPU DRP's types on sdfada018 (job 44245342), programs, features a-e, coverage (fresh evidence dir per TAG)
TAG=$1; shift 1
R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-daq-hardening
F=$R/work/prf1
GH=sdfada018; GJ=44245342
cd $R/builds/cee776d3c
export XDG_CACHE_HOME=$R/cache/xdg UV_CACHE_DIR=$R/cache/uv
source ./setup_env_daq.sh >/dev/null 2>&1; source psdaq/psdaq/sim/sim_env.sh
export PYTHONDONTWRITEBYTECODE=1
export DAQ_SIM_EVIDENCE=$F/mx-$TAG-ev; mkdir -p $DAQ_SIM_EVIDENCE
export DAQ_SIM_CUDA_LIB=$R/tools/cuda-12.9/targets/x86_64-linux/lib
export PSDAQ_SIM_WAVE8PVS_ENV=/sdf/group/lcls/ds/ana/sw/conda2/inst/envs/ps-4.5.16
export PSDAQ_SIM_WAVE8PVS_SRC=/sdf/group/lcls/ds/ana/sw/source_files/wave8-1.0.1.tar.gz
export PSDAQ_SIM_PYTHONPATH_tt='$SUBMODULEDIR/lcls2-pgp-pcie-apps/firmware/submodules/surf/python'
H='$SUBMODULEDIR/lcls2-epix-hr-pcie/firmware'; E='$SUBMODULEDIR/epix-hr-single-10k'
export PSDAQ_SIM_PYTHONPATH_epixhr2x2="$H/python:$H/submodules/surf/python:$H/submodules/axi-pcie-core/python:$H/submodules/lcls2-pgp-fw-lib/python:$H/submodules/lcls-timing-core/python:$H/submodules/l2si-core/python:$E/firmware/python:$E/software/scripts:$E/firmware/submodules/epix-hr-core/python"
unset PSDAQ_SIM_PYTHONPATH
AMI=/sdf/group/lcls/ds/ana/sw/conda2/rel/ami_091526
echo "=== matrix $TAG on $(hostname) job $SLURM_JOB_ID step $SLURM_STEP_ID builds/cee776d3c HEAD $(git --no-optional-locks rev-parse --short HEAD) dirty $(git --no-optional-locks status --porcelain --untracked-files=no | wc -l) gpu $GH job $GJ $(date -u +%FT%TZ)"
daq_sim matrix -w $F/mx-$TAG --hosts sdfmilan031,sdfmilan082 \
  --locks /tmp/sdh-daq-milan031.lock,/tmp/sdh-daq-milan082.lock \
  --gpu-host $GH --gpu-job $GJ --gpu-gres gpu:l40s:1 --gpu-lock /tmp/sdh-daq-ada018.lock \
  --ami-src $AMI --evidence $DAQ_SIM_EVIDENCE --lock-timeout 5400 "$@"
echo "MATRIX_EXIT=$? $(date -u +%FT%TZ)"
