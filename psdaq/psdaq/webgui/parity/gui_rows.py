"""
Parity rows of a PyQt GUI other than the control GUI: from its source (Python `ast`) and the
offscreen walk of the running program (qt_walk --gui), in the shape check_parity.check takes.

Source.  The GUI's own files are the file that constructs the QApplication (qapps.py) plus every
psdaq module it imports that no other psdaq file imports (procmgr/ui_procStat.py for procstat);
modules shared with other programs (cas/pvedit.py, procmgr/ProcMgr.py) are libraries.  A *site* is a
call in an own file to a counted widget: a Qt class of COUNTED_QT, or a name a library defines that
(transitively) builds one (pvedit's PvDbl, LblEditEvt, PvCheckBox ...), or a class of the own files
that derives from one (deadca's PvDblArrayW(QtWidgets.QLabel)).  Calls to other classes defined in
the own files are not sites: the sites inside them are.  Each site records its scope (Class.method or
function), its binding (self.<attr>, a local name, or the callee), the enclosing guards and whether
its line can run (def never called, `if __name__ == '__main__':` block).  QLabel sites whose first
argument is a constant text and that are not kept in a self.<attr> are decoration, not sites.
Also from source: `on_<object>_<signal>` slots of classes whose ui calls connectSlotsByName (kind slot)
and static QMessageBox.<about|critical|warning|information|question> calls (kind message).

Walk.  qt_walk --gui runs the program's own main() offscreen against the simulated DAQ, with every
counted Qt class replaced by a recording subclass, and records each instance's construction stack,
class, PV (pvedit widgets: .pv.pvname of the widget or its parent), text, choices, enabled, read-only,
signal receivers, texts written after construction, table columns and tab texts.

Rows (one per affordance of the running GUI).  Each instance is attributed to the innermost frame
of its construction stack in an own file, i.e. to a site.  A site with instances gives one row per
instance, id `<scope>.<binding>` plus `[<PV>]`, `[<text>]` and `#<n>` qualifiers as needed to keep ids
unique (QTableWidget / QTreeWidget: one row per column `.col[<header>]`, one `.cellClicked` row when connected and,
for a tree whose itemSelectionChanged is connected, one `.select` row;
QTabWidget: one row per tab `.tab[<text>]`; QMessageBox: one row for all its instances, a dialog built anew
each time it is shown).  An instance that is a QLabel with no text written after
construction is decoration and gives no row, unless the walk saw another label of the same site built by
the same line (its construction chain's innermost frame) written: that one is a display not yet updated.
A site with no instance gives one row `<scope>.<binding>` (not built); a slot gives `<Class>.<slot>`.  Kinds: button, checkbox, combo,
text (editable), value (read-only or live display), column, click, tab, message, slot.

Flags (enumerator side, from source), which check_parity uses for not-applicable rows:
  reachable=False, reach='main-block' | 'def-unreachable' | 'no-object'
             site line under `if __name__ == '__main__':`, in a def nothing calls, or in a slot whose
             object the ui never creates.  A site the walk's program did not reach for another reason
             (reach='not-built', e.g. a branch its arguments did not take) stays reachable: it can not be
             not-applicable and, not being built, can not be mapped either
  inert      a display the source never writes (no setText/append/setHtml/setPlainText on its
             binding in the own files) or a button whose clicked/toggled signal the source never
             connects
pyqtgraph: a plot panel (a PlotItem that GraphicsLayout.addPlot makes, a PlotWidget, an ImageView) is a row of kind
plot (qualifier: its left-axis label); its curves are what it shows, not rows of their own.  The widgets of its
context menu (pg_options: the ViewBox's X / Y axis panels and the PlotItem's Plot Options, which the walk marks with
their plot) are rows '<plot row id>.<xaxis|yaxis|ctrl>.<name>' (a checkable QGroupBox is a checkbox row; the
pyqtgraph labels its retranslateUi writes are value rows).
reconcile(rows, walk) says 'agree' when the walk saw what the flag says (0 instances and the line
never ran; no object of that name; display empty at the end and never written, receivers 0), and
built(rows, walk) when the row's site has an instance (or the slot's object exists) and the line ran.
"""

import ast
import hashlib
import json
import os
import re

from psdaq.webgui.parity import qapps

