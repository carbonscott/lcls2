"""daq_sim feature: one hardware-free run per system feature, end to end, with its own checks.

    daq_sim feature a|b|e [-w WORKDIR] [-p PLATFORM] [--events N] [--keep-up]
    daq_sim feature a|b|e -w WORKDIR --check-only [--break KIND]

Each feature brings the DAQ up on this node (daq_sim up --detach), drives one run, takes the DAQ
down (always, unless --keep-up) and prints a report: the Slurm job and step, the host, the
checkout's HEAD SHA, each transition with its time (each state as the client read it back, and
each transition frame simxpm sent the DRPs), each DRP's L1Accept count as the DAQ has it (the
L1Accepts simxpm sent its link) against psana2's count in its stream, and the verdict:
'FEATURE <x> PASS' and exit 0 only if every check passes.

a  Readout groups at different rates: one partition with 3 PGP DRPs of 3 types in 2 readout
   groups, fakecam_0 in group p (the platform) on pyxpm's 1.02 kHz fixed-rate marker, epix100_0
   and wave8_0 in group p+1 on the 102 Hz marker (up --also epix100:<p+1> --also wave8:<p+1>
   --fixed-rate <p>:3 --fixed-rate <p+1>:4), one cycle.  Checks: each DRP's DAQ count equals
   psana2's events in its stream, all with data and each passing the type's per-event check
   (xtc2_check); each group's L1Accepts follow its marker (group p+1 took 1/10 of group p's).
b  A scan: psdaq/psdaq/cas/generic_timing_scan.py, the facility's config scan script
   (ConfigScanBase, ConfigScan: control.py's Configure with the scan's step_keys, then per step
   BeginStep with the step's values and readout_count, Enable, simxpm's StepDone after
   readout_count L1Accepts, Disable, EndStep) over epix100_0:user.start_ns at 700000, 710000 and
   720000 ns (--linear 700000 730000 10000), --events L1Accepts per step, against the simulated
   DAQ (up --det epix100 --rate 100); epix100's own epix100_config.py applies each step's value
   (epix100_update).  Checks: psana2 reads 3 steps whose step_value are those values (and whose
   step_docstring names them), each with --events events; epix100's DAQ count equals psana2's
   and every event passes the per-pixel check.
e  System DRPs: drp_pva, drp_bld, drp_udpencoder and epicsArch recording from simulated sources
   in the same run as the PGP DRP fakecam_0 (up --pva --epics --udp --bld --rate 100), one cycle.
   Checks: psana2 reads each one's data event by event (sysdrp_check), drp_bld's from simxpm's
   BLD source over loopback multicast; each DRP's DAQ count equals psana2's events in its stream.

--check-only re-runs a feature's checks on the run already recorded in WORKDIR (no DAQ).
--break KIND makes a check fail on purpose (with --check-only; the recorded files stay as they
are, a broken copy is checked):
  a: drop-l1        cut the last 10 L1Accepts off a copy of epix100_0's stream file
     same-rate      expect both readout groups at the same rate
  b: expect-values  expect the step values + 1
  e: bld-seed       expect the BLD values of seq + 1
"""

import glob
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

from psdaq.sim import daq_sim as ds

BREAKS = {'a': ('drop-l1', 'same-rate'), 'b': ('expect-values',), 'e': ('bld-seed',)}
SCAN_VALUES = (700000., 710000., 720000.)        # --linear 700000 730000 10000
DROP_L1 = 10
TRANSITION_RE = re.compile(r'^(\S+ \S+) simxpm INFO ((ClearReadout|Configure|Unconfigure|BeginRun|EndRun|'
                           r'BeginStep|EndStep|Enable|Disable) rog 0x[0-9a-f]+ pulseId \S+ time \S+ to \d+ link\(s\)'
                           r'|L0 enable .*|L0 disable .*|group \d+: L0Select .*|step done .*)')


def up_options(feature, platform):
    """daq_sim up options of each feature."""
    g2 = (platform + 1) % 8
    return {'a': ['--also', f'epix100:{g2}', '--also', f'wave8:{g2}',
                  '--fixed-rate', f'{platform}:3', '--fixed-rate', f'{g2}:4'],
            'b': ['--det', 'epix100', '--rate', '100'],
            'e': ['--pva', '--epics', '--udp', '--bld', '--rate', '100']}[feature]


