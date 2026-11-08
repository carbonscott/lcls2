"""Headless-browser tests of the web config DB editor (static/ext/configeditor.js + configdb_api.py),
the web copy of control_gui CGWMainConfiguration (Type, Edit, save confirmation), CGWConfigSelect in
QWDialog, CGWConfigEditor, CGWConfigEditorTree, CGWConfigEditorText and QWPopupEditText/QWEditText.

The server runs in --emulate mode with --configdb-url pointing at the campaign's config DB stand-in
(psdaq.sim.configdb_server) on 127.0.0.1, seeded by configeditor_harness.py.  Elements are found by
their data-parity row id; ROWS says which test proves which row (mapping.d/configeditor.json is
checked against it by test_mapping_fragment_matches_rows).

Run with tests/run_webgui_tests.sh -k configeditor.
"""

import json
import pathlib

import pytest

pytest.importorskip('playwright')
from playwright.sync_api import expect  # noqa: E402

from webgui_harness import ServerProc, SHOTS  # noqa: E402
from configeditor_harness import ConfigDbProc, seeded_store, daq_script, SERNO  # noqa: E402

T = 15000   # ms, per UI expectation
FRAGMENT = pathlib.Path(__file__).resolve().parents[1] / 'parity' / 'mapping.d' / 'configeditor.json'

# test -> the parity rows it proves
ROWS = {
    'test_main_type_button_and_alias_popup': ['CGWMainConfiguration.but_type', 'CGWMainConfiguration.on_but_type@1'],
    'test_edit_opens_select_dialog': ['CGWMainConfiguration.but_edit', 'CGWConfigSelect.but_type',
                                      'CGWConfigSelect.on_but_type@1', 'CGWConfigSelect.but_dev',
                                      'CGWConfigSelect.on_but_dev@1', 'QWDialog.but_apply'],
    'test_select_dialog_cancel': ['QWDialog.but_cancel'],
    'test_tree_expand_collapse': ['CGWConfigEditorTree.expanded', 'CGWConfigEditorTree.collapsed',
                                  'CGWConfigEditor.but_expn'],
    'test_tree_scalar_edit_and_radix': ['CGWConfigEditorTree.tree_model_from_dict@4.edit',
                                        'CGWConfigEditorTree.tree_model_from_dict@4.check',
                                        'CGWConfigEditorTree.clicked'],
    'test_tree_list_and_long_value_popup': ['CGWConfigEditorTree.tree_model_from_dict@3.edit', 'QWEditText.edi_text',
                                            'QWPopupEditText.but_cancel', 'QWPopupEditText.but_apply'],
    'test_tree_enum_popup': ['CGWConfigEditorTree.start_special_editor@1'],
    'test_text_editor_and_type_switch': ['CGWConfigEditor.box_type', 'CGWConfigEditorText.edi_txt'],
    'test_apply_confirm_cancel_and_ok': ['CGWConfigEditor.but_apply', 'CGWMainConfiguration.save_dictj_in_db@1'],
    'test_select_other_and_close': ['CGWConfigEditor.but_select', 'CGWConfigEditor.but_close'],
    'test_more_help_save_load': ['CGWConfigEditor.box_more.help', 'CGWConfigEditor.help_box',
                                 'CGWConfigEditor.box_more.save', 'CGWConfigEditor.select_ofname@1',
                                 'CGWConfigEditor.box_more.load', 'CGWConfigEditor.select_ifname@1'],
    'test_long_value_popup_more_load_save': ['QWEditText.box_more.load', 'QWEditText.box_more.save',
                                             'QWEditText.select_ifname@1', 'QWEditText.select_ofname@1'],
    'test_serial_number_checkbox': ['CGWConfigEditor.cbx_serno'],
}


def P(pid):
    return '[data-parity~="%s"]' % pid


@pytest.fixture(scope='session')
def browser_type_launch_args(browser_type_launch_args):
    return {**browser_type_launch_args, 'headless': True, 'args': ['--no-sandbox']}


