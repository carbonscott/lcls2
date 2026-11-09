#!/bin/bash
# prebuild.sh: builds before the recording: wt-gpu-r695 (CUDA 12.9), then rehearsal builds of wt-nb45, wt-nh45 (no CUDA)
L=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/proof45
bash $L/build.sh wt-gpu-r695 12.9
bash $L/build.sh wt-nb45 none
bash $L/build.sh wt-nh45 none
echo PREBUILD_DONE
