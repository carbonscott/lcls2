"""Tests of the other-GUI parity tools (no browser): qapps, gui_rows and check_gui_parity.  No walk is kept in the
tree: the tests that need one take the walks webgui_harness.gui_walks() runs once per session (check_gui_parity's
--run-walks, PyQt5 offscreen, against the simulated DAQ of WEBGUI_SIM_DAQ), and skip without a simulated DAQ."""

import copy
import json
import os
import xml.etree.ElementTree as ET

import pytest

import webgui_harness as H
from psdaq.webgui.parity import check_gui_parity as C
from psdaq.webgui.parity import check_parity, gui_rows, qapps

SRC = qapps.default_src()


@pytest.fixture(scope='module')
def walks():
    d = H.gui_walks()
    if d is None:
        pytest.skip('needs WEBGUI_SIM_DAQ: the offscreen walks run against the simulated DAQ')
    return d


def _spec(name):
    return next(s for s in C.load_specs().values() if s['_name'] == name)


def test_qapps_lists_constructions_from_the_syntax_tree():
    text_only = []
    files = {e['file']: e for e in qapps.scan(SRC, text_only)}
    assert 'procmgr/procstat' in files and 'cas/groupca.py' in files     # an extensionless script is read too
    assert not [f for f in files if f.startswith('control_gui/')]
    assert 'webgui/tests/test_parity_enumerate_v1.py' not in files       # QApplication( only in a fixture string
    assert 'webgui/tests/test_parity_enumerate_v1.py' in [t['file'] for t in text_only]
    assert files['cas/collection_widget.py']['sites'][0]['main_block']
    assert files['webgui/parity/qt_walk.py']['sites'][0]['offscreen']


def test_no_walk_is_kept_in_the_tree():
    assert not [n for n in os.listdir(C.GUIS_DIR) if n.endswith(('.walk.json', '.probe.json'))]


@pytest.mark.parametrize('name', ['procstat', 'groupca', 'pvant', 'deadca', 'partca', 'xpmpatt', 'tprca', 'pvatable',
                                  'hsdpva', 'dtica', 'daqstat', 'datadev_monitor', 'detector_protection_monitor'])
def test_walk_is_of_this_source_and_every_row_has_one_entry(walks, name):
    spec = _spec(name)
    with open(C.walk_path(spec, walks)) as f:
        walk = json.load(f)
    info = gui_rows.source_sites(SRC, spec['file'])
    assert walk['src_digest'] == info['digest']
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


def _check(spec, junit, walks):
    e = next(x for x in qapps.scan(SRC) if x['file'] == spec['file'])
    rep, _, _, _ = C.check_gui(SRC, e, spec, check_parity.load_junit([junit]), walks)
    return rep


def test_check_passes_and_fails_when_a_mapping_or_the_backend_goes(tmp_path, walks):
    spec = _spec('groupca')
    rep = _check(spec, _junit(tmp_path, spec), walks)
    assert rep['ok'] and rep['M'] + rep['K'] == rep['N'] > 0, check_parity.render(rep)
    gone = copy.deepcopy(spec)
    del gone['mapping']['PvGroupStats.runb']
    rep = _check(gone, _junit(tmp_path, spec), walks)
    assert not rep['ok'] and [r['id'] for r in rep['unmapped']] == ['PvGroupStats.runb']
    emu = spec['mapping']['PvGroupStats.runb']['test']
    rep = _check(spec, _junit(tmp_path, spec, drop_backend_for=emu), walks)
    assert not rep['ok'] and 'PvGroupStats.runb' in [r['id'] for r, _, _ in rep['failing']]
    assert 'backend emulator, not sim-daq' in [st for _, _, st in rep['failing']]


