"""Headless-browser tests of the DAQ web GUI against the server in --emulate mode.

Run with tests/run_webgui_tests.sh (pytest-playwright, chromium headless --no-sandbox).
Elements are found by their data-parity id (<PyQt class>.<attr>[.<sub>]).
"""

import re
import time

import pytest

pytest.importorskip('playwright')
from playwright.sync_api import expect  # noqa: E402

from webgui_harness import ServerProc, SHOTS  # noqa: E402

T = 15000   # ms, per UI expectation


def P(pid):
    return '[data-parity~="%s"]' % pid


@pytest.fixture(scope='session')
def browser_type_launch_args(browser_type_launch_args):
    return {**browser_type_launch_args, 'headless': True, 'args': ['--no-sandbox']}


def _server(args):
    s = ServerProc(['--emulate'] + args).start()
    yield s
    s.stop()


@pytest.fixture
def server():
    yield from _server([])


@pytest.fixture
def slow_server():
    yield from _server(['--emulate-slow', '2.5'])


def open_gui(page, server):
    page.set_viewport_size({'width': 900, 'height': 1300})
    page.goto(server.url)
    page.wait_for_selector('body[data-ready="1"]', timeout=T)


def expect_state(page, state, transition=None):
    expect(page.locator(P('CGWMainControl.but_ctrls'))).to_have_text(state.upper(), timeout=T)
    if transition:
        expect(page.locator(P('CGWMainControl.but_transition'))).to_have_text(transition.upper(), timeout=T)


def shot(page, name):
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / name
    page.screenshot(path=str(path), full_page=True)
    return path


def events_now(page):
    return int(page.locator(P('CGWMainInfo.edi_evt')).inner_text())


def select_and_allocate(page):
    """reset -> Select (rollcall) -> unallocated -> Apply -> allocated, by clicking."""
    page.click(P('CGWMainPartition.but_select'))
    expect_state(page, 'unallocated', 'rollcall')
    expect(page.locator('#select_window')).to_be_visible(timeout=T)
    page.click(P('QWPopupTableCheck.but_apply'))
    expect_state(page, 'allocated', 'alloc')


def test_page_loads(page, server):
    open_gui(page, server)
    assert page.title() == 'DAQ Control'
    expect(page.locator('#backend')).to_have_text('backend: emulator')
    expect(page.locator('#conn')).to_have_text('connected')
    expect_state(page, 'reset', 'reset')
    for pid in ('CGWMainConfiguration.but_type', 'CGWMainPartition.but_select', 'CGWMainPartition.but_show',
                'CGWMainCollection.grid', 'CGWMainControl.but_record', 'CGWMainControl.box_state',
                'CGWMainControl.but_transition', 'CGWMainControl.but_ctrls', 'CGWMainInfo.edi_exp',
                'CGWMainInfo.edi_run', 'CGWMainInfo.edi_evt', 'CGWMainInfo.edi_evd', 'QWLoggerStd.edi_txt',
                'QWLoggerError.edi_err'):
        expect(page.locator(P(pid)).first).to_be_attached()
    shot(page, '00-loaded.png')


