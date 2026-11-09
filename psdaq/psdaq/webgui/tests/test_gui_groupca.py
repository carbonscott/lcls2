"""Headless-browser tests of /gui/groupca, the web copy of psdaq/cas/groupca.py, against the simulated DAQ's
simxpm (WEBGUI_SIM_DAQ; the server runs --pvgui 'groupca:<PVBASE> <XPM> <platform>', the arguments the parity
walk gave the PyQt groupca).  Every widget row of the page is driven or read here and checked against simxpm's
PVs read independently of the server (webgui_harness.pva) and against the PyQt walk (choices, labels).

PARITY_ROWS: which parity rows (parity/guis/groupca.json) each test proves, from the page the server builds.
"""

import json
import os
import re
import time

import pytest
from playwright.sync_api import expect

import webgui_harness as H
from psdaq.webgui.pvgui import groupca as G

T = H.UI_TIMEOUT
SIM = H.sim_daq()
PLATFORM = SIM.platform if SIM else 5
ARGV = ['%s' % (SIM.ds.PVBASE if SIM else 'DAQ:SIM'), '%d' % (SIM.ds.XPM if SIM else 0), str(PLATFORM)]
PAGE = G.build(ARGV)
BY_TYPE = {}
for _id, _n in sorted(PAGE.nodes.items()):
    BY_TYPE.setdefault(_n['type'], []).append(_id)
PARITY_ROWS = {
    'test_displays_follow_simxpm_counters': BY_TYPE.get('pvdbl', []),
    'test_deadtime_labels_follow_link_masks': BY_TYPE.get('value', []),
    'test_checkboxes_write_their_pvs': BY_TYPE.get('pvcheck', []),
    'test_int_fields_write_their_pvs': BY_TYPE.get('pvint', []),
    'test_combos_write_their_pvs_with_the_pyqt_choices': BY_TYPE.get('pvcombo', []) + BY_TYPE.get('seqsel', []),
    'test_mask_bits_write_their_pvs': BY_TYPE.get('maskbit', []),
    'test_transition_buttons_insert_messages': [i for i in BY_TYPE.get('button', []) if i.startswith('PvStateMachine')]
                                               + BY_TYPE.get('edit', []),
    'test_run_and_clear': ['PvGroupStats.b[Clear]', 'PvGroupStats.runb'],
    'test_tabs': BY_TYPE.get('tab', []),
}
PB = '%s:XPM:%s:PART:%d:' % (ARGV[0], ARGV[1], PLATFORM)
X = '%s:XPM:%s:' % (ARGV[0], ARGV[1])


def sel(rid):
    return '[data-parity="%s"]' % rid


@pytest.fixture(scope='module')
def gs():
    if SIM is None:
        pytest.skip('needs the simulated DAQ (WEBGUI_SIM_DAQ)')
    s = H.gui_server(['--pvgui', 'groupca:' + ' '.join(ARGV)], H.check_simxpm_source('groupca'))
    try:
        assert s.backend == 'sim-daq', (s.backend, s.backend_why)
        yield s
    finally:
        s.stop()


def _open(page, gs, tab=None):
    page.goto(gs.url.rstrip('/') + '/gui/groupca')
    page.wait_for_function('() => document.body.dataset.ready === "1" && +document.body.dataset.polls >= 2', timeout=T)
    if tab:
        page.locator(sel('Ui_MainWindow.tw.tab[%s]' % tab)).click()


def _server_values(gs):
    return gs.get('/api/pvgui/values?gui=groupca')['values']


