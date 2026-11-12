#!/bin/bash
# coverage: MAINTAINING.md §10 coverage command (at 8cc9e688c), srun on G=sdfada010, over mx-sms2-ev
export ROOT=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-daq-hardening
export XDG_CACHE_HOME=$ROOT/cache/xdg UV_CACHE_DIR=$ROOT/cache/uv
export WT=$ROOT/wt-sync-2026-11-12 A=sdfmilan151 B=sdfmilan175 G=sdfada010 JOB=44435234 GJOB=44435421 CUDA=$ROOT/tools/cuda-12.9
srun --jobid=44435421 --overlap -w sdfada010 --ntasks=1 --cpus-per-task=4 --mem=8G bash -c \
  'source $ROOT/simenv.sh $WT && daq_sim coverage --evidence $ROOT/work/mx-sms2-ev; echo COV_EXIT=$?' > $ROOT/sms/work/cov-sms2.log 2>&1
