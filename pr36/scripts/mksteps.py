#!/usr/bin/env python3
"""mksteps.py OUT.json: write the recdrive.py step file of the XpmDetector PR's recorded node shell."""
import json, sys

C = ' | cut -c1-138'
S = []


def step(send, expect=None, timeout=None, **kw):
    s = {'send': send}
    if expect:
        s['expect'] = expect
    if timeout:
        s['timeout'] = timeout
    s.update(kw)
    S.append(s)


def up(t, n=None, extra='', pre='', show=r'PREFLIGHT|UP\.| frame \('):
    n = n or t
    step(f"T={t}; {pre}daq_sim up -w $P/wd-{n} --det $T{extra} --detach > $P/up-{n}.log 2>&1; echo UP_EXIT=$?; "
         f"grep -E '{show}' $P/up-{n}.log{C}", r'UP_EXIT=\d+', 400)


CYCLE_SHOW = r"'^  (simxpm NumL0Acc|TEB_WrtCt|xtc2 file|psana2 (events|with data|checks)|equal) |evidence |cycle (PASS|FAIL)'"


def cycle(n, show=CYCLE_SHOW, timeout=400):
    step(f"daq_sim cycle -w $P/wd-{n} --events 1000 > $P/cycle-{n}.log 2>&1; echo CYCLE_EXIT=$?; "
         f"grep -E {show} $P/cycle-{n}.log{C}", r'CYCLE_EXIT=\d+', timeout)


def drplog(n, pat, procs='${T}_0'):
    step(f"grep -h -E '{pat}' $P/wd-{n}/pmlogs/*/*/*:{procs}.log{C}")


def faultlog(n):
    step(f"grep -h -o -E 'rogue_dev: FAULT .*|Verify error for block .*|\\*\\*\\*\\* python error|killed by signal [0-9]+' "
         f"$P/wd-{n}/pmlogs/*/*/*:${{T}}_0.log | sort | uniq -c{C}")


def check(n):
    # the file the cycle's own psana2 read names (with --segments 2, segment 0's is not -s000)
    step(f"F=$(awk '/^  xtc2 file/{{print $3}}' $P/cycle-{n}.log); for a in '' '--self-test-offset 1'; do "
         f"echo \"== xtc2_check $(basename $F) --det $T --seed 0x1234 $a\"; python -m psdaq.sim.xtc2_check $F "
         f"--det $T --seed 0x1234 $a 2>&1 | grep -v '^Rogue'{C}; echo rc=${{PIPESTATUS[0]}}; done",
         r'^rc=\d+\s*$[\s\S]*^rc=\d+\s*$', 900)


def down(n, after=''):
    step(f"daq_sim down -w $P/wd-{n} > $P/down-{n}.log 2>&1; echo DOWN_EXIT=$?; tail -1 $P/down-{n}.log{C}{after}",
         r'DOWN_EXIT=\d+', 300)


XPMDET = (r'XpmDetector:|XPM remote link id|MemPoolSim: (readout group|ts data)|payload seed|'
          r'rxready|RxLink locked|link enables|(EpixHRemu|JungfrauEmulator) configure')
OWN = {
    'hrencoder': (r'BEBDetector: .*config runs|^hrencoder_(init|connect|config)$|^ConfigLclsTimingV2\(\)$|'
                  r'StopRun|StartRun|delay_clks|link id .* from simxpm|sim payload seed|rogue_dev'),
    'epixm320': (r'BEBDetector: .*config runs|rxId .* found|link id .* from simxpm|sim payload seed|'
                 r'Init ASIC script|Initialization routine|Triggers sent|lane adjustment|config_expert complete|rogue_dev'),
    'epix100': r'config runs against|FpgaVersion|check clock rate|Loading camera|sim payload seed',
    'wave8': r'config runs against|_connect returning|sim payload seed|^base ',
    'wave8he': r'config runs against|_connect returning|sim payload seed|^base ',
}
NOTE = {
    'fakecam': 'fakecam: XpmDetector; its DRP now runs xpmdet_config against an emulated TDet receiver (it skipped it under sim:// before)',
    'cspad': 'cspad: XpmDetector (an AreaDetector, as fakecam), xpmdet_config only; psana reads it as cspad_raw_2_0_0',
    'epixhremu': 'epixhremu: XpmDetector, xpmdet_config only; the emulator replays the frame up writes from the seed',
    'jungfrauemu': 'jungfrauemu: XpmDetector, xpmdet_config only; one 512 x 1024 panel of TDet words per event',
    'ts': "ts: XpmDetector, xpmdet_config and its own ts_config (ts_connect at Connect, ts_config at Configure) on simxpm's PVs",
    'hrencoder': "hrencoder: BEB, its own hrencoder_config (the KCU and the encoder board over SRPv3, on rogue_dev)",
    'epixm320': "epixm320: BEB, its own epixm320_config (the KCU and the camera over SRPv3, its fnInitAsicScript)",
    'epix100': 'epix100 (from PR #34, regression)',
    'wave8': 'wave8 (from PR #34, regression)',
    'wave8he': 'wave8he (from PR #34, regression)',
}

