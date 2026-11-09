"""Headless-browser tests of /gui/datadev_monitor, the web copy of psdaq/cas/datadev_monitor.py
(psdaq.webgui.datadev_api), against simdatadev (psdaq/psdaq/sim/simdatadev.py: datadev_monitor's 80 node names as
simulated nodes with datadev files that differ by a fixed pattern, some unreachable), which the test starts; the
server runs --datadev-sim <its root> and never starts ssh.  Every cell is checked against simdatadev's own record of
each node (its root's simdatadev.json, read by the test, not through the server)."""

import json
import os
import tempfile
import time

import pytest
from playwright.sync_api import expect

import webgui_harness as H

SIM = H.sim_daq()
B = 'MainWindow._build_ui.'
HEADERS = ['Node', 'Groups', '/proc/datadev_*', 'datadev.ko', 'datadev.service', 'cfgRxCount', 'ExecStart']
COLS = [B + '_table.col[%s]' % h for h in HEADERS]
PARITY_ROWS = {
    'test_refresh_all_checks_every_simulated_node': [B + '_refresh_btn', B + '_progress', B + '_ts_label'] + COLS,
    'test_header_click_sorts_by_the_column': COLS,
}


def sel(rid):
    return '[data-parity="%s"]' % rid


def check_datadev_source(dev, root):
    def check(s, sim):
        st = s.get('/api/datadev/status')
        ok = st.get('sim', {}).get('pid') == dev.pid and dev.alive() and \
            os.path.realpath(st['sim']['root']) == os.path.realpath(root)
        return ok, 'datadev sim root %s pid %s (simdatadev %s pid %s alive %s)' % (
            st.get('sim', {}).get('root'), st.get('sim', {}).get('pid'), root, dev.pid, dev.alive())
    return check


@pytest.fixture(scope='module')
def dd():
    if SIM is None:
        pytest.skip('needs the simulated DAQ (WEBGUI_SIM_DAQ)')
    root = tempfile.mkdtemp(prefix='simdatadev-')
    dev = H.DeviceSim('simdatadev', ['--root', root])
    s = None
    try:
        s = H.gui_server(['--datadev-sim', root], check_datadev_source(dev, root), backend='sim-device:simdatadev')
        assert s.backend == 'sim-device:simdatadev', (s.backend, s.backend_why)
        s.sim_root = root
        yield s
    finally:
        if s is not None:
            s.stop()
        dev.stop()


def open_page(page, s):
    page.goto(s.url.rstrip('/') + '/gui/datadev_monitor')
    page.wait_for_function('() => document.body.dataset.ready === "1" && +document.body.dataset.polls >= 2',
                           timeout=H.UI_TIMEOUT)


def expected_row(h, t):
    """MainWindow._update_row for simdatadev's record t of node h: (texts of columns 2-6, colours)."""
    if not t['reachable']:
        return ['—', 'unreachable', '—', '—', None], ['GRAY'] * 5          # every column grey, ssh's message in ExecStart
    proc = ', '.join(t['proc']) if t['proc'] else 'None'
    ko, svc = 'YES' if t['ko'] else 'NO', 'YES' if t['svc'] else 'NO'
    cfg = ('YES' if t['cfg'] else 'NO') if t['svc'] else 'N/A'
    ex = t['exec'] if t['svc'] else 'N/A'
    return [proc, ko, svc, cfg, ex], ['RED' if proc == 'None' else 'GREEN', 'GREEN' if t['ko'] else 'RED',
                                      'GREEN' if t['svc'] else 'RED',
                                      {'YES': 'GREEN', 'N/A': 'AMBER'}.get(cfg, 'RED'), None]


def table(page):
    return page.evaluate('() => [...document.querySelectorAll("#body tr")].map(tr => [...tr.children].map('
                         'td => [td.textContent, td.classList.contains("GREEN") ? "GREEN" : td.classList.contains("RED")'
                         ' ? "RED" : td.classList.contains("GRAY") ? "GRAY" : td.classList.contains("AMBER") ? "AMBER" '
                         ': null]))')


def test_refresh_all_checks_every_simulated_node(page, dd):
    with open(os.path.join(dd.sim_root, 'simdatadev.json')) as f:
        truth = json.load(f)['truth']
    open_page(page, dd)
    for k, h in enumerate(HEADERS):
        expect(page.locator(sel(COLS[k]))).to_have_text(h)
    expect(page.locator(sel(B + '_ts_label'))).to_have_text('Not yet refreshed')
    rows = table(page)
    assert [r[0][0] for r in rows] == sorted(truth) and all(c[0] == '—' for r in rows for c in r[2:]), rows[:2]
    page.evaluate('() => { window.SEEN = []; new MutationObserver(() => { const p = document.getElementById("progress");'
                  ' if (!p.hidden) window.SEEN.push(p.value); }).observe(document.getElementById("progress"), '
                  '{ attributes: true }); }')
    page.locator(sel(B + '_refresh_btn')).click()
    expect(page.locator(sel(B + '_refresh_btn'))).to_be_disabled()
    expect(page.locator(sel(B + '_ts_label'))).to_have_text(__import__('re').compile(r'^Last refresh: \d{4}-'),
                                                            timeout=H.UI_TIMEOUT)
    expect(page.locator(sel(B + '_refresh_btn'))).to_be_enabled()
    expect(page.locator(sel(B + '_progress'))).to_be_hidden()
    seen = page.evaluate('() => window.SEEN')
    assert seen and max(seen) <= 100, seen                       # the bar showed while the nodes were checked
    bad = []
    for r in table(page):
        h = r[0][0]
        want, colours = expected_row(h, truth[h])
        got = [c[0] for c in r[2:]]
        if want[4] is None:                                      # unreachable: ssh's message in ExecStart
            want[4] = got[4] if 'timed out' in got[4] else '<ssh timeout message>'
        if got != want or [c[1] for c in r[2:]] != colours:
            bad.append((h, got, want, [c[1] for c in r[2:]], colours))
    assert not bad, '%d rows differ from the simulated nodes, e.g. %s' % (len(bad), bad[:3])
    n_reach = sum(t['reachable'] for t in truth.values())
    st = page.locator('#statusbar').text_content()
    assert ('%d/%d reachable' % (n_reach, len(truth))) in st and \
        ('%d with service' % sum(t['reachable'] and t['svc'] for t in truth.values())) in st and \
        ('%d with cfgRxCount' % sum(t['reachable'] and t['svc'] and t['cfg'] for t in truth.values())) in st, st
    assert dd.get('/api/datadev/status')['targets_run'] >= len(truth)
    page.screenshot(path=str(H.SHOTS / 'datadev_monitor.png'), full_page=True)


def test_header_click_sorts_by_the_column(page, dd):
    open_page(page, dd)
    for k, rid in enumerate(COLS):
        for desc in (False, True):
            page.locator(sel(rid)).click()
            col = [r[k][0] for r in table(page)]
            assert col == sorted(col, reverse=desc), (rid, desc, col[:5])
