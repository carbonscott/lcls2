"""procstat in the browser: an extension of psdaq.webgui.server (listed in its EXT_MODULES).

The web copy of psdaq/procmgr/procstat (WinProcStat + procMgrThread): the status of every process a
procmgr .cnf starts, read with the same ProcMgr(cnf, platform).getStatus() call, on the same schedule.
The server is started with --procstat-cnf FILE [--procstat-platform P] [--procstat-interval S]
[--procstat-logdir DIR] (where procstat would run: its log paths are relative to that); the
page (GET /gui/procstat) never names a file, so a browser can only see and act on that one .cnf.

Routes
  GET  /api/procstat/status   {cnf, platform, interval, seq, rows: [{showId, status, text, rgb}], error,
                               unknown_error, local_ids}            procMgrThread + onProcMgrUpdated
  POST /api/procstat/click    {id, mode: 'console'|'logfile'|'restart', offset}
                                                                    WinProcStat.onProcCellClicked:
      console  ProcMgr.spawnConsole: `cat <log>; telnet <host> <ctrl port>` in an xterm -> the page's
               console panel gets the log file text and what the procServ control port sends in 1.5 s
      logfile  ProcMgr.spawnLogfile: `less +F <LOGPATH>/<id log>` -> the log viewer (offset: follow)
      restart  local process: the warning 'Not Supported' (as procstat); else ProcMgr.stop + start,
               only for a process at 127.0.0.1 or ::1

Hosts.  ProcMgr(cnf, platform) telnets, in its constructor, to the procServ control port of every process of the
.cnf, at the host the .cnf names; a process with no host is 'localhost', which ProcMgr opens at its HOST macro,
the machine's name (a network address, not loopback).  So:
  - at startup (server.configure -> require_loopback_cnf) the server reads the .cnf with ProcMgr in a dry run that
    opens no connection, and exits 2 if any process names a host other than localhost, 127.0.0.1 or ::1
    (or no host);
  - every ProcMgr the server makes is a LoopbackProcMgr: its procServ connections go to 127.0.0.1 (::1 for
    ::1), the HOST macro included, and any other host is refused without a socket (NO CONNECT);
  - the console reads 127.0.0.1:<ctrl port>, and restart reaches only 127.0.0.1 and ::1.
"""

import logging
import os
import socket
import threading
import time
import traceback

logger = logging.getLogger(__name__)

STATUS_TEXT = {'NOCONNECT': (' NO CONNECT', (0, 0, 192)), 'RUNNING': ('RUNNING', (0, 192, 0)),
               'SHUTDOWN': (' SHUTDOWN', (192, 192, 0)), 'ERROR': (' ERROR', (255, 0, 0))}   # procstat:162-175
LOOPBACK = ('localhost', '127.0.0.1', '::1')
_PM_CLASS = []


def loopback_procmgr_class():
    """ProcMgr whose procServ connections stay on this host (made on first use: ProcMgr imports telnetlib).

    ProcMgr.__init__ assigns self.telnet = telnetlib.Telnet() and opens it at each process's host (for 'localhost'
    at its HOST macro, the machine's name).  The subclass's telnet property puts a LoopbackTelnet there instead:
    it opens 127.0.0.1 for a loopback name or the HOST macro (::1 for ::1) and raises ConnectionRefusedError for any
    other host before a socket exists, so ProcMgr shows that process NO CONNECT.  With dry=True it opens nothing and
    appends (id, host as the .cnf names it) of each process ProcMgr would contact to `seen` (the startup check).
    """
    if _PM_CLASS:
        return _PM_CLASS[0]
    import telnetlib
    from psdaq.procmgr.ProcMgr import ProcMgr

    class LoopbackTelnet(telnetlib.Telnet):
        def __init__(self, pm):
            super().__init__()
            self.pm = pm

        def open(self, host, port=0, *args, **kw):
            pm = self.pm
            if pm.dry:
                pm.seen.append((getattr(pm, 'uniqueid', '?'), getattr(pm, 'host', host)))
                raise ConnectionRefusedError('dry run: %s port %s not contacted' % (host, port))
            if host == '::1':
                to = '::1'
            elif host in LOOPBACK or host == pm.procmgr_macro.get('HOST'):
                to = '127.0.0.1'
            else:
                raise ConnectionRefusedError('host %s is not loopback: not contacted' % host)
            return super().open(to, port, *args, **kw)

    class LoopbackProcMgr(ProcMgr):
        def __init__(self, configfilename, platform, dry=False, seen=None):
            self.dry, self.seen = dry, ([] if seen is None else seen)
            super().__init__(configfilename, platform)

        @property
        def telnet(self):
            return self._loopback_telnet

        @telnet.setter
        def telnet(self, _unused):
            self._loopback_telnet = LoopbackTelnet(self)

    _PM_CLASS.append(LoopbackProcMgr)
    return LoopbackProcMgr


