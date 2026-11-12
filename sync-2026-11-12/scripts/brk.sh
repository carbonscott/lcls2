#!/bin/bash
# breaks: MAINTAINING.md §10 break command (at 8cc9e688c), srun on G=sdfada010 (ada job 44435421), W and log under $ROOT/sms/work
export ROOT=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-daq-hardening
export XDG_CACHE_HOME=$ROOT/cache/xdg UV_CACHE_DIR=$ROOT/cache/uv
export WT=$ROOT/wt-sync-2026-11-12 A=sdfmilan151 B=sdfmilan175 G=sdfada010 JOB=44435234 GJOB=44435421 CUDA=$ROOT/tools/cuda-12.9
nohup srun --jobid=44435421 --overlap -w sdfada010 --ntasks=1 --cpus-per-task=16 --mem=32G bash -c '
  source $ROOT/simenv.sh $WT && W=$ROOT/sms/work/brk-$(date -u +%m%dT%H%M)
  for k in register kill-drp corrupt; do
    daq_sim matrix -w $W --break $k --lock $LOCK --lock-timeout 5400 > $W-$k.log 2>&1
    echo "BREAK $k exit $?: $(grep -E "^MATRIX (PASS|FAIL)" $W-$k.log | tail -1)"; grep "^FAILED " $W-$k.log
  done' > $ROOT/sms/work/brk-sms2.log 2>&1 &
