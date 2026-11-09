#!/bin/bash
# compat.sh: what psdaq/drpGpu/GreenCtxCompat.hh adds to cuda.h + cuda_runtime.h under each toolkit (preprocessed)
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/proof45/env.sh wt-gpu
CXX=${CXX:-g++}
for C in $CU12 $CU13; do
  pp() { printf "$1" | $CXX -std=c++17 -E -P -x c++ -I$C/targets/x86_64-linux/include -Ipsdaq/drpGpu - 2>&1 | grep -v '^\s*$'; }   # blank lines dropped
  H='#include <cuda.h>\n#include <cuda_runtime.h>\n'
  n=$(diff <(pp "$H") <(pp "$H#include \"GreenCtxCompat.hh\"\n") | grep -c '^[<>]')
  d=$(pp "$H#include \"GreenCtxCompat.hh\"\n#ifdef DRPGPU_DRIVER_GREEN_CONTEXTS\nDEFINED\n#else\nNOT_DEFINED\n#endif\nCUDART_VERSION\n" | tail -2 | tr '\n' ' ')
  echo "$(basename $C): GreenCtxCompat.hh changes $n non-blank lines of the preprocessed cuda.h + cuda_runtime.h; DRPGPU_DRIVER_GREEN_CONTEXTS / CUDART_VERSION: $d"
done