def test_full_cycle(page, server):
    """reset -> configured -> running -> back to reset, by clicking; record on/off; events counted."""
    open_gui(page, server)
    box = page.locator(P('CGWMainControl.box_state'))
    rec = page.locator(P('CGWMainControl.but_record'))
    run_lab, run_val = page.locator('#lab_run'), page.locator(P('CGWMainInfo.edi_run'))

    expect_state(page, 'reset', 'reset')
    expect(box).to_be_disabled()                         # CGWMainControl.py:237
    expect(page.locator(P('CGWMainPartition.but_select'))).to_be_enabled()
    expect(page.locator(P('CGWMainPartition.but_show'))).to_be_disabled()
    shot(page, '01-reset.png')

    page.click(P('CGWMainPartition.but_select'))
    expect_state(page, 'unallocated', 'rollcall')
    expect(page.locator('#select_window')).to_be_visible(timeout=T)
    expect(page.locator(P('CGWMainPartition.w_select.sel'))).to_have_count(6)
    shot(page, '02-unallocated-select.png')
    page.click(P('QWPopupTableCheck.but_apply'))
    expect_state(page, 'allocated', 'alloc')
    expect(page.locator('#select_window')).to_be_hidden()
    expect(box).to_be_enabled()

    rec.click()                                           # record ON (allowed up to configured)
    expect(rec).to_have_attribute('aria-pressed', 'true', timeout=T)

    box.select_option('CONFIGURED')
    expect_state(page, 'configured', 'configure')
    expect(page.locator(P('CGWMainConfiguration.but_type'))).to_be_disabled()   # CGWMainConfiguration.py:93
    expect(run_lab).to_have_text('last run:')
    expect(run_val).to_have_text('0')
    shot(page, '03-configured.png')

    box.select_option('RUNNING')
    expect_state(page, 'running', 'enable')
    expect(rec).to_be_disabled()                          # CGWMainControl.py:236
    expect(run_lab).to_have_text('run:')
    expect(run_val).to_have_text('1')
    expect(page.locator(P('CGWMainInfo.edi_evt'))).to_have_text(re.compile(r'^[1-9]\d*$'), timeout=T)
    e1 = events_now(page)
    time.sleep(2.0)
    page.wait_for_function('() => parseInt(document.getElementById("edi_evt").textContent) > %d' % e1, timeout=T)
    e2 = events_now(page)
    assert e2 > e1, (e1, e2)
    shot(page, '04-running.png')

    box.select_option('CONFIGURED')
    expect_state(page, 'configured', 'endrun')
    expect(run_lab).to_have_text('last run:')
    expect(run_val).to_have_text('1')
    time.sleep(1.5)
    e3 = events_now(page)
    time.sleep(1.5)
    assert events_now(page) == e3 >= e2, (e2, e3)       # counter stops outside running

    rec.click()                                           # record OFF
    expect(rec).to_have_attribute('aria-pressed', 'false', timeout=T)

    box.select_option('RESET')
    expect_state(page, 'reset', 'reset')
    expect(box).to_be_disabled()
    expect(page.locator(P('CGWMainPartition.but_select'))).to_be_enabled()
    shot(page, '05-back-to-reset.png')

    log = page.locator(P('QWLoggerStd.edi_txt')).inner_text()
    for needle in ('-> daq_control_set_state(configured)', '-> daq_control_set_state(running)',
                   'transition:enable state:running', 'transition:endrun state:configured',
                   '-> daq_control_set_state(reset)', 'fileReport: /emulated/xtc/tst00000-r0001'):
        assert needle in log, needle
    assert page.locator(P('QWLoggerError.edi_err')).inner_text().strip() == ''
    assert server.get('/api/status')['state'] == 'reset'


def test_record_toggle(page, server):
    open_gui(page, server)
    rec = page.locator(P('CGWMainControl.but_record'))
    expect(rec).to_be_enabled()
    rec.click()
    expect(rec).to_have_attribute('aria-pressed', 'true', timeout=T)
    assert server.get('/api/status')['recording'] is True
    rec.click()
    expect(rec).to_have_attribute('aria-pressed', 'false', timeout=T)
    assert server.get('/api/status')['recording'] is False


def test_config_type_popup(page, server):
    open_gui(page, server)
    but = page.locator(P('CGWMainConfiguration.but_type'))
    expect(but).to_have_text('BEAM ▼', timeout=T)
    but.click()
    pop = page.locator('#popup_type')
    expect(pop).to_be_visible()
    expect(pop.locator('button')).to_have_count(2)
    pop.locator('button[data-value="NOBEAM"]').click()
    expect(but).to_have_text('NOBEAM ▼', timeout=T)
    assert server.get('/api/status')['config_alias'] == 'NOBEAM'
    expect(pop).to_be_hidden()


