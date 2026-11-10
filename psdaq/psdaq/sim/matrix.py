"""daq_sim matrix: the whole hardware-free matrix, unattended; its exit code is the verdict.

    daq_sim matrix [-w WORKDIR] [-p PLATFORM] [--only types|programs|features|coverage]...
                   [--types T,T,..] [--features x,x,..] [--events N] [--lock FILE]
                   [--ami-src DIR] [--hosts A,B [--locks LOCK_A,LOCK_B]] [--gpu-host G]
                   [--summary FILE] [--repo DIR] [--status FILE] [--evidence DIR] [-v]
    daq_sim matrix -w WORKDIR --break register|kill-drp|corrupt [--types T] [--fault PATH]

Sections, in this order (--only picks some, repeated or comma-separated):
  types     one DAQ per detector type, each in its own work dir <WORKDIR>/types/<T> (replaced by
            the type's next run): daq_sim up --det T --detach, one recorded daq_sim cycle of
            --events L1Accepts, daq_sim down.  The types are every det:drp row that
            coverage_status.json marks RUN, in the order the DRP factory registers them, plus any
            other type daq_sim up --det runs (daq_sim.SIM_TYPES); --types picks some.  Assertions,
            each named types/<T>/<what>:
              up           daq_sim up exits 0
              transitions  every transition reads back as requested, control's status stream
                           carries no error, and the run ends in the state it started from
              drp-alive    the DRP of <T>_0 is the process 'up' started, still alive after the run
              counts       simxpm's L1Accepts == the TEB's recorded events (TEB_WrtCt) ==
                           psana2's events == psana2's events with <T>'s data, all >= --events
              per-event    psdaq.sim.xtc2_check compared every event's data, through <T>'s own
                           psana interface, with the payload the simulated device was set to make
              evidence     the cycle wrote an evidence record for det:drp:<T> that coverage accepts
              down         daq_sim down exits 0: everything 'up' started stopped, the ports free
            A RUN row that daq_sim up --det cannot run fails as types/<T>/runnable.
            Each type gets one line: type, node, job, run file, the DAQ's recorded count
            (TEB_WrtCt), psana2's events, events with data, the per-event verdict, its verdict.
  programs  one DAQ with every program option of daq_sim up (PROGRAM_OPTIONS: the MEB, AMI, drp_pva,
            epicsArch, drp_udpencoder and sim_udpencoder, the PyQt GUIs, the PV-server stand-ins
            simhsd, simtpr and simdti and the GUIs on them, tprtrig, tpr_trigger and lclsBldServer on simulated
            TPR cards, the HPS BLD chain; with $PSDAQ_SIM_WAVE8PVS_ENV and $PSDAQ_SIM_WAVE8PVS_SRC set, also
            wave8pvs in that env; RUNBOOK 3m), in
            <WORKDIR>/programs: up, one recorded cycle with --ami-shot, down.  Assertions
            programs/<what>: those of a type for fakecam_0, and 'checks' (the cycle's checks of
            the system DRPs, AMI against psana2, the GUIs' witness and the AMI screenshot all
            PASS); its 'evidence' needs every row of the record accepted.  AMI comes from
            --ami-src, else daq_sim up's default ($DAQ_SIM_AMI_SRC, else ami-* on PATH).
  features  daq_sim feature <x> (psdaq.sim.feature: up, its run, its checks, down) for x = a..e,
            in <WORKDIR>/features/<x>; assertions features/<x> (FEATURE <x> PASS, exit 0) and
            features/<x>/down.  c gets --ami-src, d --hosts.  A feature psdaq.sim.feature does not
            provide, or one it cannot run here (feature.unavailable: d without --hosts naming two
            hosts of this Slurm job), is NOT AVAILABLE, a failed assertion, and starts nothing.
  coverage  daq_sim coverage at HEAD (the cycles above write its evidence): assertion coverage.

The summary lists every assertion and ends 'MATRIX PASS' (exit 0) only if all of them passed;
else 'MATRIX FAIL' and each failed assertion with why (exit 1).  It is also written as JSON
to --summary (default <WORKDIR>/matrix-summary.json).  For the types, features and coverage
not run this time, the JSON keeps the last result recorded at the same HEAD ('carried', with
its time), so a section can be re-run alone (--only, --types, --features); its 'whole'
verdict covers all of them, and the exit code what ran this time.

--lock FILE (default $DAQ_SIM_MATRIX_LOCK) takes an exclusive flock(2) on FILE around each DAQ,
from 'up' to 'down' of one type or one feature, and releases it in between, for a node where
DAQs take turns (flock(1) takes the same lock); it waits up to --lock-timeout s.

Over two hosts of this Slurm job (run on the first): --hosts A,B --locks LOCK_A,LOCK_B.  The types
are shared out between the hosts (every other one to B): B's run as one more 'daq_sim matrix --only
types' in a step of the job on B (srun --overlap), in <WORKDIR>/hosts/<B>, with LOCK_A's place taken
by LOCK_B (each a file on its own host), while A runs its own; their results join this run's, each
type's line naming its node.  The programs run and features a, b, c and e run on A under LOCK_A;
feature d (daq_sim feature d --hosts A,B) holds LOCK_A and then LOCK_B (taken by flock(1) in a step
on B) from its 'up' to its 'down'.  Coverage then reads the evidence of all of them (both hosts
write to the same evidence dir, which they must share).  --gpu-host G runs the GPU DRP's types
(daq_sim.GPU_SIM_TYPES, the det:drp_gpu rows) on G, meanwhile: one more 'daq_sim matrix --only types
--drp drp_gpu' in a step on G of the Slurm job that holds G (--gpu-job, default the one squeue shows
running there; --gpu-gres, default gpu:1), in <WORKDIR>/gpu/<G>, each DAQ under --gpu-lock (a file
on G).  drp_gpu finds its CUDA runtime through $DAQ_SIM_CUDA_LIB (daq_sim up --cuda-lib), which the
step inherits.  Their results join this run's as types drp_gpu:<T>, each line naming its node.

Deliberate breaks show that the matrix fails, naming the failed assertion.  Each runs one type
(default below, or --types) in <WORKDIR>/break-<kind> (its own summary; no feature, no
coverage, no evidence) and must exit 1:
  register  PSDAQ_SIM_ROGUE_FAULT=<register> in the DAQ's environment (--fault, default the
            type's in FAULTS): the simulated device reads that register back wrong, so the
            type's config code fails Configure (psdaq.sim.rogue_dev); default type epix100
  kill-drp  daq_sim cycle --kill-drp: SIGKILL the type's DRP once Running; default fakecam
  corrupt   PSDAQ_SIM_CORRUPT_SEQ=<--events / 2>: MemPoolSim inverts one byte of that
            L1Accept's payload, which only the per-event check can see; default fakecam
"""

