"""daq_sim: bring up, check, drive and take down the hardware-free lcls2 DAQ on one node.

    daq_sim up     [-w WORKDIR] [-p PLATFORM] [--rate HZ] [--seed N] [--length WORDS] [--segments N]
                   [--det TYPE] [--also TYPE[:GROUP]]... [--fixed-rate GROUP:INDEX]... [--bld]
                   [--meb] [--ami] [--pva] [--epics] [--udp] [--gui] [--webgui] [--detach]
                   [--hosts HOST_A,HOST_B --dry-run]
    daq_sim status [-w WORKDIR]
    daq_sim cycle  [-w WORKDIR] [--events N] [--no-record] [--kill-drp]
    daq_sim e2e    [-w WORKDIR] [--events N] [--edit-seed N [--expect-seed M]]
                   [--break kill-drp|truncate-xtc2] [--browser-python PATH] [--keep-up]
    daq_sim down   [-w WORKDIR]
    daq_sim coverage [--repo DIR] [--status FILE] [--evidence DIR] [-v] [--json]
    daq_sim matrix   [-w WORKDIR] [--only types|programs|features|coverage] [--types T,..] [--features x,..]
                     [--events N] [--lock FILE] [--ami-src DIR] [--hosts A,B]
                     [--break register|kill-drp|corrupt] (psdaq.sim.matrix)
    daq_sim feature  a|b|c|d|e [-w WORKDIR] [--events N] [--check-only] [--break KIND] [--ami-src DIR]
                     [--hosts A,B] (psdaq.sim.feature)

'up' starts, in this order and all on this node:
  1. the isolation env (sim_env.sh, sourced by re-executing through bash) and the fail-closed
     preflight (preflight.sh); 'up' stops if the preflight does not pass,
  2. the config DB stand-in (configdb_server), seeded by configdb_seed,
  3. the run DB / eLog stand-in (lgbk_server),
  4. simxpm, the software XPM (PVA server + timing frames + control.py -X receiver),
  5. procmgr with a generated .cnf: control in normal mode, teb0, and drp -D fakecam -d sim://
     (with --segments N: N such DRPs, fakecam_0 .. fakecam_<N-1>, segments of one detector, each
     with its config in the config DB, all in the partition's readout group; with --det TYPE
     another type of SIM_TYPES instead of fakecam: a BEB type's own <type>_config.py configures
     a device psdaq.sim.rogue_dev emulates, from the type's own config in the config DB; every
     XpmDetector type, fakecam included, runs xpmdet_config against an emulated TDet receiver),
     With --also TYPE[:GROUP], one more DRP <TYPE>_0 of another simulated type, in readout group
     GROUP (default: the platform's); with --fixed-rate GROUP:INDEX, simxpm runs with
     --fixed-rates and 'up' sets that group's L0Select to FixedRate and its L0Select_FixedRate to
     INDEX (pyxpm's PVs, as an operator does in the XPM GUI), so groups take L1Accepts at
     different rates; with --bld, drp_bld (bld_0) records simxpm's BLD source (simxpm --bld:
     multicast on 127.0.0.1, TTL 1, to a group outside LCLS's 239.255.0.0/16), the multicast
     group and port from the stand-in IOC's CA PVs as BldPVA reads them,
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
state it started from.  It exits nonzero on any failure (--kill-drp, a deliberate one, SIGKILLs
the DRP once Running).  A passing recorded cycle writes an
evidence record (psdaq.sim.coverage.record_evidence) for the rows it proves: the programs
of the generated .cnf, its drp's -D type and the stand-ins 'up' started; the record lists the
run's xtc2 files and every process's log with their sizes and sha256, and the cycle prints
what 'daq_sim coverage' would reject in it.
'coverage' checks that every row (detector type, program a procmgr config starts) is RUN,
STAND-IN or N/A, each RUN/STAND-IN row with evidence recorded at HEAD (psdaq.sim.coverage).
'matrix' runs the whole hardware-free matrix unattended: a cycle of every detector type, the
system features, then the coverage check; it exits 0 only if every assertion passes (psdaq.sim.matrix).
'feature' runs one system feature end to end (up, its run, its checks, down) and prints its
report (psdaq.sim.feature).
'up --hosts A,B --dry-run' prints the .cnf and environment of one partition spread over two
nodes (multi_host_plan) without starting anything.
'e2e' is the end-to-end test: the same run driven through the web GUI by a headless browser
(psdaq.webgui.e2e); it brings the DAQ up with --webgui unless it is up already, checks
every state and count itself, prints E2E PASS or E2E FAIL and the exit code says which.

Ports for platform p (block 31000 + 10 p; p = 5 gives 31050-31059):
  +0 config DB stand-in   +1 run DB stand-in   +2 simxpm frames   +3 web GUI (up --webgui)
UDP: 31200 + p drp_udpencoder (--udp), 31220 + p BLD multicast (--bld, group 239.254.31.<p>).
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
    return {'configdb': base, 'lgbk': base + 1, 'frames': base + 2, 'webgui': base + 3,
            'ami': 31100 + 10 * platform, 'ami_prom': 31180 + 2 * platform,
            'udp': 31200 + platform, 'ami_pvas': (31210 + 2 * platform, 31211 + 2 * platform),
            'bld': 31220 + platform,
            'ami_shot_pvas': (31230 + 2 * platform, 31231 + 2 * platform),
            'pvservers': {'simhsd': (31300 + 10 * platform, 31301 + 10 * platform),
                          'simtpr': (31302 + 10 * platform, 31303 + 10 * platform),
                          'simdti': (31304 + 10 * platform, 31305 + 10 * platform),
                          'bldcas': (31306 + 10 * platform, 31307 + 10 * platform),
                          'hpsdbuscas': (31308 + 10 * platform, 31309 + 10 * platform)}}


def bld_group(platform):
    """--bld's multicast group: administratively scoped, outside LCLS's 239.255.0.0/16."""
    return f'239.254.31.{platform}'


def ami_ports(platform):
    """The 10 TCP ports AMI takes from its base port (ami.comm.Ports: Comm .. Sync)."""
    base = ports(platform)['ami']
    return list(range(base, base + 10))


def meb_tag(platform):
    """The MEB's shared-memory tag (monReqServer -t), which its clients name (shmemClient -p,
    psana shmem=)."""
    return f'{INSTRUMENT}sim{platform}'


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


def drp_pid(state, alias):
    """(pid, cmdline) of the program procmgr runs as alias, e.g. <det>_0's drp: the pid 'up'
    recorded, or, when that is the procServ holding it, procServ's child; (None, '') if gone."""
    pid = (state.get('procs') or {}).get(alias)
    if pid is None or not pid_alive(pid):
        return None, ''
    if os.path.basename(cmdline(pid).split(' ')[0]) != 'procServ':
        return pid, cmdline(pid)
    for d in os.listdir('/proc'):
        if d.isdigit():
            try:
                with open(f'/proc/{d}/stat') as f:
                    ppid = int(f.read().rsplit(')', 1)[1].split()[1])
            except (OSError, IndexError, ValueError):
                continue
            if ppid == pid and pid_alive(int(d)):
                return int(d), cmdline(int(d))
    return None, ''


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
    """procmgr ids 'up' starts: PROCS plus the extra detector segments of --segments, and the
    MEB, its shmemClient and the AMI processes of --meb / --ami."""
    return PROCS + tuple(f'{DETECTOR}_{i}' for i in range(1, state.get('segments', 1))) + \
        (MEB_PROCS if state.get('meb') else ()) + (AMI_PROCS if state.get('ami') else ()) + \
        (PVA_PROCS if state.get('pva') else ()) + (EPICS_PROCS if state.get('epics') else ()) + \
        (GUI_PROCS if state.get('gui') else ()) + (UDP_PROCS if state.get('udp') else ()) + \
        tuple(a['alias'] for a in state.get('also', ())) + (BLD_PROCS if state.get('bld') else ()) + \
        (SERVER_GUI_PROCS if state.get('gui') and state.get('pvservers') else ()) + \
        (PVSERVER_PROCS if state.get('pvservers') else ())


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
# --meb: the monitoring event builder (rix.cnf's meb_cmd: -d distributes events over -q queues)
# and a shmemClient on its second queue (as lab3-hsd134_cg.cnf); -v prints every datagram's time.
# Its POSIX message queues hold -n messages, which must not exceed fs.mqueue.msg_max (10 on S3DF
# milano nodes; XtcMonitorServer.cc _openQueue), so -n 8 rather than the hutches' 64.
MEB_PROCS = ('meb0', 'shmc0')
MEB = ''' {{ id:'meb0', flags:'spu',
   cmd:'monReqServer{v} -P {instr} -C localhost -k {ep} -M {prom} -d -n 8 -q 2 -t {tag}' }},
 {{ id:'shmc0', flags:'s', cmd:'shmemClient -p {tag} -i 1 -v -R' }},
'''
# --ami: AMI as ami.cnf runs it (manager, global collector, a node collector and a worker that
# reads the MEB, plus the client GUI, offscreen), every port on 127.0.0.1.  The ami-* commands
# are the AMI source tree's console scripts, written into <workdir>/bin (ami_scripts).
AMI_PROCS = ('ami-manager', 'ami-global', 'ami-node_0', 'ami-worker_0', 'ami-client')
AMI_SCRIPTS = {'ami-manager': ('ami.manager', 'main'), 'ami-global': ('ami.collector', 'global_main'),
               'ami-node': ('ami.collector', 'node_main'), 'ami-worker': ('ami.worker', 'main'),
               'ami-client': ('ami.client', 'main')}
