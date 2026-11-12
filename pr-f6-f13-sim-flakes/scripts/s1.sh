#!/bin/bash
# f13pr STEP 1: tt x3 at e223e91cb on sdfmilan082 (job 44243825), sequential
F=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-daq-hardening/work/f13pr
for i in 1 2 3; do
  srun --jobid=44243825 --overlap -w sdfmilan082 --ntasks=1 --cpus-per-task=16 --mem=32G \
    timeout -k 10 1500 bash $F/one.sh e223e91cb s1-tt$i --only types --types tt > $F/s1-tt$i.log 2>&1
  echo "s1-tt$i done $(date -u +%FT%TZ) $(tail -1 $F/s1-tt$i.log)"
done
echo S1_DONE
