"""daq_sim feature: one hardware-free run per system feature, end to end, with its own checks.

    daq_sim feature a|b|c|e [-w WORKDIR] [-p PLATFORM] [--events N] [--keep-up] [--ami-src DIR]
    daq_sim feature a|b|c|e -w WORKDIR --check-only [--break KIND]
    daq_sim feature d --hosts HOST_A,HOST_B

Each feature brings the DAQ up on this node (daq_sim up --detach), drives one run, takes the DAQ
down (always, unless --keep-up) and prints a report: the Slurm job and step, the host, the
checkout's HEAD SHA, each transition with its time (each state as the client read it back, and
each transition frame simxpm sent the DRPs), each DRP's L1Accept count as the DAQ has it (the
L1Accepts simxpm sent its link) against psana2's count in its stream, and the verdict:
'FEATURE <x> PASS' and exit 0 only if every check passes.

a  Readout groups at different rates: one partition with 3 PGP DRPs of 3 types in 2 readout
   groups, hrencoder_0 in group p (the platform) on pyxpm's 1.02 kHz fixed-rate marker,
   epix100_0 and wave8_0 in group p+1 on the 102 Hz marker (up --det hrencoder --also
   epix100:<p+1> --also wave8:<p+1> --fixed-rate <p>:3 --fixed-rate <p+1>:4), one cycle.
   Checks: each DRP's DAQ count equals psana2's events in its stream, all with data and each
   passing the type's per-event check (xtc2_check); each group's L1Accepts follow its marker
   (group p+1 took 1/10 of group p's).  All three are BEB types: xpmdet_config (fakecam and
   the other XpmDetector types), opal_config and piranha4_config take every active DRP on the
   host for a segment on their board (barrier.supervisor_info) and wait at Connect for the
   other DRPs to join their barrier, which a DRP of another config script never does.
b  A scan: psdaq/psdaq/cas/generic_timing_scan.py, the facility's config scan script
   (ConfigScanBase, ConfigScan: control.py's Configure with the scan's step_keys, then per step
   BeginStep with the step's values and readout_count, Enable, simxpm's StepDone after
   readout_count L1Accepts, Disable, EndStep) over epix100_0:user.start_ns at 700000, 710000 and
   720000 ns (--linear 700000 730000 10000), --events L1Accepts per step, against the simulated
   DAQ (up --det tb --also epix100 --rate 100).  epix100's own epix100_config.py applies each
   step's value (epix100_update); the step values are recorded, as at the hutches, by the timing
   DRP (TimingBEB, whose scanEnabled() is true; Epix100's is false).  Checks: psana2 reads 3
   steps in tb's stream whose step_value are those values and whose step_docstring names them;
   each DRP has --events events in every step, its DAQ count equals psana2's and every event
   passes its per-event check; epix100_update applied the 3 values, in order.
e  System DRPs: drp_pva, drp_bld, drp_udpencoder and epicsArch recording from simulated sources
   in the same run as the PGP DRP fakecam_0 (up --pva --epics --udp --bld --rate 100), one cycle.
   Checks: psana2 reads each one's data event by event (sysdrp_check), drp_bld's from simxpm's
   BLD source over loopback multicast; each DRP's DAQ count equals psana2's events in its stream.
c  The MEB serving events to AMI, AMI showing live detector data: up --ami (the MEB, a
   shmemClient, ami-manager, ami-global, ami-node, an ami-worker on the MEB and ami-client,
   offscreen; --ami-src or $DAQ_SIM_AMI_SRC) --rate 100, one cycle with --ami-shot
   <WORKDIR>/ami-shot.png.  Checks: fakecam_0's DAQ count (the L1Accepts simxpm sent its link)
   equals psana2's events in its stream, all with data and passing the per-event check; the MEB
   served events (MEB_EvtCt > 0, at least the events AMI kept); every event AMI computed from the
   MEB matches psana2's event of the same timestamp (psdaq.sim.ami_check: seq and pixel, at
   least 100 events, AMI's sum of the pixel equal to psana2's); a second ami-client, AMI's own
   GUI, showed the camera image while the run was Running (the screenshot, ami_shot).
d  Two nodes: one partition over two hosts of this Slurm job's allocation (daq_sim up --hosts
   A,B --segments 2 --rate 100, run on A, psdaq.sim.twonode): control, the TEB, simxpm and
   fakecam_0 on A; fakecam_1 on B, started by procmgr through a procmgrd in a step of the job on
   B.  One recorded cycle.  Checks: the cycle passed; each DRP's DAQ count equals psana2's events
   in its own stream; while Running, 'ss -tnp' on each host shows established TCP connections to
   the other host owned by DAQ processes.  NOT AVAILABLE unless --hosts names two different
   hosts of the job's allocation (SLURM_JOB_NODELIST).

--check-only re-runs a feature's checks on the run already recorded in WORKDIR (no DAQ).
--break KIND makes a check fail on purpose (with --check-only; the recorded files stay as they
are, a broken copy is checked):
  a: drop-l1        cut the last 10 L1Accepts off a copy of epix100_0's stream file
     same-rate      expect both readout groups at the same rate
  b: expect-values  expect the step values + 1
  c: ami-tamper     change the pixel of one event in a copy of the result fetched from AMI
  e: bld-seed       expect the BLD values of seq + 1
  d: kill-remote-drp  (a live run, no --check-only) SIGKILL the DRP on the second host once Running
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

# The contract's system features (a)-(e); daq_sim matrix runs each one this names
FEATURES = {'a': 'readout groups at different rates',
            'b': 'a scan through generic_timing_scan.py',
            'c': 'the MEB serving events to AMI, AMI showing live detector data',
            'd': 'two nodes (--hosts: two hosts of this Slurm job)',
            'e': 'drp_pva, drp_bld, drp_udpencoder and epicsArch with a PGP DRP'}
BREAKS = {'a': ('drop-l1', 'same-rate'), 'b': ('expect-values',), 'c': ('ami-tamper',), 'd': ('kill-remote-drp',),
          'e': ('bld-seed',)}
SCAN_VALUES = (700000., 710000., 720000.)        # --linear 700000 730000 10000
SCAN_DET = 'epix100'                             # generic_timing_scan --detname epix100_0
DROP_L1 = 10
TRANSITION_RE = re.compile(r'^(\S+ \S+) simxpm INFO ((ClearReadout|Configure|Unconfigure|BeginRun|EndRun|'
                           r'BeginStep|EndStep|Enable|Disable) rog 0x[0-9a-f]+ pulseId \S+ time \S+ to \d+ link\(s\)'
                           r'|L0 enable .*|L0 disable .*|group \d+: L0Select .*|step done .*)')


def up_options(feature, platform):
    """daq_sim up options of each feature."""
    g2 = (platform + 1) % 8
    return {'a': ['--det', 'hrencoder', '--also', f'epix100:{g2}', '--also', f'wave8:{g2}',
                  '--fixed-rate', f'{platform}:3', '--fixed-rate', f'{g2}:4'],
            'b': ['--det', 'tb', '--also', SCAN_DET, '--rate', '100'],
            'c': ['--ami', '--rate', '100'],
            'd': ['--segments', '2', '--rate', '100'],
            'e': ['--pva', '--epics', '--udp', '--bld', '--rate', '100']}[feature]


def add_arguments(p):
    p.add_argument('feature', choices=FEATURES, help='; '.join(f'{x}: {d}' for x, d in FEATURES.items()))
    p.add_argument('-p', '--platform', type=int, default=5, choices=range(8))
    p.add_argument('--events', type=int, default=None,
                   help='L1Accepts of the cycle (a, e: default 1000), or per scan step (b: default 200)')
    p.add_argument('--check-only', action='store_true', help='re-run the checks on the recorded run')
    p.add_argument('--break', dest='breakage', default=None,
                   choices=sorted({b for v in BREAKS.values() for b in v}),
                   help='with --check-only: make a check fail on purpose (module doc)')
    p.add_argument('--keep-up', action='store_true', help='leave the DAQ up at the end')
    p.add_argument('--timeout', type=int, default=60, help='per-transition timeout, s (default %(default)d)')
    p.add_argument('--ami-src', default=None, help='c: AMI source tree for up --ami (default: up\'s, '
                   '$DAQ_SIM_AMI_SRC, else ami-* on PATH)')
    p.add_argument('--hosts', default=None, metavar='HOST_A,HOST_B',
                   help='d: two hosts of this Slurm job\'s allocation')


def head():
    """(SHA, files changed) of the checkout this module runs from."""
    def git(*a):
        r = subprocess.run(['git', '-C', ds.SIMDIR] + list(a), capture_output=True, text=True, timeout=60)
        return r.stdout.strip()
    return git('rev-parse', 'HEAD'), len([l for l in git('status', '--porcelain', '--untracked-files=no')
                                          .splitlines() if l.strip()])


def run_echo(argv, prefix, timeout, env=None):
    """Run argv, echoing each output line with a prefix; return its exit code."""
    p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                         env=env)
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

def check_a(work, state, rec, breakage=None, recompute=False):
    """Feature a's verdict from the cycle's record: 3 PGP DRPs of 3 types, 2 groups, their
    markers different, per-DRP DAQ == psana2 (the cycle's per-DRP checks; with recompute, read
    from the files again)."""
    counts, problems = rec['counts'], []
    experiment, run = rec.get('experiment'), rec.get('run')
    if breakage or recompute:
        st = dict(state)
        xtcdir = None
        if breakage == 'same-rate':
            st['fixed_rates'] = {g: 3 for g in state['fixed_rates']}
        if breakage == 'drop-l1':
            xtcdir = broken_copy(work, experiment, run, 'epix100_0')
        counts = dict(counts)
        try:
            counts.update(ds._per_drp_counts(work, st, experiment, run, counts, xtcdir=xtcdir))
        finally:
            if xtcdir:                  # the broken copy is not kept
                shutil.rmtree(xtcdir, ignore_errors=True)
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


def ami_recheck(work, state, experiment, run, tamper=False):
    """ami_check again on the result the cycle fetched from AMI (logs/ami_check.rows.json)
    against the run's file; with tamper, on a copy in which one event's pixel is off by one."""
    from psdaq.sim import ami_check
    try:
        with open(work.path('logs', 'ami_check.rows.json')) as f:
            result = json.load(f)
    except (OSError, ValueError) as e:
        return {'ami check': f'FAIL no result fetched from AMI in {work.dir}: {e}'}
    if tamper and result.get('rows'):
        i = len(result['rows']) // 2
        ts, seq, pix = result['rows'][i]
        result['rows'] = [r if r[0] != ts else [ts, seq, pix ^ 1] for r in result['rows']]
        print(f'{ds.now()} --break ami-tamper: AMI\'s row for timestamp {ts:#x} (seq {seq}) gets pixel {pix ^ 1}, '
              f'AMI computed {pix} (in a copy; logs/ami_check.rows.json stays as it is)', flush=True)
    files = sorted(glob.glob(work.path('data', ds.INSTRUMENT, experiment or 'none', 'xtc',
                                       f'{experiment}-r{run or 0:04d}-s*-c000.xtc2')))
    if not files:
        return {'ami check': f'FAIL no xtc2 file of run {run}'}
    res = ami_check.check(result, files, state['det'])
    out = {k: res[k] for k in ('ami rows', 'ami events', 'ami matched', 'ami pixsum',
                               'psana2 pixsum (same events)', 'ami seq range')}
    out['ami check'] = 'PASS' if res['pass'] else f'FAIL {res["problems"][:3]}'
    return out


def check_c(work, state, rec, breakage=None, recompute=False):
    """Feature c's verdict: fakecam_0's DAQ count == psana2's (per event), the MEB served
    events, every event AMI computed from them matches psana2's (ami_check; with recompute,
    checked again from the files) and AMI's own GUI showed the camera image while Running."""
    counts, problems = dict(rec['counts']), []
    experiment, run = rec.get('experiment'), rec.get('run')
    if breakage or recompute:
        counts.update(ami_recheck(work, state, experiment, run, tamper=breakage == 'ami-tamper'))
    if experiment and run:
        counts.update(ds._per_drp_counts(work, state, experiment, run, counts))
    if not state.get('ami') or not state.get('meb'):
        problems.append('the DAQ ran without the MEB and AMI (up --ami)')
    if counts.get('per-DRP checks') != 'PASS':
        problems.append(f'per-DRP checks: {counts.get("per-DRP checks")}')
    meb, kept = counts.get('MEB_EvtCt'), counts.get('ami events')
    if meb is None and counts.get('prometheus unread'):
        problems.append(f'MEB_EvtCt not read: the exporters that did not answer after Disable: '
                        f'{counts["prometheus unread"]}')
    elif not isinstance(meb, int) or meb <= 0:
        problems.append(f'MEB_EvtCt {meb}: the MEB served no event')
    elif isinstance(kept, int) and kept > meb:
        problems.append(f'AMI kept {kept} events, more than the MEB served ({meb})')
    if counts.get('ami check') != 'PASS':
        problems.append(f'ami check: {counts.get("ami check")}')
    shot = str(counts.get('ami shot'))
    png = shot.split()[1].rstrip(':') if shot.startswith('PASS ') else None
    counts['ami screenshot'] = png if png and os.path.isfile(png) else f'none ({shot[:200]})'
    if not (png and os.path.isfile(png) and os.path.getsize(png) > 0):
        problems.append(f'ami shot: {shot[:200]}')
    return counts, problems