AMI = ''' {{ id:'ami-manager', flags:'s',
   cmd:'{bin}/ami-manager -p {abase} -H 127.0.0.1 -n 1 -N 1 {aopts}' }},
 {{ id:'ami-global', flags:'s',
   cmd:'{bin}/ami-global -p {abase} -H 127.0.0.1 -N 0 -n 1 {aopts}' }},
 {{ id:'ami-node_0', flags:'s',
   cmd:'{bin}/ami-node -p {abase} -H 127.0.0.1 -N 0 -n 1 {aopts}' }},
 {{ id:'ami-worker_0', flags:'s',
   cmd:'{bin}/ami-worker -p {abase} -H 127.0.0.1 -N 0 -n 1 -b {heartbeat} {aopts}'
       ' psana://shmem={tag},skip_calib_load=all' }},
 {{ id:'ami-client', flags:'s', env:'QT_QPA_PLATFORM=offscreen {pvas}',
   cmd:'{bin}/ami-client -p {abase} -H 127.0.0.1 {aopts}' }},
'''
# ami-client starts a PVA server of its own (PvCtrlServer).  On the node's PVA search port it would
# share the unicast searches with simxpm's server, and a search reaches only one of the sockets
# bound to a port, so the DRPs' and control's searches could miss simxpm: it gets its own ports.
AMI_CLIENT_PVAS = 'EPICS_PVAS_SERVER_PORT={0} EPICS_PVAS_BROADCAST_PORT={1}'
AMI_HEARTBEAT_MS = 200
# --pva: drp_pva records simxpm's camera PV (simxpm --camera-pv), an NTNDArray whose every update
# carries the time of one L1Accept, as an areaDetector IOC with a timing receiver stamps frames.
PVA_PROCS = ('pvcam_0',)
CAMERA_PV = f'{PVBASE}:CAM:IMAGE'
PVA = ''' {{ id:'pvcam_0', flags:'spu',
   cmd:'drp_pva{v} -P {instr} -C localhost -d sim://127.0.0.1:{frames} -l 0x1 -o {data}'
       ' -k {ep} -M {prom} pva/{campv}' }},
'''
# --epics: epicsArch archives two CA PVs of a stand-in IOC (EPICS base's softIoc, on loopback) that
# 'up' starts from EPICS_DB, and one PVA PV of simxpm, its partition's L0 accept count (the one PVA
# server on the node, see AMI_CLIENT_PVAS).
EPICS_PROCS = ('epics_0',)
EPICS_DB = '''# Written by daq_sim up --epics: the stand-in IOC whose PVs epicsArch records
record(calc, "{pvbase}:EPICS:COUNT") {{
  field(SCAN, ".1 second")
  field(CALC, "A+1")
  field(INPA, "{pvbase}:EPICS:COUNT NPP")
}}
record(ao, "{pvbase}:EPICS:CONST") {{
  field(VAL, "{const}")
  field(PINI, "YES")
}}
'''
EPICS_CONST = 1234.5
# --udp: drp_udpencoder reads the encoder frames sim_udpencoder sends to 127.0.0.1:<udp port>,
# one per L1Accept of the readout group, paced by simxpm's frames (sim_udpencoder -T sim://)
# instead of a TPR; it prints each transition's time.
UDP_PROCS = ('encoder_0', 'simenc')
UDP = ''' {{ id:'encoder_0', flags:'spu',
   cmd:'drp_udpencoder{v} -P {instr} -C localhost -d sim://127.0.0.1:{frames} -l 0x1 -o {data}'
       ' -k {ep} -M {prom} -L {udpport}' }},
 {{ id:'simenc', flags:'s',
   cmd:'sim_udpencoder -T sim://127.0.0.1:{frames} -p {platform} -a 127.0.0.1 -d {udpport}' }},
'''
# --gui: PyQt GUIs as the configs start them, offscreen: control_gui (asc.cnf: control_gui -H
# localhost -p <p>) on the config DB stand-in, which at its default log level (DEBUG) logs every
# status message control publishes (the run's fileReport with its path relative to the data dir);
# on simxpm's PVs groupca (asc.cnf: groupca DAQ:ASC 0 0), partca (lab3-cam.cnf: launch_py
# <bins>/partca.py DAQ:LAB2:PART:<p>; psdaq installs no partca command, so python -m) and pvant (lab3-wave8.cnf: pvant --bases ... --fields ..., here the
# partition's L0 counters); procstat on procmgr's table; and epics_exporter (pvrtmon_0) on the
# XPM's partition PVs.  None of them logs a run: cycle runs each GUI once more, offscreen, while
# the run is Running, scrapes the exporter, and keeps what they show (psdaq.sim.gui_witness), as
# the witness 'daq_sim coverage' reads.
GUI_PROCS = ('control_gui', 'groupca', 'partca', 'pvant', 'procstat', 'pvrtmon_0', 'daqstat')
# daqstat (mfx.py: daqstat -i 5) shows the Slurm job of each process of a daqmgr config: here simslurm's jobs for the
# processes of daq_sim.cnf (up starts simslurm, psdaq.sim.simslurm), its Slurm commands answered by simslurm through
# the shims first on its PATH, never by a Slurm controller; HOME is where daqmgr's Runner makes daq/logs
DAQSTAT = ''' {{ id:'daqstat', flags:'s', env:'QT_QPA_PLATFORM=offscreen HOME={home} PATH={path}',
   cmd:'daqstat {args}' }},
'''
SLURM_DIR = 'slurm'                     # <workdir>/slurm: simslurm's state, the daqmgr config, shims, logs, HOME
# --gui with --pvservers (R4): the GUIs whose PVs come from a device stand-in (gui_witness.WITNESS 'server'), each
# with a PVA client that searches only its stand-in's ports on 127.0.0.1
SERVER_GUI_PROCS = ('hsdpva', 'tprca', 'dtica', 'pvatable', 'xpmpva', 'deadca')
SERVER_GUI = ''' {{ id:'{id}', flags:'s', env:'QT_QPA_PLATFORM=offscreen {pvaenv}',
   cmd:'{cmd} {args}' }},
'''
# --pvservers: the tree's own PV servers (gui_witness.PROGRAM_SERVERS, RUN rows) under procmgr as lab3-bld.cnf starts
# them, each serving on PVA ports of its own on 127.0.0.1 (so simxpm stays the only server on the search port)
PVSERVER_PROCS = ('bldcas', 'hpsdbuscas')
PVSERVER = ''' {{ id:'{id}', flags:'s', env:'EPICS_PVAS_SERVER_PORT={srv} EPICS_PVAS_BROADCAST_PORT={bcast}',
   cmd:'{id} {args}' }},
'''
GUI = ''' {{ id:'control_gui', flags:'sp', env:'QT_QPA_PLATFORM=offscreen',
   cmd:'control_gui -H localhost -l DEBUG -e {expname} -u {cfguri}' }},
 {{ id:'groupca', flags:'s', env:'QT_QPA_PLATFORM=offscreen',
   cmd:'groupca {groupca}' }},
 {{ id:'partca', flags:'s', env:'QT_QPA_PLATFORM=offscreen',
   cmd:'python -m psdaq.cas.partca {partca}' }},
 {{ id:'pvant', flags:'s', env:'QT_QPA_PLATFORM=offscreen',
   cmd:'pvant {pvant}' }},
 {{ id:'procstat', flags:'s', env:'QT_QPA_PLATFORM=offscreen',
   cmd:'procstat {procstat}' }},
 {{ id:'pvrtmon_0', flags:'s',
   cmd:'epics_exporter {epics_exporter}' }},
'''
EPICS_PVLIST = '''# Written by daq_sim up --epics: what epicsArch archives (its config file format)
*sim_count
{pvbase}:EPICS:COUNT ca
*sim_const
{pvbase}:EPICS:CONST ca
*sim_l0acc
{l0acc} pva
'''
# --also TYPE[:GROUP]: one more DRP of another simulated type (its readout group: activedet)
ALSO = ''' {{ id:'{alias}', flags:'spu',
   cmd:'drp{v} -P {instr} -C localhost -D {det} -d sim://127.0.0.1:{frames} -l 0x1 -o {data}'
       ' -k {ep},{simk} -M {prom}' }},
'''
# --bld: drp_bld records simxpm's BLD source (simxpm --bld), LCLS-II style: -D <name>+<type>+<PV prefix>
# (BldPVA), type scbld (psana2's scbld_raw_1_0_0), multicast joined on the loopback interface.
BLD_PROCS = ('bld_0',)
BLD_NAME = 'simbld'
BLD_PREFIX = f'{PVBASE}:BLD'
BLD = ''' {{ id:'bld_0', flags:'spu',
   cmd:'drp_bld{v} -P {instr} -C localhost -d sim://127.0.0.1:{frames} -l 0x1 -o {data}'
       ' -k {ep},interface=lo -M {prom} -D {bldname}+scbld+{bldprefix}' }},
'''
BLD_DB = '''record(stringin, "{prefix}:BLD1_MULT_ADDR") {{
  field(VAL, "{group}")
}}
record(longin, "{prefix}:BLD1_MULT_PORT") {{
  field(VAL, "{port}")
}}
'''
EPICS = ''' {{ id:'epics_0', flags:'spu',
   cmd:'epicsArch{v} -P {instr} -C localhost -d sim://127.0.0.1:{frames} -l 0x1 -o {data}'
       ' -k {ep} -M {prom} {pvlist}' }},
'''


def extra_entries(workdir, platform, verbose=False, meb=False, ami_bin=None, pva=False, epics=False,
                  gui=False, udp=False, also=(), bld=False, seed=0x1234, length=64, pvservers=False):
    """The procmgr entries of --also, --pva, --epics, --meb, --udp, --bld, --gui and --ami
    (ami_bin: where the ami-* programs are); with --gui and --pvservers also the GUIs on the
    device stand-ins (R4)."""
    P = ports(platform)
    common = dict(v=' -v' if verbose else '', instr=INSTRUMENT, ep=EP, frames=P['frames'],
                  data=os.path.join(workdir, 'data'), prom=os.path.join(workdir, 'prom'),
                  tag=meb_tag(platform))
    out = ''
    for a in also:
        out += ALSO.format(alias=a['alias'], det=a['det'], simk=SIM_TYPES[a['det']]['kwargs'].format(
            length=length, seed=seed, work=workdir), **common)
    if pva:
        out += PVA.format(campv=CAMERA_PV, **common)
    if epics:
        out += EPICS.format(pvlist=os.path.join(workdir, 'epicsArch.txt'), **common)
    if meb or ami_bin:
        out += MEB.format(**common)
    if udp:
        out += UDP.format(udpport=P['udp'], platform=platform, **common)
    if bld:
        out += BLD.format(bldname=BLD_NAME, bldprefix=BLD_PREFIX, **common)
    if gui:
        from psdaq.sim import gui_witness
        params = gui_params(platform, common['prom'], os.path.join(workdir, 'daq_sim.cnf'))
        out += GUI.format(expname=EXPERIMENT, cfguri=f'http://127.0.0.1:{P["configdb"]}/ws/',
                          **{g: ' '.join(gui_witness.argv(g, params))
                             for g in list(gui_witness.WITNESS) + list(gui_witness.MONITORS)})
        slurm = os.path.join(workdir, SLURM_DIR)
        out += DAQSTAT.format(home=os.path.join(slurm, 'home'), args=' '.join(gui_witness.argv('daqstat', params)),
                              path=os.path.join(slurm, 'bin') + os.pathsep + os.environ.get('PATH', ''))
        for g in (SERVER_GUI_PROCS if pvservers else ()):
            W = gui_witness.WITNESS[g]
            out += SERVER_GUI.format(id=g, cmd=f'python -m {W["module"]}' if W.get('module') else g,
                                     args=' '.join(gui_witness.argv(g, params)),
                                     pvaenv=' '.join(f'{k}={v}' for k, v in gui_witness.pva_env(
                                         P['pvservers'][W['server']][1]).items())
                                     if W['server'] in P['pvservers'] else '')    # simxpm: the node's own ports
    if pvservers:
        from psdaq.sim import gui_witness
        for g in PVSERVER_PROCS:
            out += PVSERVER.format(id=g, srv=P['pvservers'][g][0], bcast=P['pvservers'][g][1], args=' '.join(
                a.format(**gui_params(platform)) for a in gui_witness.PROGRAM_SERVERS[g]['args']))
    if ami_bin:
        aopts = (f'--prometheus-dir {common["prom"]} --prometheus-port {P["ami_prom"]} '
                 f'--hutch {INSTRUMENT}_sim{platform}')
        out += AMI.format(bin=ami_bin, abase=P['ami'], aopts=aopts, heartbeat=AMI_HEARTBEAT_MS,
                          tag=common['tag'], pvas=AMI_CLIENT_PVAS.format(*P['ami_pvas']))
    return out


