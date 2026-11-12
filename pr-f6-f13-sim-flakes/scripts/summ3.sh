#!/bin/bash
# f13pr summ3.sh TAG...: one block per STEP 3 run, from its log and watcher log
F=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-daq-hardening/work/f13pr
for T in "$@"; do
  L=$F/$T.log; W=$F/$T.watch
  echo "## $T"
  grep -a -m1 '^=== ' $L | cut -c1-200
  grep -a -E 'SEEN|STOP|CONT|KILL|gone|NEVER' $W | sed 's/: \/sdf.*bin\/\([a-zA-Z_]*\) \(.*\)/: \1 \2/' | cut -c1-170
  grep -a -h -E 'procmgr start|ready for transitions|did not respond to rollcall|at least one DRP is required|up FAILED|not RUNNING after' $L | awk '!s[$0]++' | cut -c1-260
  grep -a -E '^(TYPE|PROGRAMS)' $L | head -1 | sed 's/ run [^ ]* / run ... /' | cut -c1-200
  grep -a -E '^FAILED' $L | awk '!s[$0]++' | cut -c1-220
  grep -a -E '^MATRIX (PASS|FAIL)|^MATRIX_EXIT' $L
done
