"""Headless-browser tests of the main-window parity rows that test_webgui_ui.py does not cover:
the CGWPartitionTable ID column (collapse / expand a detector's segments), the read-only display
cells, the CGWMainTabs tab bar and the CGWMainTabUser buttons, CustomQComboBox's ignored arrow keys
and wheel on box_state, and the Qt mnemonics (&Apply, &Cancel) as Alt+<letter>.

Elements are found by their data-parity row id.  parity_rows.ROWS says which test proves which row;
conftest.py records them as junit `parity` properties, which check_parity requires.
The server runs in --emulate mode (two segments fakecam_0 / fakecam_1 of detector fakecam); the
config editor tests also run the config DB stand-in on 127.0.0.1 (configeditor_harness).

Run with tests/run_webgui_tests.sh -k parity_ui.
"""

import re

import pytest

pytest.importorskip('playwright')
from playwright.sync_api import expect  # noqa: E402

from webgui_harness import ServerProc, SHOTS  # noqa: E402
from configeditor_harness import ConfigDbProc, seeded_store  # noqa: E402

T = 15000   # ms, per UI expectation


def P(pid):
    return '[data-parity~="%s"]' % pid


@pytest.fixture(scope='session')
def browser_type_launch_args(browser_type_launch_args):
    return {**browser_type_launch_args, 'headless': True, 'args': ['--no-sandbox']}


@pytest.fixture
def server():
    s = ServerProc(['--emulate']).start()
    yield s
    s.stop()


@pytest.fixture
def cfg_server(tmp_path):
    db = ConfigDbProc(seeded_store(tmp_path)).start()
    s = ServerProc(['--emulate', '--configdb-url', db.url]).start()
    yield s
    s.stop()
    db.stop()


def open_gui(page, server, height=1300):
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.set_viewport_size({'width': 900, 'height': height})
    page.goto(server.url)
    page.wait_for_selector('body[data-ready="1"]', timeout=T)
    return errors


def posts(page):
    """List that collects every POST the page sends: (path, body)."""
    out = []
    page.on('request', lambda r: out.append((r.url.split('://', 1)[1].split('/', 1)[1], r.post_data))
            if r.method == 'POST' else None)
    return out


def expect_state(page, state):
    expect(page.locator(P('CGWMainControl.but_ctrls'))).to_have_text(state.upper(), timeout=T)


def shot(page, name):
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / name), full_page=True)


def row(page, table, alias):
    return page.locator('#%s tbody tr[data-alias="%s"]' % (table, alias))


def select(page):
    page.click(P('CGWMainPartition.but_select'))
    expect_state(page, 'unallocated')
    expect(page.locator('#select_window')).to_be_visible(timeout=T)


def platform_by_alias(server):
    plat = server.get('/api/platform')
    return {v['proc_info']['alias']: v for lvl in plat.values() for v in lvl.values()}


def alt_key(page, ch):
    """Alt+<ch> as a real keyboard would send it (CDP keyDown with unmodifiedText), so the browser's own
    accesskey handling runs; Playwright's keyboard.press('Alt+a') sends no text and never reaches it."""
    cdp = page.context.new_cdp_session(page)
    up = ch.upper()
    alt = {'key': 'Alt', 'code': 'AltLeft', 'windowsVirtualKeyCode': 18, 'nativeVirtualKeyCode': 18}
    k = {'key': ch, 'code': 'Key' + up, 'windowsVirtualKeyCode': ord(up), 'nativeVirtualKeyCode': ord(up),
         'modifiers': 1}
    cdp.send('Input.dispatchKeyEvent', dict(alt, type='rawKeyDown', modifiers=1))
    cdp.send('Input.dispatchKeyEvent', dict(k, type='keyDown', text=ch, unmodifiedText=ch))
    cdp.send('Input.dispatchKeyEvent', dict(k, type='keyUp'))
    cdp.send('Input.dispatchKeyEvent', dict(alt, type='keyUp', modifiers=0))
    cdp.detach()