def write_daqmgr_config(cnf, path, platform):
    """Write the daqmgr config (psdaq/slurm: platform and procmgr_config) of the processes of the procmgr config
    cnf, as procmgr loads it, for simslurm's jobs and daqstat.  (daqmgr's cnftopy converts a .cnf line by line and
    breaks on daq_sim.cnf's entries, which span two lines.)"""
    with open(cnf) as f:
        ns = coverage.exec_config(cnf, f.read())
    entries = [{'id': e['id'], 'cmd': e['cmd']} for e in ns['procmgr_config']]
    with open(path, 'w') as f:
        f.write(f'# Written by daq_sim up --gui from {cnf}: its processes, for simslurm and daqstat\n'
                f'platform = {str(platform)!r}\nprocmgr_config = [\n' +
                ''.join(f' {e!r},\n' for e in entries) + ']\n')
    return [e['id'] for e in entries]


def gui_params(platform, prom=None, cnf=None):
    """The placeholders of psdaq.sim.gui_witness's GUI and monitor argv (as qt_walk's sim_params
    gives them; prom: the work dir's Prometheus dir, cnf: its daq_sim.cnf)."""
    return {'pvbase': PVBASE, 'xpm': XPM, 'platform': platform,
            'part': f'{PVBASE}:XPM:{XPM}:PART:{platform}', 'prom': prom, 'cnf': cnf,
            'workdir': os.path.dirname(cnf) if cnf else None}


def udp_busy(port):
    """True if a UDP socket is bound to port."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(('0.0.0.0', port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def soft_ioc():
    """EPICS base's softIoc (CA only): on PATH, else in $CONDA_PREFIX/epics/bin/<arch>."""
    found = shutil.which('softIoc')
    if found:
        return found
    import glob
    hits = sorted(glob.glob(os.path.join(os.environ.get('CONDA_PREFIX', '/nonexistent'), 'epics', 'bin',
                                         '*', 'softIoc')))
    if not hits:
        raise Fail('--epics: no softIoc on PATH or under $CONDA_PREFIX/epics/bin (EPICS base)')
    return hits[0]


def ami_source(arg=None):
    """The AMI source tree (the directory holding the 'ami' package) for --ami: --ami-src, else
    $DAQ_SIM_AMI_SRC; None if neither is set (then the ami-* programs must be on PATH)."""
    src = arg or os.environ.get('DAQ_SIM_AMI_SRC') or None
    if src and not os.path.isfile(os.path.join(src, 'ami', 'manager.py')):
        raise Fail(f'--ami-src {src}: no ami/manager.py there (an AMI source tree, e.g. a clone '
                   'of github.com/slac-lcls/ami, holds the ami package)')
    return src


def ami_scripts(bindir, src):
    """Write the ami-* console scripts (AMI's pyproject [project.scripts]) for this python into
    bindir, importing ami from src; return bindir.  With no src, the ami-* on PATH are used."""
    if src is None:
        missing = [n for n in AMI_SCRIPTS if not shutil.which(n)]
        if missing:
            raise Fail(f'--ami: {" ".join(missing)} not on PATH; install AMI in this env or pass '
                       '--ami-src (or set DAQ_SIM_AMI_SRC) to an AMI source tree')
        return os.path.dirname(shutil.which('ami-manager'))
    os.makedirs(bindir, exist_ok=True)
    for name, (module, func) in AMI_SCRIPTS.items():
        path = os.path.join(bindir, name)
        with open(path, 'w') as f:
            f.write(f'#!{sys.executable}\n# {name}: console script of the AMI source tree in {src}, '
                    f'written by daq_sim up --ami\nimport sys\nsys.path.insert(0, {src!r})\n'
                    f'from {module} import {func}\nsys.exit({func}())\n')
        os.chmod(path, 0o755)
    return bindir


def write_activedet(path, platform, segments=1, meb=False, others=(), groups=None):
    """What control writes after an alloc of this partition, so its first rollcall finds it;
    'others' are more DRP aliases (drp_pva, epicsArch), in the same readout group, and 'groups'
    {alias: readout group} more DRPs in their own groups (--also)."""
    rog = {d: platform for d in [f'{DETECTOR}_{i}' for i in range(segments)] + list(others)}
    rog.update(groups or {})
    value = {'activedet': {'drp': {d: {'active': 1, 'det_info': {'readout': g}} for d, g in rog.items()},
                           'teb': {'teb0': {'active': 1}}},
             'history': {'drp': {d: {'det_info': {'readout': g}} for d, g in rog.items()}}}
    if meb:
        value['activedet']['meb'] = {'meb0': {'active': 1}}
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
    ami = getattr(args, 'ami', False)
    meb = getattr(args, 'meb', False) or ami
    amisrc = ami_source(getattr(args, 'ami_src', None)) if ami else None
    pva = getattr(args, 'pva', False)
    epics = getattr(args, 'epics', False)
    gui = getattr(args, 'gui', False)
    udp = getattr(args, 'udp', False)
    bld = getattr(args, 'bld', False)
    pvservers = getattr(args, 'pvservers', False)
    also = parse_also(getattr(args, 'also', None) or [], args.platform)
    fixed = parse_fixed_rates(getattr(args, 'fixed_rate', None) or [])
    why = barrier_conflict([DETECTOR] + [a['det'] for a in also], pva or epics or udp or bld)
    if why:
        raise Fail(why)
    ioc = soft_ioc() if (epics or bld) else None
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
    if ami:
        want += ami_ports(args.platform)
    if udp and udp_busy(P['udp']):
        raise Fail(f'UDP port {P["udp"]} already in use')
    if bld and udp_busy(P['bld']):
        raise Fail(f'UDP port {P["bld"]} already in use')
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
             'segments': segments, 'det': DETECTOR, 'meb': meb, 'ami': ami, 'ami_src': amisrc,
             'pva': pva, 'epics': epics, 'gui': gui, 'udp': udp,
             'also': also, 'fixed_rates': fixed, 'bld': bld, 'pvservers': pvservers}
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
        det_args = ['--det-type', DETECTOR] if DETECTOR != 'fakecam' else []
        if sim_type.get('det_yaml'):
            det_args += ['--det-yaml', sim_type['det_yaml'].format(**os.environ)]
        seeds = [(DETECTOR, segm, det_args) for segm in range(segments)]
        for a in also:                  # each --also type: its own config, as for --det
            yaml = SIM_TYPES[a['det']].get('det_yaml')
            seeds.append((a['det'], 0, (['--det-type', a['det']] if a['det'] != 'fakecam' else []) +
                          (['--det-yaml', yaml.format(**os.environ)] if yaml else [])))
        for i, (name, segm, dargs) in enumerate(seeds):
            r = subprocess.run([py, '-m', 'psdaq.sim.configdb_seed', '--url', cfg_url,
                                '--inst', INSTRUMENT, '--alias', CONFIG_ALIAS, '--trigger', TRIGGER,
                                '--det', name, '--segm', str(segm), '--sim-seed', str(args.seed),
                                '--sim-length', str(args.length)] + dargs,
                               env=env, capture_output=True, text=True, timeout=60)
            with open(work.path('logs', 'seed.log'), 'a' if i else 'w') as out:
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
                           '--pull', 'auto'] +
                          (['--camera-pv', CAMERA_PV, '--camera-seed', str(args.seed)] if pva else []) +
                          (['--fixed-rates'] if fixed else []) +
                          (['--bld', BLD_PREFIX, '--bld-dest', f'{bld_group(args.platform)}:{P["bld"]}',
                            '--bld-seed', str(args.seed)] if bld else []), env)
        wait_listen(P['frames'], 30, p, 'simxpm frames')
        wait_listen(pull_port(), 30, p, 'simxpm pull')
        for g, index in sorted(fixed.items()):     # as an operator sets a group's trigger (XPM GUI)
            for label, value in (('L0Select', 0), ('L0Select_FixedRate', index)):
                pv = count_pv(g, label)
                err = pv_put(pv, value)
                if err:
                    raise Fail(f'--fixed-rate: put {pv} = {value}: {err}')
            say(f'readout group {g}: L0Select FixedRate, L0Select_FixedRate {index} '
                f'({fixed_rate_label(index)})')

        if pvservers:                   # R3 stand-ins, each on PVA ports of its own (gui_witness.SERVERS)
            from psdaq.sim import gui_witness
            for name, S in gui_witness.SERVERS.items():
                srv, bcast = P['pvservers'][name]
                senv = dict(env, EPICS_PVAS_SERVER_PORT=str(srv), EPICS_PVAS_BROADCAST_PORT=str(bcast))
                p = start_service(work, state, name, [py, '-m', f'psdaq.sim.{name}'] +
                                  [a.format(**gui_params(args.platform)) for a in S['args']], senv)
                _wait_log(state['services'][name]['log'], 'ready', 30, p, name)
                say(f'{name} pid {p.pid}: PVA {srv}/{bcast} on 127.0.0.1, stands in for {", ".join(S["programs"])}')

        if sim_type.get('frame'):       # the frame an emulator type replays, from the seed
            r = subprocess.run([py, '-m', 'psdaq.sim.%s_frame' % DETECTOR, work.path(sim_type['frame']),
                                '--seed', str(args.seed)], env=env, capture_output=True, text=True,
                               timeout=120)
            with open(work.path('logs', 'frame.log'), 'w') as out:
                out.write(r.stdout + r.stderr)
            if r.returncode != 0:
                raise Fail(f'{DETECTOR}_frame failed: {r.stderr.strip()[-400:]}')
            say(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else f'{DETECTOR} frame written')

        write_activedet(work.path('activedet.json'), args.platform, segments, meb,
                        (PVA_PROCS if pva else ()) + (EPICS_PROCS if epics else ()) +
                        (UDP_PROCS[:1] if udp else ()) + (BLD_PROCS if bld else ()),
                        {a['alias']: a['group'] for a in also})
        if epics or bld:
            with open(work.path('sim_ioc.db'), 'w') as f:
                if epics:
                    f.write(EPICS_DB.format(pvbase=PVBASE, const=EPICS_CONST))
                if bld:
                    f.write(BLD_DB.format(prefix=BLD_PREFIX, group=bld_group(args.platform), port=P['bld']))
            if epics:
                with open(work.path('epicsArch.txt'), 'w') as f:
                    f.write(EPICS_PVLIST.format(pvbase=PVBASE, l0acc=count_pv(args.platform)))
            p = start_service(work, state, 'ioc', [ioc, '-S', '-d', work.path('sim_ioc.db')], env)
            _wait_ca(f'{PVBASE}:EPICS:CONST' if epics else f'{BLD_PREFIX}:BLD1_MULT_PORT', 30, p)
            say(f'stand-in IOC {ioc} pid {p.pid}: ' + ', '.join(
                ([f'{PVBASE}:EPICS:COUNT', f'{PVBASE}:EPICS:CONST'] if epics else []) +
                ([f'{BLD_PREFIX}:BLD1_MULT_ADDR {bld_group(args.platform)}',
                  f'{BLD_PREFIX}:BLD1_MULT_PORT {P["bld"]}'] if bld else [])) + ' (CA)')
        bindir = ami_scripts(work.path('bin'), amisrc) if ami else None
        if ami:
            say(f'AMI from {amisrc or bindir}: ports {P["ami"]}-{P["ami"] + 9} on 127.0.0.1, '
                f'worker reads psana://shmem={meb_tag(args.platform)}')
        extra = extra_entries(work.dir, args.platform, args.verbose, meb, bindir, pva, epics, gui, udp,
                              also, bld, args.seed, args.length, pvservers=pvservers)
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
                                                for i in range(1, segments)) + extra, **common))
        if gui:                         # daqstat's Slurm: simslurm's jobs for daq_sim.cnf's processes, shims on its PATH
            from psdaq.sim import simslurm
            slurm = work.path(SLURM_DIR)
            os.makedirs(os.path.join(slurm, 'home'), exist_ok=True)
            simslurm.write_shims(os.path.join(slurm, 'bin'), os.path.join(slurm, 'state.json'), py)
            write_daqmgr_config(work.path(state['cnf']), os.path.join(slurm, 'daqstat.py'), args.platform)
            p = start_service(work, state, 'simslurm', [py, '-m', 'psdaq.sim.simslurm', '--state',
                                                        os.path.join(slurm, 'state.json'), '--cnf',
                                                        os.path.join(slurm, 'daqstat.py'), '--logdir',
                                                        os.path.join(slurm, 'logs')], env)
            _wait_log(state['services']['simslurm']['log'], 'ready', 60, p, 'simslurm')
            say(f'simslurm pid {p.pid}: a Slurm job for each process of {state["cnf"]}, for daqstat')
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
        if gui:
            _wait_control_gui(work, 120)
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


