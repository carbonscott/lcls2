"""Headless-browser tests of /gui/daqstat, the web copy of psdaq/slurm/daqstat.py (psdaq.webgui.daqstat_api with
static/gui/procstat.js), against simslurm (psdaq/psdaq/sim/simslurm.py), which the test starts on the simulated DAQ's
.cnf (WEBGUI_SIM_DAQ), converted to a daqmgr config by daqmgr's own cnftopy, with one job per process, some PENDING
and then RUNNING.  The server never runs a Slurm command; the states are checked against simslurm's state file read by
the test, a restart is seen there as a new job id."""

import json
import os
import re
import tempfile
import time

import pytest
from playwright.sync_api import expect

import webgui_harness as H

PARITY_ROWS = {
    'test_table_lists_the_jobs_states_live_and_sortable': ['Ui_mainWindow.tableProcStat.col[ID]',
                                                            'Ui_mainWindow.tableProcStat.col[Status]'],
    'test_mode_buttons_are_exclusive': ['Ui_mainWindow.pushButtonConsole', 'Ui_mainWindow.pushButtonLogfile',
                                        'Ui_mainWindow.pushButtonRestart'],
    'test_cell_click_opens_console_logfile_and_restarts': ['Ui_mainWindow.tableProcStat.cellClicked'],
    'test_current_row_kept_across_refresh': ['WinProcStat.on_tableProcStat_currentCellChanged'],
    'test_unknown_error_shows_critical_and_closes': ['WinProcStat.onProcMgrUnknownError.QMessageBox.critical',
                                                     'WinProcStat.msgBox'],
}
T = H.UI_TIMEOUT
COLORS = {'RUNNING': 'rgb(0, 192, 0)', 'PENDING': 'rgb(192, 192, 0)', 'COMPLETED': 'rgb(0, 0, 192)'}


def check_daqstat_source(dev, state):
    def check(s, sim):
        st = {}
        t0 = time.time()
        while time.time() - t0 < 20 and not st.get('rows'):
            st = s.get('/api/daqstat/status')
            time.sleep(0.5)
        with open(state) as f:
            jobs = json.load(f)['jobs']
        ok = st.get('sim_pid') == dev.pid and dev.alive() and \
            sorted(r['showId'] for r in st.get('rows', [])) == sorted(j['job_name'] for j in jobs)
        return ok, 'daqstat slurm %s sim pid %s (simslurm %s pid %s alive %s), rows %s, jobs %s' % (
            st.get('slurm'), st.get('sim_pid'), state, dev.pid, dev.alive(), [r['showId'] for r in st.get('rows', [])],
            [j['job_name'] for j in jobs])
    return check


def _start(cnf_py=None, interval=1):
    sim = H.sim_daq()
    if sim is None:
        pytest.skip('needs the simulated DAQ (WEBGUI_SIM_DAQ)')
    st = sim.work.load()
    d = tempfile.mkdtemp(prefix='simslurm-')
    state = os.path.join(d, 'slurm.json')
    dev = H.DeviceSim('simslurm', ['--state', state, '--cnf', os.path.join(st['workdir'], st['cnf']),
                                   '--py', os.path.join(d, 'daqstat.py'), '--logdir', os.path.join(d, 'logs')])
    try:
        s = H.gui_server(['--daqstat-cnf', cnf_py or os.path.join(d, 'daqstat.py'), '--daqstat-slurm', state,
                          '--daqstat-interval', str(interval)],
                         check_daqstat_source(dev, state) if cnf_py is None else (lambda s, sim: (
                             s.get('/api/daqstat/status').get('sim_pid') == dev.pid, 'simslurm pid %s' % dev.pid)),
                         backend='sim-device:simslurm')
    except Exception:
        dev.stop()
        raise
    s.dev, s.state = dev, state
    return s


def _stop(s):
    try:
        s.stop()
    finally:
        s.dev.stop()


