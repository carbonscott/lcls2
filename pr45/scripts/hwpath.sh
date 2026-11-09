#!/bin/bash
# hwpath.sh <worktree> cuda|nocuda <rundir>: the hardware path (no sim:// device) of the programs whose code this
# PR touches, from <worktree>'s build; pids, addresses, times, CPU lists and paths masked, so builds diff.
#   cuda:   drp_gpu (-D epixuhremu, fakecam on /dev/datadev_0; a sim kwarg without a sim device; -D epixuhrsim
#           -d /dev/null, its own simulator mode) and drp (-D fakecam, wave8 on /dev/datadev_0)
#   nocuda: drp_gpu (is it built?), drp (-D fakecam, wave8 on /dev/datadev_0)
#   both:   psana reading files the CPU DRP recorded at this PR's head (pyprobe.py)
W=$1; MODE=$2; P=$3
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/proof45/env.sh $W
[ $MODE = cuda ] && export LD_LIBRARY_PATH=$CU12/targets/x86_64-linux/lib:$LD_LIBRARY_PATH
echo "== $W head=$(git rev-parse --short HEAD) dirty=$(git status --porcelain --untracked-files=no | wc -l) $MODE build"
mask() { sed -E "s#$R/$W#<wt>#g; s#/sdf/scratch/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/$W#<wt>#g; s#$P/##g; s/\[[0-9]+\]/[PID]/g; s/0x[0-9a-f]{6,}/0xADDR/g; s/[0-9]{2}:[0-9]{2}:[0-9]{2}/HH:MM:SS/g; s/granted [0-9]+ CPUs on NUMA node [0-9]+: [0-9,]+/granted CPUS/; s/the [0-9]+ granted CPUs are only [0-9]+ physical cores, so any hot thread past the first [0-9]+/the N granted CPUs are N cores, so past N/; s/exceed [0-9]+ granted CPUs/exceed N granted CPUs/; s/Consider cores: [0-9]+/Consider cores: N/"; }
run() {
  echo "-- $*" | mask
  { timeout -k 15 60 "$@" > $P/hw.$$ 2>&1 < /dev/null; } 2>/dev/null; rc=$?   # 60 s, then TERM; KILL 15 s later
  grep -v -E '^\s*$|DMA buffer\[|GPU Device Attributes|^tst-[a-z_]+\[[0-9]+\]: <I>   |CPU allocation|Allocated .* GB pebble|nL1Buffers|nTrBuffers|dmaCount|Calibration buffers|Number of pixels|^ +[0-9]+ +[0-9]+ +total|^ +[0-9.]+ +[0-9.]+ +total' $P/hw.$$ | mask | head -25
  echo "rc=$rc"; rm -f $P/hw.$$
}
echo "-- programs: $(command -v drp drp_gpu python | mask | tr '\n' ' ')"
K=reducer=NoOpReducer,dmaBufCount=64,dmaBufSize=458752
if [ $MODE = cuda ]; then
  run drp_gpu -P tst -p 7 -C localhost -D epixuhremu -d /dev/datadev_0 -u epixuhremu_0 -k $K
  run drp_gpu -P tst -p 7 -C localhost -D fakecam -d /dev/datadev_0 -u fakecam_0 -k $K
  run drp_gpu -P tst -p 7 -C localhost -D epixuhremu -d /dev/datadev_0 -u epixuhremu_0 -k $K,sim_dma_size=0x60000
  run drp_gpu -P tst -p 7 -C localhost -D epixuhrsim -d /dev/null -u epixuhrsim_0 -k $K,pebbleBufCount=64
else
  p=$(command -v drp_gpu); echo "-- drp_gpu: ${p:-not built (no nvcc, so meson skips psdaq/drpGpu)}" | mask
fi
run drp -P tst -p 7 -C localhost -D fakecam -d /dev/datadev_0 -u fakecam_0
run drp -P tst -p 7 -C localhost -D wave8 -d /dev/datadev_0 -u wave8_0
F() { awk '/^  xtc2 file/{print $3}' $P/cycle-drp-$1.log; }
echo "-- python pyprobe.py fakecam epixhremu epix100 (files the CPU DRP recorded at this PR's head)"
timeout -k 5 600 python $L/pyprobe.py fakecam=$(F fakecam) epixhremu=$(F epixhremu) epix100=$(F epix100) 2>&1 | quiet | mask
echo "rc=${PIPESTATUS[0]}"