@pytest.fixture
def cfgdb(tmp_path):
    db = ConfigDbProc(seeded_store(tmp_path)).start()
    yield db
    db.stop()


@pytest.fixture
def web(cfgdb):
    s = ServerProc(['--emulate', '--configdb-url', cfgdb.url]).start()
    yield s
    s.stop()


@pytest.fixture
def gui(page, web, request, record_property):
    """The main window, loaded; fails the test on any JavaScript error. Records the test's parity rows."""
    for rid in ROWS.get(request.node.originalname, []):
        record_property('parity', rid)
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.set_viewport_size({'width': 1400, 'height': 1000})
    page.goto(web.url)
    page.wait_for_selector('body[data-ready="1"]', timeout=T)
    page.wait_for_selector('body[data-cfg-editor="1"]', timeout=T)
    yield page
    assert errors == [], 'JavaScript errors: %s' % errors


def shot(page, name):
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / name), full_page=False)


def popup_items(pop):
    return [b.get_attribute('data-value') for b in pop.locator('button').all()]


def choose(page, button, popup, value, expect_items=None):
    page.click(P(button))
    pop = page.locator(P(popup))
    expect(pop).to_be_visible(timeout=T)
    if expect_items is not None:
        assert popup_items(pop) == expect_items
    pop.locator('button[data-value="%s"]' % value).click()
    expect(pop).to_be_hidden(timeout=T)


def open_editor(page, alias='BEAM', device='fakecam_0'):
    page.click(P('CGWMainConfiguration.but_edit'))
    expect(page.locator('#cfg_select')).to_be_visible(timeout=T)
    choose(page, 'CGWConfigSelect.but_type', 'CGWConfigSelect.on_but_type@1', alias)
    choose(page, 'CGWConfigSelect.but_dev', 'CGWConfigSelect.on_but_dev@1', device)
    page.click(P('QWDialog.but_apply'))
    expect(page.locator('#cfg_editor')).to_be_visible(timeout=T)
    expect(page.locator('#cfg_ed_title')).to_have_text('Config Editor for %s %s' % (alias, device), timeout=T)


def leaf(page, path):
    return page.locator('#cfg_ed_tree .cfg-val[data-path="%s"]' % path)


def expand_all(page):
    b = page.locator(P('CGWConfigEditor.but_expn'))
    expect(b).to_have_text('Expand ▼')
    b.click()
    expect(b).to_have_text('Collapse ▲')


def edit_inline(page, path, value):
    leaf(page, path).click()
    inp = page.locator('#cfg_ed_tree input.cfg-inline[data-path="%s"]' % path)
    expect(inp).to_be_visible(timeout=T)
    inp.fill(value)
    inp.press('Enter')
    expect(leaf(page, path)).to_have_text(value, timeout=T)


def apply_and_confirm(page):
    page.click(P('CGWConfigEditor.but_apply'))
    expect(page.locator(P('CGWMainConfiguration.save_dictj_in_db@1'))).to_be_visible(timeout=T)
    page.click('#cfg_cf_ok')
    expect(page.locator('#cfg_ed_status')).to_contain_text('new key', timeout=T)
    return page.locator('#cfg_ed_status').inner_text()


def db_config(web, alias, device):
    j = web.get('/api/configdb/config?alias=%s&device=%s' % (alias, device))
    assert j['ok'], j
    return json.loads(j['config_json'])


# ---------------- CGWMainConfiguration ----------------

def test_main_type_button_and_alias_popup(gui):
    page = gui
    but = page.locator(P('CGWMainConfiguration.but_type'))
    expect(but).to_be_enabled()                          # reset (CGWMainConfiguration.py:93)
    expect(but).to_have_text('BEAM ▼', timeout=T)  # the emulator's config alias
    but.click()
    pop = page.locator(P('CGWMainConfiguration.on_but_type@1'))
    expect(pop).to_be_visible(timeout=T)
    assert sorted(popup_items(pop)) == ['BEAM', 'NOBEAM']
    pop.locator('button[data-value="NOBEAM"]').click()  # -> setConfig('NOBEAM') (:163)
    expect(but).to_have_text('NOBEAM ▼', timeout=T)
    expect(page.locator('#edi_txt')).to_contain_text('setConfig(NOBEAM)', timeout=T)


