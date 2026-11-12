#!/bin/bash
# f13pr STEP 3 on sdfada016 (job 44243826), sequential, every DAQ under /tmp/sdh-daq-ada016.lock (one.sh)
F=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-daq-hardening/work/f13pr; HPP=$1
run() { srun --jobid=44243826 --overlap -w sdfada016 --ntasks=1 --cpus-per-task=16 --mem=48G timeout -k 10 2400 bash $F/f13run.sh "$@"; }
for i in 1 2 3 4 5; do [ -e $F/STOP ] && exit 3; run e223e91cb b-fc$i drp fakecam stop 45 0 --only types --types fakecam; done
for i in $(seq 1 10); do [ -e $F/STOP ] && exit 3; run $HPP a-fc$i drp fakecam stop 45 0 --only types --types fakecam; done
for i in 1 2 3; do [ -e $F/STOP ] && exit 3; run $HPP a-tt$i none - stop 0 0 --only types --types tt; done
[ -e $F/STOP ] || run $HPP g-hang drp fakecam hang 0 0 --only types --types fakecam
[ -e $F/STOP ] || run $HPP g-dead drp fakecam kill 0 6 --only types --types fakecam
[ -e $F/STOP ] || run $HPP a-pg1 epicsArch - stop 45 0 --only programs
for i in 1 2; do [ -e $F/STOP ] && exit 3; run e223e91cb b-pg$i epicsArch - stop 45 0 --only programs; done
echo S3_DONE $(date -u +%FT%TZ)
