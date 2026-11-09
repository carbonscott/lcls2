"""Headless-browser test of /gui/pvant, the web copy of psdaq/cas/pvant.py, against the simulated DAQ's simxpm
(WEBGUI_SIM_DAQ; the server runs --pvgui 'pvant:<the arguments the parity walk gave the PyQt pvant>')."""

import time

import pytest
from playwright.sync_api import expect

import webgui_harness as H
from psdaq.webgui.pvgui import pvant as P

T = H.UI_TIMEOUT
SIM = H.sim_daq()
PLATFORM = SIM.platform if SIM else 5
XPM = '%s:XPM:%d' % ((SIM.ds.PVBASE, SIM.ds.XPM) if SIM else ('DAQ:SIM', 0))
ARGV = ['--bases', '%s:PART:%d' % (XPM, PLATFORM), '%s:PART:0' % XPM, '--fields', 'NumL0Acc', 'NumL0Inp', 'L0AccRate']
PAGE = P.build(ARGV)
ROWS = sorted(k for k, n in PAGE.nodes.items() if n['type'] == 'pvint')
PARITY_ROWS = {'test_fields_show_the_pvs_and_edits_change_nothing': ROWS}


@pytest.fixture(scope='module')
def ps():
    if SIM is None:
        pytest.skip('needs the simulated DAQ (WEBGUI_SIM_DAQ)')
    s = H.gui_server(['--pvgui', 'pvant:' + ' '.join(ARGV)], H.check_simxpm_source('pvant'))
    try:
        assert s.backend == 'sim-daq', (s.backend, s.backend_why)
        yield s
    finally:
        s.stop()


def test_fields_show_the_pvs_and_edits_change_nothing(page, ps):
    mask = (1 << PLATFORM) | 1
    H.pva('put', [[XPM + ':GroupL0Reset', mask], [XPM + ':GroupL0Reset', 0]])
    page.goto(ps.url.rstrip('/') + '/gui/pvant')
    page.wait_for_function('() => document.body.dataset.ready === "1" && +document.body.dataset.polls >= 2', timeout=T)
    pvs = [PAGE.nodes[r]['pv'] for r in ROWS]
    head = page.locator('table.grid tr').first.locator('td').all_inner_texts()
    assert head[1:] == [':%d' % PLATFORM, ':0'] or head[1:] == ['%d' % PLATFORM, '0'], head   # common prefix removed

    def compare():
        time.sleep(2.5)
        want = H.pva('get', pvs)
        for r in ROWS:
            expect(page.locator('[data-parity="%s"]' % r)).to_have_value(str(int(want[PAGE.nodes[r]['pv']])), timeout=T)
        return want
    w0 = compare()
    H.pva('put', [[XPM + ':GroupL0Enable', 1 << PLATFORM], [XPM + ':GroupL0Enable', 0]])
    time.sleep(1.5)
    H.pva('put', [[XPM + ':GroupL0Disable', 1 << PLATFORM], [XPM + ':GroupL0Disable', 0]])
    w1 = compare()
    acc = '%s:PART:%d:NumL0Acc' % (XPM, PLATFORM)
    assert w1[acc] > w0[acc], (w0, w1)
    f = page.locator('[data-parity="PvScalarTable.PvInt[%s]"]' % acc)
    f.fill('12345')
    f.press('Enter')                              # PvInt.setPv: nothing is written
    time.sleep(1.0)
    assert H.pva('get', [acc])[acc] == w1[acc]
    page.screenshot(path=str(H.SHOTS / 'pvant.png'))
    H.pva('put', [[XPM + ':GroupL0Reset', mask], [XPM + ':GroupL0Reset', 0]])
