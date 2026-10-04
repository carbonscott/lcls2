/*
 * Viewer for the DAQ design model (daq-model.json).
 *
 * The model is the only source of content: this file holds the user
 * interface only. Every string about the DAQ (node and edge text, map
 * labels, captions, section texts, short names, kind names, lane and state
 * names) and every map coordinate is read from the JSON. Model text enters
 * the page only as DOM text nodes (never as HTML).
 *
 * The page has five sections, in this order:
 *   #map-section  the fixed map (model "map" block and each part's "place"),
 *                 with the detail of one part under it (its "detail" grid)
 *                 and the node panel (#detail)
 *   #tour         the tour moves the event over the same map
 *   #multiples    one small copy of the map per relation kind
 *   #sequence     the tour as one sequence chart
 *   #matrix       every relation between two parts, with no lines
 *
 * State: one hash route.
 *   #/              top; the detail shows map.default_detail
 *   #/node/<id>     the detail of the node's top-level part, node highlighted;
 *                   the panel describes the node
 *   #/tour/<k>      tour step k (1-based)
 *   #/read          the whole model as one page; #/read/<id> scrolls to a node
 * Clicks change the hash with history.replaceState (no scroll jump).
 *
 * Test hooks: see tools/README.md and the interface spec (body[data-ready],
 * body[data-mode], #map svg.map g.box[data-part][data-node][data-box],
 * path.ln[data-line], #chips .chip[data-kind], #detail-view svg.detail
 * [data-detail], g.stub[data-other][data-dir], #detail-title[data-node-id],
 * #detail-prose, #tour-prev, #tour-next, #pips .pip, #tour-step-title
 * [data-step-index], #tour-step-prose, g.callout[data-part], g.tok
 * [data-t][data-target], #multiples svg.mini[data-kind], #sequence .row
 * [data-step-index], #matrix table.nsq td[data-from][data-to], #read-page
 * section[data-node-id], #help-toggle, #help).
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
  function setHash(hash, mode) {
    if (location.hash !== hash) history.replaceState(null, '', hash);
    document.body.dataset.mode = mode;
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
        if (idx.nodes.has(id)) parent.append(link(xrefHash(id), m[3] !== undefined ? m[3] : titleOf(id), 'xref'));
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

  function parseHash() {
    let h = location.hash.replace(/^#/, '');
    try { h = decodeURIComponent(h); } catch (e) { /* keep the raw text */ }
    if (h === '' || h === '/') return { mode: 'browse', focus: ROOT };
    let m = /^\/node\/(.+)$/.exec(h);
    if (m) {
      if (idx.nodes.has(m[1])) return { mode: 'browse', focus: m[1] };
      return { mode: 'browse', focus: ROOT, message: 'There is no part with the id "' + m[1] + '" in the design model. Showing the top of the page.' };
    }
    m = /^\/tour(?:\/(\d+))?\/?$/.exec(h);
    if (m) {
      const k = m[1] === undefined ? 1 : parseInt(m[1], 10);
      if (k >= 1 && k <= idx.steps.length) return { mode: 'tour', step: k, focus: idx.steps[k - 1].node };
      return { mode: 'browse', focus: ROOT, message: 'There is no tour step ' + m[1] + '. Showing the top of the page.' };
    }
    m = /^\/read(?:\/(.+?))?\/?$/.exec(h);
    if (m) {
      const target = m[1] && idx.nodes.has(m[1]) ? m[1] : null;
      return { mode: 'read', focus: ROOT, target: target };
    }
    return { mode: 'browse', focus: ROOT, message: 'Unknown link "#' + h + '". Showing the top of the page.' };
  }

  function scrollToSection(id) {
    const sec = $(id);
    if (sec) sec.scrollIntoView({ block: 'start', behavior: 'auto' });
  }

  function route(scroll) {
    if (!model) return;
    const prev = state;
    state = parseHash();
    showMessage(state.message || '');
    const reading = state.mode === 'read';
    $('read-page').hidden = !reading;
    $('studies').hidden = reading;
    $('read-toggle').textContent = reading ? 'Back to the map' : 'Read as one page';
    $('read-toggle').setAttribute('aria-pressed', reading ? 'true' : 'false');
    document.body.dataset.mode = state.mode;
    if (reading) {
      renderReadPage(state);
      return;
    }
    updateCuesSoon();
    if (state.mode === 'tour') {
      if (d1 && !d1.current()) openNode(defaultPart());
      tourGo(state.step - 1, false);
      if (scroll) scrollToSection('tour');
    } else if (state.focus !== ROOT) {
      openNode(state.focus);
      // a link to a node (a deep link, a cross-reference, "Show on the map")
      // brings the node's detail view and the panel under it into view; a
      // click on the map itself does not scroll (it changes no hash)
      if (scroll) scrollToSection('detail-view');
    } else {
      openNode(defaultPart());
      if (scroll && prev && prev.mode === 'read') window.scrollTo(0, 0);
    }
  }

  function showMessage(text, isError) {
    const box = $('message');
    box.textContent = text;
    box.hidden = !text;
    box.classList.toggle('error', !!isError);
  }

  function defaultPart() {
    const d = lay.map && lay.map.default_detail;
    if (d && idx.nodes.has(d)) return topOf(d);
    return childrenOf(ROOT)[0];
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
    function select(part, tag) {
      G.call.textContent = '';
      const rs = reg.parts.get(part);
      if (!rs || !rs.length) return;
      const x0 = Math.min(...rs.map((r) => r.x)) - 7;
      const y0 = Math.min(...rs.map((r) => r.y)) - 7;
      const x1 = Math.max(...rs.map((r) => r.x + r.w)) + 7;
      const y1 = Math.max(...rs.map((r) => r.y + r.h)) + 7;
      const g = S('g', { class: 'callout', 'data-part': part }, G.call);
      S('rect', { x: x0, y: y0, width: x1 - x0, height: y1 - y0, rx: 5, class: 'cbox' }, g);
      const w = measure(tag, 'calltxt') + 14;
      const tx = Math.min(x0, vb.w - w - 2);
      const ty = y1 + 18 <= vb.h ? y1 - 1 : y0 - 17;
      S('rect', { x: tx, y: ty, width: r1(w), height: 18, class: 'ctag' }, g);
      stext(g, tx + 7, ty + 13.5, tag, 'calltxt');
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
      const head = el('div', { class: 'dhead' }, [
        el('span', { class: 'eyebrow', text: 'Detail' }),
        el('h3', { text: titleOf(part), tabindex: '-1' }),
        hint
      ]);
      host.append(head);
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
    panel.append(el('h2', { id: 'detail-title', class: 'detail-title', dataset: { nodeId: id }, tabindex: '-1', text: n.title }));
    const path = el('nav', { class: 'detail-path', 'aria-label': 'Location in the model' });
    [ROOT].concat(pathTo(id)).forEach((p, i, all) => {
      if (i > 0) path.append(el('span', { class: 'crumb-sep', 'aria-hidden': 'true', text: ' \u203a ' }));
      if (i === all.length - 1) path.append(el('span', { text: titleOf(p) }));
      else path.append(link(nodeHash(p), p === ROOT ? 'Top of the page' : titleOf(p)));
    });
    panel.append(path);
    appendNodeBody(panel, n, 'h3', 'h4', true);
  }

  // The body of a node: outside note, summary, prose, developer notes,
  // decisions, code references, sources and (optionally) flows.
  function appendNodeBody(box, n, h3, h4, withFlows, proseId) {
    if (n.outside_repo === true) {
      box.append(el('p', { class: 'outside-note' }, [
        el('span', { class: 'badge-outside', text: 'Outside this repo' }),
        ' The mechanism of this part is not implemented in the lcls2 repository (for example firmware, another repository or a facility service). Its description is based on the external sources listed below; the text says which pieces, if any, are in this repository.'
      ]));
    }
    box.append(inlineProse('p', n.summary, 'summary'));
    box.append(prose(n.prose, proseId === null ? {} : { id: proseId || 'detail-prose' }));

    if (typeof n.dev_notes === 'string' && n.dev_notes.trim()) {
      box.append(el(h3, { text: 'For developers' }));
      box.append(prose(n.dev_notes, { class: 'prose dev-notes' }));
    }

    const decisions = Array.isArray(n.decisions) ? n.decisions : [];
    if (decisions.length) {
      box.append(el(h3, { text: 'Design decisions' }));
      for (const d of decisions) {
        const art = el('article', { class: 'decision-card' });
        art.append(el(h4, { text: d.title }));
        art.append(el('div', { class: 'decision-label', text: 'Decision' }));
        art.append(prose(d.decision));
        art.append(el('div', { class: 'decision-label', text: 'Why' }));
        art.append(prose(d.rationale));
        const refs = referenceList(d.code_refs, d.sources);
        if (refs) art.append(refs);
        box.append(art);
      }
    }

    const codeRefs = Array.isArray(n.code_refs) ? n.code_refs : [];
    if (codeRefs.length) {
      box.append(el(h3, { text: 'Code references' }));
      box.append(el('ul', { class: 'ref-list' }, codeRefs.map(codeRefItem)));
    }
    const sourceIds = Array.isArray(n.sources) ? n.sources : [];
    if (sourceIds.length) {
      box.append(el(h3, { text: 'Sources' }));
      box.append(el('ul', { class: 'ref-list' }, sourceIds.map(sourceItem)));
    }

    if (!withFlows) return;
    // The flows are folded (closed by default) so that the panel under the
    // map stays short; the reader opens them on demand.
    const flows = flowsOf(n.id);
    if (flows.incoming.length || flows.outgoing.length) {
      const fold = el('details', { class: 'flows' }, [el('summary', {}, [el(h3, { text: 'Flows' })])]);
      if (flows.incoming.length) {
        fold.append(el(h4, { class: 'flow-heading', text: 'Comes from' }));
        fold.append(el('ul', { class: 'flow-list' }, flows.incoming.map((e) => flowItem(e, 'in', n.id))));
      }
      if (flows.outgoing.length) {
        fold.append(el(h4, { class: 'flow-heading', text: 'Goes to' }));
        fold.append(el('ul', { class: 'flow-list' }, flows.outgoing.map((e) => flowItem(e, 'out', n.id))));
      }
      box.append(fold);
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
      link(nodeHash(otherId), titleOf(otherId), 'xref flow-end'),
      el('span', { class: 'flow-where', text: whereText(otherId) })
    ]));
    if (insideId !== focusId) {
      li.append(el('div', { class: 'flow-inside' }, [
        el('span', { class: 'flow-key', text: direction === 'in' ? 'Arrives at: ' : 'Leaves from: ' }),
        link(nodeHash(insideId), titleOf(insideId), 'xref')
      ]));
    }
    flowExtras(li, e);
    return li;
  }

  // ------------------------------------------------------------------
  // Study 1: map, detail under it, panel
  // ------------------------------------------------------------------
  let m1 = null;
  let d1 = null;
  let focusAfter = null;   // {sel} to focus after a re-render (keyboard users)

  function openNode(id, o) {
    o = o || {};
    if (!idx.nodes.has(id)) return;
    const part = topOf(id);
    if (m1) m1.select(part, 'DETAIL BELOW');
    if (d1) d1.show(part, o.hot || (id === part ? null : id));
    renderPanel(id);
    if (focusAfter) {
      const target = document.querySelector(focusAfter);
      focusAfter = null;
      if (target) target.focus({ preventScroll: true });
    }
  }

  function buildStudy1() {
    const host = $('map');
    m1 = buildMap(host, {
      pick: true,
      label: 'Map of the parts of the system and the relations between them. Each part is a button that opens its detail below the map.',
      onPick: (part) => {
        openNode(part);
        setHash(nodeHash(part), 'browse');
      }
    });
    d1 = buildDetail($('detail-view'), {
      onNode: (id) => {
        focusAfter = '#detail-view [data-node="' + cssEsc(id) + '"]';
        openNode(id);
        setHash(nodeHash(id), 'browse');
      },
      onStub: (otherPart, otherNodes, fromPart) => {
        focusAfter = '#detail-view g.stub[data-other="' + cssEsc(fromPart) + '"]';
        openNode(otherPart, { hot: otherNodes });
        setHash(nodeHash(otherPart), 'browse');
        if (!document.querySelector(':focus')) { const h = document.querySelector('#detail-view .dhead h3'); if (h) h.focus({ preventScroll: true }); }
      }
    });
    // chips: emphasize one relation kind
    const chips = $('chips');
    const kinds = [{ id: 'all', name: 'All' }].concat((lay.map.kinds || []).filter((k) => k && k.id));
    kinds.forEach((k) => {
      const b = el('button', { type: 'button', class: 'chip', 'data-kind': k.id, 'aria-pressed': k.id === 'all' ? 'true' : 'false' });
      if (k.id !== 'all') {
        const s = S('svg', { viewBox: '0 0 28 8', 'aria-hidden': 'true' });
        S('line', { x1: 0, y1: 4, x2: 28, y2: 4, class: 'ln ' + k.id }, s);
        b.append(s);
      }
      b.append(k.name);
      b.addEventListener('click', () => {
        chips.querySelectorAll('.chip').forEach((c) => c.setAttribute('aria-pressed', c === b ? 'true' : 'false'));
        m1.setFocus(k.id);
      });
      chips.append(b);
    });
  }
  function cssEsc(s) { return window.CSS && CSS.escape ? CSS.escape(s) : String(s).replace(/["\\]/g, '\\$&'); }

  // ------------------------------------------------------------------
  // Study 2: the tour
  // ------------------------------------------------------------------
  let m2 = null;
  let d2 = null;
  let tourIndex = 0;

  function shortPanel(host, id) {
    let p = host.querySelector('.panel-short');
    if (!p) { p = el('div', { class: 'panel panel-short' }); host.append(p); }
    p.textContent = '';
    const t = el('span', { class: 'pt', text: titleOf(id) });
    if (isOut(id)) t.append(el('span', { class: 'otxt', text: 'outside this repo' }));
    p.append(t);
    p.append(inlineProse('span', (idx.nodes.get(id) || {}).summary, 'ps'));
    p.append(' ', link(nodeHash(id), 'Open in the map \u2191', 'ui'));
  }

  function buildTour() {
    m2 = buildMap($('tour-map'), { tour: true, label: 'The same map, used for the tour: dots show where the parts of one event are at the current step.' });
    d2 = buildDetail($('tour-detail'), {
      onNode: (id) => shortPanel($('tour-detail'), id),
      onStub: (otherPart, otherNodes) => {
        d2.show(otherPart, otherNodes);
        shortPanel($('tour-detail'), otherPart);
      }
    });
    const pips = $('pips');
    idx.steps.forEach((s, i) => {
      const b = el('button', { type: 'button', class: 'pip', text: String(i + 1), 'aria-label': 'Step ' + (i + 1) + ': ' + s.title });
      b.addEventListener('click', () => tourGo(i, true));
      pips.append(b);
    });
    $('tour-prev').addEventListener('click', () => tourGo(tourIndex - 1, true));
    $('tour-next').addEventListener('click', () => tourGo(tourIndex + 1, true));
  }

  function tourGo(i, fromClick) {
    if (!idx.steps.length) return;
    tourIndex = Math.max(0, Math.min(idx.steps.length - 1, i));
    const k = tourIndex + 1;
    const s = idx.steps[tourIndex];
    const T = idx.steps.length;
    $('pips').querySelectorAll('.pip').forEach((p, j) => { if (j === tourIndex) p.setAttribute('aria-current', 'step'); else p.removeAttribute('aria-current'); });
    $('tour-prev').disabled = tourIndex === 0;
    $('tour-next').disabled = tourIndex === T - 1;
    const card = $('stepcard');
    card.textContent = '';
    card.append(el('div', { class: 'eyebrow', text: 'Step ' + k + ' of ' + T + ' \u00b7 in ' + titleOf(topOf(s.node)) }));
    card.append(el('h3', { id: 'tour-step-title', dataset: { stepIndex: String(k) }, text: s.title }));
    card.append(prose(s.prose, { id: 'tour-step-prose' }));
    const refs = referenceList(s.code_refs, s.sources);
    if (refs) card.append(refs);
    if (model.tour && model.tour.intro) {
      const about = el('details', { class: 'tour-about' }, [el('summary', { text: 'About this tour' })]);
      about.append(prose(model.tour.intro, { class: 'prose tour-intro' }));
      card.append(about);
    }
    if (m2) {
      m2.setTour(lay.tourByStep.get(s.id) || null);
      m2.select(topOf(s.node), 'THIS STEP');
    }
    if (d2) {
      d2.show(topOf(s.node), s.node);
      shortPanel($('tour-detail'), s.node);
    }
    document.querySelectorAll('#sequence .row').forEach((r) => r.classList.toggle('cur', r.dataset.stepIndex === String(k)));
    if (fromClick) setHash('#/tour/' + k, 'tour');
  }

  // ------------------------------------------------------------------
  // Study 3: small multiples
  // ------------------------------------------------------------------
  function buildMultiples() {
    const host = $('mult');
    host.textContent = '';
    (Array.isArray(lay.map.multiples) ? lay.map.multiples : []).forEach((mm) => {
      const name = mm.kind === 'all' ? (mm.title || 'All') : kindName(mm.kind);
      const f = el('figure');
      const sheet = el('div', { class: 'sheet' });
      f.append(sheet);
      const label = mm.kind === 'all' ? 'Small copy of the map showing every kind of relation together.' : 'Small copy of the map showing only the ' + name + ' relation.';
      const api = buildMap(sheet, { mini: true, kind: mm.kind, label: label });
      api.setFocus(mm.kind);
      const cap = el('figcaption', {}, [el('b', { text: name + '.' }), ' ']);
      if (mm.caption) appendInline(cap, mm.caption);
      f.append(cap);
      host.append(f);
    });
  }

  // ------------------------------------------------------------------
  // Study 4: the tour as one sequence chart
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
      onActivate(g, () => {
        tourGo(k, true);
        $('tour').scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'start' });
      });
    });
  }

  // ------------------------------------------------------------------
  // Study 5: the N² matrix
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
  function setFull(sheet, on) {
    const svg = sheet.querySelector(':scope > svg');
    const w = svg && svg.viewBox && svg.viewBox.baseVal ? svg.viewBox.baseVal.width : 0;
    const full = !!(on && w);
    sheet.classList.toggle('full', full);
    if (svg) svg.style.width = full ? w + 'px' : '';
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
    document.querySelectorAll('.figbar').forEach((bar) => {
      const box = bar.nextElementSibling;
      if (box) scrollCue(box, bar.querySelector('.scroll-hint'), { noLeftFade: box.classList.contains('tbl') });
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
      li.append(el('span', { class: 'om-pair' }, [link(nodeHash(a), shortOf(a)), ' \u2192 ', link(nodeHash(b), shortOf(b))]), ': ', e.label, ' \u2014 ');
      if (typeof o.reason === 'string') appendInline(li, o.reason);
      ul.append(li);
    });
    host.append(ul);
  }

  // ------------------------------------------------------------------
  // Section heads (texts from map.sections)
  // ------------------------------------------------------------------
  function renderSectionHeads() {
    document.querySelectorAll('.sec-head[data-section]').forEach((h) => {
      const key = h.dataset.section;
      const s = section(key);
      const sec = h.closest('section');
      h.textContent = '';
      if (s.eyebrow) h.append(el('div', { class: 'eyebrow', text: s.eyebrow }));
      h.append(el('h2', { id: sec.id + '-title', text: s.title || '' }));
      if (s.intro) h.append(prose(s.intro));
    });
    document.querySelectorAll('.sec-caption[data-section]').forEach((c) => {
      const s = section(c.dataset.section);
      c.textContent = '';
      if (s.caption) appendInline(c, s.caption);
    });
  }

  // ------------------------------------------------------------------
  // The one-page view
  // ------------------------------------------------------------------
  function renderReadPage(st) {
    const page = $('read-page');
    page.textContent = '';
    xrefHash = readHash;
    try {
      page.append(el('p', { class: 'read-note', text: 'The whole design model as one page: the overview, then every part with its sub-parts in order, then the tour. Links to parts jump within this page; "Back to the map" returns to the map.' }));
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
          link(nodeHash(id), 'Show on the map', 'read-map-link')
        ]));
        appendNodeBody(sec, n, 'h' + Math.min(6, depth + 2), 'h' + Math.min(6, depth + 3), false, null);
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
          li.append(el('p', { class: 'read-path' }, ['Part: ', link(readHash(s.node), titleOf(s.node)), ' \u00b7 ', link('#/tour/' + (i + 1), 'Show this step on the map')]));
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
    const lede = $('model-lede');
    lede.textContent = '';
    if (model.question) lede.append(inlineProse('p', model.question, 'question'));
    if (model.summary) lede.append(prose(model.summary));
    lede.hidden = !lede.childNodes.length;
  }

  function toggleHelp(show) {
    const help = $('help');
    const open = show === undefined ? help.hidden : show;
    help.hidden = !open;
    $('help-toggle').setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open) $('help-title').focus({ preventScroll: false });
  }

  function bindEvents() {
    $('read-toggle').addEventListener('click', () => go(state && state.mode === 'read' ? '#/' : '#/read'));
    $('help-toggle').addEventListener('click', () => toggleHelp());
    $('help-close').addEventListener('click', () => { toggleHelp(false); $('help-toggle').focus(); });
    document.addEventListener('keydown', (ev) => {
      if (ev.altKey || ev.ctrlKey || ev.metaKey) return;
      const t = ev.target;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
      if (ev.key === 'Escape' && !$('help').hidden) { ev.preventDefault(); toggleHelp(false); $('help-toggle').focus(); return; }
      if (ev.key !== 'ArrowRight' && ev.key !== 'ArrowLeft') return;
      if (!state || state.mode === 'read') return;
      const inTour = t && t.closest && t.closest('#tour');
      if (document.body.dataset.mode !== 'tour' && !inTour) return;
      if (t && t.closest && t.closest('.box, .stub, .dgroup') && !inTour) return;
      ev.preventDefault();
      tourGo(tourIndex + (ev.key === 'ArrowRight' ? 1 : -1), true);
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
      renderSectionHeads();
      buildStudy1();
      buildTour();
      buildMultiples();
      buildSequence();
      buildMatrix();
      renderOmitted();
      bindFrames();
    } else {
      showMessage('The design model has no map layout ("map" block); only the one-page view is available.', true);
    }
    const initial = parseHash();
    if (initial.mode !== 'tour') tourGo(0, false);
    route(initial.mode !== 'browse' || initial.focus !== ROOT);
    document.body.dataset.ready = 'true';
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
