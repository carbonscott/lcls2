/*
 * Viewer for the DAQ design model (daq-model.json).
 *
 * The model is the only source of content: this file holds the user
 * interface only. Every string about the DAQ (node and edge text, map
 * labels, captions, section texts, short names, kind names, lane and state
 * names) and every map coordinate is read from the JSON. Model text enters
 * the page only as DOM text nodes (never as HTML).
 *
 * The page is one map with three modes and one card under it:
 *   #map-section  #modes (Explore the parts, Follow one event, Compare
 *                 kinds), #mode-note, #chips (Emphasize), #tour-controls,
 *                 #stage (the map #map; the sequence chart #seq; the small
 *                 multiples #mult; captions), #tourbar, and the card:
 *                 #part-card in Explore (the overview, or one top-level part:
 *                 its detail #detail-view and the node panel #detail) or
 *                 #step-card in Follow one event (the step, its component
 *                 and its detail #tour-detail)
 *   #matrix       after the "Reference" divider: every relation between two
 *                 parts, as a reference card
 * There is one full-size map drawing in every mode: the tour runs on it.
 *
 * State: one hash route.
 *   #/              Explore; the card shows the overview
 *   #/node/<id>     Explore; the card shows the node's top-level part, the
 *                   node highlighted in its detail, the panel on the node
 *   #/tour/<k>      Follow one event, tour step k (1-based)
 *   #/compare       Compare kinds
 *   #/read          the whole model as one page; #/read/<id> scrolls to a node
 * No in-page click moves the page: clicks change the hash with
 * history.replaceState, focus() always uses preventScroll, and only the
 * controls marked [data-moves-page] (Back to the map, Read the full
 * description, a small multiple, a link to a part) or a link from outside
 * the page scroll it.
 *
 * Test hooks: see tools/README.md ("Viewer test hooks") and the interface
 * spec: body[data-ready], body[data-mode], #modes button.mode[data-mode],
 * #chips button.chip[data-kind], #kind-caption[data-kind], #map svg.map and
 * its g.box/path.ln/g.callout/g.tok, #part-card[data-card], #card-head,
 * #card-title[data-card], #card-prev, #card-next, #card-close, #overview,
 * #detail-view svg.detail[data-detail], #detail-title[data-node-id],
 * details.fold[data-fold], #card-foot, #step-card, #tour-step-title
 * [data-step-index], #tour-step-prose, #tour-detail svg.detail, #step-foot,
 * button.open-part, #tour-controls button.view[data-view], #seq .row
 * [data-step-index], #mult figure[data-kind], #tourbar, #pips button.pip,
 * button.fullsize, #matrix table.nsq td[data-from][data-to], #matrix-foot,
 * #read-page section[data-node-id], #help-toggle, #help, [data-moves-page].
 */
