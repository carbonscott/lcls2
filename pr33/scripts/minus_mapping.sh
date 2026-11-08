#!/bin/bash
# minus_mapping.sh JUNIT WALK OUT(new): check_parity with CGWMainControl.box_state removed from a copy of the mapping.
JUNIT=$1; WALK=$2; OUT=$3; M=psdaq/psdaq/webgui/parity
[ -n "$OUT" ] && [ ! -e "$OUT" ] || { echo "usage: minus_mapping.sh JUNIT WALK OUT(new dir)"; exit 2; }
mkdir -p $OUT && cp -p $M/mapping.json $OUT/ && cp -rp $M/mapping.d $OUT/
python3 - $OUT <<'PY'
import glob, json, os, sys
rid = 'CGWMainControl.box_state'
for f in glob.glob(os.path.join(sys.argv[1], 'mapping.d', '*.json')) + [os.path.join(sys.argv[1], 'mapping.json')]:
    d = json.load(open(f))
    if rid in d:
        print('removed %s from the copy %s: %s' % (rid, os.path.relpath(f, sys.argv[1]), d.pop(rid)))
        open(f, 'w').write(json.dumps(d, indent=1, sort_keys=True) + '\n')
PY
python -m psdaq.webgui.parity.check_parity --junit $JUNIT --walk $WALK --mapping $OUT/mapping.json > $OUT/parity.txt 2>&1; echo PARITY_MINUS_EXIT=$?
grep -E 'controls found|^walk|^Unmapped|^  CGWMainControl.box_state |^RESULT' $OUT/parity.txt | cut -c1-200
