/*
 * Viewer for the DAQ design model (daq-model.json).
 *
 * The model is the only source of content: this file holds the user
 * interface only (layout, routing, rendering). Model text enters the page
 * only as DOM text nodes (never as HTML).
 *
 * State: one hash route.
 *   #/                 overview (the top-level nodes)
 *   #/node/<id>        focus on a node: the map shows its children (a leaf:
 *                      its siblings, with the leaf highlighted)
 *   #/tour/<k>         tour step k (1-based): the map shows the level of the
 *                      step's node, with the node highlighted
 *   #/read             the whole model as one page; #/read/<id> scrolls to a node
 *
 * Test hooks (documented in tools/README.md): .node-box[data-node-id] in
 * #map, #detail-title[data-node-id], #zoom-out, #breadcrumb [data-node-id]
 * (root crumb "__root__"), #tour-start, #tour-next, #tour-prev, #tour-exit,
 * #tour-step-title[data-step-index], #tour-step-prose, body[data-ready],
 * body[data-focus], body[data-mode], #map g.edge[data-edge-ids],
 * #map g.stub[data-node-id], #map g.edge-label[data-edge-ids],
 * #edge-flows[data-edge-ids], #help-toggle, #help, #read-toggle,
 * #read-page section[data-node-id].
 */
