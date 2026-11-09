// Generic renderer of a pvgui page tree (psdaq/webgui/pvgui/__init__.py): the pvedit widgets in a browser.
'use strict';
const GUI = document.body.dataset.gui || new URLSearchParams(location.search).get('gui');
const W = {};            // node id -> {node, el, update(values, computed)}
const STACKS = [];       // [{select id, children els}]
let VALUES = {}, COMPUTED = {};
// A widget's own write wins over polls until the server reports it (or 3 s pass): a poll that left before the
// put landed must not undo the click (pvedit widgets only see monitor events, which come after the put).
const PENDING = {};
function sent(pv, v) { PENDING[pv] = { v, t: Date.now() }; }
function blocked(pv, q) {
  const p = PENDING[pv];
  if (!p) return false;
  if (q === p.v || Date.now() - p.t > 3000) { delete PENDING[pv]; return false; }
  return true;
}

function el(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === 'text') e.textContent = v; else if (v !== undefined && v !== null) e.setAttribute(k, v);
  }
  for (const k of kids) if (k) e.append(k);
  return e;
}
async function put(id, value) {
  const r = await fetch('/api/pvgui/put', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                           body: JSON.stringify({ gui: GUI, id, value }) });
  const rep = await r.json();
  document.getElementById('statusbar').textContent = rep.ok ? '' : (rep.err_info || 'put failed');
  return rep;
}
function fmtInt(v) { return (v === null || v === undefined) ? '-' : String(Math.trunc(Number(v))); }   // PvEditInt
function fmtIntOrArr(v) { return Array.isArray(v) ? v.map(x => ' ' + Number(x).toFixed(6)).join('') : fmtInt(v); }
function fmtDbl(v) { return (v === null || v === undefined) ? '-' : Number(v).toFixed(4); }           // PvEditDbl

