#!/bin/bash
cd $WT && source ./setup_env_daq.sh && export CUDA_ROOT=$CUDA PATH=$PATH:$CUDA/bin && ./build_all.sh -d -j 32; echo BUILD_EXIT=$? $(date -u +%FT%TZ)