def not_editable(loc):
    """The element is shown, is not an input, holds no input, and cannot be typed into."""
    expect(loc).to_be_visible(timeout=T)
    info = loc.evaluate('''(e) => ({tag: e.tagName, ce: e.isContentEditable,
        inputs: e.querySelectorAll('input, select, textarea, [contenteditable="true"]').length})''')
    assert info['tag'] not in ('INPUT', 'SELECT', 'TEXTAREA') and not info['ce'] and info['inputs'] == 0, info
    return info


# ---------------- CGWPartitionTable: the ID column ----------------

def test_select_id_collapses_and_expands_detector(page, server):
    """CGWPartitionTable.collapse_all at construction, then on_click on an ID cell: expand_collapse_detector.
    A collapsed detector's sel / Monitor / grp set every segment (set_group_check_state,
    set_readout_group_number_for_detector_segments); Apply sends what fill_output_object gives."""
    errors = open_gui(page, server)
    select(page)
    f0, f1 = row(page, 'select_table', 'fakecam_0'), row(page, 'select_table', 'fakecam_1')
    id0, id1 = f0.locator(P('CGWMainPartition.w_select.id')), f1.locator(P('CGWMainPartition.w_select.id'))
    expect(f1).to_be_hidden()                                   # collapsed at construction
    expect(f0).to_have_attribute('data-collapser', '1')
    expect(id0).to_have_attribute('title', re.compile('EXPAND'))
    expect(row(page, 'select_table', 'timing_0')).to_be_visible()   # a one-segment detector is not collapsed
    expect(row(page, 'select_table', 'timing_0')).not_to_have_attribute('data-collapser', '1')
    shot(page, 'p01-select-collapsed.png')
    # the collapsed row's check boxes and group act on both segments
    f0.locator(P('CGWMainPartition.w_select.sel')).uncheck()
    f0.locator(P('CGWMainPartition.w_select.monitor')).check()
    f0.locator(P('CGWMainPartition.w_select.grp')).select_option('5')
    id0.click()                                                 # expand
    expect(f1).to_be_visible()
    expect(f0).not_to_have_attribute('data-collapser', '1')
    expect(id0).to_have_attribute('title', re.compile('COLLAPSE'))
    expect(f1.locator(P('CGWMainPartition.w_select.sel'))).not_to_be_checked()
    expect(f1.locator(P('CGWMainPartition.w_select.monitor'))).to_be_checked()
    expect(f1.locator(P('CGWMainPartition.w_select.grp'))).to_have_value('5')
    shot(page, 'p02-select-expanded.png')
    # mixed segments, collapsed from the other segment's ID: partial check box; Apply keeps each segment's own state
    f0.locator(P('CGWMainPartition.w_select.sel')).check()
    id1.click()                                                 # collapse with fakecam_1 as the shown row
    expect(f0).to_be_hidden()
    expect(f1).to_have_attribute('data-collapser', '1')
    assert f1.locator(P('CGWMainPartition.w_select.sel')).evaluate('(e) => e.indeterminate') is True
    page.click(P('QWPopupTableCheck.but_apply'))
    expect_state(page, 'allocated')
    by = platform_by_alias(server)
    assert (by['fakecam_0']['active'], by['fakecam_1']['active']) == (1, 0)
    assert (by['fakecam_0']['monitor'], by['fakecam_1']['monitor']) == (1, 1)
    assert by['fakecam_0']['det_info']['readout'] == by['fakecam_1']['det_info']['readout'] == 5
    assert by['timing_0']['det_info']['readout'] == 0
    assert errors == []


