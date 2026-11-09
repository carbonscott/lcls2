#!/usr/bin/env python3
"""Write redo/steps/pr39-term.json: the recorded proof of PR 39 (steps 2 and 3)."""
import json, sys
RUN = sys.argv[1] if len(sys.argv) > 1 else 'rec'
steps = []
def s(send, expect=None, timeout=None):
    d = {'send': send}
    if expect: d['expect'] = expect
    if timeout: d['timeout'] = timeout
    steps.append(d)
C = ' | cut -c1-138'
s('date -Is; hostname   # this machine: the exe.dev VM')
s('ssh -t sdfiana025 bash --rcfile $R/logs/proof39/rc.sh -i', expect=r'cwang31@sdfiana025', timeout=180)
s("hostname; date '+%F %T %Z'; echo \"S=$S\"   # every node command below is its own Slurm step on sdfmilan048: $S <script>")
s("git rev-parse HEAD; git log -1 --format='%s'" + C + "; echo \"local changes: $(git status --short --untracked-files=no | wc -l)\"")
s("git log --format='%h %s' --no-merges 8830147da..HEAD" + C)
s("git diff --stat 8830147da HEAD | tail -1; git diff --stat 8830147da HEAD -- psdaq/psdaq/configdb" + C)
s('# Step 2 at this HEAD. Build (one srun step), then the sim unit tests (one srun step)')
s(f"export P=$B/{RUN}; mkdir -p $P/ev; echo \"records in $P/ev: $(ls -A $P/ev | wc -l); work dirs in $P: $(ls -d $P/wd-* 2>/dev/null | wc -l)\"")
s("$S $B/build.sh wt-types2 > $P/build.log 2>&1; echo SRUN_EXIT=$?; grep -E '^host=|^real|BUILD_EXIT' $P/build.log" + C, expect=r'SRUN_EXIT=\d+', timeout=1200)
s('$S $B/pytest.sh' + C, expect=r'PYTEST_EXIT=\d+', timeout=1200)
s('# Each type on a fresh DAQ in its own srun step: up --det <type> --detach, cycle --events 1000, its DRP log lines, xtc2_check (as written: PASS; --self-test-offset 1: must FAIL), down')
TYPES = [
 ('opal', "ClinkDevRoot.ClinkPcie.Hsio.TimingRx.TriggerEventManager.TriggerEventBuffer[0].TriggerDelay",
  "# opal (this PR): its own opal_config on the emulated KCU, FEB and camera; the camera's serial (UART) answers come from the seed files:"),
 ('piranha4', None, "# piranha4 (this PR): its own piranha4_config; serial answers from seeds/piranha4.json (above)"),
 ('tb', "DevRoot.DevPcie.Hsio.TimingRx.TriggerEventManager.TriggerEventBuffer[3].TriggerDelay",
  "# tb (this PR): its own tb_config, with this PR's two fixes (563b4711b: the import, and tb_connectionInfo takes the alloc message)"),
 ('epixquad', "Top.SystemRegs.TrigEn=0",
  "# epixquad (this PR): its own epixquad_config with the import-order fix (6baccd060); the sim config DB adds user.pixel_map as zeros:"),
 ('fakecam', None, '# fakecam (PR #36, regression): XpmDetector, xpmdet_config'),
 ('cspad', None, '# cspad (PR #36, regression)'),
 ('epixhremu', None, '# epixhremu (PR #36, regression)'),
 ('jungfrauemu', None, '# jungfrauemu (PR #36, regression)'),
 ('ts', None, '# ts (PR #36, regression): xpmdet_config, ts_connect and ts_config on simxpm'),
 ('hrencoder', None, '# hrencoder (PR #36, regression): BEB, hrencoder_config'),
 ('epixm320', None, '# epixm320 (PR #36, regression): BEB, epixm320_config'),
 ('epix100', None, '# epix100 (PR #34, regression)'),
 ('wave8', None, '# wave8 (PR #34, regression)'),
 ('wave8he', None, '# wave8he (PR #34, regression)'),
]
for t, fault, comment in TYPES:
    s(comment)
    if t == 'opal':
        s("""python3 -c "import json; [print(t, json.load(open(f'psdaq/psdaq/sim/seeds/{t}.json'))['_uart']['replies']) for t in ('opal', 'piranha4')]\"""" + C)
    if t == 'epixquad':
        s("grep -n -A1 \"'epixquad': \\[('user.pixel_map'\" psdaq/psdaq/sim/configdb_seed.py" + C)
    f = f" '{fault}'" if fault else ''
    s(f'$S $B/typerun.sh {t} $P{f}', expect=r'TYPERUN_DONE ' + t + r' ', timeout=1800)