COUNTED_QT = ('QPushButton', 'QToolButton', 'QCheckBox', 'QRadioButton', 'QLineEdit', 'QComboBox',
              'QSpinBox', 'QDoubleSpinBox', 'QSlider', 'QTextEdit', 'QPlainTextEdit', 'QTextBrowser',
              'QLabel', 'QTableWidget', 'QTableView', 'QTreeWidget', 'QListWidget', 'QTabWidget',
              'QProgressBar', 'QMessageBox',
              'addPlot', 'PlotWidget', 'ImageView')       # pyqtgraph plot panels (GraphicsLayout.addPlot makes a PlotItem)
STATIC_MSG = ('about', 'critical', 'warning', 'information', 'question', 'aboutQt')
WRITE_METHODS = ('setText', 'append', 'setHtml', 'setPlainText', 'insertPlainText', 'insertHtml', 'setValue')
CONNECT_SIGNALS = ('clicked', 'toggled', 'pressed', 'released', 'stateChanged', 'currentIndexChanged',
                   'editingFinished', 'textChanged', 'returnPressed', 'cellClicked', 'activated')


def _rel_module(src, rel):
    return qapps._module_name(rel)


def _parse(src, rel):
    with open(os.path.join(src, rel), 'rb') as f:
        return ast.parse(f.read(), filename=rel)


