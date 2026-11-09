"""The web GUI server stays on the local host.

- refuses to bind a non-loopback address (there is no override);
- refuses non-loopback control host / config DB / events URLs before opening anything;
- --print-config lists every endpoint and all are loopback;
- the static page references no remote URL (no CDN);
- at run time (audit hook on socket.connect / bind / getaddrinfo / urllib.Request) the server only
  touches 127.0.0.1, while serving the page, the SSE stream, commands and a Prometheus events poll;
- /gui/procstat (telnetlib stubbed, so no procServ is contacted): a --procstat-cnf with a process on a host
  that is not loopback is refused at startup (exit 2) before any connection; the poll opens procServ only at
  127.0.0.1, also for the processes ProcMgr would reach at the machine's name; its ProcMgr refuses any other host.
No browser needed; runs in the DAQ env's or the test venv's pytest.
"""

import http.server
import json
import os
import pathlib
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time

import pytest

from webgui_harness import PKG_ROOT, SERVER_PYTHON, ServerProc, run_server_cmd, server_env

STATIC = PKG_ROOT / 'psdaq' / 'webgui' / 'static'


def _host_ip():
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except OSError:
        return None
    return None if ip.startswith('127.') else ip


@pytest.mark.parametrize('bind', ['0.0.0.0', '::', 'HOSTIP', 'sdfiana025.sdf.slac.stanford.edu'])
def test_refuses_non_loopback_bind(bind):
    if bind == 'HOSTIP':
        bind = _host_ip()
        if bind is None:
            pytest.skip('host has no non-loopback IPv4 address')
    r = run_server_cmd(['--emulate', '--bind', bind, '--port', '0'])
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert 'not a loopback address' in r.stderr and 'listening' not in r.stdout, r.stderr


@pytest.mark.parametrize('args', [
    ['--host', 'pswww.slac.stanford.edu'],
    ['--host', '0.0.0.0'],
    ['--configdb-url', 'https://pswww.slac.stanford.edu/ws-auth/devconfigdb/ws/'],
    ['--emulate', '--configdb-url', 'https://pswww.slac.stanford.edu/ws-auth/devconfigdb/ws/'],
    ['--emulate', '--events-source', 'prometheus', '--events-url', 'http://sdfmilan119:9200/metrics',
     '--events-metric', 'x'],
    ['--emulate', '--events-source', 'prometheus', '--events-url', 'file:///etc/passwd', '--events-metric', 'x'],
])
def test_refuses_non_loopback_endpoints(args):
    r = run_server_cmd(args + ['--port', '0'])
    assert r.returncode == 2, (args, r.returncode, r.stdout, r.stderr)
    assert 'refusing' in r.stderr or 'expected one of' in r.stderr, r.stderr


def test_print_config_defaults_are_loopback():
    r = run_server_cmd(['--print-config'])          # real (DaqControl) mode defaults
    assert r.returncode == 0, r.stderr
    cfg = json.loads(r.stdout)
    assert cfg['all_loopback'] is True, cfg
    assert cfg['listen'].startswith('http://127.0.0.1:')
    for k in ('front_rep', 'fast_rep', 'front_pub', 'step_pub'):
        assert cfg[k].startswith('tcp://127.0.0.1:'), cfg
    # platform 6: ports 29980 + 6 + {20, 40, 30, 50} (ControlDef.py:117-127)
    assert (cfg['front_rep'], cfg['fast_rep'], cfg['front_pub'], cfg['step_pub']) == (
        'tcp://127.0.0.1:30006', 'tcp://127.0.0.1:30026', 'tcp://127.0.0.1:30016', 'tcp://127.0.0.1:30036')
    assert 'configdb' not in cfg, 'no config DB by default (the PyQt default is the facility pswww URL)'


def test_print_config_explicit_endpoints():
    r = run_server_cmd(['--print-config', '-p', '5', '--configdb-url', 'http://127.0.0.1:5050/ws/',
                        '--events-source', 'prometheus', '--events-url', 'http://localhost:9200/metrics',
                        '--events-metric', 'TEB_EvtCt'])
    assert r.returncode == 0, r.stderr
    cfg = json.loads(r.stdout)
    assert cfg['all_loopback'] is True and cfg['configdb'] == 'http://127.0.0.1:5050/ws/', cfg
    assert cfg['events'] == 'http://localhost:9200/metrics' and cfg['front_rep'] == 'tcp://127.0.0.1:30005', cfg


