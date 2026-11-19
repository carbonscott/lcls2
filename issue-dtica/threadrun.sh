#!/bin/bash
# usage: threadrun.sh ARM PORT SECS -> runs/thread-ARM.txt
ARM=$1; PORT=$2; SECS=$3
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/dtica-upstream/env.sh
pva_env $PORT; cd $HERE; mkdir -p runs; PFX=TC:$(echo $ARM | tr a-z A-Z)
python -m psdaq.cas.dticas -P $PFX > runs/thread-$ARM-server.log 2>&1 & SRV=$!
for i in $(seq 30); do python -m p4p.client.cli get $PFX:3:QpllLock > /dev/null 2>&1 && break; sleep 1; done
PUT=; [ $ARM = live ] && { python putter.py $PFX > runs/thread-$ARM-putter.log 2>&1 & PUT=$!; sleep 2; }
{ date -Is; hostname; git -C lcls2 rev-parse --short HEAD; python threadcheck.py $PFX $SECS; } > runs/thread-$ARM.txt 2>&1
kill $SRV $PUT 2>/dev/null; sed -n '/^platform/,$p' runs/thread-$ARM.txt