def _imports(tree, rel):
    """absolute psdaq module names imported by this file (and the names `from X import a` brings)."""
    pkg = (qapps._module_name(rel) or 'psdaq.x').rsplit('.', 1)[0]
    mods, names = set(), {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                mods.add(a.name)
        elif isinstance(n, ast.ImportFrom) and n.module is not None or (isinstance(n, ast.ImportFrom) and n.level):
            base = n.module or ''
            if n.level:
                parts = pkg.split('.')
                parts = parts[:len(parts) - (n.level - 1)] if n.level > 1 else parts
                base = '.'.join(parts + ([base] if base else []))
            mods.add(base)
            for a in n.names:
                names[a.asname or a.name] = (base, a.name)
                mods.add(base + '.' + a.name)
    return mods, names


def _mod_file(src, mod):
    if not mod.startswith('psdaq.'):
        return None
    p = mod.split('.', 1)[1].replace('.', '/')
    for cand in (p + '.py', p + '/__init__.py'):
        if os.path.isfile(os.path.join(src, cand)):
            return cand
    return None


def own_and_libs(src, target):
    """(own files, library files) of the GUI whose QApplication file is target (rel path)."""
    graph = {}
    for p in qapps.python_files(src):
        rel = os.path.relpath(p, src)
        try:
            graph[rel] = _imports(_parse(src, rel), rel)[0]
        except SyntaxError:
            graph[rel] = set()
    tree = _parse(src, target)
    mods, _ = _imports(tree, target)
    own, libs = [target], []
    for m in sorted(mods):
        f = _mod_file(src, m)
        if f is None or f == target or f in own or f in libs:
            continue
        # a module another psdaq program imports is a library; the web copies and the parity tools (webgui/) import
        # a GUI's modules to reuse its code (plots_api runs seqplot's), which does not make them a library
        users = [r for r, ms in graph.items() if r != target and not r.startswith('webgui/') and
                 any(_mod_file(src, x) == f for x in ms if x.startswith('psdaq.'))]
        (libs if users else own).append(f)
    return own, libs


def _call_name(func):
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _builds_counted(body_nodes, counted):
    for n in body_nodes:
        for m in ast.walk(n):
            if isinstance(m, ast.Call) and _call_name(m.func) in counted:
                return True
    return False


def library_counted(src, libs):
    """names defined in library modules that build a counted widget (fixpoint over each module)."""
    counted = set(COUNTED_QT)
    defs = {}
    for rel in libs:
        try:
            tree = _parse(src, rel)
        except SyntaxError:
            continue
        for n in tree.body:
            if isinstance(n, (ast.ClassDef, ast.FunctionDef)):
                defs[n.name] = n
    changed = True
    while changed:
        changed = False
        for name, n in defs.items():
            if name in counted:
                continue
            hit = False
            if isinstance(n, ast.ClassDef):
                hit = any(_call_name(b) in counted for b in n.bases) or _builds_counted(n.body, counted)
            else:
                hit = _builds_counted(n.body, counted)
            if hit:
                counted.add(name)
                changed = True
    return counted


class _SiteScan(ast.NodeVisitor):
    def __init__(self, rel, counted, local_classes):
        self.rel = rel
        self.counted = counted
        self.local_classes = local_classes
        self.stack = []
        self.sites = []
        self.slots = []
        self.assign_target = None

    def _scope(self):
        return '.'.join(n for k, n, _ in self.stack if k in ('class', 'def')) or '<module>'

    def _cls_meth(self):
        cls = [n for k, n, _ in self.stack if k == 'class']
        defs = [n for k, n, _ in self.stack if k == 'def']
        if cls and defs:
            return '%s.%s' % (cls[-1], defs[-1]) if defs[-1] not in ('__init__', 'setupUi') else cls[-1]
        return '.'.join(cls + defs) or '<module>'

    def _guards(self):
        out = []
        for k, n, node in self.stack:
            if k in ('if', 'else'):
                try:
                    t = ast.unparse(node.test)
                except Exception:
                    t = '?'
                out.append('%s %s (%s:%d)' % ('if' if k == 'if' else 'else of if', t, self.rel, node.lineno))
        return out

    def visit_ClassDef(self, node):
        self.stack.append(('class', node.name, node))
        for n in node.body:
            if isinstance(n, ast.FunctionDef):
                m = re.match(r'^on_([A-Za-z0-9]+)_([A-Za-z0-9]+)$', n.name)
                if m:
                    self.slots.append({'cls': node.name, 'name': n.name, 'object': m.group(1), 'signal': m.group(2),
                                       'line': n.lineno})
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node):
        self.stack.append(('def', node.name, node))
        self.generic_visit(node)
        self.stack.pop()

    def visit_If(self, node):
        self.visit(node.test)
        self.stack.append(('if', None, node))
        for n in node.body:
            self.visit(n)
        self.stack.pop()
        self.stack.append(('else', None, node))
        for n in node.orelse:
            self.visit(n)
        self.stack.pop()

    def visit_AnnAssign(self, node):          # self._bar: QProgressBar = QProgressBar(self) (detector_protection_monitor)
        if node.value is not None:
            self.visit_Assign(ast.Assign(targets=[node.target], value=node.value, lineno=node.lineno))

    def visit_Assign(self, node):
        tgt = node.targets[0]
        name = None
        if isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name) and tgt.value.id == 'self':
            name = ('self', tgt.attr)
        elif isinstance(tgt, ast.Name):
            name = ('local', tgt.id)
        elif isinstance(tgt, ast.Subscript):
            v = tgt.value
            while isinstance(v, ast.Subscript):     # self.codesText['master'][i] = QLabel(...) (xpmpva)
                v = v.value
            if isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name) and v.value.id == 'self':
                name = ('self', v.attr)
            elif isinstance(v, ast.Name):
                name = ('local', v.id)
        old = self.assign_target
        self.assign_target = (name, node.value)
        self.generic_visit(node)
        self.assign_target = old

    def visit_Call(self, node):
        callee = _call_name(node.func)
        if (isinstance(node.func, ast.Attribute) and node.func.attr in STATIC_MSG and
                _call_name(node.func.value) == 'QMessageBox'):
            self.sites.append(self._site(node, 'QMessageBox.' + node.func.attr, None, kind='message', static=True))
        elif callee in self.counted and callee not in self.local_classes:
            bind = None
            if self.assign_target and self.assign_target[0]:
                val = self.assign_target[1]
                if val is node or any(c is node for c in ast.walk(val)):
                    bind = self.assign_target[0]
            deco = callee == 'QLabel' and not bind      # a label kept nowhere: constant text or a spacer
            if not deco:
                self.sites.append(self._site(node, callee, bind))
        self.generic_visit(node)

    def _site(self, node, callee, bind, kind=None, static=False):
        main = any(k == 'if' and qapps._is_main_test(n) for k, _, n in self.stack)
        binding = bind[1] if bind else callee
        return {'file': self.rel, 'line': node.lineno, 'end_line': getattr(node, 'end_lineno', node.lineno),
                'loc': '%s:%d' % (self.rel, node.lineno),
                'scope': self._cls_meth(), 'fullscope': self._scope(), 'binding': binding,
                'self_attr': bool(bind and bind[0] == 'self'), 'callee': callee, 'kind': kind,
                'guards': self._guards(), 'main_block': main, 'static': static,
                'defs': [n for k, n, _ in self.stack if k == 'def'],
                'classes': [n for k, n, _ in self.stack if k == 'class']}


