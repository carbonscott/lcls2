"""Headless-browser tests of /gui/xpmpva, the web copy of psdaq/cas/xpmpva.py (psdaq.webgui.pvgui.xpmpva), against two
campaign XPM simulators the tests start (psdaq/sim/simxpm.py at XPM 5 and 6, loopback PVA, no frames to any DRP):
XPM 5 says 'xtpg' in its FwBuild (an ATCA XPM with CuTiming, AMC0 / AMC1, PLLs, SFPs), XPM 6 'Kcu1500' (QSFP0 /
QSFP1, UsTiming, QSFPs), the arguments and devices the parity walk gave the PyQt xpmpva, so every tab xpmpva can
build is on the page.  Each widget type is driven or read and compared with the PVs read independently of the server
(webgui_harness.pva) and with the PyQt walk (texts, combo items, tab titles)."""

import os
import time

import pytest
from playwright.sync_api import expect

import webgui_harness as H
import pvgui_checks as C
from psdaq.webgui.pvgui import text_of, xpmpva as P

PVBASE = 'DAQ:SIM'
XPMS = {5: 'simxpm xtpg (psdaq/psdaq/sim/simxpm.py): software XPM, no firmware',
        6: 'simxpm Kcu1500 (psdaq/psdaq/sim/simxpm.py): software XPM, no firmware'}
TITLES = ['%s:XPM:%d' % (PVBASE, x) for x in XPMS]
FWB = {'%s:XPM:%d:FwBuild' % (PVBASE, x): fw for x, fw in XPMS.items()}
ARGV = TITLES
PAGE = P.build(ARGV, fwbuild=FWB.get)
BY = C.by_type(PAGE)
ABSENT = set(PAGE.sim_absent)
BUTTONS = [r for r in BY['pvbutton'] if PAGE.nodes[r]['pv'] not in ABSENT]
DEAD_BUTTONS = [r for r in BY['pvbutton'] if PAGE.nodes[r]['pv'] in ABSENT]
CHECKS = [r for r in BY['pvcheck'] if not PAGE.nodes[r].get('disabled')]
CHECK_DISPLAYS = [r for r in BY['pvcheck'] if PAGE.nodes[r].get('disabled')]
INTS = [r for r in BY['pvint'] if not PAGE.nodes[r].get('disabled')]
INT_DISPLAYS = [r for r in BY['pvint'] if PAGE.nodes[r].get('disabled')]
PARITY_ROWS = {
    'test_tabs_and_the_xpm_selector': BY['tab'] + BY['localcombo'],
    'test_displays_show_what_the_pyqt_update_writes': BY['text'],
    'test_groups_and_event_codes': BY['value'],
    'test_buttons_put_their_values': BUTTONS + DEAD_BUTTONS,
    'test_check_boxes': CHECKS + CHECK_DISPLAYS,
    'test_int_fields': INTS + INT_DISPLAYS,
    'test_group_masks_put_the_mask_of_the_choice': BY['groupmask'],
    'test_pattern_l0select_widgets': BY['pvcombo'] + BY['seqsel'] + BY['maskbit'],
}


def check_source(devs):
    """The page reads the simxpms this test started: SIM:NumLinks (simxpm only) of XPM 5 answers through the server,
    every PV of the page but the ones pyxpm does not serve is connected, both simulators run and their FwBuild is
    what this test gave them."""
    def check(s, sim):
        info = {}
        t0 = time.time()
        while time.time() - t0 < 30:
            info = s.get('/api/pvgui/info?gui=xpmpva')
            if info.get('connected') == info.get('read_pvs') - info.get('absent', 0):
                break
            time.sleep(0.5)
        vals = s.get('/api/pvgui/values?gui=xpmpva')['values']
        fw = {pv: vals.get(pv) for pv in FWB}
        ok = (isinstance(info.get('sim_numlinks'), int) and all(d.alive() for d in devs) and fw == FWB and
              info.get('connected') == info.get('read_pvs') - info.get('absent', 0))
        return ok, 'pvgui xpmpva: SIM:NumLinks %s, %s/%s PVs connected (%s not served: %s); FwBuild %s; simxpm pids %s' % (
            info.get('sim_numlinks'), info.get('connected'), info.get('read_pvs'), info.get('absent'),
            info.get('unconnected', [])[:8], fw, [(d.pid, d.alive()) for d in devs])
    return check


