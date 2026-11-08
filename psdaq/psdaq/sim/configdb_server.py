"""
Campaign-local stand-in for the configuration database web service.

psdaq.configdb.configdb talks to the config DB over HTTP: every call is a
GET of <url>/<root>/<command>/<args...>/ (with an optional JSON body) that
returns {"success": bool, "msg": str, "value": ...}.  This module serves
those commands from a JSON file, with the semantics of
psdaq.configdb.mongoconfigdb (versioned keys per hutch, aliases, device
configuration collections, history), so the DAQ can run with no mongod and
no facility web service.

Usage:
    python -m psdaq.sim.configdb_server --store /path/configdb.json --port 0

It binds to 127.0.0.1 only and prints the URL to pass to the DAQ, e.g.
    control -d http://127.0.0.1:<port>/ws/configDB ...
    control_gui --uris http://127.0.0.1:<port>/ws/ ...
Use a plain http:// URL: configdb.py only adds authentication when the URL
contains 'ws-auth' or 'ws-kerb'.
"""

import argparse
import copy
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

API_VERSION = {'major': 2, 'minor': 0, 'micro': 0}


class ConfigDbError(Exception):
    """An error reported to the client as {"success": false, "msg": ...}."""


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _plain(value):
    """Convert numpy scalars/arrays (from typed_json.cdict.get) to JSON types."""
    if hasattr(value, 'tolist'):
        return value.tolist()
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    return value


