// DAQ control web GUI v0 (vanilla JS, no build step, no CDN).
// Enable/disable rules mirror the PyQt set_buts_enabled methods (cited per block).
'use strict';

const $ = (id) => document.getElementById(id);
const S = {
  status: {state: null, transition: null, platform: {}},
  meta: {states: [], transitions: [], aliases: [], readout_groups: []},
  events: {},
  lastSeq: 0,
  selectOpen: false,   // QWPopupTableCheck window
  showOpen: false,     // CGWPartitionTable "show" window
  selectPlatformKey: null,
  showPlatformKey: null,
  configTypeShown: null,
  ptab: {select: null, show: null},   // CGWPartitionTable models: {rows, collapser: {detname: row key}}
  tab: 'expert',       // CGWMainTabs: 'user' | 'expert'; CGWMain.py:79 builds the Expert tab
  playLocked: false,   // CGWMainTabUser.on_but_play locks Play until the next status message
};

const lower = (x) => (x === null || x === undefined) ? 'none' : String(x).toLowerCase();
const upper = (x) => (x === null || x === undefined) ? 'None' : String(x).toUpperCase();

async function post(path, body) {
  const t0 = performance.now();
  $('cmd_status').textContent = path + ' ...';
  try {
    const r = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    const j = await r.json();
    $('cmd_status').textContent = path + (j.ok ? ' ok' : ' failed: ' + j.err_info) + ' (' + Math.round(performance.now() - t0) + ' ms)';
    $('cmd_status').dataset.ok = j.ok ? '1' : '0';
    return j;
  } catch (e) {
    $('cmd_status').textContent = path + ' error: ' + e;
    $('cmd_status').dataset.ok = '0';
    return {ok: false, err_info: String(e)};
  }
}

// ---------- platform helpers (CGJsonUtils.get_platform / set_platform) ----------
function platformRows(plat) {
  const rows = [];
  for (const level of Object.keys(plat || {})) {
    for (const id of Object.keys(plat[level])) {
      const v = plat[level][id];
      const pi = v.proc_info || {};
      const hasGrp = (level === 'drp' || level === 'tpr');
      rows.push({
        key: level + '/' + id, level, id,
        active: v.active === 1,
        readout: hasGrp && v.det_info ? String(v.det_info.readout) : '',
        hasGrp,
        name: level + '/' + (pi.pid ?? 'non-def') + '/' + (pi.host ?? 'non-def'),
        alias: pi.alias ?? 'non-def',
        monitor: v.monitor === 1,
        // CGJsonUtils.py:165 flag += 16 (BIT_HIDDENROW); QWTableOfCheckBoxes.hide_hidden_rows shows such a row
        // with every item disabled (set_items_in_hidden_row, "show rows but not editable")
        disabled: v.hidden === 1,
      });
    }
  }
  // CGWPartitionTable.sort_items: sortByColumn(ID, ascending), Qt compares the texts code unit by code unit
  rows.sort((a, b) => (a.alias < b.alias ? -1 : a.alias > b.alias ? 1 : 0));
  return rows;
}

function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c])); }

// CGWPartitionTable.detname: segment name without its trailing _<n>
const detname = (seg) => { const i = seg.lastIndexOf('_'); return i < 0 ? seg : seg.slice(0, i); };

function makeModel(plat, activeOnly) {
  const rows = platformRows(plat).filter((r) => !activeOnly || r.active);   // list_active_procs for the Show window
  const m = {rows, collapser: {}};
  collapseAll(m);
  return m;
}

function groupOf(m, r) { return m.rows.filter((x) => detname(x.alias) === detname(r.alias)); }
function isHidden(m, r) { const c = m.collapser[detname(r.alias)]; return c !== undefined && c !== r.key; }
function isCollapser(m, r) { return m.collapser[detname(r.alias)] === r.key; }

