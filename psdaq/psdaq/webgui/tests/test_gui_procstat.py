"""Headless-browser tests of /gui/procstat, the web copy of psdaq/procmgr/procstat, against the simulated DAQ
(WEBGUI_SIM_DAQ: the server's --procstat-cnf is that daq_sim's generated .cnf, its rows the processes it runs).

PARITY_ROWS: the procstat parity rows (check_gui_parity, parity/guis/procstat.json) each test proves; conftest.py
records them as junit `parity` properties and the backend (sim-daq) the server was checked against.
"""

import os
import re
import time

import pytest
from playwright.sync_api import expect

import webgui_harness as H

PARITY_ROWS = {
    'test_table_lists_sim_processes_live_and_sortable': ['Ui_mainWindow.tableProcStat.col[ID]',
                                                          'Ui_mainWindow.tableProcStat.col[Status]'],
    'test_mode_buttons_are_exclusive': ['Ui_mainWindow.pushButtonConsole', 'Ui_mainWindow.pushButtonLogfile',
                                        'Ui_mainWindow.pushButtonRestart'],
    'test_cell_click_opens_console_and_logfile': ['Ui_mainWindow.tableProcStat.cellClicked'],
    'test_restart_of_local_process_shows_warning': ['WinProcStat.msgBox'],
    'test_current_row_kept_across_refresh': ['WinProcStat.on_tableProcStat_currentCellChanged'],
    'test_unknown_error_shows_critical_and_closes': ['WinProcStat.onProcMgrUnknownError.QMessageBox.critical'],
}
T = H.UI_TIMEOUT


def _cnf(sim):
    st = sim.work.load()
    return os.path.join(st['workdir'], st['cnf'])


def _server(interval):
    sim = H.sim_daq()
    if sim is None:
        pytest.skip('needs the simulated DAQ (WEBGUI_SIM_DAQ)')
    s = H.gui_server(['--procstat-cnf', _cnf(sim), '--procstat-platform', str(sim.platform),
                      '--procstat-interval', str(interval), '--procstat-logdir', sim.work.load()['loglink']],
                     H.check_procstat_source)
    return s


@pytest.fixture(scope='module')
def ps():
    s = _server(1)
    try:
        assert s.backend == 'sim-daq', (s.backend, s.backend_why)
        yield s
    finally:
        s.stop()


def _open(page, ps):
    page.goto(ps.url.rstrip('/') + '/gui/procstat')
    expect(page.locator('#procRows tr')).to_have_count(len(ps.sim.procs()), timeout=T)


def _seq(page):
    return int(page.locator('body').get_attribute('data-seq') or -1)


def test_table_lists_sim_processes_live_and_sortable(page, ps):
    _open(page, ps)
    st, _ = ps.sim.ds.procmgr_status(ps.sim.work.load())          # `procmgr status` of the same .cnf
    ids = page.locator('#procRows td[data-col="0"]').all_inner_texts()
    assert sorted(ids) == sorted(st), (ids, st)
    for uid, (status, pid) in st.items():
        cell = page.locator('#procRows tr[data-id="%s"] td[data-col="1"]' % uid)
        assert status == 'RUNNING', st
        expect(cell).to_have_text('RUNNING')
        expect(cell).to_have_css('background-color', 'rgb(0, 192, 0)')     # procstat:166
        expect(cell).to_have_css('color', 'rgb(255, 255, 255)')
    th_id = page.locator('[data-parity~="Ui_mainWindow.tableProcStat.col[ID]"]')
    th_st = page.locator('[data-parity~="Ui_mainWindow.tableProcStat.col[Status]"]')
    expect(th_st).to_have_attribute('aria-sort', 'ascending')                 # sortItems(1, Ascending) once
    s0 = _seq(page)
    page.wait_for_function('(s) => +document.body.dataset.seq >= s + 2', arg=s0, timeout=T)   # refreshed every 1 s
    th_id.click()
    expect(th_id).to_have_attribute('aria-sort', 'ascending')
    assert page.locator('#procRows td[data-col="0"]').all_inner_texts() == sorted(st)
    th_id.click()
    expect(th_id).to_have_attribute('aria-sort', 'descending')
    assert page.locator('#procRows td[data-col="0"]').all_inner_texts() == sorted(st, reverse=True)
    page.screenshot(path=str(H.SHOTS / 'procstat-table.png'))