class JsonConfigStore(object):
    """A file-backed store with mongoconfigdb semantics.

    Layout of the file (one entry per database root, e.g. "configDB"):
        {"roots": {root: {"counters": {hutch: seq},
                          "hutches": {hutch: [alias document, ...]},
                          "device_configurations": [collection name, ...],
                          "collections": {name: [{"_id", "config"}, ...]},
                          "next_id": int}}}
    An alias document is {"date", "alias", "key", "devices": [{"device",
    "configs": [{"_id", "collection"}]}]}, exactly as mongoconfigdb stores it.
    """

    def __init__(self, path=None):
        self.path = path
        self.lock = threading.RLock()
        self.data = {'roots': {}}
        if path is not None and os.path.exists(path):
            with open(path) as f:
                self.data = json.load(f)

    def _save(self):
        if self.path is None:
            return
        tmp = self.path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(self.data, f, indent=1, sort_keys=True)
        os.replace(tmp, self.path)

    def _root(self, root):
        return self.data['roots'].setdefault(root, {
            'counters': {}, 'hutches': {}, 'device_configurations': [],
            'collections': {}, 'next_id': 0})

    @staticmethod
    def _docs(r, hutch):
        if hutch not in r['hutches']:
            raise ConfigDbError('No hutch %s' % hutch)
        return r['hutches'][hutch]

    @staticmethod
    def _alias_docs(docs, alias):
        return sorted((d for d in docs if d['alias'] == alias), key=lambda d: d['key'])

    def _new_key(self, r, hutch):
        if hutch not in r['counters']:
            raise ConfigDbError('Failed to get key for hutch %s' % hutch)
        r['counters'][hutch] += 1
        return r['counters'][hutch]

    def _resolve_key(self, r, hutch, key_or_alias):
        if isinstance(key_or_alias, int) or key_or_alias.isdigit():
            return int(key_or_alias)
        return self.get_key(r, hutch, key_or_alias)

    def _find_key(self, r, hutch, key):
        for d in self._docs(r, hutch):
            if d['key'] == key:
                return d
        raise ConfigDbError('No configuration with key %d in hutch %s' % (key, hutch))

    def _find_config(self, r, cfg):
        for d in r['collections'].get(cfg['collection'], []):
            if d['_id'] == cfg['_id']:
                return d['config']
        raise ConfigDbError('Dangling configuration %s' % cfg)

    def _save_device_config(self, r, collection, value):
        docs = r['collections'].get(collection)
        if not docs:
            raise ConfigDbError('save_device_config: No documents found for %s.' % collection)
        for d in docs:
            if d['config'] == value:
                return d['_id']
        r['next_id'] += 1
        oid = '%024x' % r['next_id']
        docs.append({'_id': oid, 'config': value})
        return oid

    # ---- commands (args are the URL path components after the command) ----

    def create_collections(self, r, hutch):
        r['hutches'].setdefault(hutch, [])
        r['counters'].setdefault(hutch, -1)

    def get_key(self, r, hutch, alias=None):
        if alias is None:
            return self._new_key(r, hutch)
        docs = self._alias_docs(self._docs(r, hutch), alias)
        if not docs:
            raise ConfigDbError('Failed to get key for alias/hutch: %s %s' % (alias, hutch))
        return docs[-1]['key']

    def add_alias(self, r, hutch, alias):
        docs = self._docs(r, hutch)
        if self._alias_docs(docs, alias):
            return None
        docs.append({'date': _now(), 'alias': alias,
                     'key': self._new_key(r, hutch), 'devices': []})

    def add_device_config(self, r, *args):
        cfg = args[-1]          # add_device_config/[<hutch>/]<cfg>/
        if r['collections'].get(cfg):
            return None
        r['collections'][cfg] = [{'_id': 'empty-' + cfg, 'config': {}}]
        if cfg not in r['device_configurations']:
            r['device_configurations'].append(cfg)

    def modify_device(self, r, hutch, alias, value):
        if not isinstance(value, dict):
            raise ConfigDbError('modify_device: value is not a dictionary!')
        for k in ('detType:RO', 'detName:RO'):
            if k not in value:
                raise ConfigDbError('modify_device: value has no %s set!' % k[:-3])
        docs = self._alias_docs(self._docs(r, hutch), alias)
        if not docs:
            raise ConfigDbError('modify_device: %s is not a configuration name!' % alias)
        device = value['detName:RO']
        collection = value['detType:RO']
        cfg = {'_id': self._save_device_config(r, collection, value),
               'collection': collection}
        c = copy.deepcopy(docs[-1])
        for entry in c['devices']:
            if entry['device'] == device:
                if entry['configs'] == [cfg]:
                    raise ConfigDbError('modify_device error: No config values changed.')
                c['devices'].remove(entry)
                break
        c['key'] = self._new_key(r, hutch)
        c['devices'].append({'device': device, 'configs': [cfg]})
        c['devices'].sort(key=lambda x: x['device'])
        c['date'] = _now()
        r['hutches'][hutch].append(c)
        return c['key']

    def get_configuration(self, r, hutch, key_or_alias, device):
        c = self._find_key(r, hutch, self._resolve_key(r, hutch, key_or_alias))
        for entry in c['devices']:
            if entry['device'] == device:
                return self._find_config(r, entry['configs'][0])
        raise ConfigDbError('get_configuration: No device %s!' % device)

    def get_history(self, r, hutch, alias, device, plist):
        from psdaq.configdb.typed_json import cdict
        out = []
        for c in self._alias_docs(self._docs(r, hutch), alias):
            for entry in c['devices']:
                if entry['device'] == device:
                    cl = cdict(self._find_config(r, entry['configs'][0]))
                    d = {'date': c['date'], 'key': c['key']}
                    for p in plist:
                        d[p] = _plain(cl.get(p))
                    out.append(d)
        return out

    def get_hutches(self, r):
        return list(r['counters'].keys())

    def get_aliases(self, r, hutch):
        seen = []
        for d in self._docs(r, hutch):
            if d['alias'] not in seen:
                seen.append(d['alias'])
        return seen

    def get_device_configs(self, r):
        return list(r['device_configurations'])

    def get_devices(self, r, hutch, key_or_alias):
        c = self._find_key(r, hutch, self._resolve_key(r, hutch, key_or_alias))
        return [entry['device'] for entry in c['devices']]

    def _modify_device_name(self, r, hutch, alias, device, newname):
        found = False
        for c in self._alias_docs(self._docs(r, hutch), alias):
            for entry in c['devices']:
                if entry['device'] == device:
                    break
            else:
                continue
            found = True
            if newname is None:
                c['devices'].remove(entry)
            else:
                old = entry['configs'][0]
                value = copy.deepcopy(self._find_config(r, old))
                value['detName:RO'] = newname
                entry['device'] = newname
                entry['configs'] = [{'_id': self._save_device_config(r, old['collection'], value),
                                     'collection': old['collection']}]
        if not found:
            raise ConfigDbError('%s_device: cannot find device %s in hutch %s, alias %s'
                                % ('remove' if newname is None else 'rename',
                                   device, hutch, alias))

    def remove_device(self, r, hutch, alias, device):
        self._modify_device_name(r, hutch, alias, device, None)

    def rename_device(self, r, hutch, alias, device, newname):
        for ch in '/.':
            if ch in newname:
                raise ConfigDbError("'%s' character not allowed in device names" % ch)
        self._modify_device_name(r, hutch, alias, device, newname)

    def print_configs(self, r, hutch):
        return '\n'.join(json.dumps(d, sort_keys=True) for d in self._docs(r, hutch))

    def print_device_configs(self, r, name='device_configurations'):
        if name == 'device_configurations':
            docs = [{'collection': c} for c in r['device_configurations']]
        else:
            docs = r['collections'].get(name, [])
        return '\n'.join(json.dumps(d, sort_keys=True) for d in docs)