// CGWPartitionTable.collapse_all (called at construction): each detector with several segments shows one row
function collapseAll(m) {
  for (const r of m.rows) {
    if (isHidden(m, r)) continue;
    if (groupOf(m, r).length > 1) m.collapser[detname(r.alias)] = r.key;
  }
}

// CGWPartitionTable.on_click on an ID cell -> expand_collapse_detector(do_collapse = not in_collapsed_group)
function toggleDetector(m, r) {
  if (r.disabled) return;                       // disabled items emit no click
  const d = detname(r.alias);
  if (m.collapser[d] !== undefined) delete m.collapser[d];
  else if (groupOf(m, r).length > 1) m.collapser[d] = r.key;
}

// collapsed row: 0 / 1 (partial) / 2 over the segments, as expand_collapse_detector sets it
function shown(m, r, field) {
  if (!isCollapser(m, r)) return r[field] ? 2 : 0;
  const g = groupOf(m, r);
  return g.every((x) => !x[field]) ? 0 : g.every((x) => x[field]) ? 2 : 1;
}

function idCell(m, r, parity) {
  const col = isCollapser(m, r);
  const tip = col ? 'Click to EXPAND detector segments' : (groupOf(m, r).length > 1 ? 'Click to COLLAPSE detector segments' : '');
  return '<td class="cell-id' + (col ? ' collapser' : '') + '" data-parity="' + parity + '"' +
    (tip ? ' title="' + tip + '"' : '') + '>' + esc(r.alias) + '</td>';
}

function renderSelectTable() {    // QWPopupTableCheck: CGWPartitionTable with do_ctrl
  const m = S.ptab.select;
  const tb = $('select_table').querySelector('tbody');
  tb.innerHTML = '';
  if (!m) return;
  const groups = S.meta.readout_groups.length ? S.meta.readout_groups : ['0', '1', '2', '3', '4', '5', '6', '7'];  // CGWPartitionTable.LIST_OF_VALUES
  for (const r of m.rows) {
    const tr = document.createElement('tr');
    tr.dataset.level = r.level; tr.dataset.id = r.id; tr.dataset.alias = r.alias; tr.dataset.key = r.key;
    if (isHidden(m, r)) tr.hidden = true;
    if (r.disabled) tr.classList.add('disabled');
    if (isCollapser(m, r)) tr.dataset.collapser = '1';
    const dis = r.disabled ? ' disabled' : '';
    let grp = '';
    if (r.hasGrp) {
      const opts = groups.includes(r.readout) ? groups : [r.readout, ...groups];
      grp = '<select class="cell-grp" data-parity="CGWMainPartition.w_select.grp CGWPartitionTable.set_readout_group_number@1" title="readout group"' + dis + '>' +
        opts.map((g) => '<option' + (g === r.readout ? ' selected' : '') + '>' + esc(g) + '</option>').join('') + '</select>';
    }
    tr.innerHTML =
      '<td><input type="checkbox" class="cell-sel" data-parity="CGWMainPartition.w_select.sel"' + dis + '></td>' +
      '<td>' + grp + '</td><td data-parity="CGWMainPartition.w_select.level_pid_host">' + esc(r.name) + '</td>' +
      idCell(m, r, 'CGWMainPartition.w_select.id') +
      '<td><input type="checkbox" class="cell-mon" data-parity="CGWMainPartition.w_select.monitor"' + dis + '></td>';
    for (const [cls, field] of [['.cell-sel', 'active'], ['.cell-mon', 'monitor']]) {
      const cb = tr.querySelector(cls);
      const v = shown(m, r, field);
      cb.checked = v === 2; cb.indeterminate = v === 1;
      cb.addEventListener('change', () => {
        // CGWPartitionTable.on_item_changed: a collapser's check box sets the whole detector (set_group_check_state)
        for (const x of (isCollapser(m, r) ? groupOf(m, r) : [r])) x[field] = cb.checked;
        renderSelectTable();
      });
    }
    const g = tr.querySelector('.cell-grp');
    if (g) g.addEventListener('change', () => {
      // set_readout_group_number: a collapser's group goes to every segment (set_readout_group_number_for_detector_segments)
      for (const x of (isCollapser(m, r) ? groupOf(m, r) : [r])) x.readout = g.value;
      renderSelectTable();
    });
    tr.querySelector('.cell-id').addEventListener('click', () => { toggleDetector(m, r); renderSelectTable(); });
    tb.appendChild(tr);
  }
}

