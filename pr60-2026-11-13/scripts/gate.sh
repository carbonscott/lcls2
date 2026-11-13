#!/bin/bash
# gate.sh N: probes on A,B,G, the sentinel half, one fakecam try on A (+ its corrupt break); log to $P/work/gate-N.log
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-daq-hardening/pr60/env.sh
N=$1; L=$P/work/gate-$N.log; exec > $L 2>&1
echo "=== gate $N $(date -u +%FT%TZ) WT HEAD $(git -C $WT rev-parse HEAD) dirty $(git -C $WT status --porcelain --untracked-files=no | wc -l)"
for n in $A $B; do srun --jobid=$JOB --overlap -w $n --ntasks=1 --cpus-per-task=2 --mem=4G bash $ROOT/probe.sh; done
srun --jobid=$GJOB --overlap -w $G --ntasks=1 --cpus-per-task=2 --mem=4G --gres=gpu:l40s:1 bash $ROOT/probe.sh
for n in $A $B $G; do tail -n 2000 $P/sentinel/$n.log | python3 -c '
import sys, datetime
node = sys.argv[1]; now = datetime.datetime.now(datetime.timezone.utc).timestamp()
mx = gap = 0.0; err = nl = 0; prev = last = None
for L in sys.stdin:
    f = L.split()
    if L.startswith("#") or len(f) < 4: continue
    t = datetime.datetime.strptime(f[0], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=datetime.timezone.utc).timestamp()
    last = t
    if now - t <= 900:
        nl += 1
        if prev is not None: gap = max(gap, t - prev)
        for kv in f[1:]:
            v = kv.split("=")[1]
            if v.startswith("ERR"): err += 1
            else: mx = max(mx, float(v))
    prev = t
age = now - last if last else 1e9
ok = nl > 0 and mx <= 3 and gap <= 4 and err == 0 and age <= 60
print("SENT %s lines15=%d max_field=%.3f max_gap=%.2f err=%d last_age=%.0fs %s" % (node, nl, mx, gap, err, age, "OK" if ok else "SHUT"))
' $n; done
srun --jobid=$JOB --overlap -w $A --ntasks=1 --cpus-per-task=16 --mem=32G bash -c '
  source $ROOT/simenv.sh $WT && W=$P/work/cheap-$(date -u +%m%dT%H%M) && mkdir -p $W-ev && export DAQ_SIM_EVIDENCE=$W-ev && t0=$(date +%s) &&
  daq_sim matrix -w $W --only types --types fakecam --lock $LOCK --evidence $W-ev; echo "MATRIX_EXIT=$? in $(( $(date +%s)-t0 )) s";
  daq_sim matrix -w $W --break corrupt --lock $LOCK; echo MATRIX_EXIT=$?' > $P/work/cheap-$N.log 2>&1
grep -E '^TYPE|^FAILED|^MATRIX' $P/work/cheap-$N.log
echo "=== gate $N end $(date -u +%FT%TZ)"
