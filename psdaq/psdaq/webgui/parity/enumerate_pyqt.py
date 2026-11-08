"""
Enumerate the user affordances of the PyQt DAQ control GUI from its source
(python ast only, no Qt import), for the web GUI parity check.  Version 1.

Unit: one row per user affordance
---------------------------------
  button      a QPushButton/QToolButton (or an in-scope subclass): one click.
  checkbox    a QCheckBox/QRadioButton.
  combo       a QComboBox used as a selector (one row for the selection).
  combo-item  an item of an "action" combo: the slot connected to the combo
              compares its index/text argument to constants (`if ind==1:`),
              so each compared item is a separate action; sub = item text.
  text        an editable text widget (QLineEdit/QTextEdit/QPlainTextEdit).
  list/value/action  QListWidget, spin boxes/sliders, QAction.
  tab, menu-item     QTabBar/QTabWidget addTab, QMenu/QToolBar addAction
              (a loop over a static list gives one row per element).
  column      one column of a table view whose header labels are static at
              the place the table is built (title_h=<static list>, or a static
              setHorizontalHeaderLabels): each column is a separate affordance
              (e.g. the `sel` and `Monitor` checkbox columns).  Whether a
              column's cells are checkable/editable is computed by abstract
              interpretation of the view's fill method with the real row
              template (the producer's `list2d.append([...])`, e.g.
              CGJsonUtils.get_platform) and the keyword values at that site;
              clicks are attributed to columns through the click slot's
              `is_column_for_title(..., '<title>')` guards.
  cell        in other item views (trees, lists): one row per item-creation
              site (`item = QStandardItem(...)`) and capability (.check/.edit)
              that can be true; one inert row when none can.
  click       a view's own signal (clicked, doubleClicked, expanded, ...)
              connected in the methods the view runs.
  popup, confirm, message, file-dialog, color-dialog, dialog
              each place the program asks the user through a modal: a call
              site of a module-level helper that opens one (e.g.
              popup_select_item_from_list -> popup, confirm_or_cancel_dialog_box
              -> confirm), a static QFileDialog/QMessageBox getter, or exec_()
              of a QMenu/QMessageBox/QColorDialog.  exec_() of an in-scope
              dialog class is not a row: that class's own widgets are rows.
              Widgets of a class built only inside such helpers (e.g. the
              QListWidget of QWPopupSelectItem) are covered by the call-site
              rows and not listed again.
  key         a `e.key() == Qt.Key_X` branch of a keyPressEvent override.
Not counted: labels, layouts, splitters, progress bars, window decorations,
widgets Qt creates internally.

Row id (contract): <Class>.<name>[.<sub>], Class = the class whose code builds
the control (for a column: the class that builds the table with its static
header), name = the self.<attr> the widget is bound to, or <method>@<n> for an
unbound local (n = 1-based order of such rows in that method).  Module-level
code uses the module's base name as Class and the function name, or
__main__ / <module>, as method.  No line numbers; file:line is a separate
column for humans.

Scope and flags
---------------
Every module under psdaq/control_gui is scanned, including code under
`if __name__ == '__main__':`.  Each row carries:
  reachable   False when the code cannot run in the GUI started from
              control_gui() in app/control_gui.py; `reach` says why:
              main-block (under `if __name__ == '__main__'`), if-false,
              module-unreachable (not imported from the entry point),
              def-unreachable (class/function never named by reachable code),
              method-not-live (not called from __init__, Qt event overrides,
              connected slots or outside the class, after dropping branches
              whose test is provably false), fallback-branch (else of a
              dispatch that covers every value its callers can pass).
  hidden      setVisible(<expr>) that is False for every reachable
              instantiation of the class (e.g. QWLoggerStd show_buttons=False).
  inert       the affordance does nothing: read-only text, a widget with no
              live signal connection whose state is never read, a column whose
              cells are never checkable/editable and gets no click action, a
              view whose signals are disconnected, a cell whose setters are all
              False.
  evidence    file:line facts behind reach/hidden/inert.

Usage:
    python -m psdaq.webgui.parity.enumerate_pyqt [--src DIR] [--format tsv|json|summary]
"""

import argparse
import ast
import collections
import copy
import json
import os
import re
import sys

WIDGET_ROW_KINDS = ('button', 'checkbox', 'combo', 'combo-item', 'text', 'list', 'value')
WIDGET_KIND = {
    'QPushButton': 'button', 'QToolButton': 'button', 'QCommandLinkButton': 'button',
    'QCheckBox': 'checkbox', 'QRadioButton': 'checkbox',
    'QComboBox': 'combo', 'QFontComboBox': 'combo',
    'QLineEdit': 'text', 'QTextEdit': 'text', 'QPlainTextEdit': 'text',
    'QSpinBox': 'value', 'QDoubleSpinBox': 'value', 'QSlider': 'value', 'QDial': 'value',
    'QDateTimeEdit': 'value', 'QListWidget': 'list', 'QAction': 'action',
}
VIEW_TYPES = {'QTableView', 'QTreeView', 'QListView', 'QTableWidget', 'QTreeWidget'}
ITEM_TYPES = {'QStandardItem', 'QTreeWidgetItem', 'QListWidgetItem', 'QTableWidgetItem'}
TAB_TYPES = {'QTabBar', 'QTabWidget'}
MENU_TYPES = {'QMenu', 'QMenuBar', 'QToolBar'}
STATIC_DIALOGS = {
    'QFileDialog': {'getOpenFileName', 'getOpenFileNames', 'getSaveFileName',
                    'getExistingDirectory'},
    'QColorDialog': {'getColor'},
    'QInputDialog': {'getText', 'getInt', 'getDouble', 'getItem', 'getMultiLineText'},
    'QMessageBox': {'question', 'warning', 'information', 'critical', 'about'},
}
VIEW_SIGNALS = {'clicked', 'doubleClicked', 'pressed', 'activated', 'entered',
                'expanded', 'collapsed', 'customContextMenuRequested'}
COMBO_SIGNALS = {'currentIndexChanged', 'activated', 'currentTextChanged', 'textActivated'}
STATE_READS = {'isChecked', 'checkState', 'currentText', 'currentIndex', 'toPlainText',
               'toHtml', 'value', 'selectedItems', 'currentItem', 'currentRow', 'itemText',
               'document', 'text'}
QT_EVENT_NAMES = {'event', 'eventFilter', 'sizeHint', 'minimumSizeHint', 'paint'}
# calls that only read or log: a slot made of these does nothing for the user
TRIVIAL_CALLS = {'debug', 'info', 'warning', 'error', 'critical', 'exception', 'log', 'print',
                 'str', 'len', 'format', 'repr', 'int', 'float', 'bool', 'hex', 'oct', 'bin',
                 'itemFromIndex', 'indexFromItem', 'text', 'row', 'column', 'parent', 'checkState',
                 'isEditable', 'isCheckable', 'item', 'model', 'accessibleText',
                 'accessibleDescription', 'hasChildren', 'literal_eval', 'getFullNameFromItem',
                 'getFullNameFromIndex', '_getFullName', 'selectedIndexes', 'selected_items',
                 'selected_indexes', 'isinstance', 'getattr', 'type', 'join', 'split',
                 'startswith', 'isdigit', 'rsplit', 'strip', 'lower', 'upper', 'replace', 'keys',
                 'values', 'items', 'range', 'enumerate', 'zip', 'all', 'any', 'min', 'max',
                 'sorted', 'list', 'tuple', 'dict', 'set', 'rowCount', 'columnCount',
                 'isRowHidden', 'horizontalHeaderItem', 'is_column_for_title'}

ENTRY_MODULE = 'psdaq.control_gui.app.control_gui'
ENTRY_FUNCTION = 'control_gui'
GUI_PACKAGE = 'control_gui'


class _Unknown(object):
    def __repr__(self):
        return '?'


UNK = _Unknown()
UNKS = frozenset([UNK])


class AList(object):
    """Abstract list: known elements (list of value sets) or unknown length with
    every element in `any`."""

    def __init__(self, elems=None, any_=None, node=None):
        self.elems = elems
        self.any = any_ if any_ is not None else (
            frozenset().union(*elems) if elems else UNKS)
        self.node = node

    def __repr__(self):
        return 'AList(%s)' % (self.elems if self.elems is not None else '*%s' % set(self.any))


def _truthy(values):
    """True / False / None (unknown) for a value set."""
    out = set()
    for v in values:
        out.add(None if v is UNK else bool(v))
    if out == {True}:
        return True
    if out == {False}:
        return False
    return None


def _may_be_true(values):
    return any(v is UNK or bool(v) for v in values)


def _sanitize(s):
    s = re.sub(r'[^0-9A-Za-z]+', '_', str(s)).strip('_').lower()
    return s or 'item'


def _fmt(values):
    vals = sorted((repr(v) if v is not UNK else '?') for v in values)
    return '{%s}' % ', '.join(vals)


# ---------------------------------------------------------------------------
# dead regions and modules

def _is_name_main(test):
    """'==' for `__name__ == '__main__'`, '!=' for the negation, else None."""
    if (isinstance(test, ast.Compare) and len(test.ops) == 1
            and isinstance(test.ops[0], (ast.Eq, ast.NotEq))):
        sides = [test.left, test.comparators[0]]
        if (any(isinstance(s, ast.Name) and s.id == '__name__' for s in sides)
                and any(isinstance(s, ast.Constant) and s.value == '__main__' for s in sides)):
            return '==' if isinstance(test.ops[0], ast.Eq) else '!='
    return None


def _live(stmts):
    """Drop branches that never run when the module is imported."""
    out = []
    for s in stmts:
        if isinstance(s, ast.If):
            m = _is_name_main(s.test)
            if m == '==':
                out.extend(_live(s.orelse))
                continue
            if m == '!=':
                out.extend(_live(s.body))
                continue
            if isinstance(s.test, ast.Constant) and not s.test.value:
                out.extend(_live(s.orelse))
                continue
        out.append(s)
    return out


class _Live(ast.NodeTransformer):
    def generic_visit(self, node):
        for field, value in ast.iter_fields(node):
            if isinstance(value, list) and value and isinstance(value[0], ast.stmt):
                setattr(node, field, [self.visit(s) for s in _live(value)])
            elif isinstance(value, list):
                setattr(node, field, [self.visit(v) if isinstance(v, ast.AST) else v
                                      for v in value])
            elif isinstance(value, ast.AST):
                setattr(node, field, self.visit(value))
        return node


def _mark_dead(node, reason=None):
    """Set node._dead = 'main-block' / 'if-false' / None on every node."""
    node._dead = reason
    for field, value in ast.iter_fields(node):
        children = value if isinstance(value, list) else [value]
        for c in children:
            if not isinstance(c, ast.AST):
                continue
            r = reason
            if r is None and isinstance(node, ast.If):
                m = _is_name_main(node.test)
                in_body = c in node.body
                in_else = c in node.orelse
                if m == '==' and in_body:
                    r = 'main-block'
                elif m == '!=' and in_else:
                    r = 'main-block'
                elif (isinstance(node.test, ast.Constant) and not node.test.value
                      and in_body):
                    r = 'if-false'
            _mark_dead(c, r)


def _walk_no_defs(node):
    todo = [node]
    while todo:
        n = todo.pop()
        yield n
        for c in ast.iter_child_nodes(n):
            if not isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                todo.append(c)


def _resolve_relative(node, current):
    if not node.level:
        return node.module
    pkg = current.split('.')[:-node.level]
    return '.'.join(pkg + ([node.module] if node.module else []))


def import_aliases(nodes, current):
    out = {}
    for node in nodes:
        for n in _walk_no_defs(node):
            if isinstance(n, ast.Import):
                for a in n.names:
                    if a.asname:
                        out[a.asname] = ('mod', a.name)
                    else:
                        out[a.name.split('.')[0]] = ('mod', a.name.split('.')[0])
            elif isinstance(n, ast.ImportFrom):
                base = _resolve_relative(n, current)
                for a in n.names:
                    out[a.asname or a.name] = ('sym', base, a.name)
    return out