def test_check_fails_without_a_walk_or_with_a_walk_of_other_source(tmp_path, walks):
    spec = _spec('groupca')
    junit = _junit(tmp_path, spec)
    rep = _check(spec, junit, None)                   # no --run-walks: no walk, so no pass
    assert not rep['ok'] and 'no walk groupca.walk.json' in rep['walk_note']
    d = tmp_path / 'stale'
    d.mkdir()
    with open(C.walk_path(spec, walks)) as f:
        walk = json.load(f)
    walk['src_digest'] = 'sha256:' + '0' * 64
    with open(C.walk_path(spec, str(d)), 'w') as f:
        json.dump(walk, f)
    rep = _check(spec, junit, str(d))
    assert not rep['ok'] and 'is of other source' in rep['walk_note']


def test_na_rules_are_checked():
    files = {e['file']: e for e in qapps.scan(SRC)}
    specs = C.load_specs()
    ok, why = C.check_na(files['webgui/parity/qt_walk.py'], specs['webgui/parity/qt_walk.py'])
    assert ok, why
    bad = dict(specs['webgui/parity/qt_walk.py'], na='no line cited')
    assert not C.check_na(files['webgui/parity/qt_walk.py'], bad)[0]
    prog = dict(specs['webgui/parity/qt_walk.py'], file='cas/groupca.py')     # a program can not be walk-tool N/A
    assert not C.check_na(files['cas/groupca.py'], prog)[0]
    ok, why = C.check_na(files['cas/collection_widget.py'], specs['cas/collection_widget.py'])   # no probe run
    assert not ok and 'no run-time import probe' in why, why


def test_library_demo_needs_the_import_probe(walks):
    files = {e['file']: e for e in qapps.scan(SRC)}
    spec = C.load_specs()['cas/collection_widget.py']
    ok, why = C.check_na(files['cas/collection_widget.py'], spec, walks)
    assert ok and 'constructed 0 QApplications' in why, why


@pytest.mark.parametrize('name, line, error', [('partca-sum', 'cas/partca-sum.py:34', 'TypeError'),
                                               ('xpmca', 'cas/xpmca.py:180', 'TypeError'),
                                               ('tdmpva', 'cas/tdmpva.py:8', 'ModuleNotFoundError')])
def test_no_window_rule_needs_the_walk_to_raise_at_the_cited_line(walks, name, line, error):
    files = {e['file']: e for e in qapps.scan(SRC)}
    spec = _spec(name)
    e = files[spec['file']]
    ok, why = C.check_na(e, spec, walks, SRC)
    assert ok and 'raised %s at %s' % (error, line) in why, why
    assert not C.check_na(e, spec, None, SRC)[0]                               # no walk: no proof
    bad = dict(spec, na=spec['na'].replace(line, 'somewhere'))
    ok, why = C.check_na(e, bad, walks, SRC)
    assert not ok and 'must cite the line that raised (%s)' % line in why, why
    prog = dict(_spec('groupca'), na='x ' + ' '.join('%s:%d' % (files['cas/groupca.py']['file'], s_['line'])
                                                     for s_ in files['cas/groupca.py']['sites']), rule='no-window')
    ok, why = C.check_na(files['cas/groupca.py'], prog, walks, SRC)            # groupca's walk shows its window
    assert not ok, why


def test_walk_refuses_other_hosts(walks):
    with open(C.walk_path(_spec('partca'), walks)) as f:
        walk = json.load(f)
    refused = [c for c in walk['calls'] if c['opener'].startswith('refused:')]
    assert refused and all('drp-tst-acc06' in c['args'][0] for c in refused), walk['calls']   # collection_widget
    from psdaq.webgui.parity.qt_walk import _endpoint_host
    assert [_endpoint_host(x) for x in ('tcp://127.0.0.1:5', 'tcp://drp-x:5', 'ipc:///tmp/a', 'inproc://a')] == \
        ['127.0.0.1', 'drp-x', '', '']


