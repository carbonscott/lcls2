#!/bin/bash
# chain4.sh: at 358be9a60 (wt-pr60d), after chain3 and the build: unit tests, gate 4, and only if the gate is open: full check pr60-4, breaks + coverage, faults3
export WT_OVERRIDE=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-daq-hardening/wt-pr60d
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-daq-hardening/pr60/env.sh
exec >> $P/work/chain4.log 2>&1
until grep -q "chain3 end" $P/work/chain3.log 2>/dev/null; do sleep 10; done
until grep -q BUILD_EXIT $P/build-d.log 2>/dev/null; do sleep 10; done
grep BUILD_EXIT $P/build-d.log; grep -q BUILD_EXIT=0 $P/build-d.log || { echo "BUILD FAILED: no checks"; exit 1; }
echo "=== chain4 $(date -u +%FT%TZ) WT $WT HEAD $(git -C $WT rev-parse HEAD)"
bash $P/ut.sh; cp $P/work/ut.log $P/work/ut-d.log; tail -1 $P/work/ut-d.log
bash $P/gate.sh 4
python3 - $P/work/gate-4.log <<'PY' || { echo "GATE SHUT $(date -u +%FT%TZ): no full check started"; exit 1; }
import re, sys
L = open(sys.argv[1]).read().splitlines(); ok = True; why = []
probes = [l for l in L if l.startswith('PROBE ')]
for l in probes:
    f = l.split(); d = dict(zip(f[2::2], f[3::2])) if False else {}
    imp = float(re.search(r'import_s (\S+)', l).group(1)); dd = float(re.search(r'dd_s (\S+)', l).group(1))
    cu = re.search(r'cuinit_s (\S+)', l).group(1)
    if imp > 5.8: ok = False; why.append('import_s %s' % imp)
    if dd > 1.4: ok = False; why.append('dd_s %s' % dd)
    if cu != 'none' and float(cu) > 0.17: ok = False; why.append('cuinit_s %s' % cu)
sent = [l for l in L if l.startswith('SENT ')]
if len(probes) != 3 or len(sent) != 3 or any(not l.endswith(' OK') for l in sent): ok = False; why.append('probes/sentinels')
m = [l for l in L if l.startswith('MATRIX_EXIT=0 in ')]
if not m or int(m[0].split()[2]) > 126: ok = False; why.append('fakecam try')
print('GATE', 'OPEN' if ok else 'SHUT', why)
sys.exit(0 if ok else 1)
PY
export WT A B G JOB GJOB ROOT CUDA P
srun --jobid=$JOB --overlap -w $A --ntasks=1 --cpus-per-task=32 --mem=120G bash $P/mx.sh pr60-4 > $P/work/mx-pr60-4.log 2>&1
tail -1 $P/work/mx-pr60-4.log
bash $P/brk-cov.sh pr60-4
bash $P/faults4.sh
echo "=== chain4 end $(date -u +%FT%TZ)"