@pytest.fixture(scope='module')
def xv():
    sim = H.sim_daq()
    if sim is None:
        pytest.skip('needs the simulated DAQ node (WEBGUI_SIM_DAQ)')
    assert sim.ds.PVBASE == PVBASE and sim.ds.XPM not in XPMS, (sim.ds.PVBASE, sim.ds.XPM)
    devs = [H.DeviceSim('simxpm', ['-P', PVBASE, '-x', str(x), '--frames', 'tcp://127.0.0.1:%d' % (31070 + x),
                                   '--pull', 'none', '--fwbuild', fw]) for x, fw in XPMS.items()]
    s = None
    try:
        s = H.gui_server(['--pvgui', 'xpmpva:' + ' '.join(ARGV)], check_source(devs), backend='sim-device:simxpm')
        assert s.backend == 'sim-device:simxpm', (s.backend, s.backend_why)
        yield s
    finally:
        if s is not None:
            s.stop()
        for d in devs:
            d.stop()


def walk():
    return C.walk_instances('xpmpva', 'cas/xpmpva.py')


def test_tabs_and_the_xpm_selector(page, xv):
    C.open_page(page, xv, 'xpmpva')
    sel = page.locator(C.sel(BY['localcombo'][0]))
    W = walk()
    assert sel.locator('option').all_inner_texts() == TITLES == W[BY['localcombo'][0]]['choices']
    for i, title in enumerate(TITLES):                  # the combo selects that XPM's tabs (QStackedWidget)
        sel.select_option(str(i))
        mine = [t for t in BY['tab'] if C.paths(PAGE)[t] and C.paths(PAGE)[t][0][2] == i]
        expect(page.locator(C.sel(mine[0]))).to_be_visible()
    C.check_tabs(page, PAGE, BY['tab'], W)


def test_displays_show_what_the_pyqt_update_writes(page, xv):
    C.open_page(page, xv, 'xpmpva')
    rows = BY['text']
    nodata = [r for r in rows if PAGE.nodes[r]['fmt'] == 'arr' and PAGE.nodes[r]['spec'] == 'd' and
              PAGE.nodes[r]['index'] >= 14]             # PathTimer labels 14..31: PATH_TIME:Array has 14 elements
    C.check_texts(page, PAGE, [r for r in rows if r not in nodata])   # = text_of(its PV read independently now)
    W = walk()                                          # and = what the PyQt display showed in the walk
    shown = page.evaluate('(ids) => ids.map(i => document.querySelector(`[data-parity="${i}"]`).textContent)', rows)
    assert len(nodata) == 2 * 8 * 18 and all(W[r]['text'] == '-' for r in nodata), len(nodata)
    assert all(t == '-' for r, t in zip(rows, shown) if r in nodata)       # never written, in either
    stable = ('linkid', 'paddr', 'cstring', 'arr')      # formats of values that stay put (not the clocks / counters)
    bad = [(r, t, W[r]['text']) for r, t in zip(rows, shown)
           if PAGE.nodes[r]['fmt'] in stable and PAGE.nodes[r]['pv'] not in FWB and W[r]['text'] != t]
    assert not bad, bad[:8]
    arr = [r for r in rows if PAGE.nodes[r]['fmt'] == 'arr']
    hidden = page.evaluate('(ids) => ids.filter(i => document.querySelector(`[data-parity="${i}"]`)'
                           '.closest("div.col[hidden]")).length', arr)
    assert hidden == 2 * 8 * 14 + 2 * 8 * 18, hidden    # DeadTime / PathTimer labels xpmpva builds, never lays out
    for x in XPMS:                                       # PATH_TIME of a group, put and shown in every element
        H.pva('put', [['%s:XPM:%d:PART:3:PATH_TIME:Array' % (PVBASE, x), [7 * k for k in range(14)]]])
    C.check_texts(page, PAGE, [r for r in rows if PAGE.nodes[r]['pv'].endswith('PART:3:PATH_TIME:Array') and
                               r not in nodata])
    page.screenshot(path=str(H.SHOTS / 'xpmpva.png'), full_page=True)