class Module(object):
    def __init__(self, name, path, src_root):
        self.name = name
        self.path = path
        self.rel = os.path.relpath(path, src_root)
        self.base = os.path.splitext(os.path.basename(path))[0]
        with open(path) as f:
            src = f.read()
        # live tree: reachability walk
        self.tree = _Live().visit(ast.parse(src, path))
        self.defs, self.init, self.aliases = {}, [], {}
        for s in self.tree.body:
            if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.defs[s.name] = s
                continue
            if isinstance(s, (ast.If, ast.Try)):
                for sub in ast.iter_child_nodes(s):
                    if isinstance(sub, (ast.FunctionDef, ast.ClassDef)):
                        self.defs[sub.name] = sub
            self.init.append(s)
            self.aliases.update(import_aliases([s], self.name))
        # full tree: enumeration, with dead regions marked
        self.full = ast.parse(src, path)
        _mark_dead(self.full)
        for node in ast.walk(self.full):
            for child in ast.iter_child_nodes(node):
                child._parent = node
        self.full_aliases = import_aliases([self.full], self.name)
        self.fdefs = {}
        for s in self.full.body:
            self._fdef(s)
        self.consts = {}
        for s in self.full.body:
            if (isinstance(s, ast.Assign) and len(s.targets) == 1
                    and isinstance(s.targets[0], ast.Name) and isinstance(s.value, ast.Constant)):
                self.consts.setdefault(s.targets[0].id, set()).add(s.value.value)

    def _fdef(self, s):
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            self.fdefs.setdefault(s.name, s)
        elif isinstance(s, (ast.If, ast.Try)):
            for sub in s.body + getattr(s, 'orelse', []):
                self._fdef(sub)


class Program(object):
    """Module loading and the symbol-level reachability walk (live trees)."""

    def __init__(self, src_root, package='psdaq'):
        self.src_root = src_root
        self.package = package
        self.modules = {}
        self.reachable = set()

    def module(self, name):
        if name in self.modules:
            return self.modules[name]
        mod = None
        if name and (name == self.package or name.startswith(self.package + '.')):
            rel = name.split('.')[1:]
            base = os.path.join(self.src_root, *rel)
            for path in (base + '.py', os.path.join(base, '__init__.py')):
                if os.path.isfile(path):
                    mod = Module(name, path, self.src_root)
                    break
        self.modules[name] = mod
        return mod

    def resolve(self, mod, name, local):
        if name in local:
            return local[name]
        if name in mod.aliases:
            return mod.aliases[name]
        if name in mod.defs:
            return ('sym', mod.name, name)
        return None

    def target(self, ref, full=False):
        if ref is None:
            return None
        if ref[0] == 'mod':
            return (ref[1], None) if self.module(ref[1]) else None
        m = self.module(ref[1])
        if m is None:
            return None
        defs = m.fdefs if full else m.defs
        if ref[2] in defs:
            return (ref[1], ref[2])
        if self.module(ref[1] + '.' + ref[2]):
            return (ref[1] + '.' + ref[2], None)
        return (ref[1], None)

    def walk(self, entry_module, entry_function):
        todo = [(entry_module, None), (entry_module, entry_function)]
        while todo:
            key = todo.pop()
            if key in self.reachable:
                continue
            mod = self.module(key[0])
            if mod is None:
                continue
            self.reachable.add(key)
            if key[1] is None:
                nodes = mod.init
                if '.' in key[0]:
                    todo.append((key[0].rsplit('.', 1)[0], None))
            else:
                if key[1] not in mod.defs:
                    continue
                todo.append((key[0], None))
                nodes = [mod.defs[key[1]]]
            for n in nodes:
                todo.extend(self._refs(mod, n))

    def _refs(self, mod, node):
        out = []
        scopes = [node] + [n for n in ast.walk(node)
                           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        local = {}
        for s in scopes:
            local.update(import_aliases([s], mod.name))
        for n in ast.walk(node):
            if isinstance(n, ast.ImportFrom):
                base = _resolve_relative(n, mod.name)
                out.append((base, None))
                for a in n.names:
                    t = self.target(('sym', base, a.name))
                    if t:
                        out.append(t)
            elif isinstance(n, ast.Import):
                for a in n.names:
                    parts = a.name.split('.')
                    out.extend(('.'.join(parts[:i]), None) for i in range(1, len(parts) + 1))
            elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                t = self.target(self.resolve(mod, n.id, local))
                if t:
                    out.append(t)
            elif isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
                ref = self.resolve(mod, n.value.id, local)
                if ref and ref[0] == 'mod':
                    t = self.target(('sym', ref[1], n.attr))
                    if t:
                        out.append(t)
        return out


# ---------------------------------------------------------------------------
# small ast helpers

def _enclosing(node, types):
    p = getattr(node, '_parent', None)
    while p is not None and not isinstance(p, types):
        p = getattr(p, '_parent', None)
    return p


def _enclosing_class(node):
    """Innermost enclosing ClassDef whose body (not a nested def) contains node."""
    p = getattr(node, '_parent', None)
    while p is not None:
        if isinstance(p, ast.ClassDef):
            return p
        p = getattr(p, '_parent', None)
    return None


def _method_of(node):
    """The innermost enclosing FunctionDef."""
    return _enclosing(node, (ast.FunctionDef, ast.AsyncFunctionDef))


def _top_method(node):
    """Outermost FunctionDef below the class (or module) level."""
    out, p = None, getattr(node, '_parent', None)
    while p is not None and not isinstance(p, (ast.ClassDef, ast.Module)):
        if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out = p
        p = getattr(p, '_parent', None)
    return out


def _assigned_to(call):
    p = getattr(call, '_parent', None)
    if isinstance(p, ast.Assign) and len(p.targets) == 1 and p.value is call:
        return ast.unparse(p.targets[0])
    if isinstance(p, ast.Return):
        return '<return>'
    return None


def _self_attr(expr):
    """'x' for `self.x`, else None."""
    if (isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name)
            and expr.value.id == 'self'):
        return expr.attr
    return None


def _const_text(args):
    for a in args:
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            return a.value
        if isinstance(a, ast.JoinedStr) or (isinstance(a, ast.BinOp) and isinstance(
                a.left, ast.Constant) and isinstance(a.left.value, str)):
            return ast.unparse(a)
    return None


def _signal_of(func):
    """For `<recv>.<sig>[...].connect`: (recv expr, sig) else None."""
    if not (isinstance(func, ast.Attribute) and func.attr in ('connect', 'disconnect')):
        return None
    sig = func.value
    if isinstance(sig, ast.Subscript):
        sig = sig.value
    if isinstance(sig, ast.Attribute):
        return sig.value, sig.attr
    return None


def _loc(mod, node):
    return '%s:%d' % (mod.rel, node.lineno)


# ---------------------------------------------------------------------------

class Ctx(object):
    """Evaluation context: module, class key, local env, kwargs of a call site."""

    def __init__(self, en, mod, cls=None, env=None, kwargs_name=None, kwargs=None):
        self.en, self.mod, self.cls = en, mod, cls
        self.env = env if env is not None else {}
        self.kwargs_name = kwargs_name
        self.kwargs = kwargs     # name -> value set; None: unknown (e.g. **x passed)
        self.fn = None

    def fork(self):
        c = copy.copy(self)
        c.env = dict(self.env)
        return c


