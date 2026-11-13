#!/bin/bash
# faults4.sh: base (a7a8fa94d, wt-pr60) against the head (358be9a60, wt-pr60d), interleaved, on A under its DAQ lock:
#  stall: the leak p4p probe frozen (SIGSTOP, the python process, not its timeout wrapper) for 25 s just after its imports line
#  ctx:   a test copy of the sim dir whose pvwait.context raises TimeoutError in the leak probe (mode 'timeout') only
#  ioc:   at the fix, a fake softIocPVA that exits / never finishes iocInit (PF_BUDGET=60)
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-daq-hardening/pr60/env.sh
export WTA=$ROOT/wt-pr60 WTB=$ROOT/wt-pr60d
srun --jobid=$JOB --overlap -w $A --ntasks=1 --cpus-per-task=8 --mem=16G bash -c '
source $ROOT/simenv.sh $WTA >/dev/null
run_stall() {
  L=$P/work/fault-stall-$2.log; rm -f $L
  ( cd $1 && flock -w 900 $LOCK bash psdaq/psdaq/sim/preflight.sh > $L 2>&1; echo "PREFLIGHT_RC=$?" >> $L ) & bg=$!
  for i in $(seq 1 2400); do grep -q "p4p probe: imports done" $L 2>/dev/null && break; sleep 0.05; done
  pid=$(pgrep -u $(id -u) -f "^python[^ ]* .*preflight_p4p\.py timeout" | head -1)
  echo "watcher: $(date -u +%T.%3N) SIGSTOP pid $pid comm=$(cat /proc/$pid/comm) ($(tr "\0" " " < /proc/$pid/cmdline | cut -c1-110)) for 25 s"
  kill -STOP $pid; sleep 25; kill -CONT $pid 2>/dev/null; echo "watcher: $(date -u +%T.%3N) SIGCONT pid $pid"
  wait $bg
  echo "STALL $2 at $(git -C $1 rev-parse --short HEAD): $(grep PREFLIGHT_RC $L) $(grep -E "PREFLIGHT (PASS|FAIL)" $L | tail -1)"
  grep -E "p4p probe|p4p timeout|REACHED|p4p rc=|LEAK|HUNG|summary|Alarm" $L
}
run_ctx() {
  C=$P/work/inj-$2/psdaq/psdaq/sim; rm -rf $P/work/inj-$2; mkdir -p $C
  cp $1/psdaq/psdaq/sim/{preflight.sh,preflight_p4p.py,pvwait.py,sim_env.sh} $C/
  python3 - $C/pvwait.py <<PY
import sys; p=sys.argv[1]; s=open(p).read()
old="    from p4p.client.thread import Context\n"
assert s.count(old)==1
s=s.replace(old, old+"    if sys.argv[1:2] == [\"timeout\"]:  # pr60 test copy: the leak probe cannot make its client context\n        raise TimeoutError(\"injected: no client context (pr60 test copy of pvwait.py)\")\n")
open(p,"w").write(s)
PY
  echo "ctx $2: copy differs from $(git -C $1 rev-parse --short HEAD) in: $(for f in preflight.sh preflight_p4p.py pvwait.py sim_env.sh; do cmp -s $1/psdaq/psdaq/sim/$f $C/$f || echo -n "$f "; done)"
  L=$P/work/fault-ctx-$2.log
  flock -w 900 $LOCK bash $C/preflight.sh > $L 2>&1; rc=$?
  echo "CTX $2 at $(git -C $1 rev-parse --short HEAD): rc=$rc $(grep -E "PREFLIGHT (PASS|FAIL)" $L | tail -1)"
  grep -E "p4p probe|p4p timeout|REACHED|p4p rc=|LEAK|summary" $L
}
run_ioc() {
  F=$P/work/fakebin; for c in exit hang; do
    t0=$(date +%s); (cd $1 && PATH=$F/$c:$PATH PF_BUDGET=60 flock -w 900 $LOCK bash psdaq/psdaq/sim/preflight.sh > $P/work/ioc-$c-$2.log 2>&1); rc=$?
    echo "IOC-BROKEN $c at $(git -C $1 rev-parse --short HEAD): rc=$rc in $(( $(date +%s)-t0 )) s: $(grep -E "PREFLIGHT (PASS|FAIL)" $P/work/ioc-$c-$2.log | tail -1)"
    grep -E "fake softIocPVA|loopback IOC|HUNG|local pvget rc|summary" $P/work/ioc-$c-$2.log
  done
}
echo "=== faults on $(hostname -s) job $SLURM_JOB_ID $(date -u +%FT%TZ) base $(git -C $WTA rev-parse HEAD) fix $(git -C $WTB rev-parse HEAD) dirty $(git -C $WTA status --porcelain --untracked-files=no | wc -l)/$(git -C $WTB status --porcelain --untracked-files=no | wc -l)"
run_stall $WTA base4; run_stall $WTB head4
run_ctx $WTA base4; run_ctx $WTB head4
run_ioc $WTB head4
echo "=== end $(date -u +%FT%TZ)"' > $P/work/faults-4.log 2>&1
