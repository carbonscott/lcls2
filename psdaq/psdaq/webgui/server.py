"""DAQ control web GUI server (v0).

A browser front end for the DAQ control level, beside the PyQt control_gui.
Standard library only: http.server + Server-Sent Events for status push,
JSON POST for commands. Binds 127.0.0.1 only.

    python -m psdaq.webgui.server -p 6 -H 127.0.0.1          # real DAQ (DaqControl)
    python -m psdaq.webgui.server --emulate                  # emulator, no DAQ
    python -m psdaq.webgui.server -p 5 --events-source pva --events-pvbase DAQ:SIM   # + XPM NumL0Acc
    daq_webgui --emulate --port 0                            # console script; port 0 = pick a free port

Then open http://127.0.0.1:<port>/ (from another machine: ssh -L <port>:127.0.0.1:<port> <node>).
See psdaq/psdaq/webgui/README.md for the HTTP API.
"""

import argparse
import collections
import json
import logging
import mimetypes
import os
import queue
import signal
import socket
import sys
import threading
import importlib
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs

from psdaq.control.ControlDef import ControlDef
from psdaq.webgui.netguard import NonLoopbackError, require_loopback_host, is_loopback_host, \
    require_loopback_pva_env

# Extension modules add API routes without editing this file. Each one defines
# register(app, get_routes, post_routes): get_routes maps a path to
# fn(query_dict) -> (code, body); post_routes maps a path to fn(body) -> (code, body).
EXT_MODULES = ('psdaq.webgui.configdb_api', 'psdaq.webgui.procstat_api', 'psdaq.webgui.pvgui_api',
               'psdaq.webgui.dpm_api', 'psdaq.webgui.datadev_api', 'psdaq.webgui.daqstat_api')


def load_extensions(app, names=EXT_MODULES):
    get_routes, post_routes = {}, {}
    for name in names:
        try:
            mod = importlib.import_module(name)
        except ImportError as ex:
            if getattr(ex, 'name', None) == name:
                continue            # extension not present in this tree
            raise
        mod.register(app, get_routes, post_routes)
    return get_routes, post_routes

logger = logging.getLogger('daq_webgui')

VERSION = 'webgui-v0'
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
STATUS_KEYS = ('transition', 'state', 'config_alias', 'recording', 'platform', 'bypass_activedet',
               'experiment_name', 'run_number', 'last_run_number')


