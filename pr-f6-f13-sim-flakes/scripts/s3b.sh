#!/bin/bash
# f13pr s3b.sh: the dead guardrail again, the DRP stopped at first sight (never Ready) and SIGKILLed 6 s after, after s3.sh ends
F=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-daq-hardening/work/f13pr; HPP=$1
until grep -q S3_DONE $F/s3.out; do sleep 10; done
srun --jobid=44243826 --overlap -w sdfada016 --ntasks=1 --cpus-per-task=16 --mem=48G timeout -k 10 2400 bash $F/f13run.sh $HPP g-dead2 drp fakecam stopkill 0 6 --only types --types fakecam
echo S3B_DONE $(date -u +%FT%TZ)