const MARK = ['', '&#9680;', '&#10003;'];   // unchecked, partial, checked

function renderShowTable() {      // CGWMainPartition.on_but_show: CGWPartitionTable of active rows, do_ctrl False (read only)
  const m = S.ptab.show;
  const tb = $('show_table').querySelector('tbody');
  tb.innerHTML = '';
  if (!m) return;
  for (const r of m.rows) {
    const tr = document.createElement('tr');
    tr.dataset.alias = r.alias; tr.dataset.key = r.key;
    if (isHidden(m, r)) tr.hidden = true;
    if (r.disabled) tr.classList.add('disabled');
    if (isCollapser(m, r)) tr.dataset.collapser = '1';
    tr.innerHTML = '<td data-parity="CGWMainPartition.w_show.sel">' + MARK[shown(m, r, 'active')] +
      '</td><td data-parity="CGWMainPartition.w_show.grp">' + esc(r.readout) +
      '</td><td data-parity="CGWMainPartition.w_show.level_pid_host">' + esc(r.name) + '</td>' +
      idCell(m, r, 'CGWMainPartition.w_show.id') +
      '<td data-parity="CGWMainPartition.w_show.monitor">' + MARK[shown(m, r, 'monitor')] + '</td>';
    tr.querySelector('.cell-id').addEventListener('click', () => { toggleDetector(m, r); renderShowTable(); });
    tb.appendChild(tr);
  }
}

function fillSelectTable(plat) { S.ptab.select = makeModel(plat, false); renderSelectTable(); }
function fillShowTable(plat) { S.ptab.show = makeModel(plat, true); renderShowTable(); }

function tableToPlatform() {
  // CGWPartitionTable.fill_output_object + CGJsonUtils.set_platform: a collapsed detector's sel column gives the
  // collapser's own state (_old_check_state), its Monitor column the shown state (DICT_CHECK_BOX_STATES: partial -> False)
  const plat = JSON.parse(JSON.stringify(S.status.platform || {}));
  const m = S.ptab.select;
  for (const r of (m ? m.rows : [])) {
    const p = plat[r.level] && plat[r.level][r.id];
    if (!p) continue;
    p.active = r.active ? 1 : 0;
    p.monitor = (isCollapser(m, r) ? shown(m, r, 'monitor') === 2 : r.monitor) ? 1 : 0;
    if (r.hasGrp && p.det_info && /^\d+$/.test(r.readout)) p.det_info.readout = parseInt(r.readout, 10);
  }
  return plat;
}

function renderCollection(plat) {   // CGWMainCollection.update_table, TABTITLE_H = drp, teb, meb; CGWPanelList cells
  const cols = ['drp', 'teb', 'meb'];
  const lists = cols.map((c) => {
    const lvl = (plat || {})[c] || {};
    return Object.keys(lvl).filter((k) => lvl[k].active === 1).map((k) => {
      const pi = lvl[k].proc_info || {};
      return pi.alias || (c + '/' + pi.pid + '/' + pi.host);
    });
  });
  const n = Math.max(0, ...lists.map((l) => l.length));
  const tb = $('collection').querySelector('tbody');
  tb.innerHTML = '';
  const tr = document.createElement('tr');
  lists.forEach((l, i) => {
    const td = document.createElement('td');
    td.dataset.col = cols[i];
    td.innerHTML = l.map((x) => '<div class="pitem" data-parity="CGWPanelList.fill_list_model@1">' + esc(x) + '</div>').join('');
    tr.appendChild(td);
  });
  if (n > 0) tb.appendChild(tr);
}

