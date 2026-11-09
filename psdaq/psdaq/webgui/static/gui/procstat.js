// web copy of psdaq/procmgr/procstat: WinProcStat.onProcMgrUpdated / onProcCellClicked / onClick*.
'use strict';
const $ = (id) => document.getElementById(id);
const S = { seq: -1, mode: 0, curKey: '', sortCol: null, sortAsc: true, firstSort: false, rows: [],
            errSeq: null, closed: false, logOffset: 0, logId: null };

function sortKey(r, col) { return col === 0 ? r.showId : r.text; }   // QTableWidgetItem text order

function render() {
  const tb = $('procRows');
  let rows = S.rows.slice();
  if (S.sortCol !== null) {
    rows.sort((a, b) => { const x = sortKey(a, S.sortCol), y = sortKey(b, S.sortCol);
                          return (x < y ? -1 : x > y ? 1 : 0) * (S.sortAsc ? 1 : -1); });
  }
  tb.textContent = '';
  for (const r of rows) {
    const tr = document.createElement('tr');
    tr.dataset.id = r.showId;
    if (r.showId === S.curKey) { tr.classList.add('current'); tr.setAttribute('aria-current', 'true'); }
    const c0 = document.createElement('td'); c0.textContent = r.showId; c0.dataset.col = '0';
    const c1 = document.createElement('td'); c1.textContent = r.text; c1.dataset.col = '1';
    c1.dataset.status = r.status;
    if (r.rgb) { c1.style.background = `rgb(${r.rgb.join(',')})`; c1.style.color = 'rgb(255,255,255)'; }
    tr.append(c0, c1);
    tr.addEventListener('click', () => cellClicked(r.showId));
    tb.append(tr);
  }
  for (const th of document.querySelectorAll('#tableProcStat th')) {
    const c = +th.dataset.col;
    th.setAttribute('aria-sort', S.sortCol === c ? (S.sortAsc ? 'ascending' : 'descending') : 'none');
  }
}

function showWarning(title, text) {            // WinProcStat.showWarningWindow (non-modal msgBox)
  $('msgBoxTitle').textContent = title; $('msgBoxText').textContent = text;
  if (!$('msgBox').open) $('msgBox').show();
}

async function poll() {
  if (S.closed) return;
  try {
    const r = await fetch('/api/procstat/status', { cache: 'no-store' });
    const st = await r.json();
    if (!st.ok) { $('statusbar').textContent = st.err_info || 'error'; return; }
    $('cnf').textContent = `${st.cnf} (platform ${st.platform}, every ${st.interval} s)`;
    document.body.dataset.seq = st.seq;
    if (st.unknown_error) { unknownError(st.unknown_error); return; }
    if (st.error && st.error.seq !== S.errSeq) { S.errSeq = st.error.seq; showWarning(st.error.title, st.error.text); }
    if (st.seq !== S.seq) {
      $('statusbar').textContent = 'Refreshing ProcMgr status...';
      S.seq = st.seq; S.rows = st.rows; S.local = st.local_ids;
      if (!S.firstSort) { S.firstSort = true; S.sortCol = 1; S.sortAsc = true; }   // sortItems(1, Ascending)
      render();
      setTimeout(() => { if ($('statusbar').textContent.startsWith('Refreshing')) $('statusbar').textContent = ''; }, 150);
    }
  } catch (e) { $('statusbar').textContent = 'status request failed: ' + e; }
  if (S.mode === 2 && S.logId) followLog();
}

function unknownError(u) {                     // onProcMgrUnknownError: critical box, then close()
  if (S.closed) return;
  S.closed = true;
  $('criticalTitle').textContent = u.title;
  $('criticalText').textContent = u.report + ' ' + u.text;
  $('criticalBox').showModal();
}
$('criticalOk').addEventListener('click', () => { $('criticalBox').close(); $('win').hidden = true; $('closedNote').hidden = false; });
$('msgBoxOk').addEventListener('click', () => $('msgBox').close());
$('viewerClose').addEventListener('click', () => { $('viewer').hidden = true; S.logId = null; });

for (const b of document.querySelectorAll('button.checkable')) {    // onClickConsole / Logfile / Restart
  b.addEventListener('click', () => {
    const on = b.getAttribute('aria-pressed') !== 'true';
    for (const o of document.querySelectorAll('button.checkable')) o.setAttribute('aria-pressed', 'false');
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
    S.mode = on ? +b.dataset.mode : 0;
  });
}
for (const th of document.querySelectorAll('#tableProcStat th')) {   // sorting enabled: header click
  th.addEventListener('click', () => { const c = +th.dataset.col;
    if (S.sortCol === c) S.sortAsc = !S.sortAsc; else { S.sortCol = c; S.sortAsc = true; } render(); });
}

async function post(body) {
  const r = await fetch('/api/procstat/click', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                 body: JSON.stringify(body) });
  return r.json();
}

async function cellClicked(id) {               // currentCellChanged keeps sCurKey; then onProcCellClicked
  S.curKey = id; render();
  if (S.mode === 0) return;
  const mode = { 1: 'console', 2: 'logfile', 3: 'restart' }[S.mode];
  const rep = await post({ id, mode });
  if (rep.warning) { showWarning(rep.warning.title, rep.warning.text); return; }
  if (rep.restarted) { $('statusbar').textContent = 'restarted ' + rep.restarted; return; }
  if (!rep.opened) { $('statusbar').textContent = rep.why || rep.err_info || 'not opened'; return; }
  $('viewer').hidden = false;
  $('viewer').dataset.mode = mode; $('viewer').dataset.id = id;
  $('viewerTitle').textContent = (mode === 'console' ? 'console: ' : 'log: ') + rep.title +
                                 (rep.path ? ' (' + rep.path + ')' : rep.port ? ` (telnet ${rep.host} ${rep.port})` : '');
  $('viewerText').textContent = rep.text;
  if (mode === 'logfile') { S.logId = id; S.logOffset = rep.offset; } else S.logId = null;
}

async function followLog() {                   // less +F
  const rep = await post({ id: S.logId, mode: 'logfile', offset: S.logOffset });
  if (rep.opened && rep.text) { $('viewerText').textContent += rep.text; S.logOffset = rep.offset; }
}

poll();
setInterval(poll, 500);