import argparse
import datetime
import fcntl
import glob
import io
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time

from psdaq.sim import coverage
from psdaq.sim import daq_sim as ds

SECTIONS = ('types', 'programs', 'features', 'coverage')
# The programs run: every program option of daq_sim up, at a camera's rate (RUNBOOK 3m)
PROGRAM_OPTIONS = ('--ami', '--pva', '--epics', '--udp', '--gui', '--pvservers', '--tpr', '--hps', '--rate', '100')
PROGRAM_CHECKS = ('system DRP checks', 'ami check', 'gui witness', 'ami shot')
FEATURES = ('a', 'b', 'c', 'd', 'e')             # the contract's system features (a)-(e)
BREAKS = ('register', 'kill-drp', 'corrupt')
BREAK_TYPES = {'register': 'epix100', 'kill-drp': 'fakecam', 'corrupt': 'fakecam'}
# A register each type's config code writes and verifies at Configure (RUNBOOK §3e, §3g)
FAULTS = {
    'epix100': 'ePixBoard.ePix100aFPGA.EpixFpgaRegisters.DaqTriggerDelay',
    'hrencoder': 'Root.App.TimingRx.TriggerEventManager.TriggerEventBuffer[0].TriggerDelay',
    'epixm320': 'Root.App.TimingRx.TriggerEventManager.TriggerEventBuffer[0].TriggerDelay',
    'opal': 'ClinkDevRoot.ClinkPcie.Hsio.TimingRx.TriggerEventManager.TriggerEventBuffer[0].TriggerDelay',
    'piranha4': 'ClinkDevRoot.ClinkPcie.Hsio.TimingRx.TriggerEventManager.TriggerEventBuffer[0].TriggerDelay',
    'tb': 'DevRoot.DevPcie.Hsio.TimingRx.TriggerEventManager.TriggerEventBuffer[3].TriggerDelay',
    'epixquad': 'Top.SystemRegs.TrigEn=0',
}
ENV_FAULT = 'PSDAQ_SIM_ROGUE_FAULT'             # psdaq.sim.rogue_dev.ENV_FAULT
ENV_CORRUPT = 'PSDAQ_SIM_CORRUPT_SEQ'           # MemPoolSim::CorruptEnv
TYPE_CHECKS = ('up', 'transitions', 'drp-alive', 'counts', 'per-event', 'evidence', 'down')
FAULT_LINE = re.compile(r'FAULT |Verify error|Error|error|Traceback|python error')


def say(*a):
    print(f'{ds.now()} matrix:', *a, flush=True)


def csv(values):
    """--only/--types/--features: repeated, comma-separated."""
    return [v for item in values or () for v in item.split(',') if v]


def add_arguments(p):
    p.add_argument('-p', '--platform', type=int, default=5, choices=range(8))
    p.add_argument('--only', action='append', metavar='SECTION',
                   help=f'run only these sections, of {",".join(SECTIONS)} (default: all; repeatable)')
    p.add_argument('--types', action='append', metavar='T,T',
                   help='run only these detector types (default: every RUN row and SIM_TYPES)')
    p.add_argument('--features', action='append', metavar='x,x',
                   help=f'run only these features, of {",".join(FEATURES)} (default: all)')
    p.add_argument('--events', type=int, default=1000, help='L1Accepts of each cycle (default %(default)d)')
    p.add_argument('--ami-src', default=None, help='programs: AMI source tree for up --ami (default: up\'s, '
                   '$DAQ_SIM_AMI_SRC, else ami-* on PATH)')
    p.add_argument('--hosts', default=None, metavar='HOST_A,HOST_B',
                   help='feature d\'s two hosts (two hosts of this Slurm job; else d is NOT AVAILABLE); with '
                        '--locks, the types are shared out between them (module doc)')
    p.add_argument('--locks', default=None, metavar='LOCK_A,LOCK_B',
                   help='with --hosts: each host\'s lock file (a file on that host), LOCK_A in --lock\'s place')
    p.add_argument('--gpu-host', default=None, metavar='HOST',
                   help='run the GPU DRP\'s types (det:drp_gpu) on HOST, in a step of the job that holds it '
                        '(module doc)')
    p.add_argument('--gpu-job', default=None, metavar='JOBID',
                   help='with --gpu-host: the Slurm job that holds it (default: the one squeue shows running there)')
    p.add_argument('--gpu-gres', default='gpu:1', help='with --gpu-host: the step\'s --gres (default %(default)s)')
    p.add_argument('--gpu-lock', default=None,
                   help='with --gpu-host: flock(2) this file on that host around each DAQ (default none)')
    p.add_argument('--drp', default='drp', choices=('drp', 'drp_gpu'),
                   help='the DRP the types section runs (drp_gpu: the GPU_SIM_TYPES, in a step that holds a GPU; '
                        '--gpu-host runs it so) (default %(default)s)')
    p.add_argument('--lock', default=os.environ.get('DAQ_SIM_MATRIX_LOCK'),
                   help='flock(2) this file around each DAQ (default $DAQ_SIM_MATRIX_LOCK, else none)')
    p.add_argument('--lock-timeout', type=int, default=3600, help='s to wait for --lock (default %(default)d)')
    p.add_argument('--break', dest='breakage', choices=BREAKS, default=None,
                   help='a deliberate break, to see the matrix fail (module doc)')
    p.add_argument('--fault', default=None, help=f'with --break register: the {ENV_FAULT} value '
                   '(default: the type\'s register in matrix.FAULTS)')
    p.add_argument('--summary', default=None, help='summary JSON (default <workdir>/matrix-summary.json)')
    p.add_argument('--repo', help='checkout coverage checks (default: the one holding this module)')
    p.add_argument('--status', help='coverage status file (default <repo>/psdaq/psdaq/sim/coverage_status.json)')
    p.add_argument('--evidence', help='evidence dir (default $DAQ_SIM_EVIDENCE, else <repo>/.daq_sim/evidence)')
    p.add_argument('-v', '--verbose', action='store_true', help='coverage: show where each row comes from')


# --- helpers ----------------------------------------------------------------------------------

def daq_sim(*args):
    return [sys.executable, '-m', 'psdaq.sim.daq_sim'] + list(args)