class Hub:
    """Shared state: cached control status, log ring, event count, SSE subscribers."""

    def __init__(self, log_size=2000):
        self.lock = threading.Lock()
        self.status = {k: None for k in STATUS_KEYS}
        self.status['platform'] = {}
        self.instrument = None
        self.progress = None
        self.events = {'events': None, 'drops': None, 'ok': True, 'error': None, 'source': 'none', 'ts': None}
        self.log = collections.deque(maxlen=log_size)
        self.seq = 0
        self.subs = []
        self.after_reset = False   # CGWMainControl.state_is_after_reset

    # ---- fan-out ----
    def subscribe(self):
        q = queue.Queue(maxsize=1000)
        with self.lock:
            self.subs.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.subs:
                self.subs.remove(q)

    def broadcast(self, event, data):
        with self.lock:
            subs = list(self.subs)
        for q in subs:
            try:
                q.put_nowait((event, data))
            except queue.Full:
                self.unsubscribe(q)

    # ---- log ----
    def add_log(self, level, msg):
        with self.lock:
            self.seq += 1
            rec = {'seq': self.seq, 'ts': time.time(), 'level': level, 'msg': msg}
            self.log.append(rec)
        getattr(logger, {'SEP': 'info'}.get(level, level.lower()), logger.info)(msg)
        self.broadcast('log', rec)
        return rec

    def snapshot(self):
        with self.lock:
            st = dict(self.status)
            st['instrument'] = self.instrument
            st['progress'] = self.progress
            return st

    # ---- control messages (front_pub), handled as CGWMain.process_zmq_message ----
    def on_control_message(self, msg):
        try:
            key = msg['header']['key']
            body = msg.get('body', {}) or {}
        except Exception:
            self.add_log('WARNING', 'unparsable control message: %r' % (msg,))
            return
        if key == 'status':
            with self.lock:
                for k in STATUS_KEYS:
                    if k == 'platform':
                        if body.get('platform') is not None:
                            self.status['platform'] = body['platform']
                    else:
                        self.status[k] = body.get(k)
                self.progress = None
            self.add_log('INFO', 'zmq msg transition:%s state:%s config:%s recording:%s'
                         % (body.get('transition'), body.get('state'), body.get('config_alias'), body.get('recording')))
            self.broadcast('status', self.snapshot())
        elif key == 'error':
            self.add_log('ERROR', str(body.get('err_info')))
        elif key == 'warning':
            self.add_log('WARNING', str(body.get('err_info')))
        elif key == 'progress':
            with self.lock:
                self.progress = {'transition': body.get('transition'), 'elapsed': body.get('elapsed'),
                                 'total': body.get('total'), 'ts': time.time()}
                p = dict(self.progress)
            self.broadcast('progress', p)
        elif key == 'fileReport':
            self.add_log('INFO', 'fileReport: %s' % body.get('path'))
        elif key == 'step':
            self.add_log('INFO', 'step done: %s' % body.get('step_done'))
        else:
            self.add_log('DEBUG', 'received json: %s' % json.dumps(msg, sort_keys=False))

    def set_events(self, ev):
        with self.lock:
            keys = ('events', 'drops', 'ok', 'error', 'final')
            old = {k: self.events.get(k) for k in keys}
            self.events = ev
            changed = old != {k: ev.get(k) for k in keys}
        if changed:
            self.broadcast('events', ev)