def _writes_and_connects(trees):
    """({binding: n writes}, {binding: n signal connects}) over the own files' source."""
    writes, connects = {}, {}
    for tree in trees:
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
                continue
            f = n.func
            if f.attr in WRITE_METHODS and isinstance(f.value, (ast.Attribute, ast.Name, ast.Subscript)):
                b = f.value.attr if isinstance(f.value, ast.Attribute) else getattr(f.value, 'id', None)
                if isinstance(f.value, ast.Subscript):
                    v = f.value.value
                    b = v.attr if isinstance(v, ast.Attribute) else getattr(v, 'id', None)
                if b:
                    writes[b] = writes.get(b, 0) + 1
            if f.attr == 'connect' and isinstance(f.value, ast.Attribute) and f.value.attr in CONNECT_SIGNALS:
                o = f.value.value
                b = o.attr if isinstance(o, ast.Attribute) else getattr(o, 'id', None)
                if b:
                    connects[b] = connects.get(b, 0) + 1
    return writes, connects


def _called_defs(trees):
    """names called anywhere (Name or attribute calls), plus names passed as callbacks."""
    out = set()
    for tree in trees:
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                c = _call_name(n.func)
                if c:
                    out.add(c)
                if c == 'super':
                    continue
                for a in list(n.args) + [k.value for k in n.keywords]:
                    if isinstance(a, ast.Attribute):
                        out.add(a.attr)
                    elif isinstance(a, ast.Name):
                        out.add(a.id)
    return out


def _refs(node):
    """names a node references (calls, callbacks, attributes, bases): an over-approximation of what it may run."""
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
    return out


def _reachable(trees):
    """(names referenced from code that can run, top-level defs/classes reachable) over the own files: from the
    module-level statements (not the defs and classes themselves) through the defs and classes they reference,
    transitively; a reachable class makes all its methods' references reachable."""
    defs, roots = {}, set()
    for tree in trees:
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
                defs.setdefault(n.name, []).append(n)
            else:
                roots |= _refs(n)
    seen, todo, called = set(), list(roots), set(roots)
    while todo:
        name = todo.pop()
        if name in seen or name not in defs:
            continue
        seen.add(name)
        for n in defs[name]:
            r = _refs(n)
            called |= r
            todo.extend(r - seen)
    return called, seen


def source_sites(src, target):
    """{'own', 'libs', 'sites', 'slots', 'writes', 'connects', 'uses_slots_by_name', 'digest'}"""
    own, libs = own_and_libs(src, target)
    counted = library_counted(src, libs)
    trees, sites, slots, local_classes = [], [], [], set()
    local_defs = {}
    for rel in own:
        t = _parse(src, rel)
        trees.append(t)
        for n in ast.walk(t):
            if isinstance(n, ast.ClassDef):
                local_classes.add(n.name)
                local_defs[n.name] = n
    # a class of the own files that derives (directly or through another such class) from a counted widget class
    # is itself a counted widget: its calls are sites (deadca.PvDblArrayW(QtWidgets.QLabel), pvatable.PvField)
    # (a base names the own files' class of that name if there is one, else a library or Qt class: a local class
    # that shadows a library name, deadca's own PvEvtTab, is judged by its own bases)
    local_counted = set()
    changed = True
    while changed:
        changed = False
        for name, n in local_defs.items():
            if name in local_counted:
                continue
            bases = [_call_name(b) for b in n.bases]
            if any((b in local_counted) if b in local_defs else (b in counted) for b in bases):
                local_counted.add(name)
                changed = True
    counted = (set(counted) - set(local_defs)) | local_counted
    local_classes = {c for c in local_classes if c not in local_counted}
    uses_sbn = False
    for rel, t in zip(own, trees):
        sc = _SiteScan(rel, counted, local_classes)
        sc.visit(t)
        sites.extend(sc.sites)
        slots.extend(dict(s, file=rel) for s in sc.slots)
        if any(isinstance(n, ast.Attribute) and n.attr == 'connectSlotsByName' for n in ast.walk(t)):
            uses_sbn = True
    writes, connects = _writes_and_connects(trees)
    called = _called_defs(trees)
    _, reach_top = _reachable(trees)
    for s in sites:
        s['def_called'] = all(d in called or d in ('__init__', 'setupUi', 'main', 'retranslateUi') or
                              d.startswith('on_') for d in s['defs'])
        s['class_used'] = all(c in called or c.startswith('Ui_') for c in s['classes'])
        # and the def or class it is in is reachable from code that runs (not only referenced by another
        # unreachable one: deadca's PvEvtTab, used only by PvEditEvt, which only LblEditEvt names, which nothing calls)
        top = (s['classes'] or s['defs'] or [None])[0]
        if top is not None and top not in reach_top and not top.startswith('Ui_'):
            if s['classes']:
                s['class_used'] = False
            else:
                s['def_called'] = False
    return {'own': own, 'libs': libs, 'sites': sites, 'slots': slots if uses_sbn else [],
            'writes': writes, 'connects': connects, 'digest': files_digest(src, own)}