def add_arguments(p):
    p.add_argument('feature', choices=('a', 'b', 'e'), help='a: readout groups at different rates; '
                   'b: a scan; e: drp_pva, drp_bld, drp_udpencoder and epicsArch with a PGP DRP')
    p.add_argument('-p', '--platform', type=int, default=5, choices=range(8))
    p.add_argument('--events', type=int, default=None,
                   help='L1Accepts of the cycle (a, e: default 1000), or per scan step (b: default 200)')
    p.add_argument('--check-only', action='store_true', help='re-run the checks on the recorded run')
    p.add_argument('--break', dest='breakage', default=None,
                   choices=sorted({b for v in BREAKS.values() for b in v}),
                   help='with --check-only: make a check fail on purpose (module doc)')
    p.add_argument('--keep-up', action='store_true', help='leave the DAQ up at the end')
    p.add_argument('--timeout', type=int, default=60, help='per-transition timeout, s (default %(default)d)')


def head():
    """(SHA, files changed) of the checkout this module runs from."""
    def git(*a):
        r = subprocess.run(['git', '-C', ds.SIMDIR] + list(a), capture_output=True, text=True, timeout=60)
        return r.stdout.strip()
    return git('rev-parse', 'HEAD'), len([l for l in git('status', '--porcelain', '--untracked-files=no')
                                          .splitlines() if l.strip()])


def run_echo(argv, prefix, timeout):
    """Run argv, echoing each output line with a prefix; return its exit code."""
    p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    timer = threading.Timer(timeout, p.kill)
    timer.start()
    try:
        for line in p.stdout:
            print(f'{prefix}{line.rstrip()}', flush=True)
        return p.wait()
    finally:
        timer.cancel()


def daq_sim(*args):
    return [sys.executable, '-m', 'psdaq.sim.daq_sim'] + list(args)


def simxpm_transitions(work, since=None):
    """simxpm's log lines of transition frames, L0 enables/disables and group rates."""
    try:
        with open(work.path('logs', 'simxpm.log'), errors='replace') as f:
            lines = [m.group(0) for m in map(TRANSITION_RE.match, f) if m]
    except OSError:
        return []
    return lines


def last_cycle(work):
    try:
        with open(work.path('logs', 'cycle.jsonl')) as f:
            return json.loads(f.read().strip().splitlines()[-1])
    except (OSError, IndexError, ValueError):
        return None


# --- checks ---------------------------------------------------------------------------------

def check_a(work, state, rec, breakage=None):
    """Feature a's verdict from the cycle's record: 3 PGP DRPs of 3 types, 2 groups, their
    markers different, per-DRP DAQ == psana2 (the cycle's per-DRP checks)."""
    counts, problems = rec['counts'], []
    experiment, run = rec.get('experiment'), rec.get('run')
    if breakage:
        st = dict(state)
        xtcdir = None
        if breakage == 'same-rate':
            st['fixed_rates'] = {g: 3 for g in state['fixed_rates']}
        if breakage == 'drop-l1':
            xtcdir = broken_copy(work, experiment, run, 'epix100_0')
        counts = dict(counts)
        counts.update(ds._per_drp_counts(work, st, experiment, run, counts, xtcdir=xtcdir))
    drps = [(f'{state["det"]}_{i}', state['platform']) for i in range(state.get('segments', 1))] + \
           [(a['alias'], a['group']) for a in state.get('also', ())]
    types = {d.rsplit('_', 1)[0] for d, _ in drps}
    groups = {g for _, g in drps}
    rates = {int(g): i for g, i in (state.get('fixed_rates') or {}).items()}
    if len(drps) < 3 or len(types) < 3:
        problems.append(f'{len(drps)} DRPs of {len(types)} types (want 3 of 3)')
    if len(groups) < 2 or len({rates.get(g) for g in groups}) < 2:
        problems.append(f'groups {sorted(groups)} at markers {rates} (want 2 groups at different rates)')
    if counts.get('per-DRP checks') != 'PASS':
        problems.append(f'per-DRP checks: {counts.get("per-DRP checks")}')
    return counts, problems


