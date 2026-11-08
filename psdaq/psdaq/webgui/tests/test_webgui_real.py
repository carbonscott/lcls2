"""The full-cycle UI test of test_webgui_ui.py, against a REAL DAQ instead of --emulate.

Same clicks and checks as test_webgui_ui.test_full_cycle: reset -> Select (rollcall) ->
Apply (selectPlatform + allocated) -> record ON -> CONFIGURED -> RUNNING -> CONFIGURED ->
record OFF -> RESET. The values the emulator fixes (6 processes, run 1, the file name)
come from the real control instead, and the events counter must be the timing source's
(--events-source pva) and must end final (data-final="1") and latched through RESET.

Skipped unless WEBGUI_REAL_URL points at a running web GUI with the real backend, e.g. the one
`daq_sim up --webgui` starts:
    WEBGUI_REAL_URL=http://127.0.0.1:31053/ psdaq/psdaq/webgui/tests/run_webgui_tests.sh -k real
control must be in state reset at the start; the test leaves it in reset.
"""

import json
import os
import re
import time
import urllib.request

import pytest

pytest.importorskip('playwright')
from playwright.sync_api import expect  # noqa: E402

from test_webgui_ui import P, T, expect_state, shot, events_now  # noqa: E402
from webgui_harness import STARTED, detect_backend  # noqa: E402

URL = os.environ.get('WEBGUI_REAL_URL')
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TR = 90000   # ms: real transitions (configure, beginrun) take seconds


class External:
    def __init__(self, url):
        self.url = url.rstrip('/') + '/'

    def get(self, path):
        with _OPENER.open(self.url.rstrip('/') + path, timeout=30) as r:
            return json.loads(r.read())


@pytest.fixture
def real():
    if not URL:
        pytest.skip('WEBGUI_REAL_URL not set (needs a running web GUI on a real DAQ)')
    s = External(URL)
    meta = s.get('/api/meta')
    b, why = detect_backend(meta)            # sim-daq if WEBGUI_SIM_DAQ names the daq_sim this web GUI is on
    STARTED.append({'url': s.url, 'backend': b, 'why': why})
    assert meta['backend'] == 'daqcontrol', meta['backend']
    assert s.get('/api/status')['state'] == 'reset', 'control must start in reset'
    return s


@pytest.fixture(scope='session')
def browser_type_launch_args(browser_type_launch_args):
    return {**browser_type_launch_args, 'headless': True, 'args': ['--no-sandbox', '--no-proxy-server']}