@pytest.fixture(scope='module')
def ds():
    s = _start()
    try:
        assert s.backend == 'sim-device:simslurm', (s.backend, s.backend_why)
        yield s
    finally:
        _stop(s)


def _jobs(s):
    with open(s.state) as f:
        return json.load(f)['jobs']


def _open(page, s):
    page.goto(s.url.rstrip('/') + '/gui/daqstat')
    n = len(set(j['job_name'] for j in _jobs(s)))
    expect(page.locator('#procRows tr')).to_have_count(n, timeout=T)


def _seq(page):
    return int(page.locator('body').get_attribute('data-seq') or -1)


def _states(s):
    """daqmgr show_status of simslurm's jobs: the latest active job of a process, else COMPLETED."""
    out = {}
    for j in sorted(_jobs(s), key=lambda j: j['job_id']):
        if j['state'] in ('PENDING', 'RUNNING', 'SUSPENDED', 'COMPLETING'):
            out[j['job_name']] = j['state']
        else:
            out.setdefault(j['job_name'], 'COMPLETED')
    return out


def test_table_lists_the_jobs_states_live_and_sortable(page, ds):
    _open(page, ds)
    seen_pending = False
    t0 = time.time()
    while time.time() - t0 < 30:
        want = _states(ds)
        got = {r: page.locator('#procRows tr[data-id="%s"] td[data-col="1"]' % r).text_content() for r in want}
        if got == want:
            seen_pending |= 'PENDING' in want.values()
            if 'PENDING' not in want.values():
                break
        time.sleep(0.3)
    assert got == want and 'PENDING' not in want.values(), (got, want)
    assert seen_pending, 'simslurm seeds a PENDING job; the table never showed it'
    for r, stt in want.items():
        cell = page.locator('#procRows tr[data-id="%s"] td[data-col="1"]' % r)
        expect(cell).to_have_css('background-color', COLORS[stt])         # daqstat:212-228
        expect(cell).to_have_css('color', 'rgb(255, 255, 255)')
    th_id = page.locator('[data-parity~="Ui_mainWindow.tableProcStat.col[ID]"]')
    th_st = page.locator('[data-parity~="Ui_mainWindow.tableProcStat.col[Status]"]')
    expect(th_st).to_have_attribute('aria-sort', 'ascending')                 # sortItems(1, Ascending) once
    s0 = _seq(page)
    page.wait_for_function('(s) => +document.body.dataset.seq >= s + 2', arg=s0, timeout=T)   # refreshed every 1 s
    th_id.click()
    assert page.locator('#procRows td[data-col="0"]').all_inner_texts() == sorted(want)
    th_id.click()
    assert page.locator('#procRows td[data-col="0"]').all_inner_texts() == sorted(want, reverse=True)
    page.screenshot(path=str(H.SHOTS / 'daqstat-table.png'))


def test_mode_buttons_are_exclusive(page, ds):
    _open(page, ds)
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
    expect(b['Restart']).to_have_text('Restart')