def run(argv, prefix, timeout, env=None):
    """Run argv, echoing each output line with a prefix; (exit code, lines).  A run over its
    timeout is killed (exit -9)."""
    p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                         env=env, errors='replace')
    timer = threading.Timer(timeout, p.kill)
    timer.start()
    lines = []
    try:
        for line in p.stdout:
            line = line.rstrip()
            lines.append(line)
            print(f'{prefix}{line}', flush=True)
        return p.wait(), lines
    finally:
        timer.cancel()


class _LockTimeout(Exception):
    pass


def _alarm(signum, frame):
    raise _LockTimeout()


class Lock:
    """An exclusive flock(2) on path for one DAQ's span (none if path is empty).  It waits in
    the kernel's queue, as flock(1) does (polling with LOCK_NB would lose every hand-over to a
    queued flock(1)), for at most timeout s (SIGALRM)."""
    def __init__(self, path, timeout):
        self.path, self.timeout, self.f = path, timeout, None

    def __enter__(self):
        if not self.path:
            return self
        self.f = open(self.path, 'a')
        t0 = time.monotonic()
        try:
            fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if self.timeout <= 0:
                self.f.close()
                raise ds.Fail(f'lock {self.path}: not free after 0 s')
            say(f'lock {self.path} taken: waiting (at most {self.timeout} s)')
            old = signal.signal(signal.SIGALRM, _alarm)
            signal.alarm(self.timeout)
            try:
                fcntl.flock(self.f, fcntl.LOCK_EX)
            except _LockTimeout:
                self.f.close()
                raise ds.Fail(f'lock {self.path}: not free after {self.timeout} s') from None
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old)
        say(f'lock {self.path} held (waited {time.monotonic() - t0:.0f} s)')
        return self

    def __exit__(self, *exc):
        if self.f:
            fcntl.flock(self.f, fcntl.LOCK_UN)
            self.f.close()
            say(f'lock {self.path} released')
        return False


class RemoteLock:
    """flock(1) on path on another host of this Slurm job, held by a step there from __enter__ to __exit__
    (its stdin closing ends it); waits at most timeout s."""
    def __init__(self, host, path, timeout):
        self.host, self.path, self.timeout, self.p = host, path, timeout, None

    def __enter__(self):
        from psdaq.sim import twonode
        if not (self.host and self.path):
            return self
        argv = twonode.srun_argv(self.host, ['flock', '-w', str(self.timeout), self.path, 'sh', '-c',
                                             'echo locked; read x'], cpus=1, mem='1G')
        say(f'lock {self.path} on {self.host}: taking it (at most {self.timeout} s)')
        t0 = time.monotonic()
        self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, env=twonode.srun_env())
        line = self.p.stdout.readline()
        if line.strip() != 'locked':
            self.p.kill()
            raise ds.Fail(f'lock {self.path} on {self.host}: not taken ({line.strip() or "no answer"}, '
                          f'exit {self.p.wait()})')
        say(f'lock {self.path} on {self.host} held (waited {time.monotonic() - t0:.0f} s)')
        return self

    def __exit__(self, *exc):
        if self.p:
            self.p.stdin.close()
            try:
                self.p.wait(60)
            except subprocess.TimeoutExpired:
                self.p.kill()
            say(f'lock {self.path} on {self.host} released')
        return False


def remote_types(args, host, lock, types, wd, env):
    """Start 'daq_sim matrix --only types' for types on host, in a step of this job there; (Popen, summary
    path).  Its output is echoed with a prefix by a thread."""
    from psdaq.sim import twonode
    summ = os.path.join(wd, 'matrix-summary.json')
    argv = [sys.executable, '-m', 'psdaq.sim.daq_sim', 'matrix', '-w', wd, '-p', str(args.platform), '--only',
            'types', '--types', ','.join(types), '--events', str(args.events), '--summary', summ,
            '--lock-timeout', str(args.lock_timeout)] + (['--lock', lock] if lock else []) + \
        [o for k in ('repo', 'status', 'evidence') if getattr(args, k, None) for o in (f'--{k}', getattr(args, k))]
    os.makedirs(wd, exist_ok=True)
    if os.path.exists(summ):
        os.unlink(summ)
    say(f'types on {host}: {" ".join(types)} (a step of job {os.environ.get("SLURM_JOB_ID")} there, {wd})')
    p = subprocess.Popen(twonode.srun_argv(host, argv, cpus=16, mem='32G'), stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, bufsize=1, errors='replace',
                         env=twonode.srun_env(env), stdin=subprocess.DEVNULL)

    def echo():
        for line in p.stdout:
            print(f'  [{host}] {line.rstrip()}', flush=True)
    t = threading.Thread(target=echo, daemon=True)
    t.start()
    p.echo = t
    return p, summ


def gpu_job(host):
    """The id of the Slurm job of this user that runs on host (squeue), or None."""
    r = subprocess.run(['squeue', '-h', '-u', os.environ.get('USER', ''), '-t', 'R', '-w', host, '-o', '%i'],
                       capture_output=True, text=True, timeout=60, env=_no_step_env(),
                       stdin=subprocess.DEVNULL)
    jobs = r.stdout.split()
    return jobs[0] if r.returncode == 0 and jobs else None


def _no_step_env(environ=None):
    from psdaq.sim import twonode
    return twonode.srun_env(environ)


def gpu_step_argv(host, job, gres, argv):
    """srun of argv as one task in a new step of Slurm job `job` on host, holding a GPU (--gres)."""
    return ['srun', f'--jobid={job}', '--overlap', '-w', host, '-N', '1', '--ntasks=1', '--cpus-per-task=16',
            '--mem=64G', f'--gres={gres}', '--kill-on-bad-exit=1'] + list(argv)


def remote_gpu_types(args, host, job, types, wd, env):
    """Start 'daq_sim matrix --only types --drp drp_gpu' for types on the GPU host, in a step of its job there;
    (Popen, summary path).  Its output is echoed with a prefix by a thread."""
    summ = os.path.join(wd, 'matrix-summary.json')
    argv = [sys.executable, '-m', 'psdaq.sim.daq_sim', 'matrix', '-w', wd, '-p', str(args.platform), '--only',
            'types', '--drp', 'drp_gpu', '--types', ','.join(types), '--events', str(args.events), '--summary',
            summ, '--lock-timeout', str(args.lock_timeout)] + (['--lock', args.gpu_lock] if args.gpu_lock else []) + \
        [o for k in ('repo', 'status', 'evidence') if getattr(args, k, None) for o in (f'--{k}', getattr(args, k))]
    os.makedirs(wd, exist_ok=True)
    if os.path.exists(summ):
        os.unlink(summ)
    say(f'GPU types on {host}: {" ".join(types)} (a step of job {job} there, --gres={args.gpu_gres}, {wd})')
    p = subprocess.Popen(gpu_step_argv(host, job, args.gpu_gres, argv), stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, bufsize=1, errors='replace',
                         env=_no_step_env(env), stdin=subprocess.DEVNULL)

    def echo():
        for line in p.stdout:
            print(f'  [{host}] {line.rstrip()}', flush=True)
    t = threading.Thread(target=echo, daemon=True)
    t.start()
    p.echo = t
    return p, summ


