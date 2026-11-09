"""Web copies of the pvedit-based PyQt GUIs (groupca, ...): an extension of psdaq.webgui.server.

The server is started with  --pvgui '<name>:<the PyQt program's arguments>'  (repeatable), e.g.
--pvgui 'groupca:DAQ:SIM 0 5' for `groupca DAQ:SIM 0 5`.  Each page is built by psdaq.webgui.pvgui.<name>
(no Qt) and served at /gui/pvgui?gui=<name> (static/gui/pvgui.html renders any page tree).  The PVs are
read and written by one p4p PV Access client in this process, created only after
netguard.require_loopback_pva_env accepted the environment (EPICS_PVA_AUTO_ADDR_LIST=NO, loopback
EPICS_PVA_ADDR_LIST): the server never searches beyond this host.  A browser can only write the PVs
the page's widgets write (Page.write_pvs), through the widget's own rule.

Routes
  GET  /api/pvgui/list                       pages: name, argv, title
  GET  /api/pvgui/spec?gui=N                 page tree (nodes with their parity ids); the first request
                                             makes the puts the PyQt program makes when it starts
  GET  /api/pvgui/values?gui=N               {values: {pv: value|null}, computed: {...}, connected, total}
  GET  /api/pvgui/info?gui=N                 PV prefix, connections, the simxpm-only <prefix>:SIM:NumLinks
  POST /api/pvgui/put  {gui, id, value}      the write of widget <id>: pvcheck 1/0, pvint int(text),
                                             pvcombo/seqsel index (only if it differs, as PvEditCmb),
                                             mask/maskbit the mask, button/check the page module's action
"""

import importlib
import logging
import os
import threading
import time

logger = logging.getLogger(__name__)


def _plain(v):
    if v is None:
        return None
    if hasattr(v, 'tolist'):
        return v.tolist()
    for t in (bool, int, float, str):
        if isinstance(v, t):
            return t(v)
    raw = getattr(v, 'raw', None)
    if raw is not None:
        return _plain(raw.value)
    return str(v)