def allocated_hosts():
    """The short names of the hosts of this Slurm job's allocation (squeue's node list of
    SLURM_JOB_ID, else SLURM_JOB_NODELIST: twonode.job_nodelist; expanded by scontrol); [] outside
    a job."""
    from psdaq.sim import twonode
    nodelist = twonode.job_nodelist()
    if not nodelist:
        return []
    try:
        r = subprocess.run(['scontrol', 'show', 'hostnames', nodelist], capture_output=True, text=True,
                           timeout=30)
        names = r.stdout.split() if r.returncode == 0 else []
    except (OSError, subprocess.SubprocessError):
        names = []
    if not names and '[' not in nodelist:
        names = nodelist.split(',')
    return [n.split('.')[0] for n in names if n]


def unavailable(feature, hosts=None):
    """Why feature cannot run here, or None.  Only d has a condition: --hosts must name two
    different hosts of this Slurm job's allocation."""
    if feature != 'd':
        return None
    job, have = os.environ.get('SLURM_JOB_ID'), allocated_hosts()
    where = f'job {job} holds {",".join(have) or "no host"}' if job else 'not inside a Slurm job'
    names = [h for h in (hosts or '').split(',') if h]
    if len(names) != 2 or names[0] == names[1]:
        return (f'two nodes needs --hosts HOST_A,HOST_B, two different hosts of this Slurm job\'s '
                f'allocation ({where}); given: {hosts or "none"}')
    missing = [h for h in names if h.split('.')[0] not in have]
    if missing:
        return f'{",".join(missing)} not in this Slurm job\'s allocation ({where})'
    return None