def test_static_has_no_remote_urls():
    files = sorted(p for p in STATIC.rglob('*') if p.is_file())
    assert {p.name for p in files} >= {'index.html', 'app.js', 'style.css'}
    pat = re.compile(r'(?:https?:)?//[A-Za-z0-9.-]+\.[A-Za-z]{2,}|<script[^>]+src="https?:|@import\s+url\(\s*["\']?https?:')
    hits = [(p.name, m.group(0)) for p in files for m in pat.finditer(p.read_text())]
    assert hits == [], hits


AUDIT = r'''
import json, runpy, sys
log = open(sys.argv[1], 'a', buffering=1)
def hook(ev, args):
    if ev in ('socket.connect', 'socket.bind'):
        log.write(json.dumps([ev, repr(args[1])]) + '\n')
    elif ev == 'socket.getaddrinfo':
        log.write(json.dumps([ev, repr(args[0])]) + '\n')
    elif ev == 'urllib.Request':
        log.write(json.dumps([ev, args[0]]) + '\n')
sys.addaudithook(hook)
sys.argv = ['daq_webgui'] + sys.argv[2:]
runpy.run_module('psdaq.webgui.server', run_name='__main__')
'''


class _Metrics(http.server.BaseHTTPRequestHandler):
    hits = 0

    def do_GET(self):
        _Metrics.hits += 1
        body = b'# TYPE TEB_EvtCt counter\nTEB_EvtCt{alias="teb0"} 1234\n'
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_runtime_contacts_only_loopback(tmp_path):
    metrics = http.server.ThreadingHTTPServer(('127.0.0.1', 0), _Metrics)
    threading.Thread(target=metrics.serve_forever, daemon=True).start()
    murl = 'http://127.0.0.1:%d/metrics' % metrics.server_address[1]
    audit = tmp_path / 'audit.jsonl'
    wrapper = tmp_path / 'audit_wrapper.py'
    wrapper.write_text(AUDIT)
    s = ServerProc(['--emulate', '--events-source', 'prometheus', '--events-url', murl,
                    '--events-metric', 'TEB_EvtCt', '--events-period', '0.2'])
    s.cmd = [SERVER_PYTHON, str(wrapper), str(audit)] + s.cmd[3:]   # same args, under the audit hook
    s.start()
    try:
        s.get('/api/status')
        s.post('/api/transition', {'transition': 'rollcall'})
        s.wait_state('unallocated')
        s.post('/api/platform', {'platform': s.get('/api/platform'), 'allocate': True})
        s.wait_state('allocated')
        s.post('/api/state', {'state': 'running'})
        s.wait_state('running')
        s.post('/api/state', {'state': 'reset'})
        s.wait_state('reset')
        t0 = time.time()
        while time.time() - t0 < 10 and s.get('/api/events')['events'] != 1234:
            time.sleep(0.2)
        ev = s.get('/api/events')
        assert ev['events'] == 1234 and ev['source'] == 'prometheus', ev
    finally:
        rc = s.stop()
        metrics.shutdown()
    assert rc == 0, '\n'.join(s.lines[-20:])
    recs = [json.loads(l) for l in audit.read_text().splitlines()]
    assert recs, 'audit hook recorded nothing'
    bad = []
    for ev, arg in recs:
        if ev == 'urllib.Request':
            ok = arg.startswith('http://127.0.0.1:') or arg.startswith('http://localhost:')
        else:
            ok = any(h in arg for h in ("'127.0.0.1'", "'localhost'", "'::1'"))
        if not ok:
            bad.append((ev, arg))
    kinds = sorted({r[0] for r in recs})
    assert 'socket.bind' in kinds and 'urllib.Request' in kinds, kinds
    assert bad == [], bad
    assert _Metrics.hits > 0


# ---------------- /gui/procstat: the .cnf's hosts (ProcMgr telnets to every process's procServ port) ----------------

TELNET_STUB = r"""
import json, runpy, sys, telnetlib
log = open(sys.argv[1], 'a', buffering=1)
def hook(ev, args):
    if ev == 'socket.connect':
        log.write(json.dumps([ev, repr(args[1])]) + '\n')
sys.addaudithook(hook)
def _open(self, host, port=0, *a, **k):          # telnetlib stubbed: record the host, connect nothing
    log.write(json.dumps(['telnet.open', host, str(port)]) + '\n')
    raise ConnectionRefusedError('telnetlib stub: not contacted')
telnetlib.Telnet.open = _open
sys.argv = ['daq_webgui'] + sys.argv[2:]
runpy.run_module('psdaq.webgui.server', run_name='__main__')
"""

CNF_REMOTE = """platform = '5'
procmgr_config = [
 { id:'here', flags:'s', cmd:'sleep 60' },
 { host:'192.0.2.1', id:'remote', flags:'s', cmd:'sleep 60' },
]
"""

