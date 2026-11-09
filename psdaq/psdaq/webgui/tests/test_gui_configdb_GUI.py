"""Headless-browser tests of /gui/configdb_GUI, the web copy of psdaq/configdb/configdb_GUI.py
(psdaq.webgui.configdb_gui_api: the window's logic with the program's own workers), against the campaign's config DB
stand-in (psdaq.sim.configdb_server --seed-gui: tst/BEAM holds tmoteb_0 and fakecam_0, _1, _2), started by each test
with a store of its own on the port the parity walk used (47321).  Each test drives the page as the walk drove the
PyQt program (select the alias, the two fakecams, user.sim_seed, type 10794, writing on, Apply, OK, close) and
compares what the page shows with what the PyQt window showed in this session's walk, and the database with what was
asked of it (read back independently, over HTTP, from the stand-in)."""

import json
import os
import time
import urllib.request

import pytest
from playwright.sync_api import expect

import webgui_harness as H
import pvgui_checks as C

PORT = 47321
URL = 'http://127.0.0.1:%d/ws-auth/' % PORT
ARGS = '--url %s --hutch tst --password sim' % URL
ARGS_NOPW = '--url %s --hutch tst' % URL
G = 'ConfigdbGUI._build_ui.'
PARITY_ROWS = {
    'test_target_read_only_and_progress_at_start': [G + 'target_label', G + 'write_box', G + 'pbar'],
    'test_alias_selection_lists_the_detectors': [G + 'hutch_tree.col[hutch / alias]', G + 'hutch_tree.select',
                                                 G + 'device_list.col[detector]'],
    'test_two_detectors_and_a_parameter': [G + 'device_list.select', G + 'param_tree.col[fakecam_0]',
                                           G + 'param_tree.col[type]', G + 'param_tree.col[value]',
                                           G + 'param_tree.select', G + 'path_label', G + 'value_edit',
                                           G + 'hint_label', G + 'log'],
    'test_enum_parameter_is_a_combo': [G + 'value_combo'],
    'test_writing_without_a_password_warns': ['ConfigdbGUI._warn.box'],
    'test_apply_confirms_writes_and_rereads': [G + 'apply_button', 'ConfirmDialog.table.col[detector]',
                                               'ConfirmDialog.table.col[current]', 'ConfirmDialog.table.col[new]',
                                               'ConfirmDialog.note[fakecam_1: user.sim_seed already 10794]'],
    'test_close_while_writing_asks': ['ConfigdbGUI.closeEvent.box'],
}
T = H.UI_TIMEOUT
_OPEN = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def db(cmd, *args):
    """A read of the stand-in, independent of the server under test."""
    url = 'http://127.0.0.1:%d/ws/configDB/%s/%s' % (PORT, cmd, ''.join('%s/' % a for a in args))
    with _OPEN.open(url, timeout=10) as r:
        out = json.loads(r.read())
    assert out['success'], out
    return out['value']


def walk():
    """{row id: walk instance} and the walk's calls, of this session's walk of the PyQt configdb_GUI."""
    from psdaq.webgui.parity import check_gui_parity
    spec = next(s for s in check_gui_parity.load_specs().values() if s['_name'] == 'configdb_GUI')
    with open(check_gui_parity.walk_path(spec, H.gui_walks())) as f:
        w = json.load(f)
    return C.walk_instances('configdb_GUI', 'configdb/configdb_GUI.py'), w['calls']


def history(x, step):
    """The instance's text after a drive step of the walk (its 'texts' history)."""
    out = None
    for label, text in x.get('texts', []):
        out = text
        if label == step:
            return text
    return out


def check_source(dev):
    def check(s, sim):
        st = {}
        t0 = time.time()
        while time.time() - t0 < 20:
            st = s.get('/api/cdbgui/state')
            if st.get('hutches'):
                break
            time.sleep(0.3)
        ok = dev.alive() and st.get('url') == URL and [h for h, _ in st.get('hutches', [])] == db('get_hutches')
        return ok, 'configdb_GUI url %s; hutches %s (stand-in configdb_server %s pid %s alive %s answers %s)' % (
            st.get('url'), st.get('hutches'), ' '.join(dev.args), dev.pid, dev.alive(), db('get_hutches'))
    return check


