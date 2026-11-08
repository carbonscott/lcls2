"""Tests for the parity checker (psdaq.webgui.parity.check_parity).

A small synthetic PyQt package gives 4 rows (2 user-facing buttons, 1 hidden
button, 1 button in an unreachable module); mapping and junit files are
written to tmp_path.
"""

import json
import os
import textwrap

import pytest

from psdaq.webgui.parity import check_parity as cpar

FILES = {
    "__init__.py": "",
    "control_gui/__init__.py": "",
    "control_gui/app/__init__.py": "",
    "control_gui/app/control_gui.py": """
        from psdaq.control_gui.Main import Main
        def control_gui():
            Main()
        """,
    "control_gui/Main.py": """
        from PyQt5.QtWidgets import QWidget, QPushButton
        from psdaq.control_gui.Logger import Logger
        class Main(QWidget):
            def __init__(self):
                self.but_a = QPushButton('A')
                self.but_a.clicked.connect(self.on_a)
                self.but_b = QPushButton('B')
                self.but_b.clicked.connect(self.on_a)
                self.log = Logger(show_buttons=False)
            def on_a(self):
                pass
        """,
    "control_gui/Logger.py": """
        from PyQt5.QtWidgets import QWidget, QPushButton
        class Logger(QWidget):
            def __init__(self, **kwargs):
                self.show_buttons = kwargs.get('show_buttons', True)
                self.but_x = QPushButton('X')
                self.but_x.clicked.connect(self.close)
                self.but_x.setVisible(self.show_buttons)
        """,
    "control_gui/Unused.py": """
        from PyQt5.QtWidgets import QWidget, QPushButton
        class Unused(QWidget):
            def __init__(self):
                self.but_u = QPushButton('U')
        """,
}

COMPLETE = {
    "Main.but_a": {"web": "[data-parity~='Main.but_a']", "test": "tests/test_ui.py::test_a"},
    "Main.but_b": {"web": "[data-parity~='Main.but_b']", "test": "tests/test_ui.py::TestB::test_b[x]"},
    "Logger.but_x": {"na": "hidden: setVisible(self.show_buttons), show_buttons=False"},
    "Unused.but_u": {"na": "module not imported from the entry point"},
}


def junit(path, failing=()):
    cases = []
    for cls, name in (('tests.test_ui', 'test_a'), ('tests.test_ui.TestB', 'test_b[x]')):
        body = '<failure message="boom">assert 0</failure>' if name in failing else ''
        cases.append('<testcase classname="%s" name="%s" time="0.1">%s</testcase>' % (cls, name, body))
    with open(path, 'w') as f:
        f.write('<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="2">%s'
                '</testsuite></testsuites>' % ''.join(cases))
    return str(path)


@pytest.fixture
def pkg(tmp_path):
    root = tmp_path / 'psdaq'
    for rel, text in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))
    return str(root)


def run(capsys, src, mapping, tmp_path, junit_files, extra=()):
    mp = tmp_path / 'mapping.json'
    mp.write_text(json.dumps(mapping))
    argv = ['--src', src, '--mapping', str(mp)] + sum([['--junit', j] for j in junit_files], []) + list(extra)
    code = cpar.main(argv)
    return code, capsys.readouterr().out


def test_complete_mapping_passes(pkg, tmp_path, capsys):
    code, out = run(capsys, pkg, COMPLETE, tmp_path, [junit(tmp_path / 'j.xml')])
    assert code == 0, out
    assert '4 controls found, 2 mapped to a web element with a passing headless-browser test, ' \
           '2 marked not applicable' in out
    assert 'Logger.but_x | control_gui/Logger.py:6 | hidden | hidden: setVisible' in out
    assert 'Unused.but_u | control_gui/Unused.py:5 | unreachable:module-unreachable | module not' in out
    assert 'RESULT: PASS (M + K = N = 4)' in out


def test_one_mapping_removed_fails_and_names_it(pkg, tmp_path, capsys):
    m = dict(COMPLETE)
    del m['Main.but_b']
    code, out = run(capsys, pkg, m, tmp_path, [junit(tmp_path / 'j.xml')])
    assert code != 0
    assert 'Unmapped (1 rows)' in out and '  Main.but_b | control_gui/Main.py:8 | button | B' in out
    assert 'RESULT: FAIL: M + K = 3 != N = 4 (1 unmapped, 0 not passing, 0 unproven na)' in out


def test_failing_test_fails(pkg, tmp_path, capsys):
    code, out = run(capsys, pkg, COMPLETE, tmp_path, [junit(tmp_path / 'j.xml', failing=('test_b[x]',))])
    assert code != 0
    assert 'Main.but_b | tests/test_ui.py::TestB::test_b[x] | failed' in out


def test_missing_test_and_no_junit_fail(pkg, tmp_path, capsys):
    m = dict(COMPLETE)
    m['Main.but_a'] = {"web": "#a", "test": "tests/test_ui.py::test_not_there"}
    code, out = run(capsys, pkg, m, tmp_path, [junit(tmp_path / 'j.xml')])
    assert code != 0 and 'Main.but_a | tests/test_ui.py::test_not_there | missing' in out
    code, out = run(capsys, pkg, COMPLETE, tmp_path, [])
    assert code != 0 and 'no junit given' in out


def test_stale_and_invalid_entries_fail(pkg, tmp_path, capsys):
    m = dict(COMPLETE)
    m['Main.but_gone'] = {"na": "removed"}
    code, out = run(capsys, pkg, m, tmp_path, [junit(tmp_path / 'j.xml')])
    assert code != 0 and 'Stale mapping entries' in out and 'Main.but_gone' in out
    m = dict(COMPLETE)
    m['Unused.but_u'] = {"na": "two\nlines"}
    code, out = run(capsys, pkg, m, tmp_path, [junit(tmp_path / 'j.xml')])
    assert code != 0 and 'Unused.but_u: na reason must be a non-empty one-line string' in out


def test_na_on_user_facing_row_needs_flag(pkg, tmp_path, capsys):
    m = dict(COMPLETE)
    m['Main.but_b'] = {"na": "not needed on the web"}
    code, out = run(capsys, pkg, m, tmp_path, [junit(tmp_path / 'j.xml')])
    assert code != 0 and 'Main.but_b | control_gui/Main.py:8 | not needed on the web' in out
    code, out = run(capsys, pkg, m, tmp_path, [junit(tmp_path / 'j.xml')], ['--allow-unproven-na'])
    assert code == 0, out


def test_no_rows_fails(tmp_path, capsys):
    root = tmp_path / 'empty' / 'psdaq'
    (root / 'control_gui' / 'app').mkdir(parents=True)
    for rel in ('__init__.py', 'control_gui/__init__.py', 'control_gui/app/__init__.py'):
        (root / rel).write_text('')
    (root / 'control_gui/app/control_gui.py').write_text('def control_gui():\n    pass\n')
    code, out = run(capsys, str(root), {}, tmp_path, [junit(tmp_path / 'j.xml')])
    assert code != 0 and 'RESULT: FAIL: N = 0' in out


REAL = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.mark.skipif(not os.path.isfile(cpar.DEFAULT_MAPPING), reason='no mapping.json')
def test_draft_mapping_is_consistent():
    rows, _ = cpar.enumerate_rows(REAL)
    with open(cpar.DEFAULT_MAPPING) as f:
        mapping = json.load(f)
    rep = cpar.check(rows, mapping, None)
    assert not rep['stale'] and not rep['invalid'] and not rep['unproven_na']
    for r, reason in rep['na']:
        assert cpar.enum_flags(r), r['id']