// ---------- render ----------
function render() {
  const st = S.status;
  const s = lower(st.state);
  const trans = lower(st.transition);
  $('instrument').textContent = 'instrument: ' + (st.instrument ?? '?');

  // CGWMainConfiguration.set_buts_enabled (:92-94) and set_config_type (:171-184)
  $('but_type').disabled = !['reset', 'unallocated', 'allocated', 'connected'].includes(s);
  const aliases = S.meta.aliases || [];
  if (aliases.includes(st.config_alias) && st.config_alias !== S.configTypeShown) {
    S.configTypeShown = st.config_alias;
  }
  $('but_type').textContent = (S.configTypeShown || 'Select') + ' ▼';
  $('but_type').dataset.value = S.configTypeShown || '';

  // CGWMainPartition.set_buts_enabled (:266-293)
  const doCtrl = ['reset', 'unallocated'].includes(s);
  $('but_select').disabled = !doCtrl;
  $('but_show').disabled = doCtrl;
  $('but_apply').disabled = !doCtrl;
  if (doCtrl && S.showOpen) setShow(false);
  if (s === 'unallocated') {
    const key = JSON.stringify(st.platform || {});
    if (!S.selectOpen || (trans === 'rollcall' && key !== S.selectPlatformKey)) {
      fillSelectTable(st.platform); S.selectPlatformKey = key;
    }
    S.selectOpen = true;
  } else {
    S.selectOpen = false;
  }
  $('select_window').hidden = !S.selectOpen;
  if (S.showOpen) {
    const key = JSON.stringify(st.platform || {});
    if (key !== S.showPlatformKey) { fillShowTable(st.platform); S.showPlatformKey = key; }
  }
  renderCollection(st.platform);

  // CGWMainControl.set_buts_enabled (:227-243)
  const rec = st.recording === true;
  const br = $('but_record');
  br.setAttribute('aria-pressed', rec ? 'true' : 'false');
  br.textContent = rec ? '\u25A0 recording ON' : '\u25CF recording OFF';
  br.disabled = !['reset', 'unallocated', 'allocated', 'connected', 'configured'].includes(s);
  $('box_state').disabled = ['reset', 'unallocated'].includes(s);
  for (const b of $('state_buttons').querySelectorAll('button')) {
    b.disabled = $('box_state').disabled || b.dataset.state === s;
  }
  $('but_ctrls').textContent = upper(st.state);
  $('but_ctrls').dataset.state = s;
  $('but_transition').textContent = upper(st.transition);
  $('but_transition').dataset.transition = trans;

  // progress bar: visible only while progress messages arrive (CGWMain.py:384-391, :309); the User tab has its own
  const pr = st.progress;
  for (const bar of [$('bar_progress'), $('bar_progress_user')]) {
    if (pr && pr.total) {
      bar.hidden = false;
      bar.querySelector('.fill').style.width = Math.min(100, 100 * pr.elapsed / pr.total) + '%';
      bar.querySelector('.plabel').textContent = pr.transition + ' ' + Math.round(100 * pr.elapsed / pr.total) + '%';
    } else {
      bar.hidden = true;
    }
  }

  // CGWMainTabUser.set_buts_enabled (:74-110): Play shows Pause while running, unlocked by every status message;
  // Record as in the Expert tab; Stop only in starting / paused / running
  const play = $('but_play');
  play.innerHTML = S.playLocked ? '&#8987;' : (s === 'running' ? '&#10074;&#10074;' : '&#9654;');
  play.dataset.icon = S.playLocked ? 'wait' : (s === 'running' ? 'pause' : 'start');
  play.disabled = S.playLocked;
  const ru = $('but_record_user');
  ru.setAttribute('aria-pressed', rec ? 'true' : 'false');
  ru.innerHTML = rec ? '&#9632;' : '&#9679;';
  ru.disabled = !['reset', 'unallocated', 'allocated', 'connected', 'configured'].includes(s);
  $('but_stop').hidden = !['starting', 'paused', 'running'].includes(s);
  $('user_state').textContent = upper(st.state) + (rec ? ', recording' : '');

  // CGWMainInfo.update_info (:90-95)
  const cond = rec && ['starting', 'paused', 'running'].includes(s);
  $('lab_run').textContent = cond ? 'run:' : 'last run:';
  $('edi_run').textContent = String(cond ? st.run_number : st.last_run_number);
  $('edi_exp').textContent = String(st.experiment_name);
  $('run_info').textContent = cond ? ('run ' + st.run_number + ' recording') : (rec ? 'recording armed' : 'not recording');
  renderEvents();
}

