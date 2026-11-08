"""
Campaign-local stand-in for the run database / eLog web service that
psdaq.control.control calls in normal (non --sim) mode:

  GET  <url>/lgbk/ws/activeexperiment_for_instrument_station?instrument_name=&station=
  GET  <url>/lgbk/<exp>/ws/current_run
  POST <url>/run_control/<exp>/ws/start_run?run_type=<type>
  POST <url>/run_control/<exp>/ws/add_run_params                  (JSON dict)
  POST <url>/run_control/<exp>/ws/add_update_run_param_descriptions (JSON dict)
  POST <url>/run_control/<exp>/ws/end_run
  POST <url>/lgbk/<exp>/ws/register_file                          (JSON file report)

It keeps one experiment per instrument, numbers runs from 1, and appends
every request (with its body; never the password) to a JSONL log so a test
can check what the DAQ reported.

Usage:
    python -m psdaq.sim.lgbk_server --instrument tst --experiment tstx00001 \\
        --state /path/lgbk.json --log /path/lgbk.jsonl
    control --url http://127.0.0.1:<port>/ ...
The trailing '/' matters: control.py builds the register_file URL as
"{url}lgbk/...".
"""

import argparse
import base64
import datetime
import json
import logging
import os
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

logger = logging.getLogger(__name__)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class RunDb(object):
    """Runs of the experiments this stand-in serves, optionally kept in a file."""

    def __init__(self, experiments, path=None):
        self.experiments = dict(experiments)     # instrument -> experiment name
        self.path = path
        self.lock = threading.Lock()
        self.data = {'runs': {}, 'param_descs': {}}
        if path is not None and os.path.exists(path):
            with open(path) as f:
                self.data = json.load(f)
        for exp in self.experiments.values():
            self.data['runs'].setdefault(exp, [])
            self.data['param_descs'].setdefault(exp, {})

    def _save(self):
        if self.path is None:
            return
        tmp = self.path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(self.data, f, indent=1, sort_keys=True)
        os.replace(tmp, self.path)

    def runs(self, exp):
        if exp not in self.data['runs']:
            raise KeyError(exp)
        return self.data['runs'][exp]

    def _open_run(self, exp):
        runs = self.runs(exp)
        if not runs or runs[-1]['end_time'] is not None:
            return None
        return runs[-1]

    # ---- requests; each returns (http status, response dict) ----

    def activeexperiment_for_instrument_station(self, query):
        inst = query.get('instrument_name')
        if inst not in self.experiments:
            return 404, {'success': False, 'msg': 'No active experiment for %s' % inst}
        return 200, {'success': True, 'value': {
            'name': self.experiments[inst], 'instrument': inst,
            'station': int(query.get('station', 0))}}

    def current_run(self, exp):
        runs = self.runs(exp)
        return 200, {'success': True, 'value': runs[-1] if runs else None}

    def start_run(self, exp, query):
        runs = self.runs(exp)
        prev = self._open_run(exp)
        if prev is not None:                    # the real service closes it too
            prev['end_time'] = _now()
        run = {'num': runs[-1]['num'] + 1 if runs else 1, 'type': query.get('run_type', 'DATA'),
               'begin_time': _now(), 'end_time': None, 'params': {}, 'files': []}
        runs.append(run)
        return 200, {'success': True, 'value': run}

    def end_run(self, exp):
        run = self._open_run(exp)
        if run is None:
            return 200, {'success': False, 'msg': 'No open run in %s' % exp}
        run['end_time'] = _now()
        return 200, {'success': True, 'value': run}

    def add_run_params(self, exp, body):
        run = self._open_run(exp)
        if run is None or not isinstance(body, dict):
            return 200, {'success': False, 'msg': 'No open run in %s or bad body' % exp}
        run['params'].update(body)
        return 200, {'success': True, 'value': len(body)}

    def add_update_run_param_descriptions(self, exp, body):
        self.runs(exp)
        if not isinstance(body, dict):
            return 200, {'success': False, 'msg': 'bad body'}
        self.data['param_descs'][exp].update(body)
        return 200, {'success': True, 'value': len(body)}

    def register_file(self, exp, body):
        runs = self.runs(exp)
        if not isinstance(body, dict) or 'path' not in body:
            return 200, {'success': False, 'msg': 'register_file needs a path'}
        num = body.get('run_num')
        run = next((r for r in runs if r['num'] == num), runs[-1] if runs else None)
        if run is None:
            return 200, {'success': False, 'msg': 'No run in %s' % exp}
        run['files'].append(body)
        return 200, {'success': True, 'value': None}


