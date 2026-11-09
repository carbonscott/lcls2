"""Headless-browser test of /gui/deadca, the web copy of psdaq/cas/deadca.py, against the simulated DAQ's simxpm
(WEBGUI_SIM_DAQ; the server runs --pvgui 'deadca:<PVBASE> <platform> <XPM>', the arguments the parity walk gave the
PyQt deadca).  The 32 cells are element i of PART:<platform>:DeadFLnk in deadca's format(q[i], '4f'), checked against
the PV read independently of the server; the links' names are LinkLabel<n> read at start."""

import time

import pytest
from playwright.sync_api import expect

import webgui_harness as H
import pvgui_checks as C
from psdaq.webgui.pvgui import deadca as P

SIM = H.sim_daq()
PLATFORM = SIM.platform if SIM else 5
BASE, XPM = (SIM.ds.PVBASE, SIM.ds.XPM) if SIM else ('DAQ:SIM', 0)
ARGV = [BASE, str(PLATFORM), str(XPM)]
PAGE = P.build(ARGV)
CELLS = C.by_type(PAGE)['text']
PARITY_ROWS = {'test_cells_show_deadflnk_and_link_labels': CELLS}


@pytest.fixture(scope='module')
def ds():
    if SIM is None:
        pytest.skip('needs the simulated DAQ (WEBGUI_SIM_DAQ)')
    s = H.gui_server(['--pvgui', 'deadca:' + ' '.join(ARGV)], H.check_simxpm_source('deadca'))
    try:
        assert s.backend == 'sim-daq', (s.backend, s.backend_why)
        yield s
    finally:
        s.stop()


def test_cells_show_deadflnk_and_link_labels(page, ds):
    dead = PAGE.dead_pv
    old = H.pva('get', [dead])[dead]
    pattern = [round(0.01 * i + 0.003, 3) for i in range(32)]
    try:
        H.pva('put', [[dead, pattern]])          # simxpm posts DeadFLnk again only when its deadtime changes
        C.open_page(page, ds, 'deadca')
        want = C.check_texts(page, PAGE, CELLS)
        assert want[dead][:32] == pytest.approx(pattern, abs=1e-6), want[dead]
        for i in range(32):
            loc = page.locator(C.sel('Ui_MainWindow.PvDblArrayW#%d' % i))
            if i in PAGE.unplaced:               # built and updated, never laid out (deadca.py setupUi)
                expect(loc).to_be_hidden()
            else:
                expect(loc).to_be_visible()
        grid = PAGE.tree['children'][0]['rows']
        lbls = [c for row in grid for c in row if c is not None and c['type'] == 'label']
        names = H.pva('get', [c['pv_once'] for c in lbls if c.get('pv_once')])
        want_lbl = [names[c['pv_once']] if c.get('pv_once') else c['text'] for c in lbls]
        shown = page.locator('table.grid td > span.lbl').all_inner_texts()
        assert shown == want_lbl, (shown, want_lbl)
        assert 'fakecam_0' in names.values(), names      # simxpm names a link by the DRP on it
        page.screenshot(path=str(H.SHOTS / 'deadca.png'))
    finally:
        H.pva('put', [[dead, old]])
    time.sleep(0.5)
