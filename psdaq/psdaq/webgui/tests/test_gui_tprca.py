"""Headless-browser tests of /gui/tprca, the web copy of psdaq/cas/tprca.py, against simtpr (psdaq/psdaq/sim/simtpr.py,
the PVs of cas/tprcas.py on this host), which each test session starts with prefix <PVBASE>:TPR, the argument the
parity walk gave the PyQt tprca.  Every widget row is driven or read and checked against the PVs read independently
of the server (webgui_harness.pva, a PV monitor for the writes) and against the PyQt walk (combo items, tab titles).
The 6 fields of CH12 / CH13 Delay, Width and Polarity read PVs tprcas does not serve: they stay at their initial
"0" / first item, as in the PyQt tprca."""

import time

import pytest
from playwright.sync_api import expect

import webgui_harness as H
import pvgui_checks as C
from psdaq.webgui.pvgui import text_of
from psdaq.webgui.pvgui import tprca as P

SIM = H.sim_daq()
PREFIX = '%s:TPR' % (SIM.ds.PVBASE if SIM else 'DAQ:SIM')
ARGV = [PREFIX]
PAGE = P.build(ARGV)
BY = C.by_type(PAGE)
ABSENT = [i for i in BY['pvcombo'] + BY['pvedit'] if PAGE.nodes[i]['pv'] in PAGE.sim_absent]
EDITS = [i for i in BY['pvedit'] if not PAGE.nodes[i]['disabled'] and i not in ABSENT]
SHOWS = [i for i in BY['pvedit'] if PAGE.nodes[i]['disabled']] + \
        [i for i in BY['pvcombo'] if PAGE.nodes[i]['disabled']]
COMBOS = [i for i in BY['pvcombo'] if not PAGE.nodes[i]['disabled'] and i not in ABSENT]
PARITY_ROWS = {
    'test_tabs': BY['tab'],
    'test_displays_follow_simtpr': SHOWS,
    'test_edit_fields_put_int_or_float': EDITS,
    'test_combos_write_their_pvs_with_the_pyqt_choices': COMBOS,
    'test_destination_bits_put_the_mask_of_all_boxes': BY['maskbit'],
    'test_fields_of_pvs_tprcas_does_not_serve_stay_initial': ABSENT,
}


@pytest.fixture(scope='module')
def ts():
    if SIM is None:
        pytest.skip('needs the simulated DAQ (WEBGUI_SIM_DAQ)')
    dev = H.DeviceSim('simtpr', ['-P', PREFIX])
    s = None
    try:
        s = H.gui_server(['--pvgui', 'tprca:' + ' '.join(ARGV)], H.check_device_source('tprca', dev),
                         backend='sim-device:simtpr')
        assert s.backend == 'sim-device:simtpr', (s.backend, s.backend_why)
        yield s
    finally:
        if s is not None:
            s.stop()
        dev.stop()


def _shown(page, rid):
    loc = page.locator(C.sel(rid))
    return loc.input_value()


def test_tabs(page, ts):
    C.open_page(page, ts, 'tprca')
    C.check_tabs(page, PAGE, BY['tab'], C.walk_instances('tprca', 'cas/tprca.py'))


def test_displays_follow_simtpr(page, ts):
    C.open_page(page, ts, 'tprca')
    pvs = [PAGE.nodes[r]['pv'] for r in SHOWS]
    t0, bad = time.time(), None
    while time.time() - t0 < 20:
        want = H.pva('get', pvs)
        bad = []
        for r in SHOWS:
            n = PAGE.nodes[r]
            exp = str(want[n['pv']]) if n['type'] == 'pvcombo' else text_of(n, want[n['pv']])
            got = _shown(page, r)
            if got != exp:
                bad.append((r, got, exp))
        if not bad:
            break
        time.sleep(0.3)
    assert not bad, bad
    assert want[PREFIX + ':LINKSTATE'] == 1 and want[PREFIX + ':FRAMERATE'] > 9e5, want   # simtpr: link up
    page.screenshot(path=str(H.SHOTS / 'tprca-input.png'))


def test_edit_fields_put_int_or_float(page, ts):
    C.open_page(page, ts, 'tprca')
    pvs = [PAGE.nodes[r]['pv'] for r in EDITS]
    before = H.pva('get', pvs)
    w = C.Watch(pvs)
    sent = {}
    try:
        for k, r in enumerate(EDITS):
            n = PAGE.nodes[r]
            C.reveal(page, PAGE, r)
            f = page.locator(C.sel(r))
            if not n['pv'].endswith((':EVTCNT', ':RATE')):        # simtpr posts these itself every second
                expect(f).to_have_value(text_of(n, before[n['pv']]), timeout=C.T)
            v = (100 + k) if n['conv'] == 'int' else round(1.5e-6 + k * 1e-7, 9)
            f.fill(str(v))
            f.press('Enter')
            sent[n['pv']] = v
            t0 = time.time()
            while time.time() - t0 < 10 and v not in w.seen[n['pv']]:
                time.sleep(0.1)
        f = page.locator(C.sel(EDITS[0]))
        C.reveal(page, PAGE, EDITS[0])
        f.fill('not a number')                                     # int('not a number') raises: nothing is put
        f.press('Enter')
        time.sleep(1.0)
    finally:
        seen = w.stop()
        H.pva('put', [[pv, v] for pv, v in before.items() if not pv.endswith((':EVTCNT', ':RATE'))])
    for pv, v in sent.items():
        assert v in seen[pv], (pv, v, seen[pv])
    assert 'not a number' not in [str(x) for x in seen[PAGE.nodes[EDITS[0]]['pv']]]


def test_combos_write_their_pvs_with_the_pyqt_choices(page, ts):
    C.open_page(page, ts, 'tprca')
    C.check_combos(page, ts, 'tprca', PAGE, COMBOS, C.walk_instances('tprca', 'cas/tprca.py'))


def test_destination_bits_put_the_mask_of_all_boxes(page, ts):
    C.open_page(page, ts, 'tprca')
    rows = BY['maskbit']
    pvs = sorted(set(PAGE.nodes[r]['pv'] for r in rows))
    before = H.pva('get', pvs)
    H.pva('put', [[pv, 0x5555] for pv in pvs])                    # tprca's boxes never follow the PV
    w = C.Watch(pvs)
    want = {pv: [] for pv in pvs}
    acc = {pv: 0 for pv in pvs}
    try:
        for r in rows:
            pv = PAGE.nodes[r]['pv']
            bit = int(r.rsplit('#', 1)[1])
            C.reveal(page, PAGE, r)
            expect(page.locator(C.sel(r))).not_to_be_checked()
            page.locator(C.sel(r)).click()
            acc[pv] |= 1 << bit
            want[pv].append(acc[pv])                               # the mask of every box checked so far
        time.sleep(1.0)
    finally:
        seen = w.stop()
        H.pva('put', [[pv, v] for pv, v in before.items()])
    for pv in pvs:
        assert [v for v in seen[pv] if v != 0x5555] == want[pv], (pv, seen[pv], want[pv])


def test_fields_of_pvs_tprcas_does_not_serve_stay_initial(page, ts):
    C.open_page(page, ts, 'tprca')
    for r in ABSENT:
        C.reveal(page, PAGE, r)
        assert _shown(page, r) == '0', (r, _shown(page, r))        # PvTextDisplay("0"); combo index 0
    with pytest.raises(RuntimeError):
        H.pva('get', [PAGE.nodes[ABSENT[0]]['pv']], timeout=20)
    info = ts.get('/api/pvgui/info?gui=tprca')
    assert sorted(info['unconnected']) == sorted(PAGE.sim_absent), info
