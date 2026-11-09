"""
Every psdaq file outside control_gui that constructs a QApplication, from source (Python `ast`).

The psdaq package directory (--src, default: the one this file is in) is walked; a file is read
when it is a .py file or has no extension and a python shebang (procmgr/procstat).  A file is
listed when its syntax tree has a call `QApplication(...)` or `<anything>.QApplication(...)`
(PyQt5 QtWidgets or PyQt4 QtGui); `QApplication.instance()` and the like are not constructions.
control_gui/ is the control GUI, checked by check_parity, and is left out.

For each file the scan also records the facts check_gui_parity needs to tell a GUI program from
a file that only builds a QApplication for something else (a test, the offscreen walk, a widget
library's demo):
  sites       line of each construction, the def/class it is in, and the enclosing guards
              (`if __name__ == '__main__':`, other `if` tests)
  main_block  line of `if __name__ == '__main__':` (or None)
  entry       console script / shared-data bin entry in psdaq/pyproject.toml naming this file
  imported_by other psdaq files that import this module
  offscreen   construction sites in a function that sets QT_QPA_PLATFORM to 'offscreen' first
  test        the file is a pytest module (tests/ dir, test_*.py)
A file that does not parse is listed with its parse error (it can not be checked).
As a cross-check, every other file under the psdaq tree whose text contains 'QApplication(' is
reported (non-Python sources), so a construction the ast scan cannot see is not lost silently.

Usage:
    python -m psdaq.webgui.parity.qapps [--src DIR] [--json]
"""

import argparse
import ast
import json
import os
import re
import sys

SKIP_DIRS = ('control_gui',)
QAPP = 'QApplication'


def default_src():
    here = os.path.dirname(os.path.abspath(__file__))       # psdaq/webgui/parity
    return os.path.dirname(os.path.dirname(here))           # psdaq/


def _is_python(path):
    if path.endswith('.py'):
        return True
    if os.path.splitext(path)[1]:
        return False
    try:
        with open(path, 'rb') as f:
            first = f.readline(200)
    except OSError:
        return False
    return first.startswith(b'#!') and b'python' in first


def python_files(src):
    out = []
    for dirpath, dirnames, files in os.walk(src):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and d != '__pycache__'
                             and not d.startswith('.'))
        if os.path.relpath(dirpath, src).split(os.sep)[0] in SKIP_DIRS:
            continue
        for f in sorted(files):
            p = os.path.join(dirpath, f)
            if os.path.isfile(p) and _is_python(p):
                out.append(p)
    return out


def _is_main_test(node):
    """`if __name__ == '__main__':`"""
    t = node.test if isinstance(node, ast.If) else None
    return (isinstance(t, ast.Compare) and isinstance(t.left, ast.Name) and t.left.id == '__name__'
            and len(t.comparators) == 1 and isinstance(t.comparators[0], ast.Constant)
            and t.comparators[0].value == '__main__')


def _is_qapp_call(node):
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    return (isinstance(f, ast.Name) and f.id == QAPP) or (isinstance(f, ast.Attribute) and f.attr == QAPP)


def _sets_offscreen(fn):
    """True if the function body assigns 'offscreen' to QT_QPA_PLATFORM (os.environ[...] = / setdefault)."""
    for n in ast.walk(fn):
        if isinstance(n, ast.Constant) and n.value == 'offscreen':
            return True
    return False


