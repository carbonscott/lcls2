"""Shared helpers for the web GUI tests: start/stop the server as a subprocess.

Environment:
  WEBGUI_PYTHON       interpreter for the server (default: this one). run_webgui_tests.sh sets the DAQ env's.
  WEBGUI_SERVER_ARGS  extra server arguments for every started server, e.g. "--emulate-fail enable"
                      (used to prove the tests fail when a transition fails).
  WEBGUI_SHOTS        directory for screenshots (default: a temp dir).
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


def run_server_cmd(args, timeout=30):
    """Run the server CLI to completion (for refusal / --print-config checks)."""
    return subprocess.run([SERVER_PYTHON, '-m', 'psdaq.webgui.server'] + list(args), env=server_env(),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