def test_show_id_collapses_and_expands_detector(page, server):
    """The Show window (CGWMainPartition.on_but_show) is a CGWPartitionTable too: ID click expands / collapses."""
    errors = open_gui(page, server)
    select(page)
    page.click(P('QWPopupTableCheck.but_apply'))
    expect_state(page, 'allocated')
    page.click(P('CGWMainPartition.but_show'))
    f0, f1 = row(page, 'show_table', 'fakecam_0'), row(page, 'show_table', 'fakecam_1')
    expect(f0).to_be_visible(timeout=T)
    expect(f1).to_be_hidden()
    expect(f0).to_have_attribute('data-collapser', '1')
    f0.locator(P('CGWMainPartition.w_show.id')).click()
    expect(f1).to_be_visible()
    shot(page, 'p03-show-expanded.png')
    f1.locator(P('CGWMainPartition.w_show.id')).click()
    expect(f0).to_be_hidden()
    expect(f1).to_have_attribute('data-collapser', '1')
    f1.locator(P('CGWMainPartition.w_show.id')).click()
    expect(f0).to_be_visible()
    assert errors == []


# ---------------- read-only displays: shown, not editable ----------------

def test_partition_display_cells_shown_not_editable(page, server):
    """Columns the enumerator finds inert (never checkable / editable, no click action): the web shows them
    and they cannot be changed; clicking them sends nothing."""
    open_gui(page, server)
    sent = posts(page)
    select(page)
    lph = row(page, 'select_table', 'teb0').locator(P('CGWMainPartition.w_select.level_pid_host'))
    expect(lph).to_have_text('teb/41004/localhost')
    not_editable(lph)
    n0 = len(sent)
    lph.click()
    page.wait_for_timeout(300)
    assert len(sent) == n0 and lph.inner_text() == 'teb/41004/localhost'
    page.click(P('QWPopupTableCheck.but_apply'))
    expect_state(page, 'allocated')
    page.click(P('CGWMainPartition.but_show'))
    r = row(page, 'show_table', 'fakecam_0')
    expect(r).to_be_visible(timeout=T)
    want = {'CGWMainPartition.w_show.sel': '✓', 'CGWMainPartition.w_show.grp': '0',
            'CGWMainPartition.w_show.level_pid_host': 'drp/41002/localhost', 'CGWMainPartition.w_show.monitor': ''}
    n0 = len(sent)
    for pid, text in want.items():
        c = r.locator(P(pid))
        expect(c).to_have_text(text)
        not_editable(c)
        c.click()
    page.wait_for_timeout(300)
    assert len(sent) == n0, sent[n0:]
    for pid, text in want.items():
        expect(r.locator(P(pid))).to_have_text(text)
    shot(page, 'p04-show-display-cells.png')


def test_collection_cells_shown_not_editable(page, server):
    """CGWMainCollection's per-level CGWPanelList items: shown, never checkable or editable (CGWPanelList.py:58-60)."""
    open_gui(page, server)
    sent = posts(page)
    select(page)
    page.click(P('QWPopupTableCheck.but_apply'))
    expect_state(page, 'allocated')
    cells = page.locator(P('CGWPanelList.fill_list_model@1'))
    expect(cells).to_have_count(5, timeout=T)                    # active drp, teb, meb (TABTITLE_H)
    texts = sorted(c.inner_text() for c in cells.all())
    assert texts == ['fakecam_0', 'fakecam_1', 'meb0', 'teb0', 'timing_0'], texts
    n0 = len(sent)
    for c in cells.all():
        not_editable(c)
        c.click()
        c.dblclick()
    page.wait_for_timeout(300)
    assert len(sent) == n0 and sorted(c.inner_text() for c in cells.all()) == texts


def test_logger_text_shown_read_only(page, server):
    """QWLoggerStd.edi_txt and QWLoggerError.edi_err are setReadOnly(True) (QWLoggerStd.py:279, QWLoggerError.py:63)."""
    open_gui(page, server)
    page.click('#expert_transitions summary')
    page.click('#transition_buttons button[data-transition="configure"]')   # refused: an ERROR line
    txt, err = page.locator(P('QWLoggerStd.edi_txt')), page.locator(P('QWLoggerError.edi_err'))
    expect(err).to_contain_text("not permitted in state 'reset'", timeout=T)
    expect(txt).to_contain_text('ERROR', timeout=T)
    for loc in (txt, err):
        not_editable(loc)
        before = loc.inner_text()
        loc.click()
        page.keyboard.type('typed text')
        page.keyboard.press('Backspace')
        assert loc.inner_text() == before
        assert 'typed text' not in loc.inner_text()


