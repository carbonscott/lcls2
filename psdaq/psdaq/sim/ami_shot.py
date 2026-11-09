"""ami_shot: a screenshot of AMI's client showing the camera image of a hardware-free run.

    daq_sim cycle --ami-shot PNG     (a DAQ 'up --ami'; while the run is Running)

While the run is Running, Shot starts one more ami-client, AMI's own Qt GUI, offscreen
(QT_QPA_PLATFORM=offscreen), on the running AMI manager, with a graph of its own ('-g ami_shot',
so the check graph of psdaq.sim.ami_check is left alone) loaded from a flowchart file ('-l') that
holds one viewed source node, <det>:raw:raw: loading it opens AMI's image viewer of the camera
image, as double-clicking the source does.  psdaq/sim/qtgrab (first on that client's PYTHONPATH
only) saves each of its windows to <workdir>/logs/ami-shot/<title>.<pid>.png every 2 s.  Shot waits
until the viewer's window has been grabbed showing data (more than one colour in the image area),
then copies that PNG to PNG and stops the client.  The client's PVA server and Prometheus port are
the platform's own (daq_sim ports: ami_shot_pvas, ami_prom + 1), on loopback.

Its log (logs/ami-shot/ami-client.log) is headed with its '# CMDLINE:' and '# PID:'; just before it
is stopped, Shot reads which processes hold AMI's ports (ami_check.served_by), its window processes
among them, for the ami_check witness of the run (coverage's ami-client row).
"""

import glob
import json
import os
import shutil
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
GRAPH = 'ami_shot'


def flowchart(source):
    """A flowchart (.fc) with one viewed source node: AMI opens its viewer when it loads it."""
    return {'nodes': [{'class': 'SourceNode', 'name': source,
                       'state': {'pos': [200.0, 0.0], 'enabled': True, 'viewed': True,
                                 'terminals': {'Out': {'io': 'out', 'removable': False,
                                                       'ttype': 'amitypes.array.Array2d',
                                                       'optional': False, 'group': None}},
                                 'widget': {}, 'source_kwargs': {}}}],
            'connects': []}


