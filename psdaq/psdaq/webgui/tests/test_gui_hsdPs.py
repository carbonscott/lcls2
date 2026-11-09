"""Headless-browser tests of /gui/hsdPs, the web copy of psdaq/cas/hsdPs.py (psdaq.webgui.plots_api: hsdPs's own main()
runs its phase scan in the server against simhsd, psdaq/sim/simhsd.py, whose MONTRIG counts 70 kHz triggers split by
the ADC/TIM clock phase, and a simxpm of its own at XPM 7 for GroupL0Enable / GroupL0Disable; its plotting process is
a thread with Qt stood in), with the arguments the parity walk gave the PyQt hsdPs (phases 0, 8, 16).  The plot's
curves are compared with the curves the PyQt hsdPs's plotting process drew in this session's walk (which follows that
process), and every control of the plot's context menu (48, parity/pg_options.py) with what it did there."""

import time

import pytest

import webgui_harness as H
import plots_checks as P

PVBASE = 'DAQ:SIM'
BASE = PVBASE + ':HSD:1_PS:A'
ARGV = ['--base', BASE, '--xpm', PVBASE + ':XPM:7', '--range', '0', '24', '8']
DEV_HSD = ['-P', BASE]
DEV_XPM = ['-P', PVBASE, '-x', '7', '--frames', 'tcp://127.0.0.1:31077', '--pull', 'none']
ROWS = ['analyze.pp']
PARITY_ROWS = {'test_plot_shows_the_pyqt_curves': ROWS, 'test_wheel_zoom_drag_pan': ROWS}
PARITY_ROWS.update(P.option_tests(globals(), 'hp', 'hsdPs', ROWS))


def check_hsdps_source(dev):
    """The scan ran (done, no error) on PVs simhsd served: <base>:SIM:PID through the server is the pid of the simhsd
    this test started, which is alive."""
    def check(s, sim):
        t0 = time.time()
        sp = s.get('/api/plots/spec?gui=hsdPs')
        while not sp.get('done') and not sp.get('error') and time.time() - t0 < 120:
            time.sleep(1)
            sp = s.get('/api/plots/spec?gui=hsdPs')
        ok = sp.get('done') and not sp.get('error') and sp.get('sim_pid', {}).get(BASE) == dev.pid and dev.alive()
        return ok, 'hsdPs scan done %s error %s; %s:SIM:PID %s (simhsd %s pid %s alive %s); %d curve points' % (
            sp.get('done'), (sp.get('error') or '')[-200:], BASE, sp.get('sim_pid'), ' '.join(dev.args), dev.pid,
            dev.alive(), sum(len(c['x']) for p in sp.get('plots', []) for c in p['curves']))
    return check


@pytest.fixture(scope='module')
def hp():
    sim = H.sim_daq()
    if sim is None:
        pytest.skip('needs the simulated DAQ (WEBGUI_SIM_DAQ)')
    assert sim.ds.PVBASE == PVBASE, sim.ds.PVBASE
    hsd = H.DeviceSim('simhsd', DEV_HSD)
    xpm = H.DeviceSim('simxpm', DEV_XPM)
    s = None
    try:
        s = H.gui_server(['--hsdps', ' '.join(ARGV)], check_hsdps_source(hsd), backend='sim-device:simhsd')
        assert s.backend == 'sim-device:simhsd', (s.backend, s.backend_why)
        yield s
    finally:
        if s is not None:
            s.stop()
        xpm.stop()
        hsd.stop()


def test_plot_shows_the_pyqt_curves(page, hp):
    P.open_page(page, hp, 'hsdPs')
    page.wait_for_function('() => document.body.dataset.done === "1"', timeout=H.UI_TIMEOUT)
    P.check_curves(page, hp, 'hsdPs', 'cas/hsdPs.py', ROWS)
    page.screenshot(path=str(H.SHOTS / 'hsdPs.png'), full_page=True)


def test_wheel_zoom_drag_pan(page, hp):
    P.open_page(page, hp, 'hsdPs')
    page.wait_for_function('() => document.body.dataset.done === "1"', timeout=H.UI_TIMEOUT)
    P.check_zoom(page, ROWS)
