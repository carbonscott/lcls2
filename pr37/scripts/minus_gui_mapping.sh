#!/bin/bash
# minus_gui_mapping.sh JUNIT WALKS OUT GUI ROW: check_gui_parity with ROW removed from the mapping of parity/guis/GUI.json
# in a scratch copy of parity/guis, on the walks --run-walks wrote (the checkout is not changed): must exit 1, naming ROW.
JUNIT=$1; WALKS=$2; OUT=$3; GUI=$4; RID=$5; G=psdaq/psdaq/webgui/parity/guis
[ -n "$RID" ] && [ ! -e "$OUT" ] || { echo "usage: minus_gui_mapping.sh JUNIT WALKS OUT(new dir) GUI ROW"; exit 2; }
mkdir -p $OUT && cp -rp $G $OUT/guis
python3 - $OUT/guis/$GUI.json "$RID" <<'PY'
import json, sys
p, rid = sys.argv[1], sys.argv[2]
d = json.load(open(p))
print('removed %s from the copy guis/%s: %s' % (rid, p.rsplit('/', 1)[-1], d['mapping'].pop(rid)))
open(p, 'w').write(json.dumps(d, indent=1) + '\n')
PY
python -m psdaq.webgui.parity.check_gui_parity --guis $OUT/guis --walks $WALKS --junit $JUNIT > $OUT/gui-parity.txt 2>&1
echo GUI_PARITY_MINUS_EXIT=$?
grep -F -e "| /gui/$GUI |" -e 'Unmapped (1 rows)' -e "  $RID |" -e "rows: $RID" -e 'RESULT: FAIL (' $OUT/gui-parity.txt | cut -c1-200
