#!/bin/bash
# pv_negative.sh SIMDAQ JUNIT WALKS OUT: a scratch tree (git archive HEAD) whose pvgui/xpmpva.py gives the four MMCM
# reset buttons each other's PV (ResetMmcm0 <-> 1, 2 <-> 3).  xpmpva's button test, run from that tree, still passes
# (it checks the page's own PVs); check_gui_parity run from that tree, on the same walks, must exit 1 and name the four
# rows with both PVs.  The checkout is not changed.
SIMDAQ=$1; JUNIT=$2; WALKS=$3; OUT=$4
[ -n "$OUT" ] && [ ! -e "$OUT" ] || { echo "usage: pv_negative.sh SIMDAQ JUNIT WALKS OUT(new dir)"; exit 2; }
M=$OUT/tree; mkdir -p $M
git archive HEAD psdaq/psdaq setup_env_daq.sh | tar -x -C $M
python3 - $M/psdaq/psdaq/webgui/pvgui/xpmpva.py <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
old = "'pv': x + 'ResetMmcm%d' % i,"
assert s.count(old) == 1
open(p, 'w').write(s.replace(old, "'pv': x + 'ResetMmcm%d' % (i ^ 1),"))
PY
echo "scratch tree $M: the only difference from the checkout:"; diff -r -x __pycache__ psdaq/psdaq $M/psdaq/psdaq | cut -c1-138
WEBGUI_SIM_DAQ=$SIMDAQ WEBGUI_SHOTS=$OUT/shots WEBGUI_PYTHON=$(command -v python) timeout -k 5 900 bash $M/psdaq/psdaq/webgui/tests/run_webgui_tests.sh -q -p no:warnings --junitxml=$OUT/pv.junit.xml -k 'test_gui_xpmpva and test_buttons_put_their_values' > $OUT/pv-tests.log 2>&1
echo PV_TESTS_EXIT=$?; grep -E '^(FAILED|ERROR)|passed|failed' $OUT/pv-tests.log | cut -c1-160 | tail -2
PYTHONPATH=$M/psdaq${PYTHONPATH:+:$PYTHONPATH} python -m psdaq.webgui.parity.check_gui_parity --src $M/psdaq/psdaq --walks $WALKS --junit $JUNIT --junit $OUT/pv.junit.xml > $OUT/gui-parity.txt 2>&1
echo GUI_PARITY_PV_EXIT=$?
grep -E '^check_gui_parity: src=' $OUT/gui-parity.txt | cut -c1-150
grep -F -e 'cas/xpmpva.py |' -e 'Invalid mapping entries' -e 'ResetMmcm' $OUT/gui-parity.txt | grep -v '^RESULT' | cut -c1-170
grep -E '^PV check of the pvgui pages' $OUT/gui-parity.txt | cut -c1-150
grep -E '^RESULT: FAIL: .*ResetMmcm' $OUT/gui-parity.txt | cut -c1-170; grep '^RESULT: FAIL (' $OUT/gui-parity.txt