def type_key(det, drp='drp'):
    """A type's name in the summary: the type for drp, drp_gpu:<type> for the GPU DRP."""
    return det if drp == 'drp' else f'{drp}:{det}'


def fresh(wd):
    """An empty work dir: one left up by an earlier run is taken down first."""
    st = ds.Work(wd).load()
    if st is not None and st.get('down') != 'done':
        run(daq_sim('down', '-w', wd), '  (earlier) down| ', 300)
    shutil.rmtree(wd, ignore_errors=True)
    os.makedirs(wd)


def last_record(path):
    try:
        with open(path) as f:
            return json.loads(f.read().strip().splitlines()[-1])
    except (OSError, IndexError, ValueError):
        return None


def drp_log_lines(wd, alias, pattern=FAULT_LINE, n=3):
    """The first n lines of alias's newest procmgr log that match pattern ('FAULT' and 'Verify
    error' first: rogue_dev's and rogue's words for a register that read back wrong)."""
    logs = sorted(glob.glob(os.path.join(wd, 'pmlogs', '*', '*', f'*:{alias}.log')), key=os.path.getmtime)
    if not logs:
        return []
    with open(logs[-1], errors='replace') as f:
        lines = [l.strip() for l in f if pattern.search(l)]
    first = [l for l in lines if 'FAULT ' in l or 'Verify error' in l]
    return (first + [l for l in lines if l not in first])[:n]


def head(repo):
    try:
        return coverage.head(repo), coverage.dirty(repo)
    except Exception as e:                       # noqa: BLE001 (reported, not fatal)
        return f'unknown ({e})', None


# --- what runs --------------------------------------------------------------------------------

def run_types(repo, status_path=None):
    """[(type, row id or None)]: every det:drp row the status file marks RUN, in the order the
    factory registers them, then the SIM_TYPES types with no RUN row; and [RUN rows that daq_sim
    up --det cannot run]."""
    rows, _ = coverage.enumerate_rows(repo)
    status, _ = coverage.load_status(status_path or os.path.join(repo, coverage.STATUS_FILE), rows)
    claimed = [r for r in rows if r.startswith('det:') and (status.get(r) or {}).get('status') == 'RUN']
    out, cannot = [], []
    for r in claimed:
        exe, det = r.split(':')[1:]
        if exe == 'drp' and det in ds.SIM_TYPES:
            out.append((det, r))
        else:
            cannot.append(r)
    out += [(t, None) for t in ds.SIM_TYPES if t not in {d for d, _ in out}]
    return out, cannot


def available_features():
    from psdaq.sim import feature
    return tuple(getattr(feature, 'FEATURES', ()))


def feature_unavailable(x, hosts=None):
    """Why feature x cannot run here (psdaq.sim.feature.unavailable), or None."""
    from psdaq.sim import feature
    if x not in available_features():
        return f'psdaq.sim.feature runs {",".join(available_features()) or "none"}'
    check = getattr(feature, 'unavailable', None)
    return check(x, hosts) if check else None


# --- one DAQ: a type, or the programs run ---------------------------------------------------

def type_up_args(det, drp='drp'):
    """up's options for one type: --drp for the GPU DRP, and --rate for a type that runs at a rate of its own
    (daq_sim's table, 'rate': jungfrau at 100 Hz, as the RUNBOOK runs it)."""
    table = ds.GPU_SIM_TYPES if drp == 'drp_gpu' else ds.SIM_TYPES
    rate = (table.get(det) or {}).get('rate')
    return ([] if drp == 'drp' else ['--drp', drp]) + ([] if rate is None else ['--rate', str(rate)])


def run_type(args, det, wd, env, kill=False, drp='drp'):
    """One type's DAQ: up --det (--drp drp_gpu for the GPU DRP; the type's own --rate), a recorded cycle, down;
    assertions types/<det>/<what> (types/drp_gpu:<det>/<what>)."""
    return run_daq(args, f'types/{type_key(det, drp)}', det, wd, env, type_up_args(det, drp), [],
                   kill=kill, drp=drp)


def run_programs(args, wd, env):
    """The programs run: up with PROGRAM_OPTIONS (the MEB, AMI, the system DRPs, the GUIs), a
    recorded cycle with the AMI screenshot, down; assertions programs/<what>."""
    up = list(PROGRAM_OPTIONS) + (['--ami-src', args.ami_src] if args.ami_src else [])
    if os.environ.get('PSDAQ_SIM_WAVE8PVS_ENV') and os.environ.get('PSDAQ_SIM_WAVE8PVS_SRC'):
        up.append('--wave8pvs')         # its site env and wave8 source (R6b, RUNBOOK 3d)
    return run_daq(args, 'programs', 'fakecam', wd, env, up, ['--ami-shot', os.path.join(wd, 'ami-shot.png')])