DAQ_PROGRAMS = ('drp', 'teb', 'control', 'python')     # the owners of a DAQ connection (control is python)


def tcp_peers(two):
    """The established TCP connections between the two hosts, from 'ss -tnp' on each (on the other host in a
    step of the job): {host: [(local, peer, owners)]}."""
    from psdaq.sim import twonode
    a, b = two['hosts']
    ip = two['ips']
    return {a: twonode.established(ip[b], ip[a], twonode.ss_lines()),
            b: twonode.established(ip[a], ip[b], twonode.ss_lines(b))}


def feature_d(args, work, started):
    """Feature d: one partition over two hosts of this job (daq_sim up --hosts A,B, run on A): control, the
    TEB and <det>_0 on A, <det>_1 on B, one recorded cycle of --events L1Accepts (default 1000).  Checks: the
    cycle passed; each DRP's DAQ count (the L1Accepts simxpm sent its link) equals psana2's events in its own
    stream, all with data and passing the per-event check; the DRP on B ran there (procmgr's host); while
    Running, 'ss -tnp' on each host shows established TCP connections to the other host owned by DAQ
    processes.  NOT AVAILABLE unless --hosts names two hosts of this job's allocation.  --break
    kill-remote-drp SIGKILLs the DRP on B once the run's L1Accepts are in (cycle --kill-drp <det>_1)."""
    hosts = getattr(args, 'hosts', None)
    why = unavailable('d', hosts)
    sha, dirty = head()
    if why:
        print('---- FEATURE d report', flush=True)
        print(f'job {os.environ.get("SLURM_JOB_ID")} step {os.environ.get("SLURM_STEP_ID")} host '
              f'{socket.gethostname()} HEAD {sha} (files changed: {dirty}) hosts {hosts or "none"} '
              f'allocated {",".join(allocated_hosts()) or "none"}', flush=True)
        print(f'FEATURE d NOT AVAILABLE: {why}', flush=True)
        return 1
    events = args.events or 1000
    peers, crc, problems = {}, None, []
    rc = run_echo(daq_sim('up', '-w', work.dir, '--detach', '-p', str(args.platform), '--hosts', hosts,
                          *up_options('d', args.platform)), '  up| ', timeout=600)
    try:
        if rc != 0:
            problems.append(f'up --hosts exit {rc}')
        else:
            st = work.load()
            kill = ['--kill-drp', sorted(st['remote'])[0]] if args.breakage == 'kill-remote-drp' else []
            p = subprocess.Popen(daq_sim('cycle', '-w', work.dir, '--events', str(events), '--timeout',
                                         str(args.timeout), *kill), stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, bufsize=1)
            timer = threading.Timer(1800, p.kill)
            timer.start()
            try:
                for line in p.stdout:
                    print(f'  cycle| {line.rstrip()}', flush=True)
                    if not peers and re.search(r' status: transition \S+ state running', line):
                        try:            # while Running: the connections between the hosts
                            peers = tcp_peers(st['two'])
                            peers['when'] = ds.now()
                        except Exception as e:
                            peers = {'error': f'{type(e).__name__}: {e}'}
                        print(f'{ds.now()} ss -tnp read on both hosts while Running', flush=True)
                crc = p.wait()
            finally:
                timer.cancel()
            print(f'{ds.now()} cycle exit {crc}', flush=True)
    finally:
        if not args.keep_up:
            rc_down = run_echo(daq_sim('down', '-w', work.dir), '  down| ', timeout=300)
            print(f'{ds.now()} down exit {rc_down}', flush=True)
            if rc_down != 0:
                problems.append(f'down exit {rc_down} (not clean)')
    state = work.load() or {}
    two = state.get('two') or {}
    rec = last_cycle(work) or {'counts': {}, 'transitions': []}
    counts = dict(rec.get('counts') or {})
    m = re.search(r'/(\w+)-r(\d{4})-s\d+-c000\.xtc2', str(counts.get('xtc2 file', '')))
    rec['experiment'], rec['run'] = (m.group(1), int(m.group(2))) if m else (None, None)
    print('---- FEATURE d: hosts', flush=True)
    for h in two.get('hosts', []):
        procs = [i for i in ds.procs(state) if (state.get('remote') or {}).get(i, two['hosts'][0]) == h]
        print(f'  {h} {two["ips"][h]} ({two["nic"].get(h)}): {" ".join(procs)}', flush=True)
    for h, info in (state.get('hostd') or {}).items():
        print(f'  procmgrd on {h}: Slurm step {info.get("job")}.{info.get("step")} (twonode.hostd)', flush=True)
    if two:
        from psdaq.sim import twonode
        a, b = two['hosts']
        for h in (a, b):                # what up --hosts set (twonode.epics_env): A's IP, B's own for its servers
            env = twonode.epics_env(two['ips'][a], two['ips'][h])
            print(f'  EPICS on {h}: ' + ' '.join(f'{k}={v}' for k, v in env.items() if 'AUTO' not in k) +
                  ' (AUTO_ADDR_LIST and AUTO_BEACON_ADDR_LIST NO; ports from sim_env.sh)', flush=True)
    print(f'  established TCP between the hosts while Running ({peers.get("when", "not read")}):', flush=True)
    for h in two.get('hosts', []):
        conns = peers.get(h) or []
        daq = [c for c in conns if any(f'(("{n}"' in c[2] for n in DAQ_PROGRAMS)]
        print(f'    on {h}: {len(conns)} connection(s), {len(daq)} owned by DAQ processes', flush=True)
        for loc, peer, own in conns:
            print(f'      {loc:<22} -> {peer:<22} {own}', flush=True)
        if not daq:
            problems.append(f'ss -tnp on {h} shows no established TCP connection to the other host owned by a DAQ '
                            f'process ({peers.get("error", "")})')
    remote = state.get('remote') or {}
    for k in list(counts):
        if k.startswith('drp '):
            counts[k] = f'on {remote.get(k[4:], two.get("hosts", ["?"])[0])}: {counts[k]}'
    if not remote:
        problems.append('no DRP ran on the second host')
    if crc != 0:
        problems.append(f'cycle exit {crc}' + (' (--break kill-remote-drp)' if args.breakage else ''))
    elif counts.get('per-DRP checks') != 'PASS':
        problems.append(f'per-DRP checks: {counts.get("per-DRP checks")}')
    if crc == 0 and not rec.get('ok'):
        problems.append('the cycle failed')
    return report('d', work, state, rec, counts, problems, started)


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
            mine = xtc2_check.check(path, alias.rsplit('_', 1)[0], None).get('with_data')
        except Exception:
            mine = 0
        if mine:
            dg = xtc2_dgrams(out)
            l1 = [i for i, d in enumerate(dg) if d[2] == 12]
            cut = dg[l1[len(l1) - drop]][0]
            with open(out, 'r+b') as f:
                f.truncate(cut)
            print(f'{ds.now()} --break drop-l1: {os.path.basename(path)} ({alias}): kept {len(l1) - drop} of '
                  f'{len(l1)} L1Accepts, cut at {cut} B (in a copy, {dst}, removed after the check)', flush=True)
    return dst