def test_edit_opens_select_dialog(gui):
    page = gui
    page.click(P('CGWMainConfiguration.but_edit'))
    dlg = page.locator('#cfg_select')
    expect(dlg).to_be_visible(timeout=T)
    expect(dlg.locator('.cfg-wtitle')).to_have_text('Select config Type & Detector')
    typ, dev, edit = (page.locator(P(x)) for x in ('CGWConfigSelect.but_type', 'CGWConfigSelect.but_dev',
                                                   'QWDialog.but_apply'))
    expect(typ).to_have_text('BEAM ▼')              # type_def = main but_type text (:218)
    expect(dev).to_have_text('Select ▼')
    expect(dev).to_be_enabled()                          # a type is selected (CGWConfigSelect.py:91-93)
    expect(edit).to_have_text('✓ Edit')             # w.but_apply.setText('Edit') (:221)
    expect(edit).to_be_disabled()                        # (:222)
    # aliases from the config DB, sorted (popup_select_item_from_list do_sort=True)
    choose(page, 'CGWConfigSelect.but_type', 'CGWConfigSelect.on_but_type@1', 'NOBEAM', ['BEAM', 'NOBEAM'])
    expect(typ).to_have_text('NOBEAM ▼')
    page.click(P('CGWConfigSelect.but_dev'))             # NOBEAM has no devices: warning, no popup (:180-182)
    expect(page.locator('#cfg_sel_msg')).to_contain_text('list_of_device_names IS EMPTY', timeout=T)
    expect(page.locator(P('CGWConfigSelect.on_but_dev@1'))).to_be_hidden()
    choose(page, 'CGWConfigSelect.but_type', 'CGWConfigSelect.on_but_type@1', 'BEAM')
    expect(dev).to_have_text('Select ▼')            # a new type resets the device (:138-140)
    choose(page, 'CGWConfigSelect.but_dev', 'CGWConfigSelect.on_but_dev@1', 'fakecam_0',
           ['fakecam_0', 'tmoteb_0', 'treetest_0'])
    expect(dev).to_have_text('fakecam_0 ▼')
    expect(edit).to_be_enabled()
    shot(page, 'cfg-01-select-dialog.png')
    edit.click()
    expect(dlg).to_be_hidden(timeout=T)
    expect(page.locator('#cfg_editor')).to_be_visible(timeout=T)
    expect(page.locator('#cfg_ed_title')).to_have_text('Config Editor for BEAM fakecam_0')
    shot(page, 'cfg-02-editor-open.png')
    eb, wb = page.locator(P('CGWMainConfiguration.but_edit')).bounding_box(), page.locator('#cfg_editor').bounding_box()
    assert eb['x'] + eb['width'] <= wb['x'], (eb, wb)    # the editor opens beside the main window, not over it
    page.click(P('CGWMainConfiguration.but_edit'))       # editor open: Edit closes it (:277-279)
    expect(page.locator('#cfg_editor')).to_be_hidden(timeout=T)


def test_select_dialog_cancel(gui):
    page = gui
    page.click(P('CGWMainConfiguration.but_edit'))
    expect(page.locator('#cfg_select')).to_be_visible(timeout=T)
    choose(page, 'CGWConfigSelect.but_dev', 'CGWConfigSelect.on_but_dev@1', 'fakecam_0')
    page.click(P('QWDialog.but_cancel'))                 # reject -> None (CGWMainConfiguration.py:229)
    expect(page.locator('#cfg_select')).to_be_hidden(timeout=T)
    expect(page.locator('#cfg_editor')).to_be_hidden()
    page.click(P('CGWMainConfiguration.but_edit'))       # Escape rejects too
    expect(page.locator('#cfg_select')).to_be_visible(timeout=T)
    page.keyboard.press('Escape')
    expect(page.locator('#cfg_select')).to_be_hidden(timeout=T)
    expect(page.locator('#cfg_editor')).to_be_hidden()