def colours(path):
    """The number of distinct colours in a PNG (None if it cannot be read)."""
    try:
        from PyQt5 import QtGui
    except ImportError:
        return None
    img = QtGui.QImage(path)
    if img.isNull():
        return None
    seen, w, h = set(), img.width(), img.height()
    for y in range(0, h, max(1, h // 200)):
        for x in range(0, w, max(1, w // 200)):
            seen.add(img.pixel(x, y))
            if len(seen) > 64:
                return len(seen)
    return len(seen)


def descendants(pid):
    """The pids of a process's children, their children, ... (from /proc)."""
    kids = {}
    for d in os.listdir('/proc'):
        if d.isdigit():
            try:
                with open(f'/proc/{d}/stat') as f:
                    kids.setdefault(int(f.read().rsplit(')', 1)[1].split()[1]), []).append(int(d))
            except (OSError, ValueError, IndexError):
                pass
    out, todo = [], [pid]
    while todo:
        for k in kids.get(todo.pop(), []):
            out.append(k)
            todo.append(k)
    return out


def _alive(pid):
    try:
        with open(f'/proc/{pid}/stat') as f:
            return f.read().rsplit(')', 1)[1].split()[0] != 'Z'
    except (OSError, IndexError):
        return False


def stop_tree(proc):
    """SIGTERM a process and every process it started (an AMI client forks its windows and may
    leave a mypy daemon), then SIGKILL what is left after 10 s."""
    pids = [proc.pid] + descendants(proc.pid)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid in pids:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        end = time.monotonic() + 10
        while time.monotonic() < end:
            proc.poll()
            if not any(_alive(p) for p in pids):
                return
            time.sleep(0.2)


class Shot:
    def __init__(self, workdir, state, out, det='fakecam', timeout=150):
        from psdaq.sim import daq_sim
        self.out, self.timeout, self.t0 = out, timeout, time.monotonic()
        self.source = f'{det}:raw:raw'
        self.dir = os.path.join(workdir, 'logs', 'ami-shot')
        os.makedirs(self.dir, exist_ok=True)
        for f in glob.glob(os.path.join(self.dir, '*')):
            os.remove(f)
        fc = os.path.join(self.dir, 'viewer.fc')
        with open(fc, 'w') as f:
            json.dump(flowchart(self.source), f, indent=1)
        P = state['ports']
        pvas = P.get('ami_shot_pvas') or daq_sim.ports(state['platform'])['ami_shot_pvas']
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen', DAQ_SIM_GRAB_DIR=self.dir, DAQ_SIM_GRAB_MS='2000',
                   EPICS_PVAS_SERVER_PORT=str(pvas[0]), EPICS_PVAS_BROADCAST_PORT=str(pvas[1]),
                   PYTHONPATH=os.pathsep.join([os.path.join(HERE, 'qtgrab'), os.environ.get('PYTHONPATH', '')]))
        env[daq_sim.TAG] = workdir      # 'down' finds whatever it leaves behind
        client = os.path.join(workdir, 'bin', 'ami-client')
        if not os.path.exists(client):
            client = shutil.which('ami-client') or client
        self.cmd = [client, '-p', str(P['ami']), '-H', '127.0.0.1', '-g', GRAPH, '-l', fc,
                    '--prometheus-port', str(P['ami_prom'] + 1)]
        self.log = os.path.join(self.dir, 'ami-client.log')
        with open(self.log, 'w') as f:
            f.write(daq_sim.log_header(self.cmd))
            f.flush()
            self.proc = subprocess.Popen(self.cmd, stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                         env=env, cwd=self.dir, start_new_session=True)
            f.write(f'# PID: {self.proc.pid}\n')
            f.flush()
        self.ports, self.served = daq_sim.ami_ports(state['platform']), []
        print(f'{daq_sim.now()} AMI shot: ami-client pid {self.proc.pid} loading a viewer of {self.source} '
              f'(logs/ami-shot)', flush=True)

    def candidates(self):
        """[(path, title, colours)] of the grabbed windows showing the source, newest first."""
        out = []
        for line in reversed(open(os.path.join(self.dir, 'index.jsonl')).read().splitlines()
                             if os.path.exists(os.path.join(self.dir, 'index.jsonl')) else []):
            try:
                g = json.loads(line)
            except ValueError:
                continue
            if self.source in g['title'] and all(g['png'] != c[0] for c in out):
                out.append((g['png'], g['title'], colours(g['png'])))
        return out

    def wait(self):
        """'PASS <png>: ...' once the viewer showed data, else 'FAIL ...'; stops the client."""
        from psdaq.sim import daq_sim
        verdict = None
        try:
            while time.monotonic() - self.t0 < self.timeout and verdict is None:
                if self.proc.poll() is not None:
                    verdict = f'FAIL ami-client exited {self.proc.returncode} (logs/ami-shot/ami-client.log)'
                    break
                for path, title, n in self.candidates():
                    if n and n > 8:     # the image, not a blank window
                        time.sleep(2.5)     # one more grab: the newest picture of the viewer
                        best = self.candidates()[0][0] if self.candidates() else path
                        shutil.copyfile(best, self.out)
                        verdict = (f'PASS {self.out}: window "{title}" of ami-client pid {self.proc.pid}, '
                                   f'{colours(self.out)}+ colours')
                        break
                time.sleep(1)
            if verdict is None:
                seen = sorted({os.path.basename(p) for p in glob.glob(os.path.join(self.dir, '*.png'))})
                verdict = f'FAIL no grab of a {self.source} window showing data in {self.timeout} s (grabbed: {seen})'
        finally:
            from psdaq.sim import ami_check
            self.served = ami_check.served_by(self.ports, exclude={os.getpid()})
            stop_tree(self.proc)
        print(f'{daq_sim.now()} AMI shot: {verdict}', flush=True)
        return verdict


if __name__ == '__main__':
    print(__doc__)
    sys.exit(0)