class App:
    def __init__(self, args, backend, events_source):
        self.args = args
        self.backend = backend
        self.events_source = events_source
        self.ext_get, self.ext_post = load_extensions(self)
        self.hub = Hub()
        bind = getattr(events_source, 'bind', None)
        if bind is not None:
            bind(self.hub)          # sources that need control's state (PvaCountEvents' latch)
        self.aliases = []
        self.aliases_source = None
        self._stop = threading.Event()

    def start(self):
        self.backend.connect()
        self.backend.start(self.hub.on_control_message)
        ctl = self.backend.ctl
        # CGWMain.init_daq_control_parameters: getStatus + getInstrument
        st = ctl.getStatus()
        with self.hub.lock:
            for k, v in zip(STATUS_KEYS, st):
                self.hub.status[k] = v
            if not isinstance(self.hub.status.get('platform'), dict):
                self.hub.status['platform'] = {}
        self.hub.instrument = ctl.getInstrument()
        if self.hub.instrument is None:
            self.hub.add_log('WARNING', 'instrument is None')
        self.aliases, self.aliases_source = self.backend.aliases(self.hub.instrument)
        self.hub.add_log('INFO', 'web GUI %s started: backend=%s state=%s instrument=%s aliases=%s (%s)'
                         % (VERSION, self.backend.name, self.hub.status['state'], self.hub.instrument,
                            self.aliases, self.aliases_source))
        t = threading.Thread(target=self._poll_events, name='events-poll', daemon=True)
        t.start()

    def stop(self):
        self._stop.set()
        self.backend.stop()

    def _poll_events(self):
        while not self._stop.is_set():
            try:
                ev = dict(self.events_source.poll())
            except Exception as ex:
                ev = {'events': None, 'drops': None, 'ok': False, 'error': str(ex)}
            ev['source'] = self.events_source.name
            if ev.get('ts') is None:
                ev['ts'] = time.time()
            self.hub.set_events(ev)
            self._stop.wait(self.args.events_period)

    def meta(self):
        return {'version': VERSION, 'backend': self.backend.name, 'states': ControlDef.states,
                'transitions': ControlDef.transitions, 'aliases': self.aliases,
                'aliases_source': self.aliases_source, 'platform_number': self.args.platform,
                'endpoints': self.backend.endpoints(), 'events_source': self.events_source.name,
                'readout_groups': [str(v) for v in range(8)]}   # CGWPartitionTable.LIST_OF_VALUES

    # ---- commands ----
    def _result(self, what, err):
        if err:
            self.hub.add_log('ERROR', '%s: %s' % (what, err))
        return {'ok': not err, 'err_info': err or None}

    def cmd_state(self, body):
        state = str(body.get('state', '')).lower()
        if state not in ControlDef.states:
            return 400, {'ok': False, 'err_info': 'unknown state %r' % state}
        if self.hub.after_reset:
            self.hub.add_log('SEP', 50 * '_')
        self.hub.after_reset = (state == 'reset')
        self.hub.add_log('INFO', '-> daq_control_set_state(%s)' % state)
        return 200, self._result('setState(%s)' % state, self.backend.ctl.setState(state))

    def cmd_transition(self, body):
        tr = str(body.get('transition', ''))
        if tr not in ControlDef.transitions:
            return 400, {'ok': False, 'err_info': 'unknown transition %r' % tr}
        self.hub.add_log('INFO', '-> setTransition(%s)' % tr)
        return 200, self._result('setTransition(%s)' % tr, self.backend.ctl.setTransition(tr))

    def cmd_record(self, body):
        rec = body.get('record')
        if not isinstance(rec, bool):
            return 400, {'ok': False, 'err_info': 'record must be true or false'}
        self.hub.add_log('INFO', '-> daq_control_set_record(%s)' % rec)
        return 200, self._result('setRecord(%s)' % rec, self.backend.ctl.setRecord(rec))

    def cmd_config(self, body):
        alias = body.get('alias')
        if not isinstance(alias, str) or not alias or '.' in alias:
            return 400, {'ok': False, 'err_info': 'bad alias %r' % (alias,)}
        self.hub.add_log('INFO', '-> setConfig(%s)' % alias)
        return 200, self._result('setConfig("%s")' % alias, self.backend.ctl.setConfig(alias))

    def cmd_platform(self, body):
        """QWPopupTableCheck.onApply: set_platform -> selectPlatform, then setState('allocated')."""
        plat = body.get('platform')
        if not isinstance(plat, dict):
            return 400, {'ok': False, 'err_info': 'platform must be an object'}
        self.hub.add_log('INFO', '-> selectPlatform(%s)' % json.dumps(plat, sort_keys=True))
        rep = self.backend.ctl.selectPlatform(plat)
        err = rep.get('err_info') if isinstance(rep, dict) else None
        if err:
            return 200, self._result('selectPlatform', err)
        if body.get('allocate', True):
            active = [1 for lvl in plat.values() for p in lvl.values() if p.get('active')]
            if not active:
                self.hub.add_log('WARNING', 'NO PROCESS SELECTED!')
            else:
                self.hub.add_log('INFO', '-> daq_control_set_state(allocated)')
                return 200, self._result('setState(allocated)', self.backend.ctl.setState('allocated'))
        return 200, {'ok': True, 'err_info': None}