def parse_also(items, platform):
    """--also TYPE[:GROUP] values -> [{det, group, alias}]: one DRP <TYPE>_0 per distinct type."""
    out = []
    for item in items:
        det, _, group = item.partition(':')
        if det not in SIM_TYPES:
            raise Fail(f'--also {item}: unknown type {det!r}; one of {sorted(SIM_TYPES)}')
        if det == DETECTOR or det in [a['det'] for a in out]:
            raise Fail(f'--also {item}: one DRP per type ({det} is already in the partition)')
        if SIM_TYPES[det].get('frame'):
            raise Fail(f'--also {item}: {det} replays a frame file; run it with --det')
        g = int(group) if group else platform
        if not 0 <= g < 8:
            raise Fail(f'--also {item}: readout group {g} not in 0..7')
        out.append({'det': det, 'group': g, 'alias': f'{det}_0'})
    return out


# Config scripts that take every active DRP on the node for a segment on their board and wait at
# Connect until all of them join their barrier (psdaq/psdaq/configdb/barrier.py supervisor_info:
# "assume non-gpu hosts have only one board"): xpmdet_config (the XpmDetector types, and drp_pva,
# epicsArch, drp_udpencoder and drp_bld, which are XpmDetectors), opal_config, piranha4_config.
BARRIER_TYPES = {'fakecam', 'cspad', 'epixhremu', 'jungfrauemu', 'ts', 'opal', 'piranha4'}


def barrier_conflict(dets, system_drps=False):
    """Why this mix of DRP types cannot connect on one node, or None: a DRP whose config script
    waits at Connect for every DRP on the node to join its barrier, beside one that never does."""
    waits = sorted(d for d in dets if d in BARRIER_TYPES) + (['the system DRPs'] if system_drps else [])
    never = sorted(d for d in dets if d not in BARRIER_TYPES)
    if waits and never:
        return (f'{", ".join(waits)} wait(s) at Connect for every DRP on this node to join their '
                f'barrier (configdb/barrier.py), which {", ".join(never)} never do(es): run them apart')
    return None


FIXED_RATE_LABELS = ('929 kHz', '71.4 kHz', '10.2 kHz', '1.02 kHz', '102 Hz', '10.2 Hz', '1.02 Hz')
FIXED_RATE_DIV = (1, 13, 91, 910, 9100, 91000, 910000)     # simxpm.FIXED_RATE_DIV


def fixed_rate_label(index):
    return FIXED_RATE_LABELS[index] if 0 <= index < len(FIXED_RATE_LABELS) else f'index {index}'


def parse_fixed_rates(items):
    """--fixed-rate GROUP:INDEX values -> {group: index} (pyxpm's L0Select_FixedRate 0..6)."""
    out = {}
    for item in items:
        try:
            g, index = (int(x) for x in item.split(':'))
        except ValueError:
            raise Fail(f'--fixed-rate {item}: GROUP:INDEX, e.g. 5:3 (1.02 kHz)')
        if not (0 <= g < 8 and 0 <= index < len(FIXED_RATE_LABELS)):
            raise Fail(f'--fixed-rate {item}: group 0..7, index 0..6')
        out[g] = index
    return out


EPICS_EPOCH_UNIX = 631152000             # 1990-01-01 in Unix seconds (the witness's times are EPICS-epoch)


def link_full(alias, share):
    """Have the link of DRP `alias` assert full for `share` of every simxpm FULL_PERIOD (simxpm's SIM:LinkFull, a
    sim-only PV): what was put, its link and when (EPICS-epoch seconds), or why not, for the witness."""
    from psdaq.sim.simxpm import NUM_LINKS
    rec = {'pv': f'{PVBASE}:XPM:{XPM}:SIM:LinkFull', 'alias': alias, 'share': share, 'link': None}
    v = pv_get(f'{PVBASE}:XPM:{XPM}:SIM:LinkL1Acc')
    try:                                # a p4p string scalar: its value is in .raw
        rec['link'] = int(json.loads(v.raw['value'] if hasattr(v, 'raw') else str(v))[alias]['link'])
    except (ValueError, TypeError, KeyError) as e:
        rec['error'] = f'no link of {alias} in SIM:LinkL1Acc ({type(e).__name__}: {e})'
        return rec
    rec['value'] = [share if n == rec['link'] else 0. for n in range(NUM_LINKS)]
    rec['on'] = round(time.time() - EPICS_EPOCH_UNIX, 3)
    rec['error'] = pv_put(rec['pv'], rec['value'])
    return rec


def pv_put(name, value, timeout=5.0):
    """Put a PV over PVA; None on success, else the error."""
    from p4p.client.thread import Context
    ctx = Context('pva')
    try:
        ctx.put(name, value, timeout=timeout)
        return None
    except Exception as e:
        return f'{type(e).__name__}: {e}'
    finally:
        ctx.close()


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


def _wait_log(path, text, timeout, proc=None, what=''):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if text in open(path, errors='replace').read():
            return
        if proc is not None and proc.poll() is not None:
            raise Fail(f'{what} exited {proc.returncode} ({path})')
        time.sleep(0.5)
    raise Fail(f'{what} did not say {text!r} in {timeout} s ({path})')


def _wait_control_gui(work, timeout):
    """Wait until control_gui has built its window and polls control (its log's first
    'CGWMain.on_zmq_poll'), so the cycle's transitions start after: a control_gui that builds its
    window once the partition is selected dies at -l DEBUG (QWPopupTableCheck.update_partition_table
    logs logger.debug('list2d\\n', list2d), whose formatting raises TypeError in QWLoggerStd's
    filter)."""
    import glob
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        logs = sorted(glob.glob(work.path('pmlogs', '*', '*', '*:control_gui.log')), key=os.path.getmtime)
        if logs and 'CGWMain.on_zmq_poll' in open(logs[-1], errors='replace').read():
            say(f'control_gui polls control ({logs[-1]})')
            return
        time.sleep(1)
    raise Fail(f'control_gui did not start polling control in {timeout} s (its procmgr log)')


def _wait_pv(name, timeout, proc=None):
    """Wait until a PV answers over PVA (from this node's loopback, sim_env.sh)."""
    end = time.monotonic() + timeout
    while True:
        v = pv_get(name, timeout=2.0)
        if not isinstance(v, str):
            return v
        if (proc is not None and proc.poll() is not None) or time.monotonic() > end:
            raise Fail(f'{name} does not answer over PVA: {v}')
        time.sleep(0.5)