# ---------------- CustomQComboBox on box_state ----------------

def test_box_state_ignores_arrow_keys_and_wheel(page, server):
    """QWCustomQComboBox.keyPressEvent ignores Key_Up / Key_Down and wheelEvent ignores the wheel, so the
    target state cannot change by accident.  The control: a plain <select> in the same page does change."""
    open_gui(page, server, height=500)          # short window: the page can scroll
    sent = posts(page)
    select(page)
    page.click(P('QWPopupTableCheck.but_apply'))
    expect_state(page, 'allocated')
    box = page.locator(P('CGWMainControl.box_state'))
    expect(box).to_be_enabled()
    page.evaluate('''() => { const s = document.createElement('select'); s.id = 'plain_control';
        s.innerHTML = '<option>Select</option><option>RESET</option><option>CONFIGURED</option>';
        document.getElementById('panel_control').appendChild(s); }''')
    n0 = len(sent)
    for k in ('ArrowDown', 'ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight'):
        box.focus()
        page.keyboard.press(k)
    page.locator('#plain_control').focus()
    page.keyboard.press('ArrowDown')
    page.wait_for_timeout(300)
    assert box.input_value() == 'Select'
    assert page.locator('#plain_control').input_value() == 'RESET'      # Chromium moves a plain select
    assert box.get_attribute('data-ignored-key') == 'ArrowRight'
    page.evaluate('''() => { const d = document.createElement('div'); d.style.height = '2000px'; document.body.appendChild(d); }''')
    moved = []
    for _ in range(2):
        box.scroll_into_view_if_needed()
        bb = box.bounding_box()
        page.mouse.move(bb['x'] + bb['width'] / 2, bb['y'] + bb['height'] / 2)
        y0 = page.evaluate('scrollY')
        page.mouse.wheel(0, 150)
        page.wait_for_timeout(300)
        moved.append(page.evaluate('scrollY') - y0)
    assert box.input_value() == 'Select'
    assert int(box.get_attribute('data-wheel') or 0) >= 2
    assert all(m > 0 for m in moved), moved      # the wheel went on to the page, as event.ignore() passes it up
    assert [p for p, _ in sent[n0:]] == [], sent[n0:]
    assert server.get('/api/status')['state'] == 'allocated'
    box.select_option('CONFIGURED')             # choosing an item still works
    expect_state(page, 'configured')


# ---------------- Qt mnemonics ----------------

def test_alt_a_applies_select_window(page, server):
    """QWPopupTableCheck '&Apply' (QWPopupTableCheck.py:55): Alt+A clicks Apply while the Select window is open,
    and does nothing when it is not."""
    open_gui(page, server)
    sent = posts(page)
    alt_key(page, 'a')                          # reset: no Select window, no Apply
    page.wait_for_timeout(300)
    assert not [p for p, _ in sent if p == 'api/platform']
    select(page)
    apply = page.locator(P('QWPopupTableCheck.but_apply.mnemonic'))
    expect(apply.locator('u')).to_have_text('A')
    alt_key(page, 'a')
    expect_state(page, 'allocated')
    assert [p for p, _ in sent].count('api/platform') == 1
    assert apply.get_attribute('accesskey') == 'a'