def check_e(work, state, rec, breakage=None):
    """Feature e's verdict: the four system DRPs and the PGP DRP in one run, each recorded and
    read back by psana2 event by event (the cycle's sysdrp and per-DRP checks)."""
    counts, problems = dict(rec['counts']), []
    experiment, run = rec.get('experiment'), rec.get('run')
    if breakage == 'bld-seed':
        argv = [sys.executable, '-m', 'psdaq.sim.sysdrp_check', '--dir',
                work.path('data', ds.INSTRUMENT, experiment, 'xtc'), '--exp', experiment, '--run', str(run),
                '--seed', str(state['seed']), '--bld', ds.BLD_NAME, '--self-test-offset', '1']
        r = subprocess.run(argv, capture_output=True, text=True, timeout=900)
        try:
            res = json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            res = {'pass': False, 'problems': [r.stderr.strip()[-300:]]}
        counts['system DRP checks'] = 'PASS' if res['pass'] else f'FAIL {res["problems"][:2]}'
        counts['sysdrp bld problems'] = res.get('bld problems')
        counts['per-DRP checks'] = 'PASS' if res['pass'] else 'FAIL (bld values)'
    for alias in ('pvcam_0', 'bld_0', 'encoder_0', 'epics_0', f'{state["det"]}_0'):
        if alias not in ds.procs(state):
            problems.append(f'{alias} not in the partition')
    for k in ('system DRP checks', 'per-DRP checks'):
        if counts.get(k) != 'PASS':
            problems.append(f'{k}: {counts.get(k)}')
    return counts, problems


def broken_copy(work, experiment, run, alias, drop=DROP_L1):
    """--break drop-l1: a copy of the run's xtc dir in which alias's stream lost its last `drop`
    L1Accepts (and everything after the first of them), cut at a datagram boundary."""
    from psdaq.webgui.e2e import xtc2_dgrams
    from psdaq.sim import xtc2_check
    src = work.path('data', ds.INSTRUMENT, experiment, 'xtc')
    dst = tempfile.mkdtemp(prefix='feature-break-', dir=work.dir)
    for path in sorted(glob.glob(os.path.join(src, f'{experiment}-r{run:04d}-s*-c000.xtc2'))):
        out = os.path.join(dst, os.path.basename(path))
        shutil.copyfile(path, out)
        try:
            mine = xtc2_check.check(path, alias, None).get('with_data')
        except Exception:
            mine = 0
        if mine:
            dg = xtc2_dgrams(out)
            l1 = [i for i, d in enumerate(dg) if d[2] == 12]
            cut = dg[l1[len(l1) - drop]][0]
            with open(out, 'r+b') as f:
                f.truncate(cut)
            print(f'{ds.now()} --break drop-l1: {os.path.basename(path)} ({alias}): kept {len(l1) - drop} of '
                  f'{len(l1)} L1Accepts, cut at {cut} B (copy in {dst})', flush=True)
    return dst


def scan_steps(path, det_name='epix100_0'):
    """[(step_value, step_docstring, events, events with det data)] of the run in one stream file."""
    os.environ.setdefault('LCLS_CALIB_HTTP', 'http://127.0.0.1:9/ws')
    from psana import DataSource
    out = []
    ds_ = DataSource(files=[path], skip_calib_load='all')
    for run in ds_.runs():
        sv, sd = run.Detector('step_value'), run.Detector('step_docstring')
        det = run.Detector(det_name)
        for step in run.steps():
            n = k = 0
            for evt in step.events():
                n += 1
                k += det.raw.raw(evt) is not None
            out.append((sv(step), sd(step), n, k))
    return out


def check_b(work, state, rec, breakage=None):
    """Feature b's verdict: steps, values, per-step counts, DAQ == psana2, per-event check."""
    from psdaq.sim import xtc2_check
    counts, problems = dict(rec['counts']), []
    experiment, run = rec.get('experiment'), rec.get('run')
    want = [v + (1 if breakage == 'expect-values' else 0) for v in SCAN_VALUES]
    events = rec.get('events_per_step')
    alias = f'{state["det"]}_0'
    files = sorted(glob.glob(work.path('data', ds.INSTRUMENT, experiment or 'none', 'xtc',
                                       f'{experiment}-r{run or 0:04d}-s*-c000.xtc2')))
    if not files:
        return counts, [f'no xtc2 file of run {run}']
    path = files[0]
    steps = scan_steps(path, alias)
    counts['psana2 steps'] = len(steps)
    for i, (v, doc, n, k) in enumerate(steps):
        counts[f'step {i + 1}'] = f'step_value {v} docstring {doc} events {n} with {alias} data {k}'
    values = [s[0] for s in steps]
    if len(steps) < 3:
        problems.append(f'{len(steps)} steps (want >= 3)')
    if values != want:
        problems.append(f'step values {values} != expected {want}')
    for i, (v, doc, n, k) in enumerate(steps):
        try:
            d = json.loads(doc) if doc else {}
        except ValueError:
            d = {}
        if float(d.get('step', -1)) != v:
            problems.append(f'step {i + 1}: docstring {doc!r} does not name step {v}')
        if events and (n != events or k != n):
            problems.append(f'step {i + 1}: {n} events, {k} with data (want {events})')
    r = xtc2_check.check(path, alias, state['seed'])
    daq = ((counts.get('simxpm links') or {}).get(alias) or {}).get('l1acc')
    counts[f'drp {alias}'] = (f'group {state["platform"]}: DAQ (simxpm L1Accepts sent) {daq} psana2 events '
                              f'{r["events"]} with data {r["with_data"]} per-event check '
                              f'{"PASS" if r["pass"] else "FAIL " + str(r["problems"][:2])} ({os.path.basename(path)})')
    if not (r['pass'] and daq == r['events'] == r['with_data'] == sum(s[2] for s in steps)):
        problems.append(f'{alias}: DAQ {daq}, psana2 {r["events"]}/{r["with_data"]}, check {r["pass"]}')
    if counts.get('scan exit') != 0:
        problems.append(f'scan script exit {counts.get("scan exit")}')
    return counts, problems