def _wait_server(gs, pv, want, timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = _server_values(gs).get(pv)
        if v == want:
            return v
        time.sleep(0.1)
    raise AssertionError('%s = %r, expected %r' % (pv, _server_values(gs).get(pv), want))


def _paths():
    """{node id: [(select id, index), ...]} of the stacks a widget sits in (outermost first)."""
    out = {}

    def walk(n, path):
        if n is None:
            return
        if n.get('id'):
            out[n['id']] = list(path)
        for b in n.get('bits', []):
            out[b['id']] = list(path)
        if n['type'] == 'stack':
            for i, c in enumerate(n['children']):
                walk(c, path + [(n['select'], i)])
            return
        for c in n.get('children', []):
            walk(c, path)
        for r in n.get('rows', []):
            for c in r:
                walk(c, path)
        for t in n.get('tabs', []):
            walk(t['child'], path)
    walk(PAGE.tree, [])
    return out


PATHS = _paths()


def _reveal(page, rid):
    for select_id, idx in PATHS.get(rid, []):
        s = page.locator(sel(select_id))
        if s.input_value() != str(idx):
            s.select_option(str(idx))
    expect(page.locator(sel(rid))).to_be_visible()


def _walk_rows():
    from psdaq.webgui.parity import check_gui_parity, gui_rows
    src = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(G.__file__))))
    spec = next(s for s in check_gui_parity.load_specs().values() if s['_name'] == 'groupca')
    with open(check_gui_parity.walk_path(spec, H.gui_walks())) as f:     # the PyQt groupca's walk, run this session
        walk = json.load(f)
    rows = gui_rows.make_rows(gui_rows.source_sites(src, 'cas/groupca.py'), walk)
    inst = {x['seq']: x for x in walk['instances']}
    return {r['id']: inst.get(r.get('instance')) for r in rows}


def test_tabs(page, gs):
    _open(page, gs)
    tabs = [t for t in BY_TYPE['tab']]
    assert page.locator('[role=tab][aria-selected="true"]').inner_text() == 'Events'    # tw.setCurrentIndex
    for t in tabs:
        page.locator(sel(t)).click()
        expect(page.locator(sel(t))).to_have_attribute('aria-selected', 'true')
        title = re.search(r'\[(.*)\]$', t).group(1)
        assert page.locator('[role=tab][aria-selected="true"]').inner_text() == title
    walk = _walk_rows()
    assert sorted(re.search(r'\[(.*)\]$', t).group(1) for t in tabs) == sorted(
        next(x for k, x in walk.items() if k.startswith('Ui_MainWindow.tw.tab'))['tabs'])


def test_displays_follow_simxpm_counters(page, gs):
    H.pva('put', [[X + 'GroupL0Reset', 1 << PLATFORM], [X + 'GroupL0Reset', 0]])
    _open(page, gs, 'Events')
    pvs = [PAGE.nodes[r]['pv'] for r in BY_TYPE['pvdbl']]

    def compare():
        time.sleep(2.5)                         # simxpm posts the counters once a second
        want = H.pva('get', pvs)
        for r in BY_TYPE['pvdbl']:
            pv = PAGE.nodes[r]['pv']
            expect(page.locator(sel(r))).to_have_value('%.4f' % want[pv], timeout=T)
        return want
    w0 = compare()
    assert w0[PB + 'NumL0Acc'] == 0.0
    H.pva('put', [[X + 'GroupL0Enable', 1 << PLATFORM], [X + 'GroupL0Enable', 0]])
    time.sleep(1.5)
    H.pva('put', [[X + 'GroupL0Disable', 1 << PLATFORM], [X + 'GroupL0Disable', 0]])
    w1 = compare()
    assert w1[PB + 'NumL0Acc'] > 0 and w1[PB + 'RunTime'] > 0, w1
    page.screenshot(path=str(H.SHOTS / 'groupca-events.png'))
    H.pva('put', [[X + 'GroupL0Reset', 1 << PLATFORM], [X + 'GroupL0Reset', 0]])


def test_deadtime_labels_follow_link_masks(page, gs):
    _open(page, gs, 'Events')
    name_id, val_id = BY_TYPE['value'][0], BY_TYPE['value'][1]
    expect(page.locator(sel(name_id))).to_have_text('')
    link = 3                                    # no DRP on link 3 of simxpm; 0x10080 = Fanout/Loopback (no DNS)
    H.pva('put', [[X + 'RemoteLinkId%d' % link, 0x10080], [X + 'LinkGroupMask%d' % link, 1 << PLATFORM]])
    try:
        expect(page.locator(sel(name_id))).to_have_text('Fanout/:Loopback', timeout=T)
        expect(page.locator(sel(val_id))).to_have_text('0.0', timeout=T)
    finally:
        H.pva('put', [[X + 'RemoteLinkId%d' % link, 0], [X + 'LinkGroupMask%d' % link, 0]])
    expect(page.locator(sel(name_id))).to_have_text('', timeout=T)
    expect(page.locator(sel(val_id))).to_have_text('', timeout=T)


