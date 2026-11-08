"""
Offscreen runtime walk of the PyQt control GUI: the independent check of the
parity enumerator's flags (hidden, inert, not reachable, never run).

The walk starts the real control_gui main window (CGWMain) with
QT_QPA_PLATFORM=offscreen, drives it through Select (unallocated), Show
(allocated), the configuration Type popup, Edit -> config select dialog -> config
editor (tree and text) -> Apply, and the logger, and records raw observations:

  lines      every source line of psdaq/control_gui that ran (sys.settrace)
  mods_gui   the control_gui modules the running GUI imported
  widgets    every counted-type widget: class, the self.<attr> names bound to it,
             visible, read-only, receivers of its main signal
  views      check/edit flags per column of the partition tables, per kind of
             config-tree item, and of the collection panels
  clicks     what clicking every cell of a column did (popup, rows hidden)
  calls      each modal opener the GUI called, with its file:line
  handlers   which input-event handlers each loaded control_gui class defines
  probes     box_state: Key_Up/Key_Down and a wheel event leave the state
             unchanged (and a plain QComboBox, the control, does change);
             buttons with a mnemonic (&Apply): the key sequence and visibility;
             CGWMainTabs built standalone, both tabs selected (lines of that
             phase are kept apart in probe_lines)

Everything is local: a config DB stand-in (psdaq.sim.configdb_server) on
127.0.0.1, DaqControl at 127.0.0.1 (nothing listens) and then an in-process
stub that serves a platform dict in control.py's shape.  The walk refuses to run
if any URI it would use is not loopback.  It takes about 15-30 s.

reconcile(rows, walk) (pure python, no Qt) turns the raw observations into a
per-row verdict: 'agree' (the walk saw what the enumerator's flags say),
'differ' (it saw the opposite) or 'not-exercised' (nothing to compare).
check_parity accepts an na row only when its verdict is 'agree'.

built(rows, walk) (pure python) is the walk's word on which rows the running GUI
builds: a row is built only if its module was imported by the running GUI, its
source line ran in the walk of the running GUI (`lines`; the standalone probe
phase's `probe_lines` do not count) and, for a widget row, an instance bound to
<Class>.<attr> existed.  check_parity refuses to count a mapped row the walk does
not show built.

Usage:
    python -m psdaq.webgui.parity.qt_walk --out walk.json        # DAQ env (PyQt5)
    python -m psdaq.webgui.parity.qt_walk --reconcile walk.json [--src DIR]
"""

import argparse
import collections
import hashlib
import json
import os
import re
import sys

WALK_VERSION = 1
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_WALK = os.path.join(HERE, 'qt_walk.json')
WIDGET_KINDS = ('button', 'checkbox', 'combo', 'combo-item', 'text', 'list', 'value')
TREE = {'tree_model_from_dict@1': '@1 key', 'tree_model_from_dict@2': '@2 list index',
        'tree_model_from_dict@3': '@3 data list', 'tree_model_from_dict@4': '@4 simple value'}


# ---------------------------------------------------------------- pure python

def source_digest(src):
    """sha256 over the control_gui sources (relative path + bytes, sorted)."""
    root = os.path.join(src, 'control_gui')
    h = hashlib.sha256()
    for dirpath, dirnames, files in os.walk(root):
        dirnames.sort()
        for f in sorted(files):
            if f.endswith('.py'):
                p = os.path.join(dirpath, f)
                h.update(os.path.relpath(p, src).encode() + b'\0')
                with open(p, 'rb') as fh:
                    h.update(fh.read())
                h.update(b'\0')
    return 'sha256:' + h.hexdigest()


def load_walk(path):
    with open(path) as f:
        w = json.load(f)
    if w.get('version') != WALK_VERSION:
        raise ValueError('walk %s has version %r, expected %d' % (path, w.get('version'), WALK_VERSION))
    return w


def _ranges(lines):
    out, start, prev = [], None, None
    for n in sorted(lines):
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append([start, prev])
            start = prev = n
    if start is not None:
        out.append([start, prev])
    return out


def _ran(walk, key, rel, line):
    for a, b in walk.get(key, {}).get(rel, []):
        if a <= line <= b:
            return True
    return False


def _caps(label):
    m = re.search(r'\(([a-z,]+)\)$', label)
    return set(m.group(1).split(',')) if m else set()


def _module_of(rel):
    return 'psdaq.' + rel[:-3].replace('/', '.').replace('.__init__', '')


