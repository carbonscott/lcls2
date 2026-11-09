#!/bin/bash
# minus_gui_mapping.sh JUNIT WALKS OUT(new): check_gui_parity with PvGroupStats.runb removed from groupca.json in a
# scratch copy of parity/guis, on the walks --run-walks wrote to WALKS (the checkout is not changed).
JUNIT=$1; WALKS=$2; OUT=$3; G=psdaq/psdaq/webgui/parity/guis
[ -n "$OUT" ] && [ ! -e "$OUT" ] || { echo "usage: minus_gui_mapping.sh JUNIT WALKS OUT(new dir)"; exit 2; }
mkdir -p $OUT && cp -rp $G $OUT/guis
python3 - $OUT/guis/groupca.json <<'PY'
import json, sys
p, rid = sys.argv[1], 'PvGroupStats.runb'
d = json.load(open(p))
print('removed %s from the copy guis/groupca.json: %s' % (rid, d['mapping'].pop(rid)))
open(p, 'w').write(json.dumps(d, indent=1) + '\n')
PY
python -m psdaq.webgui.parity.check_gui_parity --guis $OUT/guis --walks $WALKS --junit $JUNIT > $OUT/gui-parity.txt 2>&1
echo GUI_PARITY_MINUS_EXIT=$?
grep -E '^walks:|^cas/groupca.py |^Unmapped|^  PvGroupStats.runb |^RESULT' $OUT/gui-parity.txt | cut -c1-200