def require_loopback_cnf(cnf, platform=-1):
    """Startup check (server.configure): raise NonLoopbackError if a process of cnf names a host that is not
    loopback.  The .cnf is read by LoopbackProcMgr in a dry run (no connection); a .cnf that ProcMgr cannot read
    is checked up to the error and then left to the poll, which shows ProcMgr's error as procstat does.
    Returns [(id, host)] of the processes read."""
    from psdaq.procmgr.ProcMgr import deduce_platform
    from psdaq.webgui.netguard import NonLoopbackError
    cnf, seen = os.path.abspath(cnf), []
    try:
        if platform is None or platform < 0:
            platform = deduce_platform(cnf)
        loopback_procmgr_class()(cnf, platform, dry=True, seen=seen)
    except Exception:
        pass
    bad = [(i, h) for i, h in seen if h not in LOOPBACK]
    if bad:
        raise NonLoopbackError('--procstat-cnf %s: %s; refusing (the web procstat contacts procServ only on this '
                               'host: a process\'s host must be localhost, 127.0.0.1, ::1 or none)'
                               % (cnf, ', '.join('process %r names host %r' % b for b in bad)))
    return seen


def _s(v):
    return v.decode() if isinstance(v, bytes) else str(v)


class ProcStatApi:
    def __init__(self, app):
        a = app.args
        self.cnf = getattr(a, 'procstat_cnf', None)
        self.platform = getattr(a, 'procstat_platform', -1)
        self.interval = getattr(a, 'procstat_interval', 5.0)
        # procstat opens <LOGPATH>/<log id> with LOGPATH '.' (ProcMgr.spawnLogfile): relative to the directory it
        # runs in.  The web server resolves it in --procstat-logdir, default its own working directory.
        self.logdir = os.path.abspath(getattr(a, 'procstat_logdir', None) or '.')
        self.lock = threading.Lock()
        self.rows, self.seq, self.error, self.unknown = [], 0, None, None
        self.procMgr = None
        self.local_ids = []
        if self.cnf:
            self.cnf = os.path.abspath(self.cnf)
            if self.platform is None or self.platform < 0:
                from psdaq.procmgr.ProcMgr import deduce_platform
                self.platform = deduce_platform(self.cnf)
            threading.Thread(target=self._wrapper, name='procstat', daemon=True).start()

    # procstat: procMgrThreadWrapper / procMgrThread
    def _wrapper(self):
        try:
            self._thread()
        except Exception:
            report = ('procMgrThreadWrapper(): procMgrThread(ConfigFile = %s, Exp Id = %d, Exp Type = %s, '
                      'Platform = %d, Query Interval = %f ) Failed' % (self.cnf, 0, 'amo', self.platform,
                                                                       float(self.interval)))
            logger.error('%s\n%s', report, traceback.format_exc())
            with self.lock:
                self.unknown = {'title': 'Unknown Error', 'report': report,
                                'text': 'ProcStat is not updating the process status. Please check the log file '
                                        'for more details.'}

    def _thread(self):
        ProcMgr = loopback_procmgr_class()                # procServ connections only at 127.0.0.1 / ::1
        while True:
            err = None
            try:
                pm = ProcMgr(self.cnf, self.platform)
                rows = pm.getStatus()
                with self.lock:
                    self.procMgr = pm
            except IOError:
                rows = []
                err = {'title': 'ProcMgr IO Error',
                       'text': 'ProcMgr config file %s (platform %d) cannot be processed correctly, due to an IO '
                               'Error. Please check the input file format, or specify a new config file instead.'
                               % (self.cnf, self.platform)}
            except Exception:
                rows = []
                err = {'title': 'ProcMgr General Error',
                       'text': 'ProcMgr config file %s (platform %d) cannot be processed correctly, due to a general '
                               'Error. Please check the input file content, and the target machine status.'
                               % (self.cnf, self.platform)}
            out = []
            for d in rows:
                text, rgb = STATUS_TEXT.get(d['status'], (d['status'], None))
                out.append({'showId': _s(d['showId']), 'status': d['status'], 'text': text, 'rgb': rgb})
            with self.lock:
                self.rows, self.seq = out, self.seq + 1
                if err:
                    self.error = dict(err, seq=self.seq)
            time.sleep(self.interval)          # procstat:85, outside the try: a bad interval ends the thread

    def status(self, q):
        if not self.cnf:
            return 404, {'ok': False, 'err_info': 'server started without --procstat-cnf'}
        with self.lock:
            pm = self.procMgr
            local = []
            if pm is not None:
                local = [k.replace('localhost:', '') for k in pm.d.keys() if k.startswith('localhost:')]
            return 200, {'ok': True, 'cnf': self.cnf, 'platform': self.platform, 'interval': self.interval,
                         'seq': self.seq, 'rows': list(self.rows), 'error': self.error, 'unknown_error': self.unknown,
                         'local_ids': local}

    def _find(self, pm, uid):
        from psdaq.procmgr.ProcMgr import key2uniqueid
        for key in pm.d.keys():
            if key2uniqueid(key) == uid:
                return key
        return None

    def click(self, body):
        if not self.cnf:
            return 404, {'ok': False, 'err_info': 'server started without --procstat-cnf'}
        uid, mode = body.get('id'), body.get('mode')
        if not isinstance(uid, str) or mode not in ('console', 'logfile', 'restart'):
            return 400, {'ok': False, 'err_info': 'need id and mode console|logfile|restart'}
        with self.lock:
            pm = self.procMgr
        if pm is None:                                   # procstat:200: nothing before the first status
            return 200, {'ok': True, 'opened': False, 'why': 'no status yet'}
        from psdaq.procmgr.ProcMgr import key2host
        key = self._find(pm, uid)
        if mode == 'restart':
            local = [k.replace('localhost:', '') for k in pm.d.keys() if k.startswith('localhost:')]
            if uid in local:
                return 200, {'ok': True, 'warning': {'title': 'Not Supported',
                                                      'text': 'Local processes cannot be individually restarted'}}
            if key is None or key2host(key) not in LOOPBACK:
                return 200, {'ok': False, 'warning': {'title': 'Not Supported',
                                                       'text': 'the web GUI restarts only processes on this host'}}
            macro = pm.procmgr_macro
            pm.stop([uid], True)
            time.sleep(0.5)
            pm.start([uid], True, macro.get('LOGPATH'), int(macro.get('CORESIZE', 0)))
            return 200, {'ok': True, 'restarted': uid}
        if key is None:
            return 200, {'ok': True, 'opened': False, 'why': "process '%s' not found" % uid}
        st = pm.d[key][pm.DICT_STATUS]
        if st not in (pm.STATUS_RUNNING, pm.STATUS_SHUTDOWN):
            return 200, {'ok': True, 'opened': False, 'why': "process '%s' neither RUNNING nor SHUTDOWN" % uid}
        if mode == 'logfile':                           # ProcMgr.spawnLogfile
            path = os.path.join(self.logdir, pm.procmgr_macro.get('LOGPATH', '.'), _s(pm.d[key][pm.DICT_GETID]))
            if not os.path.exists(path):
                return 200, {'ok': True, 'opened': False, 'why': "process '%s' logfile not found" % uid}
            off = body.get('offset') or 0
            size = os.path.getsize(path)
            with open(path, 'rb') as f:
                f.seek(off if isinstance(off, int) and 0 <= off <= size else max(0, size - 200000))
                data = f.read(1 << 20)
            return 200, {'ok': True, 'opened': True, 'title': uid, 'path': path, 'size': size,
                         'offset': size, 'text': data.decode('utf-8', 'replace')}
        host, port = key2host(key), _s(pm.d[key][pm.DICT_CTRL])         # ProcMgr.spawnConsole
        if host not in LOOPBACK:
            return 200, {'ok': False, 'opened': False, 'why': 'host %s is not this host' % host}
        text = ''
        logfile = os.path.join(self.logdir, _s(pm.d[key][pm.DICT_GETID]))
        if os.path.exists(logfile):
            with open(logfile, 'rb') as f:
                text = f.read(1 << 20).decode('utf-8', 'replace')
        got = b''
        try:
            with socket.create_connection(('127.0.0.1', int(port)), timeout=2) as s:
                s.settimeout(0.3)
                end = time.time() + 1.5
                while time.time() < end:
                    try:
                        b = s.recv(65536)
                    except socket.timeout:
                        continue
                    if not b:
                        break
                    got += b
        except OSError as ex:
            got += ('[telnet 127.0.0.1 %s: %s]' % (port, ex)).encode()
        got = bytes(c for c in got if c < 0xf0)          # drop telnet IAC negotiation bytes
        return 200, {'ok': True, 'opened': True, 'title': uid, 'host': host, 'port': port,
                     'text': text + got.decode('utf-8', 'replace')}


def register(app, get_routes, post_routes):
    api = ProcStatApi(app)
    app.procstat_api = api
    get_routes['/api/procstat/status'] = api.status
    post_routes['/api/procstat/click'] = api.click
    return api
