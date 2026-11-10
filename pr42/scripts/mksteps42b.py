#!/usr/bin/env python3
"""Write redo/steps/pr42-term2.json: THE matrix again at the PR's head (7695dfdae), after m1 (recording 1) failed 3 types
and the head moved during it (7695dfdae: CHANGELOG links only)."""
import json, sys
TAG = sys.argv[1] if len(sys.argv) > 1 else 'm2'
steps = []
def s(send, expect=None, timeout=None, **kw):
    d = {'send': send}
    if expect: d['expect'] = expect
    if timeout: d['timeout'] = timeout
    d.update(kw); steps.append(d)
C = ' | cut -c1-138'
s('date -Is; hostname   # this machine: the exe.dev VM')
s('ssh -t sdfiana025 bash --rcfile $R/work/proof15/rc2.sh -i', expect=r'cwang31@sdfiana025', timeout=180)
s("hostname; date '+%F %T %Z'; date -u '+%FT%TZ'; echo \"S=$S\"; echo \"S2=$S2\"; squeue -u $USER -j 44000948,43970564,44016690 -o '%.9i %.18N %.20e %.14j'")
s("git log -3 --format='%H %ad %s' --date=iso" + C + "; echo \"local changes (tracked and untracked): $(git status --short | wc -l)\"; git ls-remote origin pr/final agentify")
s('# The PR head moved during recording 1 (its m1 run started at c370014fc): 7695dfdae changes only CHANGELOG.md. Everything below runs at 7695dfdae')
s('git diff --stat c370014fc HEAD; git diff --stat 29f1be4a7 HEAD; git diff --stat 5aaf09617 HEAD | tail -1')
s('source ./setup_env_daq.sh >/dev/null 2>&1; source psdaq/psdaq/sim/sim_env.sh; echo "DAQ env $CONDA_DEFAULT_ENV, $(python --version)"')
s("ninja -n -C builddir | tail -1; for d in sim webgui control configdb; do diff -rq -x __pycache__ psdaq/psdaq/$d install/lib/python3.9/site-packages/psdaq/$d && echo \"installed psdaq/$d == checkout\"; done")
s('# The sim unit tests and test_walk_guard at this HEAD (one step on sdfmilan082, under its DAQ lock)')
s('$S2 bash $Q/pyt2.sh $R/wt-final 2>&1 | grep -v -E "Warning|warnings.warn|fixture|^ *$|scope" | short', expect=r'PYTEST_EXIT=\d+', timeout=2400)
s('# m1 (recording 1) ended MATRIX FAIL, 15 of 201: epixquad1kfps (its DRP aborted 1 s into Running), drp_gpu epixuhremu and jungfrau, and coverage')
s(f"grep -E '^FAILED' $Q/mx-m1.log | cut -d: -f1 | sort | uniq -c | short; grep -h '_pending queue overflow' $Q/mx-m1/types/epixquad1kfps/pmlogs/*/*/*epixquad1kfps_0.log | short")
s('# No code changed. The same command (mx.sh, unchanged since before m1) once more, tag m2:')
s("ls -l --time-style=+%FT%T%z $Q/mx.sh | short")
s(f'$S bash $Q/mx.sh {TAG} sdfada013 43970564 2>&1 | tee $Q/mx-{TAG}.log | grep --line-buffered -E "$MXF" | short',
  expect=r'^MATRIX_EXIT=\d+', timeout=6000)
s(f"grep -c '^  PASS ' $Q/mx-{TAG}.log; grep -E '^MATRIX |^whole|^MATRIX_EXIT' $Q/mx-{TAG}.log | short; ls -l $Q/mx-{TAG}/programs/ami-shot.png $Q/mx-{TAG}/features/c/ami-shot.png | short")
s(f'python -c "import json,sys; d=json.load(open(sys.argv[1])); print(d[\'sha\'], \'exit\', d[\'exit\'], d[\'whole\'], len(d[\'assertions\']), \'assertions\')" $Q/mx-{TAG}/matrix-summary.json | short')
s('# Coverage negative over this run\'s evidence: a COPY without the records that list det:drp:epix100 must fail naming that row; the evidence itself passes')
s(f'$S bash $Q/covneg.sh $Q/mx-{TAG}-ev det:drp:epix100 2>&1 | short', expect=r"COVERAGE over the matrix's evidence: exit \d+", timeout=1200)
s("echo \"local changes: $(git status --short | wc -l)\"; git rev-parse HEAD; git ls-remote origin pr/final; date '+%F %T %Z'")
s('exit', expect=r'exedev@', timeout=60)
out = '/home/exedev/projects/lcls2/redo/steps/pr42-term2.json'
json.dump(steps, open(out, 'w'), indent=1); print(f'{len(steps)} steps -> {out}')