def files_digest(src, files):
    h = hashlib.sha256()
    for rel in sorted(files):
        h.update(rel.encode() + b'\0')
        with open(os.path.join(src, rel), 'rb') as f:
            h.update(f.read())
        h.update(b'\0')
    return 'sha256:' + h.hexdigest()


# ------------------------------------------------------------------------- rows

QT_KIND = {'QPushButton': 'button', 'QToolButton': 'button', 'QRadioButton': 'checkbox', 'QCheckBox': 'checkbox',
           'QLineEdit': 'text', 'QComboBox': 'combo', 'QSpinBox': 'text', 'QDoubleSpinBox': 'text',
           'QSlider': 'combo', 'QTextEdit': 'text', 'QPlainTextEdit': 'text', 'QTextBrowser': 'value',
           'QLabel': 'value', 'QProgressBar': 'value', 'QMessageBox': 'message', 'QListWidget': 'combo',
           'PlotItem': 'plot', 'PlotWidget': 'plot', 'ImageView': 'plot', 'addPlot': 'plot'}


def _built_at(x):
    """(own-file site, the line that constructed it): the innermost frame of its construction chain, a library's line
    for a widget a library builds (pvedit.PvIntRow's cell label), else the site itself."""
    ch = x.get('chain') or []
    return tuple((x.get('site') or [None, None])[:2]) + (tuple(ch[0][:2]) if ch else ())


def written_lines(walk):
    """The construction lines (_built_at) of every label the walk saw written: a label never written but built by
    the same line as one that was is a display whose update had not run yet (dtica's PvIntRow cells, which pvedit
    writes from a PV Access thread whose monitors the walk sees deliver to a few cells only), not decoration."""
    return {_built_at(x) for x in (walk or {}).get('instances', [])
            if x.get('base') == 'QLabel' and (x.get('writes') or len(set(t for _, t in x.get('texts', []))) >= 2)}


def _instance_kind(x, written=()):
    """kind of a walked instance, or None for decoration."""
    base = x['base']
    if base in ('QTableWidget', 'QTableView', 'QTreeWidget', 'QTabWidget'):
        return base
    if base == 'QGroupBox':                     # a group box is a frame; a checkable one is a check box
        return ('checkbox' if x.get('enabled', True) else 'value') if x.get('checkable') else None
    k = QT_KIND.get(base)
    if k in ('button', 'checkbox', 'combo') and not x.get('enabled', True):
        return 'value'
    if k == 'text' and (x.get('readonly') or not x.get('enabled', True)):
        return 'value'
    if base == 'QLabel' and not x.get('writes') and len(set(t for _, t in x.get('texts', []))) < 2 and \
            _built_at(x) not in written:
        return None                 # a label nothing writes after construction (nor another of its line): decoration
    return k


def _qual(x):
    for key in ('pv', 'text'):
        if key == 'text' and x.get('base') == 'QLabel':
            continue                # a label's text is the value it shows (a kept label is written), not a name
        v = x.get(key)
        if v not in (None, '', '-'):
            return str(v).replace('&', '')
    return None


