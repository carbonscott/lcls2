"""Config DB editor API, an extension of psdaq.webgui.server (listed in its EXT_MODULES).

The web copy of the PyQt configuration editor (control_gui CGWMainConfiguration.on_but_edit,
CGWConfigSelect, CGWConfigEditor with CGWConfigEditorTree / CGWConfigEditorText, and the
QWPopupEditText long-value editor) reaches the config DB only through this module.  It uses
psdaq.configdb.configdb, the client that CGConfigDBUtils.get_configdb wraps, with:
  url   the server's --configdb-url (loopback only: checked by server.configure and again here,
        before every request; there is no fallback to the facility URL CGConfigDBUtils.URI_CONFIGDB)
  root  --configdb-root (CGConfigDBUtils.ROOT_CONFIGDB 'configDB')
  hutch the instrument control reports (getInstrument), as CGWMainConfiguration.inst_configdb;
        if the DB has no hutch of that exact name but one that differs only in case, that one
        (the emulator reports 'TST', the campaign's stand-in is seeded as 'tst').
  user  --user, password $CONFIGDB_AUTH (used by configdb.py only for ws-auth URLs).

Routes (GET: query string, POST: JSON object body):
  GET  /api/configdb/info                    url, root, instrument, hutch, user
  GET  /api/configdb/aliases                 CGWConfigSelect.on_but_type: get_aliases(hutch)
  GET  /api/configdb/devices?alias=A         CGWConfigSelect.on_but_dev: get_devices(A, hutch)
  GET  /api/configdb/config?alias=A&device=D[&use_serial_db=0|1&serno=S]
                                             get_configuration(A, D, hutch) as the Tree editor
                                             (tree_model_from_dict) and the Text editor (str_json)
                                             show it; use_serial_db as CGWConfigEditor.on_cbx_serno
  POST /api/configdb/save    {alias, device, mode: 'tree', config_json, leaves: [[path, text], ...]}
                           | {alias, device, mode: 'text', text}
                                             CGWConfigEditor.on_but_apply -> get_content ->
                                             CGWMainConfiguration.save_dictj_in_db:
                                             modify_device(alias, dictj, hutch) -> new key
  POST /api/configdb/render  {text}          set_content of a dict loaded from a file
  POST /api/configdb/content {mode, config_json, leaves} | {mode: 'text', text}
                                             get_content (Save to file, Tree <-> Text switch)
  POST /api/configdb/npy_load {data_b64}     QWEditText.load_content_from_numpy_file
  POST /api/configdb/npy_save {text}         QWEditText.save_content_in_numpy_file
  POST /api/configdb/note    {event, name}   log lines the PyQt GUI writes for choices made in a dialog

The configuration travels to the browser and back as `config_json`, a string the page never
parses, so 64-bit integers (beyond JavaScript's 2**53) come back unchanged.
"""

import base64
import io
import json
import logging
import os
import re
import sys

from psdaq.webgui.netguard import NonLoopbackError, require_loopback_url

logger = logging.getLogger(__name__)

LIST_MAX_LEN = 5                                    # CGWConfigEditorTree list_max_len default (:76)
FALLBACK_ALIASES = ['NOBEAM', 'BEAM']               # CGWConfigSelect.py:130
SERNO_HUTCH = 'det'                                 # CGWConfigEditor.py:243
INT_TYPES = ('UINT8', 'UINT16', 'UINT32', 'UINT64', 'INT8', 'INT16', 'INT32', 'INT64')
NAME_RE = re.compile(r'^[A-Za-z0-9_+\-][A-Za-z0-9_.:+\-]*$')
NOTES = {   # event -> (level, message) as the PyQt GUI logs them
    'save_cancelled': ('WARNING', 'Saving of configuration in DB is cancelled...'),  # CGWMainConfiguration.py:143
    'load_cancelled': ('INFO', 'Loading is cancelled'),                               # CGWConfigEditor.py:191
    'save_file_cancelled': ('INFO', 'Saving is cancelled'),                           # CGWConfigEditor.py:279
    'input_file': ('INFO', 'Input file: %s'),                                         # CGWConfigEditor.py:194
    'output_file': ('INFO', 'Output file: %s'),                                       # CGWConfigEditor.py:282
    'editor_type': ('INFO', 'CGWConfigEditor set editor type %s'),                    # CGWConfigEditor.py:390
    'more_option': ('INFO', 'CGWConfigEditor selected option %s'),                    # CGWConfigEditor.py:379
    'devices_empty': ('WARNING', 'list_of_device_names IS EMPTY... Check configuration DB'),  # CGWConfigSelect.py:181
}