s('# daq_sim coverage at this HEAD over the records of these runs (bound evidence: each record proves a row only if its files show it ran)')
s('echo "records: $(ls $P/ev | wc -l)"; $S $B/cov.sh $P', expect=r'lines in cov\.txt', timeout=1800)
s("grep -E '^det:drp:[a-z0-9]+ +(RUN|STAND-IN)|^prog:(control|drp|teb|pyxpm) |^[0-9]+ rows|^status file|^(PASS|FAIL)' $P/cov.txt" + C)
s('# the same check with the tb record removed: the tb row must fail, named, exit 1')
s('$S $B/cov.sh $P det:drp:tb', expect=r'lines in cov-no-tb\.txt', timeout=1800)
s("grep -E '^det:drp:tb |^[0-9]+ rows|^(PASS|FAIL)|^  det:drp:tb' $P/cov-no-tb.txt" + C)
s('# the hardware path (no sim:// device), every type, from base wt-cov (2d9593bc5) and from this HEAD, each its own srun step; then diffed')
s("TYPES='opal piranha4 tb epixquad fakecam cspad epixhremu jungfrauemu ts hrencoder epixm320 epix100 wave8 wave8he epixhr2x2 epixquad1kfps tt epixuhr3x2'; "
  "for w in wt-cov wt-types2; do $S $B/hwpath.sh $w $TYPES > $P/hw-$w.log 2>&1; head -1 $P/hw-$w.log; done", expect=r'^== wt-types2 head=', timeout=1800)
s('diff <(tail -n +2 $P/hw-wt-cov.log) <(tail -n +2 $P/hw-wt-types2.log); echo HWPATH_DIFF_EXIT=$?; wc -l $P/hw-wt-cov.log $P/hw-wt-types2.log | head -2', expect=r'HWPATH_DIFF_EXIT=\d+', timeout=60)
s('# only tb differs: at base tb_config dies at import (ModuleNotFoundError); at this HEAD tb_init gets to the device (no /dev/datadev_0 here)')
s("for w in wt-cov wt-types2; do echo \"## $w\"; sed -n '/^-- tb python/,/^-- epixquad python/p' $P/hw-$w.log | head -12" + C + "; done")
s('# Step 3: the three config-code defects this PR fixes, at the base 8830147da (worktree wt-base39, built there, unmodified), then the same at this HEAD')
s("git -C $R/wt-base39 log -1 --format='base %H %s'" + C + "; echo \"base local changes: $(git -C $R/wt-base39 status --short --untracked-files=no | wc -l)\"")
s('W=wt-base39 $S $B/defects.sh', expect=r'DEFECTS_DONE', timeout=600)
s('$S $B/defects.sh', expect=r'DEFECTS_DONE', timeout=600)
s('git diff 8830147da HEAD -- psdaq/psdaq/configdb' + C)
s("echo \"checkout local changes: $(git status --short --untracked-files=no | wc -l)\"; date '+%F %T %Z'; exit", expect=r'exedev@', timeout=60)
json.dump(steps, open('/home/exedev/projects/lcls2/redo/steps/pr39-term.json', 'w'), indent=1)
print(len(steps), 'steps')
