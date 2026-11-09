#!/bin/bash
# On sdfiana025: stop the daq_webgui of up_gui_web.sh <run name> (its step then ends).
source /sdf/scratch/users/c/cwang31/guiproof/penv.sh
D=$P/$1; [ -n "$1" ] && [ -f $D/pid ] || { echo "no running daq_webgui in $D"; exit 2; }
mv $D/pid $D/pid.stopped
for i in $(seq 1 30); do grep -q 'daq_webgui stopped' $D/up.log && break; sleep 1; done
tail -1 $D/up.log; tail -1 $D/webgui.log | cut -c1-150
echo "port 31063 on the node: $(srun --jobid=$JOB --overlap --ntasks=1 --cpus-per-task=1 --mem=1G bash -c "ss -ltn | awk '\$4 ~ /:31063\$/' | wc -l") listening"
