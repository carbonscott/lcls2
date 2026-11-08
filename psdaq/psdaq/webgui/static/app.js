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

// ---------- platform helpers (CGJsonUtils.get_platform / get_status) ----------
function platformRows(plat) {
  const rows = [];
  for (const level of Object.keys(plat || {})) {
    for (const id of Object.keys(plat[level])) {
      const v = plat[level][id];
      const pi = v.proc_info || {};
      const hasGrp = (level === 'drp' || level === 'tpr');
      rows.push({
        level, id,
        active: v.active === 1,
        readout: hasGrp && v.det_info ? String(v.det_info.readout) : '',
        hasGrp,
        name: level + '/' + (pi.pid ?? 'non-def') + '/' + (pi.host ?? 'non-def'),
        alias: pi.alias ?? 'non-def',
        monitor: v.monitor === 1,
        hidden: v.hidden === 1,
      });
    }
  }
  // CGWPartitionTable.sort_items: by level/pid/host then alias
  rows.sort((a, b) => (a.level + a.alias).localeCompare(b.level + b.alias));
  return rows;
}

function renderCollection(plat) {   // CGWMainCollection.update_table, TABTITLE_H = drp, teb, meb
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
    td.innerHTML = l.map((x) => '<div class="pitem">' + esc(x) + '</div>').join('');
    tr.appendChild(td);
  });
  if (n > 0) tb.appendChild(tr);
}

function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c])); }

function fillSelectTable(plat) {    // QWPopupTableCheck / CGWPartitionTable with checkable cells
  const tb = $('select_table').querySelector('tbody');
  tb.innerHTML = '';
  const groups = S.meta.readout_groups.length ? S.meta.readout_groups : ['0', '1', '2', '3', '4', '5', '6', '7'];
  for (const r of platformRows(plat)) {
    const tr = document.createElement('tr');
    tr.dataset.level = r.level; tr.dataset.id = r.id; tr.dataset.alias = r.alias;
    if (r.hidden) tr.hidden = true;
    let grp = '';
    if (r.hasGrp) {
      const opts = groups.includes(r.readout) ? groups : [r.readout, ...groups];
      grp = '<select class="cell-grp" data-parity="CGWMainPartition.w_select.grp CGWPartitionTable.set_readout_group_number@1" title="readout group">' +
        opts.map((g) => '<option' + (g === r.readout ? ' selected' : '') + '>' + esc(g) + '</option>').join('') + '</select>';
    }
    tr.innerHTML =
      '<td><input type="checkbox" class="cell-sel" data-parity="CGWMainPartition.w_select.sel"' + (r.active ? ' checked' : '') + '></td>' +
      '<td>' + grp + '</td><td data-parity="CGWMainPartition.w_select.level_pid_host">' + esc(r.name) +
      '</td><td data-parity="CGWMainPartition.w_select.id">' + esc(r.alias) + '</td>' +
      '<td><input type="checkbox" class="cell-mon" data-parity="CGWMainPartition.w_select.monitor"' + (r.monitor ? ' checked' : '') + '></td>';
    tb.appendChild(tr);
  }
}

function fillShowTable(plat) {      // CGWMainPartition.on_but_show: active rows, read only
  const tb = $('show_table').querySelector('tbody');
  tb.innerHTML = '';
  for (const r of platformRows(plat).filter((x) => x.active)) {
    const tr = document.createElement('tr');
    tr.dataset.alias = r.alias;
    tr.innerHTML = '<td data-parity="CGWMainPartition.w_show.sel">' + (r.active ? '&#10003;' : '') +
      '</td><td data-parity="CGWMainPartition.w_show.grp">' + esc(r.readout) +
      '</td><td data-parity="CGWMainPartition.w_show.level_pid_host">' + esc(r.name) +
      '</td><td data-parity="CGWMainPartition.w_show.id">' + esc(r.alias) +
      '</td><td data-parity="CGWMainPartition.w_show.monitor">' + (r.monitor ? '&#10003;' : '') + '</td>';
    tb.appendChild(tr);
  }
}

function tableToPlatform() {        // CGJsonUtils.set_platform: active, monitor, readout back into the dict
  const plat = JSON.parse(JSON.stringify(S.status.platform || {}));
  for (const tr of $('select_table').querySelectorAll('tbody tr')) {
    const p = plat[tr.dataset.level] && plat[tr.dataset.level][tr.dataset.id];
    if (!p) continue;
    p.active = tr.querySelector('.cell-sel').checked ? 1 : 0;
    p.monitor = tr.querySelector('.cell-mon').checked ? 1 : 0;
    const g = tr.querySelector('.cell-grp');
    if (g && p.det_info) p.det_info.readout = parseInt(g.value, 10);
  }
  return plat;
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

  // progress bar: visible only while progress messages arrive (CGWMain.py:384-391, :309)
  const pr = st.progress;
  const bar = $('bar_progress');
  if (pr && pr.total) {
    bar.hidden = false;
    bar.querySelector('.fill').style.width = Math.min(100, 100 * pr.elapsed / pr.total) + '%';
    bar.querySelector('.plabel').textContent = pr.transition + ' ' + Math.round(100 * pr.elapsed / pr.total) + '%';
  } else {
    bar.hidden = true;
  }

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

function wire() {
  // box_state: ['Select'] + states upper (CGWMainControl.py:70); change -> setState (:165-174)
  const box = $('box_state');
  box.innerHTML = ['Select', ...S.meta.states.map((x) => x.toUpperCase())]
    .map((x) => '<option value="' + x + '">' + x + '</option>').join('');
  box.addEventListener('change', () => {
    if (box.selectedIndex <= 0) return;
    post('/api/state', {state: box.value.toLowerCase()});
  });
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
  es.addEventListener('status', (e) => { S.status = JSON.parse(e.data); render(); });
  es.addEventListener('progress', (e) => { S.status.progress = JSON.parse(e.data); render(); });
  es.addEventListener('events', (e) => { S.events = JSON.parse(e.data); renderEvents(); });
  es.addEventListener('log', (e) => addLog(JSON.parse(e.data)));
  es.onerror = () => { $('conn').textContent = 'disconnected (retrying)'; $('conn').className = 'badge bad'; };
}

connect();
