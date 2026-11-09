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