function render(n) {
  switch (n.type) {
    case 'box': { const e = el('div', { class: n.dir === 'h' ? 'row' : 'col', hidden: n.hidden ? '' : null });
                  for (const c of n.children) e.append(render(c)); return e; }
    case 'group': { const e = el('fieldset', {}, el('legend', { text: n.title }));
                    for (const c of n.children) e.append(render(c)); return e; }
    case 'label': return el('span', { class: 'lbl', text: n.text });
    case 'grid': { const t = el('table', { class: 'grid' });
                   for (const r of n.rows) { const tr = el('tr');
                     for (const c of r) tr.append(el('td', {}, c ? render(c) : null)); t.append(tr); }
                   return t; }
    case 'tabs': {
      const bar = el('div', { class: 'tabs', role: 'tablist', 'data-parity': n.id });
      const panels = el('div');
      n.tabs.forEach((t, i) => {
        const b = el('button', { role: 'tab', 'data-parity': t.id, 'aria-selected': 'false', text: t.title });
        const p = el('div', { class: 'tabpanel', role: 'tabpanel', hidden: '' }, render(t.child));
        b.addEventListener('click', () => select(i));
        bar.append(b); panels.append(p);
      });
      function select(i) {
        [...bar.children].forEach((b, j) => b.setAttribute('aria-selected', j === i ? 'true' : 'false'));
        [...panels.children].forEach((p, j) => p.hidden = j !== i);
      }
      select(n.current || 0);
      return el('div', {}, bar, panels);
    }
    case 'stack': {
      const e = el('div', { class: 'stack' });
      const kids = n.children.map(c => { const k = el('div', { hidden: '' }, render(c)); e.append(k); return k; });
      STACKS.push({ select: n.select, kids });
      if (kids.length) kids[0].hidden = false;
      return e;
    }
    case 'pvcheck': {
      const cb = el('input', { type: 'checkbox', 'data-parity': n.id, 'data-pv': n.pv, id: 'w-' + n.id });
      cb.addEventListener('click', () => { sent(n.pv, cb.checked ? 1 : 0); put(n.id, cb.checked); });   // PvCheckBox.pvClicked
      W[n.id] = { node: n, el: cb, update: (v) => { const q = v[n.pv]; if (blocked(n.pv, q)) return;
        if (q !== null && q !== undefined) cb.checked = q != 0; } };
      return el('label', {}, cb, n.label ? ' ' + n.label : '');
    }
    case 'pvint': {
      const i = el('input', { class: 'pv-edit', 'data-parity': n.id, 'data-pv': n.pv, value: '-' });
      const fin = () => { if (!n.noop) put(n.id, i.value); };      // editingFinished (PvInt: setPv does nothing)
      i.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { fin(); i.dataset.sent = '1'; } });
      i.addEventListener('blur', () => { if (i.dataset.sent !== '1' && i.dataset.dirty === '1') fin(); i.dataset.sent = ''; i.dataset.dirty = ''; });
      i.addEventListener('input', () => { i.dataset.dirty = '1'; });
      W[n.id] = { node: n, el: i, update: (v) => { if (document.activeElement !== i) i.value = fmtIntOrArr(v[n.pv]); } };
      return i;
    }
    case 'pvdbl': {
      const i = el('input', { class: 'pv-edit', disabled: '', 'data-parity': n.id, 'data-pv': n.pv, value: '-' });
      W[n.id] = { node: n, el: i, update: (v) => { i.value = fmtDbl(v[n.pv]); } };
      return i;
    }
    case 'pvcombo': case 'seqsel': {
      const s = el('select', { 'data-parity': n.id, 'data-pv': n.pv, disabled: n.disabled ? '' : null });
      n.choices.forEach((c, k) => s.append(el('option', { value: k, text: c })));
      s.addEventListener('change', () => { sent(n.pv, +s.value); put(n.id, +s.value); stacks(); });   // currentIndexChanged
      W[n.id] = { node: n, el: s, update: (v) => { const q = v[n.pv]; if (blocked(n.pv, q)) return;
        if (q !== null && q !== undefined && q >= 0 && q < n.choices.length && +s.value !== q) s.value = q;
        if (n.validate_pair) s.classList.toggle('err', v[n.pv] === 0 && v[n.validate_pair] === 0); } };
      return s;
    }
    case 'mask': {
      const box = el('div', { class: 'row mask', 'data-pv': n.pv });
      const cbs = n.bits.map((b) => { const cb = el('input', { type: 'checkbox', 'data-parity': b.id, 'data-pv': n.pv });
        box.append(el('label', {}, b.label + ' ', cb)); return cb; });
      const send = () => { let m = 0; cbs.forEach((c, i) => { if (c.checked) m |= (1 << i); }); sent(n.pv, m); put(n.bits[0].id, m); };
      cbs.forEach(c => c.addEventListener('click', send));                                // PvMaskTab.setValue
      W[n.pv + '#mask'] = { node: n, el: box, update: (v) => { const q = v[n.pv];
        if (n.nomon) return;                            // tprca.PvDstTab: never reads the PV, only writes it
        if (blocked(n.pv, q)) return;
        if (q !== null && q !== undefined) cbs.forEach((c, i) => c.checked = !!(q & (1 << i)));
        if (n.validate === 'nonzero') box.classList.toggle('err', q === 0);
        else if (n.validate && n.validate.startsWith('pair:')) box.classList.toggle('err', q === 0 && v[n.validate.slice(5)] === 0); } };
      return box;
    }
    case 'button': {
      const b = el('button', { 'data-parity': n.id, text: n.label });
      b.addEventListener('click', async () => {
        const q = (f) => document.querySelector(`[data-parity="${CSS.escape(f)}"]`);
        const env = n.fields ? n.fields.map(f => q(f).value) : (n.env ? q(n.env).value : null);   // hsdpva Apply
        b.setAttribute('aria-pressed', 'true');
        await put(n.id, env);
        b.setAttribute('aria-pressed', 'false');                                         // setChecked(False)
      });
      return b;
    }
    case 'check': {
      const cb = el('input', { type: 'checkbox', 'data-parity': n.id });
      cb.addEventListener('click', () => put(n.id, cb.checked));                         // PvGroupStats.run
      W[n.id] = { node: n, el: cb, update: (v, c) => { const st = c['check:' + n.id]; if (st !== undefined) cb.checked = st; } };
      return el('label', {}, cb, ' ' + n.label);
    }
    case 'edit': return el('input', { class: 'pv-edit', 'data-parity': n.id, value: n.text });
    case 'localcombo': {                      // a QComboBox with no PV: switches its stack (hsdpva tabsel)
      const s = el('select', { 'data-parity': n.id });
      n.choices.forEach((c, k) => s.append(el('option', { value: k, text: c })));
      s.addEventListener('change', () => stacks());
      return s;
    }
    case 'fieldedit': {                       // a QLineEdit its PV's update() rewrites when the PV changes; no put
      const i = el('input', { class: 'pv-edit', 'data-parity': n.id, 'data-pv': n.pv, value: n.init === undefined ? '-' : n.init });
      W[n.id] = { node: n, el: i, update: (v, c) => { const t = c['text:' + n.id];
        if (t !== undefined && t !== i.dataset.last) { i.dataset.last = t; i.value = t; } } };
      return i;
    }
    case 'pvbutton': {                                                                  // PvPushButton: put 1, 0
      const b = el('button', { 'data-parity': n.id, 'data-pv': n.pv, text: n.label });
      b.addEventListener('click', () => put(n.id, 1));
      return b;
    }
    case 'pvedit': {                // a QLineEdit with the PyQt update()'s text (server side); Enter puts conv(text)
      const i = el('input', { class: 'pv-edit', 'data-parity': n.id, 'data-pv': n.pv, value: n.init === undefined ? '-' : n.init,
                              disabled: n.disabled ? '' : null });
      const fin = () => { put(n.id, i.value); };
      i.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { fin(); i.dataset.sent = '1'; } });
      i.addEventListener('blur', () => { if (i.dataset.sent !== '1' && i.dataset.dirty === '1') fin(); i.dataset.sent = ''; i.dataset.dirty = ''; });
      i.addEventListener('input', () => { i.dataset.dirty = '1'; });
      W[n.id] = { node: n, el: i, update: (v, c) => { const t = c['text:' + n.id];
        if (t !== undefined && document.activeElement !== i) i.value = t; } };
      return i;
    }
    case 'list': {                                         // a QListWidget the program fills (computed server side)
      const u = el('ul', { class: 'list', 'data-parity': n.id });
      W[n.id] = { node: n, el: u, update: (v, c) => { const items = c[n.source]; if (!Array.isArray(items)) return;
        if (u.dataset.items === JSON.stringify(items)) return;
        u.dataset.items = JSON.stringify(items); u.replaceChildren(...items.map(t => el('li', { text: t }))); } };
      return u;
    }
    case 'text': {                // a display whose text the server computes with the PyQt widget's update()
      const s = el('span', { class: 'pv', 'data-parity': n.id, 'data-pv': n.pv, text: n.init === undefined ? '-' : n.init });
      W[n.id] = { node: n, el: s, update: (v, c) => { const t = c['text:' + n.id]; if (t !== undefined) s.textContent = t; } };
      return n.label === undefined ? s : el('span', { class: 'row' }, el('span', { class: 'lbl', text: n.label }), s);
    }
    case 'value': {
      const s = el('span', { class: 'pv', 'data-parity': n.id });
      W[n.id] = { node: n, el: s, update: (v, c) => { const t = c[n.source]; if (t !== undefined) s.textContent = t; } };
      return s;
    }
  }
  return el('span', { text: '?' + n.type });
}
function stacks() {
  for (const st of STACKS) {
    const s = document.querySelector(`[data-parity="${CSS.escape(st.select)}"]`);
    const i = s ? +s.value : 0;
    st.kids.forEach((k, j) => k.hidden = j !== i);
  }
}
async function poll() {
  try {
    const r = await fetch('/api/pvgui/values?gui=' + encodeURIComponent(GUI), { cache: 'no-store' });
    const rep = await r.json();
    VALUES = rep.values; COMPUTED = rep.computed;
    for (const w of Object.values(W)) w.update(VALUES, COMPUTED);
    stacks();
    document.body.dataset.connected = rep.connected + '/' + rep.total;
    document.body.dataset.polls = (+(document.body.dataset.polls || 0) + 1);
  } catch (e) { document.getElementById('statusbar').textContent = 'values: ' + e; }
}
(async () => {
  const r = await fetch('/api/pvgui/spec?gui=' + encodeURIComponent(GUI));
  const spec = await r.json();
  if (!spec.ok) { document.getElementById('statusbar').textContent = spec.err_info; return; }
  document.title = spec.title; document.getElementById('title').textContent = spec.title;
  document.getElementById('page').append(render(spec.tree));
  document.body.dataset.ready = '1';
  await poll();
  setInterval(poll, 300);
})();
