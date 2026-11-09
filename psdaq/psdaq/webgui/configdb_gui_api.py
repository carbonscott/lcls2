"""Web copy of psdaq/configdb/configdb_GUI.py (browse the configuration database and change one parameter across many
detectors), an extension of psdaq.webgui.server started with  --configdb-gui '<configdb_GUI's arguments>'
(--url, --dev, --root, --user, --password, --hutch, --allow-write).  The URL must be loopback (the campaign's config
DB stand-in, psdaq.sim.configdb_server): the server refuses any other (exit 2).

The window's logic runs here, as the PyQt program's ConfigdbGUI does it, method for method (Model below), with the
program's own pure functions and background jobs: TreeWorker, DeviceWorker, ScanWorker and WriteWorker from
configdb_GUI.py run on a thread each (their signals delivered directly, on that thread, as Qt would queue them to the
window), plan_change / ValueSpec / type_of / format_value decide what an edit does, and _writing_possible / is_prod /
read_only_url the safety catch.  The page (static/gui/configdb_GUI.html) shows the four panes, the edit row, the
status bar, the progress bar and the dialogs (ConfirmDialog, the _warn message box, the close-while-writing box),
polls the state, and sends each user action; data-parity = the PyQt row ids.

Routes
  GET  /api/cdbgui/state      the window: target, read-only box, progress, the three trees (items, selection, column
                              headers), log lines, the edit row, status, the open dialog, closed
  POST /api/cdbgui/act        {op: reload | select_alias {hutch, alias} | select_devices {devices} | select_param {path}
                               | value {text} | combo {text} | read_only {checked} | apply | dialog {answer: ok|cancel}
                               | close}
"""

import argparse
import logging
import threading
import time

logger = logging.getLogger(__name__)
JOB_PREFIX = 'cdbgui-'


def parse_args(argv):
    """configdb_GUI.main()'s arguments."""
    from psdaq.configdb import configdb_GUI as G
    import os
    p = argparse.ArgumentParser(prog='configdb_GUI')
    p.add_argument('--url')
    p.add_argument('--dev', action='store_true')
    p.add_argument('--prod', action='store_true')
    p.add_argument('--root', default=G.DEFAULT_ROOT)
    p.add_argument('--user')
    p.add_argument('--password', default=os.getenv('CONFIGDB_AUTH'))
    p.add_argument('--hutch')
    p.add_argument('--allow-write', action='store_true')
    p.add_argument('-v', '--verbose', action='store_true')
    return p.parse_args(argv)


def require_loopback_args(spec):
    """Startup check (server.configure): the database URL configdb_GUI would use with these arguments (an explicit
    --url, else production or --dev's) must be loopback; NonLoopbackError (exit 2) otherwise, before any request."""
    import shlex
    from psdaq.configdb import configdb_GUI as G
    from psdaq.webgui.netguard import require_loopback_url
    g = parse_args(shlex.split(spec))
    url = G.resolve_url(g.url, g.dev)
    require_loopback_url(url, '--configdb-gui --url')
    return url


class _LogPane(logging.Handler):
    """configdb_GUI's SignalLogHandler: INFO and up, '%(levelname)s %(name)s: %(message)s', into the log pane; here
    only the records of this window's own jobs and calls (the server logs to the same root logger)."""

    def __init__(self, model):
        logging.Handler.__init__(self)
        self.model = model
        self.setLevel(logging.INFO)
        self.setFormatter(logging.Formatter('%(levelname)s %(name)s: %(message)s'))

    def emit(self, record):
        try:
            t = threading.current_thread().name
            if t.startswith(JOB_PREFIX) or t.startswith('ThreadPoolExecutor') or getattr(self.model, '_in_call', False):
                self.model.append_log(record.levelname, self.format(record))
        except Exception:
            pass


