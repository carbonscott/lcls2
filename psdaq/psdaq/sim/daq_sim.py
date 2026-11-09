"""daq_sim: bring up, check, drive and take down the hardware-free lcls2 DAQ on one node.

    daq_sim up     [-w WORKDIR] [-p PLATFORM] [--rate HZ] [--seed N] [--length WORDS] [--segments N]
                   [--det TYPE] [--webgui] [--detach]
    daq_sim status [-w WORKDIR]
    daq_sim cycle  [-w WORKDIR] [--events N] [--no-record]
    daq_sim e2e    [-w WORKDIR] [--events N] [--edit-seed N [--expect-seed M]]
                   [--break kill-drp|truncate-xtc2] [--browser-python PATH] [--keep-up]
    daq_sim down   [-w WORKDIR]
    daq_sim coverage [--repo DIR] [--status FILE] [--evidence DIR] [-v] [--json]
    daq_sim matrix   [the coverage options]

'up' starts, in this order and all on this node:
  1. the isolation env (sim_env.sh, sourced by re-executing through bash) and the fail-closed
     preflight (preflight.sh); 'up' stops if the preflight does not pass,
  2. the config DB stand-in (configdb_server), seeded by configdb_seed,
  3. the run DB / eLog stand-in (lgbk_server),
  4. simxpm, the software XPM (PVA server + timing frames + control.py -X receiver), and the
     stand-ins of the --det type's own device, if it has any (hsd: simhsdioc, the hsd's PVs and
     IOC),
  5. procmgr with a generated .cnf: control in normal mode, teb0, and drp -D fakecam -d sim://
     (with --segments N: N such DRPs, fakecam_0 .. fakecam_<N-1>, segments of one detector, each
     with its config in the config DB, all in the partition's readout group; with --det TYPE
     another type of SIM_TYPES instead of fakecam: a BEB type's own <type>_config.py configures
     a device psdaq.sim.rogue_dev emulates, from the type's own config in the config DB; every
     XpmDetector type, fakecam included, runs xpmdet_config against an emulated TDet receiver),
  6. with --webgui, the web GUI (daq_webgui) on 127.0.0.1:<block +3>: the real DaqControl
     backend against this platform's control, and the events counter read from simxpm's
     NumL0Acc PV over PV Access.
It prints every endpoint and stays in the foreground until Ctrl-C or SIGTERM, then takes
everything down: a Slurm step kills its processes when the step's main process exits, so the
foreground process is what keeps the DAQ alive.  '--detach' returns once everything is up
instead, for a script that keeps its own step alive and calls 'daq_sim down' itself.
'down' stops only what 'up' started: the procmgr processes, the PIDs 'up' recorded, and any
process of this user whose environment carries this work dir's DAQ_SIM_WORKDIR tag (e.g. the
caRepeater that libca spawns); then it checks that the ports are free.
'cycle' drives one run with the same client the GUIs use (psdaq.control.DaqControl), one
state at a time, reads every state back, waits for --events L1Accepts and goes back to the
state it started from.  It exits nonzero on any failure.  A passing recorded cycle writes an
evidence record (psdaq.sim.coverage.record_evidence) for the rows it proves: the programs
of the generated .cnf, its drp's -D type and the stand-ins 'up' started; the record lists the
run's xtc2 files and every process's log with their sizes and sha256, and the cycle prints
what 'daq_sim coverage' would reject in it.
'coverage' checks that every row (detector type, program a procmgr config starts) is RUN,
STAND-IN or N/A, each RUN/STAND-IN row with evidence recorded at HEAD (psdaq.sim.coverage).
'matrix' runs the whole hardware-free matrix; for now it only runs the coverage check.
'e2e' is the end-to-end test: the same run driven through the web GUI by a headless browser
(psdaq.webgui.e2e); it brings the DAQ up with --webgui unless it is up already, checks
every state and count itself, prints E2E PASS or E2E FAIL and the exit code says which.

Ports for platform p (block 31000 + 10 p; p = 5 gives 31050-31059):
  +0 config DB stand-in   +1 run DB stand-in   +2 simxpm frames   +3 web GUI (up --webgui)
Ports the DAQ fixes itself: control ZMQ 29980 + p + 0,10,...,60; procServ 29000 + 100 p + 2..;
control -X / simxpm PULL 29980 + 70 + xpm; Prometheus exporters 9200-9299 (with -M);
EPICS (sim_env.sh) PVA 15075/15076, CA 15064/15065.
"""

import argparse
import datetime
import getpass
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time

from psdaq.sim import coverage

SIMDIR = os.path.dirname(os.path.abspath(__file__))
SIM_ENV = os.path.join(SIMDIR, 'sim_env.sh')
PREFLIGHT = os.path.join(SIMDIR, 'preflight.sh')
RCFILE = os.path.join(SIMDIR, 'procmgrd.s3df.conf')

