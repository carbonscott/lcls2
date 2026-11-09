#!/bin/bash
# blk.sh: the NOT DONE types' first failures at this HEAD (unrecorded), each its own srun step
B=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/proof39
S='srun --jobid=43839059 --overlap --ntasks=1 --cpus-per-task=16 --mem=32G'
timeout -k 5 600 $S $B/showblk.sh > $B/rec/showblk-H.log 2>&1; echo "showblk done $(date -Is)"
timeout -k 5 600 $S $B/stack1kfps.sh 150 > $B/rec/stack-epixquad1kfps-H.log 2>&1; echo "stack done $(date -Is)"
echo BLK_DONE
