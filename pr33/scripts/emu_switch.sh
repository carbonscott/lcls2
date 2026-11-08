#!/bin/bash
# emu_switch.sh WD SIMJUNIT WALK OUT(new): in a scratch copy of this checkout's psdaq/psdaq, switch
# test_refresh_buttons (rows CGWMainControl.but_transition, .but_ctrls) to the emulator fixture, rerun its test
# file against the simulated DAQ in WD, put that run into a copy of SIMJUNIT, then run check_parity.
WD=$1; SIMJUNIT=$2; WALK=$3; OUT=$4; WT=$PWD
[ -n "$OUT" ] && [ ! -e "$OUT" ] && [ -d psdaq/psdaq/webgui/tests ] || { echo "usage: emu_switch.sh WD SIMJUNIT WALK OUT(new); run in the checkout"; exit 2; }
mkdir -p $OUT/psdaq && cp -rp psdaq/psdaq $OUT/psdaq/ && C=$OUT/psdaq/psdaq/webgui/tests
python3 - $C/test_webgui_ui.py <<'PY'
import sys
p = sys.argv[1]; s = open(p).read(); a = 'def test_refresh_buttons(page, server):\n'
assert s.count(a) == 1, 'pattern not found once'
open(p, 'w').write(s.replace(a, 'def test_refresh_buttons(page, emu_server):\n    server = emu_server    # NEGATIVE CHECK: the emulator\n'))
PY
echo "scratch copy $C (the checkout is not changed):"; diff -u $WT/psdaq/psdaq/webgui/tests/test_webgui_ui.py $C/test_webgui_ui.py | sed -n '3,9p'
W=${AGENTIFY_WEBTEST:-/sdf/scratch/users/c/cwang31/agentify-webtest}
( export PLAYWRIGHT_BROWSERS_PATH=$W/browsers PYTHONDONTWRITEBYTECODE=1 WEBGUI_SIM_DAQ=$WD WEBGUI_SHOTS=$OUT/shots
  export HTTP_PROXY=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9 http_proxy=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9
  export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1 PYTHONPATH=$OUT/psdaq${PYTHONPATH:+:$PYTHONPATH}
  export WEBGUI_PYTHON=$(command -v python)
  cd $C && "$W/venv/bin/python" -m pytest -p no:cacheprovider --rootdir "$C" --browser chromium -q \
      --junitxml=$OUT/ui.junit.xml test_webgui_ui.py > $OUT/ui-tests.log 2>&1; echo "rerun of test_webgui_ui.py on the copy: PYTEST_EXIT=$?, $(tail -1 $OUT/ui-tests.log)" )
python3 $P/junit_backends.py $OUT/ui.junit.xml 'test_refresh_buttons[chromium]'
python3 $P/junit_swap.py $SIMJUNIT $OUT/ui.junit.xml $OUT/swapped.junit.xml
python -m psdaq.webgui.parity.check_parity --junit $OUT/swapped.junit.xml --walk $WALK > $OUT/parity.txt 2>&1; echo PARITY_EMU_EXIT=$?
grep -E 'controls found|^Mapped but test|^  CGWMainControl.but_(transition|ctrls) |^RESULT' $OUT/parity.txt | cut -c1-200
