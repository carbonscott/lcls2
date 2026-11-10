#!/usr/bin/env python3
"""Write redo/steps/pr42-term3.json: at the new PR head H (the D2, D3 and docs fixes after 7695dfdae): the build check,
the sim unit tests, cuInit on sdfada010, THE matrix (mx.sh, GPU types on sdfada010), the coverage negative, the
forgeries FG1-FG3, the three breaks."""
import json, sys
TAG = sys.argv[1] if len(sys.argv) > 1 else 'h1'
GH, GJ = (sys.argv[2], sys.argv[3]) if len(sys.argv) > 3 else ('sdfada010', '44062096')
steps = []
def s(send, expect=None, timeout=None, **kw):
    d = {'send': send}
    if expect: d['expect'] = expect
    if timeout: d['timeout'] = timeout
    d.update(kw); steps.append(d)
C = ' | cut -c1-138'
F = ' | grep -v -E "Warning|warnings.warn|fixture|^ *$|scope" | short'
s('date -Is; hostname   # this machine: the exe.dev VM')
s('ssh -t sdfiana025 bash --rcfile $R/work/fix15/rc.sh -i', expect=r'cwang31@sdfiana025', timeout=180)
s("hostname; date '+%F %T %Z'; date -u '+%FT%TZ'; echo \"S=$S\"; echo \"S2=$S2\"; echo \"G=$G\"; squeue -u $USER -j 44000948,44062096,43970564 -o '%.9i %.18N %.20e %.14j'")
s("git log -1 --format='%H %ad %s' --date=iso" + C + "; git rev-parse --abbrev-ref HEAD; echo \"local changes (tracked and untracked): $(git status --short | wc -l)\"")
s('# The PR head before these fixes was 7695dfdae (pushed). Three commits since: D2 (drp_gpu ready wait), D3 (one BeginRun per record), docs')
s("git log --format='%h %s' 7695dfdae..HEAD" + C + "; git diff --stat 7695dfdae HEAD | short")
s('source ./setup_env_daq.sh >/dev/null 2>&1; source psdaq/psdaq/sim/sim_env.sh; echo "DAQ env $CONDA_DEFAULT_ENV, $(python --version)"')
s("tail -1 $Q/build-H.out; head -1 $Q/build-H.out | short; ninja -n -C builddir | tail -1; for d in sim webgui control configdb; do diff -rq -x __pycache__ psdaq/psdaq/$d install/lib/python3.9/site-packages/psdaq/$d && echo \"installed psdaq/$d == checkout\"; done")
s('# The sim unit tests and test_walk_guard at this HEAD (one step on sdfmilan082, under its DAQ lock)')
s('$S2 bash $Q/pyt.sh all 2>&1' + F, expect=r'PYTEST_EXIT=\d+', timeout=2400)
s(f'# cuInit on {GH}\'s GPU (job {GJ}), 3 fresh processes, no DAQ (sdfada013 took 28-37 s at 02:30Z; sdfada011 fails with 999)')
s('$G bash $Q/cuinit.sh 2>&1 | short', expect=r'(cuCtxCreate rc=[\s\S]*){3}|rror', timeout=600)
s(f'# THE matrix: mx.sh (proof15\'s, only its output dir changed), the GPU DRP\'s types on {GH} (job {GJ}), tag {TAG}')
s("diff $R/work/proof15/mx.sh $Q/mx.sh | short")
s(f'$S bash $Q/mx.sh {TAG} {GH} {GJ} 2>&1 | tee $Q/mx-{TAG}.log | grep --line-buffered -E "$MXF" | short',
  expect=r'^MATRIX_EXIT=\d+', timeout=6000)
s(f"grep -c '^  PASS ' $Q/mx-{TAG}.log; grep -E '^MATRIX |^whole|^MATRIX_EXIT' $Q/mx-{TAG}.log | short; ls -l $Q/mx-{TAG}/programs/ami-shot.png $Q/mx-{TAG}/features/c/ami-shot.png | short")
s(f'python -c "import json,sys; d=json.load(open(sys.argv[1])); print(d[\'sha\'], \'exit\', d[\'exit\'], d[\'whole\'], len(d[\'assertions\']), \'assertions\')" $Q/mx-{TAG}/matrix-summary.json | short')
s(f"grep -h 'ready for transitions after' $Q/mx-{TAG}.log | short")
s('# Coverage negative over this run\'s evidence: a COPY without the records that list det:drp:epix100 must fail naming that row')
s(f'$S bash $Q/covneg.sh $Q/mx-{TAG}-ev det:drp:epix100 2>&1 | short', expect=r"COVERAGE over the matrix's evidence: exit \d+", timeout=1200)
s('# A reviewer\'s forgeries, by record edits only, at this HEAD: FG2 and FG3 (now rejected: one BeginRun per record), FG1 (still passes)')
s(f'$S bash $Q/forge.sh $Q/mx-{TAG}-ev 2>&1 | short', expect=r'=== forgeries done', timeout=1200)
s('# The three deliberate breaks (sdfmilan023, under its lock): each must exit 1 naming the failed assertion')
s(f'$S bash $Q/brk.sh {TAG} 2>&1 | short', expect=r'=== breaks done', timeout=2400)
s("echo \"local changes: $(git status --short | wc -l)\"; git rev-parse HEAD; date '+%F %T %Z'")
s('exit', expect=r'exedev@', timeout=60)
out = f'/home/exedev/projects/lcls2/redo/steps/pr42-term3-{TAG}.json'
json.dump(steps, open(out, 'w'), indent=1); print(f'{len(steps)} steps -> {out}')