@pytest.fixture
def cdb(tmp_path, request):
    """A seeded stand-in (fresh store) and a server on it; marker args: (gui args, modify delay)."""
    if H.sim_daq() is None:
        pytest.skip('needs the simulated DAQ node (WEBGUI_SIM_DAQ)')
    args, delay = getattr(request, 'param', (ARGS, 0))
    dev = H.DeviceSim('configdb_server', ['--store', str(tmp_path / 'configdb.json'), '--port', str(PORT), '--seed-gui',
                                          '--delay-modify', str(delay)])
    s = None
    try:
        s = H.gui_server(['--configdb-gui', args], check_source(dev), backend='sim-device:configdb_server')
        assert s.backend == 'sim-device:configdb_server', (s.backend, s.backend_why)
        yield s
    finally:
        if s is not None:
            s.stop()
        dev.stop()


def open_page(page, s):
    page.goto(s.url.rstrip('/') + '/gui/configdb_GUI')
    page.wait_for_function('() => document.body.dataset.ready === "1"', timeout=T)
    expect(page.locator('#hutches tr')).not_to_have_count(0, timeout=T)


def select(page, devices=('fakecam_0', 'fakecam_1'), param=('user *', 'sim_seed')):
    page.locator('#hutches tr[data-alias="BEAM"]').click()
    expect(page.locator('#devices tr')).to_have_count(len(db('get_devices', 'tst', 'BEAM')), timeout=T)
    for k, d in enumerate(devices):
        page.locator('#devices tr[data-device="%s"]' % d).click(modifiers=['Control'] if k else [])
        expect(page.locator('#devices tr[data-device="%s"].sel' % d)).to_have_count(1, timeout=T)
    expect(page.locator('#params tr')).not_to_have_count(0, timeout=T)
    if param:
        page.locator('#params tr[data-node="/%s"] .tw' % param[0]).click()
        page.locator('#params tr[data-path="%s.%s"]' % (param[0].rstrip(' *'), param[1])).click()
        expect(page.locator(C.sel(G + 'path_label'))).to_have_text('%s.%s' % (param[0].rstrip(' *'), param[1]),
                                                                    timeout=T)


def test_target_read_only_and_progress_at_start(page, cdb):
    W, _ = walk()
    open_page(page, cdb)
    shown = history(W[G + 'target_label'], 'shown')
    expect(page.locator(C.sel(G + 'target_label'))).to_have_text(shown)          # read-only: the ws/ URL
    assert shown == 'PROD  %s' % URL.replace('ws-auth', 'ws'), shown
    expect(page.locator(C.sel(G + 'write_box'))).to_be_checked()                    # starts read-only
    assert W[G + 'write_box']['text'] == 'Read-only'
    expect(page.locator(C.sel(G + 'pbar'))).to_be_hidden()                          # no job running
    expect(page).to_have_title('configdb - PROD (read-only)')