class ApiError(Exception):
    """Reported to the page as {"ok": false, "err_info": ...}."""


# ---------------- the PyQt tree model, as plain data (CGWConfigEditorTree.py) ----------------

def str_is_int(s):                                  # CGWConfigEditorTree.py:38
    return s.isdigit() or (s.startswith('-') and s[1:].isdigit())


def str_is_any_int(s):                              # CGWConfigEditorTree.py:55
    return str_is_int(s) or '0x' in s or '0o' in s or '0b' in s


def str_json(jo):                                   # CGJsonUtils.str_json (:248-251)
    return json.dumps(jo, indent=4, sort_keys=False, separators=(', ', ': '))


def _data_type(top, path):                          # CGWConfigEditorTree.data_type (:123-133)
    from psdaq.configdb.typed_json import getType
    dtype = None
    try:
        dtype = getType(top, path)
    except Exception:
        pass
    return str(dtype)


def _enum_pairs(dtype):                             # CGWConfigEditorTree.enum_dicts (:137-140)
    if isinstance(dtype, str) and dtype[:1] == '{':
        try:
            d = json.loads(dtype)
        except ValueError:
            return None
        if isinstance(d, dict):
            return [[k, v] for k, v in d.items()]
    return None


def list_texts(o, max_len=LIST_MAX_LEN):            # CGWConfigEditorTree.set_item_for_list (:241-252)
    lst = o.replace('\n', ' ').split(' ') if isinstance(o, str) else \
        [str(v) for v in o] if isinstance(o, list) else ['N/A']
    full = ' '.join(lst)
    shown = ('%s ...' % ' '.join(lst[:max_len])) if len(lst) >= max_len else full
    return shown, full


def build_tree(dictj, max_len=LIST_MAX_LEN):
    """CGWConfigEditorTree.tree_model_from_dict (:144-237) as nested dicts.

    Key node:  {key, text, kind: dict|listc|listd|data, cell: key|index, tip, children}
    Leaf:      {leaf: True, cell: list|data, path, text, full, descr, dtype, enum, editable, enabled, checkable,
                trimmed, tip}   (enum: [[name, value], ...] in the DB's order, or None)
    Keys ':types:' are skipped, keys with ':RO' are hidden except 'help:RO', whose value is read only.
    """
    if not isinstance(dictj, dict):
        return []
    root = {'key': '', 'children': []}
    _fill(dictj, dictj, root, [], False, max_len)
    return root['children']


def _fill(top, o, node, keys, ro, max_len):
    path = '.'.join(keys)                           # path_to_item (:61-65)
    key = node.get('key', '')
    if isinstance(o, dict):
        node.update(kind='dict', text='%s *' % key, tip='key to dict object', children=[])
        for k, v in o.items():
            if k == ':types:':
                continue
            is_ro = ro or (':RO' in k)
            if is_ro and not k == 'help:RO':
                continue
            child = {'key': k, 'cell': 'key'}
            node['children'].append(child)
            _fill(top, v, child, keys + [k], is_ro, max_len)
    elif isinstance(o, list):
        if any(isinstance(v, (dict, list)) for v in o):
            node.update(kind='listc', text='%s *' % key,
                        tip='key to the list of compaund types\n(lists, dicts etc.)', children=[])
            for i, v in enumerate(o):
                child = {'key': '%d' % i, 'cell': 'index'}
                node['children'].append(child)
                _fill(top, v, child, keys + ['%d' % i], ro, max_len)
        else:
            trimmed = len(o) >= max_len
            cmt = 'trimmed list' if trimmed else 'list'
            node.update(kind='listd', text='%s *' % key, tip='key to the %s' % cmt)
            shown, full = list_texts(o, max_len)
            dtype = _data_type(top, path)
            node['children'] = [{
                'leaf': True, 'cell': 'list', 'path': path, 'text': shown, 'full': full, 'descr': cmt, 'dtype': dtype,
                'enum': None, 'editable': not (trimmed or ro), 'enabled': not ro, 'checkable': False,
                'trimmed': trimmed, 'tip': '%s path: [%s] dtype: %s' % (cmt, path, dtype)}]
    else:
        node.update(kind='data', text='%s' % key, tip='key to simple data type')
        dtype = _data_type(top, path).replace(' ', '').replace("'", '"')
        enum = _enum_pairs(dtype)
        if enum:
            inv = {v: k for k, v in enum}
            s = inv[o] if o in inv else next(iter(inv.values()))
        else:
            s = str(o)
        node['children'] = [{
            'leaf': True, 'cell': 'data', 'path': path, 'text': s, 'full': s, 'descr': dtype, 'dtype': dtype, 'enum': enum,
            'editable': not ro, 'enabled': not ro, 'checkable': str_is_any_int(s), 'trimmed': False,
            'tip': 'data path: [%s] dtype: %s' % (path, dtype)}]