def make_handler(app):
    hub = app.hub

    class Handler(BaseHTTPRequestHandler):
        server_version = 'daq_webgui/' + VERSION
        protocol_version = 'HTTP/1.1'

        def log_message(self, fmt, *a):
            logger.debug('%s %s' % (self.address_string(), fmt % a))

        # ---- helpers ----
        def _host_ok(self):
            """Refuse requests whose Host header is not loopback (DNS rebinding guard)."""
            host = (self.headers.get('Host') or '').strip()
            name = host.rsplit(':', 1)[0] if not host.startswith('[') else host.split(']')[0] + ']'
            return is_loopback_host(name)

        def _send(self, code, body, ctype='application/json', extra=None):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _static(self, rel):
            rel = rel.lstrip('/') or 'index.html'
            path = os.path.realpath(os.path.join(STATIC_DIR, rel))
            if not path.startswith(os.path.realpath(STATIC_DIR) + os.sep) or not os.path.isfile(path):
                return self._send(404, {'error': 'not found'})
            ctype = mimetypes.guess_type(path)[0] or 'application/octet-stream'
            if ctype.startswith('text/') or ctype in ('application/javascript',):
                ctype += '; charset=utf-8'
            with open(path, 'rb') as f:
                self._send(200, f.read(), ctype)

        # ---- GET ----
        def do_GET(self):
            if not self._host_ok():
                return self._send(403, {'error': 'Host header must be loopback'})
            u = urlsplit(self.path)
            p = u.path
            if p == '/' or p == '/index.html':
                return self._static('index.html')
            if p.startswith('/static/'):
                return self._static(p[len('/static/'):])
            if p.startswith('/gui/') and p.count('/') == 2 and p[5:].isidentifier():
                return self._static('gui/%s.html' % p[5:])      # web copies of the other PyQt GUIs
            if p == '/api/meta':
                return self._send(200, app.meta())
            if p == '/api/status':
                return self._send(200, hub.snapshot())
            if p == '/api/platform':
                plat = hub.snapshot().get('platform') or app.backend.ctl.getPlatform()
                return self._send(200, plat)
            if p == '/api/aliases':
                return self._send(200, {'aliases': app.aliases, 'source': app.aliases_source})
            if p == '/api/events':
                with hub.lock:
                    return self._send(200, dict(hub.events))
            if p == '/api/log':
                since = int(parse_qs(u.query).get('since', ['0'])[0] or 0)
                with hub.lock:
                    recs = [r for r in hub.log if r['seq'] > since]
                return self._send(200, {'records': recs})
            if p == '/api/stream':
                return self._stream()
            fn = app.ext_get.get(p)
            if fn is not None:
                try:
                    code, rep = fn(parse_qs(u.query))
                except Exception as ex:
                    logger.exception('extension GET failed')
                    code, rep = 500, {'ok': False, 'err_info': 'server error: %s' % ex}
                return self._send(code, rep)
            return self._send(404, {'error': 'not found'})

        def _stream(self):
            q = hub.subscribe()
            try:
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Connection', 'keep-alive')
                self.end_headers()
                with hub.lock:
                    tail = list(hub.log)[-500:]
                    ev = dict(hub.events)
                hello = {'status': hub.snapshot(), 'events': ev, 'log': tail, 'meta': app.meta()}
                self._sse('hello', hello)
                while True:
                    try:
                        event, data = q.get(timeout=15)
                    except queue.Empty:
                        self.wfile.write(b': keepalive\n\n')
                        self.wfile.flush()
                        continue
                    self._sse(event, data)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                hub.unsubscribe(q)
                self.close_connection = True

        def _sse(self, event, data):
            self.wfile.write(('event: %s\ndata: %s\n\n' % (event, json.dumps(data))).encode())
            self.wfile.flush()

        # ---- POST ----
        def do_POST(self):
            if not self._host_ok():
                return self._send(403, {'error': 'Host header must be loopback'})
            origin = self.headers.get('Origin')
            if origin and origin != 'null':
                if urlsplit(origin).netloc != self.headers.get('Host'):
                    return self._send(403, {'error': 'cross-origin request refused'})
            if not (self.headers.get('Content-Type') or '').startswith('application/json'):
                return self._send(415, {'error': 'Content-Type must be application/json'})
            try:
                n = int(self.headers.get('Content-Length') or 0)
                body = json.loads(self.rfile.read(n) or b'{}')
                if not isinstance(body, dict):
                    raise ValueError('body must be a JSON object')
            except Exception as ex:
                return self._send(400, {'ok': False, 'err_info': 'bad JSON: %s' % ex})
            routes = {'/api/state': app.cmd_state, '/api/transition': app.cmd_transition,
                      '/api/record': app.cmd_record, '/api/config': app.cmd_config,
                      '/api/platform': app.cmd_platform}
            routes.update(app.ext_post)
            fn = routes.get(urlsplit(self.path).path)
            if fn is None:
                return self._send(404, {'error': 'not found'})
            try:
                code, rep = fn(body)
            except Exception as ex:
                logger.exception('command failed')
                code, rep = 500, {'ok': False, 'err_info': 'server error: %s' % ex}
            return self._send(code, rep)

    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class Server6(Server):
    address_family = socket.AF_INET6