def _wait_ca(name, timeout, proc=None):
    """Wait until a PV answers over CA (from this node's loopback, sim_env.sh)."""
    import epics
    end = time.monotonic() + timeout
    while True:
        v = epics.caget(name, timeout=2.0)
        if v is not None:
            return v
        if (proc is not None and proc.poll() is not None) or time.monotonic() > end:
            raise Fail(f'{name} does not answer over CA')
        time.sleep(0.5)


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


def _remove_meb_files(tag, quiet):
    """Remove the shared memory and message queues the MEB of tag left (XtcMonitorServer does not
    unlink them), once its processes are gone: this user's files with names ending in _<tag> or
    _<tag>_<n>."""
    import glob
    for path in glob.glob(f'/dev/shm/*_{tag}') + glob.glob(f'/dev/mqueue/*_{tag}') + \
            glob.glob(f'/dev/mqueue/*_{tag}_[0-9]*'):
        try:
            if os.stat(path).st_uid == os.getuid():
                os.unlink(path)
                if not quiet:
                    say(f'removed {path}')
        except OSError as e:
            say(f'could not remove {path}: {e}')


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
    for name in ('simhsd', 'simtpr', 'simdti', 'ioc', 'simxpm', 'lgbk', 'configdb'):
        svc = state['services'].get(name)
        if svc:
            _kill(svc['pid'], name, quiet)
    if state.get('meb') and state.get('platform') is not None:
        _remove_meb_files(meb_tag(state['platform']), quiet)
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
        if state.get('ami'):
            check += ami_ports(state['platform'])
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


# What drp_pva and drp_udpencoder count of their PV updates / encoder frames (PvaDetector.cc,
# UdpEncoder.cc exporters), per DRP
PER_DRP_COUNTERS = ('drp_match_count', 'drp_timeout_count', 'drp_miss_count', 'drp_empty_count',
                    'drp_tooOld_count', 'bld_miss_count')
COUNTERS = ('TEB_EvtCt', 'TEB_WrtCt', 'TEB_TrCt', 'MEB_EvtCt', 'MEB_TrCt', 'MEB_ReqCt',
            'DRP_RecordSize', 'drp_num_dma_errors',
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
    ami = AmiRun(state) if state.get('ami') else None
    counts = {}
    for target in STATES[i0 + 1:]:
        if not go(target):
            break
        if target == 'unallocated':
            select_all(dc)
        if target == 'starting' and ami:    # AMI learns its sources from the run (BeginRun)
            ok &= ami.add()
    count = None
    status = dc.getStatus()             # (transition, state, alias, recording, ..., experiment, run, last)
    print(f'{now()} status: transition {status[0]} state {status[1]} recording {status[3]} '
          f'experiment {status[6]} run {status[7]}', flush=True)
    witness = GuiWitness(work, state) if ok and (state.get('gui') or state.get('pvservers')) else None
    shot = None
    if ok and getattr(args, 'ami_shot', None):
        if ami:
            from psdaq.sim import ami_shot
            shot = ami_shot.Shot(work.dir, state, os.path.abspath(args.ami_shot))
        else:
            print(f'{now()} --ami-shot needs a DAQ up with --ami', flush=True)
            ok = False
    if ok and getattr(args, 'kill_drp', False):
        _kill_drp(state, plat)
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
    if witness:                         # Still Running: the GUIs' reads end before Disable
        witness.wait()
    if shot:
        counts['ami shot'] = shot.wait()
        ok &= counts['ami shot'].startswith('PASS')
        ami.served_running = shot.served           # AMI's processes while the viewer showed the run
    prev = None
    cur = dc.getState()                 # Back down, one state at a time, to the start state
    if cur in STATES:
        prev = cur
        for target in reversed(STATES[i0:STATES.index(cur)]):
            if not go(target):
                break
            if prev == 'running' and target == 'paused':
                counts.update(_run_counts(work, plat))
                if ami:
                    ami.fetch(work)
            prev = target
    if count is not None and 'simxpm NumL0Acc' not in counts:
        counts.update(_run_counts(work, plat))      # the way down failed before Disable's counts
    final = dc.getState()
    ok &= final == start
    stop.set()
    mt.join(2)
    dc.context.destroy(0)

    run = status[7] if isinstance(status[7], int) else 0
    if args.record and run:
        counts.update(_psana_counts(work, state, status[6], run))
    if state.get('meb'):
        counts.update(_meb_counts(work, state))
    if (state.get('pva') or state.get('epics') or state.get('udp') or state.get('bld')) and args.record and run:
        counts.update(_sysdrp_counts(work, state, status[6], run, bld=state.get('bld')))
        for proc, key in ((PVA_PROCS[0], 'sysdrp pva with data'), (UDP_PROCS[0], 'sysdrp udp with data')):
            daq = counts.get(f'drp_match_count {proc}')
            if key in counts and daq != counts[key]:     # the DAQ and psana2 agree on each DRP
                counts['system DRP checks'] = (f'FAIL {proc} drp_match_count {daq} != psana2 '
                                               f'{counts[key]} events with its data')
        ok &= counts.get('system DRP checks') == 'PASS'
    if ami:
        counts.update(ami.check(work, status[6], run if args.record else 0))
        ok &= counts.get('ami check') == 'PASS'
    if (state.get('also') or state.get('fixed_rates') or state.get('bld')) and args.record and run:
        counts.update(_per_drp_counts(work, state, status[6], run, counts))
        ok &= counts.get('per-DRP checks') == 'PASS'
    if witness:
        counts.update(witness.check(status[6], run if args.record else 0))
        ok &= counts.get('gui witness') == 'PASS'
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
                            'ok': ok, 'start': start, 'final': final, 'events': args.events,
                            'experiment': status[6], 'run': run}) + '\n')
    errors = [m for m in msgs if m[1] == 'error']
    if errors:
        print(f'{now()} {len(errors)} error message(s) on the status stream', flush=True)
    if ok and not errors and args.record and run:
        _record_cycle_evidence(work, state, status[6], run, counts, started)
    print(f'{now()} cycle {"PASS" if ok and not errors else "FAIL"}', flush=True)
    return 0 if ok and not errors else 1


def _kill_drp(state, plat):
    """cycle --kill-drp, a deliberate break: once the run's first L1Accepts are in, SIGKILL the
    DRP of <det>_0 (as a crash would end it)."""
    pv = f'{PVBASE}:XPM:{XPM}:PART:{plat}:NumL0Acc'
    end, v = time.monotonic() + 30, None
    while time.monotonic() < end:
        v = pv_get(pv)
        if not isinstance(v, str) and int(v) > 0:
            break
        time.sleep(0.05)
    pid, cmd = drp_pid(state, f'{DETECTOR}_0')
    n = v if isinstance(v, str) or v is None else int(v)     # a p4p value prints with its time stamp
    print(f'{now()} --kill-drp: SIGKILL {DETECTOR}_0 pid {pid} at {pv} = {n}: {cmd[:160]}', flush=True)
    if pid:
        os.kill(pid, signal.SIGKILL)


def _record_cycle_evidence(work, state, experiment, run, counts, started, kind='cycle', log='cycle.jsonl'):
    """Evidence for 'daq_sim coverage' from a passing recorded cycle: the rows of the programs
    the generated .cnf started (and its drp's -D type), plus the rows whose stand-in (in
    coverage_status.json) is a service 'up' started, e.g. simxpm for pyxpm.  It lists the run's
    xtc2 files and the logs coverage reads the rows' proof in (each procmgr process's newest
    log and each service's log).  A failure to write it, or a row coverage would reject, is
    reported and leaves the cycle's verdict alone; coverage then finds no valid evidence.
    'daq_sim feature b' records its scan the same way (kind 'scan', its log feature-b.jsonl)."""
    import glob
    try:
        rows = coverage.config_rows(work.path(state['cnf']))
        rows += coverage.stand_in_rows(state.get('services', {}))
        files = sorted(glob.glob(work.path('data', INSTRUMENT, experiment, 'xtc',
                                           f'{experiment}-r{run:04d}-s*-c*.xtc2')))
        files += [work.path(state['cnf']), work.path('logs', log)]
        files += [work.path('logs', w) for w in ('ami_check.json', 'gui_witness.json', 'ami-shot/ami-client.log')
                  if os.path.isfile(work.path('logs', w))]       # the checks' witnesses of the run
        files += [s['log'] for s in state.get('services', {}).values()]
        for proc in procs(state):       # the newest procmgr log of each process
            logs = glob.glob(work.path('pmlogs', '*', '*', f'*:{proc}.log'))
            files += sorted(logs, key=os.path.getmtime)[-1:]
        cache = {}
        path = coverage.record_evidence(rows, kind, files, run_id=f'{experiment}/r{run:04d}',
                                        counts=counts, started=started, cache=cache,
                                        data_dir=work.path('data'))
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
    for g in range(8):                  # every readout group that took L1Accepts
        v = pv_get(f'{PVBASE}:XPM:{XPM}:PART:{g}:NumL0Acc')
        if not isinstance(v, str) and int(v) and g != plat:
            out[f'simxpm NumL0Acc group {g}'] = int(v)
    if out['simxpm NumL0Acc'] is not None:
        out[f'simxpm NumL0Acc group {plat}'] = out['simxpm NumL0Acc']
    v = pv_get(f'{PVBASE}:XPM:{XPM}:SIM:LinkL1Acc')
    try:                                # a p4p string scalar: its value is in .raw
        out['simxpm links'] = json.loads(v.raw['value'] if hasattr(v, 'raw') else str(v))
    except (ValueError, TypeError, KeyError):
        out['simxpm links'] = f'unreadable: {v}'

    for port in prometheus_targets(work.path('prom')):
        for k, val in scrape(port, COUNTERS + PER_DRP_COUNTERS).items():
            name = k.split('{')[0]
            if name in PER_DRP_COUNTERS:    # one per system DRP: keep its alias
                m = re.search(r'alias="([^"]*)"', k)
                name = f'{name} {m.group(1) if m else k}'
            out[name] = int(val)
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
        if os.path.getsize(path) == 0 and path == files[-1]:    # e.g. its DRP died before writing
            return dict(out, **{'psana2 events': 0, 'psana2 with data': 0,
                                'psana2 checks': 'FAIL: the file is empty (0 B)'})
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


