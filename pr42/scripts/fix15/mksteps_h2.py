#!/usr/bin/env python3
"""Write redo/steps/pr42-term4-<tag>.json: THE matrix once more at H (no code change), the GPU DRP's types on sdfada013
(job 43970564, a GPU shared with another user's jobs) after run h1's only failure, drp_gpu jungfrau's per-event check
(UDP packets of 5 frames lost on loopback on sdfada010); then the coverage negative and the forgeries over its evidence."""
import json, sys
TAG = sys.argv[1] if len(sys.argv) > 1 else 'h2'
steps = []
def s(send, expect=None, timeout=None, **kw):
    d = {'send': send}
    if expect: d['expect'] = expect
    if timeout: d['timeout'] = timeout
    d.update(kw); steps.append(d)
C = ' | cut -c1-138'
s('date -Is; hostname   # this machine: the exe.dev VM')
s('ssh -t sdfiana025 bash --rcfile $R/work/fix15/rc.sh -i', expect=r'cwang31@sdfiana025', timeout=180)
s("hostname; date '+%F %T %Z'; date -u '+%FT%TZ'; echo \"S=$S\"; echo \"G13=$G13\"; squeue -u $USER -j 44000948,44062096,43970564 -o '%.9i %.18N %.20e %.14j'")
s("git log -1 --format='%H %ad %s' --date=iso" + C + "; git rev-parse --abbrev-ref HEAD; echo \"local changes (tracked and untracked): $(git status --short | wc -l)\"")
s('source ./setup_env_daq.sh >/dev/null 2>&1; source psdaq/psdaq/sim/sim_env.sh; ninja -n -C builddir | tail -1; for d in sim webgui; do diff -rq -x __pycache__ psdaq/psdaq/$d install/lib/python3.9/site-packages/psdaq/$d && echo "installed psdaq/$d == checkout"; done')
s('# Run h1 at this HEAD failed only drp_gpu jungfrau (per-event: UDP packets of 5 frames lost on sdfada010) and its coverage row:')
s("grep -E '^MATRIX |^MATRIX_EXIT' $Q/mx-h1.log | short; grep -h 'of 128 packets of frame' $Q/mx-h1/gpu/sdfada010/types/jungfrau/pmlogs/*/*/*jungfrau_0.log | short")
s('# No code change. The same matrix once more, the GPU DRP\'s types on sdfada013 (job 43970564; its GPU is shared with another user\'s jobs)')
s('$G13 bash $Q/cuinit.sh 2>&1 | short', expect=r'(cuCtxCreate rc=[\s\S]*){3}|rror', timeout=900)
s(f'$S bash $Q/mx.sh {TAG} sdfada013 43970564 2>&1 | tee $Q/mx-{TAG}.log | grep --line-buffered -E "$MXF" | short',
  expect=r'^MATRIX_EXIT=\d+', timeout=6000)
s(f"grep -c '^  PASS ' $Q/mx-{TAG}.log; grep -E '^MATRIX |^whole|^MATRIX_EXIT' $Q/mx-{TAG}.log | short; ls -l $Q/mx-{TAG}/programs/ami-shot.png $Q/mx-{TAG}/features/c/ami-shot.png | short")
s(f'python -c "import json,sys; d=json.load(open(sys.argv[1])); print(d[\'sha\'], \'exit\', d[\'exit\'], d[\'whole\'], len(d[\'assertions\']), \'assertions\')" $Q/mx-{TAG}/matrix-summary.json | short')
s('# D2 at work: how long each drp_gpu took to say Ready for transitions on sdfada013 (up waits for it, up to 300 s)')
s(f"grep -h 'ready for transitions after' $Q/mx-{TAG}.log | short")
s('# Coverage negative over this run\'s evidence: a COPY without the records that list det:drp:epix100 must fail naming that row')
s(f'$S bash $Q/covneg.sh $Q/mx-{TAG}-ev det:drp:epix100 2>&1 | short', expect=r"COVERAGE over the matrix's evidence: exit \d+", timeout=1200)
s('# A reviewer\'s forgeries, by record edits only, over this run\'s programs record: FG2 and FG3 now rejected (one BeginRun per record), FG1 still passes')
s(f'$S bash $Q/forge.sh $Q/mx-{TAG}-ev 2>&1 | short', expect=r'=== forgeries done', timeout=1200)
s("echo \"local changes: $(git status --short | wc -l)\"; git rev-parse HEAD; date '+%F %T %Z'")
s('exit', expect=r'exedev@', timeout=60)
out = f'/home/exedev/projects/lcls2/redo/steps/pr42-term4-{TAG}.json'
json.dump(steps, open(out, 'w'), indent=1); print(f'{len(steps)} steps -> {out}')