class Model:
    """ConfigdbGUI without Qt: the same state, the same methods (names kept), the same jobs."""

    def __init__(self, url, root, user=None, password=None, hutch=None, allow_write=False):
        from psdaq.configdb import configdb_GUI as G
        self.G = G
        self.lock = threading.RLock()
        self.auth_url, self.root, self.user, self.password = url, root, user, password
        self.start_hutch = hutch
        self.tree, self.devices = [], {}
        self.hutch = self.alias = None
        self.config = self.path = self.info = self.spec = None
        self._wanted_path = None
        self.results = {'ok': 0, 'failed': 0, 'skipped': 0}
        self._generation = 0
        self._jobs = {}
        # widgets
        self.read_only = True
        self.target_label, self.target_loud, self.window_title = '', False, 'configdb'
        self.pbar = {'visible': False, 'value': 0, 'max': 100}
        self.hutch_items, self.hutch_selected, self.hutch_expanded = [], None, set()
        self.device_items, self.device_selected = [], []
        self.param_headers, self.param_nodes, self.param_selected = ['parameter', 'type', 'value'], [], None
        self.log = []
        self.path_label, self.hint, self.apply_enabled, self.apply_tooltip = 'select a parameter', '', False, ''
        self.value_kind, self.value_text, self.combo_items, self.combo_text = 'edit', '', [], ''
        self.status = ''
        self.dialog = None
        self.closed = False
        self.seq = 0
        self._dialog_wait = None
        self.handler = _LogPane(self)
        logging.getLogger().addHandler(self.handler)
        self.read_only = not allow_write                        # self.write_box.setChecked(not allow_write)
        self._refresh_target()
        self.reload()

    # -- helpers -------------------------------------------------------------------------------------------------
    def _bump(self):
        self.seq += 1

    def append_log(self, level, text):
        with self.lock:
            self.log.append([level, text])
            self._bump()

    def _status(self, msg):
        self.status = msg
        self._bump()

    # -- jobs (ConfigdbGUI._start / _busy / _stop / _job_done / _progress / _job_failed) ------------------------
    def _start(self, name, make, **connections):
        if name == 'write' and self._busy('write'):
            logger.warning('a write is already running; ignoring this one')
            return
        self._stop(name)
        holder = {}

        def run():
            from PyQt5.QtCore import Qt
            w = make()
            holder['w'] = w
            # direct connections: a slot runs in the thread that emits (ScanWorker emits row from its pool threads),
            # under the model's lock; there is no event loop here to queue them to
            w.progress.connect(self._progress, Qt.DirectConnection)
            w.failed.connect(self._job_failed, Qt.DirectConnection)
            for sig, slot in connections.items():
                getattr(w, sig).connect(slot, Qt.DirectConnection)
            try:
                w.run()
            finally:
                self._job_done(name, t)
        t = threading.Thread(target=run, name=JOB_PREFIX + name, daemon=True)
        t.holder = holder
        self._jobs[name] = t
        t.start()

    def _busy(self, name):
        t = self._jobs.get(name)
        return bool(t) and t.is_alive()

    def _stop(self, name):
        t = self._jobs.pop(name, None)
        if not t:
            return
        w = t.holder.get('w')
        if w is not None:
            w.stop()
        t.join(3.0)
        if t.is_alive():
            logger.warning('%s worker did not stop cleanly', name)

    def _job_done(self, name, t):
        with self.lock:
            if self._jobs.get(name) is t:
                self._jobs.pop(name, None)
            if not self._jobs:
                self.pbar['visible'] = False
            self._bump()

    def _progress(self, done, total):
        with self.lock:
            self.pbar = {'visible': total > 1 and done < total, 'max': max(total, 1), 'value': done}
            self._bump()

    def _job_failed(self, generation, message):
        with self.lock:
            if generation == self._generation:
                self._status(message)

    def _fresh(self):
        self._generation += 1
        return self._generation

    def _current(self, generation):
        return generation == self._generation

    @property
    def read_url(self):
        return self.G.read_only_url(self.auth_url)

    def _worker_args(self, write=False):
        if write:
            user = self.user or (self.hutch.lower() + 'opr' if self.hutch else None)
            return dict(url=self.auth_url, root=self.root, user=user, password=self.password)
        return dict(url=self.read_url, root=self.root)

    # -- reading --------------------------------------------------------------------------------------------------
    def reload(self):
        generation = self._fresh()
        self.hutch_items, self.device_items, self.param_nodes = [], [], []
        self.devices.clear()
        self._status('loading hutches...')
        args = self._worker_args()
        self._start('tree', lambda: self.G.TreeWorker(generation, **args), loaded=self._tree_loaded)

    def _tree_loaded(self, generation, tree):
        with self.lock:
            if not self._current(generation):
                return
            self.tree = tree
            self.hutch_items = [[h, list(a)] for h, a in tree]
            for h, _ in tree:
                if self.start_hutch and h.lower() == self.start_hutch.lower():
                    self.hutch_expanded.add(h)
            self._status('%d hutches' % len(tree))

    def _alias_selected(self, hutch, alias):
        with self.lock:
            self.hutch_selected = [hutch, alias] if alias is not None else None
            self.device_items, self.device_selected = [], []
            self.param_nodes, self.param_selected = [], None
            self._clear_selection()
            if alias is None:
                self.hutch = self.alias = None
                return
            self.hutch, self.alias = hutch, alias
            key = (hutch, alias)
            if key in self.devices:
                self._show_devices()
                return
            generation = self._fresh()
            self._status('loading %s/%s...' % key)
            args = self._worker_args()
            self._start('devices', lambda: self.G.DeviceWorker(generation, hutch=hutch, alias=alias, **args),
                        loaded=self._devices_loaded)

    def _devices_loaded(self, generation, key, devices):
        with self.lock:
            self.devices[key] = devices
            if not self._current(generation):
                return
            self._show_devices()
            self._status('%d detectors' % len(devices))

    def _show_devices(self):
        devices = self.devices.get((self.hutch, self.alias))
        if devices is None:
            return
        self.device_items = list(devices)
        self._bump()

    def _devices_selected(self, devices=None, keep_path=False):
        with self.lock:
            if devices is not None:
                self.device_selected = [d for d in devices if d in self.device_items]
            wanted = self.path if keep_path else None
            self.param_nodes, self.param_selected = [], None
            self._clear_selection()
            self._wanted_path = wanted
            devices = list(self.device_selected)
            if not devices:
                return
            generation = self._fresh()
            self._status('loading %s...' % devices[0])
            args = self._worker_args()
            hutch, alias = self.hutch, self.alias
            self._start('config', lambda: self.G.ScanWorker(generation, hutch=hutch, alias=alias, devices=devices[:1],
                                                          path=None, keep_config=True, **args),
                        scanned=self._config_loaded)

    def _config_loaded(self, generation, changes):
        with self.lock:
            if not self._current(generation) or not changes:
                return
            change = changes[0]
            device = change.detector
            if change.config is None:
                logger.error('cannot read %s: %s', device, change.error or 'no configuration returned')
                return
            self.config = change.config
            wanted, self._wanted_path = self._wanted_path, None
            self.param_headers = [device, 'type', 'value']
            self.param_nodes = self._populate(self.config, '')
            if wanted:
                self.param_selected = wanted
                self._param_selected(wanted, rescan=False)
            self._bump()

    def _populate(self, node, prefix):
        """ConfigdbGUI._populate: the parameter tree (schema and read-only keys hidden), as nodes for the page."""
        G = self.G
        items = list(node.items()) if isinstance(node, dict) else [(str(i), v) for i, v in enumerate(node)]
        out = []
        for key, value in items:
            if G.is_hidden_key(key):
                continue
            path = key if not prefix else '%s.%s' % (prefix, key)
            compound = isinstance(value, dict) or (isinstance(value, list) and value and
                                                   all(isinstance(v, dict) for v in value))
            if compound:
                out.append({'text': key + ' *', 'type': '', 'value': '', 'path': None,
                            'children': self._populate(value, path)})
                continue
            info = G.type_of(self.config, path)
            out.append({'text': key, 'type': info.display if info else '?',
                        'value': G.format_value(value, G.PREVIEW_ELEMENTS), 'tooltip': 'path: %s' % path,
                        'path': None if (info is None or key == 'help:RO') else path, 'children': []})
        return out

    # -- the edit -------------------------------------------------------------------------------------------------
    def _clear_selection(self):
        self.path = None
        self.info = None
        self.path_label = 'select a parameter'
        self.hint = ''
        self.apply_enabled = False
        self._bump()

    def _param_selected(self, path, rescan=True):
        G = self.G
        with self.lock:
            if not path:
                self.param_selected = None
                self._clear_selection()
                return
            self.param_selected = path
            self.path = path
            self.info = G.type_of(self.config, path)
            self.path_label = path
            self.hint = self.info.hint() if self.info else ''
            current = G.getValue(self.config, path)
            if self.info is not None and self.info.kind == 'enum':
                self.combo_items = list(self.info.labels.keys())
                self.combo_text = self.combo_items[0] if self.combo_items else ''
                for label, number in self.info.labels.items():
                    if number == current:
                        self.combo_text = label
                        break
                self.value_kind = 'combo'
            else:
                self.value_text = G.format_value(current)
                self.value_kind = 'edit'
            self._validate()
            if rescan:
                self._scan_current()
            self._bump()

    def _scan_current(self):
        devices = list(self.device_selected)
        if not devices or not self.path:
            return
        generation = self._fresh()
        self.log.append(['INFO', '--- %s' % self.path])
        args = self._worker_args()
        hutch, alias, path = self.hutch, self.alias, self.path
        self._start('scan', lambda: self.G.ScanWorker(generation, hutch=hutch, alias=alias, devices=devices, path=path,
                                                    **args), row=self._scan_row)

    def _scan_row(self, generation, change):
        with self.lock:
            if self._current(generation):
                self.append_log('INFO', change.describe())

    def _value_text(self):
        return self.combo_text if self.value_kind == 'combo' else self.value_text

    def _validate(self):
        G = self.G
        text = self._value_text()
        if not self.path or not text:
            self.apply_enabled = False
            return
        if self.config is None:
            return
        change = G.plan_change('preview', self.config, self.path, G.ValueSpec(text))
        writable = not self.read_only
        self.apply_enabled = change.ok and writable
        if not change.ok:
            self.hint = change.error
        elif self.info is not None:
            self.hint = self.info.hint()
        self.apply_tooltip = 'enable writing first' if change.ok and not writable else ''
        self._bump()

    def _read_only_toggled(self, read_only):
        with self.lock:
            self.read_only = read_only
            if not read_only and not self._writing_possible():
                self.read_only = True
                self._bump()
                return
            self._refresh_target()
            self._validate()

    def _writing_possible(self):
        import os
        import subprocess
        if 'ws-kerb' in self.auth_url:
            if subprocess.call(['klist', '-s']) != 0:
                self._warn('No Kerberos ticket. Run kinit, then try again.')
                return False
        elif 'ws-auth' in self.auth_url:
            if not (self.password or os.getenv('CONFIGDB_AUTH')):
                self._warn('No password. Set CONFIGDB_AUTH or pass --password.')
                return False
        else:
            self._warn('This URL is unauthenticated and cannot be written to.\n'
                       'Restart with --prod or --url pointing at ws-auth.')
            return False
        return True

    def _refresh_target(self):
        writable = not self.read_only
        url = self.auth_url if writable else self.read_url
        prod = self.G.is_prod(url)
        self.target_label = '%s  %s' % ('PROD' if prod else 'dev', url)
        self.window_title = 'configdb - %s%s' % ('PROD' if prod else 'dev', '' if writable else ' (read-only)')
        self.target_loud = writable and prod
        self._bump()

    # -- applying -------------------------------------------------------------------------------------------------
    def _apply(self):
        G = self.G
        with self.lock:
            if self.read_only or not self.path:
                return
            devices = list(self.device_selected)
            text = self._value_text()
            if not devices or not text:
                return
            self.spec = G.ValueSpec(text)
            self.apply_enabled = False
            self._status('checking %d detectors...' % len(devices))
            generation = self._fresh()
            args = self._worker_args()
            hutch, alias, path, spec = self.hutch, self.alias, self.path, self.spec
            self._start('plan', lambda: G.ScanWorker(generation, hutch=hutch, alias=alias, devices=devices, path=path,
                                                   spec=spec, **args), scanned=self._plan_ready)

    def _plan_ready(self, generation, changes):
        """ConfigdbGUI._plan_ready up to the dialog: the ConfirmDialog (its exec) is the page's dialog; the user's
        answer (act dialog) continues in _confirmed."""
        G = self.G
        with self.lock:
            if not self._current(generation):
                return
            self._validate()
            writable = [c for c in changes if c.ok and not c.unchanged]
            skipped = [c for c in changes if not c.ok or c.unchanged]
            if not writable:
                self._warn('Nothing to do.\n\n%s' % '\n'.join(c.describe() for c in skipped[:20]))
                return
            target = '%s  %s/%s' % (self.auth_url, self.hutch, self.alias)
            self.dialog = {'kind': 'confirm', 'title': 'Confirm configuration change',
                           'head': 'Setting <b>%s</b> to <b>%s</b> on <b>%d</b> detector(s)<br>target: <b>%s</b>' % (
                               self.path, self.spec, len(writable), target),
                           'columns': ['detector', 'current', 'new'],
                           'rows': [[c.detector, G.format_value(c.old, G.PREVIEW_ELEMENTS),
                                     G.format_value(c.new, G.PREVIEW_ELEMENTS)] for c in writable],
                           'skipped_label': ('%d detector(s) will be skipped:' % len(skipped)) if skipped else None,
                           'note': '\n'.join(c.describe() for c in skipped) if skipped else None,
                           'footer': 'Each detector written gets a new configuration key.'}
            self._pending = (writable, self.path, self.spec)
            self._bump()

    def _confirmed(self, ok):
        G = self.G
        writable, path, spec = self._pending
        if not ok:
            self._status('cancelled')
            return
        self.results = {'ok': 0, 'failed': 0, 'skipped': 0}
        generation = self._fresh()
        self.log.append(['INFO', '--- writing %s = %s' % (path, spec)])
        args = self._worker_args(write=True)
        hutch, alias = self.hutch, self.alias
        self._start('write', lambda: G.WriteWorker(generation, hutch=hutch, alias=alias, changes=writable, path=path,
                                                 spec=spec, **args),
                    result=self._write_result, finished=self._write_finished)

    def _write_result(self, generation, change):
        with self.lock:
            if not change.ok:
                self.results['failed'] += 1
                logger.error('%s', change.describe())
            elif change.unchanged:
                self.results['skipped'] += 1
                self.append_log('INFO', change.describe())
            else:
                self.results['ok'] += 1
                self.append_log('INFO', '%s  (key %s)' % (change.describe(), change.key))

    def _write_finished(self):
        with self.lock:
            if self.closed:
                return
            summary = '%d written, %d failed, %d skipped' % (
                self.results['ok'], self.results['failed'], self.results['skipped'])
            self._status(summary)
            self.append_log('INFO', summary)
        threading.Thread(target=self._devices_selected, kwargs={'keep_path': True}, daemon=True,
                         name=JOB_PREFIX + 'reread').start()

    def _warn(self, text):
        self.dialog = {'kind': 'warn', 'title': 'configdb', 'text': text}
        self._bump()

    def close(self):
        """ConfigdbGUI.closeEvent: while a write runs, ask (the page's dialog); else stop the jobs and close."""
        with self.lock:
            if self._busy('write'):
                self.dialog = {'kind': 'close', 'title': 'configdb', 'text': 'A write is still in progress. Quit anyway?'}
                self._bump()
                return
        self._close()

    def _close(self):
        logging.getLogger().removeHandler(self.handler)
        for name in list(self._jobs):
            self._stop(name)
        with self.lock:
            self.closed = True
            self._bump()

    # -- the page -------------------------------------------------------------------------------------------------
    def state(self):
        with self.lock:
            return {'ok': True, 'seq': self.seq, 'target': self.target_label, 'target_loud': self.target_loud,
                    'window_title': self.window_title, 'read_only': self.read_only, 'pbar': dict(self.pbar),
                    'hutches': self.hutch_items, 'hutch_expanded': sorted(self.hutch_expanded),
                    'hutch_selected': self.hutch_selected, 'devices': self.device_items,
                    'devices_selected': self.device_selected, 'param_headers': self.param_headers,
                    'params': self.param_nodes, 'param_selected': self.param_selected,
                    'log': [list(x) for x in self.log], 'path_label': self.path_label, 'hint': self.hint,
                    'apply_enabled': self.apply_enabled, 'apply_tooltip': self.apply_tooltip,
                    'value_kind': self.value_kind, 'value_text': self.value_text, 'combo_items': self.combo_items,
                    'combo_text': self.combo_text, 'status': self.status, 'dialog': self.dialog,
                    'closed': self.closed, 'busy': sorted(n for n in self._jobs if self._busy(n)),
                    'url': self.auth_url}

    def act(self, body):
        op = body.get('op')
        if self.closed and op != 'state':
            return {'ok': False, 'err_info': 'the window is closed'}
        if self.dialog is not None and op not in ('dialog',):
            return {'ok': False, 'err_info': 'a dialog is open (%s)' % self.dialog['kind']}
        self._in_call = True
        try:
            if op == 'reload':
                self.reload()
            elif op == 'select_alias':
                self._alias_selected(body.get('hutch'), body.get('alias'))
            elif op == 'select_devices':
                self._devices_selected(list(body.get('devices') or []))
            elif op == 'select_param':
                self._param_selected(body.get('path'))
            elif op == 'value':
                with self.lock:
                    self.value_text = str(body.get('text', ''))
                    self._validate()
            elif op == 'combo':
                with self.lock:
                    self.combo_text = str(body.get('text', ''))
                    self._validate()
            elif op == 'read_only':
                self._read_only_toggled(bool(body.get('checked')))
            elif op == 'apply':
                self._apply()
            elif op == 'dialog':
                d, ok = self.dialog, body.get('answer') == 'ok'
                if d is None:
                    return {'ok': False, 'err_info': 'no dialog'}
                with self.lock:
                    self.dialog = None
                    self._bump()
                if d['kind'] == 'confirm':
                    self._confirmed(ok)
                elif d['kind'] == 'close' and ok:
                    self._close()
            elif op == 'close':
                self.close()
            else:
                return {'ok': False, 'err_info': 'unknown op %r' % op}
        finally:
            self._in_call = False
        return {'ok': True}


class CdbGuiApi:
    def __init__(self, app):
        a = app.args
        self.model = None
        spec = getattr(a, 'configdb_gui', None)
        if spec:
            import shlex
            from psdaq.webgui.netguard import require_loopback_url
            from psdaq.configdb import configdb_GUI as G
            g = parse_args(shlex.split(spec))
            url = G.resolve_url(g.url, g.dev)
            require_loopback_url(url, '--configdb-gui --url')       # NonLoopbackError: the server exits 2
            self.argv = shlex.split(spec)
            self.model = Model(url, g.root, g.user, g.password, g.hutch, g.allow_write)

    def state(self, q):
        if self.model is None:
            return 404, {'ok': False, 'err_info': 'server started without --configdb-gui'}
        return 200, dict(self.model.state(), argv=self.argv)

    def act(self, body):
        if self.model is None:
            return 404, {'ok': False, 'err_info': 'server started without --configdb-gui'}
        r = self.model.act(body or {})
        time.sleep(0.05)
        return 200, r


def register(app, get_routes, post_routes):
    api = CdbGuiApi(app)
    app.cdbgui_api = api
    get_routes['/api/cdbgui/state'] = api.state
    post_routes['/api/cdbgui/act'] = api.act
    return api