def make_rows(srcinfo, walk):
    """Rows (check_parity's row shape) of the GUI from the source sites and the walk (or None)."""
    rows = []
    sites = {}
    for s in srcinfo['sites']:                  # several counted calls on one line are one site
        k = (s['file'], s['line'])
        if k in sites:
            sites[k] = dict(sites[k], callee=sites[k]['callee'] + '+' + s['callee'],
                            end_line=max(sites[k]['end_line'], s['end_line']))
        else:
            sites[k] = dict(s)
    by_file = {}
    for k, s in sites.items():
        by_file.setdefault(s['file'], []).append(s)
    inst = {}
    walk_only = []
    written = written_lines(walk)
    pg_menu = []                                # pyqtgraph menu widgets: named after their plot's row, below
    for x in (walk or {}).get('instances', []):
        site = x.get('site')
        if not site:
            continue
        if x.get('pg'):
            pg_menu.append(x)
            continue
        cands = [s for s in by_file.get(site[0], []) if s['line'] <= site[1] <= s['end_line']]
        if cands:
            s = min(cands, key=lambda s: (s['end_line'] - s['line'], -s['line']))
            inst.setdefault((s['file'], s['line']), []).append(x)
        elif _instance_kind(x, written) is not None:
            walk_only.append(x)
    stems = {}
    for k, s in sorted(sites.items()):
        stems.setdefault('%s.%s' % (s['scope'], s['binding']), []).append(k)
    writes, connects = srcinfo['writes'], srcinfo['connects']

    def base_row(s, rid, kind, label, **kw):
        r = {'id': rid, 'kind': kind, 'label': label, 'file': s['file'], 'line': s['line'], 'loc': s['loc'],
             'widget': s['callee'], 'reachable': True, 'reach': '', 'hidden': False, 'inert': False,
             'guard': None, 'evidence': [], 'site': [s['file'], s['line']]}
        r.update(kw)
        return r

    objs = set((walk or {}).get('object_names', []))
    dead_slots = {sl['name']: '%s:%d' % (sl['file'], sl['line']) for sl in srcinfo['slots']
                  if walk is not None and sl['object'] not in objs}
    called_sites = {tuple(c['site'][:2]) for c in (walk or {}).get('calls', []) if c.get('site')}
    for key, s in sorted(sites.items()):
        xs = sorted(inst.get(key, []), key=lambda x: x['seq'])
        stem = '%s.%s' % (s['scope'], s['binding'])
        if len(stems[stem]) > 1:                # same scope and binding at several lines: @1, @2 in source order
            stem += '@%d' % (stems[stem].index(key) + 1)
        if s.get('static'):
            ok = any(f == s['file'] and s['line'] <= ln <= s['end_line'] for f, ln in called_sites)
            dead = [d for d in s['defs'] if d in dead_slots]
            reach, guard = '', None
            if dead:
                reach, guard = 'no-object', 'def %s (%s)' % (dead[-1], dead_slots[dead[-1]])
            elif s['main_block']:
                reach, guard = 'main-block', next((g for g in s['guards'] if '__main__' in g), None)
            rows.append(base_row(s, stem, 'message', s['callee'], reachable=not reach, reach=reach, guard=guard,
                                 static_called=ok, evidence=['static %s at %s; walk recorded the call: %s' % (
                                     s['callee'], s['loc'], ok)]))
            continue
        if not xs:
            dead = [d for d in s['defs'] if d in dead_slots]
            if dead:
                reach, guard = 'no-object', 'def %s (%s)' % (dead[-1], dead_slots[dead[-1]])
            elif s['main_block']:
                reach, guard = 'main-block', next((g for g in s['guards'] if '__main__' in g), None)
            elif not s['def_called'] or not s['class_used']:
                reach, guard = 'def-unreachable', None
            else:
                reach, guard = 'not-built', (s['guards'][-1] if s['guards'] else None)
            kind = s['kind'] or QT_KIND.get(s['callee'], 'widget')
            # a branch the walk's arguments did not take (reach 'not-built') is still a user-facing row: it can be
            # neither N/A (no structural reason) nor mapped (the walk does not show it built), so it fails the check
            rows.append(base_row(s, stem, kind, s['callee'], reachable=(reach == 'not-built'), reach=reach, guard=guard,
                                 evidence=['site %s %s; guards: %s' % (s['loc'], reach, '; '.join(s['guards']) or '-')]))
            continue
        out = []
        n_msg = 0
        for x in xs:
            k = _instance_kind(x, written)
            if k is None:
                continue
            if k == 'message':              # a dialog the program builds anew each time it is shown: one row per site
                n_msg += 1
                if n_msg > 1:
                    continue
            if k == 'QTabWidget':
                for t in x.get('tabs', []):
                    out.append(('tab', '%s.tab[%s]' % (stem, t), t, x))
                continue
            if k in ('QTableWidget', 'QTableView', 'QTreeWidget'):
                for c in x.get('columns', []):
                    out.append(('column', '%s.col[%s]' % (stem, c), c, x))
                if x.get('receivers', {}).get('cellClicked'):
                    out.append(('click', '%s.cellClicked' % stem, 'cell click', x))
                if x.get('receivers', {}).get('itemSelectionChanged'):      # a tree whose selection the program uses
                    out.append(('click', '%s.select' % stem, 'item selection', x))
                continue
            out.append((k, None, None if k == 'message' else _qual(x), x))   # a dialog's text is what it says now
        # ids for plain instances: stem, + [qual] when needed, + #n when still ambiguous
        plain = [o for o in out if o[1] is None]
        need_q = len(plain) > 1 or not s['self_attr']
        qs = [q for k, rid, q, x in plain]
        names = []
        for k, rid, q, x in out:
            if rid is None:
                # a text qualifier shared by several instances (QLineEdit('0') in a loop) says nothing: #n only
                if q and not x.get('pv') and qs.count(q) > 1:
                    q = None
                rid = stem + ('[%s]' % q if (need_q and q) else '')
            names.append(rid)
        seen = {}
        for n in names:
            seen[n] = seen.get(n, 0) + 1
        idx = {}
        for (k, rid, q, x), n in zip(out, names):
            if seen[n] > 1:
                idx[n] = idx.get(n, -1) + 1
                n = '%s#%d' % (n, idx[n])
            inert = False
            if k == 'value' and x['base'] in ('QTextBrowser', 'QTextEdit', 'QPlainTextEdit'):
                inert = writes.get(s['binding'], 0) == 0
            elif k == 'button' and s['self_attr']:
                inert = connects.get(s['binding'], 0) == 0 and not x.get('checkable')
            rows.append(base_row(s, n, k, q or s['callee'], inert=inert, instance=x['seq'],
                                 pv=x.get('pv'), evidence=['%d instance(s) at %s' % (len(xs), s['loc'])]))
    for sl in srcinfo['slots']:
        rid = '%s.%s' % (sl['cls'], sl['name'])
        loc = '%s:%d' % (sl['file'], sl['line'])
        objs = set((walk or {}).get('object_names', []))
        exists = sl['object'] in objs if walk else True
        rows.append({'id': rid, 'kind': 'slot', 'label': '%s.%s' % (sl['object'], sl['signal']), 'file': sl['file'],
                     'line': sl['line'], 'loc': loc, 'widget': sl['object'], 'reachable': exists,
                     'reach': '' if exists else 'no-object', 'hidden': False, 'inert': False,
                     'guard': None if exists else 'def %s (%s)' % (sl['name'], loc), 'site': None,
                     'evidence': ['connectSlotsByName slot for object %r' % sl['object']]})
    plot_ids = {r['instance']: r['id'] for r in rows if r.get('kind') == 'plot' and r.get('instance') is not None}
    for x in sorted(pg_menu, key=lambda x: x['seq']):
        k = _instance_kind(x, written)
        if k is None:
            continue
        owner, group, name = x['pg']
        loc = '%s:%s' % tuple(x['site'][:2])
        rows.append({'id': '%s.%s.%s' % (plot_ids.get(owner, 'pg-plot#%s' % owner), group, name), 'kind': k,
                     'label': _qual(x) or x['cls'], 'file': x['site'][0], 'line': x['site'][1], 'loc': loc,
                     'widget': x['cls'], 'reachable': True, 'reach': '', 'hidden': False, 'inert': False,
                     'guard': None, 'site': x['site'], 'instance': x['seq'], 'pv': None, 'pg': x['pg'],
                     'evidence': ['pyqtgraph %s %s of the plot built at %s (walk instance #%d)' % (
                         group, name, loc, x['seq'])]})
    for x in walk_only:                         # an instance the walk saw at a line with no site (a class in a variable:
        rows.append({'id': 'walk-only:%s:%s' % (x['site'][0], x['site'][1]) + ('[%s]' % _qual(x) if _qual(x) else ''),
                     'kind': _instance_kind(x, written) or 'value', 'label': x['cls'], 'file': x['site'][0],
                     'line': x['site'][1], 'loc': '%s:%s' % tuple(x['site'][:2]), 'widget': x['cls'],
                     'instance': x['seq'], 'pv': x.get('pv'),   # xpmpva's h[1](pvname, label)): a built row
                     'reachable': True, 'reach': '', 'hidden': False, 'inert': False, 'guard': None, 'site': x['site'],
                     'evidence': ['walk saw a %s built at %s:%s, a line the source scan has no site for' % (
                         x['cls'], x['site'][0], x['site'][1])]})
    ids = [r['id'] for r in rows]
    dup = set(i for i in ids if ids.count(i) > 1)
    if dup:
        raise ValueError('duplicate row ids: %s' % sorted(dup))
    return rows


