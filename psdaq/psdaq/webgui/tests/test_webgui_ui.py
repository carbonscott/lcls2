"""Headless-browser tests of the DAQ web GUI.

The tests that prove parity rows (parity_rows.ROWS) use the `server` fixture (webgui_harness.daq_server):
the simulated DAQ when WEBGUI_SIM_DAQ names a running `daq_sim up --segments 2` work dir, else --emulate.
The others (`emu_server`, `slow_server`) always run against the emulator.  Where the two backends differ
(processes, run numbers, the events counter), the test reads the values from the server.

Run with tests/run_webgui_tests.sh (pytest-playwright, chromium headless --no-sandbox).
Elements are found by their data-parity id (<PyQt class>.<attr>[.<sub>]).
"""

import re
import time

import pytest

pytest.importorskip('playwright')
from playwright.sync_api import expect  # noqa: E402

from webgui_harness import ServerProc, SHOTS, UI_TIMEOUT, daq_server, platform_by_alias  # noqa: E402

T = UI_TIMEOUT   # ms, per UI expectation


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
    """The simulated DAQ (WEBGUI_SIM_DAQ) or the emulator: the parity tests' server."""
    yield from daq_server()


@pytest.fixture
def emu_server():
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


def test_page_loads(page, emu_server):
    server = emu_server
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
    """reset -> configured -> running -> back to reset, by clicking; record on/off; events counted.
    On the simulated DAQ the processes, the run numbers and the file name come from control, and the events
    counter is simxpm's (PVA), latched (data-final) after Disable (test_webgui_real.test_full_cycle_real)."""
    open_gui(page, server)
    sim = server.sim is not None
    box = page.locator(P('CGWMainControl.box_state'))
    rec = page.locator(P('CGWMainControl.but_record'))
    evt = page.locator(P('CGWMainInfo.edi_evt'))
    run_lab, run_val = page.locator('#lab_run'), page.locator(P('CGWMainInfo.edi_run'))
    last = server.get('/api/status')['last_run_number'] if sim else 0

    expect_state(page, 'reset', 'reset')
    expect(box).to_be_disabled()                         # CGWMainControl.py:237
    expect(page.locator(P('CGWMainPartition.but_select'))).to_be_enabled()
    expect(page.locator(P('CGWMainPartition.but_show'))).to_be_disabled()
    shot(page, '01-reset.png')

    page.click(P('CGWMainPartition.but_select'))
    expect_state(page, 'unallocated', 'rollcall')
    expect(page.locator('#select_window')).to_be_visible(timeout=T)
    nproc = len(platform_by_alias(server))
    assert nproc == (len(server.sim.procs()) if sim else 6), nproc     # sim: control, teb0, fakecam_0..
    expect(page.locator(P('CGWMainPartition.w_select.sel'))).to_have_count(nproc)
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
    expect(run_val).to_have_text(str(last))
    shot(page, '03-configured.png')

    box.select_option('RUNNING')
    expect_state(page, 'running', 'enable')
    expect(rec).to_be_disabled()                          # CGWMainControl.py:236
    expect(run_lab).to_have_text('run:')
    st = server.get('/api/status')
    run = st['run_number'] if sim else 1
    assert run == last + 1, (run, last)
    expect(run_val).to_have_text(str(run))
    if sim:
        expect(page.locator(P('CGWMainInfo.edi_exp'))).to_have_text(st['experiment_name'])
        expect(evt).to_have_attribute('data-source', 'pva')
    expect(evt).to_have_text(re.compile(r'^[1-9]\d*$'), timeout=T)
    e1 = events_now(page)
    time.sleep(2.5)
    page.wait_for_function('() => parseInt(document.getElementById("edi_evt").textContent) > %d' % e1, timeout=T)
    e2 = events_now(page)
    assert e2 > e1, (e1, e2)
    shot(page, '04-running.png')

    box.select_option('CONFIGURED')
    expect_state(page, 'configured', 'endrun')
    expect(run_lab).to_have_text('last run:')
    expect(run_val).to_have_text(str(run))
    if sim:
        expect(evt).to_have_attribute('data-final', '1', timeout=T)       # latched after Disable
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
                   '-> daq_control_set_state(reset)',
                   ('fileReport: ', '%s-r%04d' % (st['experiment_name'], run)) if sim else
                   'fileReport: /emulated/xtc/tst00000-r0001'):
        for n in (needle if isinstance(needle, tuple) else (needle,)):
            assert n in log, n
    err = page.locator(P('QWLoggerError.edi_err')).inner_text().strip()
    if sim:     # nothing but the separator lines a state change after a RESET adds (CGWMainControl.py:169)
        assert all(set(line.strip()) <= {'_'} for line in err.splitlines()), err
    else:
        assert err == ''
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