def test_alias_selection_lists_the_detectors(page, cdb):
    W, _ = walk()
    open_page(page, cdb)
    th = page.locator(C.sel(G + 'hutch_tree.col[hutch / alias]'))
    expect(th).to_have_text(W[G + 'hutch_tree.col[hutch / alias]']['columns'][0])
    hutches = page.locator('#hutches tr[data-alias]').evaluate_all('(r) => r.map((x) => x.dataset.hutch)')
    assert sorted(set(hutches)) == W[G + 'hutch_tree.select']['top_items'] == db('get_hutches'), hutches
    aliases = page.locator('#hutches tr[data-alias]').evaluate_all('(r) => r.map((x) => x.dataset.alias)')
    assert aliases == db('get_aliases', 'tst'), aliases                          # --hutch tst: expanded
    page.locator('#hutches tr[data-alias="BEAM"]').click()
    want = db('get_devices', 'tst', 'BEAM')
    expect(page.locator('#devices tr')).to_have_count(len(want), timeout=T)
    shown = page.locator('#devices td').all_inner_texts()
    assert shown == want == W[G + 'device_list.select']['top_items'], (shown, want, W[G + 'device_list.select'])
    expect(page.locator(C.sel(G + 'device_list.col[detector]'))).to_have_text('detector')
    expect(page.locator('#hutches tr.sel')).to_have_attribute('data-alias', 'BEAM')
    page.locator(C.sel(G + 'device_list.col[detector]')).click()                  # a header click sorts
    assert page.locator('#devices td').all_inner_texts() == sorted(want)
    page.locator(C.sel(G + 'device_list.col[detector]')).click()
    assert page.locator('#devices td').all_inner_texts() == sorted(want, reverse=True)


def test_two_detectors_and_a_parameter(page, cdb):
    W, _ = walk()
    open_page(page, cdb)
    select(page)
    heads = page.locator('#paramHead th').all_inner_texts()
    assert heads == W[G + 'param_tree.select']['columns'] == ['fakecam_0', 'type', 'value'], heads
    for h in heads:
        expect(page.locator(C.sel(G + 'param_tree.col[%s]' % h))).to_be_visible()
    cfg = db('get_configuration', 'tst', 'BEAM', 'fakecam_0')
    row = page.locator('#params tr[data-path="user.sim_seed"] td')
    assert row.all_inner_texts()[1:] == ['UINT32 (0..4294967295)', str(cfg['user']['sim_seed'])], row.all_inner_texts()
    step = 'tree-select:2:user */sim_seed'
    expect(page.locator(C.sel(G + 'path_label'))).to_have_text(history(W[G + 'path_label'], step))
    expect(page.locator(C.sel(G + 'value_edit'))).to_have_value(history(W[G + 'value_edit'], step))
    expect(page.locator(C.sel(G + 'hint_label'))).to_have_text(history(W[G + 'hint_label'], step))
    log = page.locator(C.sel(G + 'log'))
    expect(log).to_contain_text('fakecam_1: user.sim_seed', timeout=T)
    want = [ln for ln in (history(W[G + 'log'], step) or '').splitlines() if ln]
    got = [ln for ln in log.inner_text().splitlines() if ln]
    assert sorted(got) == sorted(want), (got, want)            # the scan's rows come in any order, as in the PyQt
    expect(page.locator(C.sel(G + 'apply_button'))).to_be_disabled()   # read-only


def test_enum_parameter_is_a_combo(page, cdb):
    open_page(page, cdb)
    select(page, devices=('fakecam_2',), param=('user *', 'mode'))
    combo = page.locator(C.sel(G + 'value_combo'))
    expect(combo).to_be_visible()
    expect(page.locator(C.sel(G + 'value_edit'))).to_be_hidden()
    cfg = db('get_configuration', 'tst', 'BEAM', 'fakecam_2')
    labels = cfg[':types:'][':enum:']['modeEnum']
    assert combo.locator('option').all_inner_texts() == list(labels), labels
    expect(combo).to_have_value(next(k for k, v in labels.items() if v == cfg['user']['mode']))
    combo.select_option('Off')
    expect(page.locator(C.sel(G + 'hint_label'))).to_have_text('one of: Normal|Burst|Off')
    expect(page.locator(C.sel(G + 'apply_button'))).to_be_disabled()


@pytest.mark.parametrize('cdb', [(ARGS_NOPW, 0)], indirect=True)
def test_writing_without_a_password_warns(page, cdb):
    _, calls = walk()
    want = next(c['args'][0] for c in calls if c['opener'] == 'QMessageBox.exec_' and c['site'][2] == '_warn')
    open_page(page, cdb)
    page.locator(C.sel(G + 'write_box')).click()
    box = page.locator(C.sel('ConfigdbGUI._warn.box'))
    expect(box).to_be_visible(timeout=T)
    expect(page.locator('#warnText')).to_have_text(want)
    page.locator('#warnOk').click()
    expect(box).to_be_hidden()
    expect(page.locator(C.sel(G + 'write_box'))).to_be_checked()                  # still read-only


