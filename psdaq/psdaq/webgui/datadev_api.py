"""Web copy of psdaq/cas/datadev_monitor.py (the datadev node status monitor): an extension of
psdaq.webgui.server, started with  --datadev-sim ROOT  (a psdaq.sim.simdatadev root).

The PyQt program ssh-es to each drp-srcf-cmp node and runs its CHECK_SCRIPT there.  This copy never starts ssh: it
only runs the program's own CHECK_SCRIPT on the simulated nodes of ROOT (simdatadev --target ROOT HOST, a local
process that reads ROOT/HOST instead of the node), and refuses to start without a simdatadev root.  The rest is the
program's code: its node list (NODE_PREFIX, NODE_RANGE), its Ansible inventory reader for the Groups column
(parse_ansible_hosts(HOSTS_FILE)), its output parser (check_node, with the ssh call replaced), its columns, colours
and status-bar tally, and its parallelism (MAX_WORKERS).  Refresh All marks every data cell '…', checks the nodes in
the background (progress 0-100 %, the button disabled meanwhile), then writes 'Last refresh: <time>' and the tally.

Routes
  GET  /api/datadev/status    rows [{cells: [7 texts], colours: [7 names|null], tips}], refreshing, progress,
                              ts_label, status, sim (root, pid), refreshes
  POST /api/datadev/refresh   Refresh All
"""

import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime


class DatadevApi:
    def __init__(self, app):
        self.root = getattr(app.args, 'datadev_sim', None)
        self.lock = threading.Lock()
        if not self.root:
            return
        marker = os.path.join(self.root, 'simdatadev.json')
        if not os.path.isfile(marker):
            raise SystemExit('--datadev-sim %s: not a psdaq.sim.simdatadev root (no %s); the web copy of '
                             'datadev_monitor only talks to simulated nodes' % (self.root, marker))
        with open(marker) as f:
            self.sim = json.load(f)
        from psdaq.cas import datadev_monitor as D             # the program's own definitions (no QApplication)
        self.D = D
        self.hostnames = ['%s%03d' % (D.NODE_PREFIX, i) for i in D.NODE_RANGE]
        self.groups = D.parse_ansible_hosts(D.HOSTS_FILE)
        self.rows = []
        for h in self.hostnames:                               # MainWindow._populate_table
            grps = self.groups.get(h, [])
            self.rows.append({'cells': [h, '\n'.join(grps) if grps else '—'] + ['—'] * (D.NUM_COLS - 2),
                              'colours': [None] * D.NUM_COLS, 'tips': ['', '\n'.join(grps)] + [''] * (D.NUM_COLS - 2)})
        self.refreshing, self.progress, self.btn_enabled = False, None, True
        self.ts_label, self.status, self.refreshes, self.targets = 'Not yet refreshed', '', 0, 0

    def check_node(self, hostname):
        """datadev_monitor.check_node with `ssh ... HOST bash -s` replaced by the simulated node HOST."""
        D = self.D
        orig = D.subprocess.run

        def run(args, input=None, capture_output=False, text=False, timeout=None, **k):
            assert args[0] == 'ssh' and args[-1] == 'bash -s', args
            self.targets += 1
            return orig([sys.executable, '-m', 'psdaq.sim.simdatadev', '--target', self.root, args[-2]], input=input,
                        capture_output=capture_output, text=text, timeout=timeout, **k)
        return _check_node(D, hostname, run)

    def _update_row(self, result):                             # MainWindow._update_row
        D = self.D
        r = self.rows[self.hostnames.index(result['hostname'])]
        c, col = r['cells'], r['colours']
        if not result['reachable']:
            for k in range(1, D.NUM_COLS):
                c[k] = 'unreachable' if k == D.COL_KO else '—'
                col[k] = 'GRAY'
            c[D.COL_EXEC] = result.get('exec', '')
            return
        c[D.COL_PROC] = result['proc']
        col[D.COL_PROC] = 'RED' if result['proc'] == 'None' else 'GREEN'
        r['tips'][D.COL_PROC] = 'No /proc/datadev_* entries found' if result['proc'] == 'None' else \
            result.get('proc_names', '')
        c[D.COL_KO], col[D.COL_KO] = result['ko'], 'GREEN' if result['ko'] == 'YES' else 'RED'
        c[D.COL_SVC], col[D.COL_SVC] = result['svc'], 'GREEN' if result['svc'] == 'YES' else 'RED'
        c[D.COL_CFG] = result['cfg']
        col[D.COL_CFG] = 'GREEN' if result['cfg'] == 'YES' else ('AMBER' if result['cfg'] == 'N/A' else 'RED')
        c[D.COL_EXEC], col[D.COL_EXEC] = result['exec'], None
        r['tips'][D.COL_EXEC] = result['exec']

    def _run(self):
        D = self.D
        total, done = len(self.hostnames), 0
        with ThreadPoolExecutor(max_workers=D.MAX_WORKERS) as exe:           # NodeChecker.run
            futures = {exe.submit(self.check_node, h): h for h in self.hostnames}
            for fut in as_completed(futures):
                with self.lock:
                    self._update_row(fut.result())
                    done += 1
                    self.progress = int(done * 100 / total)
        with self.lock:                                                        # MainWindow._on_done
            self.refreshing, self.btn_enabled = False, True
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.ts_label = 'Last refresh: %s' % now
            reachable = sum(1 for r in self.rows if r['cells'][D.COL_KO] not in ('—', '…', 'unreachable'))
            ok_svc = sum(1 for r in self.rows if r['cells'][D.COL_SVC] == 'YES')
            ok_cfg = sum(1 for r in self.rows if r['cells'][D.COL_CFG] == 'YES')
            self.status = 'Done %s  |  %d/%d reachable  |  %d with service  |  %d with cfgRxCount' % (
                now, reachable, len(self.hostnames), ok_svc, ok_cfg)
            self.refreshes += 1

    def refresh(self, body):
        if not self.root:
            return 404, {'ok': False, 'err_info': 'no --datadev-sim'}
        with self.lock:
            if self.refreshing:                                # _start_refresh: one at a time
                return 200, {'ok': True, 'ignored': 'a refresh is running'}
            self.refreshing, self.btn_enabled, self.progress = True, False, 0
            self.status = 'Checking nodes …'
            for r in self.rows:                                # _reset_pending
                for k in range(self.D.COL_PROC, self.D.NUM_COLS):
                    r['cells'][k], r['colours'][k], r['tips'][k] = '…', None, ''
        threading.Thread(target=self._run, daemon=True).start()
        return 200, {'ok': True}

    def status_(self, q):
        if not self.root:
            return 404, {'ok': False, 'err_info': 'no --datadev-sim'}
        with self.lock:
            return 200, {'ok': True, 'title': 'datadev Node Status Monitor', 'headers': self.D.HEADERS,
                         'rows': json.loads(json.dumps(self.rows)), 'refreshing': self.refreshing,
                         'progress': self.progress, 'progress_visible': self.refreshing,
                         'button_enabled': self.btn_enabled, 'ts_label': self.ts_label, 'status': self.status,
                         'refreshes': self.refreshes, 'targets_run': self.targets,
                         'sim': {'root': self.sim['root'], 'pid': self.sim['pid']}}


def _check_node(D, hostname, run):
    """datadev_monitor.check_node, its source run with subprocess.run replaced by `run` (the simulated node)."""
    import types
    g = dict(D.__dict__)
    g['subprocess'] = types.SimpleNamespace(run=run, TimeoutExpired=subprocess.TimeoutExpired)
    fn = types.FunctionType(D.check_node.__code__, g, 'check_node')
    return fn(hostname)


def register(app, get_routes, post_routes):
    api = DatadevApi(app)
    app.datadev_api = api
    get_routes['/api/datadev/status'] = api.status_
    post_routes['/api/datadev/refresh'] = api.refresh
    return api