class AmiRun:
    """The AMI side of a cycle (up --ami): at BeginRun the check's graph goes to AMI's manager,
    after Disable its result is fetched, and once the run's file is closed psdaq.sim.ami_check
    compares it with psana2, event by event."""

    def __init__(self, state):
        if state.get('ami_src'):
            sys.path.insert(0, state['ami_src'])
        self.addr = f'tcp://127.0.0.1:{state["ports"]["ami"]}'
        self.ports = ami_ports(state['platform'])
        self.result, self.error, self.served, self.served_running = None, None, [], []

    def add(self):
        from psdaq.sim import ami_check
        try:
            took = ami_check.add(self.addr, DETECTOR, timeout=60)
            print(f'{now()} AMI {self.addr}: check graph {"added" if took else "NOT added"}', flush=True)
            return took
        except Exception as e:
            self.error = f'graph not added: {type(e).__name__}: {e}'
            print(f'{now()} AMI {self.addr}: {self.error}', flush=True)
            return False

    def fetch(self, work):
        from psdaq.sim import ami_check
        try:
            time.sleep(1.0)             # a few heartbeats: the last events reach the manager
            self.result = ami_check.fetch(self.addr)
            self.served = ami_check.served_by(self.ports, exclude={os.getpid()})
            with open(work.path('logs', 'ami_check.rows.json'), 'w') as f:
                json.dump(self.result, f)
            print(f'{now()} AMI fetched {len(self.result["rows"])} rows, ami_pixsum '
                  f'{self.result["pixsum"]}', flush=True)
        except Exception as e:
            self.error = f'fetch failed: {type(e).__name__}: {e}'
            print(f'{now()} AMI {self.error}', flush=True)

    def check(self, work, experiment, run):
        """Counts for the cycle: AMI's rows, how many psana2 matched, the verdict."""
        from psdaq.sim import ami_check
        import glob
        if self.error or self.result is None:
            return {'ami check': f'FAIL {self.error or "no result"}'}
        files = sorted(glob.glob(work.path('data', INSTRUMENT, experiment, 'xtc',
                                           f'{experiment}-r{run:04d}-s*-c000.xtc2'))) if run else []
        if not files:
            return {'ami rows': len(self.result['rows']), 'ami check': 'FAIL no recorded xtc2 file '
                    'to compare with (cycle without --no-record)'}
        res = ami_check.check(self.result, files, DETECTOR)
        with open(work.path('logs', 'ami_check.json'), 'w') as f:      # the witness coverage reads
            served = [dict(p, when='fetch') for p in self.served] + \
                     [dict(p, when='running') for p in self.served_running]
            json.dump(dict(res, witness='ami_check', run_id=f'{experiment}/r{run:04d}', xtc2=files,
                           addr=self.addr, served_by=served), f, indent=1)
        out = {k: res[k] for k in ('ami rows', 'ami events', 'ami matched', 'ami pixsum',
                                   'psana2 pixsum (same events)', 'ami seq range')}
        out['ami served by'] = ' '.join(sorted({coverage.resolve(a['cmdline'])[0] or '?' for p in served
                                                 for a in [p] + p['ancestors'][:1]}))
        out['ami check'] = 'PASS' if res['pass'] else f'FAIL {res["problems"][:3]}'
        return out


def _per_drp_counts(work, state, experiment, run, counts, xtcdir=None):
    """Each PGP DRP's and drp_bld's L1Accepts: what simxpm sent its link (SIM:LinkL1Acc, read
    after Disable) against what psana2 reads from its own stream, event by event
    (xtc2_check for the --det and --also types, sysdrp_check --bld); and, with --fixed-rate,
    each readout group's L1Accept count (simxpm NumL0Acc): groups at different rates differ."""
    from psdaq.sim import xtc2_check
    import glob
    links = counts.get('simxpm links')
    links = links if isinstance(links, dict) else {}
    files = sorted(glob.glob(os.path.join(xtcdir or work.path('data', INSTRUMENT, experiment, 'xtc'),
                                          f'{experiment}-r{run:04d}-s*-c000.xtc2')))
    out, problems = {}, []
    pgp = [(f'{DETECTOR}_{i}', state['platform']) for i in range(state.get('segments', 1))] + \
          [(a['alias'], a['group']) for a in state.get('also', ())]
    for alias, group in pgp:
        res = None
        for path in files:              # its stream: the file in which it has data (psana2 names
            try:                        # the detector by its alias less the segment)
                r = xtc2_check.check(path, alias.rsplit('_', 1)[0], state['seed'])
            except Exception:
                continue
            if r.get('with_data'):
                res = r
                break
        daq = (links.get(alias) or {}).get('l1acc')
        if res is None:
            out[f'drp {alias}'] = f'group {group}: DAQ {daq}, psana2: no stream with its data'
            problems.append(f'{alias}: no stream')
            continue
        good = res['pass'] and daq == res['events'] == res['with_data']
        out[f'drp {alias}'] = (f'group {group}: DAQ (simxpm L1Accepts sent) {daq} psana2 events '
                               f'{res["events"]} with data {res["with_data"]} per-event check '
                               f'{"PASS" if res["pass"] else "FAIL " + str(res["problems"][:2])} '
                               f'({os.path.basename(res["file"])})')
        if not good:
            problems.append(f'{alias}: DAQ {daq} psana2 {res["events"]}/{res["with_data"]} '
                            f'check {res["pass"]}')
    for alias, key, on in ((PVA_PROCS[0], 'pva', state.get('pva')), (UDP_PROCS[0], 'udp', state.get('udp')),
                           (EPICS_PROCS[0], 'epics', state.get('epics')), (BLD_PROCS[0], 'bld', state.get('bld'))):
        if not on:                      # each system DRP's stream holds every L1Accept it was sent
            continue
        daq, got = (links.get(alias) or {}).get('l1acc'), counts.get(f'sysdrp {key} events')
        out[f'drp {alias}'] = f'group {state["platform"]}: DAQ (simxpm L1Accepts sent) {daq} psana2 events {got}'
        if daq is None or daq != got:
            problems.append(f'{alias}: DAQ {daq} psana2 {got}')
    if state.get('bld'):                # sysdrp_check --bld ran in the cycle (_sysdrp_counts)
        daq = (links.get(BLD_PROCS[0]) or {}).get('l1acc')
        missed = counts.get(f'bld_miss_count {BLD_PROCS[0]}')
        got, problem = counts.get('sysdrp bld with data'), counts.get('sysdrp bld problems', 0)
        out[f'bld {BLD_PROCS[0]} data'] = (f'DAQ (simxpm L1Accepts sent) {daq} - '
                                      f'bld_miss_count {missed} = '
                                      f'{None if daq is None or missed is None else daq - missed}; psana2 '
                                      f'{BLD_NAME} events {counts.get("sysdrp bld events")} with data {got}, '
                                      f'{problem} with a wrong value')
        if daq is None or missed is None or daq - missed != got or not got or problem:
            problems.append(f'bld: DAQ {daq} - {missed} vs psana2 {got}, {problem} wrong')
    fixed = {int(g): i for g, i in (state.get('fixed_rates') or {}).items()}
    if fixed:
        per_group = {g: counts.get(f'simxpm NumL0Acc group {g}') for g in sorted(fixed)}
        out['readout groups'] = ', '.join(f'group {g} at {fixed_rate_label(i)}: {per_group[g]} L1Accepts'
                                          for g, i in sorted(fixed.items()))
        # each group's count against the fastest group's: their markers' ratio (nested markers:
        # a group k times slower took every k-th L1Accept), within 10 %
        fast = min(fixed, key=lambda g: (fixed[g], g))
        for g, i in sorted(fixed.items()):
            ratio = FIXED_RATE_DIV[i] / FIXED_RATE_DIV[fixed[fast]]
            n, n0 = per_group[g], per_group[fast]
            if not (n and n0 and abs(n0 / n - ratio) <= 0.1 * ratio):
                problems.append(f'group {g}: {n} L1Accepts against group {fast}\'s {n0}, not 1/{ratio:g} '
                                f'({fixed_rate_label(i)} vs {fixed_rate_label(fixed[fast])})')
    out['per-DRP checks'] = 'PASS' if not problems else f'FAIL {problems[:3]}'
    return out