class _Scan(ast.NodeVisitor):
    def __init__(self, text):
        self.text = text.splitlines()
        self.stack = []         # (kind, name, node)
        self.sites = []
        self.main_block = None
        self.imports = set()

    def _guard_text(self, node):
        try:
            return ast.unparse(node.test)
        except Exception:
            return '?'

    def generic_visit(self, node):
        if isinstance(node, ast.If):
            if _is_main_test(node):
                self.main_block = node.lineno
            self.stack.append(('if', node, node))
            for n in node.body:
                self.visit(n)
            self.stack.pop()
            self.stack.append(('else', node, node))
            for n in node.orelse:
                self.visit(n)
            self.stack.pop()
            self.visit(node.test)
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            self.stack.append(('def' if not isinstance(node, ast.ClassDef) else 'class', node.name, node))
            super().generic_visit(node)
            self.stack.pop()
            return
        if isinstance(node, ast.Import):
            for a in node.names:
                self.imports.add(a.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            self.imports.add(('.' * node.level) + node.module)
            for a in node.names:
                self.imports.add(('.' * node.level) + node.module + '.' + a.name)
        if _is_qapp_call(node):
            scope = [name for kind, name, _ in self.stack if kind in ('def', 'class')]
            guards = []
            for kind, n, _ in self.stack:
                if kind in ('if', 'else'):
                    g = ('if %s' if kind == 'if' else 'else of if %s') % self._guard_text(n)
                    guards.append('%s (line %d)' % (g, n.lineno))
            fns = [nd for kind, _, nd in self.stack if kind == 'def']
            self.sites.append({'line': node.lineno, 'scope': '.'.join(scope) or '<module>',
                               'guards': guards,
                               'main_block': any(k == 'if' and _is_main_test(n) for k, n, _ in self.stack),
                               'offscreen': bool(fns) and _sets_offscreen(fns[-1]),
                               'code': self.text[node.lineno - 1].strip()})
        super().generic_visit(node)


def entry_points(src):
    """{relative file: entry text} from psdaq/pyproject.toml ([project.scripts] and shared-data bins)."""
    out = {}
    pp = os.path.join(os.path.dirname(src), 'pyproject.toml')
    if not os.path.isfile(pp):
        return out
    section = None
    with open(pp) as f:
        for n, line in enumerate(f, 1):
            s = line.strip()
            if s.startswith('['):
                section = s
                continue
            m = re.match(r'^"?([^"=\s]+)"?\s*=\s*"([^"]+)"', s)
            if not m:
                continue
            if section == '[project.scripts]':
                mod = m.group(2).split(':')[0]
                rel = mod.split('.', 1)[1].replace('.', '/') + '.py' if mod.startswith('psdaq.') else None
                if rel:
                    out.setdefault(rel, []).append('console script %s = %s (pyproject.toml:%d)' % (
                        m.group(1), m.group(2), n))
            elif section and 'shared-data' in section and m.group(1).startswith('psdaq/'):
                rel = m.group(1).split('/', 1)[1]
                out.setdefault(rel, []).append('shared-data %s -> %s (pyproject.toml:%d)' % (
                    m.group(1), m.group(2), n))
    return out


def _module_name(rel):
    if not rel.endswith('.py'):
        return None
    return 'psdaq.' + rel[:-3].replace('/', '.').replace('.__init__', '')


def scan(src=None, text_only=None):
    """[{file, sites, main_block, entry, imported_by, test, parse_error}] sorted by file.
    text_only (a list, if given) gets the Python files whose text has 'QApplication(' but whose syntax tree
    constructs none: {file, string_lines} (the string constants holding it)."""
    text_only = [] if text_only is None else text_only
    src = os.path.abspath(src or default_src())
    eps = entry_points(src)
    all_imports = {}
    found = []
    for p in python_files(src):
        rel = os.path.relpath(p, src)
        with open(p, 'rb') as f:
            data = f.read()
        text = data.decode('utf-8', 'replace')
        try:
            tree = ast.parse(data, filename=p)
        except SyntaxError as ex:
            if QAPP in text:
                found.append({'file': rel, 'parse_error': '%s:%s %s' % (rel, ex.lineno, ex.msg), 'sites': []})
            continue
        sc = _Scan(text)
        sc.visit(tree)
        all_imports[rel] = sc.imports
        if not sc.sites and QAPP + '(' in text:
            strs = sorted(n.lineno for n in ast.walk(tree)
                          if isinstance(n, ast.Constant) and isinstance(n.value, str) and QAPP + '(' in n.value)
            text_only.append({'file': rel, 'string_lines': strs})
        if sc.sites:
            found.append({'file': rel, 'sites': sc.sites, 'main_block': sc.main_block,
                          'entry': eps.get(rel, []), 'parse_error': None,
                          'test': (os.sep + 'tests' + os.sep) in (os.sep + rel) and
                          os.path.basename(rel).startswith('test_')})
    for e in found:
        mod = _module_name(e['file'])
        pkg = mod.rsplit('.', 1)[0] if mod else None
        users = []
        if mod:
            short = mod.rsplit('.', 1)[1]
            for rel, imps in sorted(all_imports.items()):
                if rel == e['file']:
                    continue
                rpkg = (_module_name(rel) or '').rsplit('.', 1)[0]
                for i in imps:
                    absn = i
                    if i.startswith('.'):
                        absn = rpkg + '.' + i.lstrip('.')
                    if absn == mod or absn.startswith(mod + '.') or (rpkg == pkg and i in ('.' + short,)):
                        users.append(rel)
                        break
        e['imported_by'] = users
    return found


def grep_others(src, found):
    """Files under the psdaq tree (src's parent) that contain 'QApplication(' but are not Python files
    the ast scan read (e.g. C++), outside control_gui."""
    root = os.path.dirname(os.path.abspath(src))
    seen = {os.path.join(os.path.abspath(src), e['file']) for e in found}
    py = set(python_files(os.path.abspath(src)))
    out = []
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith('.')
                             and d not in ('build', '__pycache__'))
        for f in files:
            p = os.path.join(dirpath, f)
            if p in seen or p in py:
                continue
            if os.path.splitext(f)[1] in ('.pyc', '.so', '.o', '.a', '.png', '.gif', '.svg', '.pdf', '.xtc2'):
                continue
            try:
                with open(p, 'rb') as fh:
                    if b'QApplication(' in fh.read(4 << 20):
                        out.append(os.path.relpath(p, root))
            except OSError:
                pass
    return sorted(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description='psdaq files outside control_gui that construct a QApplication')
    ap.add_argument('--src', default=default_src(), help='psdaq package directory')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    text_only = []
    found = scan(a.src, text_only)
    others = grep_others(a.src, found)
    if a.json:
        json.dump({'files': found, 'non_python_hits': others, 'text_only': text_only}, sys.stdout, indent=1)
        print()
        return 0
    for e in found:
        s = '; '.join('%d in %s%s' % (x['line'], x['scope'], (' [%s]' % ', '.join(x['guards'])) if x['guards'] else '')
                      for x in e['sites'])
        print('%s | %s | entry: %s | imported by: %s' % (e['file'], e.get('parse_error') or s,
                                                         '; '.join(e.get('entry') or []) or '-',
                                                         ', '.join(e.get('imported_by') or []) or '-'))
    for t in text_only:
        print('not listed: %s has "QApplication(" only in %s; its syntax tree constructs none' % (
            t['file'], ('string constant(s) at line(s) %s' % ', '.join(map(str, t['string_lines'])))
            if t['string_lines'] else 'comments'))
    print('%d files construct a QApplication (outside control_gui); non-Python files with "QApplication(": %d%s'
          % (len(found), len(others), (' ' + ', '.join(others)) if others else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
