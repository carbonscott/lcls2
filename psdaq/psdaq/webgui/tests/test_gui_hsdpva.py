"""Headless-browser tests of /gui/hsdpva, the web copy of psdaq/cas/hsdpva.py, against simhsd (psdaq/psdaq/sim/simhsd.py:
the PVs of cas/hsdpvs.py for two digitizer prefixes, every monitoring field with its own start value, counters that
advance), which the test starts; the server runs --pvgui 'hsdpva:<the bases the parity walk gave the PyQt hsdpva>'.
Every display is checked against the structure PVs read independently of the server (webgui_harness.pva) and, for
the structures simhsd never changes after its start, against the text the PyQt hsdpva itself showed in this
session's offscreen walk; every editable box is driven (fill, Apply) and its PV read back."""

import time

import pytest
from playwright.sync_api import expect

import webgui_harness as H
import pvgui_checks as C
from psdaq.webgui.pvgui import text_of
from psdaq.webgui.pvgui import hsdpva as P

SIM = H.sim_daq()
BASE = SIM.ds.PVBASE if SIM else 'DAQ:SIM'
HSD = ['%s:HSD:1_1B:A' % BASE, '%s:HSD:1_1B:B' % BASE]
ARGV = list(HSD)
PAGE = P.build(ARGV)
BY = C.by_type(PAGE)
TEXTS = BY['text']
EDITS = BY['fieldedit']
APPLY = BY['button']
# In the walk of the PyQt hsdpva the first base's PvPLink update raises (cas/hsdpva.py:162, 'ntint' object has no
# attribute 'value'), so that display keeps '-'; the web copy shows PvPLink's text ('Unknown' for PLINK 0) for every base.
# MONTRIG is not among them: simhsd counts its triggers (hsdPs's phase scan) once a second, as MONTIMING
STATIC = ('MONRAWDET', 'MONFEXDET', 'MONFLOW', 'MONENV', 'MONADC', 'MONJESD', 'FWBUILD', 'PADDR', 'PLINK')
PARITY_ROWS = {
    'test_displays_show_the_structure_fields': TEXTS,
    'test_apply_puts_each_box_whole': EDITS + APPLY,
    'test_tabs': BY['tab'],
    'test_base_selector_switches_the_tab_stack': BY['localcombo'],
}


@pytest.fixture(scope='module')
def hs():
    if SIM is None:
        pytest.skip('needs the simulated DAQ (WEBGUI_SIM_DAQ)')
    dev = H.DeviceSim('simhsd', ['-P'] + HSD)
    s = None
    try:
        s = H.gui_server(['--pvgui', 'hsdpva:' + ' '.join(ARGV)], H.check_device_source('hsdpva', dev),
                         backend='sim-device:simhsd')
        assert s.backend == 'sim-device:simhsd', (s.backend, s.backend_why)
        yield s
    finally:
        if s is not None:
            s.stop()
        dev.stop()


def test_displays_show_the_structure_fields(page, hs):
    C.open_page(page, hs, 'hsdpva')
    ttl = H.pva('get', [h + ':MONJESDTTL' for h in HSD])
    for h in HSD:                                   # hsdpva reads the lane-status row titles once from MONJESDTTL
        assert ttl[h + ':MONJESDTTL']['ttl'] == PAGE.jesd_ttl, ttl
    want = C.check_texts(page, PAGE, TEXTS, timeout=40)
    a = HSD[0] + ':MONTIMING'
    time.sleep(2.5)
    w1 = C.check_texts(page, PAGE, TEXTS, timeout=40)
    assert w1[a]['trigcntsum'] > want[a]['trigcntsum'], (want[a], w1[a])       # simhsd counts triggers
    # the same text as the PyQt hsdpva showed in the walk, for every display of a structure simhsd never changes
    # that the PyQt program wrote in the walk
    walk = C.walk_instances('hsdpva', 'cas/hsdpva.py')
    static = [r for r in TEXTS if PAGE.nodes[r]['pv'].rsplit(':', 1)[1] in STATIC]
    missing = [r for r in static if walk.get(r) is None]
    assert not missing, 'rows with no instance in the PyQt walk: %s' % missing[:6]
    written = [r for r in static if walk[r].get('writes')]
    assert len(written) >= len(static) - len(HSD), (len(written), len(static))
    shown = page.evaluate('(ids) => ids.map(i => document.querySelector(`[data-parity="${i}"]`).textContent)', written)
    bad = [(r, s, walk[r]['text']) for r, s in zip(written, shown) if s != walk[r]['text']]
    assert not bad, '%d displays differ from the PyQt walk, e.g. %s' % (len(bad), bad[:6])
    for h in HSD:                                                          # PLINK 0: no link type 0xfb
        assert page.locator(C.sel('PvPLink.__display[%s:PLINK]' % h)).text_content() == 'Unknown'
    page.screenshot(path=str(H.SHOTS / 'hsdpva.png'), full_page=True)