function renderEvents() {
  const ev = S.events || {};
  const e = $('edi_evt');
  e.textContent = (ev.events === null || ev.events === undefined) ? 'N/A' : String(ev.events);
  // For tests and tools: where the number came from, when, and whether it is final for the run.
  e.dataset.source = ev.source || '';
  e.dataset.ts = (ev.ts === null || ev.ts === undefined) ? '' : String(ev.ts);
  e.dataset.final = ev.final ? '1' : '0';
  $('edi_evd').textContent = (ev.drops === null || ev.drops === undefined) ? 'N/A' : String(ev.drops);
  $('events_source').textContent = 'events source: ' + (ev.source || '?') + (ev.ok === false && ev.error ? ' (' + ev.error + ')' : '');
}

function addLog(rec) {
  if (rec.seq <= S.lastSeq) return;
  S.lastSeq = rec.seq;
  const t = new Date(rec.ts * 1000).toTimeString().slice(0, 8);
  const line = document.createElement('div');
  line.className = 'lvl-' + rec.level;
  line.dataset.level = rec.level;
  if (rec.level === 'SEP') {   // QWLoggerStd.add_separator_err after a RESET (CGWMainControl.py:169)
    line.textContent = rec.msg;
    $('edi_err').appendChild(line);
    return;
  }
  line.textContent = t + ' ' + rec.level + ': ' + rec.msg;
  appendCapped($('edi_txt'), line);
  if (rec.level === 'ERROR' || rec.level === 'CRITICAL') appendCapped($('edi_err'), line.cloneNode(true));
}

function appendCapped(pre, node) {
  const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 4;
  pre.appendChild(node);
  while (pre.childNodes.length > 2000) pre.removeChild(pre.firstChild);
  if (atBottom) pre.scrollTop = pre.scrollHeight;
}

// ---------- actions ----------
function setShow(open) {   // CGWMainPartition.on_but_show / set_but_show_title
  S.showOpen = open;
  $('show_window').hidden = !open;
  $('but_show').textContent = open ? 'Close' : 'Show';
  $('but_show').title = open ? 'Close partitions window' : 'Show partitions';
  if (open) { fillShowTable(S.status.platform); S.showPlatformKey = JSON.stringify(S.status.platform || {}); }
}

function closeTypePopup() { $('popup_type').hidden = true; }

function setTab(name) {    // CGWMainTabs.on_tab_bar -> gui_selector: one of CGWMainTabUser / CGWMainTabExpert
  S.tab = name;
  $('panel_user').hidden = name !== 'user';
  $('panel_expert').hidden = name !== 'expert';
  $('tab_user').setAttribute('aria-selected', name === 'user' ? 'true' : 'false');
  $('tab_expert').setAttribute('aria-selected', name === 'expert' ? 'true' : 'false');
  document.body.dataset.tab = name;
  syncAccessKeys();
}