def test_partition_columns_apply(page, server):
    """sel / grp / Monitor cells of the select table reach selectPlatform."""
    open_gui(page, server)
    page.click(P('CGWMainPartition.but_select'))
    expect_state(page, 'unallocated', 'rollcall')
    row = lambda alias: page.locator('#select_table tr[data-alias="%s"]' % alias)  # noqa: E731
    row('fakecam_0').locator(P('CGWMainPartition.w_select.grp')).select_option('3')
    row('fakecam_1').locator(P('CGWMainPartition.w_select.monitor')).check()
    row('meb0').locator(P('CGWMainPartition.w_select.sel')).uncheck()
    expect(row('teb0').locator(P('CGWMainPartition.w_select.grp'))).to_have_count(0)  # grp only for drp/tpr
    page.click(P('QWPopupTableCheck.but_apply'))
    expect_state(page, 'allocated', 'alloc')
    plat = server.get('/api/platform')
    by_alias = {v['proc_info']['alias']: v for lvl in plat.values() for v in lvl.values()}
    assert by_alias['fakecam_0']['det_info']['readout'] == 3
    assert by_alias['fakecam_1']['monitor'] == 1
    assert by_alias['meb0']['active'] == 0
    expect(page.locator(P('QWLoggerStd.edi_txt'))).to_contain_text('drp/fakecam_1 set to MONITOR ONLY.', timeout=T)
    # collection shows only active processes per level
    coll = page.locator(P('CGWMainCollection.grid'))
    expect(coll.locator('td[data-col="meb"]')).to_have_text('')
    expect(coll.locator('td[data-col="drp"]')).to_contain_text('fakecam_0')
    expect(coll.locator('td[data-col="teb"]')).to_have_text('teb0')


def test_collection_and_show_window(page, server):
    open_gui(page, server)
    select_and_allocate(page)
    coll = page.locator(P('CGWMainCollection.grid'))
    for col, names in (('drp', ('timing_0', 'fakecam_0', 'fakecam_1')), ('teb', ('teb0',)), ('meb', ('meb0',))):
        for n in names:
            expect(coll.locator('td[data-col="%s"]' % col)).to_contain_text(n)
    show = page.locator(P('CGWMainPartition.but_show'))
    expect(show).to_be_enabled()
    expect(show).to_have_text('Show')
    show.click()
    expect(page.locator('#show_window')).to_be_visible()
    expect(show).to_have_text('Close')
    expect(page.locator('#show_table tbody tr')).to_have_count(6)
    shot(page, '06-show-window.png')
    show.click()
    expect(page.locator('#show_window')).to_be_hidden()
    expect(show).to_have_text('Show')


def test_progress_bar(page, slow_server):
    open_gui(page, slow_server)
    select_and_allocate(page)
    page.locator(P('CGWMainControl.box_state')).select_option('CONFIGURED')
    bar = page.locator(P('CGWMainControl.bar_progress'))
    expect(bar).to_be_visible(timeout=T)
    expect(bar).to_contain_text('configure')
    shot(page, '07-progress.png')
    expect_state(page, 'configured', 'configure')
    expect(bar).to_be_hidden(timeout=T)


def test_refresh_buttons(page, server):
    """but_transition / but_ctrls only refresh the display (CGWMainControl.py:177-185)."""
    open_gui(page, server)
    page.click(P('CGWMainControl.but_transition'))
    page.click(P('CGWMainControl.but_ctrls'))
    expect_state(page, 'reset', 'reset')
    assert server.get('/api/status')['state'] == 'reset'


def test_state_and_transition_buttons(page, server):
    open_gui(page, server)
    page.click('#expert_transitions summary')
    page.click('#transition_buttons button[data-transition="rollcall"]')
    expect_state(page, 'unallocated', 'rollcall')
    page.click(P('QWPopupTableCheck.but_apply'))
    expect_state(page, 'allocated', 'alloc')
    page.click('#state_buttons button[data-state="connected"]')
    expect_state(page, 'connected', 'connect')


def test_error_log(page, server):
    """A refused transition shows in the error window (QWLoggerStd.edi_err)."""
    open_gui(page, server)
    page.click('#expert_transitions summary')
    page.click('#transition_buttons button[data-transition="configure"]')
    err = page.locator(P('QWLoggerError.edi_err'))
    expect(err).to_contain_text("transition 'configure' not permitted in state 'reset'", timeout=T)
    expect_state(page, 'reset')


def test_info_panel(page, server):
    open_gui(page, server)
    expect(page.locator(P('CGWMainInfo.edi_exp'))).to_have_text('tst00000')
    expect(page.locator(P('CGWMainInfo.edi_evt'))).to_have_text(re.compile(r'^\d+$'), timeout=T)
    expect(page.locator(P('CGWMainInfo.edi_evd'))).to_have_text('0', timeout=T)
    expect(page.locator(P('CGWMainInfo.edi_evt'))).to_be_visible()
    expect(page.locator('#events_source')).to_contain_text('emulator')