INSTRUMENT = 'tst'
EXPERIMENT = 'tstx00001'
CONFIG_ALIAS = 'BEAM'
TRIGGER = 'tmoteb'
DETECTOR = 'fakecam'
PVBASE = 'DAQ:SIM'
XPM = 0
EP = 'ep_domain=lo,ep_provider=tcp'     # libfabric tcp on loopback (Collection.cc getNicIp)
PROCS = ('control', 'teb0', DETECTOR + '_0')     # with --segments N: + DETECTOR_1 .. DETECTOR_<N-1> (procs())
# drp -k settings per simulated detector type (up --det).  BEB types (psdaq.sim.rogue_dev) get
# EventBatcher-framed buffers sized for their frame (psdaq/drp/MemPoolSim.cc) and their config
# from the type's own store; 'det_yaml' is the firmware YAML a production config is made from.
SIM_TYPES = {
    'fakecam': {'kwargs': 'sim_length={length}'},
    'epix100': {'kwargs': 'sim_dma_size=0x110000,sim_dma_count=256,sim_seed={seed:#x}',
                'det_yaml': '{SUBMODULEDIR}/epix-100a-gen2/software/yml/ePix100a_asics_0123.yml'},
    # wave8 is configured through its front-end's IOC; rogue_dev serves its PVs in process
    'wave8':   {'kwargs': 'sim_dma_size=0x2000,sim_dma_count=1024,sim_seed={seed:#x},'
                          'epics_prefix=SIM:W8:00'},
    'wave8he': {'kwargs': 'sim_dma_size=0x2000,sim_dma_count=1024,sim_seed={seed:#x},'
                          'epics_prefix=SIM:W8HE:00'},
    'hrencoder': {'kwargs': 'sim_dma_size=0x1000,sim_dma_count=1024,sim_seed={seed:#x}'},
    'epixm320':  {'kwargs': 'sim_dma_size=0xa0000,sim_dma_count=256,sim_seed={seed:#x}'},
    # camera link cameras: the camera answers its serial commands from the seed file (rogue_dev)
    'opal':      {'kwargs': 'sim_dma_size=0x201000,sim_dma_count=128,sim_seed={seed:#x}'},
    'piranha4':  {'kwargs': 'sim_dma_size=0x2000,sim_dma_count=1024,sim_seed={seed:#x}'},
    # the timing BEB: tb_config reads the card's image name, then programs simxpm's PVs as ts does
    'tb':        {'kwargs': 'sim_dma_size=0x1000,sim_dma_count=1024,sim_seed={seed:#x}'},
    'epixquad':  {'kwargs': 'sim_dma_size=0x110000,sim_dma_count=256,sim_seed={seed:#x}'},
    # the same EpixQuad DRP; its camera's SPI PROM answers the commands Top.start sends (rogue_dev).
    # Its package's ePixViewer constructs a QApplication when ePixQuad is imported, so whatever
    # imports epixquad1kfps_config (configdb_seed, the DRP) needs a display: offscreen here
    'epixquad1kfps': {'kwargs': 'sim_dma_size=0x110000,sim_dma_count=256,sim_seed={seed:#x}',
                      'env': {'QT_QPA_PLATFORM': 'offscreen'}},
    # its store's default reads PLL tables and pixel maps from EPIXUHR_CONFIG_DIR: 'up' writes them
    # (psdaq.sim.epixuhr_files); 4 ASICs of 48,384 B packed pixels per event
    'epixUHR':   {'kwargs': 'sim_dma_size=0x40000,sim_dma_count=256,sim_seed={seed:#x}',
                  'config_files': ('psdaq.sim.epixuhr_files', 'epixuhr', 'EPIXUHR_CONFIG_DIR')},
    # XpmDetector types: xpmdet_config programs an emulated TDet timing receiver (rogue_dev,
    # seeds/xpmdet.json), as for fakecam.  epixhremu replays the frame of an xtc2 file that 'up'
    # writes from the seed (psdaq.sim.epixhremu_frame), 221,184 B per event, so its DMA (and so
    # pebble) buffers are 256 kB; jungfrauemu records the DMA payload as one 512 x 1024 panel;
    # ts records the timing message (MemPoolSim.cc) and its ts_config programs simxpm's PVs.
    'cspad':       {'kwargs': 'sim_length={length}'},
    'epixhremu':   {'kwargs': 'sim_length={length},sim_dma_size=0x40000,sim_dma_count=1024,'
                              'xtcfile={work}/epixhremu-frame.xtc2',
                    'frame': 'epixhremu-frame.xtc2'},
    'jungfrauemu': {'kwargs': 'sim_length=262144,sim_dma_size=0x101000,sim_dma_count=256'},
    'ts':          {'kwargs': 'sim_seed={seed:#x}'},
    # the digitizer: hsd_config.py configures the card (rogue_dev) and, over PVA, the hsd's IOC,
    # whose PVs simhsdioc serves for channels A and B (hsd_config disables both); MemPoolSim sends
    # the hsd's raw and fex streams
    'hsd': {'kwargs': f'hsd_epics_prefix={PVBASE}:HSD:1_SIM:A,sim_seed={{seed:#x}}',
            'services': {'simhsdioc': ['-m', 'psdaq.sim.simhsdioc',
                                       '-P', f'{PVBASE}:HSD:1_SIM:A', f'{PVBASE}:HSD:1_SIM:B']}},
}


def use_det(det):
    """Select the simulated detector type for this invocation (up stores it in the state)."""
    global DETECTOR, PROCS
    if det not in SIM_TYPES:
        raise Fail(f'unknown simulated detector {det!r}; one of {sorted(SIM_TYPES)}')
    DETECTOR = det
    PROCS = ('control', 'teb0', DETECTOR + '_0')
STATES = ['reset', 'unallocated', 'allocated', 'connected', 'configured', 'starting',
          'paused', 'running']
TAG = 'DAQ_SIM_WORKDIR'                 # Environment tag of every process 'up' starts


def ports(platform):
    base = 31000 + 10 * platform
    return {'configdb': base, 'lgbk': base + 1, 'frames': base + 2, 'webgui': base + 3}


def control_ports(platform):
    return [29980 + platform + 10 * k for k in range(7)]


def pull_port(xpm=XPM):
    return 29980 + 70 + xpm             # ControlDef.xpm_pull_port for <pvbase>:XPM:<xpm>


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec='milliseconds')


def say(*args):
    print(f'{now()} daq_sim:', *args, flush=True)


class Fail(Exception):
    pass


# --- environment ---------------------------------------------------------------------------

def ensure_env(argv):
    """Re-execute through bash with sim_env.sh sourced, unless it already is."""
    if os.environ.get('SIM_ENV_SOURCED') == '1':
        return
    if not shutil.which('procmgr') or not shutil.which('drp'):
        sys.exit('daq_sim: the DAQ env is not set up: source setup_env_daq.sh from the lcls2 '
                 'checkout (its install/bin must hold procmgr, control, teb, drp)')
    cmd = ['bash', '-c', 'source "$0" && exec "$@"', SIM_ENV,
           sys.executable, '-m', 'psdaq.sim.daq_sim'] + argv
    os.execvp('bash', cmd)


def check_host(any_host):
    host = socket.gethostname()
    short = host.split('.')[0]
    if re.match(r'(drp|daq|mon|ctl|ioc)-', short) or re.search(r'-(daq|drp|mon|control)\b', short):
        raise Fail(f'refusing to run on {host}: it looks like a hutch or DAQ host')
    if re.match(r'(sdfiana|sdflogin|s3dflogin|sdfdtn)', short) and not any_host:
        raise Fail(f'refusing to run on {host}, an interactive node: run inside a Slurm step '
                   '(srun --jobid=<job> ...), or pass --any-host to mean it')
    return host


