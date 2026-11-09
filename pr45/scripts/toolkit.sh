#!/bin/bash
# toolkit.sh: what the node has for CUDA, and the conda-forge toolkits the builds use (in a GPU step)
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/proof45/env.sh wt-gpu
hdr toolkit
echo "GPU: $(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader); driver runs up to $(nvidia-smi | grep -o 'CUDA Version: [0-9.]*')"
echo "nvcc on PATH: $(command -v nvcc || echo none); /usr/local/cuda: $(ls -d /usr/local/cuda 2>&1 | sed 's/.*cannot access .*: //')"
echo "nvcc in the DAQ env $CONDA_DEFAULT_ENV: $(ls $CONDA_PREFIX/bin/nvcc 2>&1 | sed 's/.*cannot access .*: //')"
for C in $CU12 $CU13; do
  m=$(ls $C/conda-meta/cuda-nvcc-[0-9]*.json)
  echo "$(basename $C): $($C/bin/nvcc --version | grep -o 'release .*'), $(python -c "import json,sys; print(json.load(open(sys.argv[1]))['url'].replace('https://conda.anaconda.org/', ''))" $m)" | c
  I=$C/targets/x86_64-linux/include/cccl; [ -L $I ] && I="-> $(readlink $I) (added)" || I="(the toolkit's own)"
  echo "  for meson (RUNBOOK 3h): added version.json ($(grep -o '"version": "[0-9.]*"' $C/version.json)), lib64 -> $(readlink $C/lib64); include/cccl $I" | c
done