def test_cell_click_opens_console_logfile_and_restarts(page, ds):
    _open(page, ds)
    jobs = {j['job_name']: j for j in _jobs(ds) if j['state'] == 'RUNNING'}
    uid = sorted(jobs)[0]
    page.locator('[data-parity~="Ui_mainWindow.pushButtonConsole"]').click()
    page.locator('#procRows tr[data-id="%s"] td[data-col="1"]' % uid).click()
    expect(page.locator('#viewer')).to_be_visible(timeout=T)
    expect(page.locator('#viewerTitle')).to_contain_text('console: %s (sattach %s.0)' % (uid, jobs[uid]['job_id']))
    expect(page.locator('#viewerText')).to_contain_text('simslurm: job %d %s started' % (jobs[uid]['job_id'], uid))
    page.locator('[data-parity~="Ui_mainWindow.pushButtonLogfile"]').click()
    page.locator('#procRows tr[data-id="%s"] td[data-col="0"]' % uid).click()
    expect(page.locator('#viewerTitle')).to_contain_text('log: %s (%s)' % (uid, jobs[uid]['logfile']), timeout=T)
    n = page.locator('#viewerText').text_content().count('tick')
    page.wait_for_function('(n) => document.getElementById("viewerText").textContent.split("tick").length - 1 > n',
                           arg=n, timeout=T)                            # less +F: the log grows
    page.locator('[data-parity~="Ui_mainWindow.pushButtonRestart"]').click()
    page.locator('#procRows tr[data-id="%s"] td[data-col="0"]' % uid).click()
    expect(page.locator('#statusbar')).to_contain_text('restarted ' + uid, timeout=T)
    after = [j for j in _jobs(ds) if j['job_name'] == uid]
    old = [j for j in after if j['job_id'] == jobs[uid]['job_id']][0]
    new = [j for j in after if j['job_id'] > jobs[uid]['job_id']]
    assert old['state'] == 'CANCELLED' and len(new) == 1 and new[0]['submitted_by'] == 'sbatch' and \
        new[0]['comment'] == old['comment'], after                     # Runner.restart: scancel, then sbatch
    cell = page.locator('#procRows tr[data-id="%s"] td[data-col="1"]' % uid)
    seen, t0 = [], time.time()
    while time.time() - t0 < 30:                       # the new job: PENDING, then RUNNING (simslurm: after 3 s)
        t = cell.text_content()
        if not seen or seen[-1] != t:
            seen.append(t)
        if 'PENDING' in seen and t == 'RUNNING' and _states(ds)[uid] == 'RUNNING':
            break
        time.sleep(0.2)
    assert 'PENDING' in seen and seen[-1] == 'RUNNING' and _states(ds)[uid] == 'RUNNING', (seen, _states(ds))
    page.screenshot(path=str(H.SHOTS / 'daqstat-restart.png'))


def test_current_row_kept_across_refresh(page, ds):
    _open(page, ds)
    uid = sorted(_states(ds))[-1]
    page.locator('#procRows tr[data-id="%s"] td[data-col="0"]' % uid).click()
    expect(page.locator('#procRows tr.current')).to_have_attribute('data-id', uid)
    s0 = _seq(page)
    page.wait_for_function('(s) => +document.body.dataset.seq >= s + 2', arg=s0, timeout=T)
    expect(page.locator('#procRows tr.current')).to_have_count(1)
    expect(page.locator('#procRows tr.current')).to_have_attribute('data-id', uid)
    expect(page.locator('#viewer')).to_be_hidden()          # no mode: a click only moves the current row


def test_unknown_error_shows_critical_and_closes(page):
    s = _start(cnf_py='/nonexistent/daqstat.py')              # Runner raises: the thread ends (see daqstat_api)
    try:
        assert s.backend == 'sim-device:simslurm', (s.backend, s.backend_why)
        page.goto(s.url.rstrip('/') + '/gui/daqstat')
        expect(page.locator('[data-parity~="WinProcStat.msgBox"]')).to_have_count(1)     # built at start, hidden
        expect(page.locator('#msgBoxTitle')).to_have_text('Warning')
        box = page.locator('[data-parity~="WinProcStat.onProcMgrUnknownError.QMessageBox.critical"]')
        expect(box).to_be_visible(timeout=T)
        expect(page.locator('#criticalTitle')).to_have_text('Unknown Error')
        expect(page.locator('#criticalText')).to_contain_text(
            'daqmgrThreadWrapper(): daqmgrThread(ConfigFile = /nonexistent/daqstat.py, Query Interval = 1.000000 ) Failed')
        expect(page.locator('#criticalText')).to_contain_text('Not able to update the process status.')
        expect(page.locator('[data-parity~="WinProcStat.msgBox"]')).to_be_hidden()     # daqstat never shows it
        page.screenshot(path=str(H.SHOTS / 'daqstat-unknown-error.png'))
        page.locator('#criticalOk').click()
        expect(page.locator('#win')).to_be_hidden()
        expect(page.locator('#closedNote')).to_be_visible()
    finally:
        _stop(s)