def port_busy(port):
    """True if something listens on TCP port (any address)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(('0.0.0.0', port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def wait_listen(port, timeout, proc=None, what=''):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if proc is not None and proc.poll() is not None:
            raise Fail(f'{what} exited with code {proc.returncode} before listening on {port}')
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=1):
                return
        except OSError:
            time.sleep(0.2)
    raise Fail(f'{what} not listening on 127.0.0.1:{port} after {timeout} s')


def pid_alive(pid):
    """True if pid runs; a zombie (exited, not yet reaped by its parent 'up') counts as gone."""
    try:
        with open(f'/proc/{pid}/stat') as f:
            return f.read().rsplit(')', 1)[1].split()[0] != 'Z'
    except (OSError, IndexError):
        return False


def tagged_pids(workdir):
    """PIDs of this user's processes whose environment carries this work dir's tag."""
    me, tag, out = os.getuid(), f'{TAG}={workdir}'.encode() + b'\0', []
    for d in os.listdir('/proc'):
        if not d.isdigit() or int(d) == os.getpid():
            continue
        try:
            if os.stat(f'/proc/{d}').st_uid != me:
                continue
            with open(f'/proc/{d}/environ', 'rb') as f:
                if tag in f.read():
                    out.append(int(d))
        except OSError:
            continue
    return out


def cmdline(pid):
    try:
        with open(f'/proc/{pid}/cmdline', 'rb') as f:
            return f.read().replace(b'\0', b' ').decode(errors='replace').strip()
    except OSError:
        return ''


# --- state file ----------------------------------------------------------------------------

class Work:
    def __init__(self, workdir):
        self.dir = os.path.abspath(workdir)
        self.state_path = os.path.join(self.dir, 'daq_sim.state.json')

    def path(self, *parts):
        return os.path.join(self.dir, *parts)

    def load(self):
        try:
            with open(self.state_path) as f:
                return json.load(f)
        except FileNotFoundError:
            return None

    def save(self, state):
        tmp = self.state_path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, self.state_path)


def procmgr_cmd(state, verb):
    return ['procmgr', verb, state['cnf'], '-p', str(state['platform']), '-r', RCFILE,
            '-o', state['loglink']]


def procs(state):
    """procmgr ids 'up' starts: PROCS plus the extra detector segments of --segments."""
    return PROCS + tuple(f'{DETECTOR}_{i}' for i in range(1, state.get('segments', 1)))


def procmgr_status(state):
    """{id: (status, pid)} from 'procmgr status'."""
    r = subprocess.run(procmgr_cmd(state, 'status'), cwd=state['workdir'], capture_output=True,
                       text=True, timeout=60)
    out = {}
    for line in r.stdout.splitlines():
        f = line.split()
        if len(f) >= 4 and f[1] in procs(state):
            out[f[1]] = (f[2], f[3])
    return out, r.stdout


# --- up ------------------------------------------------------------------------------------

CNF = '''# Generated by daq_sim up at {when}; regenerated by every 'daq_sim up'.
# Hardware-free DAQ, all on this node: control (normal mode) + teb0 + {det}_0 (drp -d sim://).
if not platform: platform = '{platform}'
procmgr_config = [
 {{ id:'control', flags:'spu',
   cmd:'control -v -C {alias} -P {instr} -x {xpm} -B {pvbase} -X 127.0.0.1 -t {trigger} -S {slow}'
       ' -d {configdb} --url {lgbk} -r {activedet} -V /dev/null' }},
 {{ id:'teb0', flags:'spu',
   cmd:'teb{v} -P {instr} -C localhost -k {ep} -M {prom}' }},
 {{ id:'{det}_0', flags:'spu',
   cmd:'drp{v} -P {instr} -C localhost -D {det} -d sim://127.0.0.1:{frames} -l 0x1 -o {data}'
       ' -k {ep},{simk} -M {prom}' }},
{segments}]
'''
SEGMENT = ''' {{ id:'{det}_{segm}', flags:'spu',
   cmd:'drp{v} -P {instr} -C localhost -D {det} -d sim://127.0.0.1:{frames} -l 0x1 -o {data}'
       ' -k {ep},{simk} -M {prom}' }},
'''


def write_activedet(path, platform, segments=1):
    """What control writes after an alloc of this partition, so its first rollcall finds it."""
    dets = [f'{DETECTOR}_{i}' for i in range(segments)]
    value = {'activedet': {'drp': {d: {'active': 1, 'det_info': {'readout': platform}} for d in dets},
                           'teb': {'teb0': {'active': 1}}},
             'history': {'drp': {d: {'det_info': {'readout': platform}} for d in dets}}}
    with open(path, 'w') as f:
        json.dump(value, f, indent=4, sort_keys=True)


def log_header(argv):
    """The first line of a service's log: its command, as procmgr heads each process's log
    ('# CMDLINE: ...'); coverage reads it to tell which program the log is of."""
    return f'# CMDLINE: {" ".join(shlex.quote(a) for a in argv)}\n'


def start_service(work, state, name, argv, env):
    log = work.path('logs', name + '.log')
    with open(log, 'ab') as out:
        out.write(log_header(argv).encode())
        out.flush()
        p = subprocess.Popen(argv, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             env=env, cwd=work.dir, start_new_session=True)
    state['services'][name] = {'pid': p.pid, 'cmd': ' '.join(shlex.quote(a) for a in argv), 'log': log}
    work.save(state)
    return p


def cmd_up(args):
    host = check_host(args.any_host)
    segments = getattr(args, 'segments', 1)
    work = Work(args.workdir)
    os.makedirs(work.dir, exist_ok=True)
    old = work.load()
    if old and any(pid_alive(s['pid']) for s in old.get('services', {}).values()):
        raise Fail(f'already up in {work.dir} (run daq_sim down -w {work.dir} first)')
    if tagged_pids(work.dir):
        raise Fail(f'processes tagged with {work.dir} still run: {tagged_pids(work.dir)}; '
                   f'run daq_sim down -w {work.dir}')
    P = ports(args.platform)
    want = [P['configdb'], P['lgbk'], P['frames'], pull_port()] + control_ports(args.platform)
    if getattr(args, 'webgui', False):
        want.append(P['webgui'])
    busy = [p for p in want if port_busy(p)]
    if busy:
        raise Fail(f'ports already in use: {busy}')
    for d in ('logs', 'pmlogs', 'prom', os.path.join('data', INSTRUMENT)):
        os.makedirs(work.path(d), exist_ok=True)   # drp mkdirs data/<instr>/<expt>/xtc, not data/<instr>

    # procmgr's -o allows at most 50 characters
    loglink = work.path('pmlogs')
    if len(loglink) > 50:
        loglink = f'/tmp/daq_sim.{getpass.getuser()}.p{args.platform}'
        if os.path.islink(loglink):
            os.unlink(loglink)
        os.symlink(work.path('pmlogs'), loglink)

    env = dict(os.environ)
    env[TAG] = work.dir
    env['PYTHONUNBUFFERED'] = '1'
    os.environ[TAG] = work.dir          # procmgr and everything it starts inherit it

    state = {'workdir': work.dir, 'host': host, 'platform': args.platform, 'up_pid': os.getpid(),
             'slurm': {k: os.environ.get(k) for k in ('SLURM_JOB_ID', 'SLURM_STEP_ID')},
             'started': now(), 'ports': P, 'services': {}, 'loglink': loglink,
             'cnf': 'daq_sim.cnf', 'rate': args.rate, 'seed': args.seed, 'length': args.length,
             'segments': segments, 'det': DETECTOR}
    work.save(state)
    say(f'up on {host} (job {os.environ.get("SLURM_JOB_ID")} step {os.environ.get("SLURM_STEP_ID")}), '
        f'platform {args.platform}, workdir {work.dir}')

    try:
        if not args.skip_preflight:
            say('preflight (fail-closed isolation check) ...')
            with open(work.path('logs', 'preflight.log'), 'w') as out:
                rc = subprocess.run(['bash', PREFLIGHT], stdout=out, stderr=subprocess.STDOUT,
                                    env=env, timeout=240).returncode
            last = open(work.path('logs', 'preflight.log')).read().strip().splitlines()[-1:]
            say(f'preflight rc={rc}: {last[0] if last else ""}  (logs/preflight.log)')
            if rc != 0:
                raise Fail('preflight failed: not starting anything')

        py = sys.executable
        cfg_url = f'http://127.0.0.1:{P["configdb"]}/ws/'
        p = start_service(work, state, 'configdb',
                          [py, '-m', 'psdaq.sim.configdb_server', '--store', work.path('configdb.json'),
                           '--port', str(P['configdb']),
                           '--access-log', work.path('logs', 'configdb-access.jsonl')], env)
        wait_listen(P['configdb'], 30, p, 'configdb_server')
        sim_type = SIM_TYPES[DETECTOR]
        env.update(sim_type.get('env', {}))     # what the type's own code needs to run here
        os.environ.update(sim_type.get('env', {}))  # procmgr and the DRP inherit it
        if sim_type.get('config_files'):    # files the type's store reads, at a path env names
            mod, sub, var = sim_type['config_files']
            r = subprocess.run([py, '-m', mod, work.path(sub)], env=env, capture_output=True,
                               text=True, timeout=120)
            if r.returncode != 0:
                raise Fail(f'{mod} failed: {r.stderr.strip()[-400:]}')
            env[var] = work.path(sub)
            say(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else f'{var}={env[var]}')
        det_args = ['--det-type', DETECTOR] if DETECTOR != 'fakecam' else []
        if sim_type.get('det_yaml'):
            det_args += ['--det-yaml', sim_type['det_yaml'].format(**os.environ)]
        for segm in range(segments):
            r = subprocess.run([py, '-m', 'psdaq.sim.configdb_seed', '--url', cfg_url,
                                '--inst', INSTRUMENT, '--alias', CONFIG_ALIAS, '--trigger', TRIGGER,
                                '--det', DETECTOR, '--segm', str(segm), '--sim-seed', str(args.seed),
                                '--sim-length', str(args.length)] + det_args,
                               env=env, capture_output=True, text=True, timeout=60)
            with open(work.path('logs', 'seed.log'), 'a' if segm else 'w') as out:
                out.write(r.stdout + r.stderr)
            if r.returncode != 0:
                raise Fail(f'configdb_seed failed: {r.stderr.strip()[-400:]}')
            for line in r.stdout.splitlines():
                say('config DB seeded:', line)

        p = start_service(work, state, 'lgbk',
                          [py, '-m', 'psdaq.sim.lgbk_server', '--instrument', INSTRUMENT,
                           '--experiment', EXPERIMENT, '--state', work.path('lgbk.json'),
                           '--log', work.path('logs', 'lgbk.jsonl'), '--port', str(P['lgbk'])], env)
        wait_listen(P['lgbk'], 30, p, 'lgbk_server')

        p = start_service(work, state, 'simxpm',
                          [py, '-m', 'psdaq.sim.simxpm', '-P', PVBASE, '-x', str(XPM),
                           '--frames', f'tcp://127.0.0.1:{P["frames"]}', '--rate', str(args.rate),
                           '--pull', 'auto'], env)
        wait_listen(P['frames'], 30, p, 'simxpm frames')
        wait_listen(pull_port(), 30, p, 'simxpm pull')

        for name, argv in sim_type.get('services', {}).items():     # the type's device stand-ins
            p = start_service(work, state, name, [py] + argv, env)
            state.setdefault('type_services', []).append(name)
            work.save(state)
            end = time.monotonic() + 30
            while f'{name}: ready' not in open(state['services'][name]['log']).read():
                if p.poll() is not None or time.monotonic() > end:
                    raise Fail(f'{name} did not start (logs/{name}.log)')
                time.sleep(0.2)
            say(f'{name} ready (logs/{name}.log)')

        if sim_type.get('frame'):       # the frame an emulator type replays, from the seed
            r = subprocess.run([py, '-m', 'psdaq.sim.%s_frame' % DETECTOR, work.path(sim_type['frame']),
                                '--seed', str(args.seed)], env=env, capture_output=True, text=True,
                               timeout=120)
            with open(work.path('logs', 'frame.log'), 'w') as out:
                out.write(r.stdout + r.stderr)
            if r.returncode != 0:
                raise Fail(f'{DETECTOR}_frame failed: {r.stderr.strip()[-400:]}')
            say(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else f'{DETECTOR} frame written')

        write_activedet(work.path('activedet.json'), args.platform, segments)
        common = dict(instr=INSTRUMENT, ep=EP, prom=work.path('prom'), det=DETECTOR, frames=P['frames'],
                      data=work.path('data'), length=args.length, v=' -v' if args.verbose else '',
                      simk=SIM_TYPES[DETECTOR]['kwargs'].format(length=args.length, seed=args.seed,
                                                                work=work.dir))
        with open(work.path(state['cnf']), 'w') as f:
            f.write(CNF.format(when=now(), platform=args.platform, alias=CONFIG_ALIAS,
                               xpm=XPM, pvbase=PVBASE, trigger=TRIGGER,
                               slow=args.slow_update, configdb=cfg_url + 'configDB',
                               lgbk=f'http://127.0.0.1:{P["lgbk"]}/', activedet=work.path('activedet.json'),
                               segments=''.join(SEGMENT.format(segm=i, **common)
                                                for i in range(1, segments)), **common))
        say('procmgr start', state['cnf'])
        with open(work.path('logs', 'procmgr.log'), 'a') as out:
            rc = subprocess.run(procmgr_cmd(state, 'start') + ['-v'], cwd=work.dir, stdout=out,
                                stderr=subprocess.STDOUT, timeout=120).returncode
        state['procmgr_started'] = True
        work.save(state)
        if rc != 0:
            raise Fail(f'procmgr start exited {rc} (logs/procmgr.log)')
        status = _wait_running(state, 40)
        time.sleep(3)                   # A process that dies at startup does so quickly
        status, text = procmgr_status(state)
        bad = [i for i in procs(state) if status.get(i, ('?',))[0] != 'RUNNING']
        if bad:
            raise Fail(f'not RUNNING after start: {bad}\n{text}')
        state['procs'] = {i: int(status[i][1]) for i in procs(state)}
        work.save(state)
        dstate = _control_state(args.platform)
        if dstate != 'reset':
            raise Fail(f'control answers state {dstate!r}, expected reset')
        if getattr(args, 'webgui', False):
            start_webgui(work, state, env)
    except BaseException as e:
        say(f'up FAILED: {e}')
        teardown(work, quiet=False)
        if isinstance(e, Fail):
            return 1
        raise

    endpoints = _endpoints(state)
    with open(work.path('endpoints.json'), 'w') as f:
        json.dump(endpoints, f, indent=2)
    say('UP. Endpoints (also in endpoints.json):')
    for k, v in endpoints.items():
        print(f'  {k:<12} {v}', flush=True)

    if args.detach:
        return 0
    say('staying in the foreground; Ctrl-C or SIGTERM (or daq_sim down) takes everything down')
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *a: stop.set())
    reported = set()
    while not stop.wait(2):
        st = work.load()
        if st is None or st.get('down') == 'done':
            say('daq_sim down ran elsewhere; exiting')
            return 0
        if st.get('down'):              # Let 'down' finish: this step's end would kill all
            continue
        for name, svc in st['services'].items():
            if not pid_alive(svc['pid']) and name not in reported:
                reported.add(name)
                say(f'WARNING: {name} (pid {svc["pid"]}) has exited; see {svc["log"]}')
    st = work.load()
    if st is not None and st.get('down') == 'done':
        say('daq_sim down already took everything down; exiting')
        return 0 if st.get('down_clean') else 1
    say('signal received: taking everything down')
    return 0 if teardown(work) else 1


def webgui_url(state):
    return f'http://127.0.0.1:{state["ports"]["webgui"]}/'


def count_pv(platform, label='NumL0Acc'):
    """simxpm's partition counter, named as pyxpm names it: <pvbase>:XPM:<xpm>:PART:<group>:<label>."""
    return f'{PVBASE}:XPM:{XPM}:PART:{platform}:{label}'