def _canon_int_text(dictj, path, value):
    """'0x2a2a' -> '10794' for integer types (typed_json.simpleConvert takes base 10 only)."""
    from psdaq.configdb.typed_json import getType
    try:
        t = getType(dictj, path)
    except Exception:
        return value
    base = t[0] if isinstance(t, list) else t
    if base not in INT_TYPES:
        return value
    out = []
    for tok in value.split(' '):
        if re.match(r'^-?0[xXoObB]', tok):
            try:
                tok = str(int(tok, 0))
            except ValueError:
                pass
        out.append(tok)
    return ' '.join(out)


def apply_leaves(dictj, leaves):
    """CGWConfigEditorTree.get_content / iterate_over_children (:291-333): updateValue per leaf.

    leaves: [[path, text], ...] where text is what the tree item holds (the full text of a trimmed
    list, the enum value of an enum).  Returns [{path, value, status}] for nonzero statuses."""
    from psdaq.configdb.typed_json import updateValue
    if not isinstance(leaves, list):
        raise ApiError('leaves must be a list of [path, text]')
    bad = []
    for item in leaves:
        if not (isinstance(item, (list, tuple)) and len(item) == 2 and isinstance(item[0], str)):
            raise ApiError('bad leaf %r' % (item,))
        path, val = item[0], str(item[1])
        val = _canon_int_text(dictj, path, val)
        status = updateValue(dictj, path, val)
        if status:
            bad.append({'path': path, 'value': val, 'status': status})
    return bad


# ---------------- the API ----------------

def _q(query, name, required=True):
    v = (query.get(name) or [None])[0]
    if required and not v:
        raise ApiError('missing parameter %r' % name)
    return v


def _name(v, what):
    if not isinstance(v, str) or not NAME_RE.match(v) or '..' in v:
        raise ApiError('bad %s %r' % (what, v))
    return v