def test_config_type_popup(page, emu_server):
    server = emu_server
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
    """sel / grp / Monitor cells of the select table reach selectPlatform (per segment, after expanding the
    detector the table shows collapsed; the collapsed row is test_webgui_parity_ui's).  The emulator's
    platform has a meb0 to deselect; on the simulated DAQ (control, teb0, fakecam_0, fakecam_1) the
    deselected process is fakecam_0 (control refuses an alloc in which no active DRP uses the platform's
    readout group, control.py:1307, so fakecam_1 stays active, monitor-only, in that group)."""
    open_gui(page, server)
    sim = server.sim is not None
    page.click(P('CGWMainPartition.but_select'))
    expect_state(page, 'unallocated', 'rollcall')
    row = lambda alias: page.locator('#select_table tr[data-alias="%s"]' % alias)  # noqa: E731
    before = platform_by_alias(server)
    g0 = before['fakecam_1']['det_info']['readout']
    expect(row('fakecam_1')).to_be_hidden()
    row('fakecam_0').locator(P('CGWMainPartition.w_select.id')).click()          # expand fakecam's segments
    expect(row('fakecam_1')).to_be_visible()
    grp = row('fakecam_0').locator(P('CGWPartitionTable.set_readout_group_number@1'))
    assert grp.evaluate('(e) => [...e.options].map((o) => o.text)') == [str(i) for i in range(8)]  # LIST_OF_VALUES
    new = '3' if g0 != 3 else '4'
    row('fakecam_0').locator(P('CGWMainPartition.w_select.grp')).select_option(new)
    row('fakecam_1').locator(P('CGWMainPartition.w_select.monitor')).check()
    gone = 'fakecam_0' if sim else 'meb0'
    row(gone).locator(P('CGWMainPartition.w_select.sel')).uncheck()
    expect(row('teb0').locator(P('CGWMainPartition.w_select.grp'))).to_have_count(0)  # grp only for drp/tpr
    page.click(P('QWPopupTableCheck.but_apply'))
    expect_state(page, 'allocated', 'alloc')
    by_alias = platform_by_alias(server)
    assert by_alias['fakecam_0']['det_info']['readout'] == int(new)
    assert by_alias['fakecam_1']['det_info']['readout'] == g0
    assert by_alias['fakecam_1']['monitor'] == 1 and by_alias['fakecam_0']['monitor'] == 0
    assert by_alias[gone]['active'] == 0 and by_alias['fakecam_1']['active'] == 1
    if not sim:
        assert by_alias['fakecam_0']['active'] == 1
    expect(page.locator(P('QWLoggerStd.edi_txt'))).to_contain_text('drp/fakecam_1 set to MONITOR ONLY.', timeout=T)
    # collection shows only active processes per level
    coll = page.locator(P('CGWMainCollection.grid'))
    expect(coll.locator('td[data-col="meb"]')).to_have_text('')
    expect(coll.locator('td[data-col="drp"]')).to_contain_text('fakecam_1')
    if sim:
        expect(coll.locator('td[data-col="drp"]')).not_to_contain_text('fakecam_0')
    else:
        expect(coll.locator('td[data-col="drp"]')).to_contain_text('fakecam_0')
    expect(coll.locator('td[data-col="teb"]')).to_have_text('teb0')


def test_collection_and_show_window(page, server):
    open_gui(page, server)
    select_and_allocate(page)
    coll = page.locator(P('CGWMainCollection.grid'))
    by = platform_by_alias(server)
    want = {}
    for alias, v in by.items():
        if v['level'] in ('drp', 'teb', 'meb'):
            want.setdefault(v['level'], []).append(alias)
    if server.sim is None:
        assert want == {'drp': ['timing_0', 'fakecam_0', 'fakecam_1'], 'teb': ['teb0'], 'meb': ['meb0']}, want
    else:
        assert {k: sorted(v) for k, v in want.items()} == {'drp': ['fakecam_0', 'fakecam_1'], 'teb': ['teb0']}, want
    for col, names in want.items():
        for n in names:
            expect(coll.locator('td[data-col="%s"]' % col)).to_contain_text(n)
    show = page.locator(P('CGWMainPartition.but_show'))
    expect(show).to_be_enabled()
    expect(show).to_have_text('Show')
    show.click()
    expect(page.locator('#show_window')).to_be_visible()
    expect(show).to_have_text('Close')
    expect(page.locator('#show_table tbody tr')).to_have_count(len(by))
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
    """but_transition / but_ctrls only refresh the display (CGWMainControl.py:177-185): each click reads the
    status again (GET /api/status) and sends no command."""
    open_gui(page, server)
    sent = []
    page.on('request', lambda r: sent.append((r.method, r.url.rsplit('/', 1)[-1])))
    for pid in ('CGWMainControl.but_transition', 'CGWMainControl.but_ctrls'):
        with page.expect_request(lambda r: r.method == 'GET' and r.url.endswith('/api/status'), timeout=T):
            page.click(P(pid))
    expect_state(page, 'reset', 'reset')
    assert [m for m, _ in sent if m == 'POST'] == []
    assert server.get('/api/status')['state'] == 'reset'


def test_state_and_transition_buttons(page, emu_server):
    server = emu_server
    open_gui(page, server)
    page.click('#expert_transitions summary')
    page.click('#transition_buttons button[data-transition="rollcall"]')
    expect_state(page, 'unallocated', 'rollcall')
    page.click(P('QWPopupTableCheck.but_apply'))
    expect_state(page, 'allocated', 'alloc')
    page.click('#state_buttons button[data-state="connected"]')
    expect_state(page, 'connected', 'connect')


def test_error_log(page, emu_server):
    server = emu_server
    """A refused transition shows in the error window (QWLoggerStd.edi_err)."""
    open_gui(page, server)
    page.click('#expert_transitions summary')
    page.click('#transition_buttons button[data-transition="configure"]')
    err = page.locator(P('QWLoggerError.edi_err'))
    expect(err).to_contain_text("transition 'configure' not permitted in state 'reset'", timeout=T)
    expect_state(page, 'reset')


def test_info_panel(page, emu_server):
    server = emu_server
    open_gui(page, server)
    expect(page.locator(P('CGWMainInfo.edi_exp'))).to_have_text('tst00000')
    expect(page.locator(P('CGWMainInfo.edi_evt'))).to_have_text(re.compile(r'^\d+$'), timeout=T)
    expect(page.locator(P('CGWMainInfo.edi_evd'))).to_have_text('0', timeout=T)
    expect(page.locator(P('CGWMainInfo.edi_evt'))).to_be_visible()
    expect(page.locator('#events_source')).to_contain_text('emulator')
