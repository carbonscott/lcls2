// Config DB editor: the web copy of control_gui CGWMainConfiguration.on_but_edit (:265), the
// 'Select config Type & Detector' dialog (QWDialog + CGWConfigSelect, CGWMainConfiguration.py:216-236),
// CGWConfigEditor with its Tree (CGWConfigEditorTree) and Text (CGWConfigEditorText) editors, the
// long-value popup (QWPopupEditText + QWEditText) and the save confirmation (save_dictj_in_db :121-143).
// Opened by #but_edit. Talks only to /api/configdb/* (psdaq/webgui/configdb_api.py), which renders
// the tree model and applies the edits with psdaq.configdb.typed_json, as the PyQt editor does.
// Every element that implements a PyQt affordance carries data-parity="<row id>".
(function () {
'use strict';

const byId = (id) => document.getElementById(id);
const escH = (s) => String(s).replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const CH_EXPAND = '▼', CH_SHRINK = '▲';           // CGWConfigEditor.py:41-42
const MORE_OPTIONS = ['More', 'Load', 'Save', 'Help'];      // CGWConfigEditor.py:49
const LIST_MAX_LEN = 5;                                     // CGWConfigEditorTree.py:76
const EDITOR_TIP = 'Configuration editor GUI'               // CGWConfigEditor.py:112-123
  + '\n - Expand/Collapse button - expands/collapse entire dictionary content'
  + '\n - Close button - closes editor window, all modifications'
  + '     since last click on Apply will be lost'
  + '\n - Tree/Text button - switches between editor in "tree" and "text" modes'
  + '\n - More button - selects other editor options'
  + '\n - click on triangle -  expands/collapses particular item'
  + '\n - * (star) to the right of item title indicates that item is compound object'
  + '\n - double-click on value starts in-line editor or compound item editor window'
  + '\n - click on rectangular box in front of INT value swap presentation between'
  + '\n   DEC/HEX/OCT/BIN';
const MORE_TIP = 'More options:\n * Load content from file\n * Save content in file';

// ---------------- styles (injected: index.html and style.css belong to the main window) ----------------
const CSS = `
.cfg-modal { position: fixed; inset: 0; z-index: 50; background: rgba(20,24,30,.25); display: flex; align-items: flex-start; justify-content: center; padding-top: 70px; }
.cfg-modal[hidden], .cfg-window[hidden], .cfg-popup[hidden] { display: none; }
.cfg-dlg { background: #fafafa; border: 1px solid #8a929c; border-radius: 6px; box-shadow: 0 6px 22px rgba(0,0,0,.3); min-width: 340px; max-width: 92vw; padding: .5rem .6rem; }
.cfg-wtitle { font-weight: 600; background: #e4e8ee; margin: -.5rem -.6rem .5rem; padding: .3rem .6rem; border-radius: 6px 6px 0 0; border-bottom: 1px solid #c8ced6; }
/* beside the main window, as CGWMainConfiguration.on_but_edit moves it (:274): main gives up the editor's width */
body.cfg-editor-open main { margin-left: .5rem; margin-right: calc(min(560px, 58vw) + 16px); }
.cfg-window { position: fixed; top: 46px; right: 8px; bottom: 8px; width: min(560px, 58vw); z-index: 40; background: #fff; border: 2px solid var(--accent, #2c6bd6); border-radius: 6px; box-shadow: 0 6px 22px rgba(0,0,0,.25); display: flex; flex-direction: column; }
.cfg-window .cfg-wtitle { margin: 0; border-radius: 4px 4px 0 0; }
.cfg-toolbar { display: flex; gap: .3rem; align-items: center; flex-wrap: wrap; padding: .3rem .4rem; border-bottom: 1px solid #e0e3e8; }
.cfg-toolbar label { font-size: .85rem; display: inline-flex; gap: .25rem; align-items: center; }
.cfg-body { flex: 1; overflow: auto; padding: .3rem .4rem; position: relative; }
.cfg-tree ul { list-style: none; margin: 0; padding-left: 1.1rem; }
.cfg-tree > ul { padding-left: .1rem; }
.cfg-tree li { margin: .05rem 0; }
.cfg-exp { display: inline-block; width: 1.1em; cursor: pointer; user-select: none; color: #556; font-size: .8em; }
.cfg-ico { display: inline-block; position: relative; width: 14px; height: 9px; margin: 3px .3rem 0 0; vertical-align: -1px; background: #e8c35a; border: 1px solid #a5852e; border-radius: 0 2px 2px 2px; }
.cfg-ico::before { content: ''; position: absolute; left: -1px; top: -4px; width: 6px; height: 3px; background: #e8c35a; border: 1px solid #a5852e; border-bottom: 0; border-radius: 2px 2px 0 0; }
li[data-state="expanded"] > .cfg-ico { background: #f6dc8a; }
li[data-state="expanded"] > .cfg-ico::after { content: ''; position: absolute; left: 2px; right: -3px; top: 2px; bottom: -1px; background: #fbe9b0; border: 1px solid #a5852e; transform: skewX(-20deg); }
.cfg-key { cursor: default; }
.cfg-val { cursor: pointer; white-space: pre-wrap; padding: 0 .25rem; border-radius: 3px; font-family: ui-monospace, monospace; font-size: .88rem; }
.cfg-val:hover { background: #00FFAA; }
.cfg-val.ro { color: #8a8f98; cursor: not-allowed; background: none; }
.cfg-val.changed { background: #fff3bf; }
.cfg-radix { margin: 0 .2rem 0 0; vertical-align: -2px; }
input.cfg-inline { font-family: ui-monospace, monospace; font-size: .88rem; min-width: 12rem; }
textarea.cfg-text { width: 100%; height: 100%; min-height: 20rem; font: 12px/1.3 ui-monospace, monospace; border: 1px solid #d6dae0; }
.cfg-popup { position: fixed; z-index: 70; background: #fff; border: 1px solid #8a929c; border-radius: 4px; box-shadow: 0 4px 14px rgba(0,0,0,.2); display: flex; flex-direction: column; min-width: 8rem; max-height: 50vh; overflow: auto; }
.cfg-popup button { border: 0; border-radius: 0; text-align: left; background: #fff; }
.cfg-popup button:hover { background: #e8f0fe; }
#cfg_ed_status { padding: .25rem .5rem; border-top: 1px solid #e0e3e8; min-height: 1.6rem; font-size: .85rem; }
#cfg_ed_status[data-ok="0"] { color: #b00; } #cfg_ed_status[data-ok="1"] { color: #17633a; }
#cfg_pt_text { width: min(640px, 85vw); height: 14rem; font: 12px/1.3 ui-monospace, monospace; }
.cfg-help { white-space: pre-wrap; font: 12px/1.35 ui-monospace, monospace; margin: .2rem 0 .5rem; }
.cfg-msg { min-height: 1.2rem; font-size: .85rem; color: #9a6700; }
`;

// ---------------- DOM ----------------
const html = (s) => { const t = document.createElement('template'); t.innerHTML = s.trim(); return t.content.firstElementChild; };

function fileOpenDialog(id, parity, caption, accept) {      // QFileDialog.getOpenFileName
  return html(`<div id="${id}" class="cfg-modal" hidden><div class="cfg-dlg" role="dialog" aria-label="${escH(caption)}" data-parity="${parity}">
    <div class="cfg-wtitle">${escH(caption)}</div>
    <div class="row"><input type="file" class="cfg-file" accept="${accept}"></div>
    <div class="row center"><button type="button" class="cfg-fcancel">Cancel</button><button type="button" class="cfg-fok" disabled>Open</button></div>
  </div></div>`);
}

function fileSaveDialog(id, parity, caption) {              // QFileDialog.getSaveFileName
  return html(`<div id="${id}" class="cfg-modal" hidden><div class="cfg-dlg" role="dialog" aria-label="${escH(caption)}" data-parity="${parity}">
    <div class="cfg-wtitle">${escH(caption)}</div>
    <div class="row"><span class="lab">File name</span><input type="text" class="cfg-fname" size="34"></div>
    <div class="row center"><button type="button" class="cfg-fcancel">Cancel</button><button type="button" class="cfg-fok">Save</button></div>
  </div></div>`);
}

function build() {
  const st = document.createElement('style');
  st.id = 'cfg_style';
  st.textContent = CSS;
  document.head.appendChild(st);
  const root = byId('ext') || document.body;
  const parts = [
    // QWDialog(CGWConfigSelect) 'Select config Type & Detector' (CGWMainConfiguration.py:218-224)
    html(`<div id="cfg_select" class="cfg-modal" hidden><div class="cfg-dlg" role="dialog" aria-label="Select config Type &amp; Detector">
      <div class="cfg-wtitle">Select config Type &amp; Detector</div>
      <fieldset class="group"><legend>Edit configuration</legend>
        <div class="row">
          <span class="stretch"></span><span class="lab">Type</span>
          <button type="button" id="cfg_sel_type" data-parity="CGWConfigSelect.but_type" title="Select configuration type.">Select ${CH_EXPAND}</button>
          <span class="stretch"></span><span class="lab">Detector</span>
          <button type="button" id="cfg_sel_dev" data-parity="CGWConfigSelect.but_dev" title="Select device for configuration.">Select ${CH_EXPAND}</button>
        </div>
        <div id="cfg_sel_msg" class="cfg-msg"></div>
      </fieldset>
      <div class="row">
        <span class="stretch"></span><button type="button" id="cfg_dlg_cancel" data-parity="QWDialog.but_cancel" title="Use default list">&#10007; Cancel</button>
        <span class="stretch"></span><button type="button" id="cfg_dlg_apply" data-parity="QWDialog.but_apply" title="Apply changes to the list" disabled>&#10003; Edit</button><span class="stretch"></span>
      </div>
    </div></div>`),
    // popups of QWPopupSelectItem.popup_select_item_from_list
    html(`<div id="cfg_pop_type" class="cfg-popup" role="listbox" data-parity="CGWConfigSelect.on_but_type@1" hidden></div>`),
    html(`<div id="cfg_pop_dev" class="cfg-popup" role="listbox" data-parity="CGWConfigSelect.on_but_dev@1" hidden></div>`),
    html(`<div id="cfg_pop_enum" class="cfg-popup" role="listbox" data-parity="CGWConfigEditorTree.start_special_editor@1" hidden></div>`),
    // CGWConfigEditor window (CGWConfigEditor.py:68-99)
    html(`<div id="cfg_editor" class="cfg-window" hidden role="dialog" aria-label="Configuration Editor" title="${escH(EDITOR_TIP)}">
      <div class="cfg-wtitle" id="cfg_ed_title">Configuration Editor</div>
      <div class="cfg-toolbar">
        <button type="button" id="cfg_ed_apply" class="good" data-parity="CGWConfigEditor.but_apply" title="Apply content changes to configuration DB">Apply</button>
        <button type="button" id="cfg_ed_close" data-parity="CGWConfigEditor.but_close" title="Close window, cancel all modifications since last click on Apply button">Close</button>
        <button type="button" id="cfg_ed_select" data-parity="CGWConfigEditor.but_select" title="Select other configuration type and device to edit">Select</button>
        <button type="button" id="cfg_ed_expn" data-parity="CGWConfigEditor.but_expn" title="Expand/Collapse tree-like content">Expand ${CH_EXPAND}</button>
        <span class="stretch"></span>
        <select id="cfg_ed_more" title="${escH(MORE_TIP)}">
          <option>More</option>
          <option data-parity="CGWConfigEditor.box_more.load">Load</option>
          <option data-parity="CGWConfigEditor.box_more.save">Save</option>
          <option data-parity="CGWConfigEditor.box_more.help">Help</option>
        </select>
        <select id="cfg_ed_type" data-parity="CGWConfigEditor.box_type" title="Select editor type"><option>Text</option><option selected>Tree</option></select>
        <label id="cfg_ed_serno_lab"><input type="checkbox" id="cfg_ed_serno" data-parity="CGWConfigEditor.cbx_serno"> Use Serial Number Database</label>
      </div>
      <div class="cfg-body">
        <div id="cfg_ed_tree" class="cfg-tree" title="Tree-like configuration editor"></div>
        <textarea id="cfg_ed_text" class="cfg-text" data-parity="CGWConfigEditorText.edi_txt" spellcheck="false" title="Configuration editor GUI" hidden>Json in text is here...</textarea>
      </div>
      <div id="cfg_ed_status"></div>
    </div>`),
    // QWPopupEditText(QWEditText) for long "trimmed" arrays (CGWConfigEditorTree.py:420-431)
    html(`<div id="cfg_popup_text" class="cfg-modal" hidden><div class="cfg-dlg" role="dialog" aria-label="Text Editor" title="Text Editor">
      <div class="cfg-wtitle">Text Editor</div>
      <textarea id="cfg_pt_text" data-parity="QWEditText.edi_text" spellcheck="false" title="Text editor"></textarea>
      <div class="row">
        <select id="cfg_pt_more" title="${escH(MORE_TIP)}">
          <option>More</option>
          <option data-parity="QWEditText.box_more.load">Load</option>
          <option data-parity="QWEditText.box_more.save">Save</option>
        </select>
        <span class="stretch"></span>
        <button type="button" id="cfg_pt_cancel" data-parity="QWPopupEditText.but_cancel" title="Cancel changes" accesskey="c">&#10007; <u>C</u>ancel</button>
        <button type="button" id="cfg_pt_apply" data-parity="QWPopupEditText.but_apply" title="Apply changes" accesskey="a">&#10003; <u>A</u>pply</button>
      </div>
    </div></div>`),
    fileOpenDialog('cfg_fo_editor', 'CGWConfigEditor.select_ifname@1', 'Select the file to load json',
                   '.json,.cfg,.txt,.text,.dat,.data'),
    fileSaveDialog('cfg_fs_editor', 'CGWConfigEditor.select_ofname@1', 'Select the file to save json'),
    fileOpenDialog('cfg_fo_popup', 'QWEditText.select_ifname@1', 'Select the file to load json',
                   '.txt,.text,.dat,.data,.npy'),
    fileSaveDialog('cfg_fs_popup', 'QWEditText.select_ofname@1', 'Select the file to save'),
    // help_dialog_box (QWUtils.py:232)
    html(`<div id="cfg_help" class="cfg-modal" hidden><div class="cfg-dlg" role="dialog" aria-label="Help" data-parity="CGWConfigEditor.help_box">
      <div class="cfg-wtitle">Help</div><div class="cfg-help" id="cfg_help_text"></div>
      <div class="row center"><button type="button" id="cfg_help_ok">OK</button></div>
    </div></div>`),
    // confirm_or_cancel_dialog_box (QWUtils.py:210) in save_dictj_in_db
    html(`<div id="cfg_confirm" class="cfg-modal" hidden><div class="cfg-dlg" role="alertdialog" aria-label="Confirm or cancel" data-parity="CGWMainConfiguration.save_dictj_in_db@1">
      <div class="cfg-wtitle" id="cfg_cf_title">Confirm or cancel</div><div class="row" id="cfg_cf_text">Save changes in configuration DB</div>
      <div class="row center"><button type="button" id="cfg_cf_ok" class="good">OK</button><button type="button" id="cfg_cf_cancel">Cancel</button></div>
    </div></div>`),
  ];
  for (const p of parts) root.appendChild(p);
  // the main window's alias popup (app.js, CGWMainConfiguration.on_but_type :156) has no row id in index.html
  const pt = byId('popup_type');
  if (pt && !pt.dataset.parity) pt.dataset.parity = 'CGWMainConfiguration.on_but_type@1';
}

// ---------------- server calls ----------------
async function apiGet(path, params) {
  const q = params ? '?' + new URLSearchParams(params).toString() : '';
  try {
    const r = await fetch(path + q);
    return await r.json();
  } catch (e) { return {ok: false, err_info: String(e)}; }
}

async function apiPost(path, body) {
  try {
    const r = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    return await r.json();
  } catch (e) { return {ok: false, err_info: String(e)}; }
}

const note = (event, name) => apiPost('/api/configdb/note', name === undefined ? {event} : {event, name: String(name)});

// ---------------- small dialogs ----------------
let popupDone = null;                       // the open QWPopupSelectItem, if any
const modalStack = [];                      // open dialogs, innermost last: Escape cancels only that one

document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  if (popupDone) { e.stopPropagation(); popupDone(null); return; }
  const top = modalStack[modalStack.length - 1];
  if (top) { e.stopPropagation(); top.cancel(); }
}, true);