class GuiWitness:
    """The GUI side of a cycle (up --gui): once the run is Running, each GUI of
    psdaq.sim.gui_witness.WITNESS runs once more offscreen against the partition, its reads are
    kept, and after the run they become logs/gui_witness.json, the witness coverage reads."""

    def __init__(self, work, state):
        from psdaq.sim import gui_witness
        import urllib.request                   # what the threads below use, imported in this thread: an
        from p4p.client.thread import Context   # import in a thread racing one here can deadlock
        self.gw, self.work, self.state = gui_witness, work, state
        self.params = gui_params(state['platform'], work.path('prom'), work.path(state['cnf']))
        env = dict(os.environ, **{TAG: work.dir})
        self.walks, self.monitors, self.servers = {}, {}, {}
        for name in gui_witness.SERVERS:                # R3 stand-ins: read in a thread while Running
            if name in state.get('services', {}):
                res = self.servers[name] = {}
                port = state['ports']['pvservers'][name][1]
                try:
                    prepared = gui_witness.server_prepare(name, self.params, port)   # imports: in this thread
                except Exception as ex:
                    prepared, res['entry'] = None, {'pass': False, 'problems': [f'{type(ex).__name__}: {ex}']}

                def read(res=res, name=name, port=port, prepared=prepared):
                    if prepared is None:
                        return
                    try:
                        res['entry'] = gui_witness.server_entry(name, self.params, port, gui_witness.PUMPS + 4,
                                                                prepared=prepared)
                    except Exception as ex:
                        res['entry'] = {'pass': False, 'problems': [f'{type(ex).__name__}: {ex}']}
                res['thread'] = threading.Thread(target=read, daemon=True)
                res['thread'].start()
                print(f'{now()} GUI witness: reading {name}\'s PVs', flush=True)
        for name in gui_witness.PROGRAM_SERVERS:        # the tree's own PV servers: read in a thread while Running
            if name in procs(state):
                res = self.servers[name] = {}
                port = state['ports']['pvservers'][name][1]
                try:
                    prepared = gui_witness.program_server_prepare(name, self.params, port)
                except Exception as ex:
                    prepared, res['entry'] = None, {'pass': False, 'problems': [f'{type(ex).__name__}: {ex}']}

                def pread(res=res, name=name, port=port, prepared=prepared):
                    if prepared is None:
                        return
                    try:
                        res['entry'] = gui_witness.program_server_entry(name, self.params, port, gui_witness.PUMPS + 4,
                                                                        prepared=prepared)
                    except Exception as ex:
                        res['entry'] = {'pass': False, 'problems': [f'{type(ex).__name__}: {ex}']}
                res['thread'] = threading.Thread(target=pread, daemon=True)
                res['thread'].start()
                print(f'{now()} GUI witness: reading {name}\'s PVs (its own server)', flush=True)
        for name in gui_witness.WITNESS:
            if name in procs(state):
                server = gui_witness.WITNESS[name].get('server')     # R4: search only the stand-in's ports
                wenv = dict(env, **gui_witness.pva_env(state['ports']['pvservers'][server][1])) \
                    if server in state['ports'].get('pvservers', {}) else env
                self.walks[name] = list(gui_witness.start(work.dir, name, work.path('logs', 'witness'), wenv)) + [None]
                print(f'{now()} GUI witness: {name} walking offscreen (pid {self.walks[name][0].pid})', flush=True)
        self.stimulus = None            # deadca: a DRP's link asserts full part of the time while the walks run
        alias = gui_witness.WITNESS.get('deadca', {}).get('link_full')
        if 'deadca' in self.walks and alias:
            self.stimulus = link_full(alias, gui_witness.LINK_FULL)
            print(f'{now()} GUI witness: {alias}\'s link asserts full {gui_witness.LINK_FULL} of the time '
                  f'(simxpm SIM:LinkFull): {self.stimulus}', flush=True)
        self.slurm = None
        if 'daqstat' in self.walks:     # R5: squeue read from simslurm by this process, apart from daqstat's walk
            import json as _json
            st = work.path(SLURM_DIR, 'state.json')
            try:
                with open(st) as f:
                    prefix = _json.load(f).get('prefix')
            except (OSError, ValueError):
                prefix = None
            self.slurm = {'prefix': prefix, 'reads': [], 'stop': threading.Event()}

            def squeue(res=self.slurm, st=st):
                while not res['stop'].wait(0.5):
                    try:
                        res['reads'].append(gui_witness.squeue_read(st))
                    except Exception as ex:
                        res.setdefault('errors', []).append(f'{type(ex).__name__}: {ex}')
            self.slurm['thread'] = threading.Thread(target=squeue, daemon=True)
            self.slurm['thread'].start()
            print(f'{now()} GUI witness: reading squeue from simslurm every 0.5 s', flush=True)
        for name, m in gui_witness.MONITORS.items():    # scraped in a thread, as long as the walks take
            if m['id'] in procs(state):
                import glob
                logs = sorted(glob.glob(work.path('pmlogs', '*', '*', f'*:{m["id"]}.log')), key=os.path.getmtime)
                port = gui_witness.exporter_port(logs[-1]) if logs else None
                res = self.monitors[name] = {'port': port}
                names, xpm_prefix = m['argv'][8:], f'{PVBASE}:XPM:{XPM}'

                def scrape(res=res, port=port, names=names, xpm_prefix=xpm_prefix):
                    if port is None:
                        res.update(t0=time.time(), t1=time.time(), reads=[])
                        return
                    res['t0'], res['t1'], res['reads'] = gui_witness.scrape_reads(
                        port, names, xpm_prefix, gui_witness.PUMPS + 4)
                res['thread'] = threading.Thread(target=scrape, daemon=True)
                res['thread'].start()
                print(f'{now()} GUI witness: {name} scraped on port {port}', flush=True)

    def wait(self, timeout=120):
        """Wait for the walks (each one's end is the time its exit was seen, polled every 0.1 s) and the
        reader threads, then 1 s more: the run keeps taking L1Accepts past every read."""
        end = time.monotonic() + timeout
        while any(w[4] is None for w in self.walks.values()):
            for name, w in self.walks.items():
                p = w[0]
                if w[4] is None and (p.poll() is not None or time.monotonic() > end):
                    if p.poll() is None:
                        p.kill()
                        p.wait(10)
                    w[4] = time.time()
                    print(f'{now()} GUI witness: {name} walk exit {p.returncode}', flush=True)
            time.sleep(0.1)
        for name, res in list(self.monitors.items()) + list(self.servers.items()):
            res['thread'].join(max(1, end - time.monotonic()))
        if self.stimulus and self.stimulus.get('link') is not None:     # the link is full no more
            err = pv_put(self.stimulus['pv'], [0.] * len(self.stimulus['value']))
            self.stimulus.update(off=round(time.time() - EPICS_EPOCH_UNIX, 3), off_error=err)
            print(f'{now()} GUI witness: SIM:LinkFull back to 0{f" FAILED: {err}" if err else ""}', flush=True)
        time.sleep(1.0)
        if self.slurm:
            self.slurm['stop'].set()
            self.slurm['thread'].join(5)

    def check(self, experiment, run):
        import glob
        files = sorted(glob.glob(self.work.path('data', INSTRUMENT, experiment, 'xtc',
                                                f'{experiment}-r{run:04d}-s*-c*.xtc2'))) if run else []
        prefix = self.params['part']
        programs = {name: self.gw.entry(name, walk, p.returncode, t0, t1, prefix, self.params,
                                        slurm=self.slurm if name == 'daqstat' else None)
                    for name, (p, walk, log, t0, t1) in self.walks.items()}
        for name, res in self.monitors.items():
            programs[name] = self.gw.monitor_entry(name, res['port'], res.get('t0', 0), res.get('t1', 0),
                                                   res.get('reads', []), prefix, self.params)
        servers = {name: res.get('entry') or {'pass': False, 'problems': ['no result']}
                   for name, res in self.servers.items()}
        if 'deadca' in programs:
            programs['deadca']['stimulus'] = self.stimulus
        w = self.gw.witness(f'{experiment}/r{run:04d}', files, prefix, programs, servers)
        with open(self.work.path('logs', 'gui_witness.json'), 'w') as f:
            json.dump(w, f, indent=1)
        bad = [f'{n}: {e["problems"][:2]}' for n, e in list(programs.items()) + list(servers.items()) if not e['pass']]
        if not files:
            bad.append('no recorded xtc2 file (cycle without --no-record)')
        def shown(e):                   # an R4 entry has a read per widget: show two that changed
            rs = [r for r in e['reads'] if r['name'] in e['live'][:2]]
            if e.get('stand_in'):
                rs = [r for r in rs if len(coverage.changed_texts(r['values'])) >= 2][:2]
            return ', '.join(f'{r["name"].rsplit(":", 1)[-1]} {r["values"][:1] + r["values"][-1:]}' for r in rs) or 'none'
        out = {f'gui witness {n}': (f'{len(e["live"])} refreshes as squeue said, of {len(e.get("refreshes", []))}; '
                                    f'{len(e.get("squeue", []))} squeue reads' if e.get('kind') == 'slurm' else
                                    f'{len(e["live"])} live PVs' + (f' of {e["stand_in"]}' if e.get('stand_in') else '') +
                                    ', e.g. ' + shown(e))
               for n, e in programs.items()}
        out.update({f'pv server {n}': f'{len(e.get("live", []))} live PVs; ' + ', '.join(
            f'{p} {i["served"]}/{i["defined"]} PVs served' for p, i in e.get('interfaces', {}).items())
            for n, e in servers.items()})
        out['gui witness'] = 'PASS' if not bad else f'FAIL {bad[:3]}'
        return out


def _sysdrp_counts(work, state, experiment, run, bld=False):
    """psana2 over every stream of the run: what drp_pva and epicsArch recorded
    (psdaq.sim.sysdrp_check)."""
    argv = [sys.executable, '-m', 'psdaq.sim.sysdrp_check', '--dir',
            work.path('data', INSTRUMENT, experiment, 'xtc'), '--exp', experiment, '--run', str(run),
            '--seed', str(state['seed']), '--det', DETECTOR]
    if state.get('pva'):
        argv += ['--pva', PVA_PROCS[0].rsplit('_', 1)[0]]
    if state.get('epics'):
        argv += ['--epics']
    if state.get('udp'):
        argv += ['--udp', UDP_PROCS[0].rsplit('_', 1)[0]]
    if bld:
        argv += ['--bld', BLD_NAME]
    r = subprocess.run(argv, capture_output=True, text=True, timeout=900)
    try:
        res = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {'system DRP checks': f'FAIL sysdrp_check: {r.stderr.strip()[-300:]}'}
    out = {f'sysdrp {k}': v for k, v in res.items() if k not in ('problems', 'pass')}
    out['system DRP checks'] = 'PASS' if res['pass'] else f'FAIL {res["problems"][:3]}'
    return out


def _meb_counts(work, state):
    """The MEB's served-event count is MEB_EvtCt (Prometheus, read after Disable in _run_counts);
    this adds what shmemClient (-v, one line per datagram) printed from its queue."""
    import glob
    logs = sorted(glob.glob(work.path('pmlogs', '*', '*', '*:shmc0.log')), key=os.path.getmtime)
    if not logs:
        return {'shmemClient L1Accepts': 'no log'}
    with open(logs[-1], errors='replace') as f:
        text = f.read()
    return {'shmemClient L1Accepts': len(re.findall(r'^L1Accept\s+transition: time', text, re.M)),
            'shmemClient BeginRun': len(re.findall(r'^BeginRun\s+transition: time', text, re.M))}


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


# --- two nodes (plan only) -----------------------------------------------------------------

