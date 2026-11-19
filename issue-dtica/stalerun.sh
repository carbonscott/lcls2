#!/bin/bash
# usage: stalerun.sh PORT SECS TAG [--keep]   dticas + putter (1 Hz), then stalecheck.py -> runs/stale-TAG.{txt,png}
PORT=$1; SECS=$2; TAG=$3; KEEP=${4:-}
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/dtica-upstream/env.sh
pva_env $PORT; cd $HERE; mkdir -p runs; PFX=SC:$(echo $TAG | tr a-z- A-Z_)
python -m psdaq.cas.dticas -P $PFX > runs/stale-$TAG-server.log 2>&1 & SRV=$!
for i in $(seq 30); do python -m p4p.client.cli get $PFX:3:QpllLock > /dev/null 2>&1 && break; sleep 1; done
python putter.py $PFX > runs/stale-$TAG-putter.log 2>&1 & PUT=$!; sleep 2
{ date -Is; hostname; git -C lcls2 rev-parse --short HEAD; python stalecheck.py $PFX $SECS runs/stale-$TAG.png $KEEP; } > runs/stale-$TAG.txt 2>&1
kill $SRV $PUT; sed -n '/ keep=/,/^total/p' runs/stale-$TAG.txt