def _ran(walk, rel, line):
    for a, b in walk.get('lines', {}).get(rel, []):
        if a <= line <= b:
            return True
    return False


def built(rows, walk):
    out = {}
    objs = set(walk.get('object_names', []))
    for r in rows:
        if r['kind'] == 'slot':
            ok = r['widget'] in objs
            out[r['id']] = (ok, 'object %r %s at run time' % (r['widget'], 'exists' if ok else 'does NOT exist'))
            continue
        ran = _ran(walk, r['file'], r['line'])
        if 'static_called' in r:
            out[r['id']] = (ran and r['static_called'], 'line %s %s; call %s by the walk' % (
                r['loc'], 'ran' if ran else 'NEVER ran', 'recorded' if r['static_called'] else 'NOT recorded'))
            continue
        has = r.get('instance') is not None
        out[r['id']] = (ran and has, 'line %s %s; %s' % (r['loc'], 'ran' if ran else 'NEVER ran',
                                                         'instance #%s' % r['instance'] if has else 'no instance'))
    return out


def merge_walks(walks):
    """One walk from several variants of the same GUI (spec walk.variants): rows come from the first
    variant's instances; later variants add the instances of sites the first has none of, their recorded
    calls and their source lines (error paths a bad argument reaches, e.g. procstat -i -1)."""
    if len(walks) == 1:
        return walks[0]
    out = json.loads(json.dumps(walks[0]))
    have = {tuple(x['site'][:2]) for x in out['instances'] if x.get('site')}
    seq = max([x['seq'] for x in out['instances']] + [0])
    out['variants'] = [{'argv': w.get('argv'), 'instances': len(w.get('instances', [])), 'calls': len(w.get('calls', [])),
                        'exit': w.get('exit'), 'notes': w.get('notes', [])[:3]} for w in walks]
    for w in walks[1:]:
        if w.get('src_digest') != out.get('src_digest'):
            raise ValueError('walk variants of different sources')
        for x in w.get('instances', []):
            if x.get('site') and tuple(x['site'][:2]) not in have:
                seq += 1
                out['instances'].append(dict(x, seq=seq, variant=w.get('argv')))
        out['calls'] += [dict(c, variant=w.get('argv')) for c in w.get('calls', [])]
        for rel, rngs in w.get('lines', {}).items():
            cur = set()
            for a, b in out['lines'].get(rel, []) + rngs:
                cur.update(range(a, b + 1))
            out['lines'][rel] = _ranges_of(cur)
        out['object_names'] = sorted(set(out.get('object_names', [])) | set(w.get('object_names', [])))
    return out


