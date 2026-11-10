#!/bin/bash
# cuinit.sh: time CUDA driver init + context create in fresh processes on this step's GPU (diagnostic, no DAQ)
echo "$(hostname) step $SLURM_STEP_ID $(date -u +%FT%TZ) CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"
nvidia-smi --query-gpu=index,name,pci.bus_id,persistence_mode,utilization.gpu,memory.used --format=csv,noheader
for i in 1 2 3; do
python3 - <<'PY'
import ctypes, time
t0=time.time(); l=ctypes.CDLL('libcuda.so.1'); r=l.cuInit(0); t1=time.time()
d=ctypes.c_int(); l.cuDeviceGet(ctypes.byref(d),0); c=ctypes.c_void_p(); r2=l.cuCtxCreate_v2(ctypes.byref(c),0,d); t2=time.time()
print(f"cuInit rc={r} {t1-t0:.2f} s; cuCtxCreate rc={r2} {t2-t1:.2f} s")
PY
done