def run_daq(args, name, det, wd, env, up_extra, cycle_extra, kill=False, drp='drp'):
    """One DAQ: up, cycle, down (holding the lock), then the assertions <name>/<what>."""
    host, job = socket.gethostname().split('.')[0], os.environ.get('SLURM_JOB_ID')
    res = {'name': name, 'type': type_key(det, drp), 'node': host, 'job': job, 'step': os.environ.get('SLURM_STEP_ID'),
           'workdir': wd, 'started': ds.now(), 'assertions': []}
    tag = name.split('/')[-1]

    def check(what, ok, detail):
        res['assertions'].append({'name': f'{name}/{what}', 'ok': bool(ok), 'detail': detail})

    fresh(wd)
    cycle_out, cycled = [], False
    try:
        with Lock(args.lock, args.lock_timeout):
            rc, out = run(daq_sim('up', '-w', wd, '--det', det, '--detach', '-p', str(args.platform), *up_extra),
                          f'  {tag} up| ', 900, env)
            check('up', rc == 0, f'exit {rc}' + ('' if rc == 0 else ': ' + ' | '.join(
                [l for l in out if 'FAIL' in l or 'Error' in l][-2:] or out[-2:])))
            if rc == 0:
                work = ds.Work(wd)
                pid0, cmd0 = ds.drp_pid(work.load() or {}, f'{det}_0')
                argv = daq_sim('cycle', '-w', wd, '--events', str(args.events), *cycle_extra) + \
                    (['--kill-drp'] if kill else [])
                rc_c, cycle_out = run(argv, f'  {tag} cycle| ', 1800, env)
                cycled = True
                pid1, _ = ds.drp_pid(work.load() or {}, f'{det}_0')
                alive = pid0 is not None and ds.pid_alive(pid0) and pid1 == pid0
                check('drp-alive', alive, f'{det}_0 drp pid {pid0} ' + (
                    'alive after the run' if alive else
                    f'GONE after the run (now {pid1 or "no process"})' if pid0 else 'not found after up'))
                res['cycle exit'] = rc_c
            rc_d, out_d = run(daq_sim('down', '-w', wd), f'  {tag} down| ', 300, env)
            clean = rc_d == 0 and any(l.rstrip().endswith('down: clean') for l in out_d)
            check('down', clean, f'exit {rc_d}, ' + ('down: clean' if clean else ' | '.join(
                [l for l in out_d if 'LEFTOVER' in l or 'still in use' in l or 'NOT clean' in l][-2:])))
    except ds.Fail as e:
        check('lock', False, str(e))
    if cycled:
        rec = last_record(os.path.join(wd, 'logs', 'cycle.jsonl'))
        type_checks(res, det, wd, rec, cycle_out, args.events, check, programs=name == 'programs', drp=drp)
    checks = TYPE_CHECKS + (('checks',) if name == 'programs' else ())
    order = checks[:1] + ('lock',) + checks[1:]
    res['assertions'].sort(key=lambda a: order.index(a['name'].rsplit('/', 1)[1]))
    res['ended'] = ds.now()
    res['pass'] = all(a['ok'] for a in res['assertions']) and \
        {a['name'].rsplit('/', 1)[1] for a in res['assertions']} >= set(checks)
    print(type_line(res), flush=True)
    return res


def type_checks(res, det, wd, rec, cycle_out, events, check, programs=False, drp='drp'):
    """The assertions read from the cycle's record (logs/cycle.jsonl) and output; for the
    programs run also 'checks' (every check of its programs) and evidence for all its rows."""
    if rec is None:
        for what in ('transitions', 'counts', 'per-event', 'evidence') + (('checks',) if programs else ()):
            check(what, False, f'the cycle wrote no record (exit {res.get("cycle exit")})')
        return
    c = rec.get('counts', {})
    bad = [r for r in rec.get('transitions', []) if r[4] is not None or r[3] != r[2]]
    errors = [m for m in rec.get('messages', []) if m[1] == 'error']
    running = any(r[2] == 'running' and r[3] == 'running' for r in rec.get('transitions', []))
    back = rec.get('final') == rec.get('start') and rec.get('start') is not None
    ok = not bad and not errors and running and back
    if ok:
        detail = (f'{len(rec["transitions"])} transitions {rec["start"]} .. running .. {rec["final"]}, '
                  'each read back as requested, no error message')
    else:
        parts = [f'setState {r[2]} -> {r[3]}' + (f' (error: {str(r[4])[:200]})' if r[4] else '') for r in bad[:2]]
        parts += [f'status stream error: {str(m[2])[:200]}' for m in errors[:2]]
        if not running:
            parts.append('never reached running')
        if not back:
            parts.append(f'ended in {rec.get("final")!r}, started in {rec.get("start")!r}')
        log = drp_log_lines(wd, f'{det}_0')
        if log:
            parts.append(f'{det}_0 log: ' + ' / '.join(l[:220] for l in log))
        detail = '; '.join(parts)
    check('transitions', ok, detail)

    l1, daq = c.get('simxpm NumL0Acc'), c.get('TEB_WrtCt')
    ev, wdata = c.get('psana2 events'), c.get('psana2 with data')
    vals = (l1, daq, ev, wdata)
    ok = None not in vals and len(set(vals)) == 1 and l1 >= events
    check('counts', ok, f'simxpm L1Accepts {l1}, TEB_WrtCt {daq}, psana2 events {ev}, with {det} data '
                        f'{wdata}: {"equal and >= " if ok else "NOT equal and >= "}{events}')

    pe = c.get('psana2 checks')
    check('per-event', pe == 'PASS', f'xtc2_check --det {det}: {pe if pe is not None else "did not run"}')

    if programs:                        # the checks of the MEB, AMI, the system DRPs, the GUIs
        keys = [k for k in PROGRAM_CHECKS if k in c]
        ok = bool(rec.get('ok')) and keys == list(PROGRAM_CHECKS) and \
            all(str(c[k]).startswith('PASS') for k in keys)
        check('checks', ok, '; '.join(f'{k}: {str(c.get(k, "did not run"))[:200]}' for k in PROGRAM_CHECKS) +
              f'; MEB_EvtCt {c.get("MEB_EvtCt")}')

    ev_lines = [l for l in cycle_out if re.search(r' evidence \S+: ', l)]
    rows = [l for l in ev_lines if 'would reject' not in l]
    rejects = [l.split('coverage would reject it for ', 1)[1] for l in ev_lines if 'would reject' in l]
    mine = [l for l in rows if f'det:{drp}:{det}' in l.split(': ', 1)[-1].split()]
    rejected = rejects if programs else [r for r in rejects if r.startswith(f'det:{drp}:{det}:')]
    eid = re.search(r' evidence (\S+): ', mine[-1]).group(1) if mine else None
    ok = bool(mine) and not rejected
    detail = (f'record {eid}' + (f' for {len(mine[-1].split(": ", 1)[-1].split())} rows' if programs else '')
              if mine else f'no evidence record for det:{drp}:' + det + (' (the cycle failed)' if not rec.get('ok') else ''))
    if rejects:
        detail += '; coverage would reject it for ' + '; '.join(r[:200] for r in rejects[:3])
    res['evidence'] = eid
    check('evidence', ok, detail)
    res.update(run_file=(c.get('xtc2 file') or '').split(' (')[0] or None, daq=daq, l1=l1, psana2=ev,
               with_data=wdata, per_event='PASS' if pe == 'PASS' else 'FAIL',
               run_id=f'{rec.get("experiment")}/r{rec.get("run") or 0:04d}')


def type_line(r):
    """Item 2's line: type, node, job, run file, the DAQ's count, psana2's, with data, verdicts."""
    return (f'{"PROGRAMS" if r.get("name") == "programs" else "TYPE"} {r["type"]:<12} node {r["node"]} job {r["job"]} run {r.get("run_file")} '
            f'DAQ {r.get("daq")} psana2 {r.get("psana2")} with-data {r.get("with_data")} '
            f'per-event {r.get("per_event", "not run")} {"PASS" if r.get("pass") else "FAIL"}')