def test_full_cycle_real(page, real):
    page.set_viewport_size({'width': 900, 'height': 1300})
    page.goto(real.url)
    page.wait_for_selector('body[data-ready="1"]', timeout=T)
    expect(page.locator('#backend')).to_have_text('backend: daqcontrol')
    box = page.locator(P('CGWMainControl.box_state'))
    rec = page.locator(P('CGWMainControl.but_record'))
    evt = page.locator(P('CGWMainInfo.edi_evt'))
    run_lab, run_val = page.locator('#lab_run'), page.locator(P('CGWMainInfo.edi_run'))
    st0 = real.get('/api/status')
    last = st0['last_run_number']

    expect_state(page, 'reset', 'reset')
    expect(box).to_be_disabled()
    expect(page.locator(P('CGWMainPartition.but_select'))).to_be_enabled()
    expect(page.locator(P('CGWMainPartition.but_show'))).to_be_disabled()
    shot(page, 'real-01-reset.png')

    page.click(P('CGWMainPartition.but_select'))
    expect(page.locator(P('CGWMainControl.but_ctrls'))).to_have_text('UNALLOCATED', timeout=TR)
    expect_state(page, 'unallocated', 'rollcall')
    expect(page.locator('#select_window')).to_be_visible(timeout=T)
    plat = real.get('/api/platform')
    nproc = sum(len(v) for v in plat.values())
    expect(page.locator(P('CGWMainPartition.w_select.sel'))).to_have_count(nproc)
    aliases = sorted(v['proc_info']['alias'] for lvl in plat.values() for v in lvl.values())
    assert {'control', 'teb0', 'fakecam_0'} <= set(aliases), aliases
    shot(page, 'real-02-unallocated-select.png')
    page.click(P('QWPopupTableCheck.but_apply'))
    expect(page.locator(P('CGWMainControl.but_ctrls'))).to_have_text('ALLOCATED', timeout=TR)
    expect_state(page, 'allocated', 'alloc')
    expect(page.locator('#select_window')).to_be_hidden()
    expect(box).to_be_enabled()

    rec.click()
    expect(rec).to_have_attribute('aria-pressed', 'true', timeout=T)

    box.select_option('CONFIGURED')
    expect(page.locator(P('CGWMainControl.but_ctrls'))).to_have_text('CONFIGURED', timeout=TR)
    expect_state(page, 'configured', 'configure')
    expect(page.locator(P('CGWMainConfiguration.but_type'))).to_be_disabled()
    expect(run_lab).to_have_text('last run:')
    expect(run_val).to_have_text(str(last))
    shot(page, 'real-03-configured.png')

    box.select_option('RUNNING')
    expect(page.locator(P('CGWMainControl.but_ctrls'))).to_have_text('RUNNING', timeout=TR)
    expect_state(page, 'running', 'enable')
    expect(rec).to_be_disabled()
    expect(run_lab).to_have_text('run:')
    st = real.get('/api/status')
    run = st['run_number']
    assert run == last + 1, (run, last)
    expect(run_val).to_have_text(str(run))
    expect(page.locator(P('CGWMainInfo.edi_exp'))).to_have_text(st['experiment_name'])
    expect(evt).to_have_attribute('data-source', 'pva')
    expect(evt).to_have_text(re.compile(r'^[1-9]\d*$'), timeout=T)
    e1 = events_now(page)
    time.sleep(2.5)
    page.wait_for_function('() => parseInt(document.getElementById("edi_evt").textContent) > %d' % e1, timeout=T)
    e2 = events_now(page)
    assert e2 > e1, (e1, e2)
    expect(evt).to_have_attribute('data-final', '0')
    shot(page, 'real-04-running.png')

    box.select_option('CONFIGURED')
    expect(page.locator(P('CGWMainControl.but_ctrls'))).to_have_text('CONFIGURED', timeout=TR)
    expect_state(page, 'configured', 'endrun')
    expect(run_lab).to_have_text('last run:')
    expect(run_val).to_have_text(str(run))
    expect(evt).to_have_attribute('data-final', '1', timeout=T)       # latched after Disable
    e3 = events_now(page)
    time.sleep(2.5)
    assert events_now(page) == e3 >= e2, (e2, e3)
    assert real.get('/api/events')['events'] == e3

    rec.click()
    expect(rec).to_have_attribute('aria-pressed', 'false', timeout=T)

    box.select_option('RESET')
    expect(page.locator(P('CGWMainControl.but_ctrls'))).to_have_text('RESET', timeout=TR)
    expect_state(page, 'reset', 'reset')
    expect(box).to_be_disabled()
    expect(page.locator(P('CGWMainPartition.but_select'))).to_be_enabled()
    expect(evt).to_have_text(str(e3))                                  # the latch survives Reset
    expect(evt).to_have_attribute('data-final', '1')
    shot(page, 'real-05-back-to-reset.png')

    log = page.locator(P('QWLoggerStd.edi_txt')).inner_text()
    for needle in ('-> daq_control_set_state(configured)', '-> daq_control_set_state(running)',
                   'transition:enable state:running', 'transition:endrun state:configured',
                   '-> daq_control_set_state(reset)',
                   'fileReport: ', '%s-r%04d' % (st['experiment_name'], run)):
        assert needle in log, needle
    # error window: nothing but the separator lines a state change after a RESET adds
    # (QWLoggerStd.add_separator_err, CGWMainControl.py:169; app.js addLog 'SEP')
    err = page.locator(P('QWLoggerError.edi_err')).inner_text().strip()
    assert all(set(line.strip()) <= {'_'} for line in err.splitlines()), err
    assert real.get('/api/status')['state'] == 'reset'