def start_webgui(work, state, env):
    """The web GUI on 127.0.0.1:<block +3>: real DaqControl backend, events = simxpm NumL0Acc (PVA)."""
    P = state['ports']
    argv = [sys.executable, '-m', 'psdaq.webgui.server', '--bind', '127.0.0.1', '--port', str(P['webgui']),
            '-p', str(state['platform']), '-H', '127.0.0.1',
            '--configdb-url', f'http://127.0.0.1:{P["configdb"]}/ws/', '--configdb-root', 'configDB',
            '--events-source', 'pva', '--events-pv', count_pv(state['platform'])]
    say('web GUI:', ' '.join(argv[1:]))
    p = start_service(work, state, 'webgui', argv, env)
    wait_listen(P['webgui'], 60, p, 'daq_webgui')
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    end = time.monotonic() + 30
    while True:                         # The page and the API answer, and the server reached control
        try:
            st = json.loads(opener.open(webgui_url(state) + 'api/status', timeout=5).read())
            if st.get('state'):
                break
        except (OSError, ValueError):
            pass
        if time.monotonic() > end or p.poll() is not None:
            raise Fail('daq_webgui does not answer /api/status (logs/webgui.log)')
        time.sleep(0.5)
    say(f'web GUI up: {webgui_url(state)} (pid {p.pid}) control state {st.get("state")}')
    return p


