"""The offscreen walk's guards (qt_walk.guard_subprocess, run by guard_network before a walked GUI starts): no remote
shell to any host and no Slurm command, while other subprocesses run.  Each probe is a harmless local command
(ssh -V, squeue --version), run in a child python with the guard installed."""

import subprocess
import sys

import pytest

CODE = r'''
import json, os, subprocess, sys
from psdaq.webgui.parity import qt_walk
OUT = {'calls': []}
qt_walk.guard_subprocess(OUT)
res = {}
for name, argv, shell in json.loads(sys.argv[1]):
    try:
        subprocess.run(argv, shell=shell, capture_output=True, timeout=10)
        res[name] = 'ran'
    except PermissionError as e:
        res[name] = 'refused'
try:
    os.system('ssh -V')
    res['os.system ssh'] = 'ran'
except PermissionError:
    res['os.system ssh'] = 'refused'
print(json.dumps([res, OUT['calls']]))
'''


def test_remote_shells_and_slurm_refused_others_run():
    import json
    probes = [['ssh', ['ssh', '-V'], False], ['scp', ['/usr/bin/scp', '-V'], False],
              ['squeue', ['squeue', '--version'], False], ['sbatch shell', 'sbatch --version', True],
              ['echo', ['echo', 'hi'], False], ['true shell', 'true', True]]
    p = subprocess.run([sys.executable, '-c', CODE, json.dumps(probes)], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr[-800:]
    res, calls = json.loads(p.stdout.strip().splitlines()[-1])
    assert res == {'ssh': 'refused', 'scp': 'refused', 'squeue': 'refused', 'sbatch shell': 'refused',
                   'echo': 'ran', 'true shell': 'ran', 'os.system ssh': 'refused'}, res
    assert sum(c['opener'].startswith('refused:') for c in calls) == 5, calls


NET = r'''
import json, socket
from psdaq.webgui.parity import qt_walk
OUT = {'calls': []}
qt_walk.guard_network(OUT)
srv = socket.socket(); srv.bind(('0.0.0.0', 0)); srv.listen(4)
port = srv.getsockname()[1]
res = {}
for name, host in (('loopback', '127.0.0.1'), ('this host', socket.gethostname()),
                   ('another host', '192.0.2.1')):          # 192.0.2.0/24: TEST-NET-1, never routed
    s = socket.socket(); s.settimeout(2)
    try:
        s.connect((socket.gethostbyname(host) if name == 'this host' else host, port))
        res[name] = 'connected'
    except ConnectionRefusedError as e:
        res[name] = 'refused' if 'qt_walk' in str(e) else 'refused by peer'
    except OSError as e:
        res[name] = type(e).__name__
    finally:
        s.close()
print(json.dumps([res, [c['opener'] for c in OUT['calls']]]))
'''


def test_network_guard_lets_this_host_reach_itself_and_refuses_others():
    """procstat reaches the procServ ports of a local config through the host's own name: the guard lets a
    connect to this host's own addresses through (qt_walk.THIS_HOST) and still refuses another host."""
    import json
    p = subprocess.run([sys.executable, '-c', NET], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr[-800:]
    res, calls = json.loads(p.stdout.strip().splitlines()[-1])
    assert res == {'loopback': 'connected', 'this host': 'connected', 'another host': 'refused'}, res
    assert calls == ['refused:socket.connect'], calls