class PvGuiApi:
    def __init__(self, app):
        self.app = app
        self.specs = list(getattr(app.args, 'pvgui', None) or [])
        self.pages, self.mods, self.argv = {}, {}, {}
        self.values, self.lock = {}, threading.Lock()
        self.ctx, self.conf, self.subs = None, None, []
        self.started = set()
        self.checks, self.check_state = {}, {}
        if not self.specs:
            return
        from psdaq.webgui.netguard import require_loopback_pva_env
        self.conf = require_loopback_pva_env(os.environ, '--pvgui')
        from p4p.client.thread import Context
        self.ctx = Context('pva', conf=self.conf, useenv=False)
        for spec in self.specs:
            name, _, args = spec.partition(':')
            mod = importlib.import_module('psdaq.webgui.pvgui.' + name)
            page = mod.build(args.split())
            self.pages[name], self.mods[name], self.argv[name] = page, mod, args.split()
            for nid, n in page.nodes.items():
                if n['type'] == 'check' and n.get('pv_on'):
                    self.checks[nid] = (n['pv_on'], n['pv_off'], n['on_value'])
            for pv in sorted(page.read_pvs | page.write_pvs):
                self._monitor(pv)

    def _monitor(self, pv):
        if pv in self.values:
            return
        self.values[pv] = None

        def cb(v, pv=pv):
            with self.lock:
                self.values[pv] = val = None if isinstance(v, Exception) else _plain(v)
                for nid, (pv_on, pv_off, on_value) in self.checks.items():   # PvGroupStats.monEnable/monDisable
                    if val == on_value and pv in (pv_on, pv_off):
                        self.check_state[nid] = (pv == pv_on)
        self.subs.append(self.ctx.monitor(pv, cb, notify_disconnect=True))

    def _page(self, q):
        name = (q.get('gui') or [''])[0] if isinstance(q.get('gui'), list) else q.get('gui')
        if name not in self.pages:
            return None, (404, {'ok': False, 'err_info': 'no page %r (server --pvgui: %s)' % (name, self.specs)})
        return name, None

    def list(self, q):
        return 200, {'ok': True, 'pages': [{'name': n, 'argv': self.argv[n], 'title': p.title}
                                           for n, p in self.pages.items()]}

    def spec(self, q):
        name, err = self._page(q)
        if err:
            return err
        page = self.pages[name]
        done = []
        if name not in self.started:                 # the PyQt program's own puts at start (groupca addGroup)
            self.started.add(name)
            for pv, v in page.startup:
                self.ctx.put(pv, v, timeout=5.0)
                done.append([pv, v])
        return 200, {'ok': True, 'name': name, 'title': page.title, 'argv': self.argv[name], 'tree': page.tree,
                     'ids': sorted(k for k, n in page.nodes.items() if n['type'] != 'label'),
                     'startup_puts': done}

    def vals(self, q):
        name, err = self._page(q)
        if err:
            return err
        page = self.pages[name]
        with self.lock:
            vals = {pv: self.values.get(pv) for pv in page.read_pvs | page.write_pvs}
        comp = getattr(self.mods[name], 'computed', None)
        out = comp(page, vals) if comp else {}
        with self.lock:
            out.update({'check:' + nid: st for nid, st in self.check_state.items() if nid in page.nodes})
        return 200, {'ok': True, 'values': vals, 'computed': out,
                     'connected': sum(v is not None for v in vals.values()), 'total': len(vals), 'ts': time.time()}

    def info(self, q):
        name, err = self._page(q)
        if err:
            return err
        page = self.pages[name]
        prefix = getattr(page, 'xpm_prefix', None)
        probe = None
        if prefix:
            try:
                probe = _plain(self.ctx.get(prefix + ':SIM:NumLinks', timeout=3.0))
            except Exception as ex:
                probe = 'error: %s' % ex
        with self.lock:
            n = sum(self.values.get(pv) is not None for pv in page.read_pvs)
        return 200, {'ok': True, 'name': name, 'argv': self.argv[name], 'xpm_prefix': prefix, 'pva_conf': self.conf,
                     'read_pvs': len(page.read_pvs), 'connected': n, 'sim_numlinks': probe}

    def _put(self, pv, value):
        self.ctx.put(pv, value, timeout=5.0)

    def put(self, body):
        name = body.get('gui')
        if name not in self.pages:
            return 404, {'ok': False, 'err_info': 'no page %r' % name}
        page = self.pages[name]
        node = page.nodes.get(body.get('id'))
        if node is None:
            return 400, {'ok': False, 'err_info': 'no widget %r on %s' % (body.get('id'), name)}
        t, value = node['type'], body.get('value')
        try:
            if t in ('button', 'check'):
                done = self.mods[name].act(page, self._put, node, value)
                return 200, {'ok': True, 'puts': done}
            pv = node['pv']
            if pv not in page.write_pvs:
                return 403, {'ok': False, 'err_info': '%s is not written by %s' % (pv, body.get('id'))}
            if node.get('noop'):
                return 200, {'ok': True, 'ignored': 'PvInt.setPv does nothing'}
            if t == 'pvcheck':
                v = 1 if value else 0                              # PvCheckBox.pvClicked
            elif t == 'pvint':
                try:
                    v = int(str(value).strip())                    # PvEditInt.setPv: ignore what is not an int
                except ValueError:
                    return 200, {'ok': True, 'ignored': 'not an integer: %r' % (value,)}
            elif t in ('pvcombo', 'seqsel'):
                v = int(value)
                if t == 'pvcombo':
                    with self.lock:
                        cur = self.values.get(pv)
                    if cur == v:                                   # PvEditCmb.setValue skips an equal value
                        return 200, {'ok': True, 'skipped': 'equal'}
            elif t in ('mask', 'maskbit'):
                v = int(value)
            else:
                return 400, {'ok': False, 'err_info': 'widget %s (%s) does not write' % (body.get('id'), t)}
        except (TypeError, ValueError) as ex:
            return 400, {'ok': False, 'err_info': str(ex)}
        self._put(pv, v)
        return 200, {'ok': True, 'puts': [[pv, v]]}


def register(app, get_routes, post_routes):
    api = PvGuiApi(app)
    app.pvgui_api = api
    get_routes.update({'/api/pvgui/list': api.list, '/api/pvgui/spec': api.spec, '/api/pvgui/values': api.vals,
                       '/api/pvgui/info': api.info})
    post_routes['/api/pvgui/put'] = api.put
    return api