(function () {
  'use strict';

  const MODEL_URL = 'daq-model.json';
  const ROOT = '__root__';
  const SVG_NS = 'http://www.w3.org/2000/svg';

  // Relation kinds are user-interface enums (colours and line patterns in
  // viewer.css); their display names come from the model (map.kinds).
  const KIND_IDS = ['data', 'trigger', 'timing', 'control', 'monitoring'];
  const SOURCE_KIND_NAMES = {
    'site-page': 'This site',
    'confluence-public': 'Confluence',
    'confluence-internal': 'Confluence, internal space',
    'web': 'Web'
  };

  // ------------------------------------------------------------------
  // Model index
  // ------------------------------------------------------------------
  let model = null;
  const idx = {
    nodes: new Map(),     // id -> node
    children: new Map(),  // parent id (or ROOT) -> [child ids] in JSON order
    sources: new Map(),   // id -> source
    edges: [],
    edgeById: new Map(),
    steps: []
  };
  const lay = {
    map: null,            // model.map or null
    kindName: new Map(),  // kind id -> display name
    lineById: new Map(),
    boxes: [],            // {box, part}
    boxById: new Map(),
    tourByStep: new Map() // step id -> map.tour entry
  };

  function buildIndex(m) {
    const list = (x) => (Array.isArray(x) ? x : []);
    list(m.nodes).forEach((n) => {
      if (n && typeof n.id === 'string' && !idx.nodes.has(n.id)) idx.nodes.set(n.id, n);
    });
    idx.children.set(ROOT, []);
    for (const n of idx.nodes.values()) {
      const p = (typeof n.parent === 'string' && idx.nodes.has(n.parent)) ? n.parent : ROOT;
      if (!idx.children.has(p)) idx.children.set(p, []);
      idx.children.get(p).push(n.id);
    }
    list(m.sources).forEach((s) => { if (s && typeof s.id === 'string') idx.sources.set(s.id, s); });
    idx.edges = list(m.edges).filter((e) => e && idx.nodes.has(e.from) && idx.nodes.has(e.to));
    idx.edges.forEach((e) => idx.edgeById.set(e.id, e));
    idx.steps = list(m.tour && m.tour.steps).filter((s) => s && idx.nodes.has(s.node));

    const map = m.map && typeof m.map === 'object' ? m.map : null;
    lay.map = map;
    if (!map) return;
    list(map.kinds).forEach((k) => { if (k && k.id) lay.kindName.set(k.id, k.name); });
    list(map.lines).forEach((l) => { if (l && l.id) lay.lineById.set(l.id, l); });
    for (const id of childrenOf(ROOT)) {
      const place = idx.nodes.get(id).place;
      list(place && place.boxes).forEach((b) => {
        if (!b || !b.id) return;
        lay.boxes.push({ box: b, part: id });
        lay.boxById.set(b.id, { box: b, part: id });
      });
    }
    list(map.tour).forEach((t) => { if (t && t.step) lay.tourByStep.set(t.step, t); });
  }

  function childrenOf(id) { return idx.children.get(id) || []; }
  function parentOf(id) {
    const n = idx.nodes.get(id);
    return (n && typeof n.parent === 'string' && idx.nodes.has(n.parent)) ? n.parent : ROOT;
  }
  function titleOf(id) { return id === ROOT ? model.title : (idx.nodes.get(id) || {}).title || id; }
  function topOf(id) {
    let cur = id;
    const seen = new Set();
    while (parentOf(cur) !== ROOT && !seen.has(cur)) { seen.add(cur); cur = parentOf(cur); }
    return cur;
  }
  function isDesc(id, anc) {
    let cur = id;
    const seen = new Set();
    while (cur !== ROOT && !seen.has(cur)) {
      if (cur === anc) return true;
      seen.add(cur);
      cur = parentOf(cur);
    }
    return false;
  }
  function pathTo(id) {
    const path = [];
    let cur = id;
    const seen = new Set();
    while (cur !== ROOT && idx.nodes.has(cur) && !seen.has(cur)) {
      seen.add(cur);
      path.unshift(cur);
      cur = parentOf(cur);
    }
    return path;
  }
  function subtreeOf(id) {
    const out = new Set([id]);
    const stack = [id];
    while (stack.length) {
      for (const c of childrenOf(stack.pop())) {
        if (!out.has(c)) { out.add(c); stack.push(c); }
      }
    }
    return out;
  }
  function shortOf(part) {
    const n = idx.nodes.get(part);
    return (n && n.place && typeof n.place.short === 'string' && n.place.short) || titleOf(part);
  }
  function kindName(k) { return lay.kindName.get(k) || k; }
  function isOut(id) { const n = idx.nodes.get(id); return !!(n && n.outside_repo === true); }
  function section(key) { return (lay.map && lay.map.sections && lay.map.sections[key]) || {}; }

  // ------------------------------------------------------------------
  // Small DOM helpers
  // ------------------------------------------------------------------
  function el(tag, attrs, children) {
    const e = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v === undefined || v === null || v === false) continue;
        if (k === 'text') e.textContent = v;
        else if (k === 'class') e.className = v;
        else if (k === 'dataset') Object.assign(e.dataset, v);
        else e.setAttribute(k, v === true ? '' : v);
      }
    }
    for (const c of children || []) {
      if (c !== null && c !== undefined) e.append(c);
    }
    return e;
  }
  function S(tag, attrs, parent) {
    const e = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === undefined || v === null) continue;
      e.setAttribute(k, v);
    }
    if (parent) parent.appendChild(e);
    return e;
  }
  function stext(parent, x, y, s, cls, attrs) {
    const t = S('text', Object.assign({ x: x, y: y, class: cls }, attrs || {}), parent);
    t.textContent = s;
    return t;
  }
  // A text of several lines; each line but the last keeps a trailing space so
  // that the element's text reads as the original string.
  function stextLines(parent, x, y, lines, cls, lineH, attrs) {
    const t = S('text', Object.assign({ x: x, y: y, class: cls }, attrs || {}), parent);
    lines.forEach((s, i) => {
      const ts = S('tspan', { x: x, dy: i ? lineH : 0 }, t);
      ts.textContent = i < lines.length - 1 ? s + ' ' : s;
    });
    return t;
  }
  function $(id) { return document.getElementById(id); }
  function isExternal(url) { return /^https?:\/\//i.test(url); }
  function link(url, text, cls) {
    const a = el('a', { href: url, class: cls, text: text });
    if (isExternal(url)) { a.target = '_blank'; a.rel = 'noopener noreferrer'; }
    return a;
  }
  function nodeHash(id) { return id === ROOT ? '#/' : '#/node/' + encodeURIComponent(id); }
  function readHash(id) { return id === ROOT || !id ? '#/read' : '#/read/' + encodeURIComponent(id); }
  function go(hash) {
    if (location.hash === hash || (hash === '#/' && (location.hash === '' || location.hash === '#'))) route(true);
    else location.hash = hash;
  }
  // In-page clicks change the address without a history entry and without
  // a hashchange (so nothing scrolls).
  function setHash(hash) {
    if (location.hash === hash) return;
    try { history.replaceState(null, '', hash); } catch (e) { /* a sandboxed frame */ }
  }
  // Move the focus without scrolling the page.
  function focusQuietly(node) {
    if (node && typeof node.focus === 'function') node.focus({ preventScroll: true });
  }
  // The only scrolls of the page: deep links and [data-moves-page] controls.
  function scrollToTop(node, smooth) {
    if (node) node.scrollIntoView({ block: 'start', behavior: smooth && !reducedMotion() ? 'smooth' : 'auto' });
  }
  function onActivate(node, fn) {
    node.addEventListener('click', fn);
    node.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); fn(ev); }
    });
  }
  function reducedMotion() { return window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches; }
  const r1 = (v) => Math.round(v * 10) / 10;

  // ------------------------------------------------------------------
  // Text measuring (after document.fonts.ready): a hidden SVG with the same
  // classes as the figures, so the widths are those of the drawn text.
  // ------------------------------------------------------------------
  let measureSvg = null;
  const measureCache = new Map();
  function measure(text, cls, wrapCls) {
    const key = (wrapCls || '') + '|' + cls + '|' + text;
    if (measureCache.has(key)) return measureCache.get(key);
    if (!measureSvg) {
      measureSvg = S('svg', { class: 'measure', 'aria-hidden': 'true', focusable: 'false' });
      document.body.appendChild(measureSvg);
    }
    const g = S('g', { class: wrapCls || '' }, measureSvg);
    const t = stext(g, 0, 20, text, cls);
    let w = 0;
    try { w = t.getComputedTextLength(); } catch (e) { w = text.length * 7; }
    measureSvg.removeChild(g);
    measureCache.set(key, w);
    return w;
  }
  // Greedy word wrap by measured width.
  function wrapText(text, maxW, cls, wrapCls) {
    const words = String(text).split(/\s+/).filter(Boolean);
    const lines = [];
    let line = '';
    for (const w of words) {
      const next = line ? line + ' ' + w : w;
      if (line && measure(next, cls, wrapCls) + 4 > maxW) { lines.push(line); line = w; } else line = next;
    }
    if (line) lines.push(line);
    return lines;
  }
  function widest(lines, cls, wrapCls) {
    return lines.reduce((m, s) => Math.max(m, measure(s, cls, wrapCls) + 4), 0);
  }
  function longestWord(text, cls, wrapCls) {
    return String(text).split(/\s+/).filter(Boolean).reduce((m, w) => Math.max(m, measure(w, cls, wrapCls) + 4), 0);
  }

  // ------------------------------------------------------------------
  // Prose markup: paragraphs on blank lines, `code`, [text](url),
  // [[node-id]] and [[node-id|text]]. Everything else is literal text.
  // ------------------------------------------------------------------
  const INLINE_RE = /`([^`]+)`|\[\[([^\]|]+)(?:\|([^\]]+))?\]\]|\[([^\]]+)\]\(([^()\s]+)\)/g;
  let xrefHash = nodeHash;  // the one-page view links cross-references to its own sections

  function safeUrl(url) {
    if (isExternal(url)) return true;
    if (url.startsWith('//')) return false;
    return !/^[a-z][a-z0-9+.-]*:/i.test(url);  // relative URLs only, no other schemes
  }
  function appendInline(parent, text) {
    let last = 0;
    let m;
    INLINE_RE.lastIndex = 0;
    while ((m = INLINE_RE.exec(text)) !== null) {
      if (m.index > last) parent.append(text.slice(last, m.index));
      last = INLINE_RE.lastIndex;
      if (m[1] !== undefined) {
        parent.append(el('code', { text: m[1] }));
      } else if (m[2] !== undefined) {
        const id = m[2].trim();
        if (idx.nodes.has(id)) parent.append(nodeLink(id, m[3] !== undefined ? m[3] : titleOf(id), 'xref'));
        else parent.append(m[0]);
      } else if (safeUrl(m[5])) {
        const a = link(m[5], '', 'prose-link');
        appendCodeOnly(a, m[4]);
        parent.append(a);
      } else {
        parent.append(m[0]);
      }
    }
    if (last < text.length) parent.append(text.slice(last));
  }
  // A link to a node is a deep link: it may bring the node's card (or, in
  // the one-page view, its section) into view, so it is marked
  // [data-moves-page].
  function nodeLink(id, text, cls) {
    const a = link(xrefHash(id), text, cls);
    a.setAttribute('data-moves-page', '');
    return a;
  }
  function appendCodeOnly(parent, text) {
    const parts = text.split(/`([^`]+)`/);
    parts.forEach((part, i) => { if (part) parent.append(i % 2 ? el('code', { text: part }) : part); });
  }
  function prose(text, attrs) {
    const box = el('div', Object.assign({ class: 'prose' }, attrs || {}));
    if (typeof text !== 'string') return box;
    for (const para of text.split(/\n[ \t]*\n/)) {
      if (!para.trim()) continue;
      const p = el('p');
      appendInline(p, para);
      box.append(p);
    }
    return box;
  }
  function inlineProse(tag, text, cls) {
    const e = el(tag, { class: cls });
    if (typeof text === 'string') appendInline(e, text.replace(/\s*\n\s*/g, ' '));
    return e;
  }
  // ------------------------------------------------------------------
  // Routing
  // ------------------------------------------------------------------
  let state = null;

  function parseHash(hash) {
    let h = String(hash === undefined ? location.hash : hash).replace(/^#/, '');
    try { h = decodeURIComponent(h); } catch (e) { /* keep the raw text */ }
    if (h === '' || h === '/') return { mode: 'explore', focus: ROOT };
    let m = /^\/node\/(.+)$/.exec(h);
    if (m) {
      if (idx.nodes.has(m[1])) return { mode: 'explore', focus: m[1] };
      return { mode: 'explore', focus: ROOT, message: 'There is no part with the id "' + m[1] + '" in the design model. Showing the overview.' };
    }
    m = /^\/tour(?:\/(\d+))?\/?$/.exec(h);
    if (m) {
      const k = m[1] === undefined ? 1 : parseInt(m[1], 10);
      if (k >= 1 && k <= idx.steps.length) return { mode: 'tour', step: k, focus: ROOT };
      return { mode: 'explore', focus: ROOT, message: 'There is no tour step ' + m[1] + '. Showing the overview.' };
    }
    if (/^\/compare\/?$/.test(h)) return { mode: 'compare', focus: ROOT };
    m = /^\/read(?:\/(.+?))?\/?$/.exec(h);
    if (m) {
      const target = m[1] && idx.nodes.has(m[1]) ? m[1] : null;
      return { mode: 'read', focus: ROOT, target: target };
    }
    return { mode: 'explore', focus: ROOT, message: 'Unknown link "#' + h + '". Showing the overview.' };
  }

  // Show the state of the address. `land` is true for a deep link (the page
  // was opened at this address, or the address changed from outside): the
  // page then scrolls to what the link names. In-page clicks never call
  // route(); they change the state directly and replace the address.
  function route(land) {
    if (!model) return;
    const prev = state;
    state = parseHash();
    showMessage(state.message || '');
    const reading = state.mode === 'read';
    $('read-page').hidden = !reading;
    $('studies').hidden = reading || !lay.map;
    $('read-toggle').textContent = reading ? 'Back to the map' : 'Read as one page';
    $('read-toggle').setAttribute('aria-pressed', reading ? 'true' : 'false');
    if (reading) {
      clearPlace();
      document.body.dataset.mode = 'read';
      renderReadPage(state);
      return;
    }
    if (!lay.map) { document.body.dataset.mode = 'explore'; return; }
    // a deep link scrolls to what it names, so no spacer is kept for it
    if (state.mode === 'tour') {
      ui.view = 'map';
      tourIndex = state.step - 1;
      setMode('tour');
      // a link to a tour step brings the map section to the top of the
      // window and puts the focus in it, so that Left and Right move the tour
      if (land) { clearPlace(); scrollToTop($('map-section')); focusQuietly($('map-section')); }
    } else if (state.mode === 'compare') {
      setMode('compare');
      if (land) { clearPlace(); scrollToTop($('map-section')); }
    } else {
      setMode('explore');
      if (state.focus !== ROOT) {
        openNode(state.focus);
        // a link to a node brings its card to the top of the window
        if (land) { clearPlace(); scrollToTop($('part-card')); focusQuietly($('card-title')); }
      } else {
        showOverview();
        if (land) clearPlace();
        if (land && prev && prev.mode === 'read') window.scrollTo(0, 0);
      }
    }
  }

  function showMessage(text, isError) {
    const box = $('message');
    box.textContent = text;
    box.hidden = !text;
    box.classList.toggle('error', !!isError);
  }

  // ------------------------------------------------------------------
  // Map geometry helpers (SVG user units of the map viewBox)
  // ------------------------------------------------------------------
  function laneYs() {
    const l = lay.map && lay.map.lanes;
    return l && Array.isArray(l.y) ? l.y : [];
  }
  // Rectangles of a box: one per lane for a per-lane box.
  function boxCopies(b) {
    if (b.per_lane) {
      return laneYs().map((ly, i) => ({ key: b.id + '@' + i, lane: i, x: b.x, y: ly - b.h / 2, w: b.w, h: b.h }));
    }
    return [{ key: b.id, lane: null, x: b.x, y: b.y, w: b.w, h: b.h }];
  }
  // Box keys named by a line's through/ends entry, for one copy of the line.
  function resolveBoxKeys(name, lane) {
    const at = String(name).indexOf('@');
    if (at >= 0) return [String(name)];
    const entry = lay.boxById.get(name);
    if (!entry) return [String(name)];
    if (!entry.box.per_lane) return [name];
    if (lane !== null && lane !== undefined) return [name + '@' + lane];
    return laneYs().map((y, i) => name + '@' + i);
  }
  function rectOfKey(key) {
    const at = key.indexOf('@');
    const id = at >= 0 ? key.slice(0, at) : key;
    const entry = lay.boxById.get(id);
    if (!entry) return null;
    const copies = boxCopies(entry.box);
    if (at >= 0) return copies.find((c) => c.key === key) || null;
    return copies[0] || null;
  }
  // "{y}", "{y-28}", "{y+28}" in a per-lane path stand for the lane's y.
  function laneD(d, y) {
    return String(d).replace(/\{y(?:([+-])(\d+(?:\.\d+)?))?\}/g, (all, sign, n) => {
      if (!sign) return String(y);
      return String(r1(sign === '+' ? y + parseFloat(n) : y - parseFloat(n)));
    });
  }
  // Parse an SVG path (M, L, H, V, C and their relative forms, Z) into
  // subpaths of segments.
  function parsePath(d) {
    const toks = String(d).match(/[MLHVCZmlhvcz]|-?\d*\.?\d+(?:e[-+]?\d+)?/g) || [];
    const subs = [];
    let i = 0;
    let cmd = null;
    let x = 0;
    let y = 0;
    let sx = 0;
    let sy = 0;
    let cur = null;
    const num = () => parseFloat(toks[i++]);
    while (i < toks.length) {
      if (/[A-Za-z]/.test(toks[i])) cmd = toks[i++];
      if (!cmd) break;
      const rel = cmd === cmd.toLowerCase();
      const C = cmd.toUpperCase();
      if (C === 'Z') {
        if (cur) cur.segs.push({ type: 'L', a: [x, y], b: [sx, sy] });
        x = sx; y = sy;
        cmd = null;
        continue;
      }
      if (C === 'M') {
        const nx = num(); const ny = num();
        x = rel ? x + nx : nx; y = rel ? y + ny : ny;
        sx = x; sy = y;
        cur = { start: [x, y], segs: [] };
        subs.push(cur);
        cmd = rel ? 'l' : 'L';
        continue;
      }
      if (!cur) { cur = { start: [x, y], segs: [] }; subs.push(cur); }
      if (C === 'L') {
        const nx = num(); const ny = num();
        const b = [rel ? x + nx : nx, rel ? y + ny : ny];
        cur.segs.push({ type: 'L', a: [x, y], b: b }); x = b[0]; y = b[1];
      } else if (C === 'H') {
        const nx = num();
        const b = [rel ? x + nx : nx, y];
        cur.segs.push({ type: 'L', a: [x, y], b: b }); x = b[0];
      } else if (C === 'V') {
        const ny = num();
        const b = [x, rel ? y + ny : ny];
        cur.segs.push({ type: 'L', a: [x, y], b: b }); y = b[1];
      } else if (C === 'C') {
        const v = [num(), num(), num(), num(), num(), num()];
        const p = (k) => [rel ? x + v[k] : v[k], rel ? y + v[k + 1] : v[k + 1]];
        const c1 = p(0); const c2 = p(2); const b = p(4);
        cur.segs.push({ type: 'C', a: [x, y], c1: c1, c2: c2, b: b }); x = b[0]; y = b[1];
      } else {
        i++;
      }
    }
    return subs;
  }
  function subEnd(sub) { return sub.segs.length ? sub.segs[sub.segs.length - 1].b : sub.start; }
  function segIntersect(p, q, a, b) {
    const d = (q[0] - p[0]) * (b[1] - a[1]) - (q[1] - p[1]) * (b[0] - a[0]);
    if (Math.abs(d) < 1e-9) return null;
    const t = ((a[0] - p[0]) * (b[1] - a[1]) - (a[1] - p[1]) * (b[0] - a[0])) / d;
    const u = ((a[0] - p[0]) * (q[1] - p[1]) - (a[1] - p[1]) * (q[0] - p[0])) / d;
    if (t < -1e-9 || t > 1 + 1e-9 || u < -1e-9 || u > 1 + 1e-9) return null;
    return [p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])];
  }
  function rectEdges(r) {
    const a = [r.x, r.y]; const b = [r.x + r.w, r.y]; const c = [r.x + r.w, r.y + r.h]; const d = [r.x, r.y + r.h];
    return [[a, b], [b, c], [c, d], [d, a]];
  }
  function onBorder(pt, r, tol) {
    const inX = pt[0] >= r.x - tol && pt[0] <= r.x + r.w + tol;
    const inY = pt[1] >= r.y - tol && pt[1] <= r.y + r.h + tol;
    if (!inX || !inY) return false;
    return Math.abs(pt[0] - r.x) <= tol || Math.abs(pt[0] - r.x - r.w) <= tol ||
      Math.abs(pt[1] - r.y) <= tol || Math.abs(pt[1] - r.y - r.h) <= tol;
  }
  function bezPt(s, t) {
    const u = 1 - t;
    const f = (k) => u * u * u * s.a[k] + 3 * u * u * t * s.c1[k] + 3 * u * t * t * s.c2[k] + t * t * t * s.b[k];
    return [f(0), f(1)];
  }
  // Ports (derived, spec 1.1): where a line's segments cross the border of
  // one of its `through` boxes, and where it touches an `ends` box border.
  function portsOf(d, throughKeys, endsKeys) {
    const subs = parsePath(d);
    const pts = [];
    const add = (p) => { if (!pts.some((q) => Math.abs(q[0] - p[0]) < 0.6 && Math.abs(q[1] - p[1]) < 0.6)) pts.push([r1(p[0]), r1(p[1])]); };
    const through = throughKeys.map(rectOfKey).filter(Boolean);
    const ends = endsKeys.map(rectOfKey).filter(Boolean);
    for (const sub of subs) {
      for (const seg of sub.segs) {
        const pieces = [];
        if (seg.type === 'L') pieces.push([seg.a, seg.b]);
        else { let prev = seg.a; for (let k = 1; k <= 24; k++) { const p = bezPt(seg, k / 24); pieces.push([prev, p]); prev = p; } }
        for (const r of through) {
          for (const [p, q] of pieces) for (const [a, b] of rectEdges(r)) { const x = segIntersect(p, q, a, b); if (x) add(x); }
        }
      }
      for (const p of [sub.start, subEnd(sub)]) {
        if (ends.some((r) => onBorder(p, r, 2))) add(p);
      }
    }
    return pts;
  }

  // ------------------------------------------------------------------
  // Map figures (Study 1, the tour map and the small multiples)
  // ------------------------------------------------------------------
  let markerUid = 0;
  function markers(svg) {
    const id = 'mk' + (++markerUid);
    const defs = S('defs', null, svg);
    KIND_IDS.concat(['ink', 'out']).forEach((k) => {
      const s = k === 'data' ? 11 : 9;
      const m = S('marker', { id: id + '-' + k, viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: s, markerHeight: s, markerUnits: 'userSpaceOnUse', orient: 'auto-start-reverse' }, defs);
      S('path', { d: 'M0,0 L10,5 L0,10 z', class: 'mk ' + k }, m);
    });
    return (k) => 'url(#' + id + '-' + k + ')';
  }

  function buildMap(host, opt) {
    opt = opt || {};
    const M = lay.map;
    const mini = !!opt.mini;
    const vb = M.viewbox || { w: 1200, h: 690 };
    host.textContent = '';
    const svg = S('svg', {
      viewBox: '0 0 ' + vb.w + ' ' + vb.h,
      class: 'map' + (mini ? ' mini' : '') + (opt.pick ? ' pick' : ''),
      role: opt.pick ? 'group' : 'img',
      'aria-label': opt.label
    }, host);
    if (opt.kind) svg.setAttribute('data-kind', opt.kind);
    const mk = markers(svg);
    const G = {};
    ['guides', 'lines', 'boxes', 'ports', 'labels', 'call', 'tok'].forEach((k) => { G[k] = S('g', { class: 'layer-' + k }, svg); });
    const reg = { lines: new Map(), boxes: new Map(), parts: new Map(), all: [] };
    const addReg = (e, kind, lineId) => {
      e.dataset.k = kind;
      reg.all.push(e);
      if (lineId) { if (!reg.lines.has(lineId)) reg.lines.set(lineId, []); reg.lines.get(lineId).push(e); }
      return e;
    };
    const cols = Array.isArray(M.columns) ? M.columns : [];
    const bands = Array.isArray(M.bands) ? M.bands : [];
    const lys = laneYs();

    // guides between columns and between bands
    if (cols.length && bands.length) {
      const top = bands[0].y;
      const bottom = bands[bands.length - 1].y + bands[bands.length - 1].h;
      const left = cols[0].x;
      const right = cols[cols.length - 1].x + cols[cols.length - 1].w;
      for (let i = 0; i + 1 < cols.length; i++) {
        const x = r1((cols[i].x + cols[i].w + cols[i + 1].x) / 2);
        S('line', { x1: x, y1: mini ? Math.max(0, top - 26) : top, x2: x, y2: bottom, class: 'guide' }, G.guides);
      }
      for (let i = 0; i + 1 < bands.length; i++) {
        const y = bands[i].y + bands[i].h;
        S('line', { x1: left, y1: y, x2: right, y2: y, class: 'guide' }, G.guides);
      }
      if (!mini) {
        cols.forEach((c) => {
          const g = S('g', { class: 'column-label', 'data-column': c.n }, G.guides);
          stext(g, c.x + c.w / 2, top - 12, c.n + ' ' + c.name, 't-axis', { 'text-anchor': 'middle' });
        });
        bands.forEach((b) => {
          const g = S('g', { class: 'band-label', 'data-band': b.id }, G.guides);
          (Array.isArray(b.labels) ? b.labels : []).forEach((l) => stext(g, l.x, l.y, l.text, 't-band'));
        });
      }
    }

    // lines (drawn under the boxes)
    const lineList = Array.isArray(M.lines) ? M.lines : [];
    const portJobs = [];
    lineList.forEach((l) => {
      const copies = l.per_lane ? lys.map((y, i) => ({ lane: i, y: y })) : [{ lane: null, y: null }];
      copies.forEach((c) => {
        const d = c.lane === null ? String(l.d) : laneD(l.d, c.y);
        const through = [].concat(...(l.through || []).map((n) => resolveBoxKeys(n, c.lane)));
        const ends = [].concat(...(l.ends || []).map((n) => resolveBoxKeys(n, c.lane)));
        const subs = String(d).split(/(?=[Mm])/).map((s) => s.trim()).filter(Boolean);
        const pieces = (l.arrow && l.arrow !== 'none' && subs.length > 1) ? subs : [d];
        pieces.forEach((pd) => {
          const a = {
            d: pd, class: 'ln ' + l.kind + (l.out ? ' out' : ''),
            'data-line': l.id, 'data-kind': l.kind, 'data-edge-ids': (l.edges || []).join(' '),
            'data-through': through.join(' '), 'data-ends': ends.join(' ')
          };
          if (c.lane !== null) a['data-lane'] = c.lane;
          if (l.arrow === 'end' || l.arrow === 'both') a['marker-end'] = mk(l.out ? 'out' : l.kind);
          if (l.arrow === 'start' || l.arrow === 'both') a['marker-start'] = mk(l.out ? 'out' : l.kind);
          addReg(S('path', a, G.lines), l.kind, l.id);
        });
        portJobs.push({ l: l, d: d, through: through, ends: ends, lane: c.lane });
      });
    });

    // state ladder (control band): stations on one line
    const L = M.ladder;
    if (L && Array.isArray(L.states)) {
      const sx = (i) => L.x + i * L.dx;
      const T = Array.isArray(L.transitions) ? L.transitions : [];
      T.forEach((tr, i) => {
        addReg(S('path', { d: 'M' + sx(i) + ',' + L.y + ' H' + sx(i + 1), class: 'ln control', 'data-line': 'lad-' + i, 'data-kind': 'control', 'data-edge-ids': '', 'data-through': '', 'data-ends': '' }, G.lines), 'control', 'lad-' + i);
      });
      L.states.forEach((s, i) => {
        const li = 'lad-' + Math.max(0, Math.min(i, T.length - 1));
        addReg(S('circle', { cx: sx(i), cy: L.y, r: mini ? 8 : 5.5, class: 'port control', 'data-line': li }, G.ports), 'control');
        if (!mini) {
          addReg(stext(G.labels, sx(i), L.y - 14, s, 't-lab lab halo control', { 'text-anchor': 'middle', 'data-line': li }), 'control');
          if (i < T.length) addReg(stext(G.labels, (sx(i) + sx(i + 1)) / 2, L.y + 20, T[i], 't-lab lab halo control', { 'text-anchor': 'middle', 'data-line': 'lad-' + i }), 'control');
        }
      });
      if (!mini) {
        if (L.caption) stext(G.guides, L.x - 45, L.y - 50, L.caption, 't-band ladder-caption');
        if (L.note) stext(G.guides, L.x - 45, L.y + 50, L.note, 't-band ladder-note');
      }
    }

    // boxes
    let laneBoxMinX = Infinity;
    lay.boxes.forEach(({ box: b, part }) => {
      boxCopies(b).forEach((c) => {
        const g = S('g', { class: 'box', 'data-part': part, 'data-node': b.node || part, 'data-box': b.id }, G.boxes);
        if (c.lane !== null) { g.setAttribute('data-lane', c.lane); laneBoxMinX = Math.min(laneBoxMinX, c.x); }
        if (opt.pick) {
          g.setAttribute('tabindex', '0');
          g.setAttribute('role', 'button');
          g.setAttribute('aria-label', 'Open detail: ' + titleOf(part));
        }
        S('rect', { x: c.x, y: c.y, width: c.w, height: c.h, rx: 3, class: 'b' }, g);
        const subs = Array.isArray(b.sub) ? b.sub : (b.sub ? [b.sub] : []);
        const out = Array.isArray(b.out) ? !!b.out[c.lane || 0] : !!b.out;
        if (mini) {
          // the box's short title (mini) or title in one line at full size;
          // else the part's short name (for a box that stands for the whole
          // part); else two lines; else smaller
          const room = c.w - 14;
          let name = typeof b.mini === 'string' && b.mini ? b.mini : b.title;
          if (measure(name, 't-title', 'mini') > room && (b.node || part) === part && measure(shortOf(part), 't-title', 'mini') <= room) name = shortOf(part);
          let lines = [name];
          if (measure(name, 't-title', 'mini') > room) {
            const two = wrapText(name, room, 't-title', 'mini');
            if (two.length === 2) lines = two;
          }
          const wid = widest(lines, 't-title', 'mini');
          let size = Math.min(30, 30 * room / Math.max(1, wid));
          if (lines.length === 2) size = Math.min(size, (c.h - 8) / 2.1);
          const t = stextLines(g, c.x + c.w / 2, c.y + c.h / 2 + size * 0.35 - (lines.length - 1) * size * 0.525, lines, 't-title', r1(size * 1.05), { 'text-anchor': 'middle' });
          if (size < 30) t.style.fontSize = r1(size) + 'px';
        } else {
          const tx0 = typeof b.title_x === 'number' ? b.title_x : c.x + 11;
          stext(g, tx0, c.y + 21, b.title, 't-title');
          let lines;
          if (c.lane !== null) lines = subs.length > 1 ? (subs[c.lane] !== undefined ? [subs[c.lane]] : []) : subs.slice(0, 1);
          else lines = subs;
          lines.forEach((s, i) => stext(g, tx0, c.y + 38 + i * 15, s, 't-sub'));
          if (out) {
            const ow = r1(measure('outside repo', 't-out') + 10);
            S('rect', { x: r1(c.x + c.w - 7 - ow), y: c.y + 5, width: ow, height: 17, rx: 2, class: 'otag' }, g);
            stext(g, r1(c.x + c.w - 7 - ow / 2), c.y + 18, 'outside repo', 't-out', { 'text-anchor': 'middle' });
          }
        }
        reg.boxes.set(c.key, g);
        if (!reg.parts.has(part)) reg.parts.set(part, []);
        reg.parts.get(part).push(c);
        g.dataset.k = 'box';
        if (opt.pick && opt.onPick) onActivate(g, () => opt.onPick(part, g));
      });
    });

    // ports where lines meet box borders
    // Only shared lines (passing through a box, or meeting more than two
    // boxes) get port marks; a line between two boxes has none.
    portJobs.forEach((j) => {
      if (!j.through.length && j.ends.length <= 2) return;
      portsOf(j.d, j.through, j.ends).forEach((p) => {
        const a = { cx: p[0], cy: p[1], r: mini ? 6 : 3.6, class: 'port ' + j.l.kind, 'data-line': j.l.id };
        if (j.lane !== null) a['data-lane'] = j.lane;
        addReg(S('circle', a, G.ports), j.l.kind);
      });
    });

    if (!mini) {
      // labels of the lines
      (Array.isArray(M.labels) ? M.labels : []).forEach((lb) => {
        const l = lay.lineById.get(lb.line);
        const kind = l ? l.kind : (lb.kind || 'data');
        const out = !!(lb.out || (l && l.out));
        const lines = Array.isArray(lb.text) ? lb.text : [String(lb.text)];
        const t = S('text', { x: lb.x, y: lb.y, class: 't-lab lab halo ' + (out ? 'out' : kind), 'text-anchor': lb.anchor || 'start' }, G.labels);
        if (lb.line) t.setAttribute('data-line', lb.line);
        lines.forEach((s, i) => { const ts = S('tspan', { x: lb.x, dy: i ? 14 : 0 }, t); ts.textContent = s; });
        addReg(t, kind);
      });
      // notes
      (Array.isArray(M.notes) ? M.notes : []).forEach((n, k) => {
        const lines = Array.isArray(n.text) ? n.text : [String(n.text)];
        const t = S('text', { x: n.x, y: n.y, class: 't-note', 'data-note': k }, G.labels);
        lines.forEach((s, i) => { const ts = S('tspan', { x: n.x, dy: i ? 17 : 0 }, t); ts.textContent = s; });
      });
      // more lanes than drawn: a vertical ellipsis left of the lanes
      if (lys.length >= 3 && laneBoxMinX < Infinity) {
        stext(G.labels, laneBoxMinX - 9, (lys[lys.length - 2] + lys[lys.length - 1]) / 2 + 5, '\u22ee', 't-glyph', { 'aria-hidden': 'true' });
      }
    }

    // behaviour
    function setFocus(k) {
      reg.all.forEach((e) => {
        const isLine = e.classList.contains('ln') || e.classList.contains('port') || e.classList.contains('lab');
        e.classList.toggle('dim', !!k && k !== 'all' && isLine && e.dataset.k !== k);
        if (e.classList.contains('ln')) e.classList.toggle('focus', !!k && k !== 'all' && e.dataset.k === k);
      });
    }
    // The texts of the figure (not the selection's, not the tour dots') as
    // rectangles in viewBox units. They do not move once drawn; measured the
    // first time the figure is rendered (a hidden figure measures nothing).
    let textRects = null;
    function figureTexts() {
      if (textRects) return textRects;
      const list = [];
      svg.querySelectorAll('text').forEach((t) => {
        if (t.closest('.callout, .tok')) return;
        let b = null;
        try { b = t.getBBox(); } catch (e) { b = null; }
        if (b && b.width > 0 && b.height > 0) list.push({ x: b.x, y: b.y, w: b.width, h: b.height });
      });
      if (list.length) textRects = list;
      return list;
    }
    const meets = (a, b, pad) => a.x < b.x + b.w + pad && b.x < a.x + a.w + pad && a.y < b.y + b.h + pad && b.y < a.y + a.h + pad;
    // The tag of the selection goes to the first place around the dashed
    // outline (under it at the left, then at the right; over it at the left,
    // then at the right; then beside it) that covers no text of the figure
    // and no box; failing that, the first that covers no text.
    function placeTag(o, w, h) {
      const texts = figureTexts();
      const boxes = [].concat(...Array.from(reg.parts.values()));
      const cands = [];
      [[o.x0, o.y1 - 1], [o.x1 - w, o.y1 - 1], [o.x0, o.y0 - h + 1], [o.x1 - w, o.y0 - h + 1],
        [o.x1 - 1, o.y0], [o.x0 - w + 1, o.y0], [o.x1 - 1, o.y1 - h], [o.x0 - w + 1, o.y1 - h]].forEach(([x, y]) => {
        if (y >= 0 && y + h <= vb.h) cands.push({ x: Math.max(2, Math.min(x, vb.w - w - 2)), y: y, w: w, h: h });
      });
      if (!cands.length) cands.push({ x: Math.max(2, Math.min(o.x0, vb.w - w - 2)), y: Math.max(0, o.y0 - h + 1), w: w, h: h });
      const clear = (c, list, pad) => !list.some((r) => meets(c, r, pad));
      return cands.find((c) => clear(c, texts, 1) && clear(c, boxes, 0)) || cands.find((c) => clear(c, texts, 1)) || cands[0];
    }
    // Where the dashed outline would run through a text of the figure (a band
    // label, a line label), a mask leaves a gap in it, so that the text stays
    // readable.
    function gapsAtTexts(g, rect, o) {
      const pad = 2;
      const crossed = figureTexts().filter((r) => {
        const inX = (x) => x > r.x - pad && x < r.x + r.w + pad;
        const inY = (y) => y > r.y - pad && y < r.y + r.h + pad;
        const alongX = o.x0 < r.x + r.w && o.x1 > r.x;
        const alongY = o.y0 < r.y + r.h && o.y1 > r.y;
        return ((inY(o.y0) || inY(o.y1)) && alongX) || ((inX(o.x0) || inX(o.x1)) && alongY);
      });
      if (!crossed.length) return;
      const id = 'gap' + (++markerUid);
      const mask = S('mask', { id: id, maskUnits: 'userSpaceOnUse', x: 0, y: 0, width: vb.w, height: vb.h }, S('defs', null, g));
      S('rect', { x: 0, y: 0, width: vb.w, height: vb.h, fill: '#fff' }, mask);
      crossed.forEach((r) => S('rect', { x: r1(r.x - 3), y: r1(r.y - 1), width: r1(r.w + 6), height: r1(r.h + 2), fill: '#000' }, mask));
      rect.setAttribute('mask', 'url(#' + id + ')');
    }
    function select(part, tag) {
      G.call.textContent = '';
      const rs = reg.parts.get(part);
      if (!rs || !rs.length) return;
      const o = {
        x0: Math.min(...rs.map((r) => r.x)) - 7,
        y0: Math.min(...rs.map((r) => r.y)) - 7,
        x1: Math.max(...rs.map((r) => r.x + r.w)) + 7,
        y1: Math.max(...rs.map((r) => r.y + r.h)) + 7
      };
      const g = S('g', { class: 'callout', 'data-part': part }, G.call);
      const outline = S('rect', { x: o.x0, y: o.y0, width: o.x1 - o.x0, height: o.y1 - o.y0, rx: 5, class: 'cbox' }, g);
      gapsAtTexts(g, outline, o);
      const w = measure(tag, 'calltxt') + 14;
      const pos = placeTag(o, w, 18);
      S('rect', { x: r1(pos.x), y: r1(pos.y), width: r1(w), height: 18, class: 'ctag' }, g);
      stext(g, r1(pos.x + 7), r1(pos.y + 13.5), tag, 'calltxt');
    }
    // tour tokens: one element per (kind of dot, lane, occurrence)
    const tokEls = new Map();
    function tokKey(tk, n) { return tk.t + '|' + (tk.lane === null || tk.lane === undefined ? '-' : tk.lane) + '|' + n; }
    function stepTokens(entry) {
      const count = new Map();
      return (entry && Array.isArray(entry.tokens) ? entry.tokens : []).map((tk) => {
        const base = tk.t + '|' + tk.lane;
        const n = count.get(base) || 0;
        count.set(base, n + 1);
        return { key: tokKey(tk, n), tk: tk };
      });
    }
    if (opt.tour) {
      (Array.isArray(M.tour) ? M.tour : []).forEach((entry) => {
        stepTokens(entry).forEach(({ key, tk }) => {
          if (tokEls.has(key)) return;
          const g = S('g', { class: 'tok ' + tk.t, 'data-t': tk.t, style: 'opacity:0' }, G.tok);
          if (tk.t === 's') S('rect', { x: -7, y: -7, width: 14, height: 14, transform: 'rotate(45)' }, g);
          else S('circle', { r: tk.t === 'k' ? 4.5 : tk.t === 'r' ? 6 : 7.5 }, g);
          tokEls.set(key, g);
        });
      });
    }
    function setTour(entry) {
      const shown = new Map(stepTokens(entry).map((x) => [x.key, x.tk]));
      tokEls.forEach((g, key) => {
        const tk = shown.get(key);
        if (tk) {
          g.style.transform = 'translate(' + tk.x + 'px,' + tk.y + 'px)';
          g.style.opacity = '1';
          g.setAttribute('data-target', tk.x + ',' + tk.y);
        } else {
          g.style.opacity = '0';
          g.removeAttribute('data-target');
        }
      });
      const hot = new Set(entry && Array.isArray(entry.highlight) ? entry.highlight : []);
      reg.lines.forEach((els, id) => els.forEach((e) => {
        e.classList.toggle('hot', hot.has(id));
        e.classList.toggle('dim', hot.size > 0 && !hot.has(id) && e.classList.contains('ln'));
      }));
      reg.all.forEach((e) => { if (e.classList.contains('port') || e.classList.contains('lab')) e.classList.toggle('dim', hot.size > 0); });
      reg.boxes.forEach((g, key) => {
        const id = key.split('@')[0];
        g.classList.toggle('hot', hot.has('box:' + id) || hot.has('box:' + key));
      });
    }
    return { svg: svg, setFocus: setFocus, select: select, setTour: setTour };
  }

  // ------------------------------------------------------------------
  // Detail views: a part's descendants on its grid (node.detail), the
  // arrows between them, and one tag per (neighbour part, direction)
  // on the side given by detail.sides.
  // ------------------------------------------------------------------
  const DW = 1000;           // base width of a detail view (viewBox units)
  const TAG_SIDE_W = 150;    // width of tags on the left and right
  const EDGE_M = 14;         // margin of the tags from the view border
  const ZONE_GAP = 32;       // between side tags and the boxes
  const ROW_GAP = 70;
  const GROUP_PAD = 13;
  const LAB_H = 14;          // line height of arrow labels

  function detailSpec(part) {
    const n = idx.nodes.get(part);
    if (n && n.detail && Array.isArray(n.detail.rows)) return n.detail;
    // Fallback for a part without a grid: its children, four per row.
    const kids = childrenOf(part);
    if (!kids.length) return null;
    const rows = [];
    kids.forEach((k, i) => {
      if (i % 4 === 0) rows.push([]);
      rows[rows.length - 1].push({ node: k, col: i % 4 });
    });
    return { columns: Math.min(4, kids.length), rows: rows, sides: {} };
  }

  function layoutDetail(part) {
    const spec = detailSpec(part);
    if (!spec) return null;
    const items = new Map();
    spec.rows.forEach((row, ri) => (Array.isArray(row) ? row : []).forEach((it) => {
      if (it && it.group && idx.nodes.has(it.group)) {
        const kids = (Array.isArray(it.kids) ? it.kids : []).filter((k) => k && idx.nodes.has(k.node));
        items.set(it.group, { id: it.group, row: ri, col: it.col || 0, span: it.span || 1, type: 'group', kids: kids.map((k) => k.node) });
        kids.forEach((k) => items.set(k.node, { id: k.node, row: ri, col: k.col || 0, span: 1, type: 'kid', group: it.group }));
      } else if (it && it.node && idx.nodes.has(it.node)) {
        items.set(it.node, { id: it.node, row: ri, col: it.col || 0, span: it.span || 1, type: 'node' });
      }
    }));
    const nRows = spec.rows.length;
    let cols = spec.columns || 1;
    items.forEach((it) => { cols = Math.max(cols, it.col + it.span); });
    const sidesSpec = spec.sides || {};
    const vis = (id) => {
      let cur = id;
      const seen = new Set();
      while (cur !== ROOT && cur !== part && !seen.has(cur)) {
        if (items.has(cur)) return cur;
        seen.add(cur);
        cur = parentOf(cur);
      }
      return null;
    };
    const inside = (id) => id !== part && isDesc(id, part);
    const boxes = Array.from(items.values()).filter((it) => it.type !== 'group');

    // arrows inside the part and tags for arrows that cross its border
    const internal = new Map();
    const tagMap = new Map();
    for (const e of idx.edges) {
      const fi = inside(e.from);
      const ti = inside(e.to);
      if (fi && ti) {
        const a = vis(e.from);
        const b = vis(e.to);
        if (!a || !b || a === b || isDesc(a, b) || isDesc(b, a)) continue;
        const key = a + '|' + b + '|' + e.kind;
        if (!internal.has(key)) internal.set(key, { a: a, b: b, kind: e.kind, labels: [], ids: [] });
        const ie = internal.get(key);
        ie.ids.push(e.id);
        if (!ie.labels.includes(e.label)) ie.labels.push(e.label);
      } else if (fi !== ti) {
        const innerEnd = fi ? e.from : e.to;
        const otherEnd = fi ? e.to : e.from;
        if (otherEnd === part || isDesc(part, otherEnd)) continue;
        const inner = vis(innerEnd);
        if (!inner) continue;
        const other = topOf(otherEnd);
        const dir = fi ? 'out' : 'in';
        const key = other + '|' + dir;
        if (!tagMap.has(key)) tagMap.set(key, { other: other, dir: dir, edges: [], labels: [], others: [] });
        const t = tagMap.get(key);
        t.edges.push({ e: e, inner: inner });
        if (!t.labels.includes(e.label)) t.labels.push(e.label);
        if (!t.others.includes(otherEnd)) t.others.push(otherEnd);
      }
    }
    const tags = Array.from(tagMap.values());
    tags.forEach((t) => {
      t.side = ['left', 'right', 'top', 'bottom'].includes(sidesSpec[t.other]) ? sidesSpec[t.other] : (t.dir === 'in' ? 'left' : 'right');
      const kinds = new Map();
      t.edges.forEach((x) => kinds.set(x.e.kind, (kinds.get(x.e.kind) || 0) + 1));
      t.kind = Array.from(kinds.entries()).sort((p, q) => q[1] - p[1])[0][0];
      // one connector per (inner box, kind)
      const cm = new Map();
      t.edges.forEach((x) => {
        const k = x.inner + '|' + x.e.kind;
        if (!cm.has(k)) cm.set(k, { tag: t, inner: x.inner, kind: x.e.kind, ids: [] });
        cm.get(k).ids.push(x.e.id);
      });
      t.conns = Array.from(cm.values());
    });
    const conns = [].concat(...tags.map((t) => t.conns));

    // which side of the inner box each connector attaches to: left/right
    // tags reach the outermost box of a row directly, others over the top
    conns.forEach((c) => {
      const it = items.get(c.inner);
      c.att = c.tag.side;
      if (c.att === 'left' || c.att === 'right') {
        // a box of the same row between the item (a box or a group, over all
        // of its columns) and that side blocks the straight way in
        const lo = it.col;
        const hi = it.col + (it.span || 1) - 1;
        const blocked = boxes.some((o) => o.id !== it.id && o.group !== it.id && o.row === it.row && (c.att === 'left' ? o.col < lo : o.col > hi));
        if (blocked) c.att = 'top';
      }
      c.over = c.att === 'top' && (c.tag.side === 'left' || c.tag.side === 'right');
    });
    const has = { left: false, right: false, top: false, bottom: false };
    tags.forEach((t) => { has[t.side] = true; });

    // tag texts and sizes
    const sideTags = (s) => tags.filter((t) => t.side === s);
    const headOf = (t) => (t.dir === 'in' ? 'from ' : 'to ') + shortOf(t.other) + ' \u203a';
    // a tag that lists several labels starts each one with a bullet; the
    // label's further lines are indented by the bullet's width
    const bulletW = measure('\u2022 x', 't-slab', 'stub') - measure('x', 't-slab', 'stub');
    const bw = (t) => (t.labels.length > 1 ? bulletW : 0);
    const tagMinW = (t) => Math.max(measure(headOf(t), 't-shead', 'stub'), ...t.labels.map((l) => longestWord(l, 't-slab', 'stub') + bw(t))) + 18;

    // widths
    const padL = has.left ? EDGE_M + TAG_SIDE_W + ZONE_GAP : 30;
    const padR = has.right ? EDGE_M + TAG_SIDE_W + ZONE_GAP : 30;
    const gapMin = cols >= 4 ? 58 : 76;
    let gap = gapMin;
    const sameRowAdjacent = (a, b) => {
      if (a.row !== b.row) return false;
      const lo = Math.min(a.col, b.col);
      const hi = Math.max(a.col, b.col);
      return !boxes.some((o) => o.row === a.row && o.col > lo && o.col < hi);
    };
    const iedges = Array.from(internal.values());
    iedges.forEach((ie) => {
      const A = items.get(ie.a);
      const B = items.get(ie.b);
      ie.kindOf = (A.type !== 'group' && B.type !== 'group' && A.row === B.row) ? (sameRowAdjacent(A, B) ? 'h' : 'arc') : 'v';
      // the gap of a horizontal arrow holds its label in at most two lines
      if (ie.kindOf === 'h') ie.labels.forEach((l) => {
        let w = Math.max(gapMin - 10, longestWord(l, 't-lab'));
        while (w < 150 && wrapText(l, w, 't-lab').length > 2) w += 4;
        gap = Math.max(gap, w + 10);
      });
    });
    let minCW = 96;
    boxes.forEach((b) => { minCW = Math.max(minCW, longestWord(titleOf(b.id), 't-title') + 22, isOut(b.id) ? 86 : 0); });
    let W = Math.max(DW, padL + padR + gap * (cols - 1) + cols * minCW);
    ['top', 'bottom'].forEach((s) => {
      const list = sideTags(s);
      if (!list.length) return;
      const twMin = Math.max(...list.map(tagMinW));
      const xmin = has.left ? EDGE_M + TAG_SIDE_W + 10 : 20;
      const xmaxPad = has.right ? EDGE_M + TAG_SIDE_W + 10 : 20;
      W = Math.max(W, xmin + xmaxPad + list.length * twMin + 10 * (list.length - 1));
    });
    W = Math.ceil(W);
    const cw = (W - padL - padR - gap * (cols - 1)) / cols;
    const colX = (c) => padL + c * (cw + gap);

    // box sizes
    const titleLines = new Map();
    boxes.forEach((b) => titleLines.set(b.id, wrapText(titleOf(b.id), cw - 20, 't-title')));
    const bh = (id) => Math.max(56, 14 + titleLines.get(id).length * 19 + (isOut(id) ? 20 : 0) + 6);

    // horizontal arrow labels sit in the gap above the arrow
    iedges.forEach((ie) => {
      if (ie.kindOf === 'h') ie.lines = [].concat(...ie.labels.map((l) => wrapText(l, gap - 10, 't-lab')));
      else ie.lines = [].concat(...ie.labels.map((l) => wrapText(l, Math.min(170, cw + gap - 30), 't-lab')));
    });

    // over-the-top connectors per row
    const overByRow = new Map();
    conns.filter((c) => c.att === 'top' && c.over).forEach((c) => {
      const r = items.get(c.inner).row;
      overByRow.set(r, (overByRow.get(r) || 0) + 1);
    });

    // tag heights (top/bottom tags get their width later; estimate with the
    // narrowest width they may get)
    const tagH = (t, tw) => {
      const multi = t.labels.length > 1;
      t.bulletW = bw(t);
      t.lines = [];
      t.labels.forEach((l) => wrapText(l, tw - 16 - t.bulletW, 't-slab', 'stub').forEach((ln, i) => {
        t.lines.push({ s: (multi && i === 0 ? '\u2022 ' : '') + ln, indent: multi && i > 0 });
      }));
      return 12 + 16 * (t.lines.length + 1);
    };
    const xminTB = has.left ? EDGE_M + TAG_SIDE_W + 10 : 20;
    const xmaxTB = W - (has.right ? EDGE_M + TAG_SIDE_W + 10 : 20);
    const tbW = {};
    ['top', 'bottom'].forEach((s) => {
      const list = sideTags(s);
      if (!list.length) return;
      tbW[s] = Math.max(Math.min(176, (xmaxTB - xminTB - 10 * (list.length - 1)) / list.length), Math.max(...list.map(tagMinW)));
      list.forEach((t) => { t.tw = tbW[s]; t.th = tagH(t, t.tw); });
    });
    ['left', 'right'].forEach((s) => sideTags(s).forEach((t) => { t.tw = TAG_SIDE_W; t.th = tagH(t, TAG_SIDE_W); }));
    const maxTopH = has.top ? Math.max(...sideTags('top').map((t) => t.th)) : 0;
    const maxBotH = has.bottom ? Math.max(...sideTags('bottom').map((t) => t.th)) : 0;

    // vertical layout
    const groupLines = new Map();
    items.forEach((it) => {
      if (it.type !== 'group') return;
      const gw = colX(it.col + it.span - 1) + cw - colX(it.col) + 2 * GROUP_PAD;
      groupLines.set(it.id, wrapText(titleOf(it.id).toUpperCase(), gw - 24, 't-group'));
    });
    const over0 = overByRow.get(0) || 0;
    const topZoneBottom = has.top ? EDGE_M + maxTopH : 0;
    let padT = has.top ? topZoneBottom + Math.max(44, 30 + 9 * over0 + 14) : (over0 ? 44 + 9 * over0 : 30);
    const R = new Map();
    const rowTop = [];
    const rowBottom = [];
    let y = padT;
    for (let ri = 0; ri < nRows; ri++) {
      const rowItems = Array.from(items.values()).filter((it) => it.row === ri);
      const grp = rowItems.filter((it) => it.type === 'group');
      const off = grp.length ? Math.max(...grp.map((g) => 30 + (groupLines.get(g.id).length - 1) * 15)) : 0;
      const ids = rowItems.filter((it) => it.type !== 'group').map((it) => it.id);
      let h = ids.length ? Math.max(...ids.map(bh)) : 56;
      iedges.forEach((ie) => {
        if (ie.kindOf !== 'h' || items.get(ie.a).row !== ri) return;
        const need = 40 + 28 * (ie.lines.length - 1) + 8;
        h = Math.max(h, grp.length ? need : need - 2 * 24);
      });
      rowTop.push(y);
      rowItems.forEach((it) => {
        if (it.type === 'group') {
          const x = colX(it.col) - GROUP_PAD;
          R.set(it.id, { x: x, y: y, w: colX(it.col + it.span - 1) + cw + GROUP_PAD - x, h: off + h + GROUP_PAD, row: ri, group: true, strip: off });
        } else {
          R.set(it.id, { x: colX(it.col), y: y + off, w: cw + (it.span - 1) * (cw + gap), h: h, row: ri, kid: it.type === 'kid', groupId: it.group });
        }
      });
      const bottom = y + off + h + (grp.length ? GROUP_PAD : 0);
      rowBottom.push(bottom);
      // room under the row: arcs, labels of row-crossing arrows, and
      // over-the-top connectors into the next row
      let rg = ROW_GAP;
      iedges.forEach((ie) => {
        const A = items.get(ie.a);
        const B = items.get(ie.b);
        if (ie.kindOf === 'arc' && A.row === ri) rg = Math.max(rg, 52 + LAB_H * ie.lines.length + 6);
        if (ie.kindOf === 'v' && Math.min(A.row, B.row) === ri) rg = Math.max(rg, LAB_H * ie.lines.length + 34);
      });
      const overNext = overByRow.get(ri + 1) || 0;
      if (overNext) rg = Math.max(rg, 40 + 9 * overNext);
      y = bottom + (ri < nRows - 1 ? rg : 0);
    }
    const lastBottom = y;
    const arcsLast = iedges.some((ie) => ie.kindOf === 'arc' && items.get(ie.a).row === nRows - 1);
    let padB = has.bottom ? Math.max(46, arcsLast ? 66 : 46) + maxBotH + EDGE_M : (arcsLast ? 66 : 30);
    let H = lastBottom + padB;
    // side tags must fit the height
    ['left', 'right'].forEach((s) => {
      const list = sideTags(s);
      const need = list.reduce((m, t) => m + t.th + 10, 0) + 14;
      if (need > H) { padB += need - H; H = need; }
    });
    H = Math.ceil(H);

    // attachment points on box sides, spread so that ends do not meet
    const sideSlots = new Map();   // "id|side" -> [{ref, key}]
    const addSlot = (id, side, ref, key) => {
      const k = id + '|' + side;
      if (!sideSlots.has(k)) sideSlots.set(k, []);
      sideSlots.get(k).push({ ref: ref, key: key });
    };
    const cxOf = (id) => { const r = R.get(id); return r.x + r.w / 2; };
    const cyOf = (id) => { const r = R.get(id); return r.y + r.h / 2; };
    iedges.forEach((ie) => {
      const A = R.get(ie.a);
      const B = R.get(ie.b);
      if (ie.kindOf === 'h') return;
      if (ie.kindOf === 'arc') {
        addSlot(ie.a, 'bottom', { ie: ie, end: 'a' }, cxOf(ie.b));
        addSlot(ie.b, 'bottom', { ie: ie, end: 'b' }, cxOf(ie.a));
        return;
      }
      const aAbove = A.row < B.row;
      if (!A.group) addSlot(ie.a, aAbove ? 'bottom' : 'top', { ie: ie, end: 'a' }, cxOf(ie.b));
      if (!B.group) addSlot(ie.b, aAbove ? 'top' : 'bottom', { ie: ie, end: 'b' }, cxOf(ie.a));
    });
    // tag positions along their side, first estimate: near the boxes they reach
    conns.forEach((c) => {
      const r = R.get(c.inner);
      addSlot(c.inner, c.att, { conn: c }, c.tag.side === 'left' ? -1e6 + r.x : c.tag.side === 'right' ? 1e6 + r.x : 0);
    });
    // order the slots of a side by where the other end is
    sideSlots.forEach((list, k) => {
      const [id, side] = [k.slice(0, k.lastIndexOf('|')), k.slice(k.lastIndexOf('|') + 1)];
      const r = R.get(id);
      list.forEach((s) => {
        if (s.ref.conn && (s.ref.conn.tag.side === 'top' || s.ref.conn.tag.side === 'bottom')) s.key = 0;
      });
      // connectors from top/bottom tags keep their order by tag (set later);
      // provisional: by kind of the tag and its neighbour order
      list.sort((p, q) => p.key - q.key);
      list.forEach((s, i) => {
        const f = (i + 1) / (list.length + 1);
        let pt;
        if (side === 'top') pt = [r.x + r.w * f, r.y];
        else if (side === 'bottom') pt = [r.x + r.w * f, r.y + r.h];
        else if (side === 'left') pt = [r.x, r.y + Math.max(r.strip || 0, 0) + (r.h - (r.strip || 0)) * f];
        else pt = [r.x + r.w, r.y + Math.max(r.strip || 0, 0) + (r.h - (r.strip || 0)) * f];
        if (s.ref.conn) s.ref.conn.ap = pt;
        else s.ref.ie[s.ref.end === 'a' ? 'pa' : 'pb'] = pt;
      });
    });

    // left and right tags: next to the box they reach; over-the-top ones first
    ['left', 'right'].forEach((side) => {
      const list = sideTags(side);
      if (!list.length) return;
      list.forEach((t) => {
        t.overAll = t.conns.every((c) => c.over);
        t.my = t.conns.reduce((m, c) => m + c.ap[1], 0) / t.conns.length;
      });
      list.sort((p, q) => (p.overAll !== q.overAll ? (p.overAll ? -1 : 1) : p.my - q.my));
      let ys = list.map((t) => (t.overAll ? 12 : t.my - t.th / 2));
      ys[0] = Math.max(12, ys[0]);
      for (let i = 1; i < ys.length; i++) ys[i] = Math.max(ys[i], ys[i - 1] + list[i - 1].th + 10);
      const spill = ys[ys.length - 1] + list[list.length - 1].th - (H - 10);
      if (spill > 0) { ys = ys.map((v) => v - spill); for (let i = ys.length - 2; i >= 0; i--) ys[i] = Math.min(ys[i], ys[i + 1] - list[i].th - 10); }
      ys[0] = Math.max(ys[0], 12);
      for (let i = 1; i < ys.length; i++) ys[i] = Math.max(ys[i], ys[i - 1] + list[i - 1].th + 10);
      list.forEach((t, i) => { t.w = TAG_SIDE_W; t.h = t.th; t.x = side === 'left' ? EDGE_M : W - EDGE_M - TAG_SIDE_W; t.y = ys[i]; });
    });
    // place top and bottom tags near the x where their connectors attach;
    // they use the full width unless a side tag reaches into their zone
    ['top', 'bottom'].forEach((side) => {
      const list = sideTags(side);
      if (!list.length) return;
      const zone = side === 'top' ? [EDGE_M, EDGE_M + maxTopH] : [H - EDGE_M - maxBotH, H - EDGE_M];
      const clash = (s2) => sideTags(s2).some((t) => t.y < zone[1] + 10 && t.y + t.h > zone[0] - 10);
      const xmin = clash('left') ? EDGE_M + TAG_SIDE_W + 10 : 20;
      const xmax = W - (clash('right') ? EDGE_M + TAG_SIDE_W + 10 : 20);
      const twMin = Math.max(...list.map(tagMinW));
      const tw = Math.max(twMin, Math.min(176, (xmax - xmin - 10 * (list.length - 1)) / list.length));
      if (tw > tbW[side]) list.forEach((t) => { t.th = Math.min(t.th, tagH(t, tw)); });
      list.forEach((t) => { t.mx = t.conns.reduce((m, c) => m + c.ap[0], 0) / t.conns.length; });
      list.sort((p, q) => p.mx - q.mx);
      let xs = list.map((t) => Math.min(xmax - tw, Math.max(xmin, t.mx - tw / 2)));
      for (let i = 1; i < xs.length; i++) xs[i] = Math.max(xs[i], xs[i - 1] + tw + 10);
      const spill = xs[xs.length - 1] + tw - xmax;
      if (spill > 0) { xs = xs.map((x) => x - spill); for (let i = xs.length - 2; i >= 0; i--) xs[i] = Math.min(xs[i], xs[i + 1] - tw - 10); }
      xs[0] = Math.max(xs[0], xmin);
      for (let i = 1; i < xs.length; i++) xs[i] = Math.max(xs[i], xs[i - 1] + tw + 10);
      const maxH = side === 'top' ? maxTopH : maxBotH;
      list.forEach((t, i) => { t.x = xs[i]; t.w = tw; t.h = maxH; t.y = side === 'top' ? EDGE_M : H - EDGE_M - maxH; });
    });
    // re-spread the connector ends on box tops/bottoms in the order of their tags
    sideSlots.forEach((list, k) => {
      const side = k.slice(k.lastIndexOf('|') + 1);
      if (side !== 'top' && side !== 'bottom') return;
      const id = k.slice(0, k.lastIndexOf('|'));
      const r = R.get(id);
      const keyOf = (s) => {
        if (s.ref.conn) {
          const t = s.ref.conn.tag;
          if (t.side === 'left') return -1e6 + t.y;
          if (t.side === 'right') return 1e6 - t.y;
          return t.x + t.w / 2;
        }
        const ie = s.ref.ie;
        return s.ref.end === 'a' ? cxOf(ie.b) : cxOf(ie.a);
      };
      list.sort((p, q) => keyOf(p) - keyOf(q));
      // each end moves toward what it reaches (the tag's centre, the other
      // box's centre), inside the box and in order, at least `step` apart;
      // this keeps connectors short and stops them crossing under the box
      const lo = r.x + 12;
      const hi = r.x + r.w - 12;
      const n = list.length;
      const step = n > 1 ? Math.min(22, (hi - lo) / (n - 1)) : 0;
      const xs = list.map((s) => Math.min(hi, Math.max(lo, Math.abs(keyOf(s)) >= 1e5 ? (keyOf(s) < 0 ? lo : hi) : keyOf(s))));
      for (let i = 1; i < n; i++) xs[i] = Math.max(xs[i], xs[i - 1] + step);
      if (n) xs[n - 1] = Math.min(xs[n - 1], hi);
      for (let i = n - 2; i >= 0; i--) xs[i] = Math.min(xs[i], xs[i + 1] - step);
      list.forEach((s, i) => {
        const pt = [r1(xs[i]), side === 'top' ? r.y : r.y + r.h];
        if (s.ref.conn) s.ref.conn.ap = pt;
        else s.ref.ie[s.ref.end === 'a' ? 'pa' : 'pb'] = pt;
      });
    });

    // over-the-top connectors of a row: the one reaching farthest takes the
    // highest track, so that the tracks do not cross
    const overRows = new Map();
    conns.filter((c) => c.over).forEach((c) => {
      const r = R.get(c.inner).row;
      if (!overRows.has(r)) overRows.set(r, []);
      overRows.get(r).push(c);
    });
    overRows.forEach((list) => {
      const dist = (c) => (c.tag.side === 'left' ? c.ap[0] - c.tag.x : c.tag.x - c.ap[0]);
      list.sort((p, q) => dist(p) - dist(q));
      list.forEach((c, i) => { c.lane = i; c.nOver = list.length; });
    });

    return {
      part: part, items: items, R: R, W: W, H: H, cw: cw, gap: gap, cols: cols, colX: colX,
      rowTop: rowTop, rowBottom: rowBottom,
      iedges: iedges, tags: tags, conns: conns, titleLines: titleLines, groupLines: groupLines, vis: vis
    };
  }

  // Obstacles for connector routing: boxes and other groups' title strips.
  function blocked(L, seg, exemptIds) {
    const [p, q] = seg;
    const x0 = Math.min(p[0], q[0]);
    const x1 = Math.max(p[0], q[0]);
    const y0 = Math.min(p[1], q[1]);
    const y1 = Math.max(p[1], q[1]);
    for (const [id, r] of L.R) {
      if (exemptIds.includes(id)) continue;
      const rr = r.group ? { x: r.x, y: r.y, w: r.w, h: r.strip } : r;
      if (x1 > rr.x - 2 && x0 < rr.x + rr.w + 2 && y1 > rr.y - 2 && y0 < rr.y + rr.h + 2) return true;
    }
    for (const t of L.tags) {
      if (x1 > t.x - 2 && x0 < t.x + t.w + 2 && y1 > t.y - 2 && y0 < t.y + t.h + 2) return true;
    }
    return false;
  }
  function polyD(pts) {
    let d = 'M' + r1(pts[0][0]) + ',' + r1(pts[0][1]);
    for (let i = 1; i < pts.length - 1; i++) {
      const p0 = pts[i - 1]; const p = pts[i]; const p1 = pts[i + 1];
      const rad = Math.min(6, Math.hypot(p[0] - p0[0], p[1] - p0[1]) / 2, Math.hypot(p1[0] - p[0], p1[1] - p[1]) / 2);
      const a = toward(p, p0, rad); const b = toward(p, p1, rad);
      d += ' L' + r1(a[0]) + ',' + r1(a[1]) + ' Q' + r1(p[0]) + ',' + r1(p[1]) + ' ' + r1(b[0]) + ',' + r1(b[1]);
    }
    const last = pts[pts.length - 1];
    return d + ' L' + r1(last[0]) + ',' + r1(last[1]);
  }
  function toward(p, q, rad) {
    const d = Math.hypot(q[0] - p[0], q[1] - p[1]) || 1;
    return [p[0] + (q[0] - p[0]) * rad / d, p[1] + (q[1] - p[1]) * rad / d];
  }
  const P = (p) => r1(p[0]) + ',' + r1(p[1]);
  function cubicD(p0, c1, c2, p3) { return 'M' + P(p0) + ' C' + P(c1) + ' ' + P(c2) + ' ' + P(p3); }

  // Route from the box end `ap` (on its top or bottom side) to the tag zone
  // above or below, returning the polyline up to the zone edge `zoneY`
  // (straight up/down when free, else through the nearest free column gap).
  function vertRoute(L, c, zoneY) {
    const up = zoneY < c.ap[1];
    const it = L.items.get(c.inner);
    const exempt = [c.inner];
    if (it.type === 'kid') exempt.push(it.group);
    if (it.type === 'group') exempt.push(...it.kids);
    const straight = [c.ap, [c.ap[0], zoneY]];
    if (!blocked(L, straight, exempt)) return [c.ap, [c.ap[0], zoneY]];
    const r = L.R.get(c.inner);
    const chanY = up ? L.rowTop[r.row] - 16 : L.rowBottom[r.row] + 16;
    const gaps = [];
    for (let k = 0; k <= L.cols; k++) gaps.push(k === 0 ? L.colX(0) - L.gap / 2 - 6 : k === L.cols ? L.colX(L.cols - 1) + L.cw + L.gap / 2 + 6 : L.colX(k) - L.gap / 2);
    gaps.sort((a, b) => Math.abs(a - c.ap[0]) - Math.abs(b - c.ap[0]));
    for (const gx of gaps) {
      const pts = [c.ap, [c.ap[0], chanY], [gx, chanY], [gx, zoneY]];
      let ok = true;
      for (let i = 1; i < pts.length; i++) if (blocked(L, [pts[i - 1], pts[i]], i === 1 ? exempt : [])) { ok = false; break; }
      if (ok) return pts;
    }
    return straight;
  }

  function buildDetail(host, opt) {
    opt = opt || {};
    let cur = null;
    function show(part, hot) {
      cur = part;
      const hotSet = new Set((Array.isArray(hot) ? hot : (hot ? [hot] : [])).filter((id) => idx.nodes.has(id)));
      host.textContent = '';
      const hint = el('span', { class: 'scroll-hint', hidden: true, text: 'Scroll sideways to see the whole detail \u2192' });
      // (the card's head names the part; the detail's own head only says
      // when the drawing scrolls sideways)
      host.append(el('div', { class: 'dhead' }, [hint]));
      const L = layoutDetail(part);
      const sheet = el('div', { class: 'sheet' });
      host.append(sheet);
      if (!L) {
        sheet.hidden = true;
        if (opt.onShown) opt.onShown(part);
        return;
      }
      const hv = new Set(Array.from(hotSet).map((id) => (id === part ? null : L.vis(id))).filter(Boolean));
      const svg = S('svg', {
        viewBox: '0 0 ' + L.W + ' ' + L.H, class: 'detail', role: 'group', 'data-detail': part,
        'aria-label': 'Detail of ' + titleOf(part) + ': its parts, the arrows between them, and tags naming the neighbours outside it.'
      }, sheet);
      const mk = markers(svg);
      const gG = S('g', { class: 'layer-groups' }, svg);
      const gL = S('g', { class: 'layer-lines' }, svg);
      const gB = S('g', { class: 'layer-boxes' }, svg);
      const gT = S('g', { class: 'layer-labels' }, svg);
      const gS = S('g', { class: 'layer-tags' }, svg);
      const R = L.R;

      // groups
      L.items.forEach((it) => {
        if (it.type !== 'group') return;
        const r = R.get(it.id);
        const g = S('g', { class: 'dgroup' + (hv.has(it.id) ? ' hot' : ''), 'data-node': it.id, tabindex: '0', role: 'button', 'aria-label': titleOf(it.id) }, gG);
        S('rect', { x: r.x, y: r.y, width: r.w, height: r.h, rx: 4, class: 'gbox' }, g);
        S('rect', { x: r.x + 1, y: r.y + 1, width: r.w - 2, height: r.strip - 2, rx: 3, class: 'gtitle' }, g);
        L.groupLines.get(it.id).forEach((s, i) => stext(g, r.x + 12, r.y + 19 + i * 15, s, 't-group'));
        onActivate(g, () => { if (opt.onNode) opt.onNode(it.id, part); });
      });
      // boxes
      L.items.forEach((it) => {
        if (it.type === 'group') return;
        const r = R.get(it.id);
        const g = S('g', { class: 'box' + (hv.has(it.id) ? ' hot' : ''), 'data-node': it.id, tabindex: '0', role: 'button', 'aria-label': titleOf(it.id) }, gB);
        S('rect', { x: r1(r.x), y: r.y, width: r1(r.w), height: r.h, rx: 3, class: 'b' }, g);
        const lines = L.titleLines.get(it.id);
        lines.forEach((s, i) => stext(g, r1(r.x + 10), r.y + 22 + i * 19, s, 't-title'));
        if (isOut(it.id)) {
          const yy = r.y + 22 + lines.length * 19 - 6;
          const ow = r1(measure('outside repo', 't-out') + 10);
          S('rect', { x: r1(r.x + 10), y: yy, width: ow, height: 17, rx: 2, class: 'otag' }, g);
          stext(g, r1(r.x + 10 + ow / 2), yy + 13, 'outside repo', 't-out', { 'text-anchor': 'middle' });
        }
        onActivate(g, () => { if (opt.onNode) opt.onNode(it.id, part); });
      });

      // arrows inside the part
      const labelAt = (x, y, lines, kind, anchor, ids) => {
        const t = stextLines(gT, r1(x), r1(y), lines, 't-lab lab halo ' + kind, LAB_H, { 'text-anchor': anchor });
        t.setAttribute('data-edge-ids', ids.join(' '));
        return t;
      };
      const pairCount = new Map();
      L.iedges.forEach((ie) => {
        const A = R.get(ie.a);
        const B = R.get(ie.b);
        const attrs = { class: 'ln ' + ie.kind, 'data-edge-ids': ie.ids.join(' '), 'data-from-box': ie.a, 'data-to-box': ie.b, 'marker-end': mk(ie.kind) };
        let d;
        if (ie.kindOf === 'h') {
          const pk = [ie.a, ie.b].sort().join('|');
          const n = pairCount.get(pk) || 0;
          pairCount.set(pk, n + 1);
          const left = A.x < B.x ? A : B;
          const right = A.x < B.x ? B : A;
          const x1 = left.x + left.w;
          const x2 = right.x;
          const yy = left.y + left.h / 2 + (n ? 18 : 0);
          d = A === left ? 'M' + r1(x1) + ',' + r1(yy) + ' H' + r1(x2) : 'M' + r1(x2) + ',' + r1(yy) + ' H' + r1(x1);
          S('path', Object.assign({ d: d }, attrs), gL);
          if (n) labelAt((x1 + x2) / 2, yy + 16, ie.lines, ie.kind, 'middle', ie.ids);
          else labelAt((x1 + x2) / 2, yy - 8 - (ie.lines.length - 1) * LAB_H, ie.lines, ie.kind, 'middle', ie.ids);
        } else if (ie.kindOf === 'arc') {
          const pa = ie.pa;
          const pb = ie.pb;
          const dip = 46;
          d = cubicD(pa, [pa[0], pa[1] + dip], [pb[0], pb[1] + dip], pb);
          S('path', Object.assign({ d: d }, attrs), gL);
          labelAt((pa[0] + pb[0]) / 2, Math.max(pa[1], pb[1]) + dip + 2, ie.lines, ie.kind, 'middle', ie.ids);
        } else {
          // between rows: from the bottom of the upper to the top of the lower
          const aAbove = A.row < B.row;
          const top = aAbove ? A : B;
          const bot = aAbove ? B : A;
          let pTop = aAbove ? ie.pa : ie.pb;
          let pBot = aAbove ? ie.pb : ie.pa;
          if (top.group) pTop = [pBot[0], top.y + top.h];
          if (bot.group) pBot = [pTop[0], bot.y];
          const my = (pTop[1] + pBot[1]) / 2;
          const seg = cubicD(pTop, [pTop[0], my], [pBot[0], my], pBot);
          const rev = cubicD(pBot, [pBot[0], my], [pTop[0], my], pTop);
          d = aAbove ? seg : rev;
          S('path', Object.assign({ d: d }, attrs), gL);
          labelAt((pTop[0] + pBot[0]) / 2 + 8, my - (ie.lines.length - 1) * LAB_H / 2 + 4, ie.lines, ie.kind, 'start', ie.ids);
        }
      });

      // tags and their connectors
      L.tags.forEach((t) => {
        const g = S('g', {
          class: 'stub ' + t.kind, 'data-other': t.other, 'data-dir': t.dir,
          'data-edge-ids': t.edges.map((x) => x.e.id).join(' '), tabindex: '0', role: 'button',
          'aria-label': (t.dir === 'in' ? 'from ' : 'to ') + titleOf(t.other) + ': ' + t.labels.join('; ') + '. Open that detail.'
        }, gS);
        // connectors, in the order of the points they reach
        const n = t.conns.length;
        const along = (c) => (t.side === 'top' || t.side === 'bottom' ? c.ap[0] : (c.over ? -1e6 - c.lane : c.ap[1]));
        t.conns.slice().sort((p, q) => along(p) - along(q)).forEach((c, i) => {
          const f = (i + 1) / (n + 1);
          let p0;
          let d;
          if (t.side === 'top') p0 = [t.x + t.w * f, t.y + t.h];
          else if (t.side === 'bottom') p0 = [t.x + t.w * f, t.y];
          else if (t.side === 'left') p0 = [t.x + t.w, t.y + t.h * f];
          else p0 = [t.x, t.y + t.h * f];
          const p3 = c.ap;
          let pts = null;
          if (c.over) {
            const r = R.get(c.inner);
            const it = L.items.get(c.inner);
            const grpTop = it.type === 'kid' ? R.get(it.group).y : r.y;
            const lane = c.lane;
            const yc = grpTop - 22 - 9 * lane;
            const k = p0[1] < yc ? lane : c.nOver - 1 - lane;
            const xj = t.side === 'left' ? p0[0] + 8 + 8 * k : p0[0] - 8 - 8 * k;
            pts = [p0, [xj, p0[1]], [xj, yc], [p3[0], yc], p3];
            if (t.dir !== 'in') pts.reverse();
            d = polyD(pts);
          } else if (t.side === 'left' || t.side === 'right') {
            const s = t.side === 'left' ? 1 : -1;
            const c1 = [p0[0] + 40 * s, p0[1]];
            const c2 = c.att === 'left' || c.att === 'right' ? [p3[0] - 40 * s, p3[1]] : [p3[0], p3[1] - 46];
            d = t.dir === 'in' ? cubicD(p0, c1, c2, p3) : cubicD(p3, c2, c1, p0);
          } else {
            // top or bottom tag: from the box end to the free band next to
            // the tag zone (straight, or through a column gap), then a curve
            const upZone = t.side === 'top';
            const r = R.get(c.inner);
            const nextToZone = r.row === (upZone ? 0 : L.rowTop.length - 1);
            const bandY = upZone ? L.rowTop[0] - 6 : L.rowBottom[L.rowBottom.length - 1] + 6;
            const route = nextToZone ? [p3] : vertRoute(L, c, bandY);
            const q = route[route.length - 1];
            const span = Math.abs(p0[1] - q[1]);
            const sg = upZone ? 1 : -1;
            const cc1 = [p0[0], p0[1] + sg * Math.min(30, span * 0.45)];
            const cc2 = [q[0], q[1] - sg * Math.min(46, span * 0.55)];
            const tail = route.length > 1 ? polyTail(route.slice().reverse()) : '';
            const fwd = cubicD(p0, cc1, cc2, q) + tail;
            const back = route.length > 1 ? polyD(route) + ' C' + P(cc2) + ' ' + P(cc1) + ' ' + P(p0) : cubicD(q, cc2, cc1, p0);
            d = t.dir === 'in' ? fwd : back;
          }
          const a = { d: d, class: 'ln ' + c.kind, 'data-edge-ids': c.ids.join(' '), 'marker-end': mk(c.kind) };
          if (t.dir === 'in') a['data-to-box'] = c.inner; else a['data-from-box'] = c.inner;
          S('path', a, g);
        });
        S('rect', { x: r1(t.x), y: r1(t.y), width: r1(t.w), height: r1(t.h), rx: 3, class: 'tag' }, g);
        stext(g, r1(t.x + 8), r1(t.y + 18), (t.dir === 'in' ? 'from ' : 'to ') + shortOf(t.other) + ' \u203a', 't-shead');
        if (t.lines.length) {
          const tl = S('text', { x: r1(t.x + 8), y: r1(t.y + 34), class: 't-slab' }, g);
          t.lines.forEach((ln, i) => {
            const ts = S('tspan', { x: r1(t.x + 8 + (ln.indent ? t.bulletW : 0)), dy: i ? 16 : 0 }, tl);
            ts.textContent = i < t.lines.length - 1 ? ln.s + ' ' : ln.s;
          });
        }
        onActivate(g, () => { if (opt.onStub) opt.onStub(t.other, t.others, part); });
      });
      scrollCue(sheet, hint);
      if (opt.onShown) opt.onShown(part);
    }
    // The tail of a polyline (after its first point), with rounded corners.
    function polyTail(pts) {
      const d = polyD(pts);
      return ' ' + d.replace(/^M[^ ]+ ?/, '');
    }
    return { show: show, current: () => cur };
  }

  // ------------------------------------------------------------------
  // The node panel (#detail): title, place in the model, then the body
  // ------------------------------------------------------------------
  function renderPanel(id) {
    const panel = $('detail');
    panel.textContent = '';
    const n = idx.nodes.get(id);
    if (!n) return;
    const title = el('h2', { id: 'detail-title', class: 'detail-title', dataset: { nodeId: id }, tabindex: '-1', text: n.title });
    // the card's head already names a top-level part; a node inside it shows
    // its own title
    if (id === topOf(id)) title.classList.add('vh');
    panel.append(title);
    const path = el('nav', { class: 'detail-path', 'aria-label': 'Location in the model' });
    [ROOT].concat(pathTo(id)).forEach((p, i, all) => {
      if (i > 0) path.append(el('span', { class: 'crumb-sep', 'aria-hidden': 'true', text: ' › ' }));
      if (i === all.length - 1) path.append(el('span', { text: titleOf(p) }));
      else if (p === ROOT) path.append(link('#/', 'Overview', 'crumb-overview'));
      else path.append(nodeLink(p, titleOf(p)));
    });
    panel.append(path);
    appendNodeBody(panel, n, 'h3', 'h4', { flows: true, fold: true });
  }

  // A folded section (closed until the reader opens it): its line names it
  // and, for a list, says how many items it holds.
  function foldBox(kind, h3, title, count) {
    const summary = el('summary', {}, [el(h3, { text: title })]);
    if (count) summary.append(el('span', { class: 'fold-count', 'aria-label': count + (count === 1 ? ' item' : ' items'), text: String(count) }));
    return el('details', { class: 'fold', 'data-fold': kind }, [summary]);
  }

  // The body of a node: outside note, summary, prose, developer notes,
  // decisions, code references, sources and (o.flows) flows. With o.fold
  // (the card) each of the last five is folded under a line of its own;
  // without it (the one-page view) each has a heading.
  function appendNodeBody(box, n, h3, h4, o) {
    o = o || {};
    if (n.outside_repo === true) {
      box.append(el('p', { class: 'outside-note' }, [
        el('span', { class: 'badge-outside', text: 'Outside this repo' }),
        ' The mechanism of this part is not implemented in the lcls2 repository (for example firmware, another repository or a facility service). Its description is based on the external sources listed below; the text says which pieces, if any, are in this repository.'
      ]));
    }
    box.append(inlineProse('p', n.summary, 'summary'));
    box.append(prose(n.prose, o.proseId === null ? {} : { id: o.proseId || 'detail-prose' }));
    // a section: folded in the card, under a heading elsewhere
    const sectionBox = (kind, title, count) => {
      if (o.fold) { const d = foldBox(kind, h3, title, count); box.append(d); return d; }
      box.append(el(h3, { text: title }));
      return box;
    };

    if (typeof n.dev_notes === 'string' && n.dev_notes.trim()) {
      sectionBox('dev', 'For developers').append(prose(n.dev_notes, { class: 'prose dev-notes' }));
    }

    const decisions = Array.isArray(n.decisions) ? n.decisions : [];
    if (decisions.length) {
      const sec = sectionBox('decisions', 'Design decisions', decisions.length);
      for (const d of decisions) {
        const art = el('article', { class: 'decision-card' });
        art.append(el(h4, { text: d.title }));
        art.append(el('div', { class: 'decision-label', text: 'Decision' }));
        art.append(prose(d.decision));
        art.append(el('div', { class: 'decision-label', text: 'Why' }));
        art.append(prose(d.rationale));
        const refs = referenceList(d.code_refs, d.sources);
        if (refs) art.append(refs);
        sec.append(art);
      }
    }

    const codeRefs = Array.isArray(n.code_refs) ? n.code_refs : [];
    if (codeRefs.length) {
      sectionBox('code', 'Code references', codeRefs.length).append(el('ul', { class: 'ref-list' }, codeRefs.map(codeRefItem)));
    }
    const sourceIds = Array.isArray(n.sources) ? n.sources : [];
    if (sourceIds.length) {
      sectionBox('sources', 'Sources', sourceIds.length).append(el('ul', { class: 'ref-list' }, sourceIds.map(sourceItem)));
    }

    if (!o.flows) return;
    // the flows: what crosses the border of the node (and its inside)
    const flows = flowsOf(n.id);
    if (flows.incoming.length || flows.outgoing.length) {
      const sec = sectionBox('flows', 'Flows', flows.incoming.length + flows.outgoing.length);
      if (flows.incoming.length) {
        sec.append(el(h4, { class: 'flow-heading', text: 'Comes from' }));
        sec.append(el('ul', { class: 'flow-list' }, flows.incoming.map((e) => flowItem(e, 'in', n.id))));
      }
      if (flows.outgoing.length) {
        sec.append(el(h4, { class: 'flow-heading', text: 'Goes to' }));
        sec.append(el('ul', { class: 'flow-list' }, flows.outgoing.map((e) => flowItem(e, 'out', n.id))));
      }
    }
  }

  function referenceList(codeRefs, sourceIds) {
    const items = [];
    for (const c of Array.isArray(codeRefs) ? codeRefs : []) items.push(codeRefItem(c));
    for (const s of Array.isArray(sourceIds) ? sourceIds : []) items.push(sourceItem(s));
    return items.length ? el('ul', { class: 'ref-list compact' }, items) : null;
  }

  function codeRefItem(c) {
    const cb = model.code_base || {};
    const url = cb.repo_url + '/blob/' + cb.commit + '/' + c.path + '#L' + c.start + '-L' + c.end;
    const li = el('li', { class: 'code-ref' });
    li.append(link(url, '', 'code-link'));
    li.lastChild.append(el('code', { text: c.path + ':' + c.start + '-' + c.end }));
    li.append(' ', el('code', { class: 'symbol', text: c.symbol }));
    if (typeof c.note === 'string' && c.note.trim()) li.append(inlineProse('span', c.note, 'ref-note'));
    return li;
  }

  function sourceItem(sourceId) {
    const s = idx.sources.get(sourceId);
    if (!s) return el('li', { text: sourceId });
    const li = el('li', { class: 'source source-' + s.kind });
    li.append(link(s.url, s.title, 'source-link'));
    li.append(' ', el('span', { class: 'badge badge-source badge-' + s.kind, text: SOURCE_KIND_NAMES[s.kind] || s.kind }));
    if (typeof s.note === 'string' && s.note.trim()) li.append(inlineProse('span', s.note, 'ref-note'));
    return li;
  }

  // Edges that cross the boundary of the node's subtree.
  function flowsOf(id) {
    const inside = subtreeOf(id);
    const incoming = [];
    const outgoing = [];
    for (const e of idx.edges) {
      const fromIn = inside.has(e.from);
      const toIn = inside.has(e.to);
      if (fromIn && !toIn) outgoing.push(e);
      else if (!fromIn && toIn) incoming.push(e);
    }
    return { incoming: incoming, outgoing: outgoing };
  }

  function whereText(id) {
    const where = pathTo(id).slice(0, -1);
    return where.length ? ' (in ' + where.map(titleOf).join(' \u203a ') + ')' : '';
  }
  function flowExtras(li, e) {
    li.append(el('div', { class: 'flow-label' }, [el('span', { class: 'flow-key', text: 'On the arrow: ' }), e.label]));
    if (typeof e.prose === 'string' && e.prose.trim()) li.append(prose(e.prose, { class: 'prose flow-prose' }));
    const refs = referenceList(e.code_refs, e.sources);
    if (refs) li.append(refs);
  }

  function flowItem(e, direction, focusId) {
    const otherId = direction === 'in' ? e.from : e.to;
    const insideId = direction === 'in' ? e.to : e.from;
    const li = el('li', { class: 'flow kind-' + e.kind, dataset: { edgeId: e.id } });
    li.append(el('div', { class: 'flow-head' }, [
      el('span', { class: 'badge badge-kind kind-' + e.kind, text: kindName(e.kind) }),
      el('span', { class: 'flow-dir', text: direction === 'in' ? ' \u2190 from ' : ' \u2192 to ' }),
      nodeLink(otherId, titleOf(otherId), 'xref flow-end'),
      el('span', { class: 'flow-where', text: whereText(otherId) })
    ]));
    if (insideId !== focusId) {
      li.append(el('div', { class: 'flow-inside' }, [
        el('span', { class: 'flow-key', text: direction === 'in' ? 'Arrives at: ' : 'Leaves from: ' }),
        nodeLink(insideId, titleOf(insideId), 'xref')
      ]));
    }
    flowExtras(li, e);
    return li;
  }
  // ------------------------------------------------------------------
  // Keeping the page in place
  // ------------------------------------------------------------------
  // A click that changes a card never moves the page (window.scrollY stays
  // the same), and the reader sees the start of the new content where they
  // were reading:
  // - When a card turns to new content (another part, the overview, another
  //   tour step, or the card a mode brings back) while the card's top is
  //   above the window, a spacer at the top of the card's body
  //   (.card-spacer) takes the height of the part of the card that is above
  //   the window. The new content then starts right under the card's head,
  //   which is stuck at the top of the window. The spacer stays until the
  //   card turns again. A reader who scrolls back up passes through it, and
  //   a note in it, under the head, says why it is blank and links back to
  //   the map ("Back to the map", one tap out of the blank). As the reader
  //   scrolls, only what moves nothing in view is dropped: the part of the
  //   spacer below the window's bottom; the whole spacer once it is all
  //   below the window; and, once the card's top is back in view, the rest
  //   of the spacer when what is left of it, down to the window's bottom,
  //   is too short for its note (what was under it was below the window).
  // - While content changes, the page may only get longer: the browser
  //   pulls the page up when it gets shorter than the window's bottom. A
  //   minimum height on the body holds that bottom until the reader scrolls
  //   back above it.
  // Deep links and "Back to the map", which move the page anyway, drop the
  // spacers and the minimum height first.
  let floorPx = 0;
  const SPACER_PAD = 12;  // the spacer's bottom padding (viewer.css: .card-spacer)
  function naturalBottom() {
    const wrap = document.querySelector('.wrap');
    return wrap ? wrap.getBoundingClientRect().bottom + window.scrollY : 0;
  }
  // the page may only get longer from here on
  function holdFloor() {
    document.body.style.minHeight = Math.ceil(document.documentElement.scrollHeight) + 'px';
  }
  // the page reaches at least the window's bottom at scroll position y
  function setFloor(y) {
    const need = Math.ceil(y + window.innerHeight);
    floorPx = naturalBottom() < need ? need : 0;
    document.body.style.minHeight = floorPx ? floorPx + 'px' : '';
  }
  // where a card's head sticks (the window's top, below a notch's inset)
  function stickTop(head) {
    const h = head || $('card-head');
    const v = h ? parseFloat(getComputedStyle(h).top) : 0;
    return Number.isFinite(v) ? v : 0;
  }
  function spacerOf(card) { return card ? card.querySelector(':scope > .card-body > .card-spacer') : null; }
  // for each spacer that is set: where the content under it starts (gap: px
  // under the stuck head's bottom) and where the spacer's top is in the page
  // (top), kept up to date as the reader scrolls (see refitPlace)
  const spacerAt = new WeakMap();
  function notePlace(sp, under) {
    const r = sp.getBoundingClientRect();
    spacerAt.set(sp, { gap: Math.min(r.bottom, window.innerHeight) - under, top: r.top + window.scrollY });
  }
  function setSpacer(sp, px, noteTop) {
    if (!sp) return;
    if (px >= 1) {
      sp.style.height = Math.round(px) + 'px';
      sp.hidden = false;
      const note = sp.querySelector('.spacer-note');
      if (note) {
        if (noteTop !== undefined) note.style.top = Math.round(noteTop) + 'px';
        // a blank too short for its note has none (the note would lie over
        // the content under it)
        note.hidden = false;
        note.hidden = note.offsetHeight > Math.round(px);
      }
    } else {
      sp.style.height = '';
      sp.hidden = true;
      spacerAt.delete(sp);
    }
  }
  // The card turned to new content: if its top is above the window, its
  // new content starts right under its stuck head (or the window's top).
  // The spacer's box starts at the top of the card's body (it covers the
  // body's top padding) and its padding keeps that gap above the content.
  function turnCard(card) {
    if (!card || card.hidden) return;
    const sp = spacerOf(card);
    if (!sp) return;
    const head = card.querySelector(':scope > .card-head');
    const under = stickTop(head) + (head ? head.offsetHeight : 0);
    setSpacer(sp, under - sp.parentElement.getBoundingClientRect().top, under + 8);
    if (!sp.hidden) notePlace(sp, under);
  }
  function keepPlace(card, change, turn) {
    const y = window.scrollY;
    holdFloor();
    change();
    if (turn) turnCard(card);
    setFloor(y);
  }
  function clearPlace() {
    document.querySelectorAll('.card-spacer').forEach((sp) => setSpacer(sp, 0));
    floorPx = 0;
    document.body.style.minHeight = '';
  }
  // As the reader scrolls, drop what lies below the window: what cutBelow
  // drops of each spacer, and the body's minimum height.
  let trimFrame = 0;
  let fitFrame = 0;
  // Drop what of a spacer lies below the window's bottom (r: its box, under:
  // the stuck head's bottom, vh: the window's height); nothing in view
  // moves. A spacer all below the window goes. When the card's top is back
  // in view (the spacer's top at or under the stuck head's bottom), a rest
  // that reaches the window's bottom but is too short for its note goes
  // too: what was under it was below the window. False when it is gone.
  function cutBelow(sp, r, under, vh) {
    if (r.top >= vh) { setSpacer(sp, 0); return false; }
    if (r.bottom > vh) setSpacer(sp, vh - r.top - SPACER_PAD);
    const note = sp.querySelector('.spacer-note');
    if (!sp.hidden && r.top >= under && r.bottom >= vh - 1 && note && note.hidden) setSpacer(sp, 0);
    return !sp.hidden;
  }
  function trimPlace() {
    trimFrame = 0;
    const vh = window.innerHeight;
    document.querySelectorAll('.card-spacer:not([hidden])').forEach((sp) => {
      const r = sp.getBoundingClientRect();
      if (!r.height) return;
      const head = sp.closest('.card').querySelector(':scope > .card-head');
      const under = stickTop(head) + (head ? head.offsetHeight : 0);
      if (!cutBelow(sp, r, under, vh)) return;
      // (a pending refit needs the place the reader had before the resize)
      if (!fitFrame) spacerAt.set(sp, { gap: Math.min(r.bottom, vh) - under, top: r.top + window.scrollY });
    });
    if (floorPx) {
      const need = Math.ceil(window.scrollY + vh);
      if (naturalBottom() >= need) { floorPx = 0; document.body.style.minHeight = ''; }
      else if (need < floorPx) { floorPx = need; document.body.style.minHeight = need + 'px'; }
    }
  }
  window.addEventListener('scroll', () => { if (!trimFrame) trimFrame = requestAnimationFrame(trimPlace); }, { passive: true });
  // A window that changes its size (a tablet turned, a window resized) may
  // move what lies above a card. A spacer that is set is then set again:
  // - when the width changed, the card's content starts right under the
  //   stuck head again (or keeps the place the reader had scrolled to inside
  //   it), so that the blank and its note do not stay under the head;
  // - when only the height changed (a browser's bars, a window made taller),
  //   the content keeps its place in the page: the spacer takes up what the
  //   things above it gained or lost, if anything.
  // When the card's top is in view, the spacer keeps what of it is in view,
  // and what is below the window goes as when the reader scrolls (cutBelow).
  let fitWidth = window.innerWidth;
  function refitPlace() {
    fitFrame = 0;
    const widthChanged = window.innerWidth !== fitWidth;
    fitWidth = window.innerWidth;
    const y = window.scrollY;
    let changed = false;
    document.querySelectorAll('.card-spacer:not([hidden])').forEach((sp) => {
      const card = sp.closest('.card');
      if (!card || card.hidden) return;  // set again when the card shows
      const head = card.querySelector(':scope > .card-head');
      const under = stickTop(head) + (head ? head.offsetHeight : 0);
      const r = sp.getBoundingClientRect();
      if (!changed) { holdFloor(); changed = true; }
      if (r.top >= under) {
        // (the note's place and size at the window's new size first)
        setSpacer(sp, sp.offsetHeight - SPACER_PAD, under + 8);
        if (cutBelow(sp, sp.getBoundingClientRect(), under, window.innerHeight)) notePlace(sp, under);
        return;
      }
      const at = spacerAt.get(sp) || { gap: SPACER_PAD, top: r.top + y };
      // the content starts at the spacer's bottom
      if (widthChanged) setSpacer(sp, sp.offsetHeight - SPACER_PAD + (under + Math.min(at.gap, SPACER_PAD) - r.bottom), under + 8);
      else if (Math.abs(r.top + y - at.top) >= 1) setSpacer(sp, sp.offsetHeight - SPACER_PAD - (r.top + y - at.top), under + 8);
      if (!sp.hidden) notePlace(sp, under);
    });
    if (changed || floorPx) setFloor(y);
  }
  window.addEventListener('resize', () => { if (!fitFrame) fitFrame = requestAnimationFrame(refitPlace); });

  // ------------------------------------------------------------------
  // One map, three modes
  // ------------------------------------------------------------------
  const ui = { mode: 'explore', view: 'map', kind: 'all' };
  let m1 = null;          // the map (one full-size drawing, in every mode)
  let d1 = null;          // the part's detail, in the card
  let cur = ROOT;         // what the card shows: ROOT (the overview) or a node
  let focusAfter = null;  // a selector to focus after a re-render (keyboard users)

  function cssEsc(s) { return window.CSS && CSS.escape ? CSS.escape(s) : String(s).replace(/["\\]/g, '\\$&'); }

  function buildExplore() {
    m1 = buildMap($('map'), {
      pick: true,
      tour: true,
      label: 'Map of the parts of the system and the relations between them. Each part is a button that opens it in the card below the map.',
      onPick: (part) => {
        if (ui.mode !== 'explore') setMode('explore');
        openNode(part);
        setHash(nodeHash(part));
      }
    });
    d1 = buildDetail($('detail-view'), {
      onNode: (id) => {
        focusAfter = '#detail-view [data-node="' + cssEsc(id) + '"]';
        openNode(id);
        setHash(nodeHash(id));
      },
      onStub: (otherPart, otherNodes, fromPart) => {
        // the new detail's tag that leads back has the focus
        focusAfter = '#detail-view g.stub[data-other="' + cssEsc(fromPart) + '"]';
        openNode(otherPart, { hot: otherNodes });
        setHash(nodeHash(otherPart));
      }
    });
    // Emphasize: all, or one kind of relation
    const chips = $('chips');
    const kinds = [{ id: 'all', name: 'All' }].concat((Array.isArray(lay.map.kinds) ? lay.map.kinds : []).filter((k) => k && k.id));
    kinds.forEach((k) => {
      const b = el('button', { type: 'button', class: 'chip', 'data-kind': k.id, 'aria-pressed': k.id === 'all' ? 'true' : 'false' });
      if (k.id !== 'all') {
        const s = S('svg', { viewBox: '0 0 28 8', 'aria-hidden': 'true' });
        S('line', { x1: 0, y1: 4, x2: 28, y2: 4, class: 'ln ' + k.id }, s);
        b.append(s);
      }
      b.append(k.name);
      b.addEventListener('click', () => setKind(k.id));
      chips.append(b);
    });
  }

  // The caption of a kind: the caption of its small multiple (map.multiples).
  function kindCaption(k) {
    if (!k || k === 'all') return null;
    const mm = (Array.isArray(lay.map.multiples) ? lay.map.multiples : []).find((x) => x && x.kind === k);
    return mm && typeof mm.caption === 'string' && mm.caption.trim() ? mm.caption : null;
  }

  function setKind(k) {
    ui.kind = k;
    $('chips').querySelectorAll('.chip').forEach((c) => c.setAttribute('aria-pressed', c.dataset.kind === k ? 'true' : 'false'));
    const cap = $('kind-caption');
    cap.textContent = '';
    const text = kindCaption(k);
    if (text) {
      cap.dataset.kind = k;
      cap.append(el('b', { text: kindName(k) + '.' }), ' ');
      appendInline(cap, text);
    } else {
      cap.removeAttribute('data-kind');
    }
    cap.hidden = ui.mode !== 'explore' || !text;
    if (m1 && ui.mode === 'explore') m1.setFocus(k);
  }

  function setMode(mode) {
    const was = ui.mode;
    const y = window.scrollY;
    holdFloor();
    ui.mode = mode;
    document.body.dataset.mode = mode;
    document.querySelectorAll('#modes .mode').forEach((b) => b.setAttribute('aria-pressed', b.dataset.mode === mode ? 'true' : 'false'));
    const explore = mode === 'explore';
    const tour = mode === 'tour';
    const compare = mode === 'compare';
    const seqView = tour && ui.view === 'seq';
    $('mode-note').hidden = explore;
    $('note-tour').hidden = !tour;
    $('note-compare').hidden = !compare;
    $('chips').hidden = !explore;
    $('tour-controls').hidden = !tour;
    document.querySelectorAll('#tour-controls .view').forEach((b) => b.setAttribute('aria-pressed', b.dataset.view === ui.view ? 'true' : 'false'));
    // the stage: the map (Explore, the tour on the map), the sequence chart
    // (the tour's other view) or the small multiples (Compare kinds)
    $('map').hidden = compare || seqView;
    $('bar-map').hidden = compare || seqView;
    $('seq').hidden = !seqView;
    $('bar-seq').hidden = !seqView;
    $('seq-caption').hidden = !seqView;
    $('seq-key').hidden = !seqView || !$('seq-key').childNodes.length;
    $('mult').hidden = !compare;
    $('kind-caption').hidden = !explore || !kindCaption(ui.kind);
    $('map-caption').hidden = !explore || !$('map-caption').childNodes.length;
    $('map-omitted').hidden = !explore || !$('map-omitted').childNodes.length;
    $('tourbar').hidden = !tour;
    $('part-card').hidden = !explore;
    $('step-card').hidden = !tour;
    setBackLabels();
    if (m1) {
      if (tour) {
        m1.setFocus(null);
        if (was !== 'tour') stepShown = -1;
        tourGo(tourIndex, false);
      } else {
        m1.setTour(null);
        m1.setFocus(explore ? ui.kind : null);
        m1.select(explore && cur !== ROOT ? topOf(cur) : null, 'DETAIL BELOW');
      }
    }
    // the card that a mode brings back starts under the window's top
    if (explore && was !== 'explore') turnCard($('part-card'));
    setFloor(y);
    updateCuesSoon();
  }

  // The "Back to the map" links name what they go back to: the map, the
  // sequence chart (the tour's other view) or the small maps (Compare
  // kinds). A shown blank whose note's link changed fits its note again.
  function setBackLabels() {
    const text = ui.mode === 'compare' ? '\u2191 Back to the small maps'
      : ui.mode === 'tour' && ui.view === 'seq' ? '\u2191 Back to the sequence chart' : '\u2191 Back to the map';
    document.querySelectorAll('#studies a.back-to-map').forEach((a) => {
      if (a.textContent === text) return;
      a.textContent = text;
      const sp = a.closest('.card-spacer');
      if (sp && !sp.hidden && !sp.closest('.card').hidden) setSpacer(sp, sp.offsetHeight - SPACER_PAD);
    });
  }

  // A click on a mode button: the mode changes, the page stays.
  function switchMode(mode) {
    setMode(mode);
    if (mode === 'tour') setHash('#/tour/' + (tourIndex + 1));
    else if (mode === 'compare') setHash('#/compare');
    else setHash(cur === ROOT ? '#/' : nodeHash(cur));
  }

  function buildModes() {
    const host = $('modes');
    host.textContent = '';
    const T = idx.steps.length;
    const tourTitle = model.tour && typeof model.tour.title === 'string' ? model.tour.title : '';
    const defs = [
      { mode: 'explore', name: 'Explore the parts', sub: 'Tap a part to open its detail' },
      { mode: 'tour', name: 'Follow one event', sub: [tourTitle, T + (T === 1 ? ' step' : ' steps')].filter(Boolean).join(' \u00b7 ') },
      { mode: 'compare', name: 'Compare kinds', sub: 'One small map per kind of relation, and one with all' }
    ];
    defs.forEach((d) => {
      const b = el('button', { type: 'button', class: 'mode', 'data-mode': d.mode, 'aria-pressed': d.mode === ui.mode ? 'true' : 'false' }, [
        el('span', { class: 'mode-name', text: d.name }),
        el('span', { class: 'mode-sub', text: d.sub })
      ]);
      b.addEventListener('click', () => switchMode(d.mode));
      host.append(b);
    });
    document.querySelectorAll('#tour-controls .view').forEach((b) => b.addEventListener('click', () => {
      ui.view = b.dataset.view === 'seq' ? 'seq' : 'map';
      setMode('tour');
    }));
  }

  // The note above the stage in the tour and in Compare kinds: the section's
  // eyebrow and title as one heading line, then its text (the tour's texts
  // folded, so that the map and the step buttons stay in the first screen).
  function buildModeNote() {
    const note = $('mode-note');
    note.textContent = '';
    const head = (s) => {
      const h = el('h2', { class: 'note-head' });
      if (s.eyebrow) h.append(el('span', { class: 'eyebrow', text: s.eyebrow }));
      if (s.title) h.append(el('span', { text: s.title }));
      return h;
    };
    const st = section('tour');
    const tourNote = el('div', { id: 'note-tour' }, [head(st)]);
    const tourIntro = model.tour && typeof model.tour.intro === 'string' ? model.tour.intro : '';
    if (st.intro || tourIntro) {
      const about = el('details', { class: 'tour-about' }, [el('summary', { text: 'About this tour: what the dots and the diamond mean' })]);
      if (st.intro) about.append(prose(st.intro));
      if (tourIntro) about.append(prose(tourIntro, { class: 'prose tour-intro' }));
      tourNote.append(about);
    }
    const sm = section('multiples');
    const cmpNote = el('div', { id: 'note-compare' }, [head(sm)]);
    if (sm.intro) cmpNote.append(prose(sm.intro));
    cmpNote.append(el('p', { class: 'ui-note', text: 'Click or tap a copy to see the map in Explore the parts with that kind emphasized.' }));
    note.append(tourNote, cmpNote);
  }

  // ------------------------------------------------------------------
  // The card under the map (Explore the parts): the overview, or one part
  // ------------------------------------------------------------------
  let closeBtn = null;
  const cardList = () => [ROOT].concat(childrenOf(ROOT));
  const cardName = (p) => (p === ROOT ? 'Overview' : shortOf(p));
  const cardTitle = (p) => (p === ROOT ? 'Overview' : titleOf(p));

  function buildCard() {
    // the overview: the model's question, its summary, how to read the map
    const ov = $('overview');
    ov.textContent = '';
    if (model.question) ov.append(inlineProse('p', model.question, 'question'));
    if (model.summary) ov.append(prose(model.summary, { class: 'prose overview-summary' }));
    const sm = section('map');
    if (sm.title || sm.intro) {
      const h = el('h3');
      if (sm.eyebrow) h.append(el('span', { class: 'eyebrow', text: sm.eyebrow }));
      if (sm.title) h.append(el('span', { text: sm.title }));
      ov.append(el('div', { class: 'read-map' }, [h, prose(sm.intro)]));
    }
    // the head: previous and next go around the overview and the parts in
    // model order; Close (on a part only) returns to the overview
    $('card-prev').addEventListener('click', () => stepCard(-1));
    $('card-next').addEventListener('click', () => stepCard(1));
    closeBtn = el('button', { id: 'card-close', class: 'btn btn-small btn-close', type: 'button', 'aria-label': 'Close this part and show the overview' }, ['Close \u2715']);
    closeBtn.addEventListener('click', () => {
      showOverview();
      setHash('#/');
      focusQuietly($('card-title'));
    });
  }

  function stepCard(d) {
    const list = cardList();
    const at = list.indexOf(cur === ROOT ? ROOT : topOf(cur));
    const next = list[(at + d + list.length) % list.length];
    if (next === ROOT) { showOverview(); setHash('#/'); }
    else { openNode(next); setHash(nodeHash(next)); }
  }

  function renderHead() {
    const over = cur === ROOT;
    const part = over ? ROOT : topOf(cur);
    const id = over ? 'overview' : part;
    $('part-card').dataset.card = id;
    const t = $('card-title');
    t.dataset.card = id;
    // a box inside the part is open: the head names the part by its short
    // name (its full title stays the heading's name for screen readers and
    // its tooltip), then the box; nothing in the head is cut short
    const node = $('card-node');
    const lower = !over && cur !== part;
    const short = lower ? shortOf(part) : '';
    t.textContent = short || cardTitle(part);
    if (short && short !== cardTitle(part)) {
      t.setAttribute('aria-label', cardTitle(part));
      t.setAttribute('title', cardTitle(part));
    } else {
      t.removeAttribute('aria-label');
      t.removeAttribute('title');
    }
    node.textContent = lower ? '\u203a ' + titleOf(cur) : '';
    node.hidden = !lower;
    $('card-eyebrow').hidden = over || lower;
    $('card-hint').hidden = !over;
    const out = $('card-out');
    if (out) out.hidden = over || !isOut(part);
    const list = cardList();
    const i = list.indexOf(part);
    const prev = list[(i - 1 + list.length) % list.length];
    const next = list[(i + 1) % list.length];
    $('card-prev').textContent = '\u2190 ' + cardName(prev);
    $('card-prev').setAttribute('aria-label', 'Previous: ' + cardTitle(prev));
    $('card-next').textContent = cardName(next) + ' \u2192';
    $('card-next').setAttribute('aria-label', 'Next: ' + cardTitle(next));
    if (over) closeBtn.remove();
    else if (!closeBtn.isConnected) $('card-nav').append(closeBtn);
    $('card-end').textContent = over ? 'End of the overview.' : 'End of ' + titleOf(part) + '.';
  }

  function restoreFocus() {
    if (!focusAfter) return;
    const target = document.querySelector(focusAfter);
    focusAfter = null;
    focusQuietly(target || $('card-title'));
  }

  // Open a node in the card: its top-level part's detail (the node
  // highlighted) and the panel on the node.
  function openNode(id, o) {
    o = o || {};
    if (!idx.nodes.has(id)) return;
    const part = topOf(id);
    cur = id;
    const turn = $('part-card').dataset.card !== part;
    keepPlace($('part-card'), () => {
      $('overview').hidden = true;
      $('detail-view').hidden = false;
      $('detail').hidden = false;
      if (d1) d1.show(part, o.hot || (id === part ? null : id));
      renderPanel(id);
      renderHead();
    }, turn);
    if (m1 && ui.mode === 'explore') m1.select(part, 'DETAIL BELOW');
    restoreFocus();
  }

  // The card with no part open: the overview (on load and after Close).
  function showOverview() {
    cur = ROOT;
    const turn = $('part-card').dataset.card !== 'overview';
    keepPlace($('part-card'), () => {
      $('overview').hidden = false;
      $('detail-view').hidden = true;
      $('detail-view').textContent = '';
      $('detail').hidden = true;
      $('detail').textContent = '';
      renderHead();
    }, turn);
    if (m1 && ui.mode === 'explore') m1.select(null);
  }

  // A link to a node inside the page: the node opens in the card. A deep
  // link (a link in a card's text, flows or location line, marked
  // [data-moves-page]) also brings the card's head back to the top of the
  // window when it is above it; the links under the map never move the page.
  function followNodeLink(id, mayMove) {
    if (ui.mode !== 'explore') setMode('explore');
    openNode(id);
    setHash(nodeHash(id));
    const card = $('part-card');
    if (mayMove && card.getBoundingClientRect().top < 0) { clearPlace(); scrollToTop(card); }
    focusQuietly($('card-title'));
  }

  // ------------------------------------------------------------------
  // Follow one event: the tour on the map, its card under it
  // ------------------------------------------------------------------
  let d2 = null;
  let tourIndex = 0;
  let stepShown = -1;  // the step that the shown step card holds (-1: none)

  // A node's title and summary, and a button that opens its full
  // description in Explore the parts.
  function nodeSummary(id) {
    const frag = document.createDocumentFragment();
    const t = el('span', { class: 'pt', text: titleOf(id) });
    if (isOut(id)) t.append(el('span', { class: 'otxt', text: 'outside this repo' }));
    frag.append(t, inlineProse('p', (idx.nodes.get(id) || {}).summary, 'ps'));
    const b = el('button', { type: 'button', class: 'open-part linkish ui', 'data-moves-page': '', 'aria-label': 'Read the full description of ' + titleOf(id) + ' in Explore the parts' }, ['Read the full description']);
    b.addEventListener('click', () => openPart(id));
    frag.append(b);
    return frag;
  }

  function openPart(id) {
    setMode('explore');
    openNode(id);
    setHash(nodeHash(id));
    const card = $('part-card');
    if (card.getBoundingClientRect().top < 0) { clearPlace(); scrollToTop(card); }
    focusQuietly($('card-title'));
  }

  // a box of the step's detail, or a tag's neighbour, described under it
  function tourPick(id) {
    keepPlace($('step-card'), () => {
      const box = $('tour-pick');
      box.textContent = '';
      box.append(nodeSummary(id));
      box.hidden = false;
    });
  }

  function buildTour() {
    d2 = buildDetail($('tour-detail'), {
      onNode: (id) => tourPick(id),
      onStub: (otherPart, otherNodes, fromPart) => {
        keepPlace($('step-card'), () => {
          d2.show(otherPart, otherNodes);
          // "Where this step happens" names the step's own part only; its
          // place stays, so that the drawing under it does not move
          $('where-label').style.visibility = otherPart === topOf(idx.steps[tourIndex].node) ? '' : 'hidden';
        });
        tourPick(otherPart);
        focusQuietly(document.querySelector('#tour-detail g.stub[data-other="' + cssEsc(fromPart) + '"]') || $('tour-step-title'));
      }
    });
    const pips = $('pips');
    pips.textContent = '';
    idx.steps.forEach((s, i) => {
      const b = el('button', { type: 'button', class: 'pip', text: String(i + 1), 'aria-label': 'Step ' + (i + 1) + ': ' + s.title });
      b.addEventListener('click', () => tourGo(i, true));
      pips.append(b);
    });
    $('tour-prev').addEventListener('click', () => tourGo(tourIndex - 1, true));
    $('tour-next').addEventListener('click', () => tourGo(tourIndex + 1, true));
    // the step card's head (it stays in view while the step is read)
    $('step-prev').addEventListener('click', () => tourGo(tourIndex - 1, true));
    $('step-next').addEventListener('click', () => tourGo(tourIndex + 1, true));
    // and its end (each shown only where there is such a step)
    $('step-foot-prev').addEventListener('click', () => tourGo(tourIndex - 1, true));
    $('step-foot-next').addEventListener('click', () => tourGo(tourIndex + 1, true));
  }

  function renderStep(s, k, T) {
    const text = $('step-text');
    text.textContent = '';
    $('step-count').textContent = 'Step ' + k + ' of ' + T;
    text.append(el('div', { class: 'eyebrow', text: 'In ' + titleOf(topOf(s.node)) }));
    text.append(el('h2', { id: 'tour-step-title', tabindex: '-1', dataset: { stepIndex: String(k) }, text: s.title }));
    text.append(prose(s.prose, { id: 'tour-step-prose' }));
    // the step's code references and sources, folded
    const refs = $('step-refs');
    refs.textContent = '';
    const fold = (kind, title, items) => {
      if (!items.length) return;
      const d = foldBox(kind, 'h3', title, items.length);
      d.append(el('ul', { class: 'ref-list' }, items));
      refs.append(d);
    };
    fold('code', 'Code references', (Array.isArray(s.code_refs) ? s.code_refs : []).map(codeRefItem));
    fold('sources', 'Sources', (Array.isArray(s.sources) ? s.sources : []).map(sourceItem));
    // the component the step happens in: its own description follows the step
    const nd = $('step-node');
    nd.textContent = '';
    nd.append(nodeSummary(s.node));
    if (d2) d2.show(topOf(s.node), s.node);
    $('where-label').style.visibility = '';
    $('tour-pick').hidden = true;
    $('tour-pick').textContent = '';
    $('step-end').textContent = 'End of step ' + k + ' of ' + T + '.';
  }

  function tourGo(i, fromClick) {
    if (!idx.steps.length) return;
    tourIndex = Math.max(0, Math.min(idx.steps.length - 1, i));
    const k = tourIndex + 1;
    const s = idx.steps[tourIndex];
    const T = idx.steps.length;
    const pips = Array.from($('pips').querySelectorAll('.pip'));
    pips.forEach((p, j) => { if (j === tourIndex) p.setAttribute('aria-current', 'step'); else p.removeAttribute('aria-current'); });
    // a Back or Next button that becomes disabled hands its focus to the
    // pip (under the map) or to the other button of the card's head
    [['tour-prev', tourIndex === 0, pips[tourIndex]], ['tour-next', tourIndex === T - 1, pips[tourIndex]],
     ['step-prev', tourIndex === 0, $('step-next')], ['step-next', tourIndex === T - 1, $('step-prev')]].forEach(([bid, off, heir]) => {
      const b = $(bid);
      if (off && document.activeElement === b) focusQuietly(heir);
      b.disabled = off;
    });
    // the card's end shows "Previous step" and "Next step" only where there
    // is such a step; one that goes hands its focus to the other
    const footPrev = $('step-foot-prev');
    const footNext = $('step-foot-next');
    const hadFocus = document.activeElement;
    footPrev.hidden = tourIndex === 0;
    footNext.hidden = tourIndex === T - 1;
    if (hadFocus === footPrev && footPrev.hidden) focusQuietly(footNext);
    if (hadFocus === footNext && footNext.hidden) focusQuietly(footPrev);
    // another step (or the card shown again) starts under the window's top
    const turn = tourIndex !== stepShown;
    stepShown = tourIndex;
    keepPlace($('step-card'), () => renderStep(s, k, T), turn);
    if (m1 && ui.mode === 'tour') {
      m1.setTour(lay.tourByStep.get(s.id) || null);
      m1.select(topOf(s.node), 'THIS STEP');
    }
    document.querySelectorAll('#seq .row').forEach((r) => r.classList.toggle('cur', r.dataset.stepIndex === String(k)));
    $('seq-status').textContent = 'Step ' + k + ' of ' + T + ': ' + s.title;
    if (fromClick) setHash('#/tour/' + k);
  }

  // ------------------------------------------------------------------
  // Compare kinds: one small copy of the map per kind of relation, and
  // one with all of them; a copy opens Explore with its kind emphasized
  // ------------------------------------------------------------------
  function buildMultiples() {
    const host = $('mult');
    host.textContent = '';
    (Array.isArray(lay.map.multiples) ? lay.map.multiples : []).forEach((mm) => {
      if (!mm || !mm.kind) return;
      const isKind = lay.kindName.has(mm.kind);
      const name = isKind ? kindName(mm.kind) : (mm.title || 'All');
      const f = el('figure', {
        'data-kind': mm.kind, tabindex: '0', role: 'button', 'data-moves-page': '',
        'aria-label': name + ': show the map in Explore the parts with ' + (isKind ? 'this kind' : 'every kind') + ' emphasized'
      });
      const sheet = el('div', { class: 'sheet' });
      f.append(sheet);
      const label = isKind ? 'Small copy of the map showing only the ' + name + ' relation.' : 'Small copy of the map showing every kind of relation together.';
      const api = buildMap(sheet, { mini: true, kind: mm.kind, label: label });
      api.setFocus(mm.kind);
      const cap = el('figcaption', {}, [el('b', { text: name + '.' }), ' ']);
      if (mm.caption) appendInline(cap, mm.caption);
      f.append(cap);
      onActivate(f, () => {
        setKind(isKind ? mm.kind : 'all');
        setMode('explore');
        setHash(cur === ROOT ? '#/' : nodeHash(cur));
        // the mode switch and the pressed kind are in view: the map
        // section's top comes to the top of the window if it is above it
        const sec = $('map-section');
        if (sec.getBoundingClientRect().top < 0) { clearPlace(); scrollToTop(sec); }
        focusQuietly($('chips').querySelector('.chip[aria-pressed="true"]'));
      });
      host.append(f);
    });
  }

  // ------------------------------------------------------------------
  // Texts around the figures (from map.sections)
  // ------------------------------------------------------------------
  function renderCaptions() {
    const mc = $('map-caption');
    mc.textContent = '';
    if (section('map').caption) appendInline(mc, section('map').caption);
    // the sequence chart: its heading line, its intro and its caption
    const sq = section('sequence');
    const sc = $('seq-caption');
    sc.textContent = '';
    const head = [sq.eyebrow, sq.title].filter(Boolean).join(' \u00b7 ');
    if (head) sc.append(el('b', { text: head + '.' }), ' ');
    if (sq.intro) { appendInline(sc, sq.intro.replace(/\s*\n\s*/g, ' ')); sc.append(' '); }
    if (sq.caption) appendInline(sc, sq.caption);
    // the matrix card
    const sx = section('matrix');
    $('matrix-eyebrow').textContent = sx.eyebrow || '';
    $('matrix-eyebrow').hidden = !sx.eyebrow;
    $('matrix-title').textContent = sx.title || '';
    const intro = $('matrix-intro');
    intro.textContent = '';
    if (sx.intro) intro.append(prose(sx.intro));
    $('matrix-end').textContent = 'End of the ' + (sx.eyebrow ? sx.eyebrow.toLowerCase() : 'matrix') + '.';
  }

  // ------------------------------------------------------------------
  // The sequence chart (the other view of Follow one event): one row per
  // step; a row opens its step
  // ------------------------------------------------------------------
  function buildSequence() {
    const host = $('seq');
    host.textContent = '';
    const seq = lay.map.sequence;
    if (!seq || !Array.isArray(seq.lifelines)) return;
    const life = seq.lifelines;
    const X = new Map();
    life.forEach((l, i) => X.set(l.id, 150 + i * 122));
    const multi = new Set(life.filter((l) => l.multi).map((l) => l.id));
    const rows = Array.isArray(seq.rows) ? seq.rows : [];
    const W = 150 + (life.length - 1) * 122 + 106;
    const y0 = 92;
    const dy = 41;
    const H = y0 + dy * Math.max(0, rows.length - 1) + 40;
    const svg = S('svg', { viewBox: '0 0 ' + W + ' ' + H, class: 'seq', role: 'group', 'aria-label': 'Sequence chart of one event: one column per part, one row per tour step, time running down.' }, host);
    const mk = markers(svg);
    const gl = S('g', null, svg);
    const gr = S('g', null, svg);
    life.forEach((l) => {
      const x = X.get(l.id);
      if (multi.has(l.id)) [-6, 0, 6].forEach((o) => S('line', { x1: x + o, y1: 58, x2: x + o, y2: H - 14, class: 'life' }, gl));
      else S('line', { x1: x, y1: 58, x2: x, y2: H - 14, class: 'life' }, gl);
      const g = S('g', { class: 'hdr' + (l.out ? ' out' : ''), 'data-lifeline': l.id }, gl);
      S('rect', { x: x - 54, y: 22, width: 108, height: 34, rx: 3 }, g);
      const t = stext(g, x, 44, l.name, 't-title', { 'text-anchor': 'middle' });
      const w = measure(l.name, 't-title');
      if (w > 96) t.style.fontSize = r1(15 * 96 / w) + 'px';
    });
    const stepIdx = new Map(idx.steps.map((s, i) => [s.id, i]));
    rows.forEach((m, i) => {
      const k = stepIdx.has(m.step) ? stepIdx.get(m.step) : i;
      const step = idx.steps[k];
      const y = y0 + i * dy;
      const g = S('g', { class: 'row', tabindex: '0', role: 'button', 'data-step-index': k + 1, 'aria-label': 'Step ' + (k + 1) + ': ' + (step ? step.title : '') }, gr);
      S('rect', { x: 8, y: y - 24, width: W - 16, height: dy - 2, rx: 3, class: 'hit' }, g);
      S('circle', { cx: 30, cy: y - 4, r: 11, class: 'numc' }, g);
      stext(g, 30, y, String(k + 1), 'num', { 'text-anchor': 'middle' });
      const kind = m.kind;
      const edge = (n, toward) => (multi.has(n) ? X.get(n) + (toward > X.get(n) ? 6 : -6) : X.get(n));
      if (m.from === m.to && X.has(m.from)) {
        const lft = life.length && life[life.length - 1].id === m.from;
        const x = X.get(m.from) + (multi.has(m.from) ? 6 : 0);
        S('path', { d: 'M' + x + ',' + (y - 9) + (lft ? ' h-24 v12 h22' : ' h24 v12 h-22'), class: 'ln ' + kind, 'marker-end': mk(kind) }, g);
        stext(g, lft ? x - 32 : x + 32, y - 3, m.label, 't-lab lab halo ' + kind, lft ? { 'text-anchor': 'end' } : null);
      } else if (X.has(m.to)) {
        const start = !X.has(m.from);
        const xf = start ? X.get(m.to) - 92 : edge(m.from, X.get(m.to));
        const xt = edge(m.to, xf);
        if (start) S('circle', { cx: xf, cy: y, r: 4.5, class: 'dot ' + kind }, g);
        S('path', { d: 'M' + xf + ',' + y + ' H' + xt, class: 'ln ' + kind + (m.out ? ' out' : ''), 'marker-end': mk(m.out ? 'out' : kind) }, g);
        stext(g, (xf + xt) / 2, y - 7, m.label, 't-lab lab halo ' + (m.out ? 'out' : kind), { 'text-anchor': 'middle' });
        (Array.isArray(m.dots) ? m.dots : []).forEach((n) => {
          if (!X.has(n)) return;
          if (multi.has(n)) [-6, 0, 6].forEach((o) => S('circle', { cx: X.get(n) + o, cy: y, r: 3, class: 'dot ' + kind }, g));
          else S('circle', { cx: X.get(n), cy: y, r: 3.5, class: 'dot ' + kind }, g);
        });
        [m.from, m.to].filter((n) => multi.has(n)).forEach((n) => [-6, 0, 6].forEach((o) => S('circle', { cx: X.get(n) + o, cy: y, r: 2.6, class: 'dot ' + kind }, g)));
      }
      // a row opens its step in place: the card under the chart and the
      // status line change, the page does not move
      onActivate(g, () => tourGo(k, true));
    });
    // the key to the colour of what lies outside this repository
    const key = $('seq-key');
    key.textContent = '';
    if (rows.some((m) => m.out) || life.some((l) => l.out)) {
      const sw = S('svg', { viewBox: '0 0 28 8', 'aria-hidden': 'true' });
      S('line', { x1: 0, y1: 4, x2: 28, y2: 4, class: 'ln out' }, sw);
      key.append(sw, 'Outside this repository: an arrow drawn in this colour, or a column head framed by a dashed line of this colour.');
    }
  }
  // ------------------------------------------------------------------
  // The N² matrix (the reference card after the map section)
  // ------------------------------------------------------------------
  function buildMatrix() {
    const host = $('nsq');
    host.textContent = '';
    const order = childrenOf(ROOT);
    const cell = new Map();
    for (const e of idx.edges) {
      const a = topOf(e.from);
      const b = topOf(e.to);
      if (a === b) continue;
      const k = a + '|' + b;
      if (!cell.has(k)) cell.set(k, []);
      cell.get(k).push(e);
    }
    const tint = lay.map && lay.map.ladder && idx.nodes.has(lay.map.ladder.node) ? topOf(lay.map.ladder.node) : null;
    const table = el('table', { class: 'nsq' });
    const hr = el('tr', {}, [el('th', { scope: 'col', text: 'from \u2193 \u00b7 to \u2192' })]);
    order.forEach((o) => hr.append(el('th', { scope: 'col', 'data-part': o, text: shortOf(o) })));
    table.append(el('thead', {}, [hr]));
    const tb = el('tbody');
    order.forEach((a) => {
      const tr = el('tr', {}, [el('td', { 'data-part': a, text: shortOf(a) })]);
      order.forEach((b) => {
        if (a === b) { tr.append(el('td', { class: 'diag', 'aria-label': 'same part', text: '\u2014' })); return; }
        const td = el('td', { 'data-from': a, 'data-to': b, class: (a === tint || b === tint) ? 'ctl' : null });
        const groups = new Map();
        (cell.get(a + '|' + b) || []).forEach((e) => {
          const k = e.kind + '\u0000' + e.label;
          if (!groups.has(k)) groups.set(k, { kind: e.kind, label: e.label, ids: [] });
          groups.get(k).ids.push(e.id);
        });
        groups.forEach((gp) => {
          const s = S('svg', { viewBox: '0 0 22 8', 'aria-hidden': 'true' });
          S('line', { x1: 0, y1: 4, x2: 22, y2: 4, class: 'ln ' + gp.kind }, s);
          td.append(el('div', { class: 'ni', 'data-edge-ids': gp.ids.join(' '), 'data-kind': gp.kind }, [s, el('span', { text: gp.label })]));
        });
        tr.append(td);
      });
      tb.append(tr);
    });
    table.append(tb);
    host.append(table);
    // one line under the table that says what the shading means
    const key = $('nsq-key');
    if (key) {
      key.textContent = '';
      if (tint) key.append(el('span', { class: 'sw ctl', 'aria-hidden': 'true' }), 'Shaded: the ' + shortOf(tint) + ' row and column. ');
      key.append(el('span', { class: 'sw diag', 'aria-hidden': 'true', text: '—' }), 'The diagonal: a part with itself.');
      key.hidden = false;
    }
  }
  // ------------------------------------------------------------------
  // Figure frames: the scroll cue and the Full size buttons
  // ------------------------------------------------------------------
  // A frame (a .sheet, or the matrix's .tbl) whose content is wider than the
  // frame gets data-scrolls="true", a visible hint (.scroll-hint) and a fade
  // on the side where more of the figure is.
  const cues = new Set();
  function scrollCue(box, hint, o) {
    if (!box) return;
    const c = { box: box, hint: hint || null, leftFade: !(o && o.noLeftFade) };
    cues.add(c);
    box.addEventListener('scroll', () => updateCue(c), { passive: true });
    updateCue(c);
  }
  function updateCue(c) {
    const b = c.box;
    const over = b.clientWidth > 0 && b.scrollWidth - b.clientWidth > 1;
    if (over) b.setAttribute('data-scrolls', 'true'); else b.removeAttribute('data-scrolls');
    b.classList.toggle('more-right', over && b.scrollLeft + b.clientWidth < b.scrollWidth - 1);
    b.classList.toggle('more-left', over && c.leftFade && b.scrollLeft > 1);
    if (c.hint) c.hint.hidden = !over;
  }
  function updateCues() {
    cues.forEach((c) => { if (!c.box.isConnected) cues.delete(c); else updateCue(c); });
  }
  let cueFrame = 0;
  function updateCuesSoon() {
    if (cueFrame) return;
    cueFrame = requestAnimationFrame(() => { cueFrame = 0; updateCues(); });
  }
  // "Full size": the figure at its natural size (1 viewBox unit = 1 CSS px)
  // inside its scrolling frame; pressed again, it fits the frame (default).
  // It never makes a figure smaller: where the frame is wider than the
  // natural size (the sequence chart on a wide window), the figure keeps
  // the frame's width.
  function setFull(sheet, on) {
    const svg = sheet.querySelector(':scope > svg');
    const w = svg && svg.viewBox && svg.viewBox.baseVal ? svg.viewBox.baseVal.width : 0;
    const full = !!(on && w);
    sheet.classList.toggle('full', full);
    if (svg) svg.style.width = full ? 'max(' + w + 'px, 100%)' : '';
    updateCues();
    return full;
  }
  function bindFrames() {
    document.querySelectorAll('button.fullsize').forEach((b) => {
      const sheet = $(b.getAttribute('aria-controls'));
      if (!sheet) { b.hidden = true; return; }
      b.addEventListener('click', () => {
        const full = setFull(sheet, b.getAttribute('aria-pressed') !== 'true');
        b.setAttribute('aria-pressed', full ? 'true' : 'false');
      });
    });
    // each frame's bar (under the map and the sequence chart, above the
    // matrix) holds the hint that the frame scrolls sideways
    [['map', 'bar-map'], ['seq', 'bar-seq'], ['nsq', 'bar-nsq']].forEach(([box, bar]) => {
      if ($(box) && $(bar)) scrollCue($(box), $(bar).querySelector('.scroll-hint'), { noLeftFade: box === 'nsq' });
    });
    window.addEventListener('resize', updateCuesSoon);
  }

  // Relations between two parts that the map does not draw (map.omitted),
  // listed under the map's caption with the model's reason.
  function renderOmitted() {
    const host = $('map-omitted');
    if (!host) return;
    host.textContent = '';
    const list = (Array.isArray(lay.map.omitted) ? lay.map.omitted : []).filter((o) => o && idx.edgeById.has(o.edge));
    host.hidden = !list.length;
    if (!list.length) return;
    host.append(el('div', { class: 'omitted-head', text: 'Not drawn on the map' }));
    const ul = el('ul');
    list.forEach((o) => {
      const e = idx.edgeById.get(o.edge);
      const a = topOf(e.from);
      const b = topOf(e.to);
      const li = el('li', { dataset: { edgeId: e.id }, 'data-kind': e.kind });
      // (not deep links: the part opens in the card right under this list,
      // and the page stays where it is)
      li.append(el('span', { class: 'om-pair' }, [link(nodeHash(a), shortOf(a)), ' \u2192 ', link(nodeHash(b), shortOf(b))]), ': ', e.label, ' \u2014 ');
      if (typeof o.reason === 'string') appendInline(li, o.reason);
      ul.append(li);
    });
    host.append(ul);
  }
  // ------------------------------------------------------------------
  // The one-page view
  // ------------------------------------------------------------------
  // A link from the one-page view back to the map: a deep link (the page
  // moves to what it names).
  function mapLink(hash, text, cls) {
    const a = link(hash, text, cls);
    a.setAttribute('data-moves-page', '');
    return a;
  }

  function renderReadPage(st) {
    const page = $('read-page');
    page.textContent = '';
    xrefHash = readHash;
    try {
      page.append(el('p', { class: 'read-note', text: 'The design model as one document: the question and the summary, then every part with its sub-parts in order, then the tour. The map, the sequence chart and the matrix are not on this page.' }));
      page.append(inlineProse('p', model.question, 'question'));
      page.append(prose(model.summary, { class: 'prose read-summary' }));

      const toc = el('nav', { class: 'read-toc', 'aria-label': 'Contents' }, [el('h2', { text: 'Contents' })]);
      const ol = el('ol');
      for (const id of childrenOf(ROOT)) ol.append(el('li', {}, [link(readHash(id), titleOf(id))]));
      if (idx.steps.length) ol.append(el('li', {}, [link('#/read/tour', model.tour.title)]));
      toc.append(ol);
      page.append(toc);

      const addNode = (id, depth) => {
        const n = idx.nodes.get(id);
        const sec = el('section', { class: 'read-node depth-' + depth, id: 'read-' + id, dataset: { nodeId: id } });
        sec.append(el('h' + Math.min(6, depth + 1), { class: 'read-title' }, [n.title]));
        const where = pathTo(id).slice(0, -1);
        sec.append(el('p', { class: 'read-path' }, [
          where.length ? 'Part of ' + where.map(titleOf).join(' \u203a ') + '. ' : '',
          mapLink(nodeHash(id), 'Open in Explore the parts', 'read-map-link')
        ]));
        appendNodeBody(sec, n, 'h' + Math.min(6, depth + 2), 'h' + Math.min(6, depth + 3), { proseId: null });
        const out = idx.edges.filter((e) => e.from === id);
        if (out.length) {
          sec.append(el('h' + Math.min(6, depth + 2), { text: 'Flows out of this part' }));
          sec.append(el('ul', { class: 'flow-list' }, out.map((e) => {
            const li = el('li', { class: 'flow kind-' + e.kind });
            li.append(el('div', { class: 'flow-head' }, [
              el('span', { class: 'badge badge-kind kind-' + e.kind, text: kindName(e.kind) }),
              el('span', { class: 'flow-dir', text: ' \u2192 to ' }),
              link(readHash(e.to), titleOf(e.to), 'xref flow-end'),
              el('span', { class: 'flow-where', text: whereText(e.to) })
            ]));
            flowExtras(li, e);
            return li;
          })));
        }
        page.append(sec);
        for (const c of childrenOf(id)) addNode(c, depth + 1);
      };
      for (const id of childrenOf(ROOT)) addNode(id, 1);

      if (idx.steps.length) {
        const sec = el('section', { class: 'read-tour', id: 'read-tour' });
        sec.append(el('h2', { class: 'read-title' }, [model.tour.title]));
        sec.append(prose(model.tour.intro, { class: 'prose tour-intro' }));
        const steps = el('ol', { class: 'read-steps' });
        idx.steps.forEach((s, i) => {
          const li = el('li', { class: 'read-step', dataset: { stepIndex: String(i + 1) } });
          li.append(el('h3', { text: s.title }));
          li.append(el('p', { class: 'read-path' }, ['Part: ', link(readHash(s.node), titleOf(s.node)), ' \u00b7 ', mapLink('#/tour/' + (i + 1), 'Show this step on the map')]));
          li.append(prose(s.prose));
          const refs = referenceList(s.code_refs, s.sources);
          if (refs) li.append(refs);
          steps.append(li);
        });
        sec.append(steps);
        page.append(sec);
      }
    } finally {
      xrefHash = nodeHash;
    }
    scrollToReadPlace(st);
  }
  // Bring what a #/read address names to the top of the window: a node's
  // section, the tour, or the top of the page.
  function scrollToReadPlace(st) {
    const targetId = st.target ? 'read-' + st.target : (/^#\/read\/tour$/.test(location.hash) ? 'read-tour' : null);
    const target = targetId ? $(targetId) : null;
    if (target) target.scrollIntoView({ block: 'start' });
    else window.scrollTo(0, 0);
  }
  // ------------------------------------------------------------------
  // Header, help and events
  // ------------------------------------------------------------------
  function renderHeader() {
    $('model-title').textContent = model.title;
    document.title = model.title;
  }

  // The help is an overlay over the page (fixed; it scrolls inside
  // itself), so that opening and closing it never moves the page. Close
  // (at its top and bottom), Escape or a click beside the panel closes it,
  // and the focus goes back to "How to read this page".
  function toggleHelp(show) {
    const help = $('help');
    const open = show === undefined ? help.hidden : show;
    help.hidden = !open;
    $('help-toggle').setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open) { help.scrollTop = 0; focusQuietly($('help-title')); }
    else focusQuietly($('help-toggle'));
  }

  function bindEvents() {
    $('read-toggle').addEventListener('click', () => go(state && state.mode === 'read' ? '#/' : '#/read'));
    $('help-toggle').addEventListener('click', () => toggleHelp());
    $('help').querySelectorAll('#help-close, .help-close').forEach((b) => b.addEventListener('click', () => toggleHelp(false)));
    $('help').addEventListener('click', (ev) => { if (ev.target === $('help')) toggleHelp(false); });
    // the keyboard stays in the help while it is open
    $('help').addEventListener('keydown', (ev) => {
      if (ev.key !== 'Tab') return;
      const f = Array.from($('help').querySelectorAll('button, a[href], summary, [tabindex="0"]')).filter((x) => x.offsetParent !== null);
      if (!f.length) return;
      const first = f[0];
      const last = f[f.length - 1];
      if (ev.shiftKey && (document.activeElement === first || document.activeElement === $('help-title'))) { ev.preventDefault(); focusQuietly(last); }
      else if (!ev.shiftKey && document.activeElement === last) { ev.preventDefault(); focusQuietly(first); }
    });
    document.addEventListener('keydown', (ev) => {
      if (ev.altKey || ev.ctrlKey || ev.metaKey) return;
      const t = ev.target;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
      if (ev.key === 'Escape' && !$('help').hidden) { ev.preventDefault(); toggleHelp(false); }
    });
    // Links inside the map section and the matrix card: "Back to the map"
    // scrolls to the map; a link to a node opens it in the card (see
    // followNodeLink); the link to the overview in a part's location line
    // closes the part. None of them adds a history entry.
    $('studies').addEventListener('click', (ev) => {
      if (ev.defaultPrevented || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
      const a = ev.target && ev.target.closest ? ev.target.closest('a[href]') : null;
      if (!a) return;
      if (a.classList.contains('back-to-map')) {
        ev.preventDefault();
        clearPlace();
        scrollToTop($('map-section'), true);
        focusQuietly($('map-section'));
        return;
      }
      const href = a.getAttribute('href');
      if (!/^#\//.test(href)) return;
      const target = parseHash(href);
      if (target.mode === 'explore' && !target.message) {
        ev.preventDefault();
        if (target.focus !== ROOT) followNodeLink(target.focus, a.hasAttribute('data-moves-page'));
        else {
          if (ui.mode !== 'explore') setMode('explore');
          showOverview();
          setHash('#/');
          focusQuietly($('card-title'));
        }
      }
    });
    // Left and Right move the tour only in Follow one event, and only while
    // the focus is in the map section (a click anywhere in it puts the focus
    // there: it has tabindex="-1"). Elsewhere the keys keep their own
    // meaning, and so they do in a frame that scrolls sideways (the map or
    // the chart at full size, or on a narrow screen).
    let pointerFrame = null;
    $('map-section').addEventListener('pointerdown', (ev) => {
      pointerFrame = ev.target && ev.target.closest ? ev.target.closest('.sheet') : null;
    });
    $('map-section').addEventListener('keydown', (ev) => {
      if (ev.altKey || ev.ctrlKey || ev.metaKey || ev.shiftKey) return;
      if (ev.key !== 'ArrowRight' && ev.key !== 'ArrowLeft') return;
      if (!state || state.mode === 'read' || ui.mode !== 'tour') return;
      const t = ev.target;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
      if (t && t.closest && t.closest('[data-scrolls="true"]')) return;
      if (t === $('map-section') && pointerFrame && pointerFrame.getAttribute('data-scrolls') === 'true') return;
      ev.preventDefault();
      tourGo(tourIndex + (ev.key === 'ArrowRight' ? 1 : -1), true);
    });
    // A link in the one-page view to the address it already has fires no
    // hashchange: it brings its place to the top of the window here (no
    // re-render, no history entry).
    $('read-page').addEventListener('click', (ev) => {
      if (ev.defaultPrevented || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
      const a = ev.target && ev.target.closest ? ev.target.closest('a[href^="#/read"]') : null;
      if (!a || a.getAttribute('href') !== location.hash) return;
      ev.preventDefault();
      scrollToReadPlace(parseHash());
    });
    window.addEventListener('hashchange', () => route(true));
  }

  async function fontsReady() {
    if (!document.fonts) return;
    const faces = ['600 15px Archivo', '650 15px Archivo', '400 12.5px Archivo', '700 12px Archivo', '550 12px Archivo', 'italic 13px "Source Serif 4"', '17px "Source Serif 4"'];
    const timeout = new Promise((resolve) => setTimeout(resolve, 4000));
    try {
      await Promise.race([Promise.all(faces.map((f) => document.fonts.load(f).catch(() => null))).then(() => document.fonts.ready), timeout]);
    } catch (e) { /* draw with the fallback fonts */ }
  }
  async function start() {
    bindEvents();
    try {
      const response = await fetch(MODEL_URL, { cache: 'no-cache' });
      if (!response.ok) throw new Error('HTTP ' + response.status + ' ' + response.statusText);
      const data = await response.json();
      if (!data || !Array.isArray(data.nodes)) throw new Error('the file has no "nodes" list');
      model = data;
      buildIndex(model);
    } catch (err) {
      document.body.dataset.error = 'true';
      $('model-title').textContent = 'The design model could not be loaded';
      showMessage('Could not load the design model (' + MODEL_URL + '): ' + err.message, true);
      return;
    }
    renderHeader();
    await fontsReady();
    if (lay.map) {
      buildExplore();
      buildCard();
      buildModes();
      buildModeNote();
      buildTour();
      buildMultiples();
      buildSequence();
      buildMatrix();
      renderCaptions();
      renderOmitted();
      bindFrames();
      setKind('all');
    } else {
      $('studies').hidden = true;
      showMessage('The design model has no map layout ("map" block); only the one-page view is available.', true);
    }
    const initial = parseHash();
    if (initial.mode !== 'tour') tourGo(0, false);
    // a page opened at a deep link lands on what it names; #/ stays at the top
    route(initial.mode !== 'explore' || initial.focus !== ROOT);
    document.body.dataset.ready = 'true';
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