step("date -Is; hostname   # this machine: the exe.dev VM")
step("ssh -t sdfiana025 srun --jobid=43839059 --overlap --ntasks=1 --cpus-per-task=16 --mem=32G --pty bash "
     "--rcfile $R/redo/p36/node_rc.sh -i", 'cwang31@sdfmilan048', 180)
step("hostname; date '+%F %T %Z'; echo \"Slurm job $SLURM_JOB_ID step $SLURM_STEP_ID\"; "
     "ls /dev/datadev* /dev/pcie_adc* /dev/tpr* 2>&1 | head -3")
step("cd $R/wt-xpm && git rev-parse HEAD && git log --format='%h %s' ec06569d9..HEAD | cut -c1-138 && "
     "echo \"local changes: $(git status --short | wc -l)\"")
step("git diff --stat 0d04b2ab8 HEAD | tail -1; echo \"files this PR changes under psdaq/psdaq/configdb "
     "(the types' config code): $(git diff --name-only 0d04b2ab8 HEAD -- psdaq/psdaq/configdb | wc -l)\"")
step("source ./setup_env_daq.sh >/dev/null 2>&1; source psdaq/psdaq/sim/sim_env.sh; "
     "echo \"DAQ env $CONDA_DEFAULT_ENV, $(python --version)\"")
step("# The build is this HEAD's (build_all.sh at this HEAD in Slurm step 248): ninja has nothing to do, "
     "and the installed python is the checkout's")
step("grep -E '^host=|BUILD_EXIT' $Q/build.log | cut -c1-138; ninja -n -C builddir | tail -1; "
     "for d in psdaq/sim psdaq/configdb psana/detector; do diff -rq -x __pycache__ ${d%%/*}/$d "
     "install/lib/python3.9/site-packages/$d && echo \"installed $d == checkout\"; done")
step("# (a) unit tests: coverage, rogue_dev, the framer, config DB seeding, simxpm, the XpmDetector types")
step("python -m pytest -q -p no:cacheprovider psdaq/psdaq/tests/test_sim_coverage.py psdaq/psdaq/tests/test_sim_rogue_dev.py "
     "psdaq/psdaq/tests/test_sim_framer.py psdaq/psdaq/tests/test_sim_configdb_seed_store.py psdaq/psdaq/tests/test_sim_configdb.py "
     "psdaq/psdaq/tests/test_sim_lgbk.py psdaq/psdaq/tests/test_simxpm.py psdaq/psdaq/tests/test_sim_xpmdet_types.py "
     "2>&1 | grep -E ' (passed|failed|error)'", timeout=900)
step("# (b) each type on a fresh DAQ: daq_sim up --det <type> --detach, cycle --events 1000, its DRP's log lines, "
     "the per-event check (as written: PASS; --self-test-offset 1: must FAIL), down. New work dirs, a new, empty evidence dir")
step("export P=$Q/take1 DAQ_SIM_EVIDENCE=$Q/take1/ev; mkdir -p $DAQ_SIM_EVIDENCE; echo \"records in $DAQ_SIM_EVIDENCE: "
     "$(ls -A $DAQ_SIM_EVIDENCE | wc -l); work dirs in $P: $(ls -d $P/wd-* 2>/dev/null | wc -l)\"")
for t in ('fakecam', 'cspad', 'epixhremu', 'jungfrauemu', 'ts', 'hrencoder', 'epixm320', 'epix100', 'wave8', 'wave8he'):
    step('# ' + NOTE[t])
    up(t)
    cycle(t)
    drplog(t, OWN.get(t, XPMDET))
    check(t)
    down(t)

step("# (c) fakecam --segments 2: two DRPs, segments 0 and 1 of one detector, each running xpmdet_config; "
     "the check reads the file the cycle names (segment 0's)")
up('fakecam', 'fakecam-seg2', ' --segments 2', show=r'PREFLIGHT|UP\.')
step("grep -o \"pids {.*}\" $P/up-fakecam-seg2.log")
cycle('fakecam-seg2', show=r"'\[fileReport\] .*/tstx|^  (simxpm NumL0Acc|TEB_WrtCt|xtc2 file|psana2 (events|with data|checks)|equal) |evidence |cycle (PASS|FAIL)'")
step("for s in 0 1; do grep -h -E 'XpmDetector:|barrier|<I> Opening file .*-c000.xtc2' $P/wd-fakecam-seg2/pmlogs/*/*/*:fakecam_$s.log "
     "| sed \"s#^#fakecam_$s: #; s#'/sdf/.*/xtc/#'.../xtc/#\"" + C + "; done")
