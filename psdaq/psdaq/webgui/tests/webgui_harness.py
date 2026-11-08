"""Shared helpers for the web GUI tests: start/stop the server as a subprocess, on the emulator or on the
simulated DAQ, and say which one each server talked to.

Environment:
  WEBGUI_PYTHON       interpreter for the server (default: this one). run_webgui_tests.sh sets the DAQ env's.
  WEBGUI_SERVER_ARGS  extra server arguments for every started server, e.g. "--emulate-fail enable"
                      (used to prove the tests fail when a transition fails).
  WEBGUI_SHOTS        directory for screenshots (default: a temp dir).
  WEBGUI_SIM_DAQ      work dir of a running `daq_sim up` (psdaq.sim.daq_sim; on this node, best with
                      --segments 2): the parity tests' server (daq_server) then runs with the real DaqControl
                      backend against that simulated DAQ (its control, its config DB stand-in, simxpm's L1
                      counter over PVA) instead of --emulate.  Source psdaq/psdaq/sim/sim_env.sh first.

Backend of every server a test drives: start() asks the server itself (GET /api/meta) and, for the real
DaqControl backend, checks that its control endpoint and config DB are those of the running daq_sim of
WEBGUI_SIM_DAQ (control process alive): 'sim-daq'; 'emulator' for --emulate; 'daqcontrol' for any other
DAQ.  Each detection is appended to STARTED; conftest.py records the backends a test drove as junit
`backend` properties, which check_parity requires to be sim-daq for a mapped row.
"""

import json
import os
import pathlib
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

# .../psdaq/webgui/tests/this.py -> parents[3] is the directory that contains the psdaq package
PKG_ROOT = pathlib.Path(__file__).resolve().parents[3]
SERVER_PYTHON = os.environ.get('WEBGUI_PYTHON') or sys.executable
SHOTS = pathlib.Path(os.environ.get('WEBGUI_SHOTS') or tempfile.mkdtemp(prefix='webgui-shots-'))
SIM_DAQ_DIR = os.environ.get('WEBGUI_SIM_DAQ') or None
UI_TIMEOUT = 60000 if SIM_DAQ_DIR else 15000     # ms, per UI expectation (real transitions take seconds)
STARTED = []        # one dict per server a test drove: {'url', 'backend', 'why'} (conftest records the backends)

# never let a test request go through a proxy
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def server_env():
    env = dict(os.environ)
    env['PYTHONPATH'] = str(PKG_ROOT) + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
        env[k] = 'http://127.0.0.1:9'   # dead proxy: anything that tried one would fail loudly
    env['NO_PROXY'] = env['no_proxy'] = 'localhost,127.0.0.1'
    return env