# ---------------- CGWConfigEditorTree ----------------

def test_tree_expand_collapse(gui):
    page = gui
    open_editor(page)
    u = '#cfg_ed_tree > ul > li.cfg-node[data-key="user"]'
    s = u + ' > ul > li.cfg-node[data-key="sim_seed"]'
    user, seed = page.locator(u), page.locator(s)
    expect(user).to_have_attribute('data-state', 'collapsed')   # QTreeView starts collapsed
    expect(leaf(page, 'user.sim_seed')).to_be_hidden()
    page.click(u + ' > ' + P('CGWConfigEditorTree.expanded'))
    expect(user).to_have_attribute('data-state', 'expanded')
    expect(seed).to_be_visible()
    expect(leaf(page, 'user.sim_seed')).to_be_hidden()          # its own item is still collapsed
    page.click(s + ' > ' + P('CGWConfigEditorTree.expanded'))
    expect(leaf(page, 'user.sim_seed')).to_have_text('4660')
    page.click(u + ' > ' + P('CGWConfigEditorTree.collapsed'))
    expect(user).to_have_attribute('data-state', 'collapsed')
    expect(seed).to_be_hidden()
    # but_expn: expandAll / collapseAll and its label (CGWConfigEditor.py:424-431)
    expand_all(page)
    expect(leaf(page, 'expert.sim_length')).to_have_text('1024')
    expect(page.locator('#cfg_ed_tree li.cfg-node[data-state="collapsed"]')).to_have_count(0)
    shot(page, 'cfg-03-tree-expanded.png')
    page.click(P('CGWConfigEditor.but_expn'))
    expect(page.locator(P('CGWConfigEditor.but_expn'))).to_have_text('Expand ▼')
    expect(page.locator('#cfg_ed_tree li.cfg-node[data-state="expanded"]')).to_have_count(0)
    page.select_option(P('CGWConfigEditor.box_type'), 'Text')   # only shown with the Tree editor (:411)
    expect(page.locator(P('CGWConfigEditor.but_expn'))).to_be_hidden(timeout=T)
    page.select_option(P('CGWConfigEditor.box_type'), 'Tree')
    expect(page.locator(P('CGWConfigEditor.but_expn'))).to_be_visible(timeout=T)


def test_tree_scalar_edit_and_radix(gui, web):
    page = gui
    open_editor(page)
    expand_all(page)
    v = leaf(page, 'user.sim_seed')
    expect(v).to_have_text('4660')
    cb = page.locator(P('CGWConfigEditorTree.tree_model_from_dict@4.check') + '[data-path="user.sim_seed"]')
    for shown in ('0x1234', '0o11064', '0b1001000110100', '4660'):   # DEC -> HEX -> OCT -> BIN -> DEC
        cb.click()
        expect(v).to_have_text(shown)
    help_ro = leaf(page, 'help:RO')                                    # :RO value: disabled, not editable
    expect(help_ro).to_have_attribute('aria-disabled', 'true')
    help_ro.click()
    expect(page.locator('#cfg_ed_tree input.cfg-inline')).to_have_count(0)
    edit_inline(page, 'user.sim_seed', '4661')                         # click -> in-line editor (:382)
    expect(v).to_have_class('cfg-val changed')
    v.click()                                                          # Escape cancels an in-line edit
    inp = page.locator('#cfg_ed_tree input.cfg-inline')
    inp.fill('999')
    inp.press('Escape')
    expect(v).to_have_text('4661')
    cb.click()                                                         # saved in HEX: still the number
    expect(v).to_have_text('0x1235')
    shot(page, 'cfg-04-tree-edit.png')
    apply_and_confirm(page)
    assert db_config(web, 'BEAM', 'fakecam_0')['user']['sim_seed'] == 4661