# command -> (number of path args accepted, mutates the store)
COMMANDS = {
    'create_collections':   ((1,), True),
    'get_version':          ((0,), False),
    'get_key':              ((1,), True),    # bumps the hutch counter without ?alias=
    'add_alias':            ((2,), True),
    'add_device_config':    ((1, 2), True),
    'modify_device':        ((2,), True),
    'get_configuration':    ((3,), False),
    'get_history':          ((3,), False),
    'get_hutches':          ((0,), False),
    'get_aliases':          ((1,), False),
    'get_device_configs':   ((0,), False),
    'get_devices':          ((2,), False),
    'remove_device':        ((3,), True),
    'rename_device':        ((3,), True),
    'print_configs':        ((1,), False),
    'print_device_configs': ((0, 1), False),
}


def dispatch(store, path, body):
    """Run one request; return (http_status, response dict)."""
    url = urlsplit(path)
    parts = [p for p in url.path.split('/') if p]
    query = {k: v[-1] for k, v in parse_qs(url.query).items()}
    idx = next((i for i, p in enumerate(parts) if p in COMMANDS), None)
    if idx is None or idx == 0:
        return 404, {'success': False, 'msg': 'Unknown request %s' % url.path}
    root, cmd, args = parts[idx - 1], parts[idx], parts[idx + 1:]
    nargs, mutates = COMMANDS[cmd]
    if len(args) not in nargs:
        return 400, {'success': False,
                     'msg': '%s takes %s path arguments, got %d' % (cmd, nargs, len(args))}
    if cmd == 'get_version':
        return 200, {'success': True, 'msg': '', 'value': API_VERSION}
    if cmd == 'get_key' and 'alias' in query:
        args.append(query['alias'])
        mutates = False
    if cmd == 'rename_device':
        if 'newname' not in query:
            return 400, {'success': False, 'msg': 'rename_device needs ?newname='}
        args.append(query['newname'])
    if cmd == 'modify_device':
        args.append(body)
    if cmd == 'get_history':
        plist = body
        if isinstance(plist, str):          # webconfigdb.py sends a JSON string
            plist = json.loads(plist)
        args.append(plist or [])
    with store.lock:
        r = store._root(root)
        before = copy.deepcopy(r) if mutates else None
        try:
            value = getattr(store, cmd)(r, *args)
        except ConfigDbError as ex:
            if mutates:
                store.data['roots'][root] = before
            return 200, {'success': False, 'msg': str(ex), 'value': None}
        if mutates:
            store._save()
    return 200, {'success': True, 'msg': '', 'value': value}


class Handler(BaseHTTPRequestHandler):
    server_version = 'lcls2-sim-configdb/1'

    def _body(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n == 0:
            return None
        return json.loads(self.rfile.read(n).decode())

    def _reply(self, status, resp):
        data = json.dumps(resp, default=_plain).encode()
        # Log before replying: a client that has its answer can then always
        # read the record of its own request.
        if self.server.access_log is not None:
            rec = {'t': _now(), 'method': self.command, 'path': self.path,
                   'status': status, 'success': resp.get('success')}
            with self.server.log_lock, open(self.server.access_log, 'a') as f:
                f.write(json.dumps(rec) + '\n')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        try:
            status, resp = dispatch(self.server.store, self.path, self._body())
        except Exception as ex:             # keep serving; report the bug
            logger.exception('request %s failed', self.path)
            status, resp = 500, {'success': False, 'msg': '%s: %s' % (type(ex).__name__, ex)}
        self._reply(status, resp)

    do_POST = do_GET

    def log_message(self, fmt, *args):
        logger.debug('%s - %s', self.address_string(), fmt % args)


def make_server(store_path=None, host='127.0.0.1', port=0, access_log=None):
    """Create (but do not start) a server; port 0 picks a free port."""
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    srv.store = JsonConfigStore(store_path)
    srv.access_log = access_log
    srv.log_lock = threading.Lock()
    return srv


def server_url(srv):
    host, port = srv.server_address[:2]
    return 'http://%s:%d/ws/' % (host, port)


def main():
    parser = argparse.ArgumentParser(description='Local config DB web service stand-in')
    parser.add_argument('--store', required=True, help='JSON file holding the database')
    parser.add_argument('--host', default='127.0.0.1', help='bind address (default 127.0.0.1)')
    parser.add_argument('--port', type=int, default=0, help='port (default 0: pick a free one)')
    parser.add_argument('--url-file', help='write the base URL to this file once listening')
    parser.add_argument('--access-log', help='append one JSON line per request to this file')
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')

    srv = make_server(args.store, args.host, args.port, args.access_log)
    url = server_url(srv)
    if args.url_file:
        with open(args.url_file, 'w') as f:
            f.write(url + '\n')
    print('CONFIGDB_URL=%s' % url, flush=True)
    print('  control -d %sconfigDB    control_gui --uris %s' % (url, url), flush=True)

    signal.signal(signal.SIGTERM, lambda *a: threading.Thread(target=srv.shutdown).start())
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    srv.server_close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