def _boxes():
    """{Apply id: [field ids]} for every editable box (CONFIG, PGPCONFIG, RESET of each base)."""
    return {b: PAGE.nodes[b]['fields'] for b in APPLY}


def _expect(fields, texts):
    out = {}
    for f, t in zip(fields, texts):
        n = PAGE.nodes[f]
        if n.get('index', -1) >= 0:
            out.setdefault(n['field'], []).append(int(t))
        else:
            out[n['field']] = int(t) if n['conv'] == 'int' else float(t)
    return out


def test_apply_puts_each_box_whole(page, hs):
    C.open_page(page, hs, 'hsdpva')
    boxes = _boxes()
    pvs = sorted(set(PAGE.nodes[b]['pv'] for b in boxes))
    before = H.pva('get', pvs)
    try:
        for k, (b, fields) in enumerate(sorted(boxes.items())):
            pv = PAGE.nodes[b]['pv']
            C.reveal(page, PAGE, b)
            for f in fields:                                    # each field shows its PV's value
                expect(page.locator(C.sel(f))).to_have_value(text_of(PAGE.nodes[f], before[pv]), timeout=H.UI_TIMEOUT)
            texts = [str(7 + 3 * k + i) for i in range(len(fields))]
            for f, t in zip(fields, texts):
                C.reveal(page, PAGE, f)
                page.locator(C.sel(f)).fill(t)
            page.locator(C.sel(b)).click()
            want = _expect(fields, texts)
            t0 = time.time()
            got = None
            while time.time() - t0 < 10:
                got = H.pva('get', [pv])[pv]
                if all(got[k_] == v for k_, v in want.items()):
                    break
                time.sleep(0.3)
            assert all(got[k_] == v for k_, v in want.items()), (b, want, got)
            for f, t in zip(fields, texts):                      # the PV's update rewrites the fields: same text
                expect(page.locator(C.sel(f))).to_have_value(text_of(PAGE.nodes[f], got), timeout=H.UI_TIMEOUT)
            page.locator(C.sel(fields[0])).fill('not a number')  # int('not a number') raises: nothing put
            page.locator(C.sel(b)).click()
            time.sleep(1.0)
            assert H.pva('get', [pv])[pv] == got
            page.locator(C.sel(fields[0])).fill(texts[0])
    finally:
        H.pva('put', [[pv, before[pv]] for pv in pvs])


def test_tabs(page, hs):
    C.open_page(page, hs, 'hsdpva')
    C.check_tabs(page, PAGE, BY['tab'], C.walk_instances('hsdpva', 'cas/hsdpva.py'))


def test_base_selector_switches_the_tab_stack(page, hs):
    C.open_page(page, hs, 'hsdpva')
    rid = BY['localcombo'][0]
    walk = C.walk_instances('hsdpva', 'cas/hsdpva.py')
    c = page.locator(C.sel(rid))
    assert c.locator('option').all_inner_texts() == walk[rid]['choices'] == HSD, walk[rid]['choices']
    for i, h in enumerate(HSD):
        c.select_option(str(i))
        for j, h2 in enumerate(HSD):                   # only the selected base's Config box is shown
            fid = PAGE.nodes['PvScalarBox.b[%s:CONFIG]' % h2]['id']
            if i == j:
                page.locator(C.sel('Ui_MainWindow.maintab.tab[Config]#%d' % j)).click()
                expect(page.locator(C.sel(fid))).to_be_visible()
            else:
                expect(page.locator(C.sel(fid))).to_be_hidden()
