"""Headless-browser tests of /gui/xpmpatt, the web copy of psdaq/cas/xpmpatt.py, against the simulated DAQ's simxpm
(WEBGUI_SIM_DAQ; the server runs --pvgui 'xpmpatt:<PVBASE>:XPM:<XPM>', the argument the parity walk gave the PyQt
xpmpatt): the pattern statistics PATT:GROUPS / PATT:COINC (simxpm counts the L0Accepts of each group and pair of
groups per second) and every group's L0Select / DstSelect widgets, checked against the PVs read independently of
the server and against the PyQt walk (combo items, tab titles)."""

import time

import pytest

import webgui_harness as H
import pvgui_checks as C
from psdaq.webgui.pvgui import xpmpatt as P

SIM = H.sim_daq()
PLATFORM = SIM.platform if SIM else 5
X = '%s:XPM:%d' % ((SIM.ds.PVBASE, SIM.ds.XPM) if SIM else ('DAQ:SIM', 0))
ARGV = [X]
PAGE = P.build(ARGV)
BY = C.by_type(PAGE)
PARITY_ROWS = {
    'test_tabs': BY['tab'],
    'test_stats_and_coincidences_follow_simxpm': BY['text'],
    'test_combos_write_their_pvs_with_the_pyqt_choices': BY['pvcombo'] + BY['seqsel'],
    'test_mask_bits_write_their_pvs': BY['maskbit'],
    'test_int_fields_write_their_pvs': BY['pvint'],
}


@pytest.fixture(scope='module')
def xs():
    if SIM is None:
        pytest.skip('needs the simulated DAQ (WEBGUI_SIM_DAQ)')
    s = H.gui_server(['--pvgui', 'xpmpatt:' + ' '.join(ARGV)], H.check_simxpm_source('xpmpatt'))
    try:
        assert s.backend == 'sim-daq', (s.backend, s.backend_why)
        yield s
    finally:
        s.stop()


def test_tabs(page, xs):
    C.open_page(page, xs, 'xpmpatt')
    C.check_tabs(page, PAGE, BY['tab'], C.walk_instances('xpmpatt', 'cas/xpmpatt.py'))


def test_stats_and_coincidences_follow_simxpm(page, xs):
    C.open_page(page, xs, 'xpmpatt')
    cells = BY['text']
    w0 = C.check_texts(page, PAGE, cells)
    mask = (1 << PLATFORM) | 1                          # groups 0 and <platform> together: coincidences
    try:
        H.pva('put', [[X + ':GroupL0Enable', mask], [X + ':GroupL0Enable', 0]])
        time.sleep(2.5)
        w1 = C.check_texts(page, PAGE, cells)
        g = w1[X + ':PATT:GROUPS']['value']['Sum']
        coinc = w1[X + ':PATT:COINC']['value']['Coinc']     # (0, j) is entry j: (0, platform) is entry <platform>
        assert g[0] > 0 and g[PLATFORM] > 0 and coinc[PLATFORM] > 0 and coinc[0] > 0, w1
    finally:
        H.pva('put', [[X + ':GroupL0Disable', mask], [X + ':GroupL0Disable', 0]])
    time.sleep(2.5)
    w2 = C.check_texts(page, PAGE, cells)
    assert w2[X + ':PATT:GROUPS']['value']['Sum'] == [0] * 8, w2
    C.reveal(page, PAGE, cells[0])
    page.screenshot(path=str(H.SHOTS / 'xpmpatt.png'))
    H.pva('put', [[X + ':GroupL0Reset', mask], [X + ':GroupL0Reset', 0]])


def test_combos_write_their_pvs_with_the_pyqt_choices(page, xs):
    C.open_page(page, xs, 'xpmpatt')
    C.check_combos(page, xs, 'xpmpatt', PAGE, BY['pvcombo'] + BY['seqsel'], C.walk_instances('xpmpatt', 'cas/xpmpatt.py'))


def test_mask_bits_write_their_pvs(page, xs):
    C.open_page(page, xs, 'xpmpatt')
    C.check_maskbits(page, xs, 'xpmpatt', PAGE, BY['maskbit'])


def test_int_fields_write_their_pvs(page, xs):
    C.open_page(page, xs, 'xpmpatt')
    C.check_pvints(page, xs, 'xpmpatt', PAGE, BY['pvint'])
