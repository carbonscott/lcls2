#!/bin/bash
# W13: e2e-at.sh CHECKOUT WORKDIR [e2e args]: `daq_sim e2e` from that checkout of $W13, as the suite's
# fork/webgui-e2e row runs it, with two read-back pollers in the background while it runs:
#   bin/curlpoll.sh  curl of each exporter in WORKDIR/prom (no psdaq code)
#   bin/pypoll.py    the e2e's own scrape call next to the fixed call
C=$1 WD=$2; shift 2
cd $W13/$C && source ./setup_env_daq.sh >/dev/null 2>&1 || exit 1
E=$(python -c 'import psdaq.webgui.e2e as m; print(m.__file__)')
echo "checkout $C: $(git log -1 --format='%h %cI') dirty $(git status --porcelain --untracked-files=no | wc -l); e2e.py in use: ${E#$(realpath $W13)/}"
grep -n -A1 'in ds.prometheus_targets' $E
case " $* " in *" --keep-up "*)   # e2e that brings the DAQ up itself holds it in the foreground; so up first, detached
  daq_sim up --webgui --detach -w $WD > $WD-up.log 2>&1; echo "--keep-up: daq_sim up --webgui --detach first: UP_EXIT=$?";;
esac
bash $W13/bin/curlpoll.sh $WD > $WD-curl.log 2>&1 & P1=$!
python $W13/bin/pypoll.py $WD/prom > $WD-py.log 2>&1 & P2=$!
daq_sim e2e -w $WD --events 1000 --browser-python $BP "$@" > $WD.log 2>&1; rc=$?
kill $P1 $P2
grep -E 'e2e: in CONFIGURED|^  [1-7] (PASS|FAIL)|^E2E' $WD.log | cut -c1-300
echo "read-back during the run: $(wc -l < $WD-curl.log) curl readings; last: $(tail -n 1 $WD-curl.log)"
echo "pypoll last: $(tail -n 1 $WD-py.log)"
echo "E2E_EXIT=$rc $(date -u +%FT%TZ) log ${WD#$W13/}.log shots ${WD#$W13/}/e2e-shots"
