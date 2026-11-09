#!/bin/bash
# drop_control.sh SIMDAQ JUNIT WALKS OUT: a scratch tree (git archive HEAD) whose pvgui.js renders no MsgClear button on
# /gui/partca; partca's button test runs from that tree against the simulated DAQ; then check_gui_parity with that junit
# added to the suite's: it must exit 1 and name the row.  The checkout is not changed.
SIMDAQ=$1; JUNIT=$2; WALKS=$3; OUT=$4; RID='Ui_MainWindow.PvPushButton@4[DAQ:SIM:XPM:0:PART:5:MsgClear]'
[ -n "$OUT" ] && [ ! -e "$OUT" ] || { echo "usage: drop_control.sh SIMDAQ JUNIT WALKS OUT(new dir)"; exit 2; }
M=$OUT/tree; mkdir -p $M
git archive HEAD psdaq/psdaq setup_env_daq.sh | tar -x -C $M
python3 - $M/psdaq/psdaq/webgui/static/gui/pvgui.js "$RID" <<'PY'
import json, sys
p, rid = sys.argv[1], sys.argv[2]
s = open(p).read()
old = "    case 'pvbutton': {"
new = old + "\n      if (n.id === %s) return el('span', {});   // drop_control.sh: the page has no such button" % json.dumps(rid)
assert s.count(old) == 1
open(p, 'w').write(s.replace(old, new))
PY
echo "scratch tree $M: the only difference from the checkout:"; diff -r psdaq/psdaq $M/psdaq/psdaq | cut -c1-138
WEBGUI_SIM_DAQ=$SIMDAQ WEBGUI_SHOTS=$OUT/shots WEBGUI_PYTHON=$(command -v python) timeout -k 5 900 bash $M/psdaq/psdaq/webgui/tests/run_webgui_tests.sh -q -p no:warnings --junitxml=$OUT/drop.junit.xml -k 'test_gui_partca and test_buttons_put_1_then_0' > $OUT/drop-tests.log 2>&1
echo DROP_TESTS_EXIT=$?; grep -E '^(FAILED|ERROR)|passed|failed' $OUT/drop-tests.log | cut -c1-160 | tail -3
python -m psdaq.webgui.parity.check_gui_parity --walks $WALKS --junit $JUNIT --junit $OUT/drop.junit.xml > $OUT/gui-parity.txt 2>&1
echo GUI_PARITY_DROP_EXIT=$?
grep -F -e 'cas/partca.py |' -e 'Mapped but test not passing' -e "  $RID |" $OUT/gui-parity.txt | cut -c1-170
grep -E '^RESULT: FAIL: .*(MsgClear|not passing)' $OUT/gui-parity.txt | cut -c1-200 | head -2; grep '^RESULT: FAIL (' $OUT/gui-parity.txt