def built(rows, walk):
    """{row id: (built, observation)}: did the running GUI build this row, by the walk's observations?
    Built = module imported by the running GUI, the row's source line ran in the walk of the running GUI
    (not in the standalone probe phase) and, for a widget kind, an instance bound to <Class>.<attr> existed."""
    W = walk.get('widgets', [])
    mods = set(walk.get('mods_gui', []))
    out = {}
    for r in rows:
        cls, rest = r['id'].split('.', 1)
        attr = rest.split('.')[0]
        mod = _module_of(r['file'])
        imp = mod in mods
        ran = _ran(walk, 'lines', r['file'], r['line'])
        obs = ['module %s %s' % (mod, 'imported' if imp else 'NOT imported by the running GUI'),
               'line %s %s' % (r['loc'], 'ran' if ran else 'NEVER ran in the running GUI')]
        if not ran and _ran(walk, 'probe_lines', r['file'], r['line']):
            obs[-1] += ' (ran only when built standalone in the probe phase)'
        ok = imp and ran
        if r['kind'] in WIDGET_KINDS:
            n = len([x for x in W if '%s.%s' % (cls, attr) in x['refs']])
            obs.append('%d widget(s) bound to %s.%s' % (n, cls, attr))
            ok = ok and n > 0
        out[r['id']] = (ok, '; '.join(obs))
    return out


def reconcile(rows, walk):
    """{row id: (verdict, observation)} for every row; verdict in agree / differ / not-exercised."""
    W = walk.get('widgets', [])
    calls = collections.Counter(c['site'] for c in walk.get('calls', []))
    views, clicks = walk.get('views', {}), walk.get('clicks', {})
    mods = set(walk.get('mods_gui', []))
    handlers = walk.get('handlers', {})
    probes = walk.get('probes', {})
    out = {}
    for r in rows:
        rid, kind = r['id'], r['kind']
        cls, rest = rid.split('.', 1)
        attr = rest.split('.')[0]
        if not r['reachable']:
            inst = next((re.match(r'(\w+) is instantiated only at ', e) for e in r['evidence']
                         if re.match(r'\w+ is instantiated only at ', e)), None)
            if inst:
                # code of a class built only in a main block; live subclasses may share its lines,
                # so the check is that no instance of exactly this class exists at run time
                k = inst.group(1)
                n = len([x for x in W if x['cls'] == k])
                out[rid] = ('differ' if n else 'agree', '%d %s instance(s) at run time%s' % (
                    n, k, ('' if not _ran(walk, 'lines', r['file'], r['line'])
                           else '; line %s ran via a live subclass' % r['loc'])))
                continue
            ran = _ran(walk, 'lines', r['file'], r['line'])
            obs = ['line %s %s' % (r['loc'], 'RAN' if ran else 'never ran')]
            bad = ran
            if calls.get(r['loc']):
                obs.append('opener called %d x' % calls[r['loc']])
                bad = True
            if r['reach'] == 'module-unreachable':
                imp = _module_of(r['file']) in mods
                obs.append('module %s %s' % (_module_of(r['file']), 'IMPORTED' if imp else 'not imported'))
                bad = bad or imp
                if _ran(walk, 'probe_lines', r['file'], r['line']) is False and \
                        r['file'] in walk.get('probe_lines', {}):
                    obs.append('and not run when the module is built standalone (%s)'
                               % walk.get('probe_notes', {}).get(r['file'], 'probe'))
            if kind == 'key' and r['reach'] == 'main-block':
                h = handlers.get(cls)
                if h is not None:
                    has = 'keyPressEvent' in h
                    obs.append('%s.keyPressEvent %s at run time' % (cls, 'DEFINED' if has else 'not defined'))
                    bad = bad or has
            if kind in WIDGET_KINDS:
                hits = [x for x in W if '%s.%s' % (cls, attr) in x['refs']]
                if hits:
                    obs.append('widget %s.%s INSTANTIATED' % (cls, attr))
                    bad = True
            out[rid] = ('differ' if bad else 'agree', '; '.join(obs))
            continue
        flags = r['hidden'] or r['inert']
        if kind in ('mnemonic', 'event-filter'):
            p = probes.get(rid)
            if p is None:
                out[rid] = ('not-exercised', 'no probe for %s' % rid)
                continue
            if kind == 'mnemonic':
                vis = p.get('visible')
                if r['hidden']:
                    v = 'agree' if vis is False and p.get('window_visible') else 'differ'
                else:
                    v = 'agree' if p.get('sequence') and vis else 'differ'
                out[rid] = (v, 'button %s sequence %r visible %s (window visible %s)' % (
                    p.get('button'), p.get('sequence'), vis, p.get('window_visible')))
            else:
                ok = p.get('suppressed') is True and p.get('control_changed') is True
                out[rid] = ('agree' if ok and not flags else 'differ', p.get('obs', ''))
            continue
        if kind in WIDGET_KINDS:
            xs = [x for x in W if '%s.%s' % (cls, attr) in x['refs']]
            if not xs:
                out[rid] = ('differ' if flags else 'not-exercised', 'widget %s.%s not instantiated' % (cls, attr))
                continue
            vis = [x['visible'] for x in xs if x['window_visible']]
            rec = [x.get('receivers') for x in xs]
            ro = [x.get('readonly') for x in xs]
            obs = 'n=%d visible=%s receivers=%s%s' % (len(xs), vis, rec, (' readonly=%s' % ro) if kind == 'text' else '')
            ok = True
            rt_hidden = bool(vis) and not any(vis)
            if r['hidden'] and not vis:
                out[rid] = ('not-exercised', obs + ' (its window never shown)')
                continue
            if rt_hidden != r['hidden']:
                ok = False
            if kind == 'text':
                if r['inert'] != all(x is True for x in ro):
                    ok = False
            elif r['inert'] != all(v == 0 for v in rec):
                ok = False
            out[rid] = ('agree' if ok else 'differ', obs)
        elif kind == 'column':
            site = '%s.%s' % (cls, attr)
            title = r['widget'].split('[', 1)[1].rstrip(']')
            v = views.get(site, {}).get(title)
            c = clicks.get('%s.%s' % (site, title), {})
            if v is None:
                out[rid] = ('not-exercised', 'view %s not built' % site)
                continue
            rt = set()
            if v['check']:
                rt.add('check')
            if v['edit']:
                rt.add('edit')
            if c.get('popups') or c.get('row_hiding_changed'):
                rt.add('click')
            obs = 'cells n=%d check=%d edit=%d; click popups=%d rows hidden changed=%s' % (
                v['n'], v['check'], v['edit'], len(c.get('popups', [])), c.get('row_hiding_changed'))
            ok = rt == _caps(r['label']) and (not rt) == r['inert']
            out[rid] = ('agree' if ok else 'differ', obs)
        elif kind == 'cell' and cls == 'CGWConfigEditorTree':
            k = TREE.get(attr)
            v = views.get('CGWConfigEditorTree', {}).get(k)
            if v is None:
                out[rid] = ('not-exercised', 'no tree item of kind %s' % k)
                continue
            sub = rest.split('.')[1] if rest.count('.') else None
            obs = '%s n=%d check=%d edit=%d' % (k, v['n'], v['check'], v['edit'])
            if sub in ('check', 'edit'):
                out[rid] = ('agree' if v[sub] > 0 else 'differ', obs)
            else:
                out[rid] = ('agree' if (v['check'] == 0 and v['edit'] == 0) == r['inert'] else 'differ', obs)
        elif kind == 'cell' and cls == 'CGWPanelList':
            ps = views.get('CGWPanelList', [])
            if not ps:
                out[rid] = ('not-exercised', 'no collection panel built')
                continue
            inert = all(p['check'] == 0 and p['edit'] == 0 for p in ps)
            out[rid] = ('agree' if inert == r['inert'] else 'differ', 'panels=%d items=%d check=%d edit=%d' % (
                len(ps), sum(p['n'] for p in ps), sum(p['check'] for p in ps), sum(p['edit'] for p in ps)))
        elif kind == 'click' and cls == 'CGWPanelList':
            ps = views.get('CGWPanelList', [])
            if not ps:
                out[rid] = ('not-exercised', 'no collection panel built')
                continue
            recv = [p['receivers'][attr] for p in ps]
            out[rid] = ('agree' if all(x == 0 for x in recv) == r['inert'] else 'differ',
                        'receivers(%s)=%s on %d panels' % (attr, recv, len(ps)))
        elif kind == 'click' and cls == 'CGWConfigEditorTree':
            recv = views.get('CGWConfigEditorTree.receivers', {}).get(attr)
            out[rid] = ('agree' if (recv == 0) == r['inert'] else 'differ', 'receivers(%s)=%s' % (attr, recv))
        elif kind in ('popup', 'confirm', 'message', 'file-dialog', 'color-dialog', 'dialog'):
            n = calls.get(r['loc'], 0)
            out[rid] = ('agree' if n and not flags else 'differ' if flags else 'not-exercised',
                        'opener called %d x at %s' % (n, r['loc']))
        else:
            out[rid] = ('not-exercised', 'no runtime probe for kind %s' % kind)
    return out