function popupSelect(anchor, pop, items, sort) {   // QWPopupSelectItem: chosen name, or null (Escape / outside)
  if (popupDone) popupDone(null);
  const list = sort === false ? items.slice() : items.slice().sort();
  return new Promise((resolve) => {
    pop.innerHTML = list.map((x) => '<button type="button" role="option" data-value="' + escH(x) + '">' + escH(x) + '</button>').join('');
    const r = anchor.getBoundingClientRect();
    pop.style.left = Math.max(0, r.left) + 'px';
    pop.style.top = r.bottom + 'px';
    pop.hidden = false;
    const outside = (e) => { if (!pop.contains(e.target)) done(null); };
    function done(v) {
      pop.hidden = true;
      pop.innerHTML = '';
      document.removeEventListener('mousedown', outside, true);
      popupDone = null;
      resolve(v);
    }
    for (const b of pop.querySelectorAll('button')) {
      b.addEventListener('click', (e) => { e.stopPropagation(); done(b.dataset.value); });
    }
    setTimeout(() => document.addEventListener('mousedown', outside, true), 0);
    popupDone = done;
  });
}

function modalChoice(el, okSel, cancelSel, onOk) {   // resolve(onOk()) on OK, null on Cancel / Escape
  return new Promise((resolve) => {
    const ok = el.querySelector(okSel), cancel = el.querySelector(cancelSel);
    const entry = {el, cancel: () => fin(null)};
    let finished = false;
    function fin(v) {
      if (finished) return;
      finished = true;
      el.hidden = true;
      ok.removeEventListener('click', onOkClick);
      cancel.removeEventListener('click', onCancel);
      const i = modalStack.indexOf(entry);
      if (i >= 0) modalStack.splice(i, 1);
      resolve(v);
    }
    const onOkClick = () => fin(onOk());
    const onCancel = () => fin(null);
    ok.addEventListener('click', onOkClick);
    cancel.addEventListener('click', onCancel);
    modalStack.push(entry);
    el.hidden = false;
    ok.focus();
  });
}