def test_tree_list_and_long_value_popup(gui, web):
    page = gui
    open_editor(page, device='treetest_0')
    expand_all(page)
    edit_inline(page, 'user.short', '1 2 4')                          # data list, not trimmed: in line
    lng = leaf(page, 'user.long')
    expect(lng).to_have_text('10 11 12 13 14 ...')
    full = ' '.join(str(i) for i in range(10, 22))
    pop, ta = page.locator('#cfg_popup_text'), page.locator(P('QWEditText.edi_text'))
    lng.click()                                                        # trimmed: QWPopupEditText (:420-431)
    expect(pop).to_be_visible(timeout=T)
    expect(ta).to_have_value(full)
    ta.fill('77 ' + full)
    page.click(P('QWPopupEditText.but_cancel'))                        # reject: unchanged
    expect(pop).to_be_hidden(timeout=T)
    expect(lng).to_have_text('10 11 12 13 14 ...')
    lng.click()
    expect(ta).to_have_value(full)
    ta.fill(full.replace('10', '50', 1))
    shot(page, 'cfg-05-long-value-popup.png')
    page.click(P('QWPopupEditText.but_apply'))                         # set_item_for_list(item, txt_new)
    expect(pop).to_be_hidden(timeout=T)
    expect(lng).to_have_text('50 11 12 13 14 ...')
    status = apply_and_confirm(page)
    assert 'NOT applied' not in status
    c = db_config(web, 'BEAM', 'treetest_0')
    assert c['user']['short'] == [1, 2, 4] and c['user']['long'] == [50] + list(range(11, 22))
    assert c['expert']['big'] == 2 ** 63 + 5                           # untouched 64-bit value survives


def test_tree_enum_popup(gui, web):
    page = gui
    open_editor(page, device='treetest_0')
    expand_all(page)
    mode = leaf(page, 'user.mode')
    expect(mode).to_have_text('Off')
    pop = page.locator(P('CGWConfigEditorTree.start_special_editor@1'))
    mode.click()
    expect(pop).to_be_visible(timeout=T)
    enum = db_config(web, 'BEAM', 'treetest_0')[':types:'][':enum:']['modeEnum']
    assert popup_items(pop) == list(enum)                              # do_sort=False (:413): the DB's order
    page.keyboard.press('Escape')                                      # None: unchanged
    expect(pop).to_be_hidden(timeout=T)
    expect(mode).to_have_text('Off')
    mode.click()
    pop.locator('button[data-value="Slow"]').click()
    expect(mode).to_have_text('Slow')
    apply_and_confirm(page)
    c = db_config(web, 'BEAM', 'treetest_0')
    assert c['user']['mode'] == 1 and c['user']['enable'] == 1


# ---------------- CGWConfigEditor ----------------

def test_text_editor_and_type_switch(gui, web):
    page = gui
    open_editor(page)
    box, txt = page.locator(P('CGWConfigEditor.box_type')), page.locator(P('CGWConfigEditorText.edi_txt'))
    expect(box).to_have_value('Tree')                                  # setCurrentIndex(1) (:76)
    expect(txt).to_be_hidden()
    box.select_option('Text')
    expect(txt).to_be_visible(timeout=T)
    expect(page.locator('#cfg_ed_tree')).to_be_hidden()
    text = txt.input_value()
    assert '"detName:RO": "fakecam_0"' in text and '"sim_seed": 4660' in text and text.startswith('{\n    "')
    txt.fill(text.replace('"sim_seed": 4660', '"sim_seed": 4242'))
    box.select_option('Tree')
    expect(page.locator('#cfg_ed_tree')).to_be_visible(timeout=T)
    expand_all(page)
    expect(leaf(page, 'user.sim_seed')).to_have_text('4242')          # carried across the switch
    box.select_option('Text')
    expect(txt).to_be_visible(timeout=T)
    assert '"sim_seed": 4242' in txt.input_value()
    good = txt.input_value()
    txt.fill(good[:-3])                                                # broken JSON: no switch
    box.select_option('Tree')
    expect(page.locator('#cfg_ed_status')).to_contain_text('cannot switch to Tree', timeout=T)
    expect(box).to_have_value('Text')
    txt.fill(good)
    shot(page, 'cfg-06-text-editor.png')
    apply_and_confirm(page)                                            # Text editor's get_content: json.loads
    assert db_config(web, 'BEAM', 'fakecam_0')['user']['sim_seed'] == 4242