def test_popup_edit_text_mnemonics(page, cfg_server):
    """QWPopupEditText '&Cancel' / '&Apply' (QWPopupEditText.py:53-54) in the long-value popup of the config
    tree.  The Select window's '&Apply' is open at the same time: Alt+A goes to the popup (the active window)."""
    open_gui(page, cfg_server, height=1000)
    page.wait_for_selector('body[data-cfg-editor="1"]', timeout=T)
    select(page)                                # unallocated: Select window (with its own Alt+A) visible
    page.click(P('CGWMainConfiguration.but_edit'))
    expect(page.locator('#cfg_select')).to_be_visible(timeout=T)
    for but, pop, val in (('CGWConfigSelect.but_type', 'CGWConfigSelect.on_but_type@1', 'BEAM'),
                          ('CGWConfigSelect.but_dev', 'CGWConfigSelect.on_but_dev@1', 'treetest_0')):
        page.click(P(but))
        page.locator(P(pop)).locator('button[data-value="%s"]' % val).click()
    page.click(P('QWDialog.but_apply'))
    expect(page.locator('#cfg_editor')).to_be_visible(timeout=T)
    page.click(P('CGWConfigEditor.but_expn'))
    lng = page.locator('#cfg_ed_tree .cfg-val[data-path="user.long"]')
    expect(lng).to_have_text('10 11 12 13 14 ...', timeout=T)
    popup, ta = page.locator('#cfg_popup_text'), page.locator(P('QWEditText.edi_text'))
    cancel = page.locator('[data-parity~="QWPopupEditText.but_cancel"][data-accesskey="c"]')
    apply = page.locator('[data-parity~="QWPopupEditText.but_apply"][data-accesskey="a"]')
    full = ' '.join(str(i) for i in range(10, 22))
    lng.click()
    expect(popup).to_be_visible(timeout=T)
    ta.fill('77 ' + full)
    alt_key(page, 'c')                          # &Cancel
    expect(popup).to_be_hidden(timeout=T)
    expect(lng).to_have_text('10 11 12 13 14 ...')
    assert cancel.count() == 1
    lng.click()
    expect(popup).to_be_visible(timeout=T)
    ta.fill(full.replace('10', '60', 1))
    shot(page, 'p05-popup-mnemonics.png')
    alt_key(page, 'a')                          # &Apply of the popup, not of the Select window
    expect(popup).to_be_hidden(timeout=T)
    expect(lng).to_have_text('60 11 12 13 14 ...', timeout=T)
    assert apply.count() == 1
    page.wait_for_timeout(300)
    assert cfg_server.get('/api/status')['state'] == 'unallocated'      # the Select window's Apply did not fire
    expect(page.locator('#select_window')).to_be_visible()


# ---------------- config tree: key and list-index cells ----------------

def test_config_tree_key_and_index_cells_not_editable(page, cfg_server):
    """CGWConfigEditorTree key items QStandardItem(k) (:167) and list-index items QStandardItem('%d' % i)
    (:181) are setEditable(False): shown, not editable; a click opens no editor."""
    open_gui(page, cfg_server, height=1000)
    page.wait_for_selector('body[data-cfg-editor="1"]', timeout=T)
    page.click(P('CGWMainConfiguration.but_edit'))
    for but, pop, val in (('CGWConfigSelect.but_type', 'CGWConfigSelect.on_but_type@1', 'BEAM'),
                          ('CGWConfigSelect.but_dev', 'CGWConfigSelect.on_but_dev@1', 'treetest_0')):
        page.click(P(but))
        page.locator(P(pop)).locator('button[data-value="%s"]' % val).click()
    page.click(P('QWDialog.but_apply'))
    expect(page.locator('#cfg_editor')).to_be_visible(timeout=T)
    page.click(P('CGWConfigEditor.but_expn'))
    keys = page.locator('#cfg_ed_tree ' + P('CGWConfigEditorTree.tree_model_from_dict@1'))
    idx = page.locator('#cfg_ed_tree ' + P('CGWConfigEditorTree.tree_model_from_dict@2'))
    expect(idx).to_have_count(2, timeout=T)                     # expert.chan: a list of two dicts
    assert [i.inner_text().split()[0] for i in idx.all()] == ['0', '1']
    assert keys.count() > 5
    for loc in [keys.nth(i) for i in range(keys.count())] + idx.all():
        if not loc.is_visible():
            continue
        not_editable(loc)
    for loc in (keys.first, idx.first):
        text = loc.inner_text()
        loc.click()
        page.wait_for_timeout(200)
        assert page.locator('#cfg_ed_tree input.cfg-inline').count() == 0
        assert not page.locator('#cfg_popup_text').is_visible() and not page.locator('#cfg_pop_enum').is_visible()
        assert loc.inner_text() == text
    shot(page, 'p06-config-tree-keys.png')


