"""Headless-browser tests of /gui/partca, the web copy of psdaq/cas/partca.py, against the simulated DAQ
(WEBGUI_SIM_DAQ; the server runs --pvgui 'partca:<PVBASE>:XPM:<XPM>:PART:<platform>', the argument the parity walk
gave the PyQt partca): its simxpm group PVs (the counters, and the older IOC's MsgConfig / MsgEnable / ... / ResetL0
that simxpm keeps as stored stand-ins) and, for the collection panel, the simulated DAQ's control on this host.
Every widget row is driven or read and checked against the PVs read independently of the server (webgui_harness.pva,
a PV monitor for the buttons), against the PyQt walk (combo items), and against the control's own getstate reply."""

import time

import pytest
from playwright.sync_api import expect

import webgui_harness as H
import pvgui_checks as C
from psdaq.webgui.pvgui import partca as P

SIM = H.sim_daq()
PLATFORM = SIM.platform if SIM else 5
X = '%s:XPM:%d' % ((SIM.ds.PVBASE, SIM.ds.XPM) if SIM else ('DAQ:SIM', 0))
ARGV = ['%s:PART:%d' % (X, PLATFORM)]
PB = ARGV[0] + ':'
PAGE = P.build(ARGV)
BY = C.by_type(PAGE)
COLL = 'Ui_MainWindow.collectionWidget'
PARITY_ROWS = {
    'test_labels_follow_simxpm_counters': BY['text'],
    'test_checkboxes_write_their_pvs': BY['pvcheck'],
    'test_int_fields_write_their_pvs': BY['pvint'],
    'test_combos_write_their_pvs_with_the_pyqt_choices': BY['pvcombo'] + BY['seqsel'],
    'test_mask_bits_write_their_pvs': BY['maskbit'],
    'test_buttons_put_1_then_0': BY['pvbutton'],
    'test_collection_auto_connect_and_reset': [i for i in BY['button'] + BY['list'] if i.startswith(COLL)],
}


@pytest.fixture(scope='module')
def ps():
    if SIM is None:
        pytest.skip('needs the simulated DAQ (WEBGUI_SIM_DAQ)')
    s = H.gui_server(['--pvgui', 'partca:' + ' '.join(ARGV)], H.check_simxpm_source('partca'))
    try:
        assert s.backend == 'sim-daq', (s.backend, s.backend_why)
        yield s
    finally:
        s.stop()


def test_labels_follow_simxpm_counters(page, ps):
    H.pva('put', [[X + ':GroupL0Reset', 1 << PLATFORM], [X + ':GroupL0Reset', 0]])
    C.open_page(page, ps, 'partca')
    w0 = C.check_texts(page, PAGE, BY['text'])
    H.pva('put', [[X + ':GroupL0Enable', 1 << PLATFORM], [X + ':GroupL0Enable', 0]])
    time.sleep(2.5)
    w1 = C.check_texts(page, PAGE, BY['text'])          # running: rates and counters change every second
    H.pva('put', [[X + ':GroupL0Disable', 1 << PLATFORM], [X + ':GroupL0Disable', 0]])
    time.sleep(1.5)
    w2 = C.check_texts(page, PAGE, BY['text'])
    assert w1[PB + 'L0AccRate'] > 0 and w2[PB + 'NumL0Acc'] > w0[PB + 'NumL0Acc'], (w0, w1, w2)
    acc = page.locator(C.sel('Ui_MainWindow.PvLabel@6[%sNumL0Acc]' % PB)).inner_text()
    assert acc == '%s (0x%x)' % ('{:,}'.format(int(w2[PB + 'NumL0Acc'])), int(w2[PB + 'NumL0Acc'])), acc    # isInt
    page.screenshot(path=str(H.SHOTS / 'partca.png'))
    H.pva('put', [[X + ':GroupL0Reset', 1 << PLATFORM], [X + ':GroupL0Reset', 0]])


def test_checkboxes_write_their_pvs(page, ps):
    C.open_page(page, ps, 'partca')
    C.check_pvchecks(page, ps, 'partca', PAGE, BY['pvcheck'])


def test_int_fields_write_their_pvs(page, ps):
    C.open_page(page, ps, 'partca')
    C.check_pvints(page, ps, 'partca', PAGE, BY['pvint'])


def test_combos_write_their_pvs_with_the_pyqt_choices(page, ps):
    C.open_page(page, ps, 'partca')
    C.check_combos(page, ps, 'partca', PAGE, BY['pvcombo'] + BY['seqsel'], C.walk_instances('partca', 'cas/partca.py'))


def test_mask_bits_write_their_pvs(page, ps):
    C.open_page(page, ps, 'partca')
    C.check_maskbits(page, ps, 'partca', PAGE, BY['maskbit'])


def test_buttons_put_1_then_0(page, ps):
    C.open_page(page, ps, 'partca')
    C.check_pvbuttons(page, PAGE, BY['pvbutton'])


def _getstate():
    """The control's own getstate reply, read by the test over ZMQ on this host (not through the server; the DAQ
    env's python, as webgui_harness.pva)."""
    import json
    import subprocess
    code = ('import json,sys,zmq\n'
            'from psdaq.webgui.pvgui.partca import create_msg\n'
            's=zmq.Context.instance().socket(zmq.REQ); s.setsockopt(zmq.LINGER,0); s.setsockopt(zmq.RCVTIMEO,10000)\n'
            's.connect("tcp://127.0.0.1:%d" % int(sys.argv[1])); s.send_json(create_msg("getstate"))\n'
            'print(json.dumps(s.recv_json()))\n')
    p = subprocess.run([H.SERVER_PYTHON, '-c', code, str(P.rep_port(PLATFORM))], env=H.server_env(),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
    if p.returncode != 0:
        raise RuntimeError('getstate failed: %s' % p.stderr[-600:])
    return json.loads(p.stdout.strip().splitlines()[-1])


def test_collection_auto_connect_and_reset(page, ps):
    C.open_page(page, ps, 'partca')
    lists = ['%s#%d' % (COLL, i) for i in range(3)]
    try:
        page.locator(C.sel(COLL + '[Auto connect]')).click()        # rollcall, alloc, connect, then getstate
        reply = _getstate()
        want = [sorted(v['proc_info']['host'] for v in reply['body'].get(g, {}).values()) for g in P.GROUPS]
        assert want[0], reply                                       # the DRPs of the simulated DAQ answered
        for lid, w in zip(lists, want):
            t0 = time.time()
            while time.time() - t0 < 30:
                got = sorted(page.locator(C.sel(lid) + ' li').all_inner_texts())
                if got == w:
                    break
                time.sleep(0.3)
            assert got == w, (lid, got, w)
        page.screenshot(path=str(H.SHOTS / 'partca-collection.png'))
        page.locator(C.sel(COLL + '[Reset]')).click()               # reset; the lists are cleared
        for lid in lists:
            expect(page.locator(C.sel(lid) + ' li')).to_have_count(0, timeout=C.T)
        t0 = time.time()
        while time.time() - t0 < 30 and _getstate()['header']['key'] != 'reset':
            time.sleep(0.5)
        assert _getstate()['header']['key'] == 'reset'
    finally:
        SIM.restore_control(ps)