CNF_LOCAL = """platform = '5'
procmgr_config = [
 { id:'nohost', flags:'s', cmd:'sleep 60' },
 { host:'localhost', id:'named_localhost', flags:'s', cmd:'sleep 60' },
 { host:'127.0.0.1', id:'ipv4_loopback', flags:'s', cmd:'sleep 60' },
]
"""


def _stub_files(tmp_path, cnf_text):
    cnf = tmp_path / 'p.cnf'
    cnf.write_text(cnf_text)
    wrapper = tmp_path / 'telnet_stub.py'
    wrapper.write_text(TELNET_STUB)
    return cnf, wrapper, tmp_path / 'net.jsonl'


def _records(log):
    return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []


@pytest.fixture
def conda_prefix(monkeypatch):
    """ProcMgr reads os.environ['CONDA_PREFIX'] (the DAQ env sets it)."""
    if not os.environ.get('CONDA_PREFIX'):
        monkeypatch.setenv('CONDA_PREFIX', str(pathlib.Path(SERVER_PYTHON).resolve().parent.parent))


def test_procstat_cnf_naming_a_remote_host_is_refused(tmp_path, conda_prefix):
    cnf, wrapper, log = _stub_files(tmp_path, CNF_REMOTE)
    r = subprocess.run([SERVER_PYTHON, str(wrapper), str(log), '--emulate', '--port', '0', '--procstat-cnf', str(cnf)],
                       env=server_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
    print(r.stderr)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "process 'remote' names host '192.0.2.1'; refusing" in r.stderr, r.stderr
    assert 'listening' not in r.stdout, r.stdout
    recs = _records(log)
    print('telnet.open / socket.connect records:', recs)
    assert recs == [], recs                  # the dry run read the .cnf without a connection, to 192.0.2.1 or here


def test_procstat_poll_opens_only_127_0_0_1(tmp_path, conda_prefix):
    cnf, wrapper, log = _stub_files(tmp_path, CNF_LOCAL)
    s = ServerProc(['--emulate', '--procstat-cnf', str(cnf), '--procstat-interval', '0.3'])
    s.cmd = [SERVER_PYTHON, str(wrapper), str(log)] + s.cmd[3:]    # same args, telnetlib stubbed
    s.start()
    try:
        t0 = time.time()
        st = s.get('/api/procstat/status')
        while st['seq'] < 2 and time.time() - t0 < 20:
            time.sleep(0.2)
            st = s.get('/api/procstat/status')
    finally:
        rc = s.stop()
    assert rc == 0, '\n'.join(s.lines[-20:])
    rows = {r['showId']: r['status'] for r in st['rows']}
    assert rows == {'nohost': 'NOCONNECT', 'named_localhost': 'NOCONNECT', 'ipv4_loopback': 'NOCONNECT'}, st
    opens = [r for r in _records(log) if r[0] == 'telnet.open']
    print('telnet.open (host, port):', sorted({(r[1], r[2]) for r in opens}), 'in', len(opens), 'opens')
    assert opens and {r[1] for r in opens} == {'127.0.0.1'}, opens   # not the machine's name (ProcMgr's HOST)
    bad = [r for r in _records(log) if r[0] == 'socket.connect' and not any(
        h in r[1] for h in ("'127.0.0.1'", "'localhost'", "'::1'"))]
    assert bad == [], bad


GUARD = r"""
import json, sys, telnetlib
opens = []
def _open(self, host, port=0, *a, **k):
    opens.append(host)
    raise ConnectionRefusedError('telnetlib stub: not contacted')
telnetlib.Telnet.open = _open
from psdaq.webgui.procstat_api import loopback_procmgr_class
pm = loopback_procmgr_class()(sys.argv[1], 5)
rows = sorted([(r['showId'].decode() if isinstance(r['showId'], bytes) else r['showId'], r['host'], r['status'])
               for r in pm.getStatus()])
print(json.dumps({'opens': opens, 'rows': rows}))
"""


def test_procstat_poll_procmgr_refuses_a_remote_host(tmp_path, conda_prefix):
    """Past the startup check too (a .cnf that changes after it): the poll's ProcMgr never opens a remote host."""
    cnf, _, _ = _stub_files(tmp_path, CNF_REMOTE)
    r = subprocess.run([SERVER_PYTHON, '-c', GUARD, str(cnf)], env=server_env(), stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    print(out)
    assert out['opens'] == ['127.0.0.1'], out                       # 'here' only; 192.0.2.1 never reached telnetlib
    assert out['rows'] == [['here', 'localhost', 'NOCONNECT'], ['remote', '192.0.2.1', 'NOCONNECT']], out
