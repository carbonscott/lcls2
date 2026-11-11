#!/bin/bash
nvidia-smi
bash /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-daq-hardening/work/prf1/cuinit.sh
python3 -c "import ctypes,time; t=time.time(); r=ctypes.CDLL('libcuda.so.1').cuInit(0); print('runbook one-liner rc', r, time.time()-t)"