class Enumerator(object):
    def __init__(self, src_root, entry_module=ENTRY_MODULE, entry_function=ENTRY_FUNCTION):
        self.src_root = src_root
        self.prog = Program(src_root)
        self.prog.walk(entry_module, entry_function)
        self.gui_modules = []
        gui_root = os.path.join(src_root, GUI_PACKAGE)
        for dirpath, dirnames, files in os.walk(gui_root):
            dirnames.sort()
            for f in sorted(files):
                if f.endswith('.py'):
                    rel = os.path.relpath(os.path.join(dirpath, f), src_root)[:-3]
                    parts = rel.split(os.sep)
                    if parts[-1] == '__init__':
                        parts = parts[:-1]
                    m = self.prog.module('.'.join([self.prog.package] + parts))
                    if m is not None:
                        self.gui_modules.append(m)
        self.classes = {}
        for m in list(self.prog.modules.values()):
            if m is None:
                continue
            for node in ast.walk(m.full):
                if isinstance(node, ast.ClassDef):
                    self.classes.setdefault((m.name, node.name), node)
                    node._key = (m.name, node.name)
                    node._mod = m
        self._cache = {}
        self._index()
        self.rows = []
        self._counters = collections.Counter()

    # ---- name resolution on full trees ----

    def resolve(self, mod, name, node):
        f = _method_of(node)
        while f is not None:
            al = import_aliases([f], mod.name)
            if name in al:
                return al[name]
            f = _method_of(f)
        if name in mod.full_aliases:
            return mod.full_aliases[name]
        if name in mod.fdefs:
            return ('sym', mod.name, name)
        return None

    def _chase(self, ref, depth=0):
        """Follow re-exports: `from psdaq.x.A import QStandardItem` where A itself
        imported it from PyQt5."""
        while ref and ref[0] == 'sym' and ref[1] and depth < 6:
            if ref[1].startswith(('PyQt5', 'PyQt6', 'PySide')):
                return ref
            m = self.prog.module(ref[1])
            if m is None or ref[2] in m.fdefs or ref[2] not in m.full_aliases:
                return ref
            ref, depth = m.full_aliases[ref[2]], depth + 1
        return ref

    def qt_name(self, mod, expr, node):
        if isinstance(expr, ast.Name):
            ref = self._chase(self.resolve(mod, expr.id, node))
            if ref and ref[0] == 'sym' and ref[1] and ref[1].startswith(('PyQt5', 'PyQt6', 'PySide')):
                return ref[2]
        elif isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
            ref = self.resolve(mod, expr.value.id, node)
            if ref and ref[1] and ref[1].startswith(('PyQt5', 'PyQt6', 'PySide')):
                return expr.attr
        return None

    def def_target(self, mod, expr, node):
        """(module, defname) of an in-scope def that expr names."""
        t = None
        if isinstance(expr, ast.Name):
            t = self.prog.target(self.resolve(mod, expr.id, node), full=True)
        elif isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
            ref = self.resolve(mod, expr.value.id, node)
            if ref and ref[0] == 'mod':
                t = self.prog.target(('sym', ref[1], expr.attr), full=True)
        if t and t[1] and self.prog.modules.get(t[0]) and t[1] in self.prog.modules[t[0]].fdefs:
            return t
        return None

    def call_type(self, mod, call):
        qt = self.qt_name(mod, call.func, call)
        if qt:
            return ('qt', qt)
        t = self.def_target(mod, call.func, call)
        if t:
            d = self.prog.modules[t[0]].fdefs[t[1]]
            return ('cls' if isinstance(d, ast.ClassDef) else 'func', t)
        return None

    # ---- class hierarchy ----

    def bases(self, key):
        cls = self.classes[key]
        mod = cls._mod
        out = []
        for b in cls.bases:
            qt = self.qt_name(mod, b, cls)
            if qt:
                out.append(('qt', qt))
                continue
            t = self.def_target(mod, b, cls)
            if t and t in self.classes:
                out.append(('cls', t))
        return out

    def qt_ancestors(self, key):
        c = self._cache.setdefault('qta', {})
        if key in c:
            return c[key]
        c[key] = set()
        res = set()
        for kind, v in self.bases(key):
            res |= {v} if kind == 'qt' else self.qt_ancestors(v)
        c[key] = res
        return res

    def type_set(self, ctype):
        if ctype is None:
            return set()
        if ctype[0] == 'qt':
            return {ctype[1]}
        if ctype[0] == 'cls':
            return self.qt_ancestors(ctype[1])
        return set()

    def mro(self, key):
        out, todo = [], [key]
        while todo:
            k = todo.pop(0)
            if k in out:
                continue
            out.append(k)
            todo.extend(v for kind, v in self.bases(k) if kind == 'cls')
        return out

    def methods_of(self, key):
        return {s.name: s for s in self.classes[key].body
                if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))}

    def effective(self, key):
        """name -> FunctionDef used by instances of key (first along the MRO); base
        methods called explicitly as Base.m(self) / super().m() are added under
        'Base.m'."""
        c = self._cache.setdefault('eff', {})
        if key in c:
            return c[key]
        mro = self.mro(key)
        defs = [(k, self.methods_of(k)) for k in mro]
        seen = {}
        for k, ms in defs:
            for name, fn in ms.items():
                if name not in seen:
                    seen[name] = fn
                fn._key = k
        todo = list(seen.values())
        done = set()
        while todo:
            fn = todo.pop()
            if id(fn) in done:
                continue
            done.add(id(fn))
            k = fn._key
            mod = self.classes[k]._mod
            for call in (n for n in ast.walk(fn) if isinstance(n, ast.Call)):
                f = call.func
                if not isinstance(f, ast.Attribute):
                    continue
                owner = None
                if isinstance(f.value, ast.Name):
                    t = self.def_target(mod, f.value, call)
                    if t in mro:
                        owner = t
                elif (isinstance(f.value, ast.Call) and isinstance(f.value.func, ast.Name)
                      and f.value.func.id == 'super'):
                    after = mro[mro.index(k) + 1:] if k in mro else []
                    owner = next((b for b, ms in defs if b in after and f.attr in ms), None)
                if owner is None:
                    continue
                fn2 = dict(defs)[owner].get(f.attr)
                name = '%s.%s' % (owner[1], f.attr)
                if fn2 is not None and seen.get(f.attr) is not fn2 and name not in seen:
                    seen[name] = fn2
                    todo.append(fn2)
        c[key] = seen
        return seen

    def subclasses(self, key):
        return [k for k in self.classes if k != key and key in self.mro(k)]

    # ---- reachability ----

    def module_reachable(self, mod):
        return (mod.name, None) in self.prog.reachable

    def def_reachable(self, mod, name):
        return (mod.name, name) in self.prog.reachable

    def node_reach(self, mod, node):
        """(reachable, reason) for code at node, before method liveness."""
        if node._dead:
            return False, node._dead
        if not self.module_reachable(mod):
            return False, 'module-unreachable'
        top = node
        while getattr(top, '_parent', None) is not None and not isinstance(top._parent, ast.Module):
            top = top._parent
        if isinstance(top, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if not self.def_reachable(mod, top.name):
                return False, 'def-unreachable'
        return True, ''

    # ---- global index of reachable code ----

    def _index(self):
        self.sites = collections.defaultdict(list)     # class key -> [(mod, call)]
        self.fsites = collections.defaultdict(list)    # function key -> [(mod, call)]
        self.ext_attr = collections.defaultdict(list)  # attr name -> [(mod, node)] non-self receivers
        self.ext_connect = collections.defaultdict(list)  # widget attr -> [(mod, node)]
        self.attr_reads = collections.defaultdict(list)   # widget attr -> [(mod, node, method name)]
        for m in list(self.prog.modules.values()):
            if m is None:
                continue
            for node in ast.walk(m.full):
                if isinstance(node, ast.Call):
                    ct = self.call_type(m, node)
                    if ct and ct[0] == 'cls':
                        self.sites[ct[1]].append((m, node))
                    elif ct and ct[0] == 'func':
                        self.fsites[ct[1]].append((m, node))
                    f = node.func
                    sg = _signal_of(f)
                    if sg and isinstance(sg[0], ast.Attribute) and f.attr == 'connect':
                        recv = sg[0]
                        if not (isinstance(recv.value, ast.Name) and recv.value.id == 'self'):
                            self.ext_connect[recv.attr].append((m, node))
                    if (isinstance(f, ast.Attribute) and f.attr in STATE_READS
                            and isinstance(f.value, ast.Attribute)):
                        self.attr_reads[f.value.attr].append((m, node))
                if (isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)
                        and not (isinstance(node.value, ast.Name) and node.value.id in ('self', 'cls'))
                        and not (isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                                 and node.value.func.id == 'super')):
                    r, _ = self.node_reach(m, node)
                    if r:
                        self.ext_attr[node.attr].append((m, node))

    def reachable_sites(self, key):
        out = []
        for m, call in self.sites.get(key, []):
            r, _ = self.node_reach(m, call)
            if r:
                out.append((m, call))
        return out

    # ---- evaluation ----

    def site_kwargs(self, mod, call, params=None):
        """name -> value set for the keyword (and positional, given params) args."""
        ctx = Ctx(self, mod, self._class_key_of(call))
        out, unknown = {}, False
        for k in call.keywords:
            if k.arg is None:
                unknown = True
            else:
                out[k.arg] = self.ev(k.value, ctx)
        if params:
            for i, a in enumerate(call.args):
                if isinstance(a, ast.Starred):
                    unknown = True
                    break
                if i < len(params):
                    out[params[i]] = self.ev(a, ctx)
        return out, unknown

    def _class_key_of(self, node):
        c = _enclosing_class(node)
        return getattr(c, '_key', None) if c is not None else None

    def attr_values(self, key, attr, _depth=0):
        """(value set, evidence) for self.<attr> of instances of class key."""
        c = self._cache.setdefault('attr', {})
        if (key, attr) in c:
            return c[(key, attr)]
        c[(key, attr)] = (UNKS, [])
        if _depth > 3 or key not in self.classes:
            return UNKS, []
        vals, ev_ = set(), []
        assigns = []
        for name, fn in self.effective(key).items():
            for n in ast.walk(fn):
                targets = []
                if isinstance(n, ast.Assign):
                    targets = n.targets
                elif isinstance(n, ast.AugAssign):
                    targets = [n.target]
                for t in targets:
                    if _self_attr(t) == attr:
                        assigns.append((fn, n))
        if not assigns:
            c[(key, attr)] = (UNKS, [])
            return UNKS, []
        init = self.effective(key).get('__init__')
        for fn, n in assigns:
            mod = self.classes[fn._key]._mod
            if not isinstance(n, ast.Assign) or len(n.targets) != 1:
                vals.add(UNK)
                continue
            v = n.value
            if isinstance(v, ast.Constant):
                vals.add(v.value)
                ev_.append('%s self.%s = %r' % (_loc(mod, n), attr, v.value))
                continue
            param, default = None, None
            if fn is init:
                kw = fn.args.kwarg.arg if fn.args.kwarg else None
                if (isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute)
                        and v.func.attr == 'get' and isinstance(v.func.value, ast.Name)
                        and v.func.value.id == kw and v.args
                        and isinstance(v.args[0], ast.Constant)):
                    param = v.args[0].value
                    default = v.args[1] if len(v.args) > 1 else ast.Constant(value=None)
                elif isinstance(v, ast.Name):
                    names = [a.arg for a in fn.args.args]
                    if v.id in names:
                        param = v.id
                        i = names.index(v.id) - (len(names) - len(fn.args.defaults))
                        default = fn.args.defaults[i] if i >= 0 else None
            if param is None:
                vals.add(UNK)
                continue
            sites = self.reachable_sites(key)
            for sub in self.subclasses(key):
                sites += self.reachable_sites(sub)    # forwarded through **kwargs (approx.)
            if not sites:
                vals.add(UNK)
                continue
            names = [a.arg for a in fn.args.args][1:]
            dmod = self.classes[fn._key]._mod
            ev_.append('%s self.%s = %s' % (_loc(dmod, n), attr, ast.unparse(v)))
            for sm, call in sites:
                kws, unknown = self.site_kwargs(sm, call, names)
                if param in kws:
                    vals |= kws[param]
                    ev_.append('%s passes %s=%s' % (_loc(sm, call), param, _fmt(kws[param])))
                elif unknown:
                    vals.add(UNK)
                    ev_.append('%s passes **kwargs' % _loc(sm, call))
                elif default is not None:
                    dv = self.ev(default, Ctx(self, dmod, key))
                    vals |= dv
                    ev_.append('%s omits %s (default %s)' % (_loc(sm, call), param, _fmt(dv)))
                else:
                    vals.add(UNK)
        res = (frozenset(vals) if vals else UNKS, ev_)
        c[(key, attr)] = res
        return res

    def module_const(self, mod, name, node, _depth=0):
        if name in mod.consts and len(mod.consts[name]) == 1:
            return frozenset(mod.consts[name])
        ref = self.resolve(mod, name, node)
        if ref and ref[0] == 'sym' and _depth < 4:
            m2 = self.prog.module(ref[1])
            if m2 is not None and ref[2] != name or (m2 is not None and m2 is not mod):
                return self.module_const(m2, ref[2], m2.full, _depth + 1)
        return None

    def ev(self, e, ctx):
        """Value set of expression e."""
        try:
            return self._ev(e, ctx)
        except RecursionError:
            return UNKS

    def _ev(self, e, ctx):
        if e is None:
            return frozenset([None])
        if isinstance(e, ast.Constant):
            return frozenset([e.value])
        if isinstance(e, ast.Name):
            if e.id in ctx.env:
                return ctx.env[e.id]
            fn = getattr(ctx, 'fn', None)
            if fn is not None and e.id in [a.arg for a in fn.args.args[1:]]:
                return self.param_values(fn, e.id)
            v = self.module_const(ctx.mod, e.id, e)
            return v if v is not None else UNKS
        if isinstance(e, ast.Attribute):
            a = _self_attr(e)
            if a is not None:
                if 'self.' + a in ctx.env:
                    return ctx.env['self.' + a]
                if ctx.cls is not None:
                    return self.attr_values(ctx.cls, a)[0]
            return UNKS
        if isinstance(e, ast.UnaryOp):
            v = self._ev(e.operand, ctx)
            if isinstance(e.op, ast.Not):
                return frozenset(UNK if x is UNK else (not x) for x in v)
            if isinstance(e.op, ast.USub):
                return frozenset(UNK if x is UNK or not isinstance(x, (int, float)) else -x
                                 for x in v)
            return UNKS
        if isinstance(e, ast.BinOp):
            a, b = self._ev(e.left, ctx), self._ev(e.right, ctx)
            ops = {ast.BitAnd: lambda x, y: x & y, ast.BitOr: lambda x, y: x | y,
                   ast.Add: lambda x, y: x + y, ast.Sub: lambda x, y: x - y,
                   ast.Mult: lambda x, y: x * y}
            op = ops.get(type(e.op))
            out = set()
            for x in a:
                for y in b:
                    if op is None or x is UNK or y is UNK:
                        out.add(UNK)
                        continue
                    try:
                        out.add(op(x, y))
                    except Exception:
                        out.add(UNK)
            return frozenset(out)
        if isinstance(e, ast.BoolOp):
            vals = [self._ev(v, ctx) for v in e.values]
            cur = vals[0]
            for nxt in vals[1:]:
                out = set()
                for x in cur:
                    if x is UNK:
                        out |= set(nxt) | {UNK}
                    elif isinstance(e.op, ast.And):
                        out |= set(nxt) if x else {x}
                    else:
                        out |= {x} if x else set(nxt)
                cur = frozenset(out)
            return cur
        if isinstance(e, ast.Compare) and len(e.ops) == 1:
            a = self._ev(e.left, ctx)
            op = e.ops[0]
            if isinstance(op, (ast.In, ast.NotIn)):
                if isinstance(e.comparators[0], (ast.Tuple, ast.List, ast.Set)):
                    items = [self._ev(x, ctx) for x in e.comparators[0].elts]
                    if any(UNK in s for s in items):
                        return UNKS
                    pool = set().union(*items) if items else set()
                    out = set()
                    for x in a:
                        if x is UNK:
                            out.add(UNK)
                        else:
                            r = x in pool
                            out.add(r if isinstance(op, ast.In) else not r)
                    return frozenset(out)
                return UNKS
            b = self._ev(e.comparators[0], ctx)
            fns = {ast.Eq: lambda x, y: x == y, ast.NotEq: lambda x, y: x != y,
                   ast.Lt: lambda x, y: x < y, ast.LtE: lambda x, y: x <= y,
                   ast.Gt: lambda x, y: x > y, ast.GtE: lambda x, y: x >= y,
                   ast.Is: lambda x, y: x is y, ast.IsNot: lambda x, y: x is not y}
            fn = fns.get(type(op))
            out = set()
            for x in a:
                for y in b:
                    if fn is None or x is UNK or y is UNK or isinstance(x, AList) or isinstance(y, AList):
                        out.add(UNK)
                        continue
                    try:
                        out.add(fn(x, y))
                    except Exception:
                        out.add(UNK)
            return frozenset(out)
        if isinstance(e, ast.IfExp):
            t = _truthy(self._ev(e.test, ctx))
            if t is True:
                return self._ev(e.body, ctx)
            if t is False:
                return self._ev(e.orelse, ctx)
            return self._ev(e.body, ctx) | self._ev(e.orelse, ctx)
        if isinstance(e, (ast.List, ast.Tuple)):
            return frozenset([AList([self._ev(x, ctx) for x in e.elts], node=e)])
        if isinstance(e, ast.ListComp):
            return frozenset([AList(None, self._ev(e.elt, self._comp_ctx(e, ctx)), node=e)])
        if isinstance(e, ast.Subscript):
            base = self._ev(e.value, ctx)
            idx = self._ev(e.slice, ctx)
            out = set()
            for b in base:
                for i in idx:
                    if isinstance(b, AList) and b.elems is not None and isinstance(i, int) \
                            and not isinstance(i, bool) and -len(b.elems) <= i < len(b.elems):
                        out |= b.elems[i]
                    elif isinstance(b, AList):
                        out |= b.any
                    elif isinstance(b, (tuple, list)) and isinstance(i, int):
                        try:
                            out.add(b[i])
                        except Exception:
                            out.add(UNK)
                    else:
                        out.add(UNK)
            return frozenset(out) if out else UNKS
        if isinstance(e, ast.Call):
            f = e.func
            if isinstance(f, ast.Name) and f.id == 'len' and e.args:
                out = set()
                for v in self._ev(e.args[0], ctx):
                    out.add(len(v.elems) if isinstance(v, AList) and v.elems is not None
                            else (len(v) if isinstance(v, str) else UNK))
                return frozenset(out)
            if isinstance(f, ast.Name) and f.id == 'isinstance' and len(e.args) == 2:
                tname = ast.unparse(e.args[1])
                out = set()
                for v in self._ev(e.args[0], ctx):
                    if v is UNK:
                        out.add(UNK)
                    elif tname == 'list':
                        out.add(isinstance(v, AList))
                    elif tname == 'str':
                        out.add(isinstance(v, str))
                    elif tname == 'dict':
                        out.add(False if isinstance(v, (AList, str, int, float, bool)) else UNK)
                    else:
                        out.add(UNK)
                return frozenset(out)
            if isinstance(f, ast.Name) and f.id == 'bool' and e.args:
                return frozenset(UNK if v is UNK else bool(v) for v in self._ev(e.args[0], ctx))
            if (isinstance(f, ast.Attribute) and f.attr == 'get' and isinstance(f.value, ast.Name)
                    and f.value.id == ctx.kwargs_name and ctx.kwargs_name and e.args
                    and isinstance(e.args[0], ast.Constant)):
                k = e.args[0].value
                if ctx.kwargs is not None and k in ctx.kwargs:
                    return ctx.kwargs[k]
                if ctx.kwargs is None or ctx.kwargs.get('**'):
                    return UNKS
                return self._ev(e.args[1], ctx) if len(e.args) > 1 else frozenset([None])
            return UNKS
        return UNKS

    def param_values(self, fn, pname):
        """Values a method parameter takes at every reachable call `<x>.<fn.name>(...)`
        (matched by name, any receiver; calls inside fn itself are skipped)."""
        c = self._cache.setdefault('param', {})
        key = (id(fn), pname)
        if key in c:
            return c[key]
        c[key] = UNKS
        names = [a.arg for a in fn.args.args]
        i = names.index(pname) - 1
        nd = len(fn.args.defaults)
        di = names.index(pname) - (len(names) - nd)
        vals = set()
        found = False
        for m in list(self.prog.modules.values()):
            if m is None:
                continue
            for n in ast.walk(m.full):
                if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and n.func.attr == fn.name):
                    continue
                if _method_of(n) is fn or not self.node_reach(m, n)[0]:
                    continue
                found = True
                kw = [k for k in n.keywords if k.arg == pname]
                ctx = Ctx(self, m, self._class_key_of(n))
                if kw:
                    vals |= self.ev(kw[0].value, ctx)
                elif 0 <= i < len(n.args) and not any(isinstance(a, ast.Starred) for a in n.args):
                    vals |= self.ev(n.args[i], ctx)
                elif di >= 0 and not any(k.arg is None for k in n.keywords):
                    vals |= self.ev(fn.args.defaults[di], ctx)
                else:
                    vals.add(UNK)
        res = frozenset(vals) if found and vals else UNKS
        c[key] = res
        return res

    def _comp_ctx(self, comp, ctx):
        c = ctx.fork()
        for g in comp.generators:
            for n in ast.walk(g.target):
                if isinstance(n, ast.Name):
                    c.env[n.id] = UNKS
        return c

    # ---- liveness of methods ----

    def live(self, key):
        """Live-method analysis of instances of class key."""
        c = self._cache.setdefault('live', {})
        if key in c:
            return c[key]
        eff = self.effective(key)
        mod = self.classes[key]._mod
        info = {'live': {}, 'triggers': collections.defaultdict(set), 'connects': [],
                'disconnects': [], 'dropped': [], 'calls': collections.defaultdict(list)}
        c[key] = info
        mro = set(self.mro(key)) | set(self.subclasses(key))
        todo = []

        def seed(name, why):
            if name in eff:
                info['triggers'][name].add(why)
                todo.append(name)

        seed('__init__', 'init')
        for name in eff:
            if name.endswith('Event') or name in QT_EVENT_NAMES:
                seed(name, 'event:' + name)
            elif '.' not in name:
                for m2, node in self.ext_attr.get(name, []):
                    owner = self._class_key_of(node)
                    if owner not in mro:
                        seed(name, 'external:%s' % _loc(m2, node))
                        break
        seen = set()
        while todo:
            name = todo.pop()
            fn = eff[name]
            first = name not in seen
            seen.add(name)
            info['live'][name] = fn
            dmod = self.classes[fn._key]._mod
            params = [a.arg for a in fn.args.args][1:]
            for call, cond in self._calls_with_conditions(fn, key, dmod, info, name):
                f = call.func
                trig = set(info['triggers'][name])
                if cond is not None and params and cond[0] == params[0]:
                    trig = set('%s[%r]' % (t, cond[1]) for t in trig)
                sg = _signal_of(f)
                if sg and call.args:
                    recv, signame = sg
                    slot = _self_attr(call.args[0])
                    if isinstance(recv, ast.Name) and recv.id == 'self':
                        widget = None
                    else:
                        widget = _self_attr(recv)
                        if widget is None:
                            continue
                    entry = (widget, signame, slot, call, dmod, name)
                    if f.attr == 'connect':
                        if first:
                            info['connects'].append(entry)
                        if slot and slot in eff:
                            t = '%s.%s' % (widget or 'self', signame)
                            if t not in info['triggers'][slot]:
                                info['triggers'][slot].add(t)
                                todo.append(slot)
                    elif first:
                        info['disconnects'].append(entry)
                    continue
                callee = None
                if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == 'self':
                    callee = f.attr
                elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                    t = self.def_target(dmod, f.value, call)
                    if t in self.mro(key):
                        callee = '%s.%s' % (t[1], f.attr)
                        if callee not in eff and eff.get(f.attr) is self.methods_of(t).get(f.attr):
                            callee = f.attr
                elif (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Call)
                      and isinstance(f.value.func, ast.Name) and f.value.func.id == 'super'):
                    mro_l = self.mro(key)
                    k0 = fn._key
                    after = mro_l[mro_l.index(k0) + 1:] if k0 in mro_l else []
                    b = next((b for b in after if f.attr in self.methods_of(b)), None)
                    if b is not None:
                        callee = '%s.%s' % (b[1], f.attr)
                        if eff.get(f.attr) is self.methods_of(b)[f.attr]:
                            callee = f.attr
                if callee and callee in eff:
                    if first:
                        info['calls'][callee].append((name, call, dmod))
                    new = trig - info['triggers'][callee]
                    if new or callee not in info['live']:
                        info['triggers'][callee] |= trig
                        todo.append(callee)
        return info

    def _calls_with_conditions(self, fn, key, mod, info, name):
        """Calls in fn, skipping If branches provably not taken; yields (call,
        cond) where cond = (param, const) for `if param == const` branches."""
        ctx = Ctx(self, mod, key)
        out = []

        def visit(stmts, cond):
            for s in stmts:
                if isinstance(s, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                    continue
                if isinstance(s, ast.If):
                    t = _truthy(self.ev(s.test, ctx))
                    c2 = cond
                    if (isinstance(s.test, ast.Compare) and len(s.test.ops) == 1
                            and isinstance(s.test.ops[0], ast.Eq)
                            and isinstance(s.test.left, ast.Name)
                            and isinstance(s.test.comparators[0], ast.Constant)):
                        c2 = (s.test.left.id, s.test.comparators[0].value)
                    for n in _walk_no_defs(s.test):
                        if isinstance(n, ast.Call):
                            out.append((n, cond))
                    if t is False:
                        for n in s.body:
                            for m in _walk_no_defs(n):
                                if isinstance(m, ast.Call):
                                    info['dropped'].append(
                                        (m, mod, 'test `%s` is %s' % (
                                            ast.unparse(s.test), _fmt(self.ev(s.test, ctx)))))
                                    break
                    else:
                        visit(s.body, c2)
                    if t is True:
                        continue
                    visit(s.orelse, cond)
                    continue
                for field, value in ast.iter_fields(s):
                    if isinstance(value, list) and value and isinstance(value[0], ast.stmt):
                        visit(value, cond)
                    elif isinstance(value, list):
                        for v in value:
                            if isinstance(v, ast.AST):
                                for n in _walk_no_defs(v):
                                    if isinstance(n, ast.Call):
                                        out.append((n, cond))
                    elif isinstance(value, ast.AST):
                        for n in _walk_no_defs(value):
                            if isinstance(n, ast.Call):
                                out.append((n, cond))
            return out

        visit(fn.body, None)
        out.sort(key=lambda x: (x[0].lineno, x[0].col_offset))
        return out

    def method_live(self, key, fn):
        """Is FunctionDef fn live for some reachable class using it?  (live, evidence)"""
        users = []
        for k in self.classes:
            eff = self.effective(k)
            if any(f is fn for f in eff.values()):
                users.append(k)
        reachable_users = [k for k in users if self.node_reach(self.classes[k]._mod, self.classes[k])[0]]
        for k in reachable_users:
            if any(f is fn for f in self.live(k)['live'].values()):
                return True, []
        evid = []
        for k in reachable_users:
            info = self.live(k)
            for nm, f in self.effective(k).items():
                if f is fn:
                    for caller, call, m in info['calls'].get(nm, []):
                        evid.append('called from %s (%s, not live)' % (caller, _loc(m, call)))
                    for w, sig, slot, call, m, meth in info['connects']:
                        if slot == nm:
                            evid.append('slot of %s.%s connected in %s (%s)' % (w or 'self', sig, meth, _loc(m, call)))
            for call, m, why in info['dropped']:
                evid.append('dropped call %s at %s: %s' % (ast.unparse(call.func), _loc(m, call), why))
        if not reachable_users:
            return None, []
        # references to fn's name anywhere in the class family
        nm = fn.name
        for k in reachable_users:
            for f in self.effective(k).values():
                for n in ast.walk(f):
                    if isinstance(n, ast.Attribute) and n.attr == nm and f is not fn:
                        evid.append('named in %s.%s (%s), which is not live' % (
                            f._key[1], f.name, _loc(self.classes[f._key]._mod, n)))
        return False, sorted(set(evid))

    # ---- rows ----

    def add(self, mod, node, kind, widget, owner, name, sub=None, label='', tooltip='',
            evidence=(), hidden=False, inert=False, reach=None, trigger=''):
        if reach is None:
            reachable, why = self.node_reach(mod, node)
        else:
            reachable, why = reach
        rid = '%s.%s' % (owner, name) + ('.%s' % sub if sub else '')
        self.rows.append({
            'id': rid, 'file': mod.rel, 'line': node.lineno, 'loc': _loc(mod, node),
            'class': owner, 'kind': kind, 'widget': widget, 'label': label or '',
            'tooltip': tooltip or '', 'reachable': bool(reachable), 'reach': why,
            'hidden': bool(hidden), 'inert': bool(inert), 'evidence': list(evidence),
            'trigger': trigger, '_mod': mod, '_node': node, '_attr': None})
        return self.rows[-1]

    def owner_and_method(self, mod, node):
        cls = _enclosing_class(node)
        fn = _top_method(node)
        if cls is not None:
            return cls.name, (fn.name if fn is not None else '<class>'), getattr(cls, '_key', None)
        if fn is not None:
            return mod.base, fn.name, None
        return mod.base, ('__main__' if node._dead == 'main-block' else '<module>'), None

    def unbound_name(self, owner, method):
        self._counters[(owner, method)] += 1
        return '%s@%d' % (method, self._counters[(owner, method)])

    def scan(self):
        candidates = []
        for mod in self.gui_modules:
            for node in ast.walk(mod.full):
                if isinstance(node, ast.Call):
                    candidates.append((mod, node))
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == 'keyPressEvent':
                    candidates.append((mod, node))
        candidates.sort(key=lambda x: (x[0].rel, x[1].lineno, x[1].col_offset))
        self._helpers = self._dialog_helpers()
        self._helper_only = self._helper_only_classes()
        self._table_sites = []
        for mod, node in candidates:
            if isinstance(node, ast.Call):
                self._call(mod, node)
            else:
                self._keys(mod, node)
        self._views()
        self._finish()
        return self.rows

    # dialogs -----------------------------------------------------------

    def _opener(self, mod, call):
        """Kind of modal dialog `call` opens, else None."""
        f = call.func
        if isinstance(f, ast.Attribute) and f.attr in ('exec_', 'exec'):
            var = ast.unparse(f.value)
            scope = _method_of(call) or mod.full
            built = None
            for n in ast.walk(scope):
                if (isinstance(n, ast.Assign) and len(n.targets) == 1
                        and ast.unparse(n.targets[0]) == var and isinstance(n.value, ast.Call)):
                    built = n.value
            if built is None:
                return None
            if isinstance(built.func, ast.Name) and built.func.id in self._local_names(scope):
                # e.g. qcd = QColorDialog; w = qcd(...)
                for n in ast.walk(scope):
                    if (isinstance(n, ast.Assign) and len(n.targets) == 1
                            and ast.unparse(n.targets[0]) == built.func.id):
                        q = self.qt_name(mod, n.value, n)
                        if q:
                            return self._qt_dialog_kind(q, built)
            ct = self.call_type(mod, built)
            if ct is None:
                ref = self.resolve(mod, built.func.id, built) if isinstance(built.func, ast.Name) else None
                if ref and ref[0] == 'sym' and ref[1] and ref[1].startswith(self.prog.package + '.') \
                        and self.prog.module(ref[1]) is None:
                    return ('dialog', '%s (module %s not in the source tree)' % (ref[2], ref[1]))
                return None
            if ct[1] in ('QApplication', 'QCoreApplication', 'QEventLoop', 'QThread', 'QDrag'):
                return None
            if ct[0] == 'qt':
                if ct[1] == 'QApplication':
                    return None
                return self._qt_dialog_kind(ct[1], built)
            if ct[0] == 'cls':
                return ('class', ct[1])
            return None
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            qt = self.qt_name(mod, f.value, call)
            if qt in STATIC_DIALOGS and f.attr in STATIC_DIALOGS[qt]:
                kind = {'QFileDialog': 'file-dialog', 'QColorDialog': 'color-dialog',
                        'QInputDialog': 'dialog', 'QMessageBox': 'message'}[qt]
                if qt == 'QMessageBox' and f.attr == 'question':
                    kind = 'confirm'
                return (kind, '%s.%s' % (qt, f.attr))
        return None

    def _local_names(self, scope):
        out = set()
        for n in ast.walk(scope):
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        out.add(t.id)
        return out

    def _qt_dialog_kind(self, qt, built):
        if qt == 'QMenu':
            return ('popup', 'QMenu.exec_')
        if qt == 'QMessageBox':
            src = ast.unparse(built)
            return ('confirm' if 'Cancel' in src or 'No' in src else 'message', 'QMessageBox.exec_')
        if qt == 'QFileDialog':
            return ('file-dialog', 'QFileDialog.exec_')
        if qt == 'QColorDialog':
            return ('color-dialog', 'QColorDialog.exec_')
        return ('dialog', '%s.exec_' % qt)

    def _class_has(self, key, qts, _seen=None):
        _seen = _seen or set()
        if key in _seen:
            return False
        _seen.add(key)
        for fn in self.effective(key).values():
            for n in ast.walk(fn):
                if isinstance(n, ast.Call):
                    ct = self.call_type(self.classes[fn._key]._mod, n)
                    if self.type_set(ct) & qts:
                        return True
                    if ct and ct[0] == 'cls' and self._class_has(ct[1], qts, _seen):
                        return True
        return False

    def _dialog_helpers(self):
        """Module-level functions that open a modal: key -> (kind, what, opener call)."""
        out = {}
        for m in list(self.prog.modules.values()):
            if m is None:
                continue
            for s in m.full.body:
                if not isinstance(s, ast.FunctionDef):
                    continue
                for n in ast.walk(s):
                    if isinstance(n, ast.Call):
                        op = self._opener(m, n)
                        if op is None:
                            continue
                        if op[0] == 'class':
                            kind = 'popup' if self._class_has(op[1], {'QListWidget', 'QMenu'}) else 'dialog'
                            op = (kind, op[1][1])
                        out[(m.name, s.name)] = (op[0], op[1], n)
                        break
        return out

    def _helper_only_classes(self):
        """Classes instantiated only inside dialog helpers."""
        out = {}
        for key in self.classes:
            sites = self.sites.get(key, [])
            if not sites:
                continue
            hs = set()
            for m, call in sites:
                fn = _top_method(call)
                if fn is None or _enclosing_class(call) is not None or (m.name, fn.name) not in self._helpers:
                    hs = None
                    break
                hs.add(fn.name)
            if hs:
                out[key] = sorted(hs)
        return out

    # calls ---------------------------------------------------------------

    def _call(self, mod, call):
        owner, method, ckey = self.owner_and_method(mod, call)
        fn_top = _top_method(call)
        in_helper = (fn_top is not None and _enclosing_class(call) is None
                     and (mod.name, fn_top.name) in self._helpers)
        ctype = self.call_type(mod, call)
        var = _assigned_to(call)
        attr = var[5:] if var and var.startswith('self.') and '.' not in var[5:] and '[' not in var else None

        def name_for():
            return attr if attr else self.unbound_name(owner, method)

        # helper call sites
        if ctype and ctype[0] == 'func' and ctype[1] in self._helpers:
            kind, what, _ = self._helpers[ctype[1]]
            label = _const_text([k.value for k in call.keywords if k.arg in ('text', 'title', 'win_title', 'caption')] + call.args)
            if label is None and len(call.args) > 1:
                label = ast.unparse(call.args[1])
            self.add(mod, call, kind, 'helper:%s' % ctype[1][1], owner, name_for(), label=label,
                     trigger=method)
            return
        # direct openers (not inside a helper that has call sites)
        op = self._opener(mod, call)
        if op is not None:
            if in_helper and self.fsites.get((mod.name, fn_top.name)):
                return
            if op[0] == 'class':
                return            # in-scope dialog class: its widgets are rows
            label = None
            for k in call.keywords:
                if k.arg in ('caption', 'title', 'text', 'windowTitle'):
                    label = _const_text([k.value])
            self.add(mod, call, op[0], op[1], owner, name_for(), label=label or op[1], trigger=method)
            return
        if in_helper:
            return
        # tabs / menu items
        f = call.func
        if isinstance(f, ast.Attribute) and f.attr in ('addTab', 'addAction') and (ctype is None or ctype[0] != 'cls'):
            holder = ast.unparse(f.value)
            ht = self._var_type(mod, _enclosing_class(call) or _method_of(call) or mod.full, holder)
            if (f.attr == 'addTab' and ht in TAB_TYPES) or (f.attr == 'addAction' and ht in MENU_TYPES):
                kind = 'tab' if f.attr == 'addTab' else 'menu-item'
                hname = holder[5:] if holder.startswith('self.') else None
                labels = self._loop_labels(mod, call)
                base = hname or self.unbound_name(owner, method)
                if labels:
                    for lab in labels:
                        self.add(mod, call, kind, ht, owner, base, sub=_sanitize(lab), label=lab)
                else:
                    lab = _const_text(call.args)
                    self.add(mod, call, kind, ht, owner, base, sub=_sanitize(lab) if lab else None,
                             label=lab or ast.unparse(call.args[0]) if call.args else '')
            return
        if ctype is None or ctype[0] == 'func':
            return
        types = self.type_set(ctype)
        if ctype[0] == 'cls' and ctype[1] in self._helper_only:
            return
        if types & VIEW_TYPES:
            self._table_sites.append((mod, call, ctype, owner, method, attr))
            return
        wtypes = sorted(t for t in types if t in WIDGET_KIND)
        if not wtypes:
            return
        if ckey is not None and ckey in self._helper_only:
            return
        base = wtypes[0]
        kind = WIDGET_KIND[base]
        qt = ctype[1] if ctype[0] == 'qt' else ctype[1][1]
        typ = base if qt == base else '%s(%s)' % (qt, base)
        scope = _enclosing_class(call) or _method_of(call) or mod.full
        label = _const_text(call.args)
        if not label and var:
            for c in self._calls_on(scope, var, 'setText'):
                label = _const_text(c.args) or label
        tooltip = None
        if var:
            for c in self._calls_on(scope, var, 'setToolTip'):
                tooltip = _const_text(c.args) or tooltip
        loop_labels = self._loop_labels(mod, call)
        if kind == 'combo' and attr and ckey is not None:
            items = self._combo_dispatch(mod, ckey, attr)
            if items:
                for idx, text in items:
                    r = self.add(mod, call, 'combo-item', typ, owner, attr, sub=_sanitize(text),
                                 label='%s (index %r)' % (text, idx), tooltip=tooltip,
                                 trigger='%s.%s[%r]' % (attr, items.signal, idx))
                    r['_attr'] = attr
                return
            if not label:
                st = self._combo_items(mod, ckey, attr)
                if st:
                    label = '|'.join(str(s) for s in st)
                else:
                    label = self._combo_items_src(ckey, attr) or ''
        nm = name_for()
        if loop_labels:
            for lab in loop_labels:
                r = self.add(mod, call, kind, typ, owner, nm, sub=_sanitize(lab), label=lab, tooltip=tooltip)
                r['_attr'] = attr
        else:
            row = self.add(mod, call, kind, typ, owner, nm, label=label, tooltip=tooltip)
            if attr is None and _enclosing(call, (ast.For, ast.While, ast.comprehension)) is not None:
                row['evidence'].append('built in a loop over a run-time sequence')
            row['_attr'] = attr

    def _calls_on(self, scope, var, method):
        out = []
        for n in ast.walk(scope):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == method and ast.unparse(n.func.value) == var):
                out.append(n)
        return out

    def _var_type(self, mod, scope, var):
        for n in ast.walk(scope):
            if (isinstance(n, ast.Assign) and len(n.targets) == 1
                    and ast.unparse(n.targets[0]) == var and isinstance(n.value, ast.Call)):
                t = self.call_type(mod, n.value)
                for group in (TAB_TYPES, MENU_TYPES):
                    g = self.type_set(t) & group
                    if g:
                        return sorted(g)[0]
        return None

    def _static_list(self, mod, expr, node):
        """Elements of a literal list/tuple, or of a name / self.attr bound to one."""
        if isinstance(expr, (ast.List, ast.Tuple)):
            if all(isinstance(e, ast.Constant) for e in expr.elts):
                return [e.value for e in expr.elts]
            return None
        name = expr.id if isinstance(expr, ast.Name) else _self_attr(expr)
        if name is None:
            return None
        scopes = [_method_of(node), _enclosing_class(node), mod.full]
        for scope in scopes:
            if scope is None:
                continue
            body = scope.body if not isinstance(scope, ast.Module) else scope.body
            stmts = list(ast.walk(scope)) if isinstance(scope, ast.FunctionDef) else body
            for s in stmts:
                if (isinstance(s, ast.Assign) and len(s.targets) == 1
                        and ast.unparse(s.targets[0]) in (name, 'self.' + name)
                        and isinstance(s.value, (ast.List, ast.Tuple))):
                    return self._static_list(mod, s.value, s)
            if isinstance(scope, ast.Module):
                for s in ast.walk(scope):
                    if (isinstance(s, ast.Assign) and len(s.targets) == 1
                            and isinstance(s.targets[0], ast.Name) and s.targets[0].id == name
                            and isinstance(s.value, (ast.List, ast.Tuple))
                            and getattr(s, '_dead', None) == getattr(node, '_dead', None)):
                        return self._static_list(mod, s.value, s)
        return None

    def _loop_labels(self, mod, call):
        """Labels when call sits in a for-loop over a static list and uses the loop var."""
        p = getattr(call, '_parent', None)
        while p is not None and not isinstance(p, (ast.FunctionDef, ast.ClassDef, ast.Module)):
            if isinstance(p, ast.For) and isinstance(p.target, ast.Name):
                vals = self._static_list(mod, p.iter, p)
                used = any(isinstance(a, ast.Name) and a.id == p.target.id for a in call.args)
                if vals is not None and used:
                    return [str(v) for v in vals]
                return None
            p = getattr(p, '_parent', None)
        return None

    def _combo_items(self, mod, ckey, attr):
        for fn in self.methods_of(ckey).values():
            for c in self._calls_on(fn, 'self.' + attr, 'addItems'):
                if c.args:
                    vals = self._static_list(mod, c.args[0], c)
                    if vals is not None:
                        return vals
        return None

    def _combo_items_src(self, ckey, attr):
        """Source of what feeds addItems when it is not static."""
        for fn in self.methods_of(ckey).values():
            for c in self._calls_on(fn, 'self.' + attr, 'addItems'):
                if not c.args:
                    continue
                a = c.args[0]
                src = ast.unparse(a)
                if _self_attr(a):
                    for n in ast.walk(self.classes[ckey]):
                        if (isinstance(n, ast.Assign) and len(n.targets) == 1
                                and _self_attr(n.targets[0]) == _self_attr(a)):
                            return 'items: %s = %s' % (src, ast.unparse(n.value))
                return 'items: %s' % src
        return None

    def _combo_dispatch(self, mod, ckey, attr):
        """[(index, text)] when the combo's slot dispatches on constant indices."""
        methods = self.effective(ckey)
        for fn in self.methods_of(ckey).values():
            for n in ast.walk(fn):
                if not isinstance(n, ast.Call):
                    continue
                sg = _signal_of(n.func)
                if not sg or n.func.attr != 'connect' or _self_attr(sg[0]) != attr:
                    continue
                if sg[1] not in COMBO_SIGNALS or not n.args:
                    continue
                slot = methods.get(_self_attr(n.args[0]) or '')
                if slot is None or len(slot.args.args) < 2:
                    continue
                p = slot.args.args[1].arg
                consts = []
                for t in ast.walk(slot):
                    if (isinstance(t, ast.Compare) and len(t.ops) == 1 and isinstance(t.ops[0], ast.Eq)
                            and isinstance(t.left, ast.Name) and t.left.id == p
                            and isinstance(t.comparators[0], ast.Constant)):
                        consts.append(t.comparators[0].value)
                if not consts:
                    continue
                items = self._combo_items(mod, ckey, attr) or []
                out = _Dispatch()
                out.signal = sg[1]
                for k in consts:
                    if isinstance(k, int) and 0 <= k < len(items):
                        out.append((k, str(items[k])))
                    else:
                        out.append((k, str(k)))
                return out
        return None

    def _keys(self, mod, fn):
        owner, _, ckey = self.owner_and_method(mod, fn)
        cls = _enclosing_class(fn)
        if cls is None:
            return
        for n in ast.walk(fn):
            if (isinstance(n, ast.Compare) and len(n.ops) == 1 and isinstance(n.ops[0], ast.Eq)
                    and isinstance(n.left, ast.Call) and isinstance(n.left.func, ast.Attribute)
                    and n.left.func.attr == 'key' and isinstance(n.comparators[0], ast.Attribute)
                    and n.comparators[0].attr.startswith('Key_')):
                key = n.comparators[0].attr[4:]
                self.add(mod, n, 'key', 'keyPressEvent', owner, 'keyPressEvent', sub=_sanitize(key),
                         label='Key_' + key)

    # views ---------------------------------------------------------------

    def _forwarding_targets(self, mod, call, ctype):
        """Expand a site of a wrapper class that forwards **kwargs to a view."""
        return [(mod, call, ctype)]

    def _views(self):
        """Columns for sites with a static header; cells/clicks for other views."""
        # 1. wrapper forwarding: view built with **kwargs of the enclosing __init__
        #    (or **self.kwargs) -> the sites of the enclosing class are the sites.
        col_sites = []          # (site mod, site call, owner, name-ctx, view key, kwargs, unknown)
        cell_views = collections.defaultdict(list)   # view key -> [(mod, call, kwargs)]
        for mod, call, ctype, owner, method, attr in self._table_sites:
            outer = self._outer_sites(mod, call)
            for (smod, scall, sowner, smethod, sattr, kwargs, unknown) in outer:
                vkey = ctype[1] if ctype[0] == 'cls' else None
                cols, cols_ev = self._columns(smod, scall, vkey, kwargs)
                if cols:
                    col_sites.append((smod, scall, sowner, smethod, sattr, vkey, ctype, kwargs,
                                      unknown, cols, cols_ev))
                elif vkey is not None:
                    cell_views[vkey].append((smod, scall, kwargs, unknown))
        seen = set()
        for site in col_sites:
            smod, scall = site[0], site[1]
            if (smod.rel, scall.lineno, scall.col_offset) in seen:
                continue
            seen.add((smod.rel, scall.lineno, scall.col_offset))
            self._column_rows(*site)
        for vkey in sorted(cell_views):
            self._cell_rows(vkey, cell_views[vkey])

    def _outer_sites(self, mod, call):
        """[(mod, call, owner, method, attr, kwargs, unknown)] where the view's
        keyword arguments are written."""
        owner, method, ckey = self.owner_and_method(mod, call)
        var = _assigned_to(call)
        attr = var[5:] if var and var.startswith('self.') else None
        kwargs, unknown = self.site_kwargs(mod, call)
        star = [k.value for k in call.keywords if k.arg is None]
        fn = _method_of(call)
        if star and ckey is not None and fn is not None:
            s = star[0]
            init = self.methods_of(ckey).get('__init__')
            kwname = init.args.kwarg.arg if init is not None and init.args.kwarg else None
            fwd = False
            if isinstance(s, ast.Name) and fn is init and s.id == kwname:
                fwd = True
            elif _self_attr(s) is not None and init is not None:
                for n in ast.walk(init):
                    if (isinstance(n, ast.Assign) and len(n.targets) == 1
                            and _self_attr(n.targets[0]) == _self_attr(s)
                            and isinstance(n.value, ast.Name) and n.value.id == kwname):
                        fwd = True
            if fwd:
                out = []
                for smod, scall in self.sites.get(ckey, []):
                    for o in self._outer_sites(smod, scall):
                        extra = dict(o[5])
                        extra.update(kwargs)
                        out.append(o[:5] + (extra, o[6]))
                return out
        return [(mod, call, owner, method, attr, kwargs, unknown)]

    def _column_method(self, vkey):
        """(method, kwarg name used for the header, static header) of a view class."""
        for name, fn in self.effective(vkey).items():
            for n in ast.walk(fn):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and n.func.attr == 'setHorizontalHeaderLabels' and n.args):
                    a = n.args[0]
                    if isinstance(a, ast.Name):
                        kw = fn.args.kwarg.arg if fn.args.kwarg else None
                        for m in ast.walk(fn):
                            if (isinstance(m, ast.Assign) and len(m.targets) == 1
                                    and isinstance(m.targets[0], ast.Name) and m.targets[0].id == a.id
                                    and isinstance(m.value, ast.Call)
                                    and isinstance(m.value.func, ast.Attribute)
                                    and m.value.func.attr == 'get' and m.value.args
                                    and isinstance(m.value.func.value, ast.Name)
                                    and m.value.func.value.id == kw
                                    and isinstance(m.value.args[0], ast.Constant)):
                                return fn, m.value.args[0].value, None
                    vals = self._static_list(self.classes[fn._key]._mod, a, n)
                    if vals is not None:
                        return fn, None, vals
        return None, None, None

    def _columns(self, smod, scall, vkey, kwargs):
        if vkey is None:
            return None, None
        fn, kw, static = self._column_method(vkey)
        if fn is None:
            return None, None
        if static is not None:
            return static, '%s static header' % _loc(self.classes[fn._key]._mod, fn)
        for k in scall.keywords:
            if k.arg == kw:
                vals = self._static_list(smod, k.value, scall)
                if vals is not None:
                    return vals, '%s %s=%s' % (_loc(smod, scall), kw, ast.unparse(k.value))
        return None, None

    def _row_template(self, smod, scall, expr, depth=0):
        """Value set for the table data passed at a site (tableio=...)."""
        if expr is None or depth > 4:
            return UNKS, []
        ctx = Ctx(self, smod, self._class_key_of(scall))
        if isinstance(expr, (ast.List, ast.Tuple)):
            return self.ev(expr, ctx), ['%s literal table' % _loc(smod, expr)]
        if isinstance(expr, ast.Name):
            scope = _method_of(scall) or smod.full
            for n in ast.walk(scope):
                if not isinstance(n, ast.Assign) or n.lineno > scall.lineno:
                    continue
                if getattr(n, '_dead', None) != getattr(scall, '_dead', None):
                    continue
                for t in n.targets:
                    idx = None
                    if isinstance(t, ast.Name) and t.id == expr.id:
                        idx = -1
                    elif isinstance(t, ast.Tuple):
                        for i, e in enumerate(t.elts):
                            if isinstance(e, ast.Name) and e.id == expr.id:
                                idx = i
                    if idx is None:
                        continue
                    if isinstance(n.value, (ast.List, ast.Tuple)) and idx == -1:
                        return self.ev(n.value, ctx), ['%s literal table' % _loc(smod, n)]
                    if isinstance(n.value, ast.Call):
                        r = self._producer(smod, n.value, idx, depth)
                        if r is not None:
                            return r
        return UNKS, ['table data at %s not resolved' % _loc(smod, scall)]

    def _producer(self, mod, call, idx, depth):
        t = self.def_target(mod, call.func, call)
        if not t:
            return None
        pm = self.prog.modules[t[0]]
        fn = pm.fdefs[t[1]]
        if not isinstance(fn, ast.FunctionDef):
            return None
        for r in (n for n in ast.walk(fn) if isinstance(n, ast.Return) and n.value is not None):
            v = r.value
            if idx >= 0 and isinstance(v, ast.Tuple) and idx < len(v.elts):
                v = v.elts[idx]
            if isinstance(v, ast.ListComp) and len(v.generators) == 1:
                it = v.generators[0].iter
                params = [a.arg for a in fn.args.args]
                if isinstance(it, ast.Name) and it.id in params:
                    i = params.index(it.id)
                    if i < len(call.args):
                        vals, ev_ = self._row_template(mod, call, call.args[i], depth + 1)
                        return vals, ev_ + ['%s filters rows (%s)' % (_loc(pm, v), ast.unparse(v))]
            if isinstance(v, ast.Name):
                for n in ast.walk(fn):
                    if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                            and n.func.attr == 'append' and isinstance(n.func.value, ast.Name)
                            and n.func.value.id == v.id and n.args
                            and isinstance(n.args[0], (ast.List, ast.Tuple))):
                        env = self._flow_env(pm, fn)
                        row = self.ev(n.args[0], Ctx(self, pm, None, env))
                        return (frozenset([AList(None, row, node=n)]),
                                ['%s row template %s' % (_loc(pm, n), ast.unparse(n.args[0]))])
        return None

    def _flow_env(self, mod, fn):
        """Flow-insensitive value sets of fn's local names (assignments and +=)."""
        env = {}
        assigns = collections.defaultdict(list)
        augs = collections.defaultdict(list)
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        assigns[t.id].append(n.value)
                    elif isinstance(t, ast.Tuple):
                        for e in t.elts:
                            if isinstance(e, ast.Name):
                                assigns[e.id].append(None)
            elif isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name):
                augs[n.target.id].append(n)
            elif isinstance(n, (ast.For, ast.comprehension)):
                for e in ast.walk(n.target):
                    if isinstance(e, ast.Name):
                        assigns[e.id].append(None)
        for a in fn.args.args:
            assigns[a.arg].append(None)
        for _ in range(2):
            for name, vals in assigns.items():
                out = set()
                for v in vals:
                    out |= UNKS if v is None else self.ev(v, Ctx(self, mod, None, dict(env)))
                for a in augs.get(name, []):
                    d = self.ev(a.value, Ctx(self, mod, None, dict(env)))
                    if isinstance(a.op, ast.Add):
                        out |= {UNK if x is UNK or y is UNK else x + y for x in out for y in d}
                    else:
                        out.add(UNK)
                env[name] = frozenset(out) if out else UNKS
        return env

    def interpret(self, fn, ctx, records):
        """Abstract execution of fn's body; records[(item creation node, column ctx)]
        -> caps at commit points (setItem/appendRow)."""
        state = {'caps': {}}
        self._exec(fn.body, ctx, state, records, depth=0)

    def _exec(self, stmts, ctx, state, records, depth):
        if depth > 6:
            return
        for s in stmts:
            if isinstance(s, (ast.FunctionDef, ast.ClassDef, ast.Return)):
                if isinstance(s, ast.Return):
                    return
                continue
            if isinstance(s, ast.Assign):
                v = s.value
                if isinstance(v, ast.Call) and self.qt_name(ctx.mod, v.func, v) in ITEM_TYPES:
                    for t in s.targets:
                        if isinstance(t, ast.Name):
                            state['caps'][t.id] = {'site': s, 'edit': frozenset([True]),
                                                   'check': frozenset([False]),
                                                   'enabled': frozenset([True])}
                    continue
                val = self.ev(v, ctx)
                for t in s.targets:
                    if isinstance(t, ast.Name):
                        ctx.env[t.id] = val
                    elif _self_attr(t) is not None:
                        ctx.env['self.' + _self_attr(t)] = val
                    elif isinstance(t, ast.Tuple):
                        for e in t.elts:
                            if isinstance(e, ast.Name):
                                ctx.env[e.id] = UNKS
                continue
            if isinstance(s, ast.AugAssign) and isinstance(s.target, ast.Name):
                ctx.env[s.target.id] = UNKS
                continue
            if isinstance(s, ast.If):
                t = _truthy(self.ev(s.test, ctx))
                if t is True:
                    self._exec(s.body, ctx, state, records, depth)
                elif t is False:
                    self._exec(s.orelse, ctx, state, records, depth)
                else:
                    c1, s1 = ctx.fork(), _copy_state(state)
                    c2, s2 = ctx.fork(), _copy_state(state)
                    self._exec(s.body, c1, s1, records, depth)
                    self._exec(s.orelse, c2, s2, records, depth)
                    _merge(ctx, state, [(c1, s1), (c2, s2)])
                continue
            if isinstance(s, ast.For):
                iters = self._iterations(s, ctx)
                branches = []
                for binding in iters:
                    c1, s1 = ctx.fork(), _copy_state(state)
                    c1.env.update(binding)
                    self._exec(s.body, c1, s1, records, depth + 1)
                    branches.append((c1, s1))
                if branches:
                    _merge(ctx, state, branches)
                continue
            if isinstance(s, ast.Expr) and isinstance(s.value, ast.Call):
                call = s.value
                f = call.func
                if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                    var = f.value.id
                    capname = {'setEditable': 'edit', 'setCheckable': 'check',
                               'setEnabled': 'enabled'}.get(f.attr)
                    if var in state['caps'] and capname and call.args:
                        state['caps'][var] = dict(state['caps'][var])
                        state['caps'][var][capname] = self.ev(call.args[0], ctx)
                        state['caps'][var][capname + '_at'] = call
                        continue
                    if var in state['caps'] and f.attr == 'setFlags':
                        caps = dict(state['caps'][var])
                        for k in ('edit', 'check'):
                            caps[k] = UNKS
                        state['caps'][var] = caps
                        continue
                if isinstance(f, ast.Attribute) and f.attr in ('setItem', 'appendRow', 'insertRow',
                                                               'setChild', 'addItem'):
                    args = call.args
                    item = args[-1] if args else None
                    if isinstance(item, ast.Name) and item.id in state['caps']:
                        col = self.ev(args[1], ctx) if f.attr == 'setItem' and len(args) >= 3 else None
                        caps = state['caps'][item.id]
                        key = (caps['site'], col if col is None else frozenset(col))
                        prev = records.get(key)
                        records[key] = caps if prev is None else _union_caps(prev, caps)
                continue
            # other statements: descend into nested blocks conservatively
            for field, value in ast.iter_fields(s):
                if isinstance(value, list) and value and isinstance(value[0], ast.stmt):
                    self._exec(value, ctx, state, records, depth + 1)

    def _iterations(self, loop, ctx):
        """List of env bindings, one per abstract iteration of a for-loop."""
        it = loop.iter
        tgt = loop.target
        seq, enum = it, False
        zipped = None
        if isinstance(it, ast.Call) and isinstance(it.func, ast.Name) and it.args:
            if it.func.id == 'enumerate':
                seq, enum = it.args[0], True
            elif it.func.id == 'zip':
                zipped = it.args
        out = []
        if zipped is not None:
            lists = [self.ev(a, ctx) for a in zipped]
            elems = []
            for vs in lists:
                al = [v for v in vs if isinstance(v, AList)]
                elems.append(frozenset().union(*[a.any for a in al]) if al else UNKS)
            if isinstance(tgt, ast.Tuple) and len(tgt.elts) == len(elems):
                b = {}
                for e, vs in zip(tgt.elts, elems):
                    if isinstance(e, ast.Name):
                        b[e.id] = vs
                return [b]
            return [self._bind_unknown(tgt)]
        vals = self.ev(seq, ctx)
        alists = [v for v in vals if isinstance(v, AList)]
        if not alists or UNK in vals:
            return [self._bind_unknown(tgt)]
        for al in alists:
            if al.elems is not None:
                for i, ev_ in enumerate(al.elems):
                    out.append(self._bind(tgt, ev_, i if enum else None, enum))
            else:
                out.append(self._bind(tgt, al.any, UNK if enum else None, enum))
        return out

    def _bind(self, tgt, value, index, enum):
        b = {}
        if enum:
            if isinstance(tgt, ast.Tuple) and len(tgt.elts) == 2:
                if isinstance(tgt.elts[0], ast.Name):
                    b[tgt.elts[0].id] = frozenset([index])
                if isinstance(tgt.elts[1], ast.Name):
                    b[tgt.elts[1].id] = value
                return b
            return self._bind_unknown(tgt)
        if isinstance(tgt, ast.Name):
            b[tgt.id] = value
            return b
        return self._bind_unknown(tgt)

    def _bind_unknown(self, tgt):
        return {n.id: UNKS for n in ast.walk(tgt) if isinstance(n, ast.Name)}

    def _view_ctx(self, vkey, fn, kwargs, unknown):
        mod = self.classes[fn._key]._mod
        kw = fn.args.kwarg.arg if fn.args.kwarg else None
        env = {a.arg: UNKS for a in fn.args.args[1:]}
        kws = dict(kwargs)
        if unknown:
            kws['**'] = True
        return Ctx(self, mod, vkey, env, kwargs_name=kw, kwargs=kws)

    def _click_actions(self, vkey):
        """[(callee, column title or None, requires, evidence)] for the view's click slots."""
        info = self.live(vkey)
        eff = self.effective(vkey)
        out = []
        for w, sig, slot, call, m, meth in info['connects']:
            if w is not None or sig not in ('clicked', 'doubleClicked', 'pressed', 'activated'):
                continue
            fn = eff.get(slot)
            if fn is None:
                continue
            for n in ast.walk(fn):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and isinstance(n.func.value, ast.Name) and n.func.value.id == 'self'
                        and n.func.attr in eff):
                    callee = eff[n.func.attr]
                    col, req = self._guards(callee)
                    if self._does_something(vkey, callee):
                        out.append((n.func.attr, col, req, '%s %s.%s -> %s' % (
                            _loc(m, call), sig, slot, n.func.attr), sig))
                elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                      and n.func.attr not in TRIVIAL_CALLS and n.func.attr not in eff
                      and not (isinstance(n.func.value, ast.Name) and n.func.value.id in ('logger', 'logging'))):
                    out.append((n.func.attr, None, None, '%s %s.%s calls %s' % (
                        _loc(m, call), sig, slot, n.func.attr), sig))
        return out

    def _guards(self, fn):
        col, req = None, None
        for s in fn.body:
            if isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant):
                continue
            if not (isinstance(s, ast.If) and len(s.body) == 1 and isinstance(s.body[0], ast.Return)
                    and isinstance(s.test, ast.UnaryOp) and isinstance(s.test.op, ast.Not)
                    and isinstance(s.test.operand, ast.Call)):
                if isinstance(s, ast.Assign):
                    continue
                break
            c = s.test.operand
            if (isinstance(c.func, ast.Attribute) and c.func.attr == 'is_column_for_title'
                    and len(c.args) == 2 and isinstance(c.args[1], ast.Constant)):
                col = c.args[1].value
            elif isinstance(c.func, ast.Attribute) and c.func.attr in ('isEditable', 'isCheckable'):
                req = 'edit' if c.func.attr == 'isEditable' else 'check'
        return col, req

    def _does_something(self, vkey, fn, _seen=None):
        _seen = _seen or set()
        if id(fn) in _seen:
            return False
        _seen.add(id(fn))
        eff = self.effective(vkey)
        for n in ast.walk(fn):
            if not isinstance(n, ast.Call):
                continue
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else '')
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in ('logger', 'logging'):
                continue
            if name in TRIVIAL_CALLS:
                continue
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == 'self' and name in eff:
                if self._does_something(vkey, eff[name], _seen):
                    return True
                continue
            return True
        return False

    def _column_rows(self, smod, scall, sowner, smethod, sattr, vkey, ctype, kwargs, unknown,
                     cols, cols_ev):
        reach = self.node_reach(smod, scall)
        name = sattr if sattr else self.unbound_name(sowner, smethod)
        fn, _, _ = self._column_method(vkey)
        records = {}
        ev_ = [cols_ev]
        if fn is not None:
            kws = dict(kwargs)
            tab_kw = None
            for k in ('tableio', 'table', 'data', 'list2d'):
                if k in kws:
                    tab_kw = k
            if tab_kw:
                kexpr = next((k.value for k in scall.keywords if k.arg == tab_kw), None)
                if kexpr is None:
                    kexpr = self._kw_expr_outer(scall, tab_kw)
                tv, tev = self._row_template(smod, scall, kexpr)
                kws[tab_kw] = tv
                ev_ += tev
            ctx = self._view_ctx(vkey, fn, kws, unknown)
            for k in ('do_ctrl', 'do_edit'):
                if k in kws:
                    ev_.append('%s=%s' % (k, _fmt(kws[k])))
            self.interpret(fn, ctx, records)
        clicks = self._click_actions(vkey)
        fmod = self.classes[fn._key]._mod if fn is not None else smod
        for i, col in enumerate(cols):
            caps = None
            for (site, cset), cp in records.items():
                if cset is None or i in cset or UNK in cset:
                    caps = cp if caps is None else _union_caps(caps, cp)
            evid = list(ev_)
            check = edit = False
            if caps is not None:
                en = caps['enabled']
                check = _may_be_true(caps['check']) and _may_be_true(en)
                edit = _may_be_true(caps['edit']) and _may_be_true(en)
                for cname in ('check', 'edit'):
                    at = caps.get(cname + '_at')
                    evid.append('%s %s %s' % (_loc(fmod, at) if at is not None else 'default',
                                              {'check': 'checkable', 'edit': 'editable'}[cname],
                                              _fmt(caps[cname])))
            else:
                evid.append('cells not evaluated')
                check = edit = True
            acts = []
            for callee, gcol, req, cev, sig in clicks:
                if gcol is not None and gcol != col:
                    continue
                if req == 'edit' and not edit:
                    continue
                if req == 'check' and not check:
                    continue
                acts.append(cev)
            if acts:
                evid.append('click: ' + '; '.join(acts))
            else:
                evid.append('no click action for this column')
            caps_txt = ','.join(x for x, ok in (('check', check), ('edit', edit), ('click', bool(acts))) if ok)
            inert = not (check or edit or acts)
            self.add(smod, scall, 'column', '%s[%s]' % (vkey[1], col), sowner, name, sub=_sanitize(col),
                     label='%s%s' % (col, (' (%s)' % caps_txt) if caps_txt else ''),
                     evidence=evid if (inert or True) else [], inert=inert and reach[0], reach=reach)

    def _kw_expr_outer(self, scall, kw):
        return None

    def _cell_rows(self, vkey, sites):
        vmod = self.classes[vkey]._mod
        reach_sites = [(m, c, k, u) for (m, c, k, u) in sites if self.node_reach(m, c)[0]]
        use = reach_sites or sites
        vreach = (True, '') if reach_sites else self.node_reach(sites[0][0], sites[0][1])
        site_ev = [] if reach_sites else ['%s is instantiated only at %s (%s)' % (
            vkey[1], ', '.join(sorted(set(_loc(m, c) for m, c, _, _ in sites))), vreach[1])]
        eff = self.effective(vkey)
        records = {}
        for fn in sorted(set(eff.values()), key=lambda f: (f._key, f.lineno), reverse=False):
            if not any(isinstance(n, ast.Call) and self.qt_name(self.classes[fn._key]._mod, n.func, n) in ITEM_TYPES
                       for n in ast.walk(fn)):
                continue
            for m, c, kwargs, unknown in use:
                ctx = self._view_ctx(vkey, fn, kwargs, unknown)
                self.interpret(fn, ctx, records)
        by_site = collections.OrderedDict()
        for (site, cset), caps in sorted(records.items(), key=lambda kv: kv[0][0].lineno):
            prev = by_site.get(site)
            by_site[site] = caps if prev is None else _union_caps(prev, caps)
        info = self.live(vkey) if vreach[0] else None
        for site, caps in by_site.items():
            fn = _method_of(site)
            dkey = fn._key if hasattr(fn, '_key') else vkey
            dmod = self.classes[dkey]._mod
            owner = vkey[1]
            name = self.unbound_name(owner, fn.name)
            reach = vreach
            live_ev = list(site_ev)
            if reach[0] and info is not None and fn.name in eff and fn not in info['live'].values():
                ok, ev2 = self.method_live(vkey, fn)
                if ok is False:
                    reach = (False, 'method-not-live')
                    live_ev = ['%s.%s is not live' % (vkey[1], fn.name)] + ev2 + [
                        'no call or reference to %s from live code' % fn.name]
            en = caps['enabled']
            parts = []
            for cname in ('check', 'edit'):
                if _may_be_true(caps[cname]) and _may_be_true(en):
                    parts.append(cname)
            evid = []
            for cname in ('check', 'edit', 'enabled'):
                at = caps.get(cname + '_at')
                evid.append('%s %s %s' % (_loc(dmod, at) if at is not None else 'default(Qt)',
                                          cname, _fmt(caps[cname])))
            label = ast.unparse(site.value)
            evid = live_ev + evid
            if parts:
                for p in parts:
                    self.add(dmod, site, 'cell', 'item', owner, name, sub=p, label='%s: %s' % (p, label),
                             evidence=evid, reach=reach)
            else:
                self.add(dmod, site, 'cell', 'item', owner, name, label=label, evidence=evid,
                         inert=reach[0], reach=reach)
        # clicks on the view itself
        info = self.live(vkey)
        for w, sig, slot, call, m, meth in info['connects']:
            if w is not None or sig not in VIEW_SIGNALS:
                continue
            evid = site_ev + ['%s self.%s.connect(self.%s) in %s' % (_loc(m, call), sig, slot, meth)]
            inert = False
            for w2, sig2, slot2, call2, m2, meth2 in info['disconnects']:
                if w2 is None and sig2 == sig and slot2 == slot:
                    evid.append('%s disconnected in %s' % (_loc(m2, call2), meth2))
                    inert = True
            fn = eff.get(slot)
            if not inert and sig not in ('expanded', 'collapsed') and fn is not None \
                    and not self._does_something(vkey, fn):
                evid.append('slot %s only logs/reads (%s)' % (slot, _loc(self.classes[fn._key]._mod, fn)))
                inert = True
            self.add(m, call, 'click', sig, vkey[1], sig, label='%s -> %s' % (sig, slot), evidence=evid,
                     inert=inert and vreach[0], reach=vreach)

    # finishing: hidden / inert / liveness for widget and dialog rows ------

    def _finish(self):
        self._liveness_pass()
        for r in self.rows:
            for k in [k for k in r if k.startswith('_')]:
                del r[k]
            seen, ev_ = set(), []
            for e in r['evidence']:
                if e not in seen:
                    seen.add(e)
                    ev_.append(e)
            r['evidence'] = ev_
        self.rows.sort(key=lambda r: (r['file'], r['line'], r['id']))
        ids = collections.Counter()
        for r in self.rows:
            ids[r['id']] += 1
            if ids[r['id']] > 1:
                r['id'] = '%s~%d' % (r['id'], ids[r['id']])

    def _liveness_pass(self):
        for row in self.rows:
            if not row['reachable'] or row['kind'] in ('column', 'cell', 'click'):
                continue
            mod, node = row['_mod'], row['_node']
            cls = _enclosing_class(node)
            if cls is None or not hasattr(cls, '_key'):
                continue
            key = cls._key
            fn = _top_method(node)
            if fn is None:
                continue
            info = self.live(key)
            if fn not in info['live'].values():
                ok, evid = self.method_live(key, fn)
                if ok is False:
                    if self._fallback(mod, key, node, row):
                        continue
                    row['reachable'] = False
                    row['reach'] = 'method-not-live'
                    row['evidence'] += ['%s.%s is not live' % (key[1], fn.name)] + evid
                    continue
            if self._fallback(mod, key, node, row):
                continue
            trig = sorted(info['triggers'].get(fn.name, []))
            if row['kind'] in WIDGET_ROW_KINDS:
                self._widget_flags(mod, key, row['_attr'], row, info)
            elif row['kind'] != 'key':
                row['trigger'] = ', '.join(trig) or row['trigger']
                hidden_widgets = {r['_attr'] for r in self.rows
                                  if r['class'] == key[1] and r['hidden'] and r.get('_attr')}
                ws = {t.split('.')[0] for t in trig}
                if trig and ws <= hidden_widgets:
                    row['hidden'] = True
                    row['evidence'].append('opened only from hidden %s' % ', '.join(sorted(ws)))

    def _fallback(self, mod, key, node, row):
        """else-branch of an exhaustive dispatch on a static tuple (see docstring)."""
        ret = _enclosing(node, (ast.Return,))
        p = getattr(node, '_parent', None)
        if not isinstance(p, ast.Return):
            return False
        chain = []
        cur, child = p._parent, p
        while isinstance(cur, ast.If) and child in cur.orelse:
            chain.append(cur)
            child, cur = cur, cur._parent
        if not chain:
            return False
        fn = _method_of(node)
        if fn is None or len(fn.args.args) < 2:
            return False
        param = fn.args.args[1].arg
        tname, idxs = None, set()
        for i in chain:
            t = i.test
            if not (isinstance(t, ast.Compare) and len(t.ops) == 1 and isinstance(t.ops[0], ast.Eq)
                    and isinstance(t.left, ast.Name) and t.left.id == param
                    and isinstance(t.comparators[0], ast.Subscript)):
                return False
            sub = t.comparators[0]
            nm = ast.unparse(sub.value)
            if tname not in (None, nm) or not isinstance(sub.slice, ast.Constant):
                return False
            tname = nm
            idxs.add(sub.slice.value)
        vals = self._static_list(mod, ast.parse(tname, mode='eval').body, node) if tname else None
        if vals is None or idxs != set(range(len(vals))):
            return False
        callers = []
        for f2 in self.methods_of(key).values():
            for n in ast.walk(f2):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and _self_attr(n.func) == fn.name):
                    if not n.args:
                        return False
                    a = n.args[0]
                    ok = isinstance(a, ast.Subscript) and ast.unparse(a.value) == tname
                    if isinstance(a, ast.Name):
                        for m in ast.walk(f2):
                            if (isinstance(m, ast.Assign) and len(m.targets) == 1
                                    and isinstance(m.targets[0], ast.Name) and m.targets[0].id == a.id
                                    and isinstance(m.value, ast.Subscript)
                                    and ast.unparse(m.value.value) == tname):
                                ok = True
                                callers.append(_loc(mod, m))
                    if not ok:
                        return False
                    callers.append(_loc(mod, n))
        if not callers:
            return False
        row['reachable'] = False
        row['reach'] = 'fallback-branch'
        row['evidence'].append('else of %s == %s[i] for every i of %s=%r (%s); every call passes an '
                               'element of %s (%s)' % (param, tname, tname, tuple(vals),
                                                       ', '.join(_loc(mod, i) for i in chain), tname,
                                                       ', '.join(callers)))
        return True

    def _widget_flags(self, mod, key, attr, row, info):
        if attr is None or '@' in attr:
            return
        eff = self.effective(key)
        live_fns = list(info['live'].values())
        # hidden
        vis = []
        for fn in live_fns:
            for n in ast.walk(fn):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and _self_attr(n.func.value) == attr
                        and n.func.attr in ('setVisible', 'setHidden', 'show', 'hide')):
                    vis.append((fn, n))
        if vis:
            shown = False
            evid = []
            for fn, n in vis:
                ctx = Ctx(self, self.classes[fn._key]._mod, key)
                ctx.fn = _method_of(n)
                if n.func.attr == 'setVisible' and n.args:
                    v = self.ev(n.args[0], ctx)
                    t = _truthy(v)
                    evid.append('%s %s.setVisible(%s) -> %s' % (_loc(self.classes[fn._key]._mod, n), attr,
                                                               ast.unparse(n.args[0]), _fmt(v)))
                    if n.args and _self_attr(n.args[0]):
                        evid += self.attr_values(key, _self_attr(n.args[0]))[1]
                    if t is not False:
                        shown = True
                elif n.func.attr == 'hide':
                    evid.append('%s %s.hide()' % (_loc(self.classes[fn._key]._mod, n), attr))
                else:
                    shown = True
            if not shown:
                row['hidden'] = True
                row['evidence'] += evid
        # inert: read-only text
        if row['kind'] == 'text':
            ro = []
            for fn in live_fns:
                for n in ast.walk(fn):
                    if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                            and _self_attr(n.func.value) == attr and n.func.attr == 'setReadOnly' and n.args):
                        cx = Ctx(self, self.classes[fn._key]._mod, key)
                        cx.fn = _method_of(n)
                        ro.append((fn, n, self.ev(n.args[0], cx)))
            if ro and all(_truthy(v) is True for _, _, v in ro):
                row['inert'] = True
                row['evidence'] += ['%s setReadOnly(%s)' % (_loc(self.classes[f._key]._mod, n),
                                                            ast.unparse(n.args[0])) for f, n, _ in ro]
            return
        if row['kind'] == 'combo-item':
            if not any(c[0] == attr for c in info['connects']):
                row['inert'] = True
                row['evidence'].append('no live connection of %s' % attr)
            return
        # inert: no live connection and state never read
        conns = [c for c in info['connects'] if c[0] == attr]
        ext = [(m, n) for m, n in self.ext_connect.get(attr, []) if self.node_reach(m, n)[0]]
        reads = []
        for fn in live_fns:
            for n in ast.walk(fn):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and n.func.attr in STATE_READS and _self_attr(n.func.value) == attr
                        and not (row['kind'] == 'button' and n.func.attr == 'text')):
                    reads.append(n)
        for m, n in self.attr_reads.get(attr, []):
            if self.node_reach(m, n)[0] and not (isinstance(n.func.value.value, ast.Name)
                                                 and n.func.value.value.id == 'self'):
                reads.append(n)
        if not conns and not ext and not reads:
            row['inert'] = True
            allc = []
            for fn in eff.values():
                for n in ast.walk(fn):
                    sg = _signal_of(n.func) if isinstance(n, ast.Call) else None
                    if sg and n.func.attr == 'connect' and _self_attr(sg[0]) == attr:
                        allc.append('%s connect in %s (not live)' % (
                            _loc(self.classes[fn._key]._mod, n), fn.name))
            row['evidence'].append('no live signal connection and state never read')
            row['evidence'] += allc
            for call, m, why in info['dropped']:
                row['evidence'].append('dropped %s at %s: %s' % (ast.unparse(call.func), _loc(m, call), why))
        elif conns:
            row['trigger'] = ', '.join(sorted('%s->%s' % (c[1], c[2]) for c in conns))