def build_parser():
    p = argparse.ArgumentParser(prog='daq_webgui', description='DAQ control web GUI server (binds 127.0.0.1 only)')
    p.add_argument('--bind', default='127.0.0.1', help='listen address; must be loopback (default 127.0.0.1)')
    p.add_argument('--port', type=int, default=8650, help='listen port, 0 = any free port (default 8650)')
    p.add_argument('--port-file', help='write the bound port number to this file')
    p.add_argument('-p', '--platform', type=int, default=6, help='DAQ platform [0-7] (default 6, as control_gui)')
    p.add_argument('-H', '--host', default='127.0.0.1', help='control host; must be loopback (default 127.0.0.1)')
    p.add_argument('-t', '--timeout', type=int, default=60000, help='DaqControl timeout [ms] (default 60000)')
    p.add_argument('--configdb-url', default=None,
                   help='config DB URL, loopback only, e.g. http://127.0.0.1:<port>/ws/ (default: none, '
                        'aliases fall back to NOBEAM/BEAM)')
    p.add_argument('--configdb-root', default='configDB')
    p.add_argument('--user', default='tstopr', help='config DB user')
    p.add_argument('--emulate', action='store_true', help='use the built-in emulator instead of DaqControl')
    p.add_argument('--emulate-fail', default=None, metavar='TRANSITION',
                   help='emulator: make this transition fail (to prove tests can fail)')
    p.add_argument('--emulate-rate', type=float, default=500.0, help='emulator: L1Accept rate in running [Hz]')
    p.add_argument('--emulate-slow', type=float, default=0.6,
                   help='emulator: duration of configure/beginrun with progress messages [s]')
    p.add_argument('--events-source', choices=('auto', 'none', 'emulator', 'prometheus', 'pva'), default='auto',
                   help='events counter source (auto = emulator with --emulate, else none; pva = the XPM '
                        'partition counter NumL0Acc over PV Access, needs a loopback-only EPICS_PVA env)')
    p.add_argument('--events-pv', default=None,
                   help='pva: counter PV (default <pvbase>:XPM:<xpm>:PART:<group>:NumL0Acc)')
    p.add_argument('--events-pvbase', default=None, help='pva: XPM PV base, as control -B (e.g. DAQ:SIM)')
    p.add_argument('--events-xpm', default='0', help='pva: XPM number, as control -x (default 0)')
    p.add_argument('--events-group', type=int, default=None, help='pva: readout group (default: the platform)')
    p.add_argument('--events-drops-pv', default=None,
                   help='pva: input-trigger PV; drops = it - events (default: NumL0Inp beside the counter PV; '
                        '"none" to disable)')
    p.add_argument('--events-url', default=None, help='prometheus: loopback metrics URL')
    p.add_argument('--events-metric', default=None, help='prometheus: metric name to sum')
    p.add_argument('--events-drops-metric', default=None, help='prometheus: metric name for drops')
    p.add_argument('--events-labels', default='', help='prometheus: label filter k=v,k2=v2')
    p.add_argument('--events-period', type=float, default=1.0, help='events poll period [s]')
    p.add_argument('--procstat-cnf', default=None,
                   help='/gui/procstat: the procmgr .cnf whose processes it shows (as procstat <cnf>)')
    p.add_argument('--procstat-platform', type=int, default=-1, help='/gui/procstat: platform (procstat -p; '
                   'default: deduced from the .cnf)')
    p.add_argument('--procstat-interval', type=float, default=5.0, help='/gui/procstat: query interval [s] '
                   '(procstat -i, default 5)')
    p.add_argument('--procstat-logdir', default=None, help='/gui/procstat: the directory procstat would run in; '
                   'the log ids ProcMgr reports are relative to it (default: the working directory)')
    p.add_argument('--pvgui', action='append', default=[], metavar="NAME:ARGS",
                   help="/gui/<NAME>: web copy of a pvedit GUI with the PyQt program's arguments, e.g. "
                        "'groupca:DAQ:SIM 0 5' (repeatable; PVs through one PV Access client, needs a "
                        "loopback-only EPICS_PVA env, as --events-source pva)")
    p.add_argument('--dpm', default=None, metavar='ARGS',
                   help="/gui/detector_protection_monitor: web copy of trigger/detector_protection_monitor.py with the "
                        "PyQt program's arguments, e.g. '-b DAQ:SIM:JF16M:BLOCKER -d Jungfrau' (Channel Access, "
                        "loopback EPICS_CA_* env only)")
    p.add_argument('--daqstat-cnf', default=None, help='/gui/daqstat: the daqmgr .cnf whose jobs it shows (as daqstat <cnf>)')
    p.add_argument('--daqstat-slurm', default=None, metavar='STATE',
                   help='/gui/daqstat: the psdaq.sim.simslurm state file that answers its Slurm commands (required)')
    p.add_argument('--daqstat-interval', type=float, default=5.0, help='/gui/daqstat: query interval [s] (daqstat -i)')
    p.add_argument('--datadev-sim', default=None, metavar='ROOT',
                   help='/gui/datadev_monitor: web copy of cas/datadev_monitor.py on the simulated nodes of a '
                        'psdaq.sim.simdatadev root (it never starts ssh)')
    p.add_argument('--print-config', action='store_true', help='print every endpoint as JSON and exit')
    p.add_argument('-l', '--loglevel', default='INFO')
    return p