def _wait_running(state, timeout):
    end = time.monotonic() + timeout
    while True:
        status, text = procmgr_status(state)
        if all(status.get(i, ('?',))[0] == 'RUNNING' for i in procs(state)) or time.monotonic() > end:
            return status
        time.sleep(1)


def _control_state(platform, timeout=5000):
    from psdaq.control.DaqControl import DaqControl
    dc = DaqControl(host='localhost', platform=platform, timeout=timeout)
    try:
        return dc.getState()
    finally:
        dc.context.destroy(0)


def _endpoints(state):
    P, p = state['ports'], state['platform']
    cp = control_ports(p)
    return {
        'host': f'{state["host"]} (Slurm job {state["slurm"]["SLURM_JOB_ID"]})',
        'control': f'platform {p} on localhost: ZMQ ports {cp[0]}-{cp[-1]} '
                   f'(front_rep {cp[2]}, front_pub {cp[3]}); daqstate -p {p} -P {INSTRUMENT} -C localhost',
        'configdb': f'http://127.0.0.1:{P["configdb"]}/ws/configDB  ({INSTRUMENT}/{CONFIG_ALIAS}: '
                    f'{TRIGGER}_0, {DETECTOR}_0 sim_seed={state["seed"]:#x})',
        'rundb': f'http://127.0.0.1:{P["lgbk"]}/  (experiment {EXPERIMENT}; log logs/lgbk.jsonl)',
        'simxpm': f'PVs {PVBASE}:XPM:{XPM}:* on PVA 127.0.0.1:{os.environ.get("EPICS_PVA_SERVER_PORT", "5075")}, '
                  f'frames tcp://127.0.0.1:{P["frames"]}, control -X tcp://127.0.0.1:{pull_port()}, '
                  f'{state["rate"]:g} Hz; count: pvget {PVBASE}:XPM:{XPM}:PART:{p}:NumL0Acc',
        'procmgr': f'{state["workdir"]}/{state["cnf"]}  pids {state.get("procs")}  logs {state["workdir"]}/pmlogs',
        'data': f'{state["workdir"]}/data  (xtc2 written when recording)',
        'prometheus': f'{state["workdir"]}/prom/*.yaml  (exporters on 0.0.0.0:9200-9299)',
        'webgui': (f'{webgui_url(state)}  (pid {state["services"]["webgui"]["pid"]}; from your machine: '
                   f'ssh -L {P["webgui"]}:127.0.0.1:{P["webgui"]} <node>, via the login host)'
                   if 'webgui' in state['services'] else f'port {P["webgui"]} (not started: up --webgui)'),
        'drive': f'daq_sim cycle -w {state["workdir"]} --events 1000   or   daq_sim e2e -w {state["workdir"]}',
        'stop': f'Ctrl-C the up process, or daq_sim down -w {state["workdir"]}',
    }


# --- down ----------------------------------------------------------------------------------

def _kill(pid, what, quiet):
    if not pid_alive(pid):
        return
    if not quiet:
        say(f'stopping {what} pid {pid}: {cmdline(pid)[:120]}')
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(50):
        if not pid_alive(pid):
            return
        time.sleep(0.1)
    say(f'{what} pid {pid} ignored SIGTERM: SIGKILL')
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def teardown(work, quiet=False):
    """Stop everything 'up' started in work.dir; return True if all is gone and ports are free."""
    state = work.load()
    if state is None:
        say(f'nothing recorded in {work.dir}')
        state = {'services': {}, 'platform': None}
    state['down'] = 'in progress'
    if 'workdir' in state:
        work.save(state)
    svc = state['services'].get('webgui')   # First: it holds DaqControl sockets to control
    if svc:
        _kill(svc['pid'], 'webgui', quiet)
    if state.get('procmgr_started'):
        say('procmgr stop', state['cnf'])
        with open(work.path('logs', 'procmgr.log'), 'a') as out:
            subprocess.run(procmgr_cmd(state, 'stop') + ['-v'], cwd=work.dir, stdout=out,
                           stderr=subprocess.STDOUT, timeout=120)
    for name in ('simxpm', 'lgbk', 'configdb') + tuple(state.get('type_services', ())):
        svc = state['services'].get(name)
        if svc:
            _kill(svc['pid'], name, quiet)
    for pid in tagged_pids(work.dir):
        if pid != state.get('up_pid'):
            _kill(pid, 'leftover (tagged)', False)
    time.sleep(0.5)
    left = [(pid, cmdline(pid)) for pid in tagged_pids(work.dir) if pid != state.get('up_pid')]
    ok = not left
    if left:
        say(f'LEFTOVER processes: {left}')
    if state.get('platform') is not None:
        P = state['ports']
        check = [P['configdb'], P['lgbk'], P['frames'], pull_port()] + control_ports(state['platform'])
        if 'webgui' in state['services']:
            check.append(P['webgui'])
        busy = [p for p in check if port_busy(p)]
        if busy:
            ok = False
            say(f'ports still in use: {busy}')
        else:
            say(f'ports free: {check}')
    if 'workdir' in state:
        state['down'] = 'done'
        state['down_clean'] = ok
        work.save(state)
    say('down: ' + ('clean' if ok else 'NOT clean'))
    return ok