def scan_steps(path, det_name):
    """[(step_value, step_docstring, events, events with det_name's data)] of the run in one
    stream file; the values are None in a stream that does not record them."""
    os.environ.setdefault('LCLS_CALIB_HTTP', 'http://127.0.0.1:9/ws')
    from psana import DataSource
    out = []
    ds_ = DataSource(files=[path], skip_calib_load='all')
    for run in ds_.runs():
        sv = run.Detector('step_value', accept_missing=True)
        sd = run.Detector('step_docstring', accept_missing=True)
        has = type(sv).__name__ != 'MissingDet'     # step_value is an env variable, not a detector
        det = run.Detector(det_name)
        for step in run.steps():
            n = k = 0
            for evt in step.events():
                n += 1
                k += det.raw._segments(evt) is not None     # any type's data (tb: ts_raw)
            out.append((sv(step) if has else None, sd(step) if has else None, n, k))
    return out


def check_b(work, state, rec, breakage=None):
    """Feature b's verdict: the recorder's steps and step values (TimingBEB records them, as the
    timing system does at the hutches), each DRP's events per step, DAQ == psana2, the per-event
    checks, and the scanned detector's config code applying each step's value."""
    from psdaq.sim import xtc2_check
    counts, problems = dict(rec['counts']), []
    experiment, run = rec.get('experiment'), rec.get('run')
    want = [v + (1 if breakage == 'expect-values' else 0) for v in SCAN_VALUES]
    events = rec.get('events_per_step')
    files = sorted(glob.glob(work.path('data', ds.INSTRUMENT, experiment or 'none', 'xtc',
                                       f'{experiment}-r{run or 0:04d}-s*-c000.xtc2')))
    if not files:
        return counts, [f'no xtc2 file of run {run}']
    links = counts.get('simxpm links')
    links = links if isinstance(links, dict) else {}
    recorded = None
    for name in [state['det']] + [a['det'] for a in state.get('also', ())]:
        res = path = None
        for f in files:                 # its stream: the file in which it has data
            try:
                r = xtc2_check.check(f, name, state['seed'])
            except Exception:
                continue
            if r.get('with_data'):
                res, path = r, f
                break
        daq = (links.get(f'{name}_0') or {}).get('l1acc')
        if res is None:
            problems.append(f'{name}_0: no stream with its data (DAQ {daq})')
            continue
        steps = scan_steps(path, name)
        counts[f'drp {name}_0'] = (f'DAQ (simxpm L1Accepts sent) {daq} psana2 events {res["events"]} with data '
                                   f'{res["with_data"]} per step {[s[2] for s in steps]} per-event check '
                                   f'{"PASS" if res["pass"] else "FAIL " + str(res["problems"][:2])} '
                                   f'({os.path.basename(path)})')
        if not (res['pass'] and daq == res['events'] == res['with_data'] == sum(s[2] for s in steps)):
            problems.append(f'{name}_0: DAQ {daq}, psana2 {res["events"]}/{res["with_data"]}, check {res["pass"]}')
        if events and any(n != events or k != n for _, _, n, k in steps):
            problems.append(f'{name}_0: events per step {[(s[2], s[3]) for s in steps]}, want {events} each')
        if steps and steps[0][0] is not None:
            recorded = (name, steps)
    if recorded is None:
        return counts, problems + ['no stream records step_value']
    name, steps = recorded
    counts['psana2 steps'] = f'{len(steps)} (step_value and step_docstring in {name}_0\'s stream)'
    for i, (v, doc, n, k) in enumerate(steps):
        counts[f'step {i + 1}'] = f'step_value {v} step_docstring {doc} events {n}'
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
        if v is None or float(d.get('step', -1)) != v:
            problems.append(f'step {i + 1}: docstring {doc!r} does not name step {v}')
    applied = scan_applied(work, SCAN_DET)
    counts[f'{SCAN_DET}_update start_ns'] = applied
    if [float(a) for a in applied] != list(SCAN_VALUES):
        problems.append(f'{SCAN_DET}_config applied start_ns {applied}, the scan set {list(SCAN_VALUES)}')
    if counts.get('scan exit') != 0:
        problems.append(f'scan script exit {counts.get("scan exit")}')
    return counts, problems