def test_mode_buttons_are_exclusive(page, ps):
    _open(page, ps)
    b = {k: page.locator('[data-parity~="Ui_mainWindow.pushButton%s"]' % k) for k in ('Console', 'Logfile', 'Restart')}
    for k in ('Console', 'Logfile', 'Restart'):
        b[k].click()
        for o in b:
            expect(b[o]).to_have_attribute('aria-pressed', 'true' if o == k else 'false')
    b['Restart'].click()
    for o in b:
        expect(b[o]).to_have_attribute('aria-pressed', 'false')
    expect(b['Console']).to_have_text('Open Console')
    expect(b['Logfile']).to_have_text('View Logfile')


def test_cell_click_opens_console_and_logfile(page, ps):
    _open(page, ps)
    page.locator('[data-parity~="Ui_mainWindow.pushButtonConsole"]').click()
    page.locator('#procRows tr[data-id="teb0"] td[data-col="1"]').click()
    expect(page.locator('#viewer')).to_be_visible(timeout=T)
    expect(page.locator('#viewerTitle')).to_contain_text('console: teb0')
    expect(page.locator('#viewerText')).to_contain_text('@@@ Welcome to procServ', timeout=T)
    page.locator('[data-parity~="Ui_mainWindow.pushButtonLogfile"]').click()
    page.locator('#procRows tr[data-id="fakecam_0"] td[data-col="0"]').click()
    expect(page.locator('#viewerTitle')).to_contain_text('log: fakecam_0', timeout=T)
    path = re.search(r'\((/[^)]+)\)', page.locator('#viewerTitle').inner_text()).group(1)
    with open(path, 'rb') as f:
        head = f.read(300).decode('utf-8', 'replace')
    assert head.strip(), path
    first = head.splitlines()[0]
    expect(page.locator('#viewerText')).to_contain_text(first)
    page.screenshot(path=str(H.SHOTS / 'procstat-logfile.png'))


def test_restart_of_local_process_shows_warning(page, ps):
    _open(page, ps)
    before, _ = ps.sim.ds.procmgr_status(ps.sim.work.load())
    page.locator('[data-parity~="Ui_mainWindow.pushButtonRestart"]').click()
    page.locator('#procRows tr[data-id="control"] td[data-col="0"]').click()
    box = page.locator('[data-parity~="WinProcStat.msgBox"]')
    expect(box).to_be_visible(timeout=T)
    expect(page.locator('#msgBoxTitle')).to_have_text('Not Supported')
    expect(page.locator('#msgBoxText')).to_have_text('Local processes cannot be individually restarted')
    page.screenshot(path=str(H.SHOTS / 'procstat-restart-warning.png'))
    page.locator('#msgBoxOk').click()
    expect(box).to_be_hidden()
    time.sleep(1.5)
    after, _ = ps.sim.ds.procmgr_status(ps.sim.work.load())
    assert after == before, (before, after)            # nothing was restarted


def test_current_row_kept_across_refresh(page, ps):
    _open(page, ps)
    page.locator('#procRows tr[data-id="fakecam_1"] td[data-col="0"]').click()
    cur = page.locator('#procRows tr.current')
    expect(cur).to_have_attribute('data-id', 'fakecam_1')
    s0 = _seq(page)
    page.wait_for_function('(s) => +document.body.dataset.seq >= s + 2', arg=s0, timeout=T)
    expect(page.locator('#procRows tr.current')).to_have_count(1)
    expect(page.locator('#procRows tr.current')).to_have_attribute('data-id', 'fakecam_1')
    expect(page.locator('#viewer')).to_be_hidden()          # no mode: a click only moves the current row


def test_unknown_error_shows_critical_and_closes(page):
    s = _server(-1)                                         # procstat -i -1: time.sleep(-1) ends procMgrThread
    try:
        assert s.backend == 'sim-daq', (s.backend, s.backend_why)
        page.goto(s.url.rstrip('/') + '/gui/procstat')
        box = page.locator('[data-parity~="WinProcStat.onProcMgrUnknownError.QMessageBox.critical"]')
        expect(box).to_be_visible(timeout=T)
        expect(page.locator('#criticalTitle')).to_have_text('Unknown Error')
        expect(page.locator('#criticalText')).to_contain_text('procMgrThreadWrapper(): procMgrThread(ConfigFile = %s'
                                                              % _cnf(s.sim))
        expect(page.locator('#criticalText')).to_contain_text('Query Interval = -1.000000 ) Failed')
        expect(page.locator('#criticalText')).to_contain_text('ProcStat is not updating the process status.')
        page.screenshot(path=str(H.SHOTS / 'procstat-unknown-error.png'))
        page.locator('#criticalOk').click()
        expect(page.locator('#win')).to_be_hidden()
        expect(page.locator('#closedNote')).to_be_visible()
    finally:
        s.stop()