def multi_host_plan(host_a, host_b, platform=5, also=(), workdir='daq_sim_work', addr=None, nic='eth0'):
    """One partition over two nodes: control, the TEB, simxpm and the stand-ins on host_a, the
    --also DRPs on host_b (procmgr's host:), the --det DRP on host_a.  Returns {cnf, env,
    endpoints, needs}.  Every endpoint is one of the two nodes (addr: {host: IP}); nothing listens
    on loopback only, since the other node must reach it, and nothing else is addressed."""
    addr = addr or {}
    ip_a, ip_b = addr.get(host_a, host_a), addr.get(host_b, host_b)
    P = ports(platform)
    ep = f'ep_domain={nic},ep_provider=tcp'           # libfabric tcp over the nodes' NIC
    data = os.path.join(workdir, 'data')
    prom = os.path.join(workdir, 'prom')
    cfg = f'http://{ip_a}:{P["configdb"]}/ws/'
    lines = [f'# daq_sim up --hosts {host_a},{host_b} --dry-run: one partition over two nodes',
             f"if not platform: platform = '{platform}'",
             'procmgr_config = [',
             f" {{ host:'{host_a}', id:'control', flags:'spu', cmd:'control -v -C {CONFIG_ALIAS} -P {INSTRUMENT}"
             f" -x {XPM} -B {PVBASE} -X {ip_a} -t {TRIGGER} -S 1 -d {cfg}configDB --url http://{ip_a}:{P['lgbk']}/"
             f" -r {os.path.join(workdir, 'activedet.json')} -V /dev/null' }},",
             f" {{ host:'{host_a}', id:'teb0', flags:'spu', cmd:'teb -P {INSTRUMENT} -C {host_a} -k {ep} -M {prom}' }},",
             f" {{ host:'{host_a}', id:'{DETECTOR}_0', flags:'spu', cmd:'drp -P {INSTRUMENT} -C {host_a} -D {DETECTOR}"
             f" -d sim://{ip_a}:{P['frames']} -l 0x1 -o {data} -k {ep},{SIM_TYPES[DETECTOR]['kwargs'].format(length=64, seed=0x1234, work=workdir)} -M {prom}' }},"]
    for a in also:
        k = SIM_TYPES[a['det']]['kwargs'].format(length=64, seed=0x1234, work=workdir)
        lines.append(f" {{ host:'{host_b}', id:'{a['alias']}', flags:'spu', cmd:'drp -P {INSTRUMENT} -C {host_a}"
                     f" -D {a['det']} -d sim://{ip_a}:{P['frames']} -l 0x1 -o {data} -k {ep},{k} -M {prom}' }},")
    lines.append(']')
    env = {'EPICS_PVA_AUTO_ADDR_LIST': 'NO', 'EPICS_PVA_ADDR_LIST': f'{ip_a} {ip_b}',
           'EPICS_CA_AUTO_ADDR_LIST': 'NO', 'EPICS_CA_ADDR_LIST': f'{ip_a} {ip_b}',
           'EPICS_PVAS_INTF_ADDR_LIST': ip_a}
    endpoints = {'simxpm frames': f'tcp://{ip_a}:{P["frames"]} (simxpm --frames, --allow-remote)',
                 'simxpm PVA': f'{ip_a}:{os.environ.get("EPICS_PVA_SERVER_PORT", "15075")} (simxpm --bind {ip_a})',
                 'control -X': f'tcp://{ip_a}:{pull_port()} (simxpm --pull)',
                 'config DB': cfg, 'run DB': f'http://{ip_a}:{P["lgbk"]}/',
                 'control ZMQ': f'{host_a}:{control_ports(platform)[0]}-{control_ports(platform)[-1]}',
                 'TEB/DRP libfabric': f'{ep} on {ip_a} and {ip_b}'}
    needs = [f"procmgr starts {host_b}'s processes through procServ on {host_b}: procmgrd/procServ "
             f"reachable from {host_a} (ssh between the nodes, or the procServ started in a Slurm step "
             f"on {host_b} of the job that holds it)",
             'configdb_server and lgbk_server bound to the node address instead of 127.0.0.1, and simxpm '
             '--bind/--frames/--pull on it with --allow-remote',
             'preflight.sh: the EPICS address lists above (two nodes), not loopback only',
             f"the nodes' NIC ({nic}) for libfabric tcp, and the DRP on {host_b} writing to a file "
             "system both nodes share (data under the work dir)"]
    return {'cnf': '\n'.join(lines) + '\n', 'env': env, 'endpoints': endpoints, 'needs': needs}


def cmd_plan(args):
    """up --hosts A,B --dry-run: print the two-node plan; start nothing."""
    hosts = (args.hosts or '').split(',')
    if len(hosts) != 2 or not all(hosts) or hosts[0] == hosts[1]:
        raise Fail('--hosts HOST_A,HOST_B: two different nodes')
    if not args.dry_run:
        raise Fail('--hosts is a plan only for now: add --dry-run (RUNBOOK: two nodes)')
    for h in hosts:
        short = h.split('.')[0]
        if re.match(r'(drp|daq|mon|ctl|ioc)-', short):
            raise Fail(f'refusing {h}: it looks like a hutch or DAQ host')
    use_det(args.det)
    also = parse_also(args.also or [], args.platform)
    plan = multi_host_plan(hosts[0], hosts[1], args.platform, also, os.path.abspath(args.workdir))
    print('# .cnf')
    print(plan['cnf'], end='')
    print('# environment (both nodes)')
    for k, v in plan['env'].items():
        print(f'export {k}="{v}"')
    print('# endpoints')
    for k, v in plan['endpoints'].items():
        print(f'#   {k:<18} {v}')
    print('# not done yet (needed to run it)')
    for n in plan['needs']:
        print(f'#   - {n}')
    return 0


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
    upopts.add_argument('--meb', action='store_true',
                        help='also run the MEB (monReqServer meb0) and a shmemClient (shmc0) reading it')
    upopts.add_argument('--ami', action='store_true',
                        help='also run AMI on the MEB (implies --meb): ami-manager, ami-global, ami-node, '
                             'ami-worker (psana://shmem=<tag>) and ami-client (offscreen), all on 127.0.0.1; '
                             'cycle then checks what AMI computed against psana2 (psdaq.sim.ami_check)')
    upopts.add_argument('--ami-src', default=None,
                        help='AMI source tree for --ami (default $DAQ_SIM_AMI_SRC; else ami-* from PATH)')
    upopts.add_argument('--pva', action='store_true',
                        help=f'also run drp_pva (pvcam_0) on simxpm\'s camera PV {CAMERA_PV}, one update per L1Accept')
    upopts.add_argument('--epics', action='store_true',
                        help='also run epicsArch (epics_0) on two CA PVs of a stand-in IOC (softIoc, loopback) '
                             'and a PVA PV of simxpm')
    upopts.add_argument('--udp', action='store_true',
                        help='also run drp_udpencoder (encoder_0) on the encoder frames sim_udpencoder sends on '
                             'loopback UDP, paced by simxpm (sim_udpencoder -T sim://)')
    upopts.add_argument('--also', action='append', metavar='TYPE[:GROUP]',
                        help='one more DRP <TYPE>_0 of another simulated type, in readout group GROUP '
                             '(default: the platform); repeatable')
    upopts.add_argument('--fixed-rate', action='append', metavar='GROUP:INDEX',
                        help="readout group GROUP's L1Accepts on pyxpm's fixed-rate marker INDEX (3: "
                             '1.02 kHz, 4: 102 Hz, 5: 10.2 Hz, 6: 1.02 Hz; simxpm --fixed-rates); repeatable')
    upopts.add_argument('--bld', action='store_true',
                        help=f'also run drp_bld (bld_0) on simxpm\'s BLD source {BLD_PREFIX} (multicast on '
                             '127.0.0.1, TTL 1), its group and port from the stand-in IOC (CA)')
    upopts.add_argument('--hosts', default=None, metavar='HOST_A,HOST_B',
                        help='with --dry-run: plan one partition over two nodes (control, the TEB and '
                             'stand-ins on HOST_A, the --also DRPs on HOST_B)')
    upopts.add_argument('--dry-run', action='store_true', help='print the plan (.cnf, environment); start nothing')
    upopts.add_argument('--gui', action='store_true',
                        help='also run the PyQt GUIs control_gui, groupca, partca, pvant and procstat and the '
                             'monitor epics_exporter, offscreen, as the configs start them (with --pvservers also '
                             'hsdpva, tprca, dtica, pvatable, xpmpva and deadca on the stand-ins); cycle then runs each GUI '
                             'once more while Running and checks it shows live values (psdaq.sim.gui_witness; for '
                             'deadca the first DRP\'s link asserts full part of the time meanwhile)')
    upopts.add_argument('--pvservers', action='store_true',
                        help='also run the PV-server stand-ins simhsd (for hsdpvs), simtpr (for tprcas) and simdti '
                             '(for dticas), each on PVA ports of its own; cycle reads their PVs while Running '
                             '(psdaq.sim.gui_witness)')
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
    cy.add_argument('--kill-drp', action='store_true',
                    help=f'a deliberate break: SIGKILL the DRP of <det>_0 once the run\'s first L1Accepts are in '
                         '(daq_sim matrix --break kill-drp)')
    cy.add_argument('--ami-shot', metavar='PNG', default=None,
                    help='(up --ami) while Running, open a viewer of the camera image in another ami-client, '
                         'offscreen, and save its window to PNG (psdaq.sim.ami_shot)')
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
    from psdaq.sim import matrix
    matrix.add_arguments(sub.add_parser('matrix', parents=[common], help='the whole hardware-free matrix, '
                                        'unattended: every detector type, the features, coverage '
                                        '(psdaq.sim.matrix)'))
    from psdaq.sim import feature
    feature.add_arguments(sub.add_parser('feature', parents=[common], help='run one system feature '
                                         'end to end with its checks (psdaq.sim.feature)'))
    args = parser.parse_args(argv)
    if args.command == 'coverage':      # reads the checkout only: no DAQ env needed
        return coverage.run(args)
    if args.command == 'matrix':        # the DAQ env only for the sections that run a DAQ
        try:
            return matrix.cmd_matrix(args, argv)
        except Fail as e:
            print(f'daq_sim matrix: {e}', file=sys.stderr, flush=True)
            return 1
    if args.command == 'up' and (args.dry_run or args.hosts):
        try:                            # a plan only: no DAQ env needed
            return cmd_plan(args)
        except Fail as e:
            print(f'daq_sim up: {e}', file=sys.stderr, flush=True)
            return 1
    ensure_env(argv)
    try:
        old = Work(args.workdir).load() or {}
        use_det(getattr(args, 'det', None) or old.get('det') or 'fakecam')
        if args.command == 'e2e':
            from psdaq.webgui.e2e import cmd_e2e
            return cmd_e2e(args)
        if args.command == 'feature':
            return feature.cmd_feature(args)
        return {'up': cmd_up, 'down': cmd_down, 'status': cmd_status, 'cycle': cmd_cycle}[args.command](args)
    except Fail as e:
        print(f'daq_sim {args.command}: {e}', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    # Run main() from the importable module, not from __main__: psdaq.webgui.e2e imports
    # psdaq.sim.daq_sim, and its Fail must be the class main() catches (else a traceback).
    from psdaq.sim import daq_sim
    sys.exit(daq_sim.main())