check('fakecam-seg2')
down('fakecam-seg2')

step("# (d) a fault per config path. xpmdet_config: TDetSemi.Length_0 reads back wrong, so Connect (xpmdet_connect) must fail and name it")
step("echo \"evidence records before the fault runs: $(ls $DAQ_SIM_EVIDENCE | wc -l)\"")
up('fakecam', 'fault-xpmdet', pre='PSDAQ_SIM_ROGUE_FAULT=DrpTDet.PcieControl.DevPcie.TDetSemi.Length_0 ', show=r'PREFLIGHT|UP\.')
cycle('fault-xpmdet', show=r"'setState|\[error\]|cycle (PASS|FAIL)'", timeout=500)
faultlog('fault-xpmdet')
down('fault-xpmdet')
step("# hrencoder_config: its trigger delay register reads back wrong, so Configure (config_expert's write-verify) must fail and name it")
up('hrencoder', 'fault-hrencoder', show=r'PREFLIGHT|UP\.',
   pre="PSDAQ_SIM_ROGUE_FAULT='Root.App.TimingRx.TriggerEventManager.TriggerEventBuffer[0].TriggerDelay' ")
cycle('fault-hrencoder', show=r"'setState|\[error\]|cycle (PASS|FAIL)'", timeout=500)
faultlog('fault-hrencoder')
down('fault-hrencoder', after="; echo \"evidence records after the fault runs: $(ls $DAQ_SIM_EVIDENCE | wc -l)\"")

step("# (e) daq_sim coverage at this head with this shell's 11 records: the det rows, then the summary")
step("daq_sim coverage > $P/cov.txt; echo COVERAGE_EXIT=$?; wc -l < $P/cov.txt; sed -n '/^row /,/^det:drp_gpu:jungfrau /p' $P/cov.txt" + C,
     r'COVERAGE_EXIT=\d+', 300)
step("grep -E '^evidence:|^prog:(control|drp|teb|pyxpm) |^[0-9]+ rows|^status file|^(PASS|FAIL)' $P/cov.txt" + C +
     "; echo \"UNPROVEN rows: $(grep -c ' UNPROVEN ' $P/cov.txt)\"")
step("# 61 rows UNPROVEN is expected at this PR (no run for them yet), so the check ends FAIL, exit 1")
step("# (f) a RUN row whose record is gone: a copy of the evidence dir without the ts record")
step("python3 $Q/mutate.py $DAQ_SIM_EVIDENCE $P/ev-removed det:drp:ts remove" + C)
step("daq_sim coverage --evidence $P/ev-removed > $P/cov-removed.txt; echo COVERAGE_EXIT=$?; grep -E '^evidence:|^det:drp:(fakecam|ts|hrencoder) "
     "|^[0-9]+ rows|^(PASS|FAIL)|^  det:' $P/cov-removed.txt" + C, r'COVERAGE_EXIT=\d+', 300)

step("# (g) the hardware path, no sim:// device: the same commands from base wt-cov (2d9593bc5) and from this head, then diffed")
step("git -C $R/wt-cov log -1 --format='base %H %s'" + C + "; echo \"base local changes: $(git -C $R/wt-cov status --short | wc -l); "
     "files under psdaq/drp and psdaq/psdaq/configdb that differ 2d9593bc5..HEAD: $(git diff --name-only 2d9593bc5 HEAD -- psdaq/drp "
     "psdaq/psdaq/configdb | wc -l)\"")
step("TYPES='fakecam cspad epixhremu jungfrauemu ts hrencoder epixm320 epix100 wave8 wave8he epixhr2x2'; for w in wt-cov wt-xpm; do "
     "bash $R/logs/xpm/hwpath.sh $w $TYPES > $P/hw-$w.log 2>&1; head -1 $P/hw-$w.log; done", r'^== wt-xpm head=', 900)
step("diff <(tail -n +2 $P/hw-wt-cov.log) <(tail -n +2 $P/hw-wt-xpm.log); echo HWPATH_DIFF_EXIT=$?; "
     "wc -l $P/hw-wt-cov.log $P/hw-wt-xpm.log | head -2", r'HWPATH_DIFF_EXIT=\d+', 60)
step("sed -n '/^-- fakecam python/,/^-- cspad python/p' $P/hw-wt-xpm.log" + C)
step("sed -n '/^-- hrencoder python/,/^-- epixm320 python/p' $P/hw-wt-xpm.log" + C)
step("echo \"checkout local changes: $(git status --short | wc -l)\"; date '+%F %T %Z'; exit", 'exedev@', 60)

json.dump(S, open(sys.argv[1], 'w'), indent=1)
print(f'{sys.argv[1]}: {len(S)} steps')