def dispatch(db, method, path, body):
    """Route one request; return (http status, response dict)."""
    url = urlsplit(path)
    parts = [p for p in url.path.split('/') if p]
    query = {k: v[-1] for k, v in parse_qs(url.query).items()}
    cmd = parts[-1] if parts else ''
    try:
        with db.lock:
            if parts[-3:] == ['lgbk', 'ws', 'activeexperiment_for_instrument_station']:
                return db.activeexperiment_for_instrument_station(query)
            if len(parts) < 4 or parts[-2] != 'ws' or parts[-4] not in ('lgbk', 'run_control'):
                return 404, {'success': False, 'msg': 'Unknown request %s' % url.path}
            service, exp = parts[-4], parts[-3]
            if service == 'lgbk' and cmd == 'current_run' and method == 'GET':
                return db.current_run(exp)
            routes = {('lgbk', 'register_file'): lambda: db.register_file(exp, body),
                      ('run_control', 'start_run'): lambda: db.start_run(exp, query),
                      ('run_control', 'end_run'): lambda: db.end_run(exp),
                      ('run_control', 'add_run_params'): lambda: db.add_run_params(exp, body),
                      ('run_control', 'add_update_run_param_descriptions'):
                          lambda: db.add_update_run_param_descriptions(exp, body)}
            if method != 'POST' or (service, cmd) not in routes:
                return 404, {'success': False, 'msg': 'Unknown request %s %s' % (method, url.path)}
            status, resp = routes[(service, cmd)]()
            if resp.get('success'):
                db._save()
            return status, resp
    except KeyError as ex:
        return 404, {'success': False, 'msg': 'Unknown experiment %s' % ex}


class Handler(BaseHTTPRequestHandler):
    server_version = 'lcls2-sim-lgbk/1'

    def _user(self):
        auth = self.headers.get('Authorization', '')
        if auth.startswith('Basic '):
            try:
                return base64.b64decode(auth[6:]).decode().split(':', 1)[0]
            except Exception:
                return '?'
        return None

    def _handle(self):
        n = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(n).decode() if n else ''
        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            body = raw
        try:
            status, resp = dispatch(self.server.db, self.command, self.path, body)
        except Exception as ex:
            logger.exception('request %s failed', self.path)
            status, resp = 500, {'success': False, 'msg': '%s: %s' % (type(ex).__name__, ex)}
        data = json.dumps(resp).encode()
        rec = {'t': _now(), 'method': self.command, 'path': self.path, 'user': self._user(),
               'body': body, 'status': status, 'response': resp}
        logger.info('%s %s -> %d %s', self.command, self.path, status, resp.get('success'))
        if self.server.log_path is not None:
            with self.server.log_lock, open(self.server.log_path, 'a') as f:
                f.write(json.dumps(rec) + '\n')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = _handle
    do_POST = _handle

    def log_message(self, fmt, *args):
        logger.debug('%s - %s', self.address_string(), fmt % args)


def make_server(experiments, state_path=None, log_path=None, host='127.0.0.1', port=0):
    """experiments: {instrument: experiment name}. Port 0 picks a free port."""
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    srv.db = RunDb(experiments, state_path)
    srv.log_path = log_path
    srv.log_lock = threading.Lock()
    return srv


def server_url(srv):
    host, port = srv.server_address[:2]
    return 'http://%s:%d/' % (host, port)


def main():
    parser = argparse.ArgumentParser(description='Local run database / eLog stand-in')
    parser.add_argument('--instrument', default='tst')
    parser.add_argument('--experiment', default='tstx00001',
                        help='experiment reported as active for --instrument')
    parser.add_argument('--state', help='JSON file keeping runs across restarts')
    parser.add_argument('--log', help='append one JSON line per request to this file')
    parser.add_argument('--host', default='127.0.0.1', help='bind address (default 127.0.0.1)')
    parser.add_argument('--port', type=int, default=0, help='port (default 0: pick a free one)')
    parser.add_argument('--url-file', help='write the base URL to this file once listening')
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')

    srv = make_server({args.instrument: args.experiment}, args.state, args.log,
                      args.host, args.port)
    url = server_url(srv)
    if args.url_file:
        with open(args.url_file, 'w') as f:
            f.write(url + '\n')
    print('LGBK_URL=%s' % url, flush=True)
    print('  control --url %s ...' % url, flush=True)

    signal.signal(signal.SIGTERM, lambda *a: threading.Thread(target=srv.shutdown).start())
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    srv.server_close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