class _Dispatch(list):
    signal = ''


def _copy_state(state):
    return {'caps': dict(state['caps'])}


def _union_caps(a, b):
    out = dict(a)
    for k in ('edit', 'check', 'enabled'):
        out[k] = a[k] | b[k]
    for k in ('edit_at', 'check_at', 'enabled_at'):
        out[k] = a.get(k) or b.get(k)
    return out


def _merge(ctx, state, branches):
    names = set()
    for c, _ in branches:
        names |= set(c.env)
    for n in names:
        vals = frozenset()
        for c, _ in branches:
            vals = vals | c.env.get(n, UNKS)
        ctx.env[n] = vals
    caps = {}
    for _, s in branches:
        for var, cp in s['caps'].items():
            if var in caps and caps[var]['site'] is cp['site']:
                caps[var] = _union_caps(caps[var], cp)
            else:
                caps[var] = cp
    state['caps'] = caps


# ---------------------------------------------------------------------------

COLUMNS = ['id', 'loc', 'class', 'kind', 'widget', 'label', 'tooltip', 'reachable', 'reach',
           'hidden', 'inert', 'trigger', 'evidence']


def summary(rows, en):
    lines = ['N = %d rows (user affordances)' % len(rows)]
    by_kind = collections.Counter(r['kind'] for r in rows)
    lines.append('by kind: ' + ', '.join('%s %d' % kv for kv in sorted(by_kind.items())))
    reach = [r for r in rows if r['reachable']]
    live = [r for r in reach if not r['hidden'] and not r['inert']]
    lines.append('reachable %d (of which hidden %d, inert %d, user-facing %d); not reachable %d'
                 % (len(reach), sum(r['hidden'] for r in reach), sum(r['inert'] and not r['hidden'] for r in reach),
                    len(live), len(rows) - len(reach)))
    why = collections.Counter(r['reach'] for r in rows if not r['reachable'])
    lines.append('not reachable by reason: ' + ', '.join('%s %d' % kv for kv in sorted(why.items())))
    lines.append('user-facing by kind: ' + ', '.join(
        '%s %d' % kv for kv in sorted(collections.Counter(r['kind'] for r in live).items())))
    lines.append('by file (all / user-facing):')
    allf = collections.Counter(r['file'] for r in rows)
    livef = collections.Counter(r['file'] for r in live)
    lines.extend('  %3d %3d  %s' % (n, livef.get(f, 0), f) for f, n in sorted(allf.items()))
    mods = sorted(m.rel for m in en.gui_modules if en.module_reachable(m))
    lines.append('reachable control_gui modules (%d): %s' % (len(mods), ' '.join(mods)))
    un = sorted(m.rel for m in en.gui_modules if not en.module_reachable(m))
    lines.append('control_gui modules not reachable (%d): %s' % (len(un), ' '.join(un)))
    ho = sorted('%s (via %s)' % (k[1], ','.join(v)) for k, v in en._helper_only.items())
    lines.append('classes covered by helper call-site rows: %s' % ', '.join(ho))
    return '\n'.join(lines)


def default_src():
    here = os.path.dirname(os.path.abspath(__file__))       # psdaq/webgui/parity
    return os.path.dirname(os.path.dirname(here))           # psdaq/


def enumerate_rows(src=None):
    en = Enumerator(src or default_src())
    return en.scan(), en


def main(argv=None):
    parser = argparse.ArgumentParser(description='Enumerate PyQt control GUI affordances from source')
    parser.add_argument('--src', default=default_src(), help='the psdaq package directory')
    parser.add_argument('--format', choices=('tsv', 'json', 'summary'), default='tsv')
    args = parser.parse_args(argv)
    rows, en = enumerate_rows(args.src)
    if args.format == 'json':
        json.dump(rows, sys.stdout, indent=1)
        print()
    elif args.format == 'summary':
        print(summary(rows, en))
    else:
        print('\t'.join(COLUMNS))
        for r in rows:
            vals = []
            for c in COLUMNS:
                v = r[c]
                if isinstance(v, list):
                    v = ' | '.join(v)
                vals.append(str(v).replace('\t', ' ').replace('\n', '\\n'))
            print('\t'.join(vals))
    return 0


if __name__ == '__main__':
    sys.exit(main())
