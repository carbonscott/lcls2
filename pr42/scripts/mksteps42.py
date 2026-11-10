#!/usr/bin/env python3
"""Write redo/steps/pr42-term.json: the recorded proof of PR 42 (pr/final) at its head c370014fc."""
import json, sys
TAG = sys.argv[1] if len(sys.argv) > 1 else 'm1'
steps = []
def s(send, expect=None, timeout=None, **kw):
    d = {'send': send}
    if expect: d['expect'] = expect
    if timeout: d['timeout'] = timeout
    d.update(kw)
    steps.append(d)
C = ' | cut -c1-138'
s('date -Is; hostname   # this machine: the exe.dev VM')
s('ssh -t sdfiana025 bash --rcfile $R/work/proof15/rc.sh -i', expect=r'cwang31@sdfiana025', timeout=180)
s("hostname; date '+%F %T %Z'; date -u '+%FT%TZ'; echo \"S=$S\"; echo \"S2=$S2\"")
s("squeue -u $USER -j 44000948,43970564,44016690 -o '%.9i %.18N %.20e %.14j'   # the campaign's Slurm jobs (end times PST)")
s('# every node command below is its own Slurm step: $S on sdfmilan023, $S2 on sdfmilan082; the matrix adds steps on sdfmilan082 and sdfada013')
s("git log -1 --format='%H%n%ad%n%s' --date=iso" + C + "; echo \"local changes (tracked and untracked): $(git status --short | wc -l)\"")
s("git log --first-parent --format='%h %s' 5aaf09617..HEAD" + C)
s('git diff --stat 29f1be4a7 HEAD   # 29f1be4a7 = the head the last full matrix ran at; this head adds only the changelog link to #42')
s('git diff --stat 5aaf09617 HEAD | tail -1   # the whole PR against its base, agentify at 5aaf09617')
s('source ./setup_env_daq.sh >/dev/null 2>&1; source psdaq/psdaq/sim/sim_env.sh; echo "DAQ env $CONDA_DEFAULT_ENV, $(python --version)"')
s('# The build at this HEAD (build_all.sh -d with CUDA 12.9 on PATH, sdfada011 step 39, before this recording): ninja has nothing left to do')
s("cat $Q/buildinc.out" + C + "; ninja -n -C builddir | tail -1; ls install/bin/drp install/bin/drp_gpu; echo \"GPU libs: $(ls install/lib | grep -c '_gpu\\.so$')\"")
s('for d in sim webgui control configdb; do diff -rq -x __pycache__ psdaq/psdaq/$d install/lib/python3.9/site-packages/psdaq/$d && echo "installed psdaq/$d == checkout"; done')
s('# The sim unit tests and test_walk_guard at this HEAD (one step on sdfmilan082, under its DAQ lock)')
s('$S2 bash $Q/pyt2.sh $R/wt-final 2>&1 | grep -v -E "Warning|warnings.warn|fixture|^ *$|scope"' + C, expect=r'PYTEST_EXIT=\d+', timeout=2400)
s('# THE matrix (RUNBOOK 3p), one command in one step on sdfmilan023: mx.sh = the env lines and the daq_sim matrix line')
s("sed \"s#$R#\\$R#g\" $Q/mx.sh | fold -w 138")
s(f'# Run: 21 drp types over sdfmilan023+082, 5 drp_gpu types on sdfada013 (GPU), programs, features a-e, coverage. Pane: the lines $MXF picks')
s(f'$S bash $Q/mx.sh {TAG} sdfada013 43970564 2>&1 | tee $Q/mx-{TAG}.log | grep --line-buffered -E "$MXF" | short',
  expect=r'^MATRIX_EXIT=\d+', timeout=6000)
s(f"grep -c '^  PASS ' $Q/mx-{TAG}.log; grep -E '^MATRIX|^whole|^MATRIX_EXIT' $Q/mx-{TAG}.log; ls -l $Q/mx-{TAG}/programs/ami-shot.png $Q/mx-{TAG}/features/c/ami-shot.png | short")
s(f'python -c "import json,sys; d=json.load(open(sys.argv[1])); print(d[\'sha\'], d[\'exit\'], d[\'whole\'], d[\'assertions\'] if not isinstance(d[\'assertions\'], list) else len(d[\'assertions\']))" $Q/mx-{TAG}/matrix-summary.json' + C)
s('# Coverage negative: a COPY of the evidence without the records that list det:drp:epix100 must fail naming that row; the evidence itself passes')
s(f'$S bash $Q/covneg.sh $Q/mx-{TAG}-ev det:drp:epix100 2>&1 | short', expect=r"COVERAGE over the matrix's evidence: exit \d+", timeout=1200)
s('# The three deliberate breaks (matrix --break register|kill-drp|corrupt, sdfmilan023, its lock): each must exit nonzero naming the assertion')
s('$S bash $Q/brk.sh b1 2>&1 | short', expect=r'=== breaks done', timeout=3600)
s('# Hardware path (no simulated device): the union of the branches\' scripts, base 5aaf09617 vs this HEAD (hwall.sh, sdfada013 GPU step, before this recording)')
s('cat $Q/hwall15.log' + C)
s('for f in $Q/hw/*.diff; do cmp -s $f $R/work/finalinteg/hw/$(basename $f) && echo "$(basename $f): $(wc -l < $f) lines, the same as at 29f1be4a7" || echo "$(basename $f): DIFFERS from 29f1be4a7"; done')
s("cat $Q/hw/typesfix-hwx.diff" + C + "; grep -E '^(==|diff|DIFF)' $Q/hw/bh-tail2.log $Q/hw/bh-tail3.log" + C)
s("echo \"local changes: $(git status --short | wc -l)\"; git rev-parse HEAD; date '+%F %T %Z'")
s('exit', expect=r'exedev@', timeout=60)
out = '/home/exedev/projects/lcls2/redo/steps/pr42-term.json'
json.dump(steps, open(out, 'w'), indent=1)
print(f'{len(steps)} steps -> {out}')