# --- feature b's drive: the facility's scan script against the simulated DAQ ----------------

def drive_scan(work, events, timeout):
    """Bring the DAQ to connected (selecting every process, as the GUIs do), run
    generic_timing_scan.py, bring it back to reset; returns the record check_b reads."""
    from psdaq.control.DaqControl import DaqControl
    state = work.load()
    plat = state['platform']
    dc = DaqControl(host='localhost', platform=plat, timeout=timeout * 1000)
    msgs, rows, stop = [], [], threading.Event()

    def monitor():
        mon = DaqControl(host='localhost', platform=plat, timeout=1000)
        mon.front_sub.setsockopt(ds.zmq_rcvtimeo(), 500)
        while not stop.is_set():
            try:
                m = mon.front_sub.recv_json()
            except Exception:
                continue
            key, body = m.get('header', {}).get('key'), m.get('body', {})
            if key == 'transition':
                print(f'{ds.now()} [transition] {body.get("transition")} -> state {body.get("state")}', flush=True)
            elif key in ('step', 'error', 'fileReport'):
                text = body.get('err_info', body.get('path', json.dumps(body)[:160]))
                msgs.append((ds.now(), key, text))
                print(f'{ds.now()} [{key}] {text}', flush=True)
        mon.context.destroy(0)

    mt = threading.Thread(target=monitor, daemon=True)
    mt.start()
    time.sleep(0.5)

    def go(target):
        t0 = ds.now()
        err = dc.setState(target)
        got = dc.getState()
        rows.append((t0, ds.now(), target, got, err))
        print(f'{ds.now()} setState {target:<12} -> {got:<12} {"OK" if err is None and got == target else "FAIL"}'
              f'{"  error: " + str(err) if err else ""}', flush=True)
        return err is None and got == target

    ok = go('unallocated')
    if ok:
        ds.select_all(dc)
        ok = go('allocated') and go('connected')
    rc = None
    if ok:
        argv = [sys.executable, '-m', 'psdaq.cas.generic_timing_scan', '-p', str(plat), '-C', 'localhost',
                '--detname', f'{state["det"]}_0', '--scantype', 'timing', '--events', str(events),
                '--record', '1', '--config', ds.CONFIG_ALIAS, '-t', str(timeout * 1000),
                '--linear', '700000', '730000', '10000']
        print(f'{ds.now()} scan: {" ".join(argv[1:])}', flush=True)
        rc = run_echo(argv, '  scan| ', timeout=600)
        print(f'{ds.now()} scan exit {rc}', flush=True)
    counts = ds._run_counts(work, plat)     # at connected: simxpm's and the DRPs' counters
    status = dc.getStatus()
    run = status[8] if isinstance(status[8], int) else None   # the last run
    cur = dc.getState()
    if cur in ds.STATES:
        for target in reversed(ds.STATES[:ds.STATES.index(cur)]):
            if not go(target):
                break
    stop.set()
    mt.join(2)
    dc.context.destroy(0)
    counts['scan exit'] = rc
    rec = {'when': ds.now(), 'transitions': rows, 'messages': msgs, 'counts': counts,
           'experiment': status[6], 'run': run, 'events_per_step': events, 'feature': 'b'}
    with open(work.path('logs', 'feature-b.jsonl'), 'a') as f:
        f.write(json.dumps(rec) + '\n')
    return rec


# --- the command ------------------------------------------------------------------------------