def test_checkboxes_write_their_pvs(page, gs):
    _open(page, gs, 'Group %d' % PLATFORM)
    rows = BY_TYPE['pvcheck']
    pvs = [PAGE.nodes[r]['pv'] for r in rows]
    before = H.pva('get', pvs)
    master = [r for r in rows if r.startswith('GroupMaster')]
    assert before[PB + 'Master'] == 1            # the page's startup put (addGroup: Master = 1 without --mon)
    for r in rows:
        cb = page.locator(sel(r))
        expect(cb).to_be_checked(checked=before[PAGE.nodes[r]['pv']] != 0, timeout=T)
        cb.click()
        _wait_server(gs, PAGE.nodes[r]['pv'], 0 if before[PAGE.nodes[r]['pv']] else 1)
    after = H.pva('get', pvs)
    assert after == {pv: (0 if v else 1) for pv, v in before.items()}, (before, after)
    for r in rows:
        page.locator(sel(r)).click()
    time.sleep(1)
    assert H.pva('get', pvs) == before
    assert master


def test_int_fields_write_their_pvs(page, gs):
    _open(page, gs, 'Group %d' % PLATFORM)
    rows = BY_TYPE['pvint']
    pvs = [PAGE.nodes[r]['pv'] for r in rows]
    before = H.pva('get', pvs)
    want = {}
    for k, r in enumerate(rows):
        _reveal(page, r)
        f = page.locator(sel(r))
        expect(f).to_have_value(str(int(before[PAGE.nodes[r]['pv']])), timeout=T)
        v = 100 + k
        f.fill(str(v))
        f.press('Enter')
        want[PAGE.nodes[r]['pv']] = v
        _wait_server(gs, PAGE.nodes[r]['pv'], v)
    f = page.locator(sel(rows[0]))
    f.fill('not a number')                       # PvEditInt.setPv ignores it
    f.press('Enter')
    time.sleep(0.5)
    assert H.pva('get', pvs) == want
    H.pva('put', [[pv, v] for pv, v in before.items()])


def test_combos_write_their_pvs_with_the_pyqt_choices(page, gs):
    _open(page, gs, 'Group %d' % PLATFORM)
    walk = _walk_rows()
    rows = BY_TYPE['pvcombo'] + BY_TYPE['seqsel']
    pvs = sorted(set(PAGE.nodes[r]['pv'] for r in rows))
    before = H.pva('get', pvs)
    for r in rows:
        n = PAGE.nodes[r]
        _reveal(page, r)
        s = page.locator(sel(r))
        opts = s.locator('option').all_inner_texts()
        assert opts == walk[r]['choices'], (r, opts, walk[r]['choices'])     # the PyQt combo's items
        cur = int(s.input_value())
        new = (cur + 1) % len(opts)
        if n['pv'].endswith('L0Select') or n['pv'].endswith('_Sequence'):
            new = cur                                 # the stack selectors stay where _reveal put them
        else:
            s.select_option(str(new))
            _wait_server(gs, n['pv'], new)
        assert int(s.input_value()) == new
    for r in [x for x in BY_TYPE['seqsel']] + [x for x in BY_TYPE['pvcombo'] if x.endswith('L0Select]')]:
        s = page.locator(sel(r))
        for i in range(len(PAGE.nodes[r]['choices'])):
            s.select_option(str(i))
            _wait_server(gs, PAGE.nodes[r]['pv'], i)
        assert H.pva('get', [PAGE.nodes[r]['pv']])[PAGE.nodes[r]['pv']] == len(PAGE.nodes[r]['choices']) - 1
    H.pva('put', [[pv, v] for pv, v in before.items()])


