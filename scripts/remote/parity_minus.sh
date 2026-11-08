#!/bin/bash
# The parity check with one web mapping (CGWMainControl.box_state) removed from a copy of the mapping.
JUNIT=$1; OUT=$2; M=psdaq/psdaq/webgui/parity
rm -rf "${OUT:?}"; mkdir -p $OUT/mapping.d; cp $M/mapping.d/*.json $OUT/mapping.d/
python - $M/mapping.json $OUT <<'PY'
import json, sys, glob, os
src, out = sys.argv[1], sys.argv[2]
rid = 'CGWMainControl.box_state'
m = json.load(open(src)); removed = False
if rid in m: del m[rid]; removed = True
json.dump(m, open(os.path.join(out, 'mapping.json'), 'w'), indent=1)
for f in glob.glob(os.path.join(out, 'mapping.d', '*.json')):
    d = json.load(open(f))
    if rid in d: del d[rid]; removed = True; json.dump(d, open(f, 'w'), indent=1)
print('removed', rid, removed)
PY
python -m psdaq.webgui.parity.check_parity --junit $JUNIT --mapping $OUT/mapping.json > $OUT/parity-minus.txt 2>&1; echo PARITY_MINUS_EXIT=$?
grep -E 'controls found|RESULT' $OUT/parity-minus.txt