# ---------------------------------------------------------------- the walk (Qt)

def _require_loopback(url):
    from urllib.parse import urlsplit
    host = urlsplit(url).hostname if '://' in url else url
    if host not in ('127.0.0.1', 'localhost', '::1'):
        raise SystemExit('qt_walk: refusing non-loopback endpoint %r' % url)


def run_walk(out_path, workdir):
    import threading
    import time
    import traceback
    t0 = time.time()
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    for k, v in (('EPICS_CA_AUTO_ADDR_LIST', 'NO'), ('EPICS_CA_ADDR_LIST', '127.0.0.1'),
                 ('EPICS_PVA_AUTO_ADDR_LIST', 'NO'), ('EPICS_PVA_ADDR_LIST', '127.0.0.1'),
                 ('EPICS_PVAS_INTF_ADDR_LIST', '127.0.0.1'), ('EPICS_CAS_INTF_ADDR_LIST', '127.0.0.1')):
        os.environ[k] = v
    for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
        os.environ[k] = 'http://127.0.0.1:9'
    os.environ['NO_PROXY'] = os.environ['no_proxy'] = 'localhost,127.0.0.1'
    import psdaq
    src = os.path.dirname(os.path.realpath(psdaq.__file__))
    gui_prefix = os.path.join(src, 'control_gui') + os.sep
    OUT = {'version': WALK_VERSION, 'src': src, 'src_digest': source_digest(src),
           'calls': [], 'widgets': [], 'views': {}, 'clicks': {}, 'notes': [], 'probes': {},
           'probe_notes': {}}
    hits = {'lines': collections.defaultdict(set), 'probe_lines': collections.defaultdict(set)}
    bucket = ['lines']
    fcache = {}

    def local(frame, event, arg):
        if event == 'line':
            hits[bucket[0]][frame.f_code.co_filename].add(frame.f_lineno)
        return local

    def glob(frame, event, arg):
        fn = frame.f_code.co_filename
        ok = fcache.get(fn)
        if ok is None:
            ok = fcache[fn] = os.path.realpath(fn).startswith(gui_prefix)
        if not ok:
            return None
        hits[bucket[0]][fn].add(frame.f_lineno)
        return local
    sys.settrace(glob)
    threading.settrace(glob)

    from psdaq.sim import configdb_server, configdb_seed
    srv = configdb_server.make_server(None)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    URL = configdb_server.server_url(srv)
    _require_loopback(URL)
    configdb_seed.seed(URL)
    from psdaq.configdb.configdb import configdb
    from psdaq.configdb.typed_json import cdict
    # a second segment of the same detector, with an enum and a long (trimmed) list
    top = cdict()
    top.setAlg('fakecam', [0, 0, 1])
    top.define_enum('modeEnum', {'Slow': 0, 'Fast': 1})
    top.set('user.mode', 1, 'modeEnum')
    top.set('user.sim_seed', 7, 'UINT32')
    top.set('expert.coeffs', [1, 2, 3, 4, 5, 6, 7], 'UINT32')
    top.set('expert.gains', [1, 2], 'UINT32')
    top.setInfo('fakecam', 'fakecam', 1, 'sim-fakecam-1', 'qt_walk')
    db = configdb(URL, 'tst', create=True, root='configDB')
    db.add_device_config('fakecam')
    db.modify_device('BEAM', json.loads(json.dumps(top.typed_json())))
    OUT['notes'].append('config DB stand-in %s devices %s' % (URL, db.get_devices('BEAM')))

    from PyQt5.QtWidgets import (QApplication, QWidget, QPushButton, QToolButton, QCheckBox,
                                 QRadioButton, QComboBox, QLineEdit, QTextEdit, QPlainTextEdit,
                                 QSpinBox, QDoubleSpinBox, QSlider, QDial, QListWidget, QTabBar,
                                 QMenu, QAction, QTableView, QTreeView, QListView,
                                 QAbstractItemView, QDialog, QFileDialog, QAbstractButton)
    from PyQt5.QtCore import Qt, QPoint, QPointF
    from PyQt5.QtGui import QKeySequence, QWheelEvent
    from PyQt5.QtTest import QTest
    from PyQt5 import sip
    addr = sip.unwrapinstance
    TYPES = [QPushButton, QToolButton, QCheckBox, QRadioButton, QComboBox, QLineEdit, QTextEdit,
             QPlainTextEdit, QSpinBox, QDoubleSpinBox, QSlider, QDial, QListWidget, QTabBar, QMenu,
             QTableView, QTreeView, QListView]

    def ctype(w):
        for t in TYPES:
            if isinstance(w, t):
                return t.__name__
        return None

    logdir = os.path.join(workdir, 'qtlogs')
    os.makedirs(logdir, exist_ok=True)
    sys.argv = ['control_gui', '-p', '6', '-H', '127.0.0.1', '-t', '1500', '-u', URL,
                '-l', 'INFO', '-L', logdir, '--user', 'tstopr']
    for a in ('127.0.0.1', URL):
        _require_loopback(a)
    mods0 = set(sys.modules)
    from psdaq.control_gui.app.control_gui import input_option_parser
    from psdaq.control_gui.CGWMain import CGWMain
    from psdaq.control_gui.CGConfigParameters import cp
    from psdaq.control_gui.CGDaqControl import daq_control
    import psdaq.control_gui.CGWMainConfiguration as M_conf
    import psdaq.control_gui.CGWConfigSelect as M_sel
    import psdaq.control_gui.CGWPartitionTable as M_ptab
    import psdaq.control_gui.CGWConfigEditorTree as M_tree
    import psdaq.control_gui.CGWConfigEditor as M_edit
    from psdaq.control_gui.QWDialog import QWDialog
    from psdaq.control_gui.QWPopupEditText import QWPopupEditText

    app = QApplication(sys.argv)
    cp.qapplication = app

    def pump(sec):
        end = time.time() + sec
        while time.time() < end:
            app.processEvents()
            time.sleep(0.02)

    def site():
        for fr in reversed(traceback.extract_stack()[:-2]):
            if os.path.realpath(fr.filename).startswith(gui_prefix):
                return '%s:%d' % (os.path.relpath(os.path.realpath(fr.filename), src), fr.lineno)
        return '?'

    ANSWERS = {}
    PHASE = ['startup']

    def recorder(name, answer):
        def f(*a, **k):
            OUT['calls'].append({'opener': name, 'site': site(), 'phase': PHASE[0]})
            v = ANSWERS.get(name, answer)
            return v(*a, **k) if callable(v) else v
        return f

    for modobj in (M_conf, M_sel, M_ptab, M_tree):
        modobj.popup_select_item_from_list = recorder('popup_select_item_from_list', None)
    M_conf.confirm_or_cancel_dialog_box = recorder('confirm_or_cancel_dialog_box', False)
    M_edit.help_dialog_box = recorder('help_dialog_box', None)
    QFileDialog.getOpenFileName = recorder('QFileDialog.getOpenFileName', ('', ''))
    QFileDialog.getSaveFileName = recorder('QFileDialog.getSaveFileName', ('', ''))

    w = CGWMain(input_option_parser())
    w.show()
    pump(1.0)

    class Ctl(object):
        """In-process stand-in for DaqControl (records calls)."""
        log = []

        def __getattr__(self, name):
            def f(*a):
                Ctl.log.append((name, a))
                return {'getPlatform': PLATFORM, 'getInstrument': 'tst', 'getState': cp.s_state,
                        'getStatus': ('rollcall', cp.s_state, 'BEAM', False, PLATFORM, False,
                                      'tstx00117', 1, 0)}.get(name)
            return f

    def proc(i, alias, readout=None, active=1, monitor=0, hidden=0):
        d = {'active': active, 'monitor': monitor, 'hidden': hidden,
             'proc_info': {'alias': alias, 'host': '127.0.0.1', 'pid': 1000 + i}}
        if readout is not None:
            d['det_info'] = {'readout': readout, 'segment': 0}
        return d

    PLATFORM = {'drp': {'0': proc(0, 'fakecam_0', 0), '1': proc(1, 'fakecam_1', 0, monitor=1),
                        '2': proc(2, 'timing_0', 0, hidden=1)},
                'teb': {'3': proc(3, 'teb0')}, 'control': {'4': proc(4, 'control')}}
    daq_control.set_daq_control(Ctl())
    cp.instr = 'tst'
    cp.s_platform = PLATFORM

    def refs():
        import gc
        out = collections.defaultdict(list)
        for o in gc.get_objects():
            try:
                mod = type(o).__module__
            except Exception:
                continue
            if not mod.startswith('psdaq.control_gui'):
                continue
            d = getattr(o, '__dict__', None)
            if not isinstance(d, dict):
                continue
            for k, v in d.items():
                if isinstance(v, (QWidget, QAction)):
                    out[addr(v)].append('%s.%s' % (type(o).__name__, k))
        return out

    SIG = {'QPushButton': 'clicked', 'QCheckBox': 'stateChanged', 'QComboBox': 'currentIndexChanged',
           'QTextEdit': 'textChanged', 'QListWidget': 'itemClicked'}
    SEEN = set()

    def walk(label):
        r = refs()
        n = 0
        for x in QApplication.allWidgets():
            if addr(x) in SEEN:
                continue
            t = ctype(x)
            if t is None:
                continue
            SEEN.add(addr(x))
            n += 1
            rec = {'phase': label, 'type': t, 'cls': type(x).__name__, 'refs': sorted(r.get(addr(x), [])),
                   'visible': x.isVisible(), 'window_visible': x.window().isVisible()}
            if isinstance(x, (QTextEdit, QPlainTextEdit, QLineEdit)):
                rec['readonly'] = x.isReadOnly()
            s = SIG.get(t)
            if s:
                try:
                    rec['receivers'] = x.receivers(getattr(x, s))
                except Exception as ex:
                    rec['receivers'] = 'err %s' % ex
            if isinstance(x, QAbstractButton) and '&' in x.text():
                rec['mnemonic'] = QKeySequence.mnemonic(x.text()).toString()
            OUT['widgets'].append(rec)
        return n

    def col_flags(view, key):
        m = QAbstractItemView.model(view)
        hdr = [str(m.headerData(c, Qt.Horizontal) or '') for c in range(m.columnCount())]
        out = {}
        for c, h in enumerate(hdr):
            n = chk = edit = 0
            for r_ in range(m.rowCount()):
                f = m.flags(m.index(r_, c))
                n += 1
                en = bool(f & Qt.ItemIsEnabled)
                chk += bool(f & Qt.ItemIsUserCheckable) and en
                edit += bool(f & Qt.ItemIsEditable) and en
            out[h] = {'n': n, 'check': chk, 'edit': edit}
        OUT['views'][key] = out

    def click_cells(view, key, title):
        m = QAbstractItemView.model(view)
        hdr = [str(m.headerData(c, Qt.Horizontal) or '') for c in range(m.columnCount())]
        c = hdr.index(title)
        before = len(OUT['calls'])
        hidden0 = [view.isRowHidden(r_) for r_ in range(m.rowCount())]
        ANSWERS['popup_select_item_from_list'] = '3'
        for r_ in range(m.rowCount()):
            if not view.isRowHidden(r_):
                view.clicked.emit(m.index(r_, c))
        pump(0.1)
        hidden1 = [view.isRowHidden(r_) for r_ in range(m.rowCount())]
        OUT['clicks']['%s.%s' % (key, title)] = {
            'popups': [x['site'] for x in OUT['calls'][before:]],
            'row_hiding_changed': hidden0 != hidden1, 'hidden_before': hidden0, 'hidden_after': hidden1}
        ANSWERS.pop('popup_select_item_from_list', None)

    walk('startup')
    cp.cgwmaincollection.update_table()
    pump(0.1)
    from psdaq.control_gui.CGWPanelList import CGWPanelList
    panels = []
    for x in QApplication.allWidgets():
        if isinstance(x, CGWPanelList):
            pm = QAbstractItemView.model(x)
            n_, chk, edit = 0, 0, 0
            for r_ in range(pm.rowCount()):
                f = pm.flags(pm.index(r_, 0))
                en = bool(f & Qt.ItemIsEnabled)
                n_ += 1
                chk += bool(f & Qt.ItemIsUserCheckable) and en
                edit += bool(f & Qt.ItemIsEditable) and en
            panels.append({'n': n_, 'check': chk, 'edit': edit,
                           'texts': [pm.item(r_).text() for r_ in range(pm.rowCount())],
                           'receivers': {s: x.receivers(getattr(x, s)) for s in ('clicked', 'doubleClicked')}})
    OUT['views']['CGWPanelList'] = panels

    # --- box_state: Key_Up / Key_Down / wheel against a plain QComboBox (the control)
    PHASE[0] = 'box_state'
    cp.s_state, cp.s_transition = 'allocated', 'alloc'
    w.set_buts_enabled()
    pump(0.2)
    ctrl = cp.cgwmaincontrol
    box = ctrl.box_state
    plain = QComboBox()
    plain.addItems([box.itemText(i) for i in range(box.count())])
    plain.show()

    def wheel(target):
        ev = QWheelEvent(QPointF(5, 5), QPointF(target.mapToGlobal(QPoint(5, 5))), QPoint(0, 0),
                         QPoint(0, -120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(target, ev)

    for which, act in (('keyPressEvent', lambda t: (QTest.keyClick(t, Qt.Key_Down), QTest.keyClick(t, Qt.Key_Down),
                                                     QTest.keyClick(t, Qt.Key_Up))),
                       ('wheelEvent', lambda t: (wheel(t), wheel(t)))):
        box.setCurrentIndex(0)
        plain.setCurrentIndex(0)
        pump(0.05)
        n0 = len([c for c in Ctl.log if c[0] == 'setState'])
        act(box)
        act(plain)
        pump(0.1)
        n1 = len([c for c in Ctl.log if c[0] == 'setState'])
        OUT['probes']['CGWMainControl.box_state.' + which] = {
            'suppressed': box.currentIndex() == 0 and n1 == n0, 'control_changed': plain.currentIndex() != 0,
            'obs': '%s on box_state (%s): index 0 -> %d, setState calls %d; on a plain QComboBox: index 0 -> %d'
                   % ('Key_Down, Key_Down, Key_Up' if which == 'keyPressEvent' else '2 wheel steps down',
                      type(box).__name__, box.currentIndex(), n1 - n0, plain.currentIndex())}
    plain.close()

    # --- partition: state unallocated -> the GUI opens the Select window itself
    PHASE[0] = 'select'
    cp.s_state, cp.s_transition = 'unallocated', 'rollcall'
    w.set_buts_enabled()
    pump(0.5)
    part = cp.cgwmainpartition
    sel = part.w_select
    walk('select')
    OUT['probes']['QWPopupTableCheck.but_apply.mnemonic'] = {
        'button': sel.but_apply.text(), 'sequence': QKeySequence.mnemonic(sel.but_apply.text()).toString(),
        'visible': sel.but_apply.isVisible(), 'window_visible': sel.isVisible()}
    col_flags(sel.wtab, 'CGWMainPartition.w_select')
    for title in ('sel', 'grp', 'level/pid/host', 'ID', 'Monitor'):
        click_cells(sel.wtab, 'CGWMainPartition.w_select', title)
    sel.but_apply.click()
    pump(0.1)
    OUT['notes'].append('select Apply -> setState calls %s' % [c for c in Ctl.log if c[0] == 'setState'][-1:])

    # --- state allocated: Select closes, Show opens on click
    PHASE[0] = 'show'
    cp.s_state, cp.s_transition = 'allocated', 'alloc'
    w.set_buts_enabled()
    pump(0.2)
    part.but_show.click()
    pump(0.5)
    show = part.w_show
    walk('show')
    col_flags(show, 'CGWMainPartition.w_show')
    for title in ('sel', 'grp', 'level/pid/host', 'ID', 'Monitor'):
        click_cells(show, 'CGWMainPartition.w_show', title)

    # --- configuration: type popup, then Edit -> QWDialog(CGWConfigSelect) -> editor
    PHASE[0] = 'config'
    cp.s_state = 'connected'
    w.set_buts_enabled()
    ANSWERS['popup_select_item_from_list'] = 'BEAM'
    w.wconf.but_type.click()
    pump(0.1)
    DLG = {}

    def dlg_exec(self):
        walk('config-dialog')
        wd = [c for c in self.findChildren(QWidget) if type(c).__name__ == 'CGWConfigSelect'][0]
        DLG['apply_enabled_before'] = self.but_apply.isEnabled()
        ANSWERS['popup_select_item_from_list'] = 'BEAM'
        wd.but_type.click()
        ANSWERS['popup_select_item_from_list'] = 'fakecam_1'
        wd.but_dev.click()
        DLG['apply_enabled_after'] = self.but_apply.isEnabled()
        OUT['calls'].append({'opener': 'QWDialog.exec_', 'site': site(), 'phase': PHASE[0]})
        return QDialog.Accepted
    QWDialog.exec_ = dlg_exec
    w.wconf.but_edit.click()
    pump(0.5)
    OUT['notes'].append('config dialog: %s' % DLG)
    ed = cp.cgwconfigeditor
    PHASE[0] = 'editor'
    walk('editor')
    tree = ed.wedi
    m = tree.model
    kinds = collections.defaultdict(lambda: {'n': 0, 'check': 0, 'edit': 0})

    def visit(parent_item, parent_descr):
        for r_ in range(parent_item.rowCount()):
            it = parent_item.child(r_, 0)
            descr = it.accessibleDescription()
            f = it.flags()
            if it.hasChildren() or descr.startswith('key'):
                k = '@2 list index' if parent_descr == 'key-to-list-compaund' else '@1 key'
            elif descr in ('list', 'trimmed list'):
                k = '@3 data list'
            else:
                k = '@4 simple value'
            kk = kinds[k]
            kk['n'] += 1
            en = bool(f & Qt.ItemIsEnabled)
            kk['check'] += bool(f & Qt.ItemIsUserCheckable) and en
            kk['edit'] += bool(f & Qt.ItemIsEditable) and en
            visit(it, descr)
    visit(m.invisibleRootItem(), '')
    from psdaq.control_gui.CGWConfigEditorTree import CGWConfigEditorTree
    extra = CGWConfigEditorTree(dictj={'chans': [{'gain': 1}, {'gain': 2}]})
    visit(extra.model.invisibleRootItem(), '')
    OUT['views']['CGWConfigEditorTree'] = dict(kinds)
    OUT['notes'].append('config tree kinds from fakecam_1 plus one tree with a compound list built directly')
    OUT['views']['CGWConfigEditorTree.receivers'] = {s: tree.receivers(getattr(tree, s))
                                                     for s in ('clicked', 'doubleClicked', 'expanded', 'collapsed')}
    POPUP_EDIT = {}

    def pe_exec(self):
        walk('popup-edit-text')
        POPUP_EDIT['opened'] = True
        OUT['calls'].append({'opener': 'QWPopupEditText.exec_', 'site': site(), 'phase': PHASE[0]})
        for b in (self.but_apply, self.but_cancel):
            OUT['probes']['QWPopupEditText.%s.mnemonic' % ('but_apply' if b is self.but_apply else 'but_cancel')] = {
                'button': b.text(), 'sequence': QKeySequence.mnemonic(b.text()).toString(),
                'visible': b.isVisibleTo(self), 'window_visible': None,
                'note': 'exec_ patched: the modal is built but not shown; visible = isVisibleTo(dialog)'}
        for i in (1, 2):
            self.edi_text.box_more.setCurrentIndex(i)
        return QDialog.Rejected
    QWPopupEditText.exec_ = pe_exec
    ANSWERS['popup_select_item_from_list'] = None

    def leaves(item, acc):
        for r_ in range(item.rowCount()):
            c = item.child(r_, 0)
            if c.hasChildren():
                leaves(c, acc)
            else:
                acc.append(c)
        return acc
    for it in leaves(m.invisibleRootItem(), []):
        tree.clicked.emit(m.indexFromItem(it))
        pump(0.02)
    OUT['notes'].append('QWPopupEditText opened from the tree: %s' % POPUP_EDIT)
    for i in (1, 2, 3):
        ed.box_more.setCurrentIndex(i)
        pump(0.05)
    ed.box_type.setCurrentIndex(0)
    pump(0.2)
    walk('editor-text')
    ed.box_type.setCurrentIndex(1)
    pump(0.2)
    walk('editor-tree2')
    cp.cgwmainconfiguration.cfgtype_edit = 'BEAM'
    ed.but_apply.click()
    pump(0.1)

    # --- logger: hidden, unconnected buttons
    PHASE[0] = 'logger'
    w.wlogr.but_save.click()
    pump(0.1)

    # --- mnemonics of every button seen
    rr = refs()
    for x in QApplication.allWidgets():
        if isinstance(x, QAbstractButton) and '&' in x.text():
            for nm in rr.get(addr(x), []):
                OUT['probes'].setdefault(nm + '.mnemonic', {
                    'button': x.text(), 'sequence': QKeySequence.mnemonic(x.text()).toString(),
                    'visible': x.isVisible(), 'window_visible': x.window().isVisible()})

    # handlers each loaded control_gui class defines (main-block methods are absent at run time)
    hs = {}
    for name, mod in list(sys.modules.items()):
        if not name.startswith('psdaq.control_gui') or mod is None:
            continue
        for k, v in list(vars(mod).items()):
            if isinstance(v, type) and v.__module__ == name:
                hs[k] = sorted(h for h in ('keyPressEvent', 'wheelEvent', 'mousePressEvent') if h in vars(v))
    OUT['handlers'] = hs
    OUT['mods_gui'] = sorted(mm for mm in set(sys.modules) - mods0 if mm.startswith('psdaq.control_gui'))

    # --- probe phase: CGWMainTabs (not imported by the GUI) built standalone, both tabs selected
    bucket[0] = 'probe_lines'
    try:
        from psdaq.control_gui.CGWMainTabs import CGWMainTabs
        tabs = CGWMainTabs()
        tabs.show()
        seen = []
        for i in (0, 1, 0, 1):
            tabs.tab_bar.setCurrentIndex(i)
            pump(0.1)
            seen.append(type(tabs.gui_win).__name__)
        OUT['probe_notes']['control_gui/CGWMainTabs.py'] = 'CGWMainTabs() then tabs %s gave gui_win %s' % (
            [tabs.tab_bar.tabText(i) for i in range(tabs.tab_bar.count())], seen)
        tabs.close()
    except Exception as ex:
        OUT['probe_notes']['control_gui/CGWMainTabs.py'] = 'probe failed: %s' % ex
    sys.settrace(None)
    threading.settrace(None)

    for key in ('lines', 'probe_lines'):
        OUT[key] = {}
        for fn, ls in sorted(hits[key].items()):
            rel = os.path.relpath(os.path.realpath(fn), src)
            OUT[key].setdefault(rel, [])
            OUT[key][rel] = _ranges(set(n for a, b in OUT[key][rel] for n in range(a, b + 1)) | ls)
    OUT['elapsed'] = round(time.time() - t0, 1)
    try:
        import PyQt5.QtCore as QC
        OUT['qt'] = QC.QT_VERSION_STR
    except Exception:
        pass
    OUT['python'] = sys.version.split()[0]
    with open(out_path, 'w') as f:
        json.dump(OUT, f, indent=0, sort_keys=True, default=str)
    print('qt_walk: %d widgets, %d opener calls, %d files with lines, %d probes, elapsed %.1f s -> %s' % (
        len(OUT['widgets']), len(OUT['calls']), len(OUT['lines']), len(OUT['probes']), OUT['elapsed'], out_path))
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


def main(argv=None):
    ap = argparse.ArgumentParser(description='offscreen PyQt walk / reconcile for the parity check')
    ap.add_argument('--out', help='run the walk (needs PyQt5) and write the raw observations here')
    ap.add_argument('--workdir', default=None, help='scratch dir for the GUI log files (default: next to --out)')
    ap.add_argument('--reconcile', metavar='WALK', help='print per-row verdicts for a saved walk')
    ap.add_argument('--src', default=None, help='psdaq package dir (default: the imported psdaq)')
    a = ap.parse_args(argv)
    if a.out:
        run_walk(os.path.abspath(a.out), a.workdir or os.path.dirname(os.path.abspath(a.out)))
        return 0
    if a.reconcile:
        from psdaq.webgui.parity.enumerate_pyqt import default_src, enumerate_rows
        src = a.src or default_src()
        walk = load_walk(a.reconcile)
        rows, _ = enumerate_rows(src)
        ver = reconcile(rows, walk)
        same = walk.get('src_digest') == source_digest(src)
        print('walk %s (%s), source digest %s' % (a.reconcile, walk.get('elapsed'), 'matches' if same else 'DIFFERS'))
        for r in rows:
            v, obs = ver[r['id']]
            fl = ','.join(f for f, on in (('unreachable:' + r['reach'], not r['reachable']),
                                          ('hidden', r['hidden']), ('inert', r['inert'])) if on) or '-'
            print('%s | %s | %s | %s | %s' % (r['id'], r['kind'], fl, v, obs))
        print(collections.Counter(v for v, _ in ver.values()))
        return 0
    ap.error('give --out or --reconcile')


if __name__ == '__main__':
    sys.exit(main())