# --- one feature ------------------------------------------------------------------------------

def run_feature(args, x, wd, env):
    res = {'feature': x, 'node': socket.gethostname().split('.')[0], 'job': os.environ.get('SLURM_JOB_ID'),
           'workdir': wd, 'started': ds.now(), 'assertions': []}

    def check(what, ok, detail):
        res['assertions'].append({'name': f'features/{x}{what}', 'ok': bool(ok), 'detail': detail})

    why = feature_unavailable(x, getattr(args, 'hosts', None))
    if why:                             # before the lock: nothing starts
        check('', False, f'NOT AVAILABLE: {why}')
        res.update(verdict='NOT AVAILABLE', ended=ds.now(), **{'pass': False})
        print(f'FEATURE {x} NOT AVAILABLE: {why}', flush=True)
        return res
    extra = (['--ami-src', args.ami_src] if x == 'c' and args.ami_src else []) + \
        (['--hosts', args.hosts] if x == 'd' and getattr(args, 'hosts', None) else [])
    fresh(wd)
    out = []
    remote = (None, None)
    if x == 'd' and getattr(args, 'locks', None) and getattr(args, 'hosts', None):
        remote = (args.hosts.split(',')[1], args.locks.split(',')[1])      # d holds B's lock too
    try:
        with Lock(args.lock, args.lock_timeout), RemoteLock(remote[0], remote[1], args.lock_timeout):
            rc, out = run(daq_sim('feature', x, '-w', wd, '-p', str(args.platform), *extra),
                          f'  feature {x}| ', 3600, env)
            rc_d, out_d = run(daq_sim('down', '-w', wd), f'  feature {x} down| ', 300, env)
        clean = rc_d == 0 and any(l.rstrip().endswith('down: clean') for l in out_d)
        check('/down', clean, f'exit {rc_d}' + (', down: clean' if clean else ''))
    except ds.Fail as e:
        check('/lock', False, str(e))
        rc = None
    verdict = next((m.group(1) for m in (re.match(rf'FEATURE {x} (PASS|FAIL|NOT AVAILABLE)\b', l.strip())
                                         for l in out) if m), None)
    problems = [l.strip()[len('problem: '):] for l in out if l.strip().startswith('problem: ')]
    check('', rc == 0 and verdict == 'PASS', f'exit {rc}, FEATURE {x} {verdict}' +
          (': ' + '; '.join(p[:200] for p in problems[:3]) if problems else ''))
    i = next((k for k, l in enumerate(out) if l.startswith(f'---- FEATURE {x} report')), None)
    res.update(verdict=verdict, report=out[i:] if i is not None else out[-20:], ended=ds.now(),
               **{'pass': all(a['ok'] for a in res['assertions'])})
    return res


# --- coverage ---------------------------------------------------------------------------------

def run_coverage(args):
    res = {'started': ds.now()}
    try:
        cov = coverage.check(coverage.find_repo(args.repo), args.status, args.evidence)
    except (coverage.CoverageError, OSError, subprocess.SubprocessError) as e:
        res.update(ended=ds.now(), assertions=[{'name': 'coverage', 'ok': False, 'detail': f'coverage: {e}'}],
                   **{'pass': False})
        return res
    buf = io.StringIO()
    coverage.report(cov, args.verbose, file=buf)
    for line in buf.getvalue().splitlines():
        print(f'  coverage| {line}', flush=True)
    n, c = len(cov['rows']), cov['count']
    counts = (f'{n} rows, {c["RUN"]} run, {c["STAND-IN"]} stand-in, {c["N/A"]} N/A, {c["UNPROVEN"]} unproven, '
              f'{c["INVALID"]} claimed without valid evidence')
    bad = [r['row'] for r in cov['rows'] if not r['ok']]
    detail = f'at {cov["sha"][:9]}: {counts}' + ('' if cov['pass'] else
                                                  f'; failing rows: {" ".join(bad[:8])}' +
                                                  (f' and {len(bad) - 8} more' if len(bad) > 8 else '') +
                                                  (f'; errors: {cov["problems"][:2]}' if cov['problems'] else ''))
    res.update(ended=ds.now(), sha=cov['sha'], rows=n, count=c, failing=bad, problems=cov['problems'],
               assertions=[{'name': 'coverage', 'ok': cov['pass'], 'detail': detail}], **{'pass': cov['pass']})
    return res


# --- the summary ------------------------------------------------------------------------------

def merge(path, sha, brk, now_res):
    """The summary to write: this run's results over the ones the file holds for the same HEAD
    and break (those 'carried')."""
    old = last_record_json(path)
    out = {'sha': sha, 'break': brk, 'types': {}, 'programs': None, 'features': {}, 'coverage': None,
           'runs': []}
    if old and old.get('sha') == sha and old.get('break') == brk:
        for k in ('types', 'features'):
            out[k] = {n: dict(v, carried=True) for n, v in (old.get(k) or {}).items()}
        for k in ('programs', 'coverage'):
            out[k] = dict(old[k], carried=True) if old.get(k) else None
        out['runs'] = old.get('runs', [])
    for k in ('types', 'features'):
        for n, v in now_res[k].items():
            out[k][n] = dict(v, carried=False)
    for k in ('programs', 'coverage'):
        if now_res.get(k) is not None:
            out[k] = dict(now_res[k], carried=False)
    return out


def last_record_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def whole_verdict(summary, all_types, cannot):
    """The verdict over every section at this HEAD, carried results included."""
    missing = [f'types/{t}' for t in all_types if t not in summary['types']]
    missing += [f'features/{x}' for x in FEATURES if x not in summary['features']]
    missing += [k for k in ('programs', 'coverage') if summary.get(k) is None]
    stale = None
    cov = summary['coverage']
    runs = [v for k in ('types', 'features') for v in summary[k].values()] + \
        ([summary['programs']] if summary.get('programs') else [])
    if cov is not None:
        newest = max([v.get('ended') or '' for v in runs] or [''])
        if newest > (cov.get('started') or ''):
            stale = f'coverage ran at {cov.get("started")}, before the run that ended {newest}'
    failed = [a['name'] for v in runs for a in v['assertions'] if not a['ok']]
    failed += [a['name'] for a in (cov or {}).get('assertions', []) if not a['ok']]
    failed += [f'types/{r}/runnable' for r in cannot]
    return {'pass': not missing and not stale and not failed, 'missing': missing, 'stale': stale,
            'failed': failed}


def all_assertions(results):
    """This run's assertions, in section order."""
    out = [a for v in results['types'].values() for a in v['assertions']] + results['extra']
    if results.get('programs') is not None:
        out += results['programs']['assertions']
    out += [a for v in results['features'].values() for a in v['assertions']]
    if results['coverage'] is not None:
        out += results['coverage']['assertions']
    return out