def test_mask_bits_write_their_pvs(page, gs):
    _open(page, gs, 'Group %d' % PLATFORM)
    rows = BY_TYPE['maskbit']
    pvs = sorted(set(PAGE.nodes[r]['pv'] for r in rows))
    before = H.pva('get', pvs)
    expect_v = dict(before)
    bit = {}
    for r in rows:
        pv = PAGE.nodes[r]['pv']
        bit[r] = int(r.rsplit('#', 1)[1])
    for r in rows:
        pv = PAGE.nodes[r]['pv']
        _reveal(page, r)
        page.locator(sel(r)).click()
        expect_v[pv] ^= 1 << bit[r]
        _wait_server(gs, pv, expect_v[pv])
    assert H.pva('get', pvs) == expect_v
    H.pva('put', [[pv, v] for pv, v in before.items()])
    for r in rows:
        expect(page.locator(sel(r))).to_be_checked(checked=bool(before[PAGE.nodes[r]['pv']] & (1 << bit[r])), timeout=T)


def _simxpm_log(sim):
    p = sim.work.load()['services']['simxpm']['log']
    with open(p) as f:
        return f.read()


def test_transition_buttons_insert_messages(page, gs):
    _open(page, gs, 'Transitions')
    names = {0: 'ClearReadout', 1: 'Reset', 2: 'Configure', 3: 'Unconfigure', 4: 'BeginRun', 5: 'EndRun',
             8: 'Enable', 9: 'Disable'}                                        # simxpm TransitionId.names
    for i, (tr, trid) in enumerate(G.Transitions):
        rid = 'PvStateMachine.btn[%s]' % tr
        env = 'PvStateMachine.env#%d' % i
        expect(page.locator(sel(rid))).to_have_text(tr)
        n0 = len(re.findall(r'INFO %s rog 0x%02x' % (names[trid], 1 << PLATFORM), _simxpm_log(gs.sim)))
        page.locator(sel(env)).fill(str(20 + i))
        page.locator(sel(rid)).click()
        _wait_server(gs, PB + 'MsgPayload', 20 + i)
        got = H.pva('get', [PB + 'MsgHeader', PB + 'MsgPayload', X + 'GroupMsgInsert'])
        assert got == {PB + 'MsgHeader': trid, PB + 'MsgPayload': 20 + i, X + 'GroupMsgInsert': 0}, (tr, got)
        t0 = time.time()
        while time.time() - t0 < 10:
            n1 = len(re.findall(r'INFO %s rog 0x%02x' % (names[trid], 1 << PLATFORM), _simxpm_log(gs.sim)))
            if n1 > n0:
                break
            time.sleep(0.2)
        assert n1 == n0 + 1, (tr, n0, n1)          # simxpm generated exactly one such transition frame
    H.pva('put', [[PB + 'MsgHeader', 0], [PB + 'MsgPayload', 0]])


def test_run_and_clear(page, gs):
    _open(page, gs, 'Events')
    H.pva('put', [[X + 'GroupL0Reset', 1 << PLATFORM], [X + 'GroupL0Reset', 0]])
    run = page.locator(sel('PvGroupStats.runb'))
    acc = page.locator(sel('PvGroupStats.PvDbl[%sNumL0Acc]' % PB))
    expect(acc).to_have_value('0.0000', timeout=T)
    run.click()                                      # L0Enable = group mask, then 0
    expect(run).to_be_checked(timeout=T)             # monEnable
    time.sleep(2.5)
    run.click()                                      # L0Disable
    expect(run).not_to_be_checked(timeout=T)         # monDisable
    time.sleep(2.0)
    n = H.pva('get', [PB + 'NumL0Acc'])[PB + 'NumL0Acc']
    assert n > 0
    expect(acc).to_have_value('%.4f' % n, timeout=T)
    page.locator(sel('PvGroupStats.b[Clear]')).click()    # GroupL0Reset = mask, then 0
    expect(acc).to_have_value('0.0000', timeout=T)
    assert H.pva('get', [PB + 'NumL0Acc', PB + 'NumL0Inp']) == {PB + 'NumL0Acc': 0.0, PB + 'NumL0Inp': 0.0}
    page.screenshot(path=str(H.SHOTS / 'groupca-run-clear.png'))
