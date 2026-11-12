#!/bin/bash
# f13pr tot.sh: one line per STEP 3 run (F13 before at e223e91cb, after at 82a2868fe, guardrails)
F=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-daq-hardening/work/f13pr; cd $F
for t in b-fc1 b-fc2 b-fc3 b-fc4 b-fc5 a-fc1 a-fc2 a-fc3 a-fc4 a-fc5 a-fc6 a-fc7 a-fc8 a-fc9 a-fc10 a-tt1 a-tt2 a-tt3 b-pg1 b-pg2 a-pg1 g-hang g-dead2; do
  B=$(grep -a -m1 -o 'builds/[0-9a-f]*' $t.log)
  A=$(grep -a -o -E 'STOP pid [0-9]+|KILL pid [0-9]+' $t.watch | head -2 | tr '\n' ' ')
  R=$(grep -a -h -o -E '[A-Za-z0-9_]+ ready for transitions after [0-9]+ s' $t.log | grep -v -E '^(fakecam|pvcam|encoder)_0 .* 0 s' | head -1)
  M=$(grep -a -h -o -E 'drp/[a-z0-9_]+ did not respond to rollcall|up FAILED: [a-z0-9_]+ not ready for transitions [^:]*' $t.log | head -1)
  echo "$t ${B#builds/} ${A:-no-watcher-action} | ${R:-} ${M:-} | $(grep -a '^MATRIX \(PASS\|FAIL\)' $t.log) | $(grep -a -o 'MATRIX_EXIT=[0-9]*' $t.log)"
done
