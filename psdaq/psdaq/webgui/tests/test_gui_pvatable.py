"""Headless-browser test of /gui/pvatable, the web copy of psdaq/cas/pvatable.py, against simhsd
(psdaq/psdaq/sim/simhsd.py: the PVs of cas/hsdpvs.py for two digitizer prefixes, with counters that advance), which
the test starts; the server runs --pvgui 'pvatable:<the arguments the parity walk gave the PyQt pvatable>'.  Each
cell is checked against the structure PV read independently of the server (webgui_harness.pva)."""

import pytest

import webgui_harness as H
import pvgui_checks as C
from psdaq.webgui.pvgui import pvatable as P

SIM = H.sim_daq()
BASE = SIM.ds.PVBASE if SIM else 'DAQ:SIM'
HSD = ['%s:HSD:1_DA:A' % BASE, '%s:HSD:1_DA:B' % BASE]
ARGV = ['--bases'] + HSD + ['--fields', 'MONTIMING.trigcntsum', 'MONTIMING.timframecnt', 'MONPGP.txcntsum',
                            'MONPGP.rxcnt[2]', 'MONRAWBUF.freesz']
PAGE = P.build(ARGV)
CELLS = C.by_type(PAGE)['text']
PARITY_ROWS = {'test_cells_show_the_structure_fields': CELLS}


@pytest.fixture(scope='module')
def ps():
    if SIM is None:
        pytest.skip('needs the simulated DAQ (WEBGUI_SIM_DAQ)')
    dev = H.DeviceSim('simhsd', ['-P'] + HSD)
    s = None
    try:
        s = H.gui_server(['--pvgui', 'pvatable:' + ' '.join(ARGV)], H.check_device_source('pvatable', dev),
                         backend='sim-device:simhsd')
        assert s.backend == 'sim-device:simhsd', (s.backend, s.backend_why)
        yield s
    finally:
        if s is not None:
            s.stop()
        dev.stop()


def test_cells_show_the_structure_fields(page, ps):
    C.open_page(page, ps, 'pvatable')
    head = page.locator('table.grid tr').first.locator('td').all_inner_texts()
    assert head[1:] == ['A', 'B'], head                                   # the common prefix removed
    w0 = C.check_texts(page, PAGE, CELLS)
    import time
    time.sleep(2.5)
    w1 = C.check_texts(page, PAGE, CELLS)
    a = HSD[0] + ':MONTIMING'
    assert w1[a]['trigcntsum'] > w0[a]['trigcntsum'], (w0[a], w1[a])       # simhsd counts triggers
    arr = page.locator(C.sel('PvScalarTable.PvField#4')).text_content()    # MONPGP.txcntsum of A: 4 lanes
    assert len(arr.split('\n')) == 4, arr
    page.screenshot(path=str(H.SHOTS / 'pvatable.png'))
