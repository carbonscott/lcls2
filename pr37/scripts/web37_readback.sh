#!/bin/bash
# On sdfiana025: hand the browser run's writes (JSON on stdin) to the session step on the node, which reads them back
# with its own p4p client (readback37.py), and print what it read.
source /sdf/scratch/users/c/cwang31/proof37/penv.sh
D=$Q/$1; [ -n "$1" ] && grep -q SESSION_UP $D/session.log 2>/dev/null || { echo "no running session in $D"; exit 2; }
rm -f $D/readback.out; cat > $D/readback.tmp && mv $D/readback.tmp $D/readback.req
for i in $(seq 1 150); do grep -q READBACK_DONE $D/readback.out 2>/dev/null && break; sleep 1; done
grep -v READBACK_DONE $D/readback.out | cut -c1-150