function confirmOrCancel(text, title) {   // QWUtils.confirm_or_cancel_dialog_box: OK -> true
  const el = byId('cfg_confirm');
  byId('cfg_cf_text').textContent = text;
  byId('cfg_cf_title').textContent = title;
  return modalChoice(el, '#cfg_cf_ok', '#cfg_cf_cancel', () => true).then((v) => v === true);
}

function chooseOpenFile(id) {             // getOpenFileName: File, or null when cancelled
  const el = byId(id), inp = el.querySelector('.cfg-file'), ok = el.querySelector('.cfg-fok');
  inp.value = '';
  ok.disabled = true;
  inp.onchange = () => { ok.disabled = !inp.files.length; };
  return modalChoice(el, '.cfg-fok', '.cfg-fcancel', () => inp.files[0] || null);
}

function chooseSaveName(id, def) {        // getSaveFileName: name, or null when cancelled ('' too)
  const el = byId(id), inp = el.querySelector('.cfg-fname');
  inp.value = def;
  return modalChoice(el, '.cfg-fok', '.cfg-fcancel', () => inp.value.trim() || null);
}

function download(name, data, type) {
  const blob = data instanceof Blob ? data : new Blob([data], {type: type || 'text/plain'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name.split('/').pop();
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

function b64FromBuffer(buf) {
  let s = '';
  const u = new Uint8Array(buf);
  for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000));
  return btoa(s);
}

// ---------------- CGWConfigSelect inside QWDialog ----------------
const SEL = {type: 'Select', dev: 'Select', typeOld: null, resolve: null};

function selButs() {                       // CGWConfigSelect.set_buts_enabled (:90-97)
  byId('cfg_sel_type').textContent = SEL.type + ' ' + CH_EXPAND;
  byId('cfg_sel_dev').textContent = SEL.dev + ' ' + CH_EXPAND;
  byId('cfg_sel_type').dataset.value = SEL.type;
  byId('cfg_sel_dev').dataset.value = SEL.dev;
  const isType = SEL.type.slice(0, 6) !== 'Select', isDev = SEL.dev.slice(0, 6) !== 'Select';
  byId('cfg_sel_dev').disabled = !isType;
  byId('cfg_dlg_apply').disabled = !(isType && isDev);
}

function selMsg(t) { byId('cfg_sel_msg').textContent = t || ''; }

async function onSelType() {               // CGWConfigSelect.on_but_type (:124-146)
  const r = await apiGet('/api/configdb/aliases');
  if (!r.ok) { selMsg(r.err_info); return; }
  selMsg(r.fallback ? 'List of configdb-s IS EMPTY... Use default: ' + r.aliases.join(', ') : '');
  const selected = await popupSelect(byId('cfg_sel_type'), byId('cfg_pop_type'), r.aliases);
  if (selected === null) return;           // PyQt would show 'None' here (set_but_type_text(None))
  SEL.type = selected;
  if (selected !== SEL.typeOld) { SEL.dev = 'Select'; SEL.typeOld = selected; }
  selButs();
}

async function onSelDev() {                // CGWConfigSelect.on_but_dev (:174-189)
  const r = await apiGet('/api/configdb/devices', {alias: SEL.type});
  if (!r.ok) { selMsg(r.err_info); return; }
  if (!r.devices.length) {
    selMsg('list_of_device_names IS EMPTY... Check configuration DB');
    note('devices_empty');
    return;
  }
  selMsg('');
  const selected = await popupSelect(byId('cfg_sel_dev'), byId('cfg_pop_dev'), r.devices);
  if (selected === null) return;
  SEL.dev = selected;
  selButs();
}

function selectConfigTypeAndDev() {        // CGWMainConfiguration.select_config_type_and_dev (:216-236)
  const main = byId('but_type');
  SEL.type = (main && main.dataset.value) || 'Select';   // type_def=self.but_type_text()
  SEL.dev = 'Select';
  SEL.typeOld = null;
  selButs();
  selMsg('');
  const el = byId('cfg_select');
  return modalChoice(el, '#cfg_dlg_apply', '#cfg_dlg_cancel', () => [SEL.type, SEL.dev]);
}

// ---------------- CGWConfigEditor ----------------
const E = {open: false, cfgtype: null, dev: null, configJson: null, leaves: [], mode: 'Tree',
           ofname: 'test.json', popupOfname: 'test.txt'};

function status(text, ok) {
  const s = byId('cfg_ed_status');
  s.textContent = text || '';
  s.dataset.ok = ok === undefined ? '' : (ok ? '1' : '0');
}

async function selectConfigurationDictToEdit() {   // CGWMainConfiguration.select_configuration_dict_to_edit (:239-262)
  const resp = await selectConfigTypeAndDev();
  if (resp === null) return null;
  const [cfgtype, dev] = resp;
  const j = await apiGet('/api/configdb/config', {alias: cfgtype, device: dev});
  if (!j.ok) {
    if (E.open) status('get_configuration(' + cfgtype + ', ' + dev + '): ' + j.err_info, false);
    else alertMain('get_configuration(' + cfgtype + ', ' + dev + '): ' + j.err_info);
    return null;
  }
  E.cfgtype = cfgtype;                     // cfgtype_edit, device_edit
  E.dev = dev;
  return j;
}

function alertMain(t) {
  const c = byId('cmd_status');
  if (c) { c.textContent = 'config editor: ' + t; c.dataset.ok = '0'; }
}

async function onButEdit() {               // CGWMainConfiguration.on_but_edit (:265-279)
  if (E.open) { closeEditor(); return; }
  const j = await selectConfigurationDictToEdit();
  if (j === null) return;
  E.open = true;
  byId('cfg_ed_type').value = 'Tree';      // box_type.setCurrentIndex(1)
  showMode('Tree');
  setContent(j);
  setupSerno();
  status('');
  byId('cfg_editor').hidden = false;
  document.body.classList.add('cfg-editor-open');
}

function closeEditor() {                   // CGWConfigEditor.on_but_close / closeEvent
  E.open = false;
  byId('cfg_editor').hidden = true;
  document.body.classList.remove('cfg-editor-open');
  byId('cfg_help').hidden = true;
  if (popupDone) popupDone(null);
}

function setTitle() {                      // CGWConfigEditor.set_window_title (:364-367)
  byId('cfg_ed_title').textContent = 'Config Editor for ' + E.cfgtype + ' ' + E.dev;
}

function setContent(j) {                   // wedi.set_content(dictj)
  E.configJson = j.config_json;
  byId('cfg_ed_text').value = j.text;
  renderTree(j.tree);
  setTitle();
}

function showMode(m) {                     // on_box_type / editor_widget_selector (:388-420)
  E.mode = m;
  byId('cfg_ed_tree').hidden = m !== 'Tree';
  byId('cfg_ed_text').hidden = m !== 'Text';
  const ex = byId('cfg_ed_expn');
  ex.hidden = m !== 'Tree';
  if (m === 'Tree') ex.textContent = 'Expand ' + CH_EXPAND;
}

function leafValue(l) {                    // CGWConfigEditorTree.iterate_over_children (:315-320)
  if (l.descr.slice(0, 4) === 'trim') return l.full;
  if (l.enum) {
    const hit = l.enum.find((p) => p[0] === l.text);
    return hit ? String(hit[1]) : l.text;
  }
  return l.text;
}

function contentBody() {                   // get_content of the current editor
  if (E.mode === 'Text') return {mode: 'text', text: byId('cfg_ed_text').value};
  return {mode: 'tree', config_json: E.configJson, leaves: E.leaves.map((l) => [l.path, leafValue(l)])};
}

async function onButApply() {              // CGWConfigEditor.on_but_apply (:301-340) -> save_dictj_in_db
  const body = contentBody();
  if (body.mode === 'text') {
    try { JSON.parse(body.text); } catch (e) { status('Text is not valid JSON, nothing saved: ' + e.message, false); return; }
  }
  const ok = await confirmOrCancel('Save changes in configuration DB', 'Confirm or cancel');
  if (!ok) {
    note('save_cancelled');
    status('Saving of configuration in DB is cancelled...', false);
    return;
  }
  status('saving ...');
  const r = await apiPost('/api/configdb/save', Object.assign({alias: E.cfgtype, device: E.dev}, body));
  if (!r.ok) { status('not saved: ' + r.err_info, false); return; }
  E.configJson = r.config_json;
  for (const el of document.querySelectorAll('#cfg_ed_tree .cfg-val.changed')) el.classList.remove('changed');
  const bad = (r.bad || []).map((b) => b.path + '=' + b.value + ' (status ' + b.status + ')');
  status('saved ' + r.alias + '/' + r.device + ' in ' + r.hutch + ': new key ' + r.key
         + (bad.length ? '; NOT applied: ' + bad.join(', ') : ''), !bad.length);
  byId('cfg_ed_status').dataset.key = String(r.key);
}

async function onButSelect() {             // CGWConfigEditor.on_but_select (:344-360)
  const j = await selectConfigurationDictToEdit();
  if (j === null) return;
  setContent(j);
  setupSerno();
  status('');
}

function onButExpn() {                     // CGWConfigEditor.on_but_expn (:424-431)
  const b = byId('cfg_ed_expn');
  if (b.textContent.slice(0, 6) === 'Expand') { setAllExpanded(true); b.textContent = 'Collapse ' + CH_SHRINK; }
  else { setAllExpanded(false); b.textContent = 'Expand ' + CH_EXPAND; }
}

async function onBoxType() {               // CGWConfigEditor.on_box_type (:388-399)
  const box = byId('cfg_ed_type');
  const type = box.value;
  if (type === E.mode) return;
  note('editor_type', type);
  // carry the current content across (the PyQt widget is rebuilt from the last applied dict)
  const r = await apiPost('/api/configdb/content', contentBody());
  if (!r.ok) { status('cannot switch to ' + type + ': ' + r.err_info, false); box.value = E.mode; return; }
  E.configJson = r.config_json;
  if (type === 'Text') byId('cfg_ed_text').value = r.text;
  else renderTree(r.tree);
  showMode(type);
}

async function onBoxMore() {               // CGWConfigEditor.on_box_more (:377-384)
  const box = byId('cfg_ed_more');
  const ind = box.selectedIndex;
  box.selectedIndex = 0;
  if (ind <= 0) return;
  note('more_option', MORE_OPTIONS[ind]);
  if (ind === 1) await onButLoad();
  else if (ind === 2) await onButSave();
  else if (ind === 3) onButHelp();
}

async function onButLoad() {               // on_but_load / select_ifname / load_dict (:166-195)
  const f = await chooseOpenFile('cfg_fo_editor');
  if (!f) { note('load_cancelled'); return; }
  note('input_file', f.name);
  const r = await apiPost('/api/configdb/render', {text: await f.text()});
  if (!r.ok) { status('load ' + f.name + ': ' + r.err_info, false); return; }
  setContent(r);
  status('loaded ' + f.name + ' (Apply saves it to ' + E.cfgtype + ' as detName ' + detName(r.config_json) + ')', true);
}

function detName(cj) { try { return JSON.parse(cj)['detName:RO']; } catch (e) { return '?'; } }

async function onButSave() {               // on_but_save / select_ofname / save_dict_in_file (:199-297)
  const name = await chooseSaveName('cfg_fs_editor', E.ofname);
  if (!name) { note('save_file_cancelled'); return; }
  const r = await apiPost('/api/configdb/content', contentBody());
  if (!r.ok) { status('save to file: ' + r.err_info, false); return; }
  E.ofname = name;
  note('output_file', name);
  download(name, r.text, 'application/json');
  status('saved in file ' + name, true);
}

function onButHelp() {                     // on_but_help (:206-211)
  byId('cfg_help_text').textContent = EDITOR_TIP;
  modalChoice(byId('cfg_help'), '#cfg_help_ok', '#cfg_help_ok', () => true);
}

// ---- serial number DB (CGWConfigEditor.set_style :153-162, on_cbx_serno :215-268) ----
function getSerno(alias) {                 // CGConfigParameters.get_serno: from the status platform
  const plat = (typeof S !== 'undefined' && S && S.status && S.status.platform) || {};
  for (const level of ['drp', 'tpr']) {
    const d = plat[level] || {};
    for (const k of Object.keys(d)) {
      const it = d[k] || {};
      if ((it.proc_info || {}).alias === alias) {
        const sn = (it.connect_info || {}).short_sn_id;
        return sn === undefined ? null : sn;
      }
    }
  }
  return null;
}

function setupSerno() {
  const sn = getSerno(E.dev);
  const cbx = byId('cfg_ed_serno');
  cbx.checked = false;
  cbx.disabled = !(sn !== null && sn !== '-');
  cbx.dataset.serno = sn === null ? '' : sn;
  const tip = sn ? 'Detector Serial Number: ' + sn : 'Serial number not available (detector not in partition)';
  cbx.title = tip;
  byId('cfg_ed_serno_lab').title = tip;
}

async function onCbxSerno() {
  const cbx = byId('cfg_ed_serno');
  const on = cbx.checked;
  const q = {alias: E.cfgtype, device: E.dev, use_serial_db: on ? '1' : '0'};
  if (on) q.serno = cbx.dataset.serno;
  const r = await apiGet('/api/configdb/config', q);
  if (!r.ok) {
    status((on ? 'Failed to fetch serial number config for ' + q.serno : 'Failed to revert to the alias config for ' + E.dev) + ': ' + r.err_info, false);
    if (on) cbx.checked = false;
    return;
  }
  E.configJson = r.config_json;
  byId('cfg_ed_text').value = r.text;
  renderTree(r.tree);
  status(on ? 'serial number DB ' + q.serno + ' merged (use_serial_db True)' : 'alias DB (use_serial_db False)', true);
}

// ---------------- CGWConfigEditorTree ----------------
function renderTree(nodes) {               // fill_tree_model_from_dict: a new model starts collapsed
  E.leaves = [];
  const t = byId('cfg_ed_tree');
  t.innerHTML = '';
  t.appendChild(buildUl(nodes || []));
  byId('cfg_ed_expn').textContent = 'Expand ' + CH_EXPAND;
}

function buildUl(nodes) {
  const ul = document.createElement('ul');
  for (const n of nodes) ul.appendChild(n.leaf ? buildLeaf(n) : buildNode(n));
  return ul;
}

function buildNode(n) {                    // a key item (QStandardItem(k) :167, QStandardItem('%d' % i) :181)
  const li = document.createElement('li');
  li.className = 'cfg-node';
  li.dataset.key = n.key;
  li.dataset.kind = n.kind;
  const kids = n.children || [];
  const exp = document.createElement('span');
  exp.className = 'cfg-exp';
  const ico = document.createElement('span');
  ico.className = 'cfg-ico';
  const key = document.createElement('span');
  key.className = 'cfg-key';
  key.textContent = n.text;
  key.title = n.tip;
  key.dataset.parity = n.cell === 'index' ? 'CGWConfigEditorTree.tree_model_from_dict@2' : 'CGWConfigEditorTree.tree_model_from_dict@1';
  li.append(exp, ico, key);
  if (kids.length) {
    exp.dataset.parity = 'CGWConfigEditorTree.expanded CGWConfigEditorTree.collapsed';
    exp.title = 'expand / collapse';
    const ul = buildUl(kids);
    li.appendChild(ul);
    setExpanded(li, false);
    exp.addEventListener('click', () => setExpanded(li, li.dataset.state !== 'expanded'));
    key.addEventListener('dblclick', () => setExpanded(li, li.dataset.state !== 'expanded'));
  }
  return li;
}

function setExpanded(li, on) {             // QWTree on_item_expanded / on_item_collapsed (folder icon)
  const ul = li.querySelector(':scope > ul');
  if (!ul) return;
  ul.hidden = !on;
  li.dataset.state = on ? 'expanded' : 'collapsed';
  li.querySelector(':scope > .cfg-exp').textContent = on ? '▾' : '▸';
}

function setAllExpanded(on) {              // QWTree.process_expand / process_collapse
  for (const li of document.querySelectorAll('#cfg_ed_tree li.cfg-node')) setExpanded(li, on);
}

function buildLeaf(l) {                    // the data item (:196 data list, :224 scalar)
  l.changed = false;
  E.leaves.push(l);
  const li = document.createElement('li');
  li.className = 'cfg-leaf';
  li.dataset.path = l.path;
  const span = document.createElement('span');
  span.className = 'cfg-val' + (l.enabled ? '' : ' ro');
  span.textContent = l.text;
  span.title = l.tip;
  span.dataset.path = l.path;
  span.dataset.parity = (l.cell === 'list' ? 'CGWConfigEditorTree.tree_model_from_dict@3.edit'
                                           : 'CGWConfigEditorTree.tree_model_from_dict@4.edit') + ' CGWConfigEditorTree.clicked';
  if (!l.enabled) span.setAttribute('aria-disabled', 'true');
  if (l.enum) span.dataset.enum = '1';
  if (l.trimmed) span.dataset.trimmed = '1';
  if (l.checkable) {                      // item.setCheckable(str_is_any_int(s)) (:235)
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.className = 'cfg-radix';
    cb.dataset.parity = 'CGWConfigEditorTree.tree_model_from_dict@4.check';
    cb.dataset.path = l.path;
    cb.title = 'swap presentation DEC/HEX/OCT/BIN';
    cb.disabled = !l.enabled;
    cb.addEventListener('change', () => cycleRadix(l, cb, span));
    li.appendChild(cb);
  }
  span.addEventListener('click', () => onClick(l, span));
  li.appendChild(span);
  return li;
}

const strIsInt = (s) => /^[0-9]+$/.test(s) || (s.startsWith('-') && /^[0-9]+$/.test(s.slice(1)));
const strIsHex = (s) => s.includes('0x');
const strIsOct = (s) => s.includes('0o');
const strIsBin = (s) => s.includes('0b');

function convertRadix(s) {                 // on_item_changed (:351-356): DEC -> HEX -> OCT -> BIN -> DEC
  const neg = s.startsWith('-'), body = neg ? s.slice(1) : s, sg = neg ? '-' : '';
  try {
    if (strIsInt(s)) return sg + '0x' + BigInt(body).toString(16);
    if (strIsHex(s)) return sg + '0o' + BigInt(body).toString(8);
    if (strIsOct(s)) return sg + '0b' + BigInt(body).toString(2);
    if (strIsBin(s)) return sg + BigInt(body).toString(10);
  } catch (e) { /* not a number after all: leave it */ }
  return s;
}

function cycleRadix(l, cb, span) {
  const s = l.text;
  const state = strIsBin(s) ? 0 : 1;       // item.setCheckState(0 if str_is_bin(s) else 1)
  l.text = convertRadix(s);
  span.textContent = l.text;
  cb.checked = false;
  cb.indeterminate = state === 1;
}

function setItemForList(l, o) {            // set_item_for_list (:241-252)
  const lst = String(o).replace(/\n/g, ' ').split(' ');
  l.full = lst.join(' ');
  l.text = lst.length >= LIST_MAX_LEN ? lst.slice(0, LIST_MAX_LEN).join(' ') + ' ...' : l.full;
}

function markChanged(l, span) {
  l.changed = true;
  span.textContent = l.text;
  span.classList.add('changed');
}

function onClick(l, span) {                // on_click (:366-382)
  if (!l.enabled) return;                  // disabled items (:RO) give no clicked signal
  if (startSpecialEditor(l, span)) return;
  if (l.editable) inlineEdit(l, span);
}

function startSpecialEditor(l, span) {     // :392-433
  if (l.enum) {                            // enumerated values: popup of the names, unsorted
    popupSelect(span, byId('cfg_pop_enum'), l.enum.map((p) => p[0]), false).then((sel) => {
      if (sel === null) return;
      setItemForList(l, sel);
      markChanged(l, span);
    });
    return true;
  }
  if (l.descr.slice(0, 7) === 'trimmed') { // long "trimmed" arrays: QWPopupEditText
    popupEditText(l.full).then((txt) => {
      if (txt === null) return;
      setItemForList(l, txt);
      markChanged(l, span);
    });
    return true;
  }
  return false;
}

function inlineEdit(l, span) {             // self.edit(index): in-line editor, Enter / focus-out commits, Escape cancels
  const inp = document.createElement('input');
  inp.className = 'cfg-inline';
  inp.value = l.text;
  inp.dataset.path = l.path;
  span.replaceWith(inp);
  inp.focus();
  inp.select();
  let done = false;
  const finish = (commit) => {
    if (done) return;
    done = true;
    if (commit && inp.value !== l.text) { l.text = inp.value; markChanged(l, span); }
    inp.replaceWith(span);
  };
  inp.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') finish(true);
    else if (e.key === 'Escape') { e.stopPropagation(); finish(false); }
  });
  inp.addEventListener('blur', () => finish(true));
}

