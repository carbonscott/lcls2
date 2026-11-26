#!/bin/bash
# logbook.sh CASE OUT: psana2 DataSource(exp=, run=, dir=) on files on disk, offline, inside unshare -rn.
#   CASE nonet : no network at all (only lo), no proxy          -> what an offline job sees
#   CASE proxy : HTTPS_PROXY = loopback recording proxy          -> which host psana tries to reach
#   CASE fix   : no network, suggested fix applied (fixshim/)    -> the disk fallback works
# Writes its log to stdout (provenance header first).
set -u
P=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-issues/agents/h2
L=$P/lgbk
CASE=$1; OUT=$2
XTC=$L/xtc   # made with the release's own test writer: xtcwriter -n 20 -f mfxsim0001-r0001-s000-c000.xtc2; smdwriter -f ... -o smalldata/...smd.xtc2
R=$(readlink -f /sdf/group/lcls/ds/ana/sw/conda2/manage/bin/psconda.sh); R=${R%/setup_env_ana.sh}
echo "# host: $(hostname)"
echo "# date: $(date -u +%FT%TZ)"
echo "# commit: lcls2 release $(basename $R) = $(git -c safe.directory=$R -C $R rev-parse HEAD); upstream lcls2 master $(git -C $P/lcls2-up rev-parse master)"
echo "# cmd: logbook.sh $CASE $OUT  (srun on job 47203681, inside unshare -rn)"
echo "# network: $(ip -o link show | awk -F': ' '{print $2}' | tr '\n' ' ')(namespace $(readlink /proc/self/ns/net))"
echo "# scripts sha256: $(cd $L && sha256sum logbook.sh probe.py proxy.py fixshim/sitecustomize.py | awk '{printf "%s:%s ", $2, substr($1,1,12)}')"
ip link set lo up 2>/dev/null || true
source /sdf/group/lcls/ds/ana/sw/conda2/manage/bin/psconda.sh >/dev/null 2>&1
unset CALIB_JWT ARP_JOB_ID ARP_LOCATION JID_UPDATE_COUNTERS HTTP_PROXY HTTPS_PROXY http_proxy https_proxy
export KRB5CCNAME=FILE:/nonexistent-lgbk
export OMPI_ALLOW_RUN_AS_ROOT=1 OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1
# calibration constants from the loopback stand-in (same as the smalldata runs), so the logbook is the only variable
PORT=31878
export LCLS_CALIB_HTTP=http://127.0.0.1:$PORT NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost
python $P/x6/calibws_jf.py --port $PORT --log $OUT/calibws-$CASE.jsonl > $OUT/calibws-$CASE.out 2>&1 &
CWS=$!
for i in $(seq 50); do grep -q ready $OUT/calibws-$CASE.out 2>/dev/null && break; sleep 0.2; done
echo "psana: $(python -c 'import psana.psexp.ds_base as m; print(m.__file__)')"
echo "ds_base.py sha256: $(sha256sum $R/psana/psana/psexp/ds_base.py | cut -c1-16) (release)  $(sha256sum $P/lcls2-up/psana/psana/psexp/ds_base.py | cut -c1-16) (upstream master)"
echo "xtc on disk (written by the release's xtcwriter/smdwriter, $(stat -c %y $XTC/*.xtc2 | cut -c1-19)): $(ls $XTC/*.xtc2 $XTC/smalldata/*.xtc2 | xargs -n1 basename | tr '\n' ' ')"
case $CASE in
  proxy)
    python $L/proxy.py 3128 $OUT/proxy-$CASE.log > $OUT/proxy.out 2>&1 &
    PXY=$!; sleep 1; cat $OUT/proxy.out
    export HTTPS_PROXY=http://127.0.0.1:3128 https_proxy=http://127.0.0.1:3128 ;;
  fix)
    export PYTHONPATH=$L/fixshim${PYTHONPATH:+:$PYTHONPATH} ;;
esac
echo "---- python probe.py (case $CASE) ----"
python -u $L/probe.py $XTC 2>&1
RC=$?
echo "---- probe exit status: $RC ----"
if [ "$CASE" = proxy ]; then echo "recording proxy log:"; cat $OUT/proxy-$CASE.log; kill $PXY; fi
echo "calibration stand-in requests: $(wc -l < $OUT/calibws-$CASE.jsonl)"
kill $CWS 2>/dev/null
exit $RC