def test_apply_confirm_cancel_and_ok(gui, web):
    page = gui
    open_editor(page)
    expand_all(page)
    edit_inline(page, 'expert.sim_length', '2048')
    page.click(P('CGWConfigEditor.but_apply'))
    dlg = page.locator(P('CGWMainConfiguration.save_dictj_in_db@1'))
    expect(dlg).to_be_visible(timeout=T)
    expect(dlg).to_contain_text('Save changes in configuration DB')
    expect(dlg.locator('.cfg-wtitle')).to_have_text('Confirm or cancel')
    shot(page, 'cfg-07-confirm.png')
    page.click('#cfg_cf_cancel')
    expect(dlg).to_be_hidden(timeout=T)
    expect(page.locator('#edi_txt')).to_contain_text('Saving of configuration in DB is cancelled...', timeout=T)
    assert db_config(web, 'BEAM', 'fakecam_0')['expert']['sim_length'] == 1024
    status = apply_and_confirm(page)
    assert 'saved BEAM/fakecam_0 in tst: new key' in status
    assert db_config(web, 'BEAM', 'fakecam_0')['expert']['sim_length'] == 2048
    expect(page.locator('#edi_txt')).to_contain_text('configdb: saved BEAM/fakecam_0', timeout=T)
    expect(page.locator('#cfg_editor')).to_be_visible()                # the editor stays open after Apply


def test_select_other_and_close(gui):
    page = gui
    open_editor(page)
    expand_all(page)
    edit_inline(page, 'user.sim_seed', '1')                            # never applied
    page.click(P('CGWConfigEditor.but_select'))
    expect(page.locator('#cfg_select')).to_be_visible(timeout=T)
    choose(page, 'CGWConfigSelect.but_type', 'CGWConfigSelect.on_but_type@1', 'BEAM')
    choose(page, 'CGWConfigSelect.but_dev', 'CGWConfigSelect.on_but_dev@1', 'treetest_0')
    page.click(P('QWDialog.but_apply'))
    expect(page.locator('#cfg_ed_title')).to_have_text('Config Editor for BEAM treetest_0', timeout=T)
    expect(page.locator('#cfg_ed_tree li.cfg-node[data-key="user"] li.cfg-node[data-key="mode"]')).to_have_count(1)
    page.click(P('CGWConfigEditor.but_select'))                        # Cancel keeps the current one
    page.click(P('QWDialog.but_cancel'))
    expect(page.locator('#cfg_ed_title')).to_have_text('Config Editor for BEAM treetest_0')
    page.click(P('CGWConfigEditor.but_close'))
    expect(page.locator('#cfg_editor')).to_be_hidden(timeout=T)
    open_editor(page)                                                  # the unapplied edit is gone
    expand_all(page)
    expect(leaf(page, 'user.sim_seed')).to_have_text('4660')