def cmd_down(args):
    work = Work(args.workdir)
    state = work.load() or {}
    ok = teardown(work)
    up = state.get('up_pid')
    if up and pid_alive(up) and 'daq_sim' in cmdline(up):
        os.kill(up, signal.SIGTERM)     # Its own teardown then finds nothing left to do
    return 0 if ok else 1


# --- status --------------------------------------------------------------------------------

def prometheus_targets(promdir):
    out = []
    for name in sorted(os.listdir(promdir)) if os.path.isdir(promdir) else []:
        if name.endswith('.yaml'):
            m = re.search(r":(\d+)'", open(os.path.join(promdir, name)).read())
            if m:
                out.append(int(m.group(1)))
    return out


def scrape(port, names):
    """{metric{labels}: value} for metric names in 'names', from 127.0.0.1:port."""
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    out = {}
    try:
        text = opener.open(f'http://127.0.0.1:{port}/metrics', timeout=3).read().decode()
    except OSError:
        return out
    for line in text.splitlines():
        m = re.match(r'([A-Za-z_]+)(\{[^}]*\})?\s+(\S+)', line)
        if m and m.group(1) in names:
            out[m.group(1) + (m.group(2) or '')] = float(m.group(3))
    return out


COUNTERS = ('TEB_EvtCt', 'TEB_WrtCt', 'TEB_TrCt', 'DRP_RecordSize', 'drp_num_dma_errors',
            'drp_num_pgp_jump', 'drp_num_th_error', 'drp_num_missing_rogs', 'DRP_Damage')


def pv_get(name, timeout=3.0):
    from p4p.client.thread import Context
    ctx = Context('pva')
    try:
        return ctx.get(name, timeout=timeout)
    except Exception as e:
        return f'error: {e}'
    finally:
        ctx.close()


def cmd_status(args):
    work = Work(args.workdir)
    state = work.load()
    if state is None:
        print(f'daq_sim: nothing recorded in {work.dir}')
        return 1
    ok = True
    print(f'workdir {work.dir}  host {state["host"]}  platform {state["platform"]}  started {state["started"]}'
          f'{"  (down)" if state.get("down") else ""}')
    for name, svc in state['services'].items():
        alive = pid_alive(svc['pid'])
        ok &= alive
        print(f'  {name:<10} pid {svc["pid"]:<8} {"alive" if alive else "DEAD"}')
    if state.get('procmgr_started'):
        status, _ = procmgr_status(state)
        for i in procs(state):
            st = status.get(i, ('?', '-'))
            ok &= st[0] == 'RUNNING'
            print(f'  {i:<10} pid {st[1]:<8} {st[0]}')
    try:
        from psdaq.control.DaqControl import DaqControl
        dc = DaqControl(host='localhost', platform=state['platform'], timeout=3000)
        t, s, alias, rec, _, _, exp, run, last = dc.getStatus()
        dc.context.destroy(0)
        print(f'  control    state {s}  transition {t}  config {alias}  recording {rec}  '
              f'experiment {exp}  run {run}  last run {last}')
    except Exception as e:
        ok = False
        print(f'  control    error: {e}')
    if 'webgui' in state['services']:
        import urllib.request
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            st = json.loads(opener.open(webgui_url(state) + 'api/status', timeout=5).read())
            ev = json.loads(opener.open(webgui_url(state) + 'api/events', timeout=5).read())
            print(f'  webgui     {webgui_url(state)} state {st.get("state")}  events {ev.get("events")} '
                  f'(source {ev.get("source")}, final {ev.get("final")})')
        except (OSError, ValueError) as e:
            ok = False
            print(f'  webgui     {webgui_url(state)} error: {e}')
    g = state['platform']
    for pv in ('NumL0Acc', 'NumL0Inp'):
        print(f'  simxpm     PART:{g}:{pv} = {pv_get(f"{PVBASE}:XPM:{XPM}:PART:{g}:{pv}")}')
    for port in prometheus_targets(work.path('prom')):
        for k, v in scrape(port, COUNTERS).items():
            print(f'  prom:{port} {k} = {v:g}')
    return 0 if ok else 1


# --- cycle ---------------------------------------------------------------------------------

