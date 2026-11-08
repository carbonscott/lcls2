"""Tests for the parity checker (psdaq.webgui.parity.check_parity).

A small synthetic PyQt package gives 6 rows: 2 user-facing buttons and the Alt+A mnemonic of one,
1 hidden button, 1 button in an unreachable module (its import commented out) and 1 in a main
block.  Mapping, junit and walk files are written to tmp_path.  The last tests run the checker on
the real control_gui with the real mapping and the saved offscreen walk (parity/qt_walk.json).
"""

import json
import os
import textwrap

import pytest

from psdaq.webgui.parity import check_parity as cpar
from psdaq.webgui.parity import qt_walk

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
        #from psdaq.control_gui.Unused import Unused
        class Main(QWidget):
            def __init__(self):
                self.but_a = QPushButton('&A')
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
        if __name__ == "__main__":
            w = QPushButton('T')
        """,
}

UI = 'tests/test_ui.py::'
COMPLETE = {
    "Main.but_a": {"web": "[data-parity~='Main.but_a']", "test": UI + "test_a[chromium]"},
    "Main.but_a.mnemonic": {"web": "[data-parity~='Main.but_a'][accesskey]", "test": UI + "test_a[chromium]"},
    "Main.but_b": {"web": "[data-parity~='Main.but_b']", "test": "tests/test_ui.py::TestB::test_b[chromium]"},
    "Logger.but_x": {"na": "hidden: control_gui/Logger.py:8 setVisible(self.show_buttons), show_buttons=False"},
    "Unused.but_u": {"na": "module not imported from the entry point: control_gui/Main.py:4 import commented out"},
    "Unused.__main__@1": {"na": "test harness under control_gui/Unused.py:6 if __name__ == '__main__'"},
}
CASES = (('tests.test_ui', 'test_a[chromium]', ('Main.but_a', 'Main.but_a.mnemonic')),
         ('tests.test_ui.TestB', 'test_b[chromium]', ('Main.but_b',)))


def junit(path, failing=(), untagged=()):
    cases = []
    for cls, name, rids in CASES:
        props = ''.join('<property name="parity" value="%s"/>' % r for r in rids if r not in untagged)
        body = ('<properties>%s</properties>' % props if props else '') + \
            ('<failure message="boom">assert 0</failure>' if name in failing else '')
        cases.append('<testcase classname="%s" name="%s" time="0.1">%s</testcase>' % (cls, name, body))
    with open(path, 'w') as f:
        f.write('<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="2">%s'
                '</testsuite></testsuites>' % ''.join(cases))
    return str(path)


def walk(path, src, but_x_visible=False, unused_imported=False, digest=None, unused_line_ran=False):
    """Raw observations as qt_walk.run_walk writes them, for the synthetic package."""
    w = {'version': qt_walk.WALK_VERSION, 'src_digest': digest or qt_walk.source_digest(src), 'elapsed': 0.1,
         'python': 'synthetic',
         'mods_gui': ['psdaq.control_gui.Main', 'psdaq.control_gui.Logger'] + (
             ['psdaq.control_gui.Unused'] if unused_imported else []),
         'lines': {'control_gui/Main.py': [[2, 12]], 'control_gui/Logger.py': [[2, 8]]},
         'widgets': [{'type': 'QPushButton', 'cls': 'QPushButton', 'refs': ['Main.but_a'], 'visible': True,
                      'window_visible': True, 'receivers': 1},
                     {'type': 'QPushButton', 'cls': 'QPushButton', 'refs': ['Logger.but_x'],
                      'visible': but_x_visible, 'window_visible': True, 'receivers': 1}],
         'calls': [], 'views': {}, 'clicks': {}, 'handlers': {}, 'probes': {}}
    if unused_line_ran:
        w['lines']['control_gui/Unused.py'] = [[5, 5]]
    with open(path, 'w') as f:
        json.dump(w, f)
    return str(path)


@pytest.fixture
def pkg(tmp_path):
    root = tmp_path / 'psdaq'
    for rel, text in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))
    return str(root)


def run(capsys, src, mapping, tmp_path, junit_files, extra=(), walk_file=None):
    mp = tmp_path / 'mapping.json'
    mp.write_text(json.dumps(mapping))
    wf = walk_file if walk_file is not None else walk(tmp_path / 'walk.json', src)
    argv = ['--src', src, '--mapping', str(mp), '--walk', wf] + \
        sum([['--junit', j] for j in junit_files], []) + list(extra)
    code = cpar.main(argv)
    return code, capsys.readouterr().out


def test_complete_mapping_passes(pkg, tmp_path, capsys):
    code, out = run(capsys, pkg, COMPLETE, tmp_path, [junit(tmp_path / 'j.xml')])
    assert code == 0, out
    assert '6 controls found, 3 mapped to a web element with a passing headless-browser test, ' \
           '3 marked not applicable' in out
    assert 'Logger.but_x | control_gui/Logger.py:6 | hidden | hidden: control_gui/Logger.py:8' in out
    assert '| walk agree: n=1 visible=[False]' in out
    assert 'Unused.but_u | control_gui/Unused.py:5 | unreachable:module-unreachable | module not' in out
    assert 'walk agree: line control_gui/Unused.py:5 never ran; module psdaq.control_gui.Unused not imported' in out
    assert '[main-block: 1]' in out and '[module-unreachable: 1]' in out and '[hidden: 1]' in out
    assert 'RESULT: PASS (M + K = N = 6)' in out


def test_one_mapping_removed_fails_and_names_it(pkg, tmp_path, capsys):
    m = dict(COMPLETE)
    del m['Main.but_b']
    code, out = run(capsys, pkg, m, tmp_path, [junit(tmp_path / 'j.xml')])
    assert code != 0
    assert 'Unmapped (1 rows)' in out and '  Main.but_b | control_gui/Main.py:9 | button | B' in out
    assert 'RESULT: FAIL: M + K = 5 != N = 6 (1 unmapped, 0 not passing, 0 na unconfirmed' in out
    assert 'rows: Main.but_b' in out
    m = dict(COMPLETE)
    del m['Unused.__main__@1']                   # an na row removed fails the same way
    code, out = run(capsys, pkg, m, tmp_path, [junit(tmp_path / 'j.xml')])
    assert code != 0 and '  Unused.__main__@1 | control_gui/Unused.py:7 | button |' in out


def test_failing_test_fails(pkg, tmp_path, capsys):
    code, out = run(capsys, pkg, COMPLETE, tmp_path, [junit(tmp_path / 'j.xml', failing=('test_b[chromium]',))])
    assert code != 0
    assert 'Main.but_b | tests/test_ui.py::TestB::test_b[chromium] | failed' in out


def test_passing_test_without_the_rows_parity_property_fails(pkg, tmp_path, capsys):
    code, out = run(capsys, pkg, COMPLETE, tmp_path, [junit(tmp_path / 'j.xml', untagged=('Main.but_a.mnemonic',))])
    assert code != 0
    assert 'Main.but_a.mnemonic | tests/test_ui.py::test_a[chromium] | untagged' in out
    assert '2 mapped' in out


def test_missing_test_and_no_junit_fail(pkg, tmp_path, capsys):
    m = dict(COMPLETE)
    m['Main.but_a'] = {"web": "#a", "test": UI + "test_not_there[chromium]"}
    code, out = run(capsys, pkg, m, tmp_path, [junit(tmp_path / 'j.xml')])
    assert code != 0 and 'Main.but_a | tests/test_ui.py::test_not_there[chromium] | missing' in out
    code, out = run(capsys, pkg, COMPLETE, tmp_path, [])
    assert code != 0 and 'no junit given' in out


def test_non_browser_test_is_invalid(pkg, tmp_path, capsys):
    m = dict(COMPLETE)
    m['Main.but_b'] = {"web": "#b", "test": "tests/test_unit.py::test_b"}
    code, out = run(capsys, pkg, m, tmp_path, [junit(tmp_path / 'j.xml')])
    assert code != 0 and 'Main.but_b: test tests/test_unit.py::test_b is not a headless-browser' in out


def test_stale_and_invalid_entries_fail(pkg, tmp_path, capsys):
    m = dict(COMPLETE)
    m['Main.but_gone'] = {"na": "removed"}
    code, out = run(capsys, pkg, m, tmp_path, [junit(tmp_path / 'j.xml')])
    assert code != 0 and 'Stale mapping entries' in out and 'Main.but_gone' in out
    m = dict(COMPLETE)
    m['Unused.but_u'] = {"na": "two\nlines control_gui/Main.py:4"}
    code, out = run(capsys, pkg, m, tmp_path, [junit(tmp_path / 'j.xml')])
    assert code != 0 and 'Unused.but_u: na reason must be a non-empty one-line string' in out


def test_na_reason_must_cite_the_guard_line(pkg, tmp_path, capsys):
    m = dict(COMPLETE)
    m['Unused.__main__@1'] = {"na": "test harness, never runs"}
    code, out = run(capsys, pkg, m, tmp_path, [junit(tmp_path / 'j.xml')])
    assert code != 0 and 'Unused.__main__@1: na reason must cite the guard line control_gui/Unused.py:6' in out


def test_na_on_user_facing_row_needs_flag(pkg, tmp_path, capsys):
    m = dict(COMPLETE)
    m['Main.but_b'] = {"na": "not needed on the web"}
    code, out = run(capsys, pkg, m, tmp_path, [junit(tmp_path / 'j.xml')])
    assert code != 0 and 'Main.but_b | control_gui/Main.py:9 | not needed on the web' in out
    code, out = run(capsys, pkg, m, tmp_path, [junit(tmp_path / 'j.xml')], ['--allow-unproven-na'])
    assert code == 0, out


def test_na_needs_the_walk_to_agree(pkg, tmp_path, capsys):
    j = junit(tmp_path / 'j.xml')
    # the walk saw the hidden button visible / the unreachable module imported and its line run
    for kw, rid, why in ((dict(but_x_visible=True), 'Logger.but_x', 'differ: n=1 visible=[True]'),
                         (dict(unused_imported=True), 'Unused.but_u', 'module psdaq.control_gui.Unused IMPORTED'),
                         (dict(unused_line_ran=True), 'Unused.but_u', 'line control_gui/Unused.py:5 RAN')):
        code, out = run(capsys, pkg, COMPLETE, tmp_path, [j], walk_file=walk(tmp_path / 'w2.json', pkg, **kw))
        assert code != 0, out
        assert 'na not confirmed by the walk (1 rows, not counted)' in out and rid in out and why in out, out
    # no walk at all, or a walk of other source: no na is confirmed
    code, out = run(capsys, pkg, COMPLETE, tmp_path, [j], walk_file=str(tmp_path / 'absent.json'))
    assert code != 0 and 'na not confirmed by the walk (3 rows' in out and 'no walk' in out
    code, out = run(capsys, pkg, COMPLETE, tmp_path, [j], walk_file=walk(tmp_path / 'w3.json', pkg, digest='sha256:0'))
    assert code != 0 and 'walk is of other source' in out


def test_no_rows_fails(tmp_path, capsys):
    root = tmp_path / 'empty' / 'psdaq'
    (root / 'control_gui' / 'app').mkdir(parents=True)
    for rel in ('__init__.py', 'control_gui/__init__.py', 'control_gui/app/__init__.py'):
        (root / rel).write_text('')
    (root / 'control_gui/app/control_gui.py').write_text('def control_gui():\n    pass\n')
    code, out = run(capsys, str(root), {}, tmp_path, [junit(tmp_path / 'j.xml')])
    assert code != 0 and 'RESULT: FAIL: N = 0' in out


# ---------------- the real control_gui, mapping and saved walk ----------------

REAL = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HAVE_REAL = os.path.isdir(os.path.join(REAL, 'control_gui')) and os.path.isfile(cpar.DEFAULT_MAPPING)


def real_junit(path, mapping, drop_tag=None):
    """A junit in which every mapped browser test passed and tags the rows its mapping entry names."""
    by_test = {}
    for rid, e in mapping.items():
        if 'test' in e and rid != drop_tag:
            by_test.setdefault(e['test'], []).append(rid)
    cases = []
    for t, rids in sorted(by_test.items()):
        cls, name = cpar.nodeid_key(t)
        cases.append('<testcase classname="%s" name="%s"><properties>%s</properties></testcase>' % (
            cls, name, ''.join('<property name="parity" value="%s"/>' % r for r in rids)))
    with open(path, 'w') as f:
        f.write('<?xml version="1.0"?><testsuites><testsuite>%s</testsuite></testsuites>' % ''.join(cases))
    return str(path)


@pytest.mark.skipif(not HAVE_REAL, reason='no control_gui or mapping.json next to webgui')
def test_real_mapping_is_consistent_and_the_saved_walk_agrees():
    rows, _ = cpar.enumerate_rows(REAL)
    mapping = cpar.load_mapping(cpar.DEFAULT_MAPPING)
    walk_ = qt_walk.load_walk(qt_walk.DEFAULT_WALK)
    rep = cpar.check(rows, mapping, None, walk=walk_, src_digest=qt_walk.source_digest(REAL))
    assert not rep['stale'] and not rep['invalid'] and not rep['unproven_na'] and not rep['unmapped']
    assert rep['unconfirmed_na'] == [], [(r['id'], v) for r, _, v in rep['unconfirmed_na']]
    assert rep['K'] == len([e for e in mapping.values() if 'na' in e]) and rep['K'] > 0
    for r, reason, v in rep['na']:
        assert cpar.enum_flags(r) and v[0] == 'agree', r['id']


@pytest.mark.skipif(not HAVE_REAL, reason='no control_gui or mapping.json next to webgui')
def test_real_check_passes_and_fails_when_one_mapping_is_removed(tmp_path, capsys):
    """With every mapped test passed and tagged, M + K = N; deleting one entry (a web row, then an na row) from
    a copy of the mapping makes the check exit nonzero and name that row; so does one missing parity tag."""
    mapping = cpar.load_mapping(cpar.DEFAULT_MAPPING)
    j = real_junit(tmp_path / 'all.xml', mapping)
    code = cpar.main(['--src', REAL, '--junit', j])
    out = capsys.readouterr().out
    assert code == 0, out
    assert 'RESULT: PASS (M + K = N = %d)' % len(mapping) in out
    web_row = 'CGWMainControl.box_state.keyPressEvent'
    na_row = next(k for k, e in sorted(mapping.items()) if 'na' in e)
    for gone in (web_row, na_row):
        m = dict(mapping)
        del m[gone]
        mp = tmp_path / ('mapping-without-%s.json' % gone)
        mp.write_text(json.dumps(m))          # a copy outside parity/: its mapping.d fragments are not read
        code = cpar.main(['--src', REAL, '--mapping', str(mp), '--junit', j])
        out = capsys.readouterr().out
        assert code != 0, out
        assert 'Unmapped (1 rows)' in out and ('  %s |' % gone) in out and ('rows: %s' % gone) in out
    code = cpar.main(['--src', REAL, '--junit', real_junit(tmp_path / 'untag.xml', mapping, drop_tag=web_row)])
    out = capsys.readouterr().out
    assert code != 0 and '%s | test_webgui_parity_ui.py::' % web_row in out and '| untagged' in out


def test_mainwindow_fragment_matches_rows():
    import parity_rows
    frag_path = os.path.join(os.path.dirname(cpar.DEFAULT_MAPPING), 'mapping.d', 'mainwindow.json')
    with open(frag_path) as f:
        frag = json.load(f)
    assert frag == parity_rows.fragment()
    here = os.path.dirname(os.path.abspath(__file__))
    for mod, tests in parity_rows.ROWS.items():
        src = open(os.path.join(here, mod + '.py')).read()
        for t in tests:
            assert 'def %s(' % t in src, (mod, t)