class ConfigDbApi:
    def __init__(self, app):
        self.app = app
        args = getattr(app, 'args', None)
        self.url = getattr(args, 'configdb_url', None)
        self.root = getattr(args, 'configdb_root', None) or 'configDB'
        self.user = getattr(args, 'user', None) or 'tstopr'
        self.password = os.getenv('CONFIGDB_AUTH')
        self.refused = None
        if self.url:
            try:
                require_loopback_url(self.url, '--configdb-url')
            except NonLoopbackError as ex:   # server.configure refuses these first; never talk to it
                self.refused = str(ex)

    # ---- helpers ----
    def _log(self, level, msg):
        hub = getattr(self.app, 'hub', None)
        if hub is not None:
            hub.add_log(level, msg)
        else:
            logger.log(getattr(logging, level, logging.INFO), msg)

    def _db(self):
        if self.refused:
            raise ApiError(self.refused)
        if not self.url:
            raise ApiError('no --configdb-url given: the config DB editor needs a loopback config DB '
                           '(e.g. python -m psdaq.sim.configdb_server)')
        require_loopback_url(self.url, '--configdb-url')     # again, before any request
        from psdaq.configdb.configdb import configdb
        return configdb(self.url, self._instrument() or 'none', create=False, root=self.root,
                        user=self.user, password=self.password)

    def _instrument(self):
        hub = getattr(self.app, 'hub', None)
        return getattr(hub, 'instrument', None)

    def _hutch(self, db):
        inst = self._instrument()
        if not inst:
            raise ApiError('instrument is None (getInstrument): no hutch for the config DB')
        hutches = db.get_hutches() or []
        if inst in hutches:
            return inst
        same = [h for h in hutches if str(h).lower() == str(inst).lower()]
        return same[0] if len(same) == 1 else inst

    def _render(self, cfg):
        return {'config_json': json.dumps(cfg), 'text': str_json(cfg), 'tree': build_tree(cfg)}

    def _run(self, fn, *a):
        try:
            return 200, fn(*a)
        except ApiError as ex:
            return 200, {'ok': False, 'err_info': str(ex)}
        except NonLoopbackError as ex:
            return 200, {'ok': False, 'err_info': str(ex)}
        except Exception as ex:
            msg = '%s: %s' % (type(ex).__name__, ex)
            self._log('ERROR', 'configdb: %s' % msg)
            return 200, {'ok': False, 'err_info': msg}

    # ---- GET ----
    def info(self, query):
        def do():
            out = {'ok': True, 'url': self.url, 'root': self.root, 'user': self.user,
                   'instrument': self._instrument(), 'hutch': None, 'err_info': self.refused}
            if self.refused:
                out['ok'] = False
            elif not self.url:
                out['ok'] = False
                out['err_info'] = 'no --configdb-url given'
            else:
                out['hutch'] = self._hutch(self._db())
            return out
        return self._run(do)

    def aliases(self, query):
        def do():
            db = self._db()
            hutch = self._hutch(db)
            lst = db.get_aliases(hutch=hutch)
            fallback = not lst
            if fallback:
                lst = list(FALLBACK_ALIASES)
                self._log('WARNING', 'List of configdb-s IS EMPTY... Use default: %s' % str(lst))
            return {'ok': True, 'aliases': list(lst), 'fallback': fallback, 'hutch': hutch}
        return self._run(do)

    def devices(self, query):
        def do():
            alias = _name(_q(query, 'alias'), 'alias')
            db = self._db()
            hutch = self._hutch(db)
            lst = db.get_devices(alias, hutch=hutch) or []
            return {'ok': True, 'alias': alias, 'devices': list(lst), 'hutch': hutch}
        return self._run(do)

    def config(self, query):
        def do():
            alias = _name(_q(query, 'alias'), 'alias')
            device = _name(_q(query, 'device'), 'device')
            use_sn = _q(query, 'use_serial_db', required=False)
            db = self._db()
            hutch = self._hutch(db)
            cfg = db.get_configuration(alias, device, hutch=hutch)
            if use_sn == '1':                       # CGWConfigEditor.on_cbx_serno, checked (:230-251)
                serno = _name(_q(query, 'serno'), 'serial number')
                if serno == '-':
                    raise ApiError('Serial number not available for redirection')
                sn_cfg = db.get_configuration(alias, serno, hutch=SERNO_HUTCH)
                cfg['use_serial_db'] = True
                cfg.setdefault(':types:', {})['use_serial_db'] = 'boolEnum'
                from psdaq.configdb.get_config import update_config
                cfg = update_config(sn_cfg, cfg)
            elif use_sn == '0':                     # unchecked (:259-263)
                cfg['use_serial_db'] = False
                cfg.setdefault(':types:', {})['use_serial_db'] = 'boolEnum'
            out = {'ok': True, 'alias': alias, 'device': device, 'hutch': hutch,
                   'title': 'Config Editor for %s %s' % (alias, device)}   # set_window_title (:367)
            out.update(self._render(cfg))
            return out
        return self._run(do)

    # ---- POST ----
    def _content(self, body):
        """(dictj, bad statuses) from the editor content, as get_content of the Tree or Text editor."""
        mode = body.get('mode')
        if mode == 'text':                          # CGWConfigEditorText.get_content (:74-77)
            text = body.get('text')
            if not isinstance(text, str):
                raise ApiError('text must be a string')
            try:
                dictj = json.loads(text)
            except ValueError as ex:
                raise ApiError('the text is not valid JSON: %s' % ex)
            if not isinstance(dictj, dict):
                raise ApiError('the text is not a JSON object')
            return dictj, []
        if mode == 'tree':
            cj = body.get('config_json')
            if not isinstance(cj, str):
                raise ApiError('config_json must be a string')
            dictj = json.loads(cj)
            if not isinstance(dictj, dict):
                raise ApiError('config_json is not a JSON object')
            return dictj, apply_leaves(dictj, body.get('leaves', []))
        raise ApiError("mode must be 'tree' or 'text'")

    def _warn_bad(self, bad):
        for b in bad:                               # CGWConfigEditorTree.py:329-330
            self._log('WARNING', 'CGWConfigEditorTree.updateValue path:[%s] new value: %s bad status: %d'
                      % (b['path'], b['value'], b['status']))

    def save(self, body):
        def do():
            alias = _name(body.get('alias'), 'alias')
            device = _name(body.get('device'), 'device')
            dictj, bad = self._content(body)
            self._warn_bad(bad)
            db = self._db()
            hutch = self._hutch(db)
            try:                                    # CGWMainConfiguration.save_dictj_in_db (:133-140)
                new_key = db.modify_device(alias, dictj, hutch=hutch)
            except ValueError as err:
                self._log('ERROR', 'ValueError: %s' % err)
                return {'ok': False, 'err_info': 'ValueError: %s' % err, 'bad': bad}
            except Exception as err:
                self._log('ERROR', 'Exception: %s' % err)
                return {'ok': False, 'err_info': 'Exception: %s' % err, 'bad': bad}
            self._log('INFO', 'configdb: saved %s/%s (detName %s) in hutch %s, new key %s'
                      % (alias, device, dictj.get('detName:RO'), hutch, new_key))
            out = {'ok': True, 'key': new_key, 'alias': alias, 'device': device, 'hutch': hutch, 'bad': bad}
            out.update(self._render(dictj))
            return out
        return self._run(do)

    def render(self, body):
        def do():
            text = body.get('text')
            if not isinstance(text, str):
                raise ApiError('text must be a string')
            try:
                dictj = json.loads(text)            # CGJsonUtils.load_json_from_file
            except ValueError as ex:
                raise ApiError('not valid JSON: %s' % ex)
            if not isinstance(dictj, dict):
                self._log('WARNING', 'Loaded configuration object is not a dict....')   # :108
            out = {'ok': True}
            out.update(self._render(dictj))
            return out
        return self._run(do)

    def content(self, body):
        def do():
            dictj, bad = self._content(body)
            self._warn_bad(bad)
            out = {'ok': True, 'bad': bad}
            out.update(self._render(dictj))
            return out
        return self._run(do)

    def npy_load(self, body):                       # QWEditText.load_content_from_numpy_file (:156-164)
        def do():
            import numpy as np
            raw = base64.b64decode(body.get('data_b64') or '', validate=True)
            nda = np.load(io.BytesIO(raw), allow_pickle=False)
            # threshold: no '...' summary for long arrays (np.array2string's default drops values)
            txt = np.array2string(nda, threshold=sys.maxsize).lstrip('[').rstrip(']')
            return {'ok': True, 'text': txt}
        return self._run(do)

    def npy_save(self, body):                       # QWEditText.save_content_in_numpy_file (:168-178)
        def do():
            import numpy as np
            txt = body.get('text')
            if not isinstance(txt, str):
                raise ApiError('text must be a string')
            arr = np.array([float(x) for x in txt.split()])   # np.fromstring(txt, sep=' ')
            buf = io.BytesIO()
            np.save(buf, arr)
            return {'ok': True, 'data_b64': base64.b64encode(buf.getvalue()).decode()}
        return self._run(do)

    def note(self, body):
        ev = body.get('event')
        if ev not in NOTES:
            return 400, {'ok': False, 'err_info': 'unknown event %r' % (ev,)}
        level, msg = NOTES[ev]
        if '%s' in msg:
            name = str(body.get('name', ''))[:200].replace('\n', ' ')
            msg = msg % name
        self._log(level, msg)
        return 200, {'ok': True}


def register(app, get_routes, post_routes):
    """Called by psdaq.webgui.server.load_extensions (from App.__init__, before app.hub exists)."""
    api = ConfigDbApi(app)
    app.configdb_api = api
    get_routes.update({
        '/api/configdb/info': api.info,
        '/api/configdb/aliases': api.aliases,
        '/api/configdb/devices': api.devices,
        '/api/configdb/config': api.config,
    })
    post_routes.update({
        '/api/configdb/save': api.save,
        '/api/configdb/render': api.render,
        '/api/configdb/content': api.content,
        '/api/configdb/npy_load': api.npy_load,
        '/api/configdb/npy_save': api.npy_save,
        '/api/configdb/note': api.note,
    })
    return api