def cmd_cycle(args):
    """Drive one run, one state at a time; every state is read back.

    control.py answers setstate with 'ok' before it runs the transition, and serves the next
    request (getState) only after it, so getState is the wait; failures arrive as 'error'
    messages on the status stream, which a thread collects (daqstate ignores both)."""
    from psdaq.control.DaqControl import DaqControl
    started = now()
    work = Work(args.workdir)
    state = work.load()
    if state is None or state.get('down'):
        raise Fail(f'not up in {work.dir}')
    plat = state['platform']
    dc = DaqControl(host='localhost', platform=plat, timeout=args.timeout * 1000)
    msgs, stop = [], threading.Event()

    def monitor():                      # The status stream: errors, file reports, transitions
        mon = DaqControl(host='localhost', platform=plat, timeout=1000)
        mon.front_sub.setsockopt(zmq_rcvtimeo(), 500)
        while not stop.is_set():
            try:
                m = mon.front_sub.recv_json()
            except Exception:
                continue
            key = m.get('header', {}).get('key')
            if key in ('error', 'warning', 'fileReport'):
                body = m.get('body', {})
                msgs.append((now(), key, body.get('err_info', body.get('path'))))
                print(f'{now()} [{key}] {msgs[-1][2]}', flush=True)
        mon.context.destroy(0)

    mt = threading.Thread(target=monitor, daemon=True)
    mt.start()
    time.sleep(0.5)
    rows, ok = [], True

    def go(target):
        nonlocal ok
        t0 = now()
        err = dc.setState(target)
        got = dc.getState()
        t1 = now()
        rows.append((t0, t1, target, got, err))
        good = err is None and got == target
        print(f'{t1} setState {target:<12} -> {got:<12} {"OK" if good else "FAIL"}'
              f'{"  error: " + str(err) if err else ""}', flush=True)
        ok &= good
        return good

    start = dc.getState()
    print(f'{now()} start state: {start}', flush=True)
    if start not in STATES:
        raise Fail(f'control state {start!r}')
    if dc.getStatus()[3] != args.record:
        err = dc.setRecord(args.record)
        print(f'{now()} setRecord({args.record}) -> {err or "OK"}', flush=True)
    i0 = STATES.index(start)
    for target in STATES[i0 + 1:]:
        if not go(target):
            break
        if target == 'unallocated':
            select_all(dc)
    count = None
    status = dc.getStatus()             # (transition, state, alias, recording, ..., experiment, run, last)
    print(f'{now()} status: transition {status[0]} state {status[1]} recording {status[3]} '
          f'experiment {status[6]} run {status[7]}', flush=True)
    if ok:
        pv = f'{PVBASE}:XPM:{XPM}:PART:{plat}:NumL0Acc'
        end = time.monotonic() + args.events / max(state['rate'], 1.) * 3 + 30
        while time.monotonic() < end:
            v = pv_get(pv)
            count = int(v) if not isinstance(v, str) else None
            if count is not None and count >= args.events:
                break
            time.sleep(1)
        print(f'{now()} {pv} = {count} (wanted >= {args.events})', flush=True)
        ok &= count is not None and count >= args.events
    counts, prev = {}, None
    cur = dc.getState()                 # Back down, one state at a time, to the start state
    if cur in STATES:
        prev = cur
        for target in reversed(STATES[i0:STATES.index(cur)]):
            if not go(target):
                break
            if prev == 'running' and target == 'paused':
                counts.update(_run_counts(work, plat))
            prev = target
    final = dc.getState()
    ok &= final == start
    stop.set()
    mt.join(2)
    dc.context.destroy(0)

    run = status[7] if isinstance(status[7], int) else 0
    if args.record and run:
        counts.update(_psana_counts(work, state, status[6], run))
    want = ('simxpm NumL0Acc', 'TEB_WrtCt', 'psana2 events') if args.record and run else \
           ('simxpm NumL0Acc', 'TEB_EvtCt')
    values = [counts.get(k) for k in want]
    equal = None not in values and len(set(values)) == 1 and values[0] >= args.events
    if args.record and run:
        equal = equal and counts.get('psana2 with data') == values[0] and counts.get('psana2 checks') == 'PASS'
    ok &= bool(equal)
    print(f'{now()} final state {final} (start {start})', flush=True)
    print('transitions (request -> read back):', flush=True)
    for t0, t1, target, got, err in rows:
        print(f'  {t0} -> {t1}  {target:<12} {got:<12} {"" if err is None else err}', flush=True)
    print('counts:', flush=True)
    for k, v in counts.items():
        print(f'  {k:<22} {v}', flush=True)
    print(f'  equal ({" == ".join(want)}) >= {args.events}: {bool(equal)}', flush=True)
    with open(work.path('logs', 'cycle.jsonl'), 'a') as f:
        f.write(json.dumps({'when': now(), 'transitions': rows, 'messages': msgs, 'counts': counts,
                            'ok': ok}) + '\n')
    errors = [m for m in msgs if m[1] == 'error']
    if errors:
        print(f'{now()} {len(errors)} error message(s) on the status stream', flush=True)
    if ok and not errors and args.record and run:
        _record_cycle_evidence(work, state, status[6], run, counts, started)
    print(f'{now()} cycle {"PASS" if ok and not errors else "FAIL"}', flush=True)
    return 0 if ok and not errors else 1


def _record_cycle_evidence(work, state, experiment, run, counts, started):
    """Evidence for 'daq_sim coverage' from a passing recorded cycle: the rows of the programs
    the generated .cnf started (and its drp's -D type), plus the rows whose stand-in (in
    coverage_status.json) is a service 'up' started, e.g. simxpm for pyxpm.  It lists the run's
    xtc2 files and the logs coverage reads the rows' proof in (each procmgr process's newest
    log and each service's log).  A failure to write it, or a row coverage would reject, is
    reported and leaves the cycle's verdict alone; coverage then finds no valid evidence."""
    import glob
    try:
        rows = coverage.config_rows(work.path(state['cnf']))
        rows += coverage.stand_in_rows(state.get('services', {}))
        files = sorted(glob.glob(work.path('data', INSTRUMENT, experiment, 'xtc',
                                           f'{experiment}-r{run:04d}-s*-c*.xtc2')))
        files += [work.path(state['cnf']), work.path('logs', 'cycle.jsonl')]
        files += [s['log'] for s in state.get('services', {}).values()]
        for proc in procs(state):       # the newest procmgr log of each process
            logs = glob.glob(work.path('pmlogs', '*', '*', f'*:{proc}.log'))
            files += sorted(logs, key=os.path.getmtime)[-1:]
        cache = {}
        path = coverage.record_evidence(rows, 'cycle', files, run_id=f'{experiment}/r{run:04d}',
                                        counts=counts, started=started, cache=cache)
        eid = os.path.basename(path)[:-5]
        print(f'{now()} evidence {eid}: {" ".join(sorted(rows))}', flush=True)
        for row, why in sorted(coverage.record_verdicts(path, cache=cache).items()):
            if why:
                print(f'{now()} evidence {eid}: coverage would reject it for {row}: {why}', flush=True)
    except Exception as e:
        print(f'{now()} evidence NOT recorded: {type(e).__name__}: {e}', flush=True)


def _run_counts(work, plat):
    """Counts right after Disable: simxpm's NumL0Acc and the TEB/DRP Prometheus counters (they
    vanish at Disconnect)."""
    time.sleep(1.0)                     # The last L1Accepts drain through the TEB
    out = {}
    v = pv_get(f'{PVBASE}:XPM:{XPM}:PART:{plat}:NumL0Acc')
    out['simxpm NumL0Acc'] = None if isinstance(v, str) else int(v)
    v = pv_get(f'{PVBASE}:XPM:{XPM}:PART:{plat}:NumL0Inp')
    out['simxpm NumL0Inp'] = None if isinstance(v, str) else int(v)
    for port in prometheus_targets(work.path('prom')):
        for k, val in scrape(port, COUNTERS).items():
            out[k.split('{')[0]] = int(val)
    print(f'{now()} counts after Disable: {out}', flush=True)
    return out


def _psana_counts(work, state, experiment, run, seed=None):
    """Read the run's xtc2 file back with psana2 (psdaq.sim.xtc2_check); every event's w3 must be
    seed (default: the sim_seed 'up' stored)."""
    import glob
    pattern = work.path('data', INSTRUMENT, experiment, 'xtc', f'{experiment}-r{run:04d}-s*-c000.xtc2')
    files = sorted(glob.glob(pattern))
    if not files:
        return {'xtc2 file': f'none matching {pattern}'}
    # With --segments N each DRP writes its own -s<stream> file and control numbers the streams, so
    # <det>_0's file is the first one in which xtc2_check finds segment 0 (the type's det.raw.raw).
    for path in files:
        out = {'xtc2 file': f'{path} ({os.path.getsize(path)} B)'}
        r = subprocess.run([sys.executable, '-m', 'psdaq.sim.xtc2_check', path, '--det', DETECTOR,
                            '--seed', str(state['seed'] if seed is None else seed), '--json'],
                           capture_output=True, text=True, timeout=600)
        try:
            res = json.loads(r.stdout.strip().splitlines()[-1])
            break
        except (ValueError, IndexError):
            if path == files[-1]:
                return dict(out, **{'psana2 checks': f'xtc2_check failed: {r.stderr.strip()[-300:]}'})
    out.update({'psana2 events': res['events'], 'psana2 with data': res['with_data'],
                'psana2 checks': 'PASS' if res['pass'] else f'FAIL {res["problems"][:3]}',
                'psana2 seq': f'{res["first_seq"]}..{res["last_seq"]}',
                'psana2 seeds': {f'{int(k):#x}': v for k, v in res.get('seeds', {}).items()}})
    return out