// ---------------- QWPopupEditText / QWEditText ----------------
function popupEditText(text) {             // exec_(): Apply -> edited text, Cancel / Escape -> null
  const ta = byId('cfg_pt_text');
  ta.value = text;
  return modalChoice(byId('cfg_popup_text'), '#cfg_pt_apply', '#cfg_pt_cancel', () => ta.value);
}

async function onPopupMore() {             // QWEditText.on_box_more (:225-230)
  const box = byId('cfg_pt_more');
  const ind = box.selectedIndex;
  box.selectedIndex = 0;
  if (ind === 1) await popupLoad();
  else if (ind === 2) await popupSave();
}

async function popupLoad() {               // QWEditText.on_but_load (:182-189)
  const f = await chooseOpenFile('cfg_fo_popup');
  if (!f) { note('load_cancelled'); return; }
  note('input_file', f.name);
  const ta = byId('cfg_pt_text');
  if (/\.npy$/.test(f.name)) {
    const r = await apiPost('/api/configdb/npy_load', {data_b64: b64FromBuffer(await f.arrayBuffer())});
    if (!r.ok) { ta.dataset.err = r.err_info; return; }
    ta.value = r.text;
  } else {
    ta.value = await f.text();
  }
  delete ta.dataset.err;
}

async function popupSave() {               // QWEditText.on_but_save (:216-221)
  const name = await chooseSaveName('cfg_fs_popup', E.popupOfname);
  if (!name) { note('save_file_cancelled'); return; }
  E.popupOfname = name;
  note('output_file', name);
  const txt = byId('cfg_pt_text').value;
  if (/\.npy$/.test(name)) {
    const r = await apiPost('/api/configdb/npy_save', {text: txt});
    if (!r.ok) { byId('cfg_pt_text').dataset.err = r.err_info; return; }
    const bin = Uint8Array.from(atob(r.data_b64), (c) => c.charCodeAt(0));
    download(name, new Blob([bin], {type: 'application/octet-stream'}));
  } else {
    download(name, txt);
  }
}

// ---------------- wiring ----------------
function wire() {
  byId('but_edit').addEventListener('click', onButEdit);
  byId('cfg_sel_type').addEventListener('click', onSelType);
  byId('cfg_sel_dev').addEventListener('click', onSelDev);
  byId('cfg_ed_apply').addEventListener('click', onButApply);
  byId('cfg_ed_close').addEventListener('click', closeEditor);
  byId('cfg_ed_select').addEventListener('click', onButSelect);
  byId('cfg_ed_expn').addEventListener('click', onButExpn);
  byId('cfg_ed_type').addEventListener('change', onBoxType);
  byId('cfg_ed_more').addEventListener('change', onBoxMore);
  byId('cfg_ed_serno').addEventListener('change', onCbxSerno);
  byId('cfg_pt_more').addEventListener('change', onPopupMore);
  document.body.dataset.cfgEditor = '1';
}

build();
wire();
})();