def test_more_help_save_load(gui, tmp_path):
    page = gui
    open_editor(page)
    more = page.locator('#cfg_ed_more')
    more.select_option('Help')
    hb = page.locator(P('CGWConfigEditor.help_box'))
    expect(hb).to_be_visible(timeout=T)
    expect(hb).to_contain_text('Expand/Collapse button - expands/collapse entire dictionary content')
    expect(more).to_have_value('More')                                 # setCurrentIndex(0) (:384)
    shot(page, 'cfg-08-help.png')
    page.click('#cfg_help_ok')
    expect(hb).to_be_hidden(timeout=T)
    expand_all(page)
    edit_inline(page, 'user.sim_seed', '777')
    # Save: file dialog, then the editor content as str_json
    more.select_option('Save')
    sd = page.locator(P('CGWConfigEditor.select_ofname@1'))
    expect(sd).to_be_visible(timeout=T)
    expect(sd.locator('.cfg-wtitle')).to_have_text('Select the file to save json')
    expect(sd.locator('.cfg-fname')).to_have_value('test.json')       # ofname_json default (:62)
    with page.expect_download(timeout=T) as dl:
        sd.locator('.cfg-fok').click()
    assert dl.value.suggested_filename == 'test.json'
    saved = json.loads(pathlib.Path(dl.value.path()).read_text())
    assert saved['user']['sim_seed'] == 777 and saved['detName:RO'] == 'fakecam_0'
    more.select_option('Save')
    sd.locator('.cfg-fcancel').click()
    expect(page.locator('#edi_txt')).to_contain_text('Saving is cancelled', timeout=T)
    # Load: file dialog, then set_content
    saved['user']['sim_seed'] = 31337
    f = tmp_path / 'loaded.json'
    f.write_text(json.dumps(saved))
    more.select_option('Load')
    od = page.locator(P('CGWConfigEditor.select_ifname@1'))
    expect(od).to_be_visible(timeout=T)
    expect(od.locator('.cfg-wtitle')).to_have_text('Select the file to load json')
    od.locator('.cfg-file').set_input_files(str(f))
    od.locator('.cfg-fok').click()
    expect(od).to_be_hidden(timeout=T)
    expand_all(page)
    expect(leaf(page, 'user.sim_seed')).to_have_text('31337', timeout=T)
    expect(page.locator('#edi_txt')).to_contain_text('Input file: loaded.json', timeout=T)
    more.select_option('Load')
    od.locator('.cfg-fcancel').click()
    expect(page.locator('#edi_txt')).to_contain_text('Loading is cancelled', timeout=T)


def test_long_value_popup_more_load_save(gui, tmp_path):
    page = gui
    open_editor(page, device='treetest_0')
    expand_all(page)
    leaf(page, 'user.long').click()
    ta = page.locator(P('QWEditText.edi_text'))
    expect(ta).to_be_visible(timeout=T)
    full = ta.input_value()
    more = page.locator('#cfg_pt_more')
    sd = page.locator(P('QWEditText.select_ofname@1'))
    more.select_option('Save')
    expect(sd).to_be_visible(timeout=T)
    expect(sd.locator('.cfg-wtitle')).to_have_text('Select the file to save')
    expect(sd.locator('.cfg-fname')).to_have_value('test.txt')        # ofname default (QWEditText.py:49)
    with page.expect_download(timeout=T) as dl:
        sd.locator('.cfg-fok').click()
    assert pathlib.Path(dl.value.path()).read_text() == full
    more.select_option('Save')                                         # .npy: np.save of the values
    sd.locator('.cfg-fname').fill('arr.npy')
    with page.expect_download(timeout=T) as dl:
        sd.locator('.cfg-fok').click()
    npy = tmp_path / 'arr.npy'
    dl.value.save_as(str(npy))
    assert npy.read_bytes()[:6] == b'\x93NUMPY'
    od = page.locator(P('QWEditText.select_ifname@1'))
    txt = tmp_path / 'values.txt'
    txt.write_text('1 2 3 4 5 6 7 8 9 10 11 12')
    more.select_option('Load')
    expect(od).to_be_visible(timeout=T)
    od.locator('.cfg-file').set_input_files(str(txt))
    od.locator('.cfg-fok').click()
    expect(ta).to_have_value('1 2 3 4 5 6 7 8 9 10 11 12', timeout=T)
    more.select_option('Load')                                         # .npy: np.array2string
    od.locator('.cfg-file').set_input_files(str(npy))
    od.locator('.cfg-fok').click()
    page.wait_for_function("document.getElementById('cfg_pt_text').value.indexOf('.') >= 0", timeout=T)
    assert [float(x) for x in ta.input_value().split()] == [float(x) for x in full.split()]
    page.click(P('QWPopupEditText.but_cancel'))
    expect(page.locator('#cfg_popup_text')).to_be_hidden(timeout=T)


