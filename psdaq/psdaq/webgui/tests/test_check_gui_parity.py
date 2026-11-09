"""Tests of the other-GUI parity tools (no Qt, no browser): qapps, gui_rows and check_gui_parity on the saved walks."""

import copy
import json
import os
import xml.etree.ElementTree as ET

import pytest

from psdaq.webgui.parity import check_gui_parity as C
from psdaq.webgui.parity import check_parity, gui_rows, qapps

SRC = qapps.default_src()


def test_qapps_lists_constructions_from_the_syntax_tree():
    text_only = []
    files = {e['file']: e for e in qapps.scan(SRC, text_only)}
    assert 'procmgr/procstat' in files and 'cas/groupca.py' in files     # an extensionless script is read too
    assert not [f for f in files if f.startswith('control_gui/')]
    assert 'webgui/tests/test_parity_enumerate_v1.py' not in files       # QApplication( only in a fixture string
    assert 'webgui/tests/test_parity_enumerate_v1.py' in [t['file'] for t in text_only]
    assert files['cas/collection_widget.py']['sites'][0]['main_block']
    assert files['webgui/parity/qt_walk.py']['sites'][0]['offscreen']


@pytest.mark.parametrize('name', ['procstat', 'groupca', 'pvant'])
def test_saved_walk_is_of_this_source_and_every_row_has_one_entry(name):
    specs = {s['_name']: s for s in C.load_specs().values()}
    spec = specs[name]
    with open(C.walk_path(spec)) as f:
        walk = json.load(f)
    info = gui_rows.source_sites(SRC, spec['file'])
    assert walk['src_digest'] == info['digest'], 'stale walk: run check_gui_parity --run-walks'
    rows = gui_rows.make_rows(info, walk)
    assert sorted(r['id'] for r in rows) == sorted(spec['mapping'])


def _junit(tmp_path, spec, backend='sim-daq', drop_backend_for=None):
    """A junit file in which every mapped test passed, tagged with its rows and the backend."""
    tests = {}
    for rid, e in spec['mapping'].items():
        if 'test' in e:
            tests.setdefault(e['test'], []).append(rid)
    root = ET.Element('testsuites')
    suite = ET.SubElement(root, 'testsuite')
    for nodeid, rids in tests.items():
        cls, name = check_parity.nodeid_key(nodeid)
        tc = ET.SubElement(suite, 'testcase', classname=cls, name=name)
        props = ET.SubElement(tc, 'properties')
        for rid in rids:
            ET.SubElement(props, 'property', name='parity', value=rid)
        ET.SubElement(props, 'property', name='backend',
                      value='emulator' if nodeid == drop_backend_for else backend)
    p = tmp_path / 'junit.xml'
    ET.ElementTree(root).write(str(p))
    return str(p)


def _check(spec, junit):
    e = next(x for x in qapps.scan(SRC) if x['file'] == spec['file'])
    rep, _, _, _ = C.check_gui(SRC, e, spec, check_parity.load_junit([junit]))
    return rep


def test_check_passes_and_fails_when_a_mapping_or_the_backend_goes(tmp_path):
    spec = next(s for s in C.load_specs().values() if s['_name'] == 'groupca')
    rep = _check(spec, _junit(tmp_path, spec))
    assert rep['ok'] and rep['M'] + rep['K'] == rep['N'] > 0, check_parity.render(rep)
    gone = copy.deepcopy(spec)
    del gone['mapping']['PvGroupStats.runb']
    rep = _check(gone, _junit(tmp_path, spec))
    assert not rep['ok'] and [r['id'] for r in rep['unmapped']] == ['PvGroupStats.runb']
    emu = spec['mapping']['PvGroupStats.runb']['test']
    rep = _check(spec, _junit(tmp_path, spec, drop_backend_for=emu))
    assert not rep['ok'] and 'PvGroupStats.runb' in [r['id'] for r, _, _ in rep['failing']]
    assert 'backend emulator, not sim-daq' in [st for _, _, st in rep['failing']]


def test_na_rules_are_checked():
    files = {e['file']: e for e in qapps.scan(SRC)}
    specs = C.load_specs()
    ok, why = C.check_na(files['webgui/parity/qt_walk.py'], specs['webgui/parity/qt_walk.py'])
    assert ok, why
    bad = dict(specs['webgui/parity/qt_walk.py'], na='no line cited')
    assert not C.check_na(files['webgui/parity/qt_walk.py'], bad)[0]
    prog = dict(specs['webgui/parity/qt_walk.py'], file='cas/groupca.py')     # a program can not be walk-tool N/A
    assert not C.check_na(files['cas/groupca.py'], prog)[0]