// Qt mnemonics ('&Apply' -> Alt+A).  An element declares its letter in data-accesskey (or a static accesskey, as
// the config editor's popups do); only one visible, enabled element per letter keeps the live accesskey
// attribute, because Chromium activates the FIRST element in document order with that accesskey even when it is
// hidden (QWPopupTableCheck '&Apply' and QWPopupEditText '&Apply' share Alt+A).  An open modal wins, as Qt's
// active window does.  Re-synced when Alt goes down, before the letter's keydown reaches the page.
function syncAccessKeys() {
  const els = [...document.querySelectorAll('[data-accesskey], [accesskey]')];
  const by = {};
  for (const el of els) {
    if (!el.dataset.accesskey) el.dataset.accesskey = el.getAttribute('accesskey');
    (by[el.dataset.accesskey.toLowerCase()] ||= []).push(el);
  }
  const vis = (el) => !el.disabled && (el.checkVisibility ? el.checkVisibility() : el.offsetParent !== null);
  for (const [k, list] of Object.entries(by)) {
    const live = list.filter(vis);
    const modal = live.filter((el) => el.closest('[role="dialog"], [role="alertdialog"], .cfg-modal'));
    const pick = (modal.length ? modal : live).slice(-1)[0];
    for (const el of list) {
      if (el === pick) el.setAttribute('accesskey', k); else el.removeAttribute('accesskey');
    }
  }
}

function wire() {
  // box_state: ['Select'] + states upper (CGWMainControl.py:70); change -> setState (:165-174)
  const box = $('box_state');
  box.innerHTML = ['Select', ...S.meta.states.map((x) => x.toUpperCase())]
    .map((x) => '<option value="' + x + '">' + x + '</option>').join('');
  box.addEventListener('change', () => {
    if (box.selectedIndex <= 0) return;
    post('/api/state', {state: box.value.toLowerCase()});
  });
  // QWCustomQComboBox (CGWMainControl.py:65): Key_Up / Key_Down are ignored (keyPressEvent, :17-22) so the target
  // state cannot change by accident; Left / Right do nothing on a Qt combo either.  Alt+Down still opens the list.
  box.addEventListener('keydown', (e) => {
    if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Up', 'Down', 'Left', 'Right'].includes(e.key) && !e.altKey) {
      e.preventDefault();
      box.dataset.ignoredKey = e.key;
    }
  });
  // wheelEvent (:24-25) ignores the wheel: the event goes on to the page (it scrolls) and the state never changes.
  // Not passive, so the browser hit-tests the wheel before it scrolls; it never calls preventDefault.
  box.addEventListener('wheel', () => { box.dataset.wheel = String((+box.dataset.wheel || 0) + 1); if (document.activeElement === box) box.blur(); }, {passive: false});
  $('state_buttons').innerHTML = S.meta.states.map((x) =>
    '<button data-state="' + x + '" title="setState(' + x + ')">' + x.toUpperCase() + '</button>').join(' ');
  for (const b of $('state_buttons').querySelectorAll('button')) {
    b.addEventListener('click', () => post('/api/state', {state: b.dataset.state}));
  }
  $('transition_buttons').innerHTML = S.meta.transitions.map((x) =>
    '<button data-transition="' + x + '" title="setTransition(' + x + ')">' + x + '</button>').join(' ');
  for (const b of $('transition_buttons').querySelectorAll('button')) {
    b.addEventListener('click', () => post('/api/transition', {transition: b.dataset.transition}));
  }
  // but_record: setRecord(not recording) (CGWMainControl.py:196-200)
  $('but_record').addEventListener('click', () => post('/api/record', {record: !(S.status.recording === true)}));
  // but_transition / but_ctrls only refresh (CGWMainControl.py:177-185)
  $('but_transition').addEventListener('click', refreshStatus);
  $('but_ctrls').addEventListener('click', refreshStatus);
  // Partition: Select -> rollcall (CGWMainPartition.py:108-113,256-262)
  $('but_select').addEventListener('click', () => post('/api/transition', {transition: 'rollcall'}));
  $('but_show').addEventListener('click', () => setShow(!S.showOpen));
  // Apply -> selectPlatform + setState('allocated') (QWPopupTableCheck.py:132-148)
  $('but_apply').addEventListener('click', () => post('/api/platform', {platform: tableToPlatform(), allocate: true}));
  // Configuration type popup (CGWMainConfiguration.on_but_type :146-168)
  $('but_type').addEventListener('click', async (e) => {
    e.stopPropagation();
    const pop = $('popup_type');
    if (!pop.hidden) { closeTypePopup(); return; }
    const r = await fetch('/api/aliases').then((x) => x.json()).catch(() => ({aliases: S.meta.aliases}));
    const list = (r.aliases && r.aliases.length) ? r.aliases : ['NOBEAM', 'BEAM'];
    S.meta.aliases = list;
    pop.innerHTML = list.map((a) => '<button role="option" data-value="' + esc(a) + '">' + esc(a) + '</button>').join('');
    for (const b of pop.querySelectorAll('button')) {
      b.addEventListener('click', async (ev) => {
        ev.stopPropagation();
        closeTypePopup();
        const sel = b.dataset.value;
        if (sel === S.configTypeShown) return;   // CGWMainConfiguration.py:161
        const j = await post('/api/config', {alias: sel});
        if (!j.ok) { S.configTypeShown = 'error'; render(); }
      });
    }
    pop.hidden = false;
  });
  document.addEventListener('click', closeTypePopup);
  // CGWMainTabs tab bar (CGWMainTabs.py:111-128): User | Expert
  $('tab_user').addEventListener('click', () => setTab('user'));
  $('tab_expert').addEventListener('click', () => setTab('expert'));
  // CGWMainTabUser.on_but_play (:216-235): running -> paused, anything else -> running; locked until the next status
  $('but_play').addEventListener('click', async () => {
    const cmd = lower(S.status.state) === 'running' ? 'paused' : 'running';
    S.playLocked = true; render();
    const j = await post('/api/state', {state: cmd});
    if (!j.ok) { S.playLocked = false; render(); }
  });
  // CGWMainTabUser.on_but_record (:256-262) and on_but_stop (:279-282)
  $('but_record_user').addEventListener('click', () => post('/api/record', {record: !(S.status.recording === true)}));
  $('but_stop').addEventListener('click', () => post('/api/state', {state: 'configured'}));
  document.addEventListener('keydown', (e) => { if (e.key === 'Alt') syncAccessKeys(); }, true);
  setTab(S.tab);
}

