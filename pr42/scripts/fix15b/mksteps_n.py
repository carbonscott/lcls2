#!/usr/bin/env python3
"""Write redo/steps/pr42-term5-TAG.json (fix15b, as fix15's mksteps_h.py): at the PR head H2 (the MEB counter retry,
simsls' flow control, docs, after b14885af3): the build check, the sim unit tests' result, the UDP loss before/after,
cuInit on the GPU node, THE matrix (mx.sh), then (with --negatives) the coverage negative and the three breaks.
usage: mksteps_n.py TAG GPUHOST GPUJOB [--negatives | --covneg] [--rerun 'COMMENT']: --rerun leaves out the build, test and loss
steps (they are in the first recording) and types COMMENT (why this run) before the cuInit step."""
import json, sys
TAG, GH, GJ = sys.argv[1], sys.argv[2], sys.argv[3]
NEG = '--negatives' in sys.argv
RERUN = sys.argv[sys.argv.index('--rerun') + 1] if '--rerun' in sys.argv else None
G = '$G' if GH == 'sdfada010' else '$G13'
steps = []
def s(send, expect=None, timeout=None, **kw):
    d = {'send': send}
    if expect: d['expect'] = expect
    if timeout: d['timeout'] = timeout
    d.update(kw); steps.append(d)
C = ' | cut -c1-138'
s('date -Is; hostname   # this machine: the exe.dev VM')
s('ssh -t sdfiana025 bash --rcfile $R/work/fix15b/rc.sh -i', expect=r'cwang31@sdfiana025', timeout=180)
s("hostname; date '+%F %T %Z'; date -u '+%FT%TZ'; echo \"S=$S\"; echo \"S2=$S2\"; echo \"G=$G\"; squeue -u $USER -j 44000948,44062096,43970564 -o '%.9i %.18N %.20e %.14j'")
s("git log -1 --format='%H %ad %s' --date=iso" + C + "; git rev-parse --abbrev-ref HEAD; echo \"local changes (tracked and untracked): $(git status --short | wc -l)\"")
s('# The PR head before these fixes was b14885af3 (pushed). Three commits since: MEB counter retry, simsls flow control, docs')
s("git log --format='%h %s' b14885af3..HEAD" + C + "; git diff --stat b14885af3 HEAD | short")
s('source ./setup_env_daq.sh >/dev/null 2>&1; source psdaq/psdaq/sim/sim_env.sh; echo "DAQ env $CONDA_DEFAULT_ENV, $(python --version)"')
if RERUN:
    s(RERUN)
else:
    s("tail -2 $Q/build-H2.out | head -1; head -1 $Q/build-H2.out | short; ninja -n -C builddir | tail -1; for d in sim webgui control configdb; do diff -rq -x __pycache__ psdaq/psdaq/$d install/lib/python3.9/site-packages/psdaq/$d && echo \"installed psdaq/$d == checkout\"; done")
    s('# The sim unit tests and test_walk_guard at this HEAD ran in one step on sdfmilan082 (pyt.sh all); its output:')
    s("grep -v -E 'Warning|warnings.warn|fixture|^ *$|scope' $Q/pyt-H2.out | short")
    s('# drp_gpu jungfrau, UDP loss: 3 runs of its matrix type cycle on sdfada010 at b14885af3 (before) and at this HEAD (after)')
    s("cat $Q/loss.sh | sed -n '2,6p' | short")
    s("for t in before-gpu after-gpu before-cpu after-cpu; do grep -E '^=== loss .*: drp|^RUN ' $Q/lossrun-$t.out | sed -E 's/ on sdf.*HEAD / HEAD /; s/ job [0-9]+ step / step /' | short; done")
    s("grep -h 'TYPE ' $Q/loss-after-gpu-*.log | sed -E 's# run /[^ ]+##' | sort -u | short; grep -rh 'receiver buffer' $Q/loss-after-gpu-1/ | cut -c1-20,150-330")
s(f'# cuInit on {GH}\'s GPU (job {GJ}), 3 fresh processes, no DAQ')
s(f'{G} bash $Q/cuinit.sh 2>&1 | short', expect=r'(cuCtxCreate rc=[\s\S]*){3}|rror', timeout=600)
s(f'# THE matrix: mx.sh (fix15\'s, only its output dir changed), the GPU DRP\'s types on {GH} (job {GJ}), tag {TAG}')
s("diff $R/work/fix15/mx.sh $Q/mx.sh | short")
s(f'$S bash $Q/mx.sh {TAG} {GH} {GJ} 2>&1 | tee $Q/mx-{TAG}.log | grep --line-buffered -E "$MXF" | short',
  expect=r'^MATRIX_EXIT=\d+', timeout=6000)
s(f"grep -c '^  PASS ' $Q/mx-{TAG}.log; grep -E '^MATRIX |^whole|^MATRIX_EXIT' $Q/mx-{TAG}.log | short; ls -l $Q/mx-{TAG}/programs/ami-shot.png $Q/mx-{TAG}/features/c/ami-shot.png | short")
s(f'python -c "import json,sys; d=json.load(open(sys.argv[1])); print(d[\'sha\'], \'exit\', d[\'exit\'], d[\'whole\'], len(d[\'assertions\']), \'assertions\')" $Q/mx-{TAG}/matrix-summary.json | short')
s(f"grep -h 'ready for transitions after' $Q/mx-{TAG}.log | short; grep -h 'feature c|.*counts after Disable' $Q/mx-{TAG}.log | grep -o \"'MEB_EvtCt': [0-9]*\\|prometheus unread[^,]*\" | head -3")
s(f"grep -rh 'exiting: status' $Q/mx-{TAG}/gpu/*/types/jungfrau/ $Q/mx-{TAG}/types/jungfrau/ 2>/dev/null | grep -o \"'frames.*\" | short; grep -rhc 'sent .* of 128 packets' $Q/mx-{TAG}/gpu/*/types/jungfrau/pmlogs $Q/mx-{TAG}/types/jungfrau/pmlogs 2>/dev/null | paste -sd' '")
if NEG or '--covneg' in sys.argv:
    s('# Coverage negative over this run\'s evidence: a COPY without the records that list det:drp:epix100 must fail naming that row')
    s(f'$S bash $Q/covneg.sh $Q/mx-{TAG}-ev det:drp:epix100 2>&1 | short', expect=r"COVERAGE over the matrix's evidence: exit \d+", timeout=1200)
if NEG:
    s('# The three deliberate breaks (sdfmilan023, under its lock): each must exit 1 naming the failed assertion')
    s(f'$S bash $Q/brk.sh {TAG} 2>&1 | short', expect=r'=== breaks done', timeout=2400)
    s("git diff --stat b14885af3 HEAD | short")
s("echo \"local changes: $(git status --short | wc -l)\"; git rev-parse HEAD; date '+%F %T %Z'")
s('exit', expect=r'exedev@', timeout=60)
out = f'/home/exedev/projects/lcls2/redo/steps/pr42-term{6 if RERUN else 5}-{TAG}.json'
json.dump(steps, open(out, 'w'), indent=1); print(f'{len(steps)} steps -> {out}')