# ---------------- CGWMainTabs / CGWMainTabUser ----------------

def test_tab_bar_user_and_expert(page, server):
    """CGWMainTabs: tab bar User | Expert; gui_selector shows CGWMainTabUser or CGWMainTabExpert.
    Opens on Expert, as CGWMain.py:79 builds the Expert tab."""
    errors = open_gui(page, server)
    user, expert = page.locator(P('CGWMainTabs.tab_bar.user')), page.locator(P('CGWMainTabs.tab_bar.expert'))
    expect(expert).to_have_attribute('aria-selected', 'true')
    expect(page.locator(P('CGWMainPartition.but_select'))).to_be_visible()
    expect(page.locator(P('CGWMainTabUser.but_play'))).to_be_hidden()
    user.click()
    expect(user).to_have_attribute('aria-selected', 'true')
    expect(expert).to_have_attribute('aria-selected', 'false')
    expect(page.locator(P('CGWMainTabUser.but_play'))).to_be_visible()
    expect(page.locator(P('CGWMainTabUser.but_record'))).to_be_visible()
    expect(page.locator(P('CGWMainPartition.but_select'))).to_be_hidden()
    expect(page.locator(P('CGWMainControl.box_state'))).to_be_hidden()
    expect(page.locator(P('CGWMainConfiguration.but_type'))).to_be_visible()   # outside the tabs
    shot(page, 'p07-user-tab.png')
    expert.click()
    expect(expert).to_have_attribute('aria-selected', 'true')
    expect(page.locator(P('CGWMainPartition.but_select'))).to_be_visible()
    expect(page.locator(P('CGWMainTabUser.but_play'))).to_be_hidden()
    assert errors == []


def test_user_tab_play_stop_record(page, server):
    """CGWMainTabUser: Play -> running (pause icon while running) -> Play -> paused; Stop (shown only in
    starting / paused / running) -> configured; Record toggles recording where CGWMainTabUser.py:107 allows."""
    errors = open_gui(page, server)
    sent = posts(page)
    select(page)
    page.click(P('QWPopupTableCheck.but_apply'))
    expect_state(page, 'allocated')
    page.click(P('CGWMainTabs.tab_bar.user'))
    play, stop, rec = (page.locator(P(x)) for x in ('CGWMainTabUser.but_play', 'CGWMainTabUser.but_stop',
                                                     'CGWMainTabUser.but_record'))
    us = page.locator('#user_state')
    expect(play).to_have_attribute('data-icon', 'start')
    expect(stop).to_be_hidden()
    expect(rec).to_be_enabled()
    rec.click()
    expect(rec).to_have_attribute('aria-pressed', 'true', timeout=T)
    assert server.get('/api/status')['recording'] is True
    play.click()
    expect(us).to_have_text(re.compile('^RUNNING'), timeout=T)
    expect(play).to_have_attribute('data-icon', 'pause', timeout=T)
    expect(stop).to_be_visible()
    expect(rec).to_be_disabled()
    shot(page, 'p08-user-running.png')
    play.click()
    expect(us).to_have_text(re.compile('^PAUSED'), timeout=T)
    expect(play).to_have_attribute('data-icon', 'start', timeout=T)
    expect(stop).to_be_visible()
    stop.click()
    expect(us).to_have_text(re.compile('^CONFIGURED'), timeout=T)
    expect(stop).to_be_hidden()
    expect(rec).to_be_enabled()
    rec.click()
    expect(rec).to_have_attribute('aria-pressed', 'false', timeout=T)
    bodies = [b for p, b in sent if p == 'api/state']
    assert bodies == ['{"state":"running"}', '{"state":"paused"}', '{"state":"configured"}'], bodies
    assert server.get('/api/status')['state'] == 'configured'
    assert errors == []
