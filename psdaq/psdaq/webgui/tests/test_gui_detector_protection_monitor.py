"""Headless-browser tests of /gui/detector_protection_monitor, the web copy of psdaq/trigger/
detector_protection_monitor.py (psdaq.webgui.dpm_api), against simdetprot (psdaq/psdaq/sim/simdetprot.py: the
protection IOC's BLOCKED, NPIX, NPIX_OT and ADU over Channel Access on this host, NPIX_OT stepping once a second,
SIM:TRIP to trip it), which the test starts with the base PV the parity walk gave the PyQt monitor; the server runs
--dpm '-b <base> -d Jungfrau'.  The bar is checked against the PVs read independently of the server (pyepics in a
subprocess, loopback CA env); a trip is made by a put of SIM:TRIP and the dialog's Dismiss is clicked."""

import json
import os
import re
import subprocess
import time

import pytest
from playwright.sync_api import expect

import webgui_harness as H

SIM = H.sim_daq()
BASE = '%s:JF16M:BLOCKER' % (SIM.ds.PVBASE if SIM else 'DAQ:SIM')
ARGS = '-b %s -d Jungfrau' % BASE
BAR = 'MonitorProgressBar._pix_over_threshold_bar'
DIALOG = 'MonitorMW.detector_protection_activated.msg_box'
PARITY_ROWS = {
    'test_bar_shows_hot_pixels_as_percent_of_the_trip_count': [BAR],
    'test_a_trip_opens_the_dialog_and_dismiss_reopens_it': [DIALOG],
}


def sel(rid):
    return '[data-parity="%s"]' % rid


def ca(op, items, timeout=30):
    """Channel Access from the test, independent of the server: 'get' [names] -> {name: value}; 'put' [[name, v]]."""
    code = ('import json,sys,os\n'
            'from psdaq.webgui.netguard import require_loopback_ca_env\n'
            'require_loopback_ca_env(os.environ)\n'
            'import epics\n'
            'op,items=json.loads(sys.argv[1])\n'
            'if op=="get":\n'
            '    out={n:epics.caget(n,timeout=5.0) for n in items}\n'
            '    print(json.dumps({n:(v.tolist() if hasattr(v,"tolist") else v) for n,v in out.items()}))\n'
            'else:\n'
            '    print(json.dumps([epics.caput(n,v,wait=True,timeout=5.0) for n,v in items]))\n'
            'sys.stdout.flush(); os._exit(0)\n')
    p = subprocess.run([H.SERVER_PYTHON, '-c', code, json.dumps([op, items])], env=H.server_env(),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError('ca %s failed: %s' % (op, p.stderr[-800:]))
    return json.loads(p.stdout.strip().splitlines()[-1])


def check_dpm_source(dev):
    """The page's data: its <base>:SIM:PID, read through the server's CA client, is the pid of the simdetprot this
    test started, which is alive, and the server reads the protection PVs."""
    def check(s, sim):
        st = {}
        t0 = time.time()
        while time.time() - t0 < 30:
            st = s.get('/api/dpm/status')
            if st.get('connected') and st.get('sim_pid') == dev.pid:
                break
            time.sleep(0.5)
        ok = st.get('connected') and st.get('sim_pid') == dev.pid and dev.alive()
        return ok, 'dpm %s: SIM:PID %s (simdetprot %s pid %s alive %s), connected %s, %s reads, CA %s' % (
            st.get('base_pv'), st.get('sim_pid'), ' '.join(dev.args), dev.pid, dev.alive(), st.get('connected'),
            st.get('reads'), st.get('ca_conf'))
    return check


@pytest.fixture(scope='module')
def dp():
    if SIM is None:
        pytest.skip('needs the simulated DAQ (WEBGUI_SIM_DAQ)')
    dev = H.DeviceSim('simdetprot', ['-P', BASE])
    s = None
    try:
        s = H.gui_server(['--dpm', ARGS], check_dpm_source(dev), backend='sim-device:simdetprot')
        assert s.backend == 'sim-device:simdetprot', (s.backend, s.backend_why)
        yield s
    finally:
        if s is not None:
            s.stop()
        dev.stop()


def open_page(page, s):
    page.goto(s.url.rstrip('/') + '/gui/detector_protection_monitor')
    page.wait_for_function('() => document.body.dataset.ready === "1" && +document.body.dataset.polls >= 2 && '
                           'document.body.dataset.connected === "1"', timeout=H.UI_TIMEOUT)


def test_bar_shows_hot_pixels_as_percent_of_the_trip_count(page, dp):
    open_page(page, dp)
    expect(page.locator('#title')).to_have_text('Jungfrau Detector Protection Monitor')
    seen, bad = set(), None
    t0 = time.time()
    while time.time() - t0 < 30 and len(seen) < 3:
        v = ca('get', [BASE + ':NPIX_OT', BASE + ':NPIX'])
        shown = page.locator(sel(BAR) + ' #pct').text_content()
        want = '%d%%' % int(v[BASE + ':NPIX_OT'] / v[BASE + ':NPIX'] * 100)
        if shown == want:
            seen.add(shown)
        else:
            bad = (shown, want, v)
        time.sleep(0.4)
    assert len(seen) >= 3, ('the bar did not follow NPIX_OT / NPIX', seen, bad)
    page.screenshot(path=str(H.SHOTS / 'detector_protection_monitor.png'), full_page=True)


def test_a_trip_opens_the_dialog_and_dismiss_reopens_it(page, dp):
    open_page(page, dp)
    d = page.locator(sel(DIALOG))
    expect(d).to_be_hidden()
    adu = ca('get', [BASE + ':ADU'])[BASE + ':ADU']
    ca('put', [[BASE + ':SIM:TRIP', 1]])                 # simdetprot writes BLOCKED with a new timestamp
    expect(d).to_be_visible(timeout=H.UI_TIMEOUT)
    expect(page.locator('#dlg-title')).to_have_text('Jungfrau Tripped')
    m = re.fullmatch(r'(\d+) pixels over threshold (\d+)', page.locator('#dlg-text').text_content())
    assert m and int(m.group(2)) == adu and 0 <= int(m.group(1)) < 100, page.locator('#dlg-text').text_content()
    expect(page.locator('#dlg-button')).to_have_text('Dismiss.')
    n = int(d.get_attribute('data-n'))
    page.locator('#dlg-button').click()
    # BlockerPVMonitor never updates its last timestamp: once reports are back on, the dialog opens again at once
    page.wait_for_function('(n) => { const d = document.querySelector(\'[data-parity="%s"]\'); '
                           'return !d.hidden && +d.dataset.n > n; }' % DIALOG, arg=n, timeout=H.UI_TIMEOUT)
    st = dp.get('/api/dpm/status')
    assert st['dialog']['n'] > n and st['reports'] is False, st