(function () {
  'use strict';

  const MODEL_URL = 'daq-model.json';
  const ROOT = '__root__';
  const SVG_NS = 'http://www.w3.org/2000/svg';

  const EDGE_KINDS = ['data', 'trigger', 'timing', 'control', 'monitoring'];
  const EDGE_KIND_NAMES = {
    data: 'Data', trigger: 'Trigger', timing: 'Timing', control: 'Control', monitoring: 'Monitoring'
  };
  // Only these kinds decide the left-to-right order of the boxes.
  const RANKING_KINDS = new Set(['data', 'trigger', 'timing']);
  const SOURCE_KIND_NAMES = {
    'site-page': 'This site',
    'confluence-public': 'Confluence',
    'confluence-internal': 'Confluence, internal space',
    'web': 'Web'
  };

  // Layout constants (pixels).
  const L = {
    boxMinW: 150, boxH0: 100, boxHFit: 136, boxHMax: 240,
    colGapMin: 96, colGapMax: 170, rowGap: 56,
    marginX: 16, marginRight: 40, marginTop: 36, marginBottom: 36,
    maxRows: 4, laneExtraMax: 70,
    labelLineH: 13, labelPadX: 5, labelPadY: 2, labelSlideMax: 80,
    laneTrack: 19, gutterTrack: 8, cornerRadius: 6,
    stubMinW: 100, stubMaxW: 230, stubH: 17, stubGap: 22
  };
  const FONT_FAMILY = 'system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';
  const LABEL_FONT = '11px ' + FONT_FAMILY;
  const TITLE_FONT = '600 14px ' + FONT_FAMILY;
  const SUMMARY_FONT = '12px ' + FONT_FAMILY;

  // ------------------------------------------------------------------
  // Model index
  // ------------------------------------------------------------------
  let model = null;
  const idx = {
    nodes: new Map(),     // id -> node
    children: new Map(),  // parent id (or ROOT) -> [child ids] in JSON order
    order: new Map(),     // id -> position in the JSON node list
    sources: new Map(),   // id -> source
    edges: [],
    edgeById: new Map(),
    steps: []
  };
  let current = null;            // the state being shown
  let tourReturnHash = '#/';     // where "Exit tour" goes
  let focusMapAfterRender = false;
  let selectedGroup = null;      // edge ids of the arrow whose flows are listed in the panel

  function buildIndex(m) {
    const list = (x) => (Array.isArray(x) ? x : []);
    list(m.nodes).forEach((n, i) => {
      if (n && typeof n.id === 'string' && !idx.nodes.has(n.id)) {
        idx.nodes.set(n.id, n);
        idx.order.set(n.id, i);
      }
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
    idx.steps = list(m.tour && m.tour.steps);
  }

  function childrenOf(id) { return idx.children.get(id) || []; }
  function parentOf(id) {
    const n = idx.nodes.get(id);
    return (n && typeof n.parent === 'string' && idx.nodes.has(n.parent)) ? n.parent : ROOT;
  }
  function titleOf(id) { return id === ROOT ? model.title : (idx.nodes.get(id) || {}).title || id; }
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
  // The ancestor-or-self of id that is in the set, or null.
  function liftTo(id, set) {
    let cur = id;
    const seen = new Set();
    while (cur !== ROOT && !seen.has(cur)) {
      if (set.has(cur)) return cur;
      seen.add(cur);
      cur = parentOf(cur);
    }
    return null;
  }

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
  function svg(tag, attrs) {
    const e = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
    return e;
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
    if (location.hash === hash || (hash === '#/' && (location.hash === '' || location.hash === '#'))) render();
    else location.hash = hash;
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
  // Prose markup reduced to plain text (for tooltips and measuring).
  function plainText(text) {
    if (typeof text !== 'string') return '';
    return text
      .replace(/\[\[([^\]|]+)\|([^\]]+)\]\]/g, '$2')
      .replace(/\[\[([^\]|]+)\]\]/g, (all, id) => (idx.nodes.has(id.trim()) ? titleOf(id.trim()) : all))
      .replace(/\[([^\]]+)\]\(([^()\s]+)\)/g, '$1')
      .replace(/`([^`]+)`/g, '$1')
      .replace(/\s+/g, ' ')
      .trim();
  }

  // ------------------------------------------------------------------
  // Routing
  // ------------------------------------------------------------------
  function parseHash() {
    let h = location.hash.replace(/^#/, '');
    try { h = decodeURIComponent(h); } catch (e) { /* keep the raw text */ }
    if (h === '' || h === '/') return { mode: 'browse', focus: ROOT };
    let m = /^\/node\/(.+)$/.exec(h);
    if (m) {
      if (idx.nodes.has(m[1])) return { mode: 'browse', focus: m[1] };
      return { mode: 'browse', focus: ROOT, message: 'There is no part with the id "' + m[1] + '" in the design model. Showing the overview.' };
    }
    m = /^\/tour(?:\/(\d+))?\/?$/.exec(h);
    if (m) {
      const k = m[1] === undefined ? 1 : parseInt(m[1], 10);
      const step = idx.steps[k - 1];
      if (k >= 1 && step && idx.nodes.has(step.node)) return { mode: 'tour', step: k, focus: step.node };
      return { mode: 'browse', focus: ROOT, message: 'The tour has no step ' + m[1] + '. Showing the overview.' };
    }
    m = /^\/read(?:\/(.+?))?\/?$/.exec(h);
    if (m) {
      const target = m[1] && idx.nodes.has(m[1]) ? m[1] : null;
      return { mode: 'read', focus: ROOT, target: target };
    }
    return { mode: 'browse', focus: ROOT, message: 'Unknown link "#' + h + '". Showing the overview.' };
  }

  // Which boxes the map shows for a state.
  function viewOf(state) {
    if (state.mode === 'tour') {
      const p = parentOf(state.focus);
      return { parent: p, ids: childrenOf(p), highlight: state.focus };
    }
    if (state.focus === ROOT) return { parent: ROOT, ids: childrenOf(ROOT), highlight: null };
    const kids = childrenOf(state.focus);
    if (kids.length) return { parent: state.focus, ids: kids, highlight: null };
    const p = parentOf(state.focus);
    return { parent: p, ids: childrenOf(p), highlight: state.focus };
  }

  function zoomOut() {
    if (!current || current.mode === 'read') return;
    if (current.focus === ROOT) return;
    go(nodeHash(parentOf(current.focus)));
  }
  function startTour() {
    if (!idx.steps.length) return;
    if (!current || current.mode !== 'tour') tourReturnHash = location.hash && location.hash !== '#' ? location.hash : '#/';
    go('#/tour/1');
  }
  function exitTour() {
    const back = /^#\/(tour|read)/.test(tourReturnHash) ? '#/' : tourReturnHash;
    go(back);
  }
  function tourStep(delta) {
    if (!current || current.mode !== 'tour') return;
    const k = current.step + delta;
    if (k >= 1 && k <= idx.steps.length) go('#/tour/' + k);
  }

  // ------------------------------------------------------------------
  // Rendering
  // ------------------------------------------------------------------
  function render() {
    if (!model) return;
    const state = parseHash();
    if (!current || current.mode !== state.mode || current.focus !== state.focus || current.step !== state.step) selectedGroup = null;
    current = state;
    showMessage(state.message || '');
    const reading = state.mode === 'read';
    $('read-page').hidden = !reading;
    document.querySelector('main.layout').hidden = reading;
    $('read-toggle').textContent = reading ? 'Back to the map' : 'Read as one page';
    $('read-toggle').setAttribute('aria-pressed', reading ? 'true' : 'false');
    if (reading) {
      renderReadPage(state);
    } else {
      renderBreadcrumb(state);
      renderMap(state);
      renderDetail(state);
      $('zoom-out').disabled = state.focus === ROOT;
    }
    $('tour-start').setAttribute('aria-pressed', state.mode === 'tour' ? 'true' : 'false');
    document.body.dataset.mode = state.mode;
    document.body.dataset.focus = state.focus;
    document.body.dataset.ready = 'true';
  }

  function showMessage(text, isError) {
    const box = $('message');
    box.textContent = text;
    box.hidden = !text;
    box.classList.toggle('error', !!isError);
  }

  function renderBreadcrumb(state) {
    const nav = $('breadcrumb');
    nav.textContent = '';
    const path = state.focus === ROOT ? [] : pathTo(state.focus);
    const crumbs = [ROOT].concat(path);
    crumbs.forEach((id, i) => {
      if (i > 0) nav.append(el('span', { class: 'crumb-sep', 'aria-hidden': 'true', text: '›' }));
      const isLast = i === crumbs.length - 1;
      nav.append(el('button', {
        type: 'button', class: 'crumb', dataset: { nodeId: id },
        'aria-current': isLast ? 'location' : null,
        text: id === ROOT ? 'Overview' : titleOf(id)
      }));
    });
  }

  // ---- the map -------------------------------------------------------
  function renderMap(state) {
    const map = $('map');
    const view = viewOf(state);
    const highlightEdges = new Set(state.mode === 'tour' ? (idx.steps[state.step - 1].edges || []) : []);
    const selected = new Set(selectedGroup || []);
    const groups = visibleEdgeGroups(view.ids);
    const stubs = stubGroups(view.ids);
    const availW = Math.max(300, map.clientWidth - 4);
    const availH = Math.max(240, map.clientHeight - 4);
    const layout = layoutBoxes(view.ids, groups, stubs, availW, availH);
    const routes = routeEdges(layout);

    const canvas = el('div', { class: 'map-canvas' });
    canvas.style.width = layout.width + 'px';
    canvas.style.height = layout.height + 'px';

    const lines = svg('svg', { class: 'edges', width: layout.width, height: layout.height, 'aria-hidden': 'true' });
    lines.append(arrowDefs());
    const labels = svg('svg', { class: 'edge-labels', width: layout.width, height: layout.height });
    const placed = [];
    const boxRects = Array.from(layout.pos.values()).map((p) => ({ x: p.x - 2, y: p.y - 2, w: p.w + 4, h: p.h + 4 }));
    const bounds = { x: 0, y: 0, w: layout.width, h: layout.height };

    // Stub chips first: they sit at fixed places on the canvas edge.
    for (const r of routes.filter((x) => x.stub)) placed.push(r.chip);

    for (const r of routes) {
      const ids = r.group.items.map((e) => e.id);
      const lit = ids.some((id) => highlightEdges.has(id));
      const isSel = ids.some((id) => selected.has(id));
      const flags = ' kind-' + r.group.kind + (lit ? ' is-highlighted' : '') +
        (isSel ? ' is-selected' : '') + (highlightEdges.size && !lit ? ' is-dim' : '');
      const g = svg('g', { class: 'edge' + (r.stub ? ' stub' : '') + flags, 'data-edge-ids': ids.join(' ') });
      if (r.stub) g.setAttribute('data-node-id', r.group.outside);
      g.append(svg('path', { class: 'edge-line', d: r.d, 'marker-end': 'url(#arrow-' + r.group.kind + ')' }));
      lines.append(g);
      if (r.stub) {
        labels.append(stubChip(r, 'stub-chip' + flags, ids));
      } else {
        const lg = placeLabel(r, boxRects, placed, ids, bounds);
        lg.setAttribute('class', 'edge-label' + flags);
        labels.append(lg);
      }
    }
    canvas.append(lines);

    for (const id of view.ids) {
      const p = layout.pos.get(id);
      canvas.append(nodeBox(id, p, id === view.highlight));
    }
    canvas.append(labels);

    map.textContent = '';
    map.append(canvas);
    map.scrollTop = 0;
    map.scrollLeft = 0;
    const lit = view.highlight ? canvas.querySelector('.node-box.is-highlighted') : null;
    if (lit) lit.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    if (focusMapAfterRender) {
      focusMapAfterRender = false;
      const target = lit || canvas.querySelector('.node-box');
      if (target) target.focus({ preventScroll: true });
    }
  }

  function flowText(e) {
    return (EDGE_KIND_NAMES[e.kind] || e.kind) + ': ' + titleOf(e.from) + ' → ' + titleOf(e.to) + ' (' + e.label + ')';
  }

  function nodeBox(id, p, highlighted) {
    const n = idx.nodes.get(id);
    const kids = childrenOf(id).length;
    const meta = el('span', { class: 'node-meta' }, [
      n.outside_repo === true ? el('span', { class: 'badge badge-outside', text: 'Outside this repo' }) : null,
      el('span', { class: 'node-count', text: kids ? kids + (kids === 1 ? ' part' : ' parts') : 'Details' })
    ]);
    const tip = n.title + (typeof n.summary === 'string' ? '\n\n' + plainText(n.summary) : '') +
      (kids ? '\n\nClick to zoom in.' : '\n\nClick to show the details.');
    const box = el('button', {
      type: 'button',
      class: 'node-box' + (kids ? ' has-children' : ' is-leaf') + (n.outside_repo === true ? ' is-outside' : '') + (highlighted ? ' is-highlighted' : ''),
      dataset: { nodeId: id },
      title: tip,
      'aria-current': highlighted ? 'true' : null
    }, [
      el('span', { class: 'node-title', text: n.title }),
      inlineProse('span', n.summary, 'node-summary'),
      meta
    ]);
    const lines = String(summaryLinesFor(id, p.w, p.h));
    box.querySelector('.node-summary').style.webkitLineClamp = lines;
    box.querySelector('.node-summary').style.lineClamp = lines;
    box.style.left = p.x + 'px';
    box.style.top = p.y + 'px';
    box.style.width = p.w + 'px';
    box.style.height = p.h + 'px';
    return box;
  }

  function arrowDefs() {
    const defs = svg('defs');
    for (const kind of EDGE_KINDS) {
      const marker = svg('marker', {
        id: 'arrow-' + kind, viewBox: '0 0 10 10', refX: '9', refY: '5',
        markerWidth: '7', markerHeight: '7', orient: 'auto-start-reverse', markerUnits: 'userSpaceOnUse'
      });
      marker.append(svg('path', { d: 'M0,0 L10,5 L0,10 z', class: 'arrow kind-' + kind }));
      defs.append(marker);
    }
    return defs;
  }

  // Edges between the boxes in view, lifted to the visible ancestors and
  // grouped by (from, to, kind). Edges whose lifted ends coincide are not
  // drawn; edges with exactly one end in view become stubs (stubGroups).
  function visibleEdgeGroups(ids) {
    const set = new Set(ids);
    const groups = new Map();
    for (const e of idx.edges) {
      const a = liftTo(e.from, set);
      const b = liftTo(e.to, set);
      if (!a || !b || a === b) continue;
      const key = a + '|' + b + '|' + e.kind;
      if (!groups.has(key)) groups.set(key, { key: key, from: a, to: b, kind: e.kind, items: [] });
      groups.get(key).items.push(e);
    }
    return Array.from(groups.values());
  }

  // Edges with one end inside the view and the other end outside it (and not
  // an ancestor of the view): drawn as stub arrows to the canvas edge, named
  // after the node at the outside end.
  function stubGroups(ids) {
    const set = new Set(ids);
    const groups = new Map();
    for (const e of idx.edges) {
      const a = liftTo(e.from, set);
      const b = liftTo(e.to, set);
      if ((a && b) || (!a && !b)) continue;
      const dir = a ? 'out' : 'in';
      const inside = a || b;
      const outside = a ? e.to : e.from;
      const key = dir + '|' + inside + '|' + outside + '|' + e.kind;
      if (!groups.has(key)) groups.set(key, { key: key, dir: dir, inside: inside, outside: outside, kind: e.kind, items: [], stub: true });
      groups.get(key).items.push(e);
    }
    return Array.from(groups.values());
  }

  // ---- text measuring ------------------------------------------------
  let measureCtx = null;
  function textWidth(text, font) {
    if (!measureCtx) measureCtx = document.createElement('canvas').getContext('2d');
    measureCtx.font = font || LABEL_FONT;
    return measureCtx.measureText(text).width;
  }
  function wrapText(text, maxW, font) {
    const words = text.split(/\s+/).filter(Boolean);
    const lines = [];
    let line = '';
    for (const w of words) {
      const next = line ? line + ' ' + w : w;
      if (line && textWidth(next, font) > maxW) { lines.push(line); line = w; } else line = next;
    }
    if (line) lines.push(line);
    return lines;
  }
  function fitText(text, maxW, font) {
    if (textWidth(text, font) <= maxW) return text;
    let s = text;
    while (s.length > 1 && textWidth(s + '…', font) > maxW) s = s.slice(0, -1);
    return s.replace(/\s+$/, '') + '…';
  }
  // Box text metrics (pixels): padding and border, title and summary line
  // heights, and the meta row; they match viewer.css.
  const BOX_FIXED = 44;
  const TITLE_LINE = 17.5;
  const SUMMARY_LINE = 15.6;
  function titleLines(id, w) { return Math.min(3, wrapText(idx.nodes.get(id).title || '', w - 24, TITLE_FONT).length); }
  // Height a box needs to show its title and summary in full at width w.
  function boxHeightFor(id, w) {
    const s = Math.min(8, wrapText(plainText(idx.nodes.get(id).summary), w - 24, SUMMARY_FONT).length);
    return Math.ceil(BOX_FIXED + titleLines(id, w) * TITLE_LINE + s * SUMMARY_LINE);
  }
  // Summary lines that fit in a box of size w x h.
  function summaryLinesFor(id, w, h) {
    return Math.max(1, Math.floor((h - BOX_FIXED - titleLines(id, w) * TITLE_LINE) / SUMMARY_LINE));
  }

  // ---- layout --------------------------------------------------------
  // Layered left to right by longest path over the data/trigger/timing
  // edges (back edges of cycles ignored), JSON order as tie-break. A layer
  // with more than maxRows boxes wraps into several columns; when the
  // columns do not fit the width, they wrap into bands below each other,
  // every second band running right to left (so that the flow continues
  // under the last column). Boxes without any data/trigger/timing edge have
  // no rank: they fill the free cells of the bands, then rows below, in JSON
  // order. With no ranking edges at all: a grid in JSON order. Box sizes
  // and gaps grow to use the available area; stubs get a margin on the
  // side of the canvas they point to.
  function layoutBoxes(ids, groups, stubs, availW, availH) {
    const order = new Map(ids.map((id, i) => [id, i]));
    const out = new Map(ids.map((id) => [id, []]));
    const ranked = new Set();
    for (const g of groups) {
      if (!RANKING_KINDS.has(g.kind)) continue;
      ranked.add(g.from);
      ranked.add(g.to);
      const list = out.get(g.from);
      if (!list.includes(g.to)) list.push(g.to);
    }
    for (const list of out.values()) list.sort((a, b) => order.get(a) - order.get(b));

    const hasIn = stubs.some((s) => s.dir === 'in');
    const hasOut = stubs.some((s) => s.dir === 'out');
    // On a narrow screen (a phone) the stub tags and margins shrink so that
    // one column of boxes still fits without scrolling sideways.
    const narrow = availW < 560;
    const stubW = narrow ? 72 : Math.round(Math.max(L.stubMinW, Math.min(L.stubMaxW, availW * 0.2)));
    const stubGap = narrow ? 12 : L.stubGap;
    const baseRight = narrow ? 24 : L.marginRight;
    const marginLeft = L.marginX + (hasIn ? stubW + stubGap : 0);
    const marginRight = baseRight + (hasOut ? stubW + stubGap : 0);
    const usableW = Math.max(L.boxMinW, availW - marginLeft - marginRight);
    const fit = Math.max(1, Math.floor((usableW + L.colGapMin) / (L.boxMinW + L.colGapMin)));

    const cell = new Map();
    let nCols;
    let nRows;
    if (ranked.size === 0) {
      // Grid in JSON order (reading order).
      nCols = Math.max(1, Math.min(fit, ids.length <= 3 ? ids.length : Math.ceil(Math.sqrt(ids.length))));
      nRows = Math.ceil(ids.length / nCols);
      ids.forEach((id, i) => cell.set(id, { col: i % nCols, row: Math.floor(i / nCols) }));
    } else {
      // Drop back edges with a depth-first search in JSON order.
      const mark = new Map();
      const forward = new Map(ids.map((id) => [id, []]));
      const dfs = (u) => {
        mark.set(u, 1);
        for (const v of out.get(u)) {
          if (mark.get(v) === 1) continue;  // back edge
          forward.get(u).push(v);
          if (!mark.get(v)) dfs(v);
        }
        mark.set(u, 2);
      };
      ids.forEach((id) => { if (!mark.get(id)) dfs(id); });

      // Longest path layering (Kahn's algorithm, JSON order).
      const layer = new Map(ids.map((id) => [id, 0]));
      const indeg = new Map(ids.map((id) => [id, 0]));
      for (const list of forward.values()) for (const v of list) indeg.set(v, indeg.get(v) + 1);
      const queue = ids.filter((id) => indeg.get(id) === 0);
      while (queue.length) {
        const u = queue.shift();
        for (const v of forward.get(u)) {
          layer.set(v, Math.max(layer.get(v), layer.get(u) + 1));
          indeg.set(v, indeg.get(v) - 1);
          if (indeg.get(v) === 0) queue.push(v);
        }
      }
      const rankedIds = ids.filter((id) => ranked.has(id));
      const nLayers = Math.max(...rankedIds.map((id) => layer.get(id))) + 1;
      const layers = Array.from({ length: nLayers }, () => []);
      rankedIds.forEach((id) => layers[layer.get(id)].push(id));
      const columns = [];
      for (const members of layers) {
        const nSub = Math.ceil(members.length / L.maxRows);
        const rows = Math.ceil(members.length / nSub);
        for (let k = 0; k < nSub; k++) columns.push(members.slice(k * rows, (k + 1) * rows));
      }

      const perBand = Math.max(1, Math.min(columns.length, fit));
      let rowStart = 0;
      for (let b = 0; b * perBand < columns.length; b++) {
        const band = columns.slice(b * perBand, (b + 1) * perBand);
        const bandRows = Math.max(...band.map((c) => c.length));
        band.forEach((members, c) => {
          const col = b % 2 === 1 ? perBand - 1 - c : c;
          const offset = Math.floor((bandRows - members.length) / 2);
          members.forEach((id, r) => cell.set(id, { col: col, row: rowStart + offset + r }));
        });
        rowStart += bandRows;
      }
      const unranked = ids.filter((id) => !ranked.has(id));
      const taken = new Set(Array.from(cell.values()).map((c) => c.col + ',' + c.row));
      const free = [];
      for (let r = 0; r < rowStart; r++) {
        for (let c = 0; c < perBand; c++) if (!taken.has(c + ',' + r)) free.push({ col: c, row: r });
      }
      const inFree = unranked.slice(0, free.length);
      const extra = unranked.slice(free.length);
      inFree.forEach((id, i) => cell.set(id, free[i]));
      nCols = Math.max(perBand, Math.min(extra.length, fit));
      extra.forEach((id, i) => cell.set(id, { col: i % nCols, row: rowStart + Math.floor(i / nCols) }));
      nRows = rowStart + Math.ceil(extra.length / nCols);
    }

    // Box width and column gap: use the width that is there.
    const maxW = nCols <= 2 ? 320 : (nCols === 3 ? 270 : 230);
    let w = Math.floor((usableW - (nCols - 1) * L.colGapMin) / nCols);
    w = Math.max(L.boxMinW, Math.min(maxW, w));
    let gap = nCols > 1 ? Math.floor((usableW - nCols * w) / (nCols - 1)) : L.colGapMin;
    gap = Math.max(L.colGapMin, Math.min(L.colGapMax, gap));

    // Decide every route on the grid first; busy lanes get taller.
    const routes = classifyRoutes(groups, stubs, cell, nRows);
    const laneCount = new Array(nRows + 1).fill(0);
    for (const r of routes) if (r.lane !== undefined) laneCount[r.lane]++;
    const laneH = laneCount.map((n, l) => {
      const base = l === 0 ? L.marginTop : (l === nRows ? L.marginBottom : L.rowGap);
      return Math.max(base, 16 + n * L.laneTrack);
    });
    // Box height: enough for the longest text, but not more than fits the
    // pane (never below boxHFit); a box that is still too small shows the
    // full text on hover.
    const need = Math.max(...ids.map((id) => boxHeightFor(id, w)));
    const fitH = Math.floor((availH - laneH.reduce((a, b) => a + b, 0)) / nRows);
    const h = Math.max(L.boxH0, Math.min(L.boxHMax, need, Math.max(L.boxHFit, fitH)));
    // Spread spare height over the lanes (centred, not stretched to the edge).
    const used = laneH.reduce((a, b) => a + b, 0) + nRows * h;
    if (used < availH) {
      const extraH = Math.min(L.laneExtraMax, Math.floor((availH - used) / (nRows + 1)));
      for (let l = 1; l < nRows; l++) laneH[l] += extraH;
    }

    const colX = (c) => marginLeft + c * (w + gap);
    const rowTop = [];
    let y = laneH[0];
    for (let r = 0; r < nRows; r++) { rowTop.push(y); y += h + laneH[r + 1]; }
    const pos = new Map();
    for (const [id, c] of cell) {
      pos.set(id, { id: id, col: c.col, row: c.row, x: colX(c.col), y: rowTop[c.row], w: w, h: h });
    }
    const width = colX(nCols - 1) + w + marginRight;
    return {
      pos: pos, routes: routes, nCols: nCols, nRows: nRows, w: w, h: h, gap: gap,
      width: width, height: y, stubW: stubW,
      // x of the vertical gutter left of column c (c = 0..nCols)
      gutterX: (c) => (c <= 0 ? marginLeft - Math.min(gap, marginLeft) / 2 : (c >= nCols ? colX(nCols - 1) + w + baseRight / 2 : colX(c) - gap / 2)),
      // y of the middle of the horizontal lane above row r (r = 0..nRows)
      laneY: (r) => (r <= 0 ? laneH[0] / 2 : (r >= nRows ? rowTop[nRows - 1] + h + laneH[nRows] / 2 : rowTop[r] - laneH[r] / 2))
    };
  }

  // ---- edge routing --------------------------------------------------
  // Every segment runs in a gutter between columns or a lane between rows,
  // or is a short stub from a box side into the next gutter/lane, so no
  // edge is drawn through a box.
  //   curve:    neighbouring columns, at most one row apart; a curve
  //             inside the gutter
  //   vertical: same column, neighbouring rows; through the lane between
  //   lane:     same row, further apart; up (or down) into the lane, across
  //   gutter:   otherwise; out of the side into the gutter, along it to the
  //             lane next to the target box, across, into the box
  //   stub in:  from a chip at the left edge along the lane above the box
  //   stub out: from the bottom of the box along the lane below to a chip
  //             at the right edge
  function classifyRoutes(groups, stubs, cell, nRows) {
    const routes = groups.map((g, i) => {
      const A = cell.get(g.from);
      const B = cell.get(g.to);
      const dc = B.col - A.col;
      const dr = B.row - A.row;
      const r = { group: g, index: i };
      if ((dc === 1 || dc === -1) && Math.abs(dr) <= 1) {
        r.type = 'curve'; r.fromSide = dc > 0 ? 'R' : 'L'; r.toSide = dc > 0 ? 'L' : 'R';
      } else if (dc === 0 && Math.abs(dr) === 1) {
        r.type = 'vertical'; r.fromSide = dr > 0 ? 'B' : 'T'; r.toSide = dr > 0 ? 'T' : 'B';
      } else if (dr === 0) {
        r.type = 'lane';
        if (dc > 0) { r.fromSide = 'T'; r.toSide = 'T'; r.lane = A.row; } else { r.fromSide = 'B'; r.toSide = 'B'; r.lane = A.row + 1; }
      } else {
        r.type = 'gutter';
        r.fromSide = dc < 0 ? 'L' : 'R';
        r.gutter = dc < 0 ? A.col : A.col + 1;
        if (dr > 0) { r.toSide = 'T'; r.lane = B.row; } else { r.toSide = 'B'; r.lane = B.row + 1; }
      }
      return r;
    });
    stubs.forEach((g, i) => {
      const C = cell.get(g.inside);
      const r = { group: g, index: groups.length + i, stub: true, type: 'stub-' + g.dir };
      if (g.dir === 'in') { r.toSide = 'T'; r.lane = C.row; } else { r.fromSide = 'B'; r.lane = Math.min(nRows, C.row + 1); }
      routes.push(r);
    });
    return routes;
  }

  function routeEdges(layout) {
    const routes = layout.routes;
    const sides = new Map();   // "id:side" -> [{route, end}]
    const lanes = new Map();   // lane index -> [route]
    const gutters = new Map(); // gutter index -> [route]
    const use = (map, key, r) => { if (!map.has(key)) map.set(key, []); map.get(key).push(r); };
    for (const r of routes) {
      if (r.stub) {
        const box = layout.pos.get(r.group.inside);
        const edgeX = r.group.dir === 'in' ? -1e6 : 1e6;
        const virtual = { x: edgeX, y: box.y, w: 0, h: 0 };
        if (r.group.dir === 'in') { r.A = virtual; r.B = box; use(sides, r.group.inside + ':' + r.toSide, { route: r, end: 'to' }); }
        else { r.A = box; r.B = virtual; use(sides, r.group.inside + ':' + r.fromSide, { route: r, end: 'from' }); }
        use(lanes, r.lane, r);
        continue;
      }
      r.A = layout.pos.get(r.group.from);
      r.B = layout.pos.get(r.group.to);
      if (r.lane !== undefined) use(lanes, r.lane, r);
      if (r.gutter !== undefined) use(gutters, r.gutter, r);
      use(sides, r.group.from + ':' + r.fromSide, { route: r, end: 'from' });
      use(sides, r.group.to + ':' + r.toSide, { route: r, end: 'to' });
    }

    // Tracks: the routes that share a lane or gutter run side by side.
    for (const list of lanes.values()) {
      list.forEach((r, k) => { r.ly = layout.laneY(r.lane) + (k - (list.length - 1) / 2) * L.laneTrack; });
    }
    for (const list of gutters.values()) {
      const spacing = Math.min(L.gutterTrack, (layout.gap - 24) / list.length);
      list.forEach((r, k) => { r.gx = layout.gutterX(r.gutter) + (k - (list.length - 1) / 2) * spacing; });
    }

    // Anchors: spread the edge ends on each box side, ordered by where the
    // other end goes, so that the lines do not cross near the box.
    for (const [key, list] of sides) {
      const side = key.slice(key.lastIndexOf(':') + 1);
      const horizontalSide = side === 'T' || side === 'B';
      const far = (item) => {
        const r = item.route;
        const other = item.end === 'from' ? r.B : r.A;
        if (horizontalSide) {
          if (r.type === 'gutter' && item.end === 'to') return r.gx;
          return other.x + other.w / 2;
        }
        if (r.type === 'gutter' && item.end === 'from') return r.ly;
        return other.y + other.h / 2;
      };
      list.sort((a, b) => (far(a) - far(b)) || (a.route.index - b.route.index));
      list.forEach((item, k) => {
        const box = item.end === 'from' ? item.route.A : item.route.B;
        const t = (k + 1) / (list.length + 1);
        let pt;
        if (side === 'L') pt = { x: box.x, y: box.y + box.h * (0.2 + 0.6 * t) };
        else if (side === 'R') pt = { x: box.x + box.w, y: box.y + box.h * (0.2 + 0.6 * t) };
        else if (side === 'T') pt = { x: box.x + box.w * (0.12 + 0.76 * t), y: box.y };
        else pt = { x: box.x + box.w * (0.12 + 0.76 * t), y: box.y + box.h };
        item.route[item.end === 'from' ? 'S' : 'E'] = pt;
      });
    }

    for (const r of routes) {
      if (r.stub) buildStub(r, layout);
      else buildPath(r);
    }
    return routes;
  }

  function buildPath(r) {
    const S = r.S;
    const E = r.E;
    if (r.type === 'curve') {
      const dx = (E.x - S.x) / 2;
      const c1 = { x: S.x + dx, y: S.y };
      const c2 = { x: E.x - dx, y: E.y };
      r.d = 'M' + S.x + ',' + S.y + ' C' + c1.x + ',' + c1.y + ' ' + c2.x + ',' + c2.y + ' ' + E.x + ',' + E.y;
      r.pts = [];
      for (let i = 0; i <= 16; i++) {
        const t = i / 16;
        const u = 1 - t;
        r.pts.push({
          x: u * u * u * S.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t * t * t * E.x,
          y: u * u * u * S.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t * t * t * E.y
        });
      }
    } else if (r.type === 'vertical') {
      const dy = (E.y - S.y) / 2;
      r.d = 'M' + S.x + ',' + S.y + ' C' + S.x + ',' + (S.y + dy) + ' ' + E.x + ',' + (E.y - dy) + ' ' + E.x + ',' + E.y;
      r.pts = [S, { x: S.x, y: S.y + dy }, { x: E.x, y: E.y - dy }, E];
    } else if (r.type === 'lane') {
      r.pts = [S, { x: S.x, y: r.ly }, { x: E.x, y: r.ly }, E];
      r.d = roundedPath(r.pts);
    } else {
      r.pts = [S, { x: r.gx, y: S.y }, { x: r.gx, y: r.ly }, { x: E.x, y: r.ly }, E];
      r.d = roundedPath(r.pts);
    }
  }

  // A stub: a chip at the canvas edge, joined to the box through the lane.
  function buildStub(r, layout) {
    const g = r.group;
    const title = titleOf(g.outside);
    const prefix = g.dir === 'in' ? 'from ' : 'to ';
    const text = fitText(prefix + title, layout.stubW - 2 * L.labelPadX - 2, LABEL_FONT);
    const w = Math.ceil(textWidth(text, LABEL_FONT)) + 2 * L.labelPadX + 2;
    const h = L.stubH;
    if (g.dir === 'in') {
      const x = L.marginX / 2;
      r.chip = { x: x, y: r.ly - h / 2, w: w, h: h, text: text };
      r.pts = [{ x: x + w, y: r.ly }, { x: r.E.x, y: r.ly }, r.E];
    } else {
      const x = layout.width - L.marginX / 2 - w;
      r.chip = { x: x, y: r.ly - h / 2, w: w, h: h, text: text };
      r.pts = [r.S, { x: r.S.x, y: r.ly }, { x: x - 1, y: r.ly }];
    }
    r.d = roundedPath(r.pts);
  }

  function stubChip(r, cls, ids) {
    const g = r.group;
    const c = r.chip;
    const tip = g.items.map(flowText).join('\n') + '\nClick to go to ' + titleOf(g.outside) + '.';
    const chip = svg('g', {
      class: cls, 'data-edge-ids': ids.join(' '), 'data-node-id': g.outside,
      tabindex: '0', role: 'link', 'aria-label': (g.dir === 'in' ? 'Arrow from ' : 'Arrow to ') + titleOf(g.outside) + ', outside this level'
    });
    const t = svg('title');
    t.textContent = tip;
    chip.append(t);
    chip.append(svg('rect', { class: 'stub-bg', x: c.x, y: c.y, width: c.w, height: c.h, rx: 9 }));
    const text = svg('text', { class: 'stub-text', x: c.x + c.w / 2, y: c.y + c.h / 2 + 4 });
    text.textContent = c.text;
    chip.append(text);
    return chip;
  }

  // Polyline with rounded corners.
  function roundedPath(pts) {
    const clean = pts.filter((p, i) => i === 0 || p.x !== pts[i - 1].x || p.y !== pts[i - 1].y);
    let d = 'M' + clean[0].x + ',' + clean[0].y;
    for (let i = 1; i < clean.length - 1; i++) {
      const p0 = clean[i - 1];
      const p = clean[i];
      const p1 = clean[i + 1];
      const r = Math.min(L.cornerRadius, dist(p0, p) / 2, dist(p, p1) / 2);
      const a = toward(p, p0, r);
      const b = toward(p, p1, r);
      d += ' L' + a.x + ',' + a.y + ' Q' + p.x + ',' + p.y + ' ' + b.x + ',' + b.y;
    }
    const last = clean[clean.length - 1];
    return d + ' L' + last.x + ',' + last.y;
  }
  function dist(a, b) { return Math.hypot(a.x - b.x, a.y - b.y); }
  function toward(p, q, r) {
    const d = dist(p, q) || 1;
    return { x: p.x + (q.x - p.x) * r / d, y: p.y + (q.y - p.y) * r / d };
  }
  // The point at fraction t of the length of a polyline.
  function pointAlong(pts, t) {
    let total = 0;
    for (let i = 1; i < pts.length; i++) total += dist(pts[i - 1], pts[i]);
    let want = total * t;
    for (let i = 1; i < pts.length; i++) {
      const d = dist(pts[i - 1], pts[i]);
      if (want <= d || i === pts.length - 1) {
        const f = d ? Math.min(1, want / d) : 0;
        return { x: pts[i - 1].x + (pts[i].x - pts[i - 1].x) * f, y: pts[i - 1].y + (pts[i].y - pts[i - 1].y) * f };
      }
      want -= d;
    }
    return pts[0];
  }

  // ---- edge labels ---------------------------------------------------
  function overlaps(a, b) {
    return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
  }
  // The label sits on its own arrow: centred on a point of the path, tried
  // from the middle outwards until it covers no box and no other label.
  function placeLabel(r, boxRects, placed, ids, bounds) {
    const items = r.group.items;
    const text = items[0].label + (items.length > 1 ? ' (+' + (items.length - 1) + ' more)' : '');
    // Two shapes of the text: wide (few lines) and narrow (more lines).
    const shapes = [190, 70].map((maxW) => {
      const lines = wrapText(text, maxW, LABEL_FONT);
      return {
        lines: lines,
        w: Math.ceil(Math.max(...lines.map((s) => textWidth(s, LABEL_FONT)))) + 2 * L.labelPadX,
        h: lines.length * L.labelLineH + 2 * L.labelPadY
      };
    });
    const ts = [0.5, 0.42, 0.58, 0.34, 0.66, 0.26, 0.74, 0.18, 0.82];
    // At each point along the arrow (middle first), the narrow shape comes
    // first where the arrow runs up or down, the wide one where it runs across.
    const candidates = [];
    for (const t of ts) {
      const p = pointAlong(r.pts, t);
      const q = pointAlong(r.pts, Math.min(1, t + 0.02));
      const o = pointAlong(r.pts, Math.max(0, t - 0.02));
      const upright = Math.abs(q.y - o.y) > Math.abs(q.x - o.x);
      for (const sh of (upright ? [shapes[1], shapes[0]] : shapes)) {
        candidates.push({ x: p.x - sh.w / 2, y: p.y - sh.h / 2, w: sh.w, h: sh.h, shape: sh });
      }
    }
    // Last resort before overlapping: right beside the arrow.
    for (const t of ts) {
      const p = pointAlong(r.pts, t);
      const sh = shapes[1];
      candidates.push({ x: p.x + 3, y: p.y - sh.h / 2, w: sh.w, h: sh.h, shape: sh });
      candidates.push({ x: p.x - 3 - sh.w, y: p.y - sh.h / 2, w: sh.w, h: sh.h, shape: sh });
      candidates.push({ x: p.x - shapes[0].w / 2, y: p.y + 3, w: shapes[0].w, h: shapes[0].h, shape: shapes[0] });
    }
    const inside = (c) => c.x >= bounds.x + 1 && c.y >= bounds.y + 1 && c.x + c.w <= bounds.x + bounds.w - 1 && c.y + c.h <= bounds.y + bounds.h - 1;
    const freeOfLabels = (rect) => !placed.some((b) => overlaps(rect, b));
    const freeOfBoxes = (rect) => !boxRects.some((b) => overlaps(rect, b));
    const free = (c) => inside(c) && freeOfLabels(c) && freeOfBoxes(c);
    // Every place is taken: slide a place right, left, down or up, just past
    // the labels in its way, and take the shortest slide that ends free.
    const slide = (c, dx, dy) => {
      let s = c;
      for (let k = 0; k < 6; k++) {
        const b = placed.find((p) => overlaps(s, p));
        if (!b) break;
        const x = dx > 0 ? b.x + b.w + 2 : (dx < 0 ? b.x - 2 - s.w : s.x);
        const y = dy > 0 ? b.y + b.h + 2 : (dy < 0 ? b.y - 2 - s.h : s.y);
        s = Object.assign({}, s, { x: x, y: y });
      }
      return Object.assign({}, s, { move: Math.abs(s.x - c.x) + Math.abs(s.y - c.y) });
    };
    const slid = [];
    for (const c of candidates) for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) slid.push(slide(c, dx, dy));
    slid.sort((a, b) => a.move - b.move);
    const chosen = candidates.find(free) || slid.find((c) => c.move <= L.labelSlideMax && free(c)) ||
      candidates.find((c) => inside(c) && freeOfBoxes(c)) || candidates.find(inside) || candidates[0];
    placed.push(chosen);
    const lines = chosen.shape.lines;
    const w = chosen.w;
    const h = chosen.h;
    const g = svg('g', {
      'data-edge-ids': ids.join(' '), tabindex: '0', role: 'button',
      'aria-label': 'List the flows on this arrow: ' + text
    });
    const tip = svg('title');
    tip.textContent = items.map(flowText).join('\n') + '\nClick to list these flows in the panel.';
    g.append(tip);
    g.append(svg('rect', { class: 'edge-label-bg', x: chosen.x, y: chosen.y, width: w, height: h, rx: 3 }));
    const t = svg('text', { class: 'edge-label-text', x: chosen.x + w / 2, y: chosen.y + L.labelPadY + L.labelLineH - 3 });
    lines.forEach((line, i) => {
      const span = svg('tspan', { x: chosen.x + w / 2, dy: i === 0 ? 0 : L.labelLineH });
      span.textContent = line;
      t.append(span);
    });
    g.append(t);
    return g;
  }

  // ---- the detail panel ----------------------------------------------
  function renderDetail(state) {
    const panel = $('detail');
    panel.textContent = '';
    if (state.mode === 'tour') panel.append(tourCard(state.step));
    if (selectedGroup && selectedGroup.length) panel.append(edgeFlows(selectedGroup));
    if (state.mode === 'tour') panel.append(el('p', { class: 'tour-node-note', text: 'The part this step is about:' }));
    panel.append(state.focus === ROOT ? rootDetail() : nodeDetail(state.focus));
    panel.scrollTop = 0;
  }

  function rootDetail() {
    const box = el('div', { class: 'detail' });
    box.append(el('h2', { id: 'detail-title', class: 'detail-title', dataset: { nodeId: ROOT }, tabindex: '-1', text: model.title }));
    box.append(inlineProse('p', model.question, 'question'));
    box.append(prose(model.summary, { id: 'detail-prose' }));
    box.append(el('p', { class: 'hint', text: 'Click a box to zoom in; use Zoom out or the breadcrumb to go back. Tour follows one event step by step; "How to read this page" explains the map.' }));
    return box;
  }

  function nodeDetail(id) {
    const n = idx.nodes.get(id);
    const box = el('div', { class: 'detail' });
    box.append(el('h2', { id: 'detail-title', class: 'detail-title', dataset: { nodeId: id }, tabindex: '-1', text: n.title }));

    const path = el('nav', { class: 'detail-path', 'aria-label': 'Location in the model' });
    [ROOT].concat(pathTo(id)).forEach((p, i, all) => {
      if (i > 0) path.append(el('span', { class: 'crumb-sep', 'aria-hidden': 'true', text: '›' }));
      if (i === all.length - 1) path.append(el('span', { text: titleOf(p) }));
      else path.append(link(nodeHash(p), p === ROOT ? 'Overview' : titleOf(p)));
    });
    box.append(path);
    appendNodeBody(box, n, 'h3', 'h4', true);
    return box;
  }

  // The body of a node: outside note, summary, prose, developer notes,
  // decisions, code references, sources and (optionally) flows.
  function appendNodeBody(box, n, h3, h4, withFlows, proseId) {
    if (n.outside_repo === true) {
      box.append(el('p', { class: 'outside-note' }, [
        el('span', { class: 'badge badge-outside', text: 'Outside this repo' }),
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
        const art = el('article', { class: 'decision' });
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
    const flows = flowsOf(n.id);
    if (flows.incoming.length || flows.outgoing.length) {
      box.append(el(h3, { text: 'Flows' }));
      if (flows.incoming.length) {
        box.append(el(h4, { class: 'flow-heading', text: 'Comes from' }));
        box.append(el('ul', { class: 'flow-list' }, flows.incoming.map((e) => flowItem(e, 'in', n.id))));
      }
      if (flows.outgoing.length) {
        box.append(el(h4, { class: 'flow-heading', text: 'Goes to' }));
        box.append(el('ul', { class: 'flow-list' }, flows.outgoing.map((e) => flowItem(e, 'out', n.id))));
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
    return where.length ? ' (in ' + where.map(titleOf).join(' › ') + ')' : '';
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
      el('span', { class: 'badge badge-kind kind-' + e.kind, text: EDGE_KIND_NAMES[e.kind] || e.kind }),
      el('span', { class: 'flow-dir', text: direction === 'in' ? ' ← from ' : ' → to ' }),
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

  // The flows an arrow on the map stands for (opened by clicking its label).
  function edgeFlows(ids) {
    const edges = ids.map((id) => idx.edgeById.get(id)).filter(Boolean);
    const sec = el('section', { id: 'edge-flows', class: 'edge-flows', 'aria-label': 'Flows on the selected arrow', dataset: { edgeIds: ids.join(' ') } });
    sec.append(el('div', { class: 'edge-flows-head' }, [
      el('h3', { text: edges.length === 1 ? 'The flow on this arrow' : 'The ' + edges.length + ' flows on this arrow' }),
      el('button', { id: 'edge-flows-close', type: 'button', text: 'Close' })
    ]));
    sec.append(el('ul', { class: 'flow-list' }, edges.map((e) => {
      const li = el('li', { class: 'flow kind-' + e.kind, dataset: { edgeId: e.id } });
      li.append(el('div', { class: 'flow-head' }, [
        el('span', { class: 'badge badge-kind kind-' + e.kind, text: EDGE_KIND_NAMES[e.kind] || e.kind }),
        ' ',
        link(nodeHash(e.from), titleOf(e.from), 'xref flow-end'),
        el('span', { class: 'flow-dir', text: ' → ' }),
        link(nodeHash(e.to), titleOf(e.to), 'xref flow-end')
      ]));
      flowExtras(li, e);
      return li;
    })));
    return sec;
  }

  function tourCard(k) {
    const tour = model.tour;
    const step = idx.steps[k - 1];
    const T = idx.steps.length;
    const card = el('section', { class: 'tour-card', 'aria-label': 'Tour step' });
    card.append(el('div', { class: 'tour-head' }, [
      el('span', { class: 'tour-count', text: 'Step ' + k + ' of ' + T }),
      el('span', { class: 'tour-name', text: tour.title })
    ]));
    card.append(el('div', { class: 'tour-controls' }, [
      el('button', { id: 'tour-prev', type: 'button', disabled: k <= 1, text: '← Previous' }),
      el('button', { id: 'tour-next', type: 'button', class: 'primary', disabled: k >= T, text: 'Next →' }),
      el('button', { id: 'tour-exit', type: 'button', text: 'Exit tour' })
    ]));
    card.append(el('p', { class: 'tour-keys', text: 'Keys: Left and Right arrows move between steps; Escape leaves the tour.' }));
    card.append(el('h2', { id: 'tour-step-title', class: 'tour-step-title', dataset: { stepIndex: String(k) }, text: step.title }));
    card.append(prose(step.prose, { id: 'tour-step-prose' }));
    const refs = referenceList(step.code_refs, step.sources);
    if (refs) card.append(refs);
    const about = el('details', { class: 'tour-about', open: k === 1 }, [el('summary', { text: 'About this tour' })]);
    about.append(prose(tour.intro, { class: 'prose tour-intro' }));
    card.append(about);
    return card;
  }

  // ---- the one-page view ----------------------------------------------
  function renderReadPage(state) {
    const page = $('read-page');
    page.textContent = '';
    xrefHash = readHash;
    try {
      page.append(el('p', { class: 'read-note', text: 'The whole design model as one page: the overview, then every part with its sub-parts in order, then the tour. Links to parts jump within this page; "Back to the map" returns to the zoomable map.' }));
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
        const hTag = 'h' + Math.min(6, depth + 1);
        const head = el(hTag, { class: 'read-title' }, [n.title]);
        sec.append(head);
        const where = pathTo(id).slice(0, -1);
        sec.append(el('p', { class: 'read-path' }, [
          where.length ? 'Part of ' + where.map(titleOf).join(' › ') + '. ' : '',
          link(nodeHash(id), 'Show on the map', 'read-map-link')
        ]));
        appendNodeBody(sec, n, 'h' + Math.min(6, depth + 2), 'h' + Math.min(6, depth + 3), false, null);
        const out = idx.edges.filter((e) => e.from === id);
        if (out.length) {
          sec.append(el('h' + Math.min(6, depth + 2), { text: 'Flows out of this part' }));
          sec.append(el('ul', { class: 'flow-list' }, out.map((e) => {
            const li = el('li', { class: 'flow kind-' + e.kind });
            li.append(el('div', { class: 'flow-head' }, [
              el('span', { class: 'badge badge-kind kind-' + e.kind, text: EDGE_KIND_NAMES[e.kind] || e.kind }),
              el('span', { class: 'flow-dir', text: ' → to ' }),
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
          li.append(el('p', { class: 'read-path' }, ['Part: ', link(readHash(s.node), titleOf(s.node)), ' · ', link('#/tour/' + (i + 1), 'Show this step on the map')]));
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
    const targetId = state.target ? 'read-' + state.target : (/^#\/read\/tour$/.test(location.hash) ? 'read-tour' : null);
    const target = targetId ? $(targetId) : null;
    if (target) target.scrollIntoView({ block: 'start' });
    else page.scrollTop = 0;
  }

  // ---- legend ----------------------------------------------------------
  function renderLegend() {
    const legend = $('legend');
    legend.textContent = '';
    legend.append(el('span', { class: 'legend-title', text: 'Arrows:' }));
    for (const kind of EDGE_KINDS) {
      const s = svg('svg', { width: 34, height: 10, class: 'legend-line', 'aria-hidden': 'true' });
      const g = svg('g', { class: 'edge kind-' + kind });
      g.append(svg('path', { class: 'edge-line', d: 'M1,5 L30,5', 'marker-end': 'url(#legend-arrow-' + kind + ')' }));
      const defs = svg('defs');
      const marker = svg('marker', { id: 'legend-arrow-' + kind, viewBox: '0 0 10 10', refX: '9', refY: '5', markerWidth: '6', markerHeight: '6', orient: 'auto', markerUnits: 'userSpaceOnUse' });
      marker.append(svg('path', { d: 'M0,0 L10,5 L0,10 z', class: 'arrow kind-' + kind }));
      defs.append(marker);
      s.append(defs, g);
      legend.append(el('span', { class: 'legend-item' }, [s, EDGE_KIND_NAMES[kind]]));
    }
    legend.append(el('span', { class: 'legend-item' }, [
      el('span', { class: 'badge badge-outside', text: 'Outside this repo' }),
      'not implemented in this repository'
    ]));
    legend.append(el('span', { class: 'legend-item' }, [
      el('span', { class: 'badge badge-stub', text: 'to …' }),
      'arrow to a part on another level (click the tag)'
    ]));
  }

  // ------------------------------------------------------------------
  // Events
  // ------------------------------------------------------------------
  function selectEdges(ids) {
    selectedGroup = ids;
    renderMap(current);
    renderDetail(current);
    const sec = $('edge-flows');
    if (sec) {
      const h = sec.querySelector('h3');
      if (h) { h.setAttribute('tabindex', '-1'); h.focus({ preventScroll: true }); }
    }
  }
  function activateMapItem(target) {
    const stub = target.closest('.stub-chip');
    if (stub) { focusMapAfterRender = true; go(nodeHash(stub.getAttribute('data-node-id'))); return true; }
    const label = target.closest('.edge-label');
    if (label) { selectEdges(label.getAttribute('data-edge-ids').split(' ')); return true; }
    const box = target.closest('.node-box');
    if (box) { focusMapAfterRender = true; go(nodeHash(box.dataset.nodeId)); return true; }
    return false;
  }
  function toggleHelp(show) {
    const help = $('help');
    const open = show === undefined ? help.hidden : show;
    help.hidden = !open;
    $('help-toggle').setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open) $('help-title').focus({ preventScroll: false });
  }

  function bindEvents() {
    $('map').addEventListener('click', (ev) => { activateMapItem(ev.target); });
    $('map').addEventListener('keydown', (ev) => {
      if (ev.key !== 'Enter' && ev.key !== ' ') return;
      const t = ev.target;
      if (t && t.closest && (t.closest('.stub-chip') || t.closest('.edge-label'))) {
        ev.preventDefault();
        activateMapItem(t);
      }
    });
    $('breadcrumb').addEventListener('click', (ev) => {
      const crumb = ev.target.closest('.crumb');
      if (crumb) go(nodeHash(crumb.dataset.nodeId));
    });
    $('zoom-out').addEventListener('click', zoomOut);
    $('tour-start').addEventListener('click', startTour);
    $('read-toggle').addEventListener('click', () => go(current && current.mode === 'read' ? '#/' : '#/read'));
    $('help-toggle').addEventListener('click', () => toggleHelp());
    $('help-close').addEventListener('click', () => { toggleHelp(false); $('help-toggle').focus(); });
    $('detail').addEventListener('click', (ev) => {
      const btn = ev.target.closest('button');
      if (!btn) return;
      if (btn.id === 'edge-flows-close') { selectedGroup = null; renderMap(current); renderDetail(current); return; }
      if (!current || current.mode !== 'tour') return;
      if (btn.id === 'tour-next') tourStep(1);
      else if (btn.id === 'tour-prev') tourStep(-1);
      else if (btn.id === 'tour-exit') exitTour();
    });
    document.addEventListener('keydown', (ev) => {
      if (ev.altKey || ev.ctrlKey || ev.metaKey) return;
      const t = ev.target;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
      if (ev.key === 'Escape' && !$('help').hidden) { ev.preventDefault(); toggleHelp(false); return; }
      if (!current || current.mode === 'read') return;
      if (current && current.mode === 'tour' && (ev.key === 'ArrowRight' || ev.key === 'ArrowLeft')) {
        ev.preventDefault();
        tourStep(ev.key === 'ArrowRight' ? 1 : -1);
        return;
      }
      if (ev.key !== 'Escape' && ev.key !== 'Backspace') return;
      ev.preventDefault();
      if (current && current.mode === 'tour' && ev.key === 'Escape') exitTour();
      else zoomOut();
    });
    window.addEventListener('hashchange', render);
    let resizeTimer = null;
    window.addEventListener('resize', () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => { if (current && current.mode !== 'read') renderMap(current); }, 150);
    });
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
      $('map').append(el('p', { class: 'load-error', text: 'Nothing to show: the design model did not load.' }));
      return;
    }
    $('model-title').textContent = model.title;
    document.title = model.title;
    $('tour-start').disabled = idx.steps.length === 0;
    renderLegend();
    render();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