def select_all(dc):
    """Select every process that answered rollcall, as the GUIs' partition dialog does.

    control.py sets each process's 'monitor' flag only in selectplatform (control.py
    handle_selectplatform); without this step BeginRun logs "<E> KeyError: 'monitor'" and
    leaves the detector out of the run parameters (control.py RunParams, condition_beginrun)."""
    body = dc.getPlatform()
    for level, procs in body.items():
        for proc in procs.values():
            proc['active'] = 1
            proc.setdefault('monitor', 0)
    reply = dc.selectPlatform(body)
    print(f'{now()} selectPlatform({", ".join(sorted(body))}) -> '
          f'{reply.get("err_info", "OK") if isinstance(reply, dict) else reply}', flush=True)


def zmq_rcvtimeo():
    import zmq
    return zmq.RCVTIMEO


# --- matrix --------------------------------------------------------------------------------

def cmd_matrix(args):
    """The whole hardware-free matrix, unattended; its exit code is the verdict.  For now it
    only runs the coverage check: the runs that write evidence for each row come later."""
    say('matrix: no runs yet, coverage check only')
    return coverage.run(args)


# --- main ----------------------------------------------------------------------------------

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(prog='daq_sim', description=__doc__.split('\n\n')[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog=__doc__.split('\n\n', 1)[1])
    sub = parser.add_subparsers(dest='command', required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('-w', '--workdir', default=os.environ.get('DAQ_SIM_WORKDIR_DEFAULT', 'daq_sim_work'),
                        help='work dir for state, logs, data (default ./%(default)s)')
    upopts = argparse.ArgumentParser(add_help=False)
    upopts.add_argument('-p', '--platform', type=int, default=5, choices=range(8))
    upopts.add_argument('--rate', type=float, default=1000., help='L1Accept rate, Hz (default %(default)g)')
    upopts.add_argument('--seed', type=lambda s: int(s, 0), default=0x1234,
                        help='sim_seed stored in the config DB (default %(default)#x)')
    upopts.add_argument('--length', type=int, default=64, help='payload words per event (default %(default)d)')
    upopts.add_argument('--segments', type=int, default=1, choices=range(1, 5),
                        help='DRPs of the --det type, as segments 0..N-1 of one detector (default %(default)d)')
    upopts.add_argument('--det', default='fakecam', choices=sorted(SIM_TYPES),
                        help='simulated detector type for the DRP (default %(default)s)')
    upopts.add_argument('-S', '--slow-update', type=int, default=1, choices=(0, 1, 5, 10),
                        help='control -S slow update rate, Hz (default %(default)d)')
    upopts.add_argument('--skip-preflight', action='store_true', help='do not run preflight.sh (not recommended)')
    upopts.add_argument('--any-host', action='store_true', help='allow an interactive node')
    upopts.add_argument('-v', '--verbose', action='store_true', help='teb and drp with -v')
    up = sub.add_parser('up', parents=[common, upopts], help='start everything (foreground)')
    up.add_argument('--webgui', action='store_true',
                    help='also start the web GUI on 127.0.0.1:<port block +3> (real DaqControl backend)')
    up.add_argument('--detach', action='store_true', help='return once up instead of staying in the foreground')
    sub.add_parser('down', parents=[common], help='stop what up started; check ports')
    sub.add_parser('status', parents=[common], help='show processes, control state, counts')
    cy = sub.add_parser('cycle', parents=[common], help='drive one run up to running and back')
    cy.add_argument('--events', type=int, default=1000, help='L1Accepts to wait for (default %(default)d)')
    cy.add_argument('--no-record', dest='record', action='store_false', help='do not record')
    cy.add_argument('--timeout', type=int, default=60, help='per-transition timeout, s (default %(default)d)')
    e2e = sub.add_parser('e2e', parents=[common, upopts],
                         help='end-to-end test: a headless browser drives one run through the web GUI')
    e2e.add_argument('--events', type=int, default=1000,
                     help='L1Accepts the run must record (default %(default)d); the test waits for 10%% more')
    e2e.add_argument('--break', dest='breakage', choices=('kill-drp', 'truncate-xtc2'), default=None,
                     help='make the test fail on purpose: kill-drp = SIGKILL the DRP once RUNNING; '
                          'truncate-xtc2 = cut the last 100 L1Accepts off the xtc2 file before psana2 reads it')
    e2e.add_argument('--edit-seed', type=lambda s: int(s, 0), default=None,
                     help='before Configure, set user.sim_seed of BEAM/fakecam_0 to this value in the web '
                          'config editor; the DRP must read it at Configure and psana2 find it in every event')
    e2e.add_argument('--expect-seed', type=lambda s: int(s, 0), default=None,
                     help='sim_seed the checks expect (default: --edit-seed, else --seed); set it to another '
                          'value than --edit-seed to see the test fail')
    e2e.add_argument('--browser-python', default=None,
                     help='python of the Playwright venv (default $DAQ_SIM_BROWSER_PYTHON, else '
                          '$AGENTIFY_WEBTEST/venv/bin/python)')
    e2e.add_argument('--browsers-path', default=None,
                     help='PLAYWRIGHT_BROWSERS_PATH (default: $PLAYWRIGHT_BROWSERS_PATH, else <venv>/../browsers)')
    e2e.add_argument('--keep-up', action='store_true',
                     help='do not take the DAQ down at the end (if e2e brought it up, it then stays in the '
                          'foreground, like up)')
    e2e.add_argument('--timeout', type=int, default=60, help='per-transition timeout, s (default %(default)d)')
    e2e.add_argument('--shots', default=None, help='screenshot dir (default <workdir>/e2e-shots)')
    cov = sub.add_parser('coverage', help='is every detector type and program proven at HEAD? '
                         '(psdaq.sim.coverage)')
    coverage.add_arguments(cov)
    mx = sub.add_parser('matrix', help='the whole hardware-free matrix (for now: the coverage check)')
    coverage.add_arguments(mx)
    args = parser.parse_args(argv)
    if args.command == 'coverage':      # reads the checkout only: no DAQ env needed
        return coverage.run(args)
    if args.command == 'matrix':
        return cmd_matrix(args)
    ensure_env(argv)
    try:
        old = Work(args.workdir).load() or {}
        use_det(getattr(args, 'det', None) or old.get('det') or 'fakecam')
        if args.command == 'e2e':
            from psdaq.webgui.e2e import cmd_e2e
            return cmd_e2e(args)
        return {'up': cmd_up, 'down': cmd_down, 'status': cmd_status, 'cycle': cmd_cycle}[args.command](args)
    except Fail as e:
        print(f'daq_sim {args.command}: {e}', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    # Run main() from the importable module, not from __main__: psdaq.webgui.e2e imports
    # psdaq.sim.daq_sim, and its Fail must be the class main() catches (else a traceback).
    from psdaq.sim import daq_sim
    sys.exit(daq_sim.main())