class ServerProc:
    def __init__(self, args, prefix=None):
        self.cmd = list(prefix or []) + [SERVER_PYTHON, '-m', 'psdaq.webgui.server', '--port', '0'] + list(args)
        self.cmd += shlex.split(os.environ.get('WEBGUI_SERVER_ARGS', ''))
        self.lines = []
        self.url = None

    def start(self, timeout=60):
        self.p = subprocess.Popen(self.cmd, env=server_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, bufsize=1)
        got = threading.Event()

        def reader():
            for line in self.p.stdout:
                self.lines.append(line.rstrip('\n'))
                if self.url is None and 'listening on http://' in line:
                    self.url = line.split('listening on ', 1)[1].split()[0]
                    got.set()
            got.set()
        threading.Thread(target=reader, daemon=True).start()
        if not got.wait(timeout) or self.url is None:
            self.stop()
            raise RuntimeError('server did not start: %s\n%s' % (self.cmd, '\n'.join(self.lines[-30:])))
        self.backend, self.backend_why = detect_backend(self.get('/api/meta'))
        self.started_entry = {'url': self.url, 'backend': self.backend, 'why': self.backend_why}
        STARTED.append(self.started_entry)
        return self

    def stop(self):
        if self.p.poll() is None:
            self.p.terminate()
            try:
                self.p.wait(10)
            except subprocess.TimeoutExpired:
                self.p.kill()
                self.p.wait(5)
        return self.p.returncode

    # tiny HTTP client (no proxy)
    def get(self, path):
        with _OPENER.open(self.url.rstrip('/') + path, timeout=10) as r:
            return json.loads(r.read())

    def post(self, path, body):
        req = urllib.request.Request(self.url.rstrip('/') + path, data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json'}, method='POST')
        with _OPENER.open(req, timeout=30) as r:
            return json.loads(r.read())

    def wait_state(self, state, timeout=15):
        t0 = time.time()
        while time.time() - t0 < timeout:
            st = self.get('/api/status')
            if st['state'] == state:
                return st
            time.sleep(0.1)
        raise AssertionError('server state %r, expected %r' % (self.get('/api/status')['state'], state))


# ---------------- which backend a server talks to ----------------

def detect_backend(meta):
    """(backend, why) from the server's /api/meta: 'emulator' | 'sim-daq' | 'daqcontrol' | 'unknown:<name>'."""
    name = meta.get('backend')
    if name == 'emulator':
        return 'emulator', 'server backend emulator (--emulate)'
    if name != 'daqcontrol':
        return 'unknown:%s' % name, 'server backend %r' % name
    sim = sim_daq()
    if sim is None:
        return 'daqcontrol', 'real DaqControl backend; WEBGUI_SIM_DAQ not set, so not known to be the simulated DAQ'
    ok, why = sim.matches(meta.get('endpoints') or {})
    return ('sim-daq' if ok else 'daqcontrol'), why


_SIM = {}


def sim_daq():
    """The SimDaq of WEBGUI_SIM_DAQ, or None."""
    if not SIM_DAQ_DIR:
        return None
    if 'sim' not in _SIM:
        _SIM['sim'] = SimDaq(SIM_DAQ_DIR)
    return _SIM['sim']


class SimDaq:
    """A running `daq_sim up` (psdaq.sim.daq_sim) on this node, read from its work dir's state file."""

    def __init__(self, workdir):
        from psdaq.sim import daq_sim as ds          # stdlib only at import time
        self.ds = ds
        self.work = ds.Work(workdir)
        st = self.work.load()
        if st is None:
            raise RuntimeError('WEBGUI_SIM_DAQ=%s: no daq_sim state file (%s)' % (workdir, self.work.state_path))
        self.platform = st['platform']
        self.configdb_url = 'http://127.0.0.1:%d/ws/' % st['ports']['configdb']
        self.cfg_dbase = self.configdb_url + 'configDB'
        self.instrument = ds.INSTRUMENT
        self.alias = ds.CONFIG_ALIAS
        self.snapshot = None

    @property
    def url(self):                    # what the config editor tests' cfgdb.url is in emulator mode
        return self.configdb_url

    def alive(self):
        """(bool, why): the state file says up, and every DAQ process procmgr started runs."""
        st = self.work.load()
        if not st or st.get('down') or not st.get('procs'):
            return False, 'daq_sim in %s is not up (state %s)' % (self.work.dir, st and st.get('down'))
        dead = [k for k, pid in st['procs'].items() if not self.ds.pid_alive(pid)]
        if dead:
            return False, 'daq_sim processes not running: %s' % dead
        return True, 'daq_sim %s up on %s (job %s), procs %s' % (self.work.dir, st.get('host'),
                                                               (st.get('slurm') or {}).get('SLURM_JOB_ID'),
                                                               sorted(st['procs']))

    def procs(self):
        """procmgr ids daq_sim up started (control, teb0, fakecam_0 .. fakecam_<segments-1>)."""
        return self.ds.procs(self.work.load())

    def matches(self, endpoints):
        ok, why = self.alive()
        if not ok:
            return False, why
        ports = set(self.ds.control_ports(self.platform))
        ep = endpoints.get('front_rep', '')
        host, _, port = ep.rpartition(':')
        if host not in ('tcp://127.0.0.1', 'tcp://localhost') or not port.isdigit() or int(port) not in ports:
            return False, 'control endpoint %s is not platform %d of %s' % (ep, self.platform, why)
        cdb = endpoints.get('configdb')
        if cdb is not None and cdb.rstrip('/') != self.configdb_url.rstrip('/'):
            return False, 'config DB %s is not the daq_sim stand-in %s' % (cdb, self.configdb_url)
        return True, 'control %s, config DB %s; %s' % (ep, cdb, why)

    def server_args(self):
        """The arguments `daq_sim up --webgui` gives its web GUI (daq_sim.start_webgui), with --port 0."""
        return ['-p', str(self.platform), '-H', '127.0.0.1', '--configdb-url', self.configdb_url,
                '--configdb-root', 'configDB', '--events-source', 'pva', '--events-pv',
                self.ds.count_pv(self.platform)]

    def prepare(self):
        """Once per session: add the config editor tests' entries to the sim's config DB (NOBEAM, treetest_0,
        det/BEAM/<serial number>; never touches what daq_sim seeded) and snapshot every config."""
        if self.snapshot is None:
            from configeditor_harness import daq_script
            path = os.path.join(tempfile.mkdtemp(prefix='simdaq-snap-'), 'snapshot.json')
            self.prepared = daq_script('sim-prepare', '--url', self.configdb_url, '--out', path)
            self.snapshot = path
        return self.prepared

    def restore_configdb(self):
        """Write back every config a test changed (a new version equal to the snapshot)."""
        from configeditor_harness import daq_script
        return daq_script('sim-restore', '--url', self.configdb_url, '--snapshot', self.snapshot)

    def restore_control(self, s, timeout=120):
        """Through the test's own server s: back to reset, recording off, config alias BEAM, and the partition
        selection daq_sim set up (every process active, no monitor-only DRP, DRP readout group = platform),
        re-applied by a rollcall + selectPlatform + alloc only if it differs."""
        done = []
        st = s.get('/api/status')
        if st['state'] != 'reset':
            s.post('/api/state', {'state': 'reset'})
            s.wait_state('reset', timeout)
            done.append('reset from %s' % st['state'])
        st = s.get('/api/status')
        if st.get('recording'):
            s.post('/api/record', {'record': False})
            done.append('recording off')
        if st.get('config_alias') != self.alias:
            s.post('/api/config', {'alias': self.alias})
            done.append('config alias %s' % self.alias)
        s.post('/api/transition', {'transition': 'rollcall'})
        s.wait_state('unallocated', timeout)
        plat = s.get('/api/platform')
        want, differ = json.loads(json.dumps(plat)), []
        for level, procs in want.items():
            for v in procs.values():
                grp = level in ('drp', 'tpr') and 'det_info' in v
                if v.get('active') != 1 or v.get('monitor', 0) != 0 or (
                        grp and v['det_info'].get('readout') != self.platform):
                    differ.append(v['proc_info']['alias'])
                v['active'], v['monitor'] = 1, 0              # control.py:1738 reads 'monitor' of every entry
                if grp:
                    v['det_info']['readout'] = self.platform
        if differ:
            r = s.post('/api/platform', {'platform': want, 'allocate': True})
            if not r.get('ok', True):
                raise RuntimeError('restore: selectPlatform failed: %s' % r)
            s.wait_state('allocated', timeout)
            done.append('selection re-applied (%s)' % ', '.join(differ))
        s.post('/api/state', {'state': 'reset'})
        s.wait_state('reset', timeout)
        return done


def daq_server(emulate_args=()):
    """Generator for a fixture: the server a parity test drives.  With WEBGUI_SIM_DAQ, the real DaqControl backend
    on that simulated DAQ (before and after the test, control, the partition selection and, after it, the config
    DB are put back as daq_sim set them up); else --emulate plus emulate_args."""
    sim = sim_daq()
    if sim is None:
        s = ServerProc(['--emulate'] + list(emulate_args)).start()
        s.sim = None
        try:
            yield s
        finally:
            s.stop()
        return
    sim.prepare()
    s = ServerProc(sim.server_args()).start()
    s.sim = sim
    try:
        assert s.backend == 'sim-daq', (s.backend, s.backend_why)
        s.restore_start = sim.restore_control(s)      # whatever ran before (a test, daq_sim cycle) left
        yield s
    finally:
        try:
            s.restore_done = sim.restore_control(s)
        finally:
            s.stop()
            sim.restore_configdb()


def platform_by_alias(s):
    plat = s.get('/api/platform')
    return {v['proc_info']['alias']: dict(v, level=lvl) for lvl, procs in plat.items() for v in procs.values()}


def run_server_cmd(args, timeout=30):
    """Run the server CLI to completion (for refusal / --print-config checks)."""
    return subprocess.run([SERVER_PYTHON, '-m', 'psdaq.webgui.server'] + list(args), env=server_env(),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