def print_summary(sha, dirty, started, results, summary_path, whole, brk, env_note):
    asserts = all_assertions(results)
    failed = [a for a in asserts if not a['ok']]
    print(f'==== MATRIX SUMMARY at HEAD {sha} (tracked files modified: {dirty}), host '
          f'{socket.gethostname().split(".")[0]}, job {os.environ.get("SLURM_JOB_ID")} step '
          f'{os.environ.get("SLURM_STEP_ID")}, {started} .. {ds.now()}', flush=True)
    if brk:
        print(f'deliberate break: --break {brk} ({env_note})', flush=True)
    if results['types']:
        print(f'types ({len(results["types"])}):', flush=True)
        for r in results['types'].values():
            print(type_line(r), flush=True)
    if results.get('programs') is not None:
        print('programs:', flush=True)
        print(type_line(results['programs']), flush=True)
    if results['features']:
        print('features:', flush=True)
        for x, r in results['features'].items():
            first = next((a['detail'] for a in r['assertions'] if a['name'] == f'features/{x}'), '')
            print(f'FEATURE {x} {r.get("verdict") or "FAIL"}  {first}', flush=True)
    if results['coverage'] is not None:
        print(f'coverage: {results["coverage"]["assertions"][0]["detail"]}', flush=True)
    print(f'assertions: {len(asserts)}, {len(asserts) - len(failed)} passed, {len(failed)} failed', flush=True)
    for a in asserts:
        print(f'  {"PASS" if a["ok"] else "FAIL"} {a["name"]}: {a["detail"]}', flush=True)
    print(f'summary JSON: {summary_path}', flush=True)
    if whole is not None:
        w = whole
        print(f'whole matrix at this HEAD (with carried results): {"PASS" if w["pass"] else "FAIL"}' +
              (f'; not run: {" ".join(w["missing"])}' if w['missing'] else '') +
              (f'; stale: {w["stale"]}' if w['stale'] else '') +
              (f'; failed: {" ".join(w["failed"][:12])}' if w['failed'] else ''), flush=True)
    for a in failed:
        print(f'FAILED {a["name"]}: {a["detail"]}', flush=True)
    verdict = 'PASS' if asserts and not failed else 'FAIL'
    print(f'MATRIX {verdict}' + (f' ({len(failed)} of {len(asserts)} assertions failed)' if failed else
                                 f' ({len(asserts)} assertions)'), flush=True)
    return 0 if verdict == 'PASS' else 1


# --- the command ------------------------------------------------------------------------------