def test_rows_of_a_class_only_an_unreachable_def_uses_are_not_applicable():
    rows = {r['id']: r for r in gui_rows.make_rows(gui_rows.source_sites(SRC, 'cas/deadca.py'), None)}
    assert rows['PvEvtTab.PvEditCmb@1']['reach'] == 'def-unreachable'      # used by PvEditEvt, named only by LblEditEvt
    assert rows['PvInput.label']['reach'] == 'def-unreachable'             # in deadca's own PvInput class
    assert 'LblEditEvt.PvInput' not in rows      # a call to that class (a plain object; pvedit's PvInput is a widget
                                                 # builder of the same name) is not a site: the sites inside it are
    assert rows['Ui_MainWindow.PvDblArrayW']['reach'] == 'not-built'        # setupUi's, reachable (no walk given)


def test_walk_refuses_every_ssh_of_datadev_monitor(walks):
    with open(C.walk_path(_spec('datadev_monitor'), walks)) as f:
        walk = json.load(f)
    refused = [c['args'][0] for c in walk['calls'] if c['opener'] == 'refused:subprocess']
    assert len(refused) == 80 and all(a.startswith('ssh ') and ' drp-srcf-cmp' in a for a in refused), refused[:3]


def _site(line, callee, binding='w', self_attr=False):
    return {'file': 'x.py', 'line': line, 'end_line': line, 'loc': 'x.py:%d' % line, 'scope': 'S', 'fullscope': 'S',
            'binding': binding, 'self_attr': self_attr, 'callee': callee, 'kind': None, 'guards': [],
            'main_block': False, 'static': False, 'defs': [], 'classes': ['S'], 'def_called': True, 'class_used': True}


def _inst(seq, base, line, lib_line, writes=0, text=''):
    return {'seq': seq, 'cls': base, 'base': base, 'site': ['x.py', line, 'f'], 'chain': [['lib.py', lib_line, 'g']],
            'pv': None, 'text': text, 'enabled': True, 'writes': writes, 'receivers': {}, 'texts': [['shown', text]]}


def test_unwritten_label_of_a_line_the_walk_saw_write_is_a_display():
    info = {'sites': [_site(10, 'PvIntTable')], 'slots': [], 'writes': {}, 'connects': {}}
    walk = {'instances': [_inst(1, 'QLabel', 10, 5, writes=1, text='1.0000'), _inst(2, 'QLabel', 10, 5),
                          _inst(3, 'QLabel', 10, 4, text='name')]}   # the row-name label: another line, never written
    rows = gui_rows.make_rows(info, walk)
    assert [(r['id'], r['kind']) for r in rows] == [('S.w#0', 'value'), ('S.w#1', 'value')], rows


def test_a_message_box_built_many_times_is_one_row():
    info = {'sites': [_site(20, 'QMessageBox', 'msg_box')], 'slots': [], 'writes': {}, 'connects': {}}
    walk = {'instances': [_inst(k, 'QMessageBox', 20, 20, text='%d pixels over threshold 2000' % k) for k in (1, 2, 3)]}
    assert [r['id'] for r in gui_rows.make_rows(info, walk)] == ['S.msg_box']


def test_annotated_assignment_binds_its_widget():
    sites = gui_rows.source_sites(SRC, 'trigger/detector_protection_monitor.py')['sites']
    assert [(s['binding'], s['self_attr']) for s in sites if s['callee'] == 'QProgressBar'] == \
        [('_pix_over_threshold_bar', True)]


@pytest.mark.parametrize('name, plots', [('seqplot', 2), ('seq_epixhr', 1)])
def test_walk_records_pyqtgraph_plot_panels_and_their_curves(walks, name, plots):
    spec = _spec(name)
    with open(C.walk_path(spec, walks)) as f:
        walk = json.load(f)
    p = [x for x in walk['instances'] if x['base'] == 'PlotItem']
    assert len(p) == plots and all(x['curves'] and x['curves'][0]['n'] > 0 for x in p), [(x['text'], len(x['curves']))
                                                                                         for x in p]
    rows = gui_rows.make_rows(gui_rows.source_sites(SRC, spec['file']), walk)
    assert sorted(r['id'] for r in rows if r['kind'] == 'plot') == sorted(
        rid for rid in spec['mapping'] if rid.startswith('PatternWaveform.add.q0['))