async function refreshStatus() {
  try { S.status = await fetch('/api/status').then((r) => r.json()); render(); } catch (e) { /* stream will resync */ }
}

function connect() {
  const es = new EventSource('/api/stream');
  es.addEventListener('hello', (e) => {
    const h = JSON.parse(e.data);
    const first = !S.meta.states.length;
    S.meta = h.meta; S.status = h.status; S.events = h.events;
    $('backend').textContent = 'backend: ' + h.meta.backend;
    $('backend').className = 'badge ' + (h.meta.backend === 'emulator' ? 'bad' : 'good');
    if (first) wire();
    for (const r of h.log) addLog(r);
    $('conn').textContent = 'connected'; $('conn').className = 'badge good';
    document.body.dataset.ready = '1';
    render();
  });
  es.addEventListener('status', (e) => { S.status = JSON.parse(e.data); S.playLocked = false; render(); });
  es.addEventListener('progress', (e) => { S.status.progress = JSON.parse(e.data); render(); });
  es.addEventListener('events', (e) => { S.events = JSON.parse(e.data); renderEvents(); });
  es.addEventListener('log', (e) => addLog(JSON.parse(e.data)));
  es.onerror = () => { $('conn').textContent = 'disconnected (retrying)'; $('conn').className = 'badge bad'; };
}

connect();
