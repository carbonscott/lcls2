export ROOT=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-daq-hardening
export WT=${WT_OVERRIDE:-$ROOT/wt-pr60c} CUDA=$ROOT/tools/cuda-12.9 JOB=44815799 GJOB=44815797 A=sdfmilan061 B=sdfmilan062 G=sdfada018
export P=$ROOT/pr60 XDG_CACHE_HOME=$ROOT/cache/xdg UV_CACHE_DIR=$ROOT/cache/uv
mkdir -p $P/work
