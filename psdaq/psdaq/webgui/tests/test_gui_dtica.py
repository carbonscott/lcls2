"""Headless-browser tests of /gui/dtica, the web copy of psdaq/cas/dtica.py, against simdti (psdaq/psdaq/sim/simdti.py:
the PVs of cas/dticas.py for slots 3-7, counting), which the test starts with the prefix the parity walk gave the
PyQt dtica; the server runs --pvgui 'dtica:<prefix>'.  Every display is checked against the PVs read independently of
the server (webgui_harness.pva) and in the PyQt walk's format; every allocation box is clicked and the PV it puts
read back; the PVs are put from outside and the boxes followed; CountClear's 1, 0 is seen by a PV monitor."""

import re
import time

import pytest
from playwright.sync_api import expect

import webgui_harness as H
import pvgui_checks as C
from psdaq.webgui.pvgui import dtica as P

SIM = H.sim_daq()
PREFIX = '%s:DTI' % (SIM.ds.PVBASE if SIM else 'DAQ:SIM')
ARGV = [PREFIX]
PAGE = P.build(ARGV)
BY = C.by_type(PAGE)
TEXTS = BY['text']
SLOTS = ['%s:%d:' % (PREFIX, s) for s in range(3, 8)]
PARITY_ROWS = {
    'test_displays_follow_simdti': TEXTS + BY['maskdisp'],
    'test_partition_boxes_put_their_index_minus_one': BY['exclbox'],
    'test_downstream_link_boxes_put_the_forward_masks': BY['fwdcell'],
    'test_count_clear_buttons': BY['pvbutton'],
    'test_tabs': BY['tab'],
}


@pytest.fixture(scope='module')
def ds():
    if SIM is None:
        pytest.skip('needs the simulated DAQ (WEBGUI_SIM_DAQ)')
    dev = H.DeviceSim('simdti', ['-P', PREFIX])
    s = None
    try:
        s = H.gui_server(['--pvgui', 'dtica:' + PREFIX], H.check_device_source('dtica', dev),
                         backend='sim-device:simdti')
        assert s.backend == 'sim-device:simdti', (s.backend, s.backend_why)
        yield s
    finally:
        if s is not None:
            s.stop()
        dev.stop()


def test_displays_follow_simdti(page, ds):
    C.open_page(page, ds, 'dtica')
    w0 = C.check_texts(page, PAGE, TEXTS, timeout=40)
    pvs = sorted(set(PAGE.nodes[r]['pv'] for r in BY['maskdisp']))
    want = H.pva('get', pvs)
    for r in BY['maskdisp']:                                       # PvMask: bit n of the link-up mask
        n = PAGE.nodes[r]
        expect(page.locator(C.sel(r))).to_be_checked(checked=bool(want[n['pv']]['value'] & (1 << n['bit'])
                                                              if isinstance(want[n['pv']], dict) else
                                                              want[n['pv']] & (1 << n['bit'])), timeout=H.UI_TIMEOUT)
        expect(page.locator(C.sel(r))).to_be_disabled()
    time.sleep(2.5)
    w1 = C.check_texts(page, PAGE, TEXTS, timeout=40)
    pv = SLOTS[0] + 'UsWrFifoD'
    assert w1[pv] != w0[pv], (w0[pv], w1[pv])                     # simdti counts
    walk = C.walk_instances('dtica', 'cas/dtica.py')               # the PyQt cells' format: '{0:.4f}', PvLabel's
    for r in TEXTS:
        t = walk[r]['text']
        shown = page.locator(C.sel(r)).text_content()
        if PAGE.nodes[r]['fmt'] == 'introw':
            assert re.fullmatch(r'-?\d+\.\d{4}', shown) and (t == '' or re.fullmatch(r'-?\d+\.\d{4}', t)), (r, shown, t)
        elif walk[r].get('writes'):
            pat = re.sub(r'\d', '9', t)
            assert re.sub(r'\d', '9', shown) == pat or PAGE.nodes[r]['pv'].endswith(('TimFrRate', 'MonClkRate')), \
                (r, shown, t)
    page.screenshot(path=str(H.SHOTS / 'dtica.png'), full_page=True)