def test_groups_and_event_codes(page, xv):
    C.open_page(page, xv, 'xpmpva')
    rows = BY['value']
    W = walk()
    shown = page.evaluate('(ids) => ids.map(i => document.querySelector(`[data-parity="${i}"]`).textContent)', rows)
    assert all(W[r]['text'] == t for r, t in zip(rows, shown)), [(r, t, W[r]['text']) for r, t in zip(rows, shown)
                                                                 if W[r]['text'] != t][:8]
    x = TITLES[0]                                        # a master group and an enabled event code: XpmGroups._update
    H.pva('put', [[x + ':PART:2:Master', 1], [x + ':PART:2:L0InpRate', 929.0]])
    try:
        H.pva('put', [[x + ':SEQCODES', {'labels': ['EventCode', 'Description', 'Rate', 'Enabled'],
                                         'value': {'EventCode': list(range(256, 288)),
                                                   'Description': ['code%d' % k for k in range(32)],
                                                   'Rate': [k * 10 for k in range(32)],
                                                   'Enabled': [k == 4 for k in range(32)]}}]])
    except RuntimeError:
        pytest.fail('SEQCODES put refused')
    m = next(r for r in rows if PAGE.nodes[r]['source'] == 'groups:%s:master:2' % x)
    rate = next(r for r in rows if PAGE.nodes[r]['source'] == 'groups:%s:l0rate:2' % x)
    desc = next(r for r in rows if PAGE.nodes[r]['source'] == 'groups:%s:codes:desc:4' % x)
    cmaster = next(r for r in rows if PAGE.nodes[r]['source'] == 'groups:%s:codes:master:4' % x)
    crate = next(r for r in rows if PAGE.nodes[r]['source'] == 'groups:%s:codes:rate:4' % x)
    C.reveal(page, PAGE, m)
    expect(page.locator(C.sel(m))).to_have_text('XPM:5:', timeout=C.T)
    t0 = time.time()                                     # str(L0InpRate) (simxpm posts it once a second)
    while time.time() - t0 < 10:
        want = str(float(H.pva('get', [x + ':PART:2:L0InpRate'])[x + ':PART:2:L0InpRate']))
        if page.locator(C.sel(rate)).text_content() == want:
            break
    assert page.locator(C.sel(rate)).text_content() == want
    expect(page.locator(C.sel(desc))).to_have_text('code4')
    expect(page.locator(C.sel(cmaster))).to_have_text('XPM:5:')
    expect(page.locator(C.sel(crate))).to_have_text('40')
    H.pva('put', [[x + ':PART:2:Master', 0]])
    expect(page.locator(C.sel(m))).to_have_text('-', timeout=C.T)