def test_serial_number_checkbox(gui):
    page = gui
    open_editor(page)
    cbx = page.locator(P('CGWConfigEditor.cbx_serno'))
    expect(cbx).to_be_disabled()                                       # no serial number in the platform
    expect(cbx).to_have_attribute('title', 'Serial number not available (detector not in partition)')
    page.click(P('CGWConfigEditor.but_close'))
    # a partition whose DRP reported a serial number (connect_info.short_sn_id, CGConfigParameters.get_serno)
    page.evaluate("""sn => { S.status.platform = {drp: {'2': {proc_info: {alias: 'fakecam_0', host: 'localhost', pid: 1},
                                                    active: 1, connect_info: {short_sn_id: sn}}}}; }""", SERNO)
    open_editor(page)
    expect(cbx).to_be_enabled()
    expect(cbx).to_have_attribute('title', 'Detector Serial Number: %s' % SERNO)
    cbx.check()                                                        # det-hutch config merged in (:230-251)
    expect(page.locator('#cfg_ed_status')).to_contain_text('serial number DB', timeout=T)
    expand_all(page)
    expect(leaf(page, 'expert.sim_length')).to_have_text('2048')
    expect(leaf(page, 'user.sim_seed')).to_have_text(str(0x5555))
    expect(leaf(page, 'use_serial_db')).to_have_text('True')
    shot(page, 'cfg-09-serial-number-db.png')
    cbx.uncheck()                                                      # back to the alias config (:259-263)
    expect(page.locator('#cfg_ed_status')).to_contain_text('alias DB', timeout=T)
    expand_all(page)
    expect(leaf(page, 'expert.sim_length')).to_have_text('1024')
    expect(leaf(page, 'use_serial_db')).to_have_text('False')


# ---------------- item 5: the edit is what the DAQ reads at Configure ----------------

def test_edit_seed_read_back_by_daq_config_readers(gui, web, cfgdb):
    """Change fakecam_0 user.sim_seed 0x1234 -> 0x2a2a in the web editor, Apply, then read it back
    with control.py's and the DRP's config readers (configeditor_harness.readback)."""
    page = gui
    before = daq_script('readback', '--url', cfgdb.url)
    assert before['control_py']['user.sim_seed'] == 0x1234 and before['drp']['user.sim_seed'] == 0x1234
    open_editor(page)
    expand_all(page)
    edit_inline(page, 'user.sim_seed', '0x2a2a')
    status = apply_and_confirm(page)
    shot(page, 'cfg-10-readback-saved.png')
    after = daq_script('readback', '--url', cfgdb.url)
    report = {'editor_status': status, 'before': before, 'after': after}
    SHOTS.mkdir(parents=True, exist_ok=True)
    (SHOTS / 'readback.json').write_text(json.dumps(report, indent=1))
    print('READBACK ' + json.dumps(report))
    assert after['control_py']['user.sim_seed'] == 0x2a2a
    assert after['drp']['user.sim_seed'] == 0x2a2a


# ---------------- the parity fragment says what this file proves ----------------

def test_mapping_fragment_matches_rows():
    frag = json.loads(FRAGMENT.read_text())
    # pytest-playwright parametrizes each browser test: the junit name (what check_parity matches) has [chromium]
    want = {rid: {'web': P(rid), 'test': 'test_configeditor_ui.py::%s[chromium]' % t}
            for t, rids in ROWS.items() for rid in rids}
    assert frag == want
    assert len(frag) == 37
    for t in ROWS:
        assert callable(globals().get(t)), t