def _val(v):
    return v['value'] if isinstance(v, dict) else v


def test_partition_boxes_put_their_index_minus_one(page, ds):
    C.open_page(page, ds, 'dtica')
    groups = {}
    for r in sorted(BY['exclbox'], key=lambda r: PAGE.nodes[r]['index']):     # boxes in index order: None, 0 .. 7
        groups.setdefault(PAGE.nodes[r]['pv'], []).append(r)
    before = H.pva('get', sorted(groups))
    try:
        for pv, boxes in sorted(groups.items()):
            for r in boxes[1:] + boxes[:1]:                          # box 0 last: it puts -1 (the PV is unsigned)
                C.reveal(page, PAGE, r)
                page.locator(C.sel(r)).click()
                want = PAGE.nodes[r]['index'] - 1
                C.wait_server(ds, 'dtica', pv, want if want >= 0 else want + (1 << 32))
                expect(page.locator(C.sel(r))).to_be_checked()
                for o in boxes:
                    if o != r:
                        expect(page.locator(C.sel(o))).not_to_be_checked()
        pv, boxes = sorted(groups.items())[0]                        # a put from outside checks box value+1
        for v in (4, 0):
            H.pva('put', [[pv, v]])
            C.reveal(page, PAGE, boxes[v + 1])
            expect(page.locator(C.sel(boxes[v + 1]))).to_be_checked(timeout=H.UI_TIMEOUT)
        got = H.pva('get', sorted(groups))
        assert all(_val(got[p]) == 4294967295 for p in sorted(groups)[1:]), got
    finally:
        H.pva('put', [[pv, _val(v)] for pv, v in before.items()])


def test_downstream_link_boxes_put_the_forward_masks(page, ds):
    C.open_page(page, ds, 'dtica')
    for slot in SLOTS:
        pvs = [slot + 'UsLinkFwdMask%d' % i for i in range(7)]
        before = H.pva('get', pvs)
        cells = {(PAGE.nodes[r]['i'], PAGE.nodes[r]['j']): r for r in BY['fwdcell'] if PAGE.nodes[r]['slot'] == slot}
        try:
            cols = [-1] * 7
            for (i, j), r in sorted(cells.items()):              # every box once: its column's row becomes i
                C.reveal(page, PAGE, r)
                page.locator(C.sel(r)).click()
                cols[j] = i
                want = [sum(1 << jj for jj, ii in enumerate(cols) if ii == k) for k in range(7)]
                t0 = time.time()
                while time.time() - t0 < 10:
                    vals = H.pva('get', pvs) if (i, j) == (6, 6) else ds.get('/api/pvgui/values?gui=dtica')['values']
                    if [_val(vals[p]) for p in pvs] == want:
                        break
                    time.sleep(0.1)
                assert [_val(vals[p]) for p in pvs] == want, (r, want, vals)
            H.pva('put', [[pvs[2], 0x7f]] + [[p, 0] for k, p in enumerate(pvs) if k != 2])   # from outside: row 2
            for j in range(7):
                expect(page.locator(C.sel(cells[(2, j)]))).to_be_checked(timeout=H.UI_TIMEOUT)
                for i in range(7):
                    if i != 2:
                        expect(page.locator(C.sel(cells[(i, j)]))).not_to_be_checked()
        finally:
            H.pva('put', [[p, _val(before[p])] for p in pvs])


def test_count_clear_buttons(page, ds):
    C.open_page(page, ds, 'dtica')
    C.check_pvbuttons(page, PAGE, BY['pvbutton'])


def test_tabs(page, ds):
    C.open_page(page, ds, 'dtica')
    C.check_tabs(page, PAGE, BY['tab'], C.walk_instances('dtica', 'cas/dtica.py'))