def configure(args):
    """Validate every address before anything is opened; return (backend, events_source)."""
    from psdaq.webgui.backend import RealBackend, EmulatorBackend
    from psdaq.webgui import events as ev
    require_loopback_host(args.bind, '--bind')
    if args.procstat_cnf:
        from psdaq.webgui.procstat_api import require_loopback_cnf
        require_loopback_cnf(args.procstat_cnf, args.procstat_platform)    # every process's host is loopback
    if args.emulate:
        backend = EmulatorBackend(fail_transition=args.emulate_fail, l1_rate=args.emulate_rate,
                                  slow_transition_time=args.emulate_slow)
        if args.configdb_url:
            from psdaq.webgui.netguard import require_loopback_url
            require_loopback_url(args.configdb_url, '--configdb-url')
    else:
        backend = RealBackend(host=args.host, platform=args.platform, timeout=args.timeout,
                              configdb_url=args.configdb_url, configdb_root=args.configdb_root,
                              user=args.user, password=os.getenv('CONFIGDB_AUTH'))
    src = args.events_source
    if src == 'auto':
        src = 'emulator' if args.emulate else ('prometheus' if args.events_url else 'none')
    if src == 'prometheus':
        if not (args.events_url and args.events_metric):
            raise SystemExit('daq_webgui: --events-source prometheus needs --events-url and --events-metric')
        events_source = ev.PrometheusTextEvents(args.events_url, args.events_metric,
                                                ev.parse_labels(args.events_labels), args.events_drops_metric)
    elif src == 'pva':
        conf = require_loopback_pva_env(os.environ, '--events-source pva')   # NonLoopbackError -> exit 2
        pv, drops_pv = pva_pvs(args)
        events_source = ev.PvaCountEvents(pv, conf, drops_pv)
    elif src == 'emulator':
        if not args.emulate:
            raise SystemExit('daq_webgui: --events-source emulator needs --emulate')
        events_source = None   # bound after the emulator exists
    else:
        events_source = ev.NoEvents()
    return backend, events_source, src