def scan_applied(work, det):
    """The start_ns values the scanned detector's config code applied, step by step, from its
    DRP's log (epix100_config.epix100_update prints each)."""
    logs = sorted(glob.glob(work.path('pmlogs', '*', '*', f'*:{det}_0.log')), key=os.path.getmtime)
    if not logs:
        return []
    with open(logs[-1], errors='replace') as f:
        return [int(m.group(1)) for m in re.finditer(r'\*\*\*%s_update start_ns: (\d+)' % det, f.read())]


# --- feature b's drive: the facility's scan script against the simulated DAQ ----------------

def drive_scan(work, events, timeout):
    """Bring the DAQ to connected (selecting every process, as the GUIs do), run
    generic_timing_scan.py, bring it back to reset; returns the record check_b reads."""
    from psdaq.control.DaqControl import DaqControl
    state = work.load()
    plat = state['platform']
    dc = DaqControl(host='localhost', platform=plat, timeout=timeout * 1000)
    msgs, rows, stop, last = [], [], threading.Event(), [None]

    def monitor():
        mon = DaqControl(host='localhost', platform=plat, timeout=1000)
        mon.front_sub.setsockopt(ds.zmq_rcvtimeo(), 500)
        while not stop.is_set():
            try:
                m = mon.front_sub.recv_json()
            except Exception:
                continue
            key, body = m.get('header', {}).get('key'), m.get('body', {}) or {}
            if key == 'status':             # control's status after each transition
                now = (body.get('transition'), body.get('state'))
                if now != last[0]:
                    last[0] = now
                    rows.append((ds.now(), ds.now(), f'[{now[0]}]', now[1], None))
                    print(f'{ds.now()} [status] transition {now[0]} -> state {now[1]}', flush=True)
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
                '--detname', f'{SCAN_DET}_0', '--scantype', 'timing', '--events', str(events),
                '--record', '1', '--config', ds.CONFIG_ALIAS, '-t', str(timeout * 1000),
                '--linear', '700000', '730000', '10000']
        print(f'{ds.now()} scan: {" ".join(argv[1:])}', flush=True)
        rc = run_echo(argv, '  scan| ', timeout=600, env=dict(os.environ, PYTHONUNBUFFERED='1'))
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
                                                 'bld_miss', 'scan exit', f'{SCAN_DET}_update', 'MEB_EvtCt',
                                                 'shmemClient', 'ami ')):
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
    if args.breakage and not args.check_only and feature != 'd':
        raise ds.Fail('--break needs --check-only (it breaks a copy of a recorded run)')
    if feature == 'd':
        return feature_d(args, work, started)
    events = args.events or (200 if feature == 'b' else 1000)
    ami_src = getattr(args, 'ami_src', None)
    if not args.check_only:
        rc = run_echo(daq_sim('up', '-w', work.dir, '--detach', '-p', str(args.platform),
                              *up_options(feature, args.platform),
                              *(['--ami-src', ami_src] if feature == 'c' and ami_src else [])),
                      '  up| ', timeout=600)
        try:
            if rc != 0:
                print(f'{ds.now()} up exit {rc}', flush=True)
                return 1
            if feature == 'b':
                drive_scan(work, events, args.timeout)
            else:
                shot = ['--ami-shot', work.path('ami-shot.png')] if feature == 'c' else []
                rc = run_echo(daq_sim('cycle', '-w', work.dir, '--events', str(events),
                                      '--timeout', str(args.timeout), *shot), '  cycle| ', timeout=1800)
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
        if not args.check_only and not problems:     # evidence of the scan, as a cycle's
            ds._record_cycle_evidence(work, state, rec['experiment'], rec['run'], rec['counts'], started,
                                      kind='scan', log='feature-b.jsonl')
    else:
        rec = last_cycle(work)
        if rec is None:
            raise ds.Fail(f'no cycle recorded in {work.dir}')
        m = [k for k in rec['counts'] if k == 'xtc2 file']
        path = rec['counts'].get('xtc2 file', '') if m else ''
        mm = re.search(r'/(\w+)-r(\d{4})-s\d+-c000\.xtc2', path)
        rec['experiment'], rec['run'] = (mm.group(1), int(mm.group(2))) if mm else (None, None)
        if feature == 'c':
            counts, problems = check_c(work, state, rec, args.breakage, recompute=args.check_only)
            if not args.check_only and rc != 0:
                problems.append(f'cycle exit {rc}')
            elif not args.breakage and not rec.get('ok'):
                problems.append('the cycle failed')
        elif not args.check_only and rc != 0:
            counts, problems = rec['counts'], [f'cycle exit {rc}']
        else:
            if feature == 'a':
                counts, problems = check_a(work, state, rec, args.breakage, recompute=args.check_only)
            else:
                counts, problems = check_e(work, state, rec, args.breakage)
            if not args.breakage and not rec.get('ok'):
                problems.append('the cycle failed')
    return report(feature, work, state, rec, counts, problems, started)