def _ranges_of(lines):
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


def reconcile(rows, walk):
    out = {}
    objs = set(walk.get('object_names', []))
    by_seq = {x['seq']: x for x in walk.get('instances', [])}
    for r in rows:
        if r['kind'] == 'slot':
            ex = r['widget'] in objs
            out[r['id']] = ('agree' if ex == r['reachable'] else 'differ',
                            'object %r %s among %d object names' % (r['widget'], 'found' if ex else 'not found', len(objs)))
            continue
        if not r['reachable'] and r['reach'] == 'no-object':
            obj = re.match(r'def on_([A-Za-z0-9]+)_', r['guard'] or '')
            ex = obj and obj.group(1) in objs
            ran = _ran(walk, r['file'], r['line'])
            out[r['id']] = ('differ' if (ex or ran) else 'agree', 'object %r %s at run time; line %s %s' % (
                obj.group(1) if obj else '?', 'EXISTS' if ex else 'does not exist', r['loc'], 'RAN' if ran else 'never ran'))
            continue
        if not r['reachable']:
            ran = _ran(walk, r['file'], r['line'])
            n = len([x for x in walk.get('instances', []) if x.get('site') and tuple(x['site'][:2]) == (r['file'], r['line'])])
            out[r['id']] = ('differ' if (ran or n) else 'agree', 'line %s %s; %d instance(s)' % (
                r['loc'], 'RAN' if ran else 'never ran', n))
            continue
        x = by_seq.get(r.get('instance'))
        if x is None:
            out[r['id']] = ('not-exercised', 'no instance')
            continue
        if r['inert']:
            if x['base'] in ('QTextBrowser', 'QTextEdit', 'QPlainTextEdit'):
                ok = not x.get('writes') and not x.get('content')
                obs = 'writes after construction %d, text at end %r' % (x.get('writes', 0), (x.get('content') or '')[:40])
            else:
                rec = x.get('receivers', {})
                ok = not any(rec.values())
                obs = 'receivers %s' % rec
            out[r['id']] = ('agree' if ok else 'differ', obs)
            continue
        out[r['id']] = ('not-exercised', 'user-facing row (instance #%d)' % x['seq'])
    return out