def report(feature, work, state, rec, counts, problems, started):
    print(f'---- FEATURE {feature} report', flush=True)
    sha, dirty = head()
    print(f'job {os.environ.get("SLURM_JOB_ID")} step {os.environ.get("SLURM_STEP_ID")} host '
          f'{socket.gethostname()} HEAD {sha} (files changed: {dirty}) workdir {work.dir}', flush=True)
    print(f'run {rec.get("experiment")}/r{rec.get("run") or 0:04d} started {started}', flush=True)
    print('transitions (client request -> state read back):', flush=True)
    for t0, t1, target, got, err in rec.get('transitions', []):
        print(f'  {t0} -> {t1}  {target:<12} {got:<12} {"" if err is None else err}', flush=True)
    lines = simxpm_transitions(work)
    print(f'transition frames simxpm sent the DRPs ({len(lines)} lines of logs/simxpm.log):', flush=True)
    for line in lines:
        print(f'  {line}', flush=True)
    print('counts:', flush=True)
    for k, v in counts.items():
        if k == 'simxpm links' or k.startswith(('drp ', 'bld ', 'step ', 'readout groups', 'per-DRP', 'psana2', 'sysdrp',
                                                 'system DRP', 'simxpm NumL0Acc', 'TEB_', 'drp_match',
                                                 'bld_miss', 'scan exit')):
            print(f'  {k:<26} {v}', flush=True)
    for p in problems:
        print(f'  problem: {p}', flush=True)
    verdict = 'PASS' if not problems else 'FAIL'
    print(f'FEATURE {feature} {verdict}', flush=True)
    return 0 if not problems else 1


def cmd_feature(args):
    feature = args.feature
    work = ds.Work(args.workdir)
    started = ds.now()
    sha, dirty = head()
    print(f'{started} FEATURE {feature}: job {os.environ.get("SLURM_JOB_ID")} step '
          f'{os.environ.get("SLURM_STEP_ID")} host {socket.gethostname()} HEAD {sha} (files changed: {dirty})',
          flush=True)
    if args.breakage and args.breakage not in BREAKS[feature]:
        raise ds.Fail(f'--break {args.breakage} is not one of feature {feature}\'s {BREAKS[feature]}')
    if args.breakage and not args.check_only:
        raise ds.Fail('--break needs --check-only (it breaks a copy of a recorded run)')
    events = args.events or (200 if feature == 'b' else 1000)
    if not args.check_only:
        rc = run_echo(daq_sim('up', '-w', work.dir, '--detach', '-p', str(args.platform),
                              *up_options(feature, args.platform)), '  up| ', timeout=600)
        try:
            if rc != 0:
                print(f'{ds.now()} up exit {rc}', flush=True)
                return 1
            if feature == 'b':
                drive_scan(work, events, args.timeout)
            else:
                rc = run_echo(daq_sim('cycle', '-w', work.dir, '--events', str(events),
                                      '--timeout', str(args.timeout)), '  cycle| ', timeout=1800)
                print(f'{ds.now()} cycle exit {rc}', flush=True)
        finally:
            if not args.keep_up:
                rc_down = run_echo(daq_sim('down', '-w', work.dir), '  down| ', timeout=300)
                print(f'{ds.now()} down exit {rc_down}', flush=True)
    state = work.load()
    if state is None:
        raise ds.Fail(f'nothing recorded in {work.dir}')
    if feature == 'b':
        try:
            with open(work.path('logs', 'feature-b.jsonl')) as f:
                rec = json.loads(f.read().strip().splitlines()[-1])
        except (OSError, IndexError, ValueError):
            raise ds.Fail(f'no scan recorded in {work.dir}')
        counts, problems = check_b(work, state, rec, args.breakage)
    else:
        rec = last_cycle(work)
        if rec is None:
            raise ds.Fail(f'no cycle recorded in {work.dir}')
        m = [k for k in rec['counts'] if k == 'xtc2 file']
        path = rec['counts'].get('xtc2 file', '') if m else ''
        mm = re.search(r'/(\w+)-r(\d{4})-s\d+-c000\.xtc2', path)
        rec['experiment'], rec['run'] = (mm.group(1), int(mm.group(2))) if mm else (None, None)
        if not args.check_only and rc != 0:
            counts, problems = rec['counts'], [f'cycle exit {rc}']
        else:
            counts, problems = (check_a if feature == 'a' else check_e)(work, state, rec, args.breakage)
            if not args.breakage and not rec.get('ok'):
                problems.append('the cycle failed')
    return report(feature, work, state, rec, counts, problems, started)
