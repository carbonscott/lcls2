#!/bin/bash
# repro3.sh (work/prf1 copy of work/f1fix2/repro2.sh: output dir and STOP file only; that is a copy of work/f1fix/repro.sh: output dir, STOP file and per-node lock only)
# repro.sh BUILD TAG N STOP_S [OVERLAY_DIR] : the F1 reproducer, N tries of
#   daq_sim matrix -w WD --only types --types opal --lock $LOCK --lock-timeout 600 --evidence EV
# with f1watch.py SIGSTOPping teb0 for STOP_S s right after the opal DRP logs 'TebRcvr saw Enable', and promsample2.py
# sampling TCtbO_InFlt every 0.2 s. OVERLAY_DIR (optional) is put first on PYTHONPATH (discriminator only).
R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-daq-hardening
B=$1; TAG=$2; N=$3; STOP_S=$4; OV=$5; F=$R/work/prf1/runs/$TAG; LOCK=/tmp/sdh-daq-$(hostname -s | sed s/^sdf//).lock; mkdir -p $F
source $R/work/f1fix2/env.sh $B || exit 1
[ -n "$OV" ] && export PYTHONPATH=$OV:$PYTHONPATH
echo "=== repro on $(hostname) job $SLURM_JOB_ID step $SLURM_STEP_ID build $B HEAD $(git rev-parse HEAD) dirty $(git status --porcelain --untracked-files=no | wc -l) stop_s $STOP_S overlay '${OV}' $(date -u +%FT%TZ)"
python3 -c 'import psdaq.sim.daq_sim as d; print("daq_sim from", d.__file__, "opal kwargs", d.SIM_TYPES["opal"]["kwargs"])'
for i in $(seq 1 $N); do
  [ -e $R/work/prf1/STOP ] && break
  WD=$F/try-$i; EV=$F/try-$i-ev; mkdir -p $EV
  echo "--- try $i start $(date -u +%FT%TZ) load: $(cat /proc/loadavg)"
  python3 $R/work/f1fix2/promsample2.py $WD $F/try-$i-prom.json & SP=$!
  python3 $R/work/f1fix2/f1watch.py $WD opal $F/try-$i-watch.json $STOP_S & WP=$!
  CMD="daq_sim matrix -w $WD --only types --types opal --lock $LOCK --lock-timeout 600 --evidence $EV"
  echo "    CMD: $CMD"
  $CMD > $F/try-$i.log 2>&1; RC=$?
  kill -TERM $SP $WP; wait $SP $WP 2>/dev/null
  echo "    try $i MATRIX_EXIT=$RC end $(date -u +%FT%TZ)"
  grep -E "^\s*TYPE|MATRIX (PASS|FAIL)" $F/try-$i.log | sed 's/^/    /'
  grep -h -E "nL1Buffers|nTrBuffers|dmaCount|# of TEB contrib|Batch pool depth" $WD/types/opal/pmlogs/*/*/*opal_0.log | head -5 | sed 's/^/    drp: /'
  echo "    overflow: $(grep -h '_pending queue overflow' $WD/types/opal/pmlogs/*/*/*.log 2>/dev/null)"
  echo "    drp errs: $(grep -h -c -E 'overrun|Overrun|DMA buffer index|pebble index' $WD/types/opal/pmlogs/*/*/*opal_0.log)"
  python3 -c "import json;w=json.load(open('$F/try-$i-watch.json'));e=w['enable_t'];f=lambda k:None if (w[k] is None or e is None) else round(w[k]-e,3);print('    watch teb', w['teb_pid'], 'stop+',f('stop_t'),'cont+',f('cont_t'),'overflow+',f('overflow_t'))" 2>&1
  python3 -c "
import json
d=json.load(open('$F/try-$i-prom.json')).get('opal',{}); w=json.load(open('$F/try-$i-watch.json'))
print('    prom opal peak', d.get('inflt_peak'), 'IFMax', d.get('ifmax'), 'samples', d.get('samples'), 'evt', d.get('evtct_last'))
e=w['enable_t'] or 0
tr=[(round(j['t']-e,1),int(j['TCtbO_InFlt'])) for j in map(json.loads,open('$F/try-$i-prom.json.jsonl')) if j['type']=='opal']
print('    trace (t-Enable s, InFlt):', ' '.join(f'{t}:{v}' for t,v in tr[:40]))" 2>&1
done
echo "=== repro done $(date -u +%FT%TZ)"