def pva_pvs(args):
    """(counter PV, drops PV or None) for --events-source pva."""
    from psdaq.webgui.events import xpm_count_pv
    group = args.platform if args.events_group is None else args.events_group
    pv = args.events_pv
    if not pv:
        if not args.events_pvbase:
            raise SystemExit('daq_webgui: --events-source pva needs --events-pv or --events-pvbase')
        pv = xpm_count_pv(args.events_pvbase, args.events_xpm, group)
    drops = args.events_drops_pv
    if drops is None and pv.endswith(':NumL0Acc'):
        drops = pv[:-len('NumL0Acc')] + 'NumL0Inp'
    return pv, (None if drops in (None, '', 'none') else drops)


def config_report(args, backend, src):
    eps = {'listen': 'http://%s:%d/' % (args.bind, args.port), 'backend': backend.name}
    eps.update(backend.endpoints())
    if args.configdb_url:
        eps['configdb'] = args.configdb_url
    if src == 'prometheus':
        eps['events'] = args.events_url
    if src == 'pva':
        eps['events_pv'], eps['events_drops_pv'] = pva_pvs(args)
        eps['events_pva_conf'] = require_loopback_pva_env(os.environ, '--events-source pva')
    eps['events_source'] = src
    hosts = []
    for k, v in eps.items():
        if isinstance(v, str) and '://' in v:
            hosts.append(urlsplit(v).hostname)
    eps['all_loopback'] = all(is_loopback_host(h) for h in hosts)
    return eps


def main(argv=None):
    args = build_parser().parse_args(argv)
    logging.basicConfig(format='%(asctime)s %(name)s %(levelname)s: %(message)s',
                        level=getattr(logging, args.loglevel.upper(), logging.INFO))
    # never route local requests (config DB, metrics) through a proxy
    for k in ('NO_PROXY', 'no_proxy'):
        cur = [x for x in os.environ.get(k, '').split(',') if x]
        os.environ[k] = ','.join(cur + [h for h in ('127.0.0.1', 'localhost', '::1') if h not in cur])
    try:
        backend, events_source, src = configure(args)
    except NonLoopbackError as ex:
        print('daq_webgui: %s' % ex, file=sys.stderr)
        return 2
    if args.print_config:
        print(json.dumps(config_report(args, backend, src), indent=2))
        return 0

    try:
        httpd = (Server6 if ':' in args.bind else Server)((args.bind, args.port), None)
    except OSError as ex:
        print('daq_webgui: cannot listen on %s:%d: %s' % (args.bind, args.port, ex), file=sys.stderr)
        return 1
    if src == 'emulator':
        from psdaq.webgui.events import EmulatorEvents

        class _Late:
            name = 'emulator'

            def poll(self):
                return EmulatorEvents(backend.ctl).poll()
        events_source = _Late()
    app = App(args, backend, events_source)
    httpd.RequestHandlerClass = make_handler(app)
    app.start()
    port = httpd.server_address[1]
    if args.port_file:
        with open(args.port_file, 'w') as f:
            f.write('%d\n' % port)
    print('daq_webgui: listening on http://%s:%d/ backend=%s events=%s' % (args.bind, port, backend.name, src),
          flush=True)

    def _term(signum, frame):
        threading.Thread(target=httpd.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, _term)
    signal.signal(signal.SIGINT, _term)
    try:
        httpd.serve_forever(poll_interval=0.5)
    finally:
        app.stop()
        httpd.server_close()
    print('daq_webgui: stopped', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