def test_buttons_put_their_values(page, xv):
    C.open_page(page, xv, 'xpmpva')
    pvs = sorted({PAGE.nodes[r]['pv'] for r in BUTTONS})
    w = C.Watch(pvs)
    bad = []
    try:
        for r in BUTTONS:                                 # each click: exactly its puts, seen by an independent monitor
            n = PAGE.nodes[r]
            C.reveal(page, PAGE, r)
            expect(page.locator(C.sel(r))).to_have_text(n['label'])
            want = n.get('puts', [1, 0])                  # PvPushButtonX: 1 then 0; PvPushButtonVal: its value
            before = len(w.seen[n['pv']])
            page.locator(C.sel(r)).click()
            t0 = time.time()
            while time.time() - t0 < 10 and w.seen[n['pv']][before:] != want:
                time.sleep(0.05)
            if w.seen[n['pv']][before:] != want:
                bad.append((r, w.seen[n['pv']][before:], want))
    finally:
        w.stop()
    assert not bad, bad[:6]
    for r in DEAD_BUTTONS:                               # ModuleInit / Inhibit / TagStream: no IOC serves them
        C.reveal(page, PAGE, r)
        page.locator(C.sel(r)).click()
        expect(page.locator('#statusbar')).to_contain_text('put %s' % PAGE.nodes[r]['pv'], timeout=C.T)


def test_check_boxes(page, xv):
    C.open_page(page, xv, 'xpmpva')
    C.check_pvchecks(page, xv, 'xpmpva', PAGE, CHECKS)  # LinkLoopback: a click puts 1 / 0
    served = [r for r in CHECK_DISPLAYS if PAGE.nodes[r]['pv'] not in ABSENT]
    vals = H.pva('get', sorted({PAGE.nodes[r]['pv'] for r in served}))
    for r in CHECK_DISPLAYS:
        C.reveal(page, PAGE, r, visible=False)
        cb = page.locator(C.sel(r))
        expect(cb).to_be_disabled()
        pv = PAGE.nodes[r]['pv']
        expect(cb).to_be_checked(checked=(pv in vals and vals[pv] != 0))   # LinkIsXpm<n>: never connects, unchecked


def test_int_fields(page, xv):
    C.open_page(page, xv, 'xpmpva')
    C.check_pvints(page, xv, 'xpmpva', PAGE, INTS)
    vals = H.pva('get', sorted({PAGE.nodes[r]['pv'] for r in INT_DISPLAYS}))
    for r in INT_DISPLAYS:
        C.reveal(page, PAGE, r, visible=False)
        f = page.locator(C.sel(r))
        expect(f).to_be_disabled()
        expect(f).to_have_value(str(int(vals[PAGE.nodes[r]['pv']])))


def test_group_masks_put_the_mask_of_the_choice(page, xv):
    C.open_page(page, xv, 'xpmpva')
    W = walk()
    for r in BY['groupmask']:
        assert W[r]['choices'] == P.MASKS, (r, W[r]['choices'])
    for r, (i, mask) in zip(BY['groupmask'], [(k % 10, [0, 1, 2, 4, 8, 16, 32, 64, 128, 0xff][k % 10])
                                              for k in range(1, len(BY['groupmask']) + 1)]):
        C.reveal(page, PAGE, r)
        page.locator(C.sel(r)).select_option(str(i))
        C.wait_server(xv, 'xpmpva', PAGE.nodes[r]['pv'], mask)
        assert H.pva('get', [PAGE.nodes[r]['pv']])[PAGE.nodes[r]['pv']] == mask
    r = BY['groupmask'][0]                               # the box follows the PV: 3 groups -> All, one -> its index
    H.pva('put', [[PAGE.nodes[r]['pv'], 0b1011]])
    expect(page.locator(C.sel(r))).to_have_value('9', timeout=C.T)
    H.pva('put', [[PAGE.nodes[r]['pv'], 1 << 5]])
    expect(page.locator(C.sel(r))).to_have_value('6', timeout=C.T)
    for r in BY['groupmask']:
        H.pva('put', [[PAGE.nodes[r]['pv'], 0]])


def test_pattern_l0select_widgets(page, xv):
    C.open_page(page, xv, 'xpmpva')
    W = walk()
    C.check_combos(page, xv, 'xpmpva', PAGE, BY['pvcombo'] + BY['seqsel'], W)
    C.check_maskbits(page, xv, 'xpmpva', PAGE, BY['maskbit'])