def _edit_and_apply(page):
    select(page)
    page.locator(C.sel(G + 'value_edit')).fill('10794')
    page.locator(C.sel(G + 'write_box')).click()
    expect(page.locator(C.sel(G + 'write_box'))).not_to_be_checked(timeout=T)
    expect(page.locator(C.sel(G + 'apply_button'))).to_be_enabled(timeout=T)
    page.locator(C.sel(G + 'apply_button')).click()
    expect(page.locator('#confirm')).to_be_visible(timeout=T)


def test_apply_confirms_writes_and_rereads(page, cdb):
    W, calls = walk()
    open_page(page, cdb)
    _edit_and_apply(page)
    expect(page.locator(C.sel(G + 'target_label'))).to_have_text(W[G + 'target_label']['text'])   # PROD .../ws-auth/
    expect(page.locator('#target')).to_have_class('loud')
    assert any(c['opener'] == 'QDialog.exec' and c['args'][0] == 'ConfirmDialog' for c in calls), calls
    for col in ('detector', 'current', 'new'):
        expect(page.locator(C.sel('ConfirmDialog.table.col[%s]' % col))).to_have_text(col)
    tab = W['ConfirmDialog.table.col[detector]']
    cells = page.locator('#confirmRows tr').evaluate_all('(rs) => rs.map((r) => [...r.cells].map((c) => c.textContent))')
    assert cells == [row for row in tab['cells'] if row[0] is not None] == [['fakecam_0', '4660', '10794']], cells
    note = 'ConfirmDialog.note[fakecam_1: user.sim_seed already 10794]'
    expect(page.locator(C.sel(note))).to_have_value(W[note]['content'])
    expect(page.locator('#confirmHead')).to_contain_text('Setting user.sim_seed to 10794 on 1 detector(s)')
    page.screenshot(path=str(H.SHOTS / 'configdb_GUI-confirm.png'))
    page.locator('#confirmOk').click()
    log = page.locator(C.sel(G + 'log'))
    expect(log).to_contain_text('1 written, 0 failed, 0 skipped', timeout=T)
    expect(log).to_contain_text('--- writing user.sim_seed = 10794')
    assert db('get_configuration', 'tst', 'BEAM', 'fakecam_0')['user']['sim_seed'] == 10794
    assert db('get_configuration', 'tst', 'BEAM', 'fakecam_1')['user']['sim_seed'] == 10794
    expect(page.locator('#params tr[data-path="user.sim_seed"] td').nth(2)).to_have_text('10794', timeout=T)  # re-read
    expect(page.locator(C.sel(G + 'path_label'))).to_have_text('user.sim_seed')   # the selection comes back
    page.screenshot(path=str(H.SHOTS / 'configdb_GUI-written.png'))


@pytest.mark.parametrize('cdb', [(ARGS, 3)], indirect=True)
def test_close_while_writing_asks(page, cdb):
    _, calls = walk()
    want = next(c['args'][0] for c in calls if c['opener'] == 'QMessageBox.exec_' and c['site'][2] == 'closeEvent')
    open_page(page, cdb)
    _edit_and_apply(page)
    page.locator('#confirmOk').click()
    page.wait_for_function('() => (document.body.dataset.busy || "").includes("write")', timeout=T)
    page.locator('#closeWin').click()
    box = page.locator(C.sel('ConfigdbGUI.closeEvent.box'))
    expect(box).to_be_visible(timeout=T)
    expect(page.locator('#closeText')).to_have_text(want)
    page.locator('#closeOk').click()
    expect(page.locator('#closedNote')).to_be_visible(timeout=T)
    expect(page.locator('#win')).to_be_hidden()
