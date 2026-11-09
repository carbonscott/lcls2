"""daqstat in the browser: an extension of psdaq.webgui.server, the web copy of psdaq/slurm/daqstat.py (WinProcStat +
daqmgrThread): the Slurm job state of every process of a daqmgr .cnf, read with the same psdaq.slurm.main.Runner(cnf)
.show_status(quiet=True) call on the same schedule.

    --daqstat-cnf FILE --daqstat-slurm STATE [--daqstat-interval S]

The server never runs a Slurm command: STATE is a psdaq.sim.simslurm job state file, and psdaq.slurm.utils's
`subprocess` and the Runner's sbatch helper are simslurm's stand-ins in this process (a command simslurm does not
answer is refused); without --daqstat-slurm the page is off.  The Runner writes its sbatch logs under the simslurm
log dir, not under $HOME/daq/logs.

Routes (the page is static/gui/daqstat.html with procstat.js, data-api /api/daqstat)
  GET  /api/daqstat/status   {cnf, interval, seq, rows: [{showId, status, text, rgb}], error, unknown_error, local_ids}
                                                                     daqmgrThread + WinProcStat.onProcMgrUpdated
  POST /api/daqstat/click    {id, mode: console|logfile|restart, offset}           WinProcStat.onProcCellClicked
      console  Runner.spawnConsole: an xterm running `sattach <job>.0` -> the viewer gets the job's output (its log)
      logfile  Runner.spawnLogfile: `less +F <logfile>` -> the viewer, following
      restart  Runner.restart(unique_ids=id): scancel + sbatch, answered by simslurm
"""

import logging
import os
import threading
import time
import traceback

logger = logging.getLogger(__name__)

COLORS = {'COMPLETED': (0, 0, 192), 'COMPLETING': (0, 0, 192), 'FAILED': (255, 0, 0), 'PENDING': (192, 192, 0),
          'PREEMPTED': (255, 0, 0), 'RUNNING': (0, 192, 0), 'SUSPENDED': (255, 0, 0), 'STOPPED': (255, 0, 0)}  # daqstat:212


class DaqStatApi:
    def __init__(self, app):
        a = app.args
        self.cnf = getattr(a, 'daqstat_cnf', None)
        self.state = getattr(a, 'daqstat_slurm', None)
        self.interval = getattr(a, 'daqstat_interval', 5.0)
        self.lock = threading.Lock()
        self.rows, self.status_list, self.seq, self.error, self.unknown = [], [], 0, None, None
        self.runner = None
        if not self.cnf:
            return
        if not self.state or not os.path.isfile(self.state):
            raise SystemExit('--daqstat-cnf needs --daqstat-slurm STATE, a psdaq.sim.simslurm state file: the web copy '
                             'of daqstat never runs a Slurm command')
        self.cnf, self.state = os.path.abspath(self.cnf), os.path.abspath(self.state)
        from psdaq.sim import simslurm
        from psdaq.slurm import utils as U
        import json
        with open(self.state) as f:
            self.sim = json.load(f)
        U.subprocess = simslurm.SubprocessStandIn(self.state)           # every Slurm call of the Runner: simslurm
        self.ProcStandIn = simslurm.ProcStandIn
        threading.Thread(target=self._wrapper, name='daqstat', daemon=True).start()

    def _wrapper(self):                                                  # daqmgrThreadWrapper
        try:
            self._thread()
        except Exception:
            report = ('daqmgrThreadWrapper(): daqmgrThread(ConfigFile = %s, Query Interval = %f ) Failed'
                      % (self.cnf, float(self.interval)))
            logger.error('%s\n%s', report, traceback.format_exc())
            with self.lock:
                self.unknown = {'title': 'Unknown Error', 'report': report,
                                'text': 'Not able to update the process status. Please check the log file for more '
                                        'details.'}

    def _thread(self):                                                   # daqmgrThread
        from psdaq.slurm.main import Runner
        while True:
            # daqmgrThread's except branches emit ProcMgrIOError / ProcMgrGeneralError with one argument where the
            # signals take (str, int): the emit raises TypeError, which ends the thread (-> Unknown Error).  So here
            # any failure ends the thread too.
            if self.runner is None:
                self.runner = Runner(self.cnf, output=self.sim['logdir'])
                self.runner.proc = self.ProcStandIn(self.state)
            ld = self.runner.show_status(quiet=True)
            out = []
            for d in ld:
                s = d['status']
                out.append({'showId': d['showId'], 'status': s, 'text': s, 'rgb': COLORS[s]})
            with self.lock:
                self.rows, self.status_list, self.seq = out, ld, self.seq + 1
            time.sleep(self.interval)

    def status(self, q):
        if not self.cnf:
            return 404, {'ok': False, 'err_info': 'server started without --daqstat-cnf'}
        with self.lock:
            return 200, {'ok': True, 'cnf': self.cnf, 'platform': getattr(self.runner, 'platform', None),
                         'interval': self.interval, 'seq': self.seq, 'rows': list(self.rows), 'error': self.error,
                         'unknown_error': self.unknown, 'local_ids': [], 'slurm': self.state,
                         'sim_pid': self.sim.get('pid')}

    def click(self, body):
        if not self.cnf:
            return 404, {'ok': False, 'err_info': 'server started without --daqstat-cnf'}
        uid, mode = body.get('id'), body.get('mode')
        if not isinstance(uid, str) or mode not in ('console', 'logfile', 'restart'):
            return 400, {'ok': False, 'err_info': 'need id and mode console|logfile|restart'}
        with self.lock:
            r, ld = self.runner, list(self.status_list)
        if r is None:                                                    # onProcCellClicked: runner None
            return 200, {'ok': True, 'opened': False, 'why': 'no status yet'}
        if mode == 'restart':
            r.restart(unique_ids=uid)
            return 200, {'ok': True, 'restarted': uid}
        st = r.get_statusdict(uid, ld)
        if mode == 'console':                                            # Runner.spawnConsole
            if not st.get('job_id'):
                return 200, {'ok': True, 'opened': False, 'why': "spawnConsole: process '%s' not found" % uid}
            path = st.get('logfile') or ''
            text = open(path, 'rb').read(1 << 20).decode('utf-8', 'replace') if os.path.isfile(path) else ''
            return 200, {'ok': True, 'opened': True, 'title': uid, 'label': 'sattach %s.0' % st['job_id'],
                         'path': path, 'text': text}
        path = st.get('logfile') or ''                                   # Runner.spawnLogfile
        if not path or not os.path.exists(path):
            return 200, {'ok': True, 'opened': False, 'why': 'spawnLogfile: process %s logfile not found (%s)' % (uid, path)}
        off = body.get('offset') or 0
        size = os.path.getsize(path)
        with open(path, 'rb') as f:
            f.seek(off if isinstance(off, int) and 0 <= off <= size else max(0, size - 200000))
            data = f.read(1 << 20)
        return 200, {'ok': True, 'opened': True, 'title': uid, 'path': path, 'size': size, 'offset': size,
                     'text': data.decode('utf-8', 'replace')}


def register(app, get_routes, post_routes):
    api = DaqStatApi(app)
    app.daqstat_api = api
    get_routes['/api/daqstat/status'] = api.status
    post_routes['/api/daqstat/click'] = api.click
    return api