def cmd_matrix(args, argv=()):
    started = ds.now()
    sections = csv(args.only) or list(SECTIONS)
    bad = [s for s in sections if s not in SECTIONS]
    if bad:
        raise ds.Fail(f'--only {",".join(bad)}: not one of {",".join(SECTIONS)}')
    if args.breakage:
        if args.only and sections != ['types']:
            raise ds.Fail('--break runs the types section only')
        sections = ['types']
    repo = coverage.find_repo(args.repo)
    sha, dirty = head(repo)
    wd = os.path.abspath(args.workdir)
    if args.breakage:
        wd = os.path.join(wd, f'break-{args.breakage}')
    if set(sections) & {'types', 'programs', 'features'}:
        ds.ensure_env(list(argv))                # the DAQ env (re-executes through sim_env.sh)
    os.makedirs(wd, exist_ok=True)
    summary_path = os.path.abspath(args.summary or os.path.join(wd, 'matrix-summary.json'))
    print(f'{started} MATRIX: sections {",".join(sections)} at HEAD {sha} (tracked files modified: {dirty}) '
          f'host {socket.gethostname()} job {os.environ.get("SLURM_JOB_ID")} step {os.environ.get("SLURM_STEP_ID")} '
          f'workdir {wd}' + (f' --break {args.breakage}' if args.breakage else ''), flush=True)

    hosts = [h for h in (getattr(args, 'hosts', None) or '').split(',') if h]
    locks = [x for x in (getattr(args, 'locks', None) or '').split(',') if x]
    if locks and len(locks) != len(hosts):
        raise ds.Fail(f'--locks names {len(locks)} lock(s) for {len(hosts)} host(s) of --hosts')
    if locks:
        args.lock = locks[0]                    # this host's
    shard = len(hosts) == 2 and bool(locks) and not args.breakage
    if shard:
        from psdaq.sim import twonode
        if twonode.short(socket.gethostname()) != twonode.short(hosts[0]):
            raise ds.Fail(f'run the matrix on --hosts\'s first host {hosts[0]}')
    env = dict(os.environ)
    for k in (ENV_FAULT, ENV_CORRUPT):          # only a deliberate break sets these
        if env.pop(k, None) is not None:
            say(f'{k} was set in the environment: removed (use --break)')
    all_types, cannot = run_types(repo, args.status)
    all_names = [t for t, _ in all_types]
    gpu_host = getattr(args, 'gpu_host', None) if not args.breakage else None
    gpu_types = []
    if args.drp == 'drp_gpu':                   # this run is the GPU host's (--gpu-host's step)
        all_names, cannot = list(ds.GPU_SIM_TYPES), []
    elif gpu_host:                              # the GPU DRP's types run there; its RUN rows are runnable
        gpu_types = list(ds.GPU_SIM_TYPES)
        cannot = [r for r in cannot if not (r.startswith('det:drp_gpu:') and r.split(':')[2] in ds.GPU_SIM_TYPES)]
        all_names = all_names + [type_key(t, 'drp_gpu') for t in gpu_types]
    known = ds.GPU_SIM_TYPES if args.drp == 'drp_gpu' else ds.SIM_TYPES
    types = csv(args.types) or ([BREAK_TYPES[args.breakage]] if args.breakage else
                                [t for t in all_names if t in known])
    unknown = [t for t in types if t not in known]
    if unknown:
        raise ds.Fail(f'--types {",".join(unknown)}: daq_sim up --drp {args.drp} --det runs {",".join(known)}')
    note = ''
    if args.breakage == 'register':
        if len(types) != 1:
            raise ds.Fail('--break register takes one type')
        fault = args.fault or FAULTS.get(types[0])
        if not fault:
            raise ds.Fail(f'--break register: no register known for {types[0]}; give --fault')
        env[ENV_FAULT] = fault
        note = f'{ENV_FAULT}={fault}'
    elif args.breakage == 'corrupt':
        env[ENV_CORRUPT] = str(max(1, args.events // 2))
        note = f'{ENV_CORRUPT}={env[ENV_CORRUPT]}'
    elif args.breakage == 'kill-drp':
        note = 'daq_sim cycle --kill-drp'
    if note:
        say(f'deliberate break: {note}')

    results = {'types': {}, 'programs': None, 'features': {}, 'coverage': None, 'extra': []}
    if 'types' in sections:
        if not args.breakage and not args.types:
            for r in cannot:
                results['extra'].append({'name': f'types/{r}/runnable', 'ok': False,
                                         'detail': 'RUN in the status file, but daq_sim up --det cannot run it'})
        say(f'types: {" ".join(types)}' + (f'; GPU types on {gpu_host}: {" ".join(gpu_types)}' if gpu_types else ''))
        mine, theirs, rp, gp = types, [], None, None
        if gpu_types and not args.types:        # the GPU host's types, meanwhile, in a step of its job
            job = getattr(args, 'gpu_job', None) or gpu_job(gpu_host)
            if job is None:
                for t in gpu_types:
                    results['types'][type_key(t, 'drp_gpu')] = {
                        'name': f'types/{type_key(t, "drp_gpu")}', 'type': type_key(t, 'drp_gpu'), 'node': gpu_host,
                        'job': None, 'started': ds.now(), 'ended': ds.now(), 'pass': False,
                        'assertions': [{'name': f'types/{type_key(t, "drp_gpu")}/up', 'ok': False,
                                        'detail': f'no running Slurm job of this user on {gpu_host} (--gpu-job)'}]}
            else:
                gp, gsumm = remote_gpu_types(args, gpu_host, job, gpu_types,
                                             os.path.join(wd, 'gpu', gpu_host.split('.')[0]), env)
        if shard and len(types) > 1:            # every other type on the second host, in a step there
            mine, theirs = types[0::2], types[1::2]
            rp, rsumm = remote_types(args, hosts[1], locks[1], theirs,
                                     os.path.join(wd, 'hosts', twonode.short(hosts[1])), env)
        for t in mine:
            say(f'---- type {t} ({types.index(t) + 1} of {len(types)})')
            results['types'][type_key(t, args.drp)] = run_type(args, t, os.path.join(wd, 'types', t), env,
                                                               kill=args.breakage == 'kill-drp', drp=args.drp)
        if rp is not None:
            say(f'waiting for the types on {hosts[1]}')
            try:
                rc_r = rp.wait(len(theirs) * 1800 + 600)
            except subprocess.TimeoutExpired:
                rp.kill()
                rc_r = rp.wait()
            rp.echo.join(10)
            got = (last_record_json(rsumm) or {}).get('types') or {}
            for t in theirs:
                if t in got and not got[t].get('carried'):
                    results['types'][t] = {k: v for k, v in got[t].items() if k != 'carried'}
                else:
                    results['types'][t] = {'name': f'types/{t}', 'type': t, 'node': twonode.short(hosts[1]),
                                           'job': os.environ.get('SLURM_JOB_ID'), 'started': ds.now(), 'ended': ds.now(),
                                           'assertions': [{'name': f'types/{t}/up', 'ok': False,
                                                           'detail': f'the types run on {hosts[1]} (exit {rc_r}) '
                                                                     f'gave no result for {t}'}], 'pass': False}
            say(f'types on {hosts[1]}: exit {rc_r}, {sum(1 for t in theirs if results["types"][t].get("pass"))} '
                f'of {len(theirs)} passed')
        if gp is not None:
            say(f'waiting for the GPU types on {gpu_host}')
            try:
                rc_g = gp.wait(len(gpu_types) * 1800 + 600)
            except subprocess.TimeoutExpired:
                gp.kill()
                rc_g = gp.wait()
            gp.echo.join(10)
            got = (last_record_json(gsumm) or {}).get('types') or {}
            for t in gpu_types:
                k = type_key(t, 'drp_gpu')
                if k in got and not got[k].get('carried'):
                    results['types'][k] = {kk: v for kk, v in got[k].items() if kk != 'carried'}
                else:
                    results['types'][k] = {'name': f'types/{k}', 'type': k, 'node': gpu_host.split('.')[0],
                                           'job': None, 'started': ds.now(), 'ended': ds.now(), 'pass': False,
                                           'assertions': [{'name': f'types/{k}/up', 'ok': False,
                                                           'detail': f'the GPU types run on {gpu_host} (exit {rc_g}) '
                                                                     f'gave no result for {t}'}]}
            say(f'GPU types on {gpu_host}: exit {rc_g}, '
                f'{sum(1 for t in gpu_types if results["types"][type_key(t, "drp_gpu")].get("pass"))} of '
                f'{len(gpu_types)} passed')
        order = [type_key(t, args.drp) for t in types] + [type_key(t, 'drp_gpu') for t in gpu_types]
        results['types'] = {t: results['types'][t] for t in order if t in results['types']}
    if 'programs' in sections:
        say('---- programs')
        results['programs'] = run_programs(args, os.path.join(wd, 'programs'), env)
    if 'features' in sections:
        feats = csv(args.features) or list(FEATURES)
        bad = [x for x in feats if x not in FEATURES]
        if bad:
            raise ds.Fail(f'--features {",".join(bad)}: not one of {",".join(FEATURES)}')
        for x in feats:
            say(f'---- feature {x}')
            results['features'][x] = run_feature(args, x, os.path.join(wd, 'features', x), env)
    if 'coverage' in sections:
        say('---- coverage')
        results['coverage'] = run_coverage(args)

    summary = merge(summary_path, sha, args.breakage, results)
    whole = None if args.breakage else whole_verdict(summary, all_names, cannot)
    run_info = {'started': started, 'ended': ds.now(), 'host': socket.gethostname(), 'hosts': hosts or None,
                'gpu_host': getattr(args, 'gpu_host', None),
                'job': os.environ.get('SLURM_JOB_ID'), 'step': os.environ.get('SLURM_STEP_ID'),
                'argv': list(argv), 'sections': sections, 'types': list(results['types']),
                'programs': results['programs'] is not None,
                'features': list(results['features']), 'break': args.breakage, 'break_env': note or None}
    rc = print_summary(sha, dirty, started, results, summary_path, whole, args.breakage, note)
    run_info['exit'] = rc
    summary['runs'] = summary['runs'][-19:] + [run_info]
    summary.update(dirty=dirty, updated=ds.now(), whole=whole, exit=rc, assertions=all_assertions(results))
    tmp = summary_path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(summary, f, indent=1)
    os.replace(tmp, summary_path)
    return rc


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    return ds.main(['matrix'] + list(argv))


if __name__ == '__main__':
    sys.exit(main())
