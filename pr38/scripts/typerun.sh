#!/bin/bash
# usage (ONE Slurm step): typerun.sh <type>: a fresh simulated DAQ for <type>: daq_sim up --det <type> --detach,
# cycle --events 1000 (it writes its evidence record to $DAQ_SIM_EVIDENCE), down. Everything up starts, down stops.
T=$1
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/covbind/p38b/env.sh
hdr; echo "evidence=$DAQ_SIM_EVIDENCE sim_env=$SIM_ENV_SOURCED EPICS_PVA_ADDR_LIST=$EPICS_PVA_ADDR_LIST"
WD=$Q/wd-$T
[ -e $WD ] && { echo "work dir exists: $WD"; exit 3; }
echo "before: listening on 30050/15075: $(ss -ltn | grep -cE ':(30050|15075) '); my procServ: $(pgrep -u $USER -x procServ | wc -l)"
echo "== up --det $T --detach"
timeout -k 5 300 daq_sim up -w $WD --det $T --detach; echo UP_EXIT=$?
echo "== cycle --events 1000"
timeout -k 5 400 daq_sim cycle -w $WD --events 1000; echo CYCLE_EXIT=$?
echo "== down"
timeout -k 5 120 daq_sim down -w $WD; echo DOWN_EXIT=$?
echo "== leftovers: procServ $(pgrep -u $USER -f "procServ.*$WD" | wc -l) tagged $(grep -l "DAQ_SIM_WORKDIR=$WD" /proc/[0-9]*/environ 2>/dev/null | wc -l) ports $(ss -ltn | grep -cE ':(30050|15075) ')"
echo TYPERUN_DONE
