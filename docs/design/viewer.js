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
 *
 * Test hooks (documented in tools/README.md): .node-box[data-node-id] in
 * #map, #detail-title[data-node-id], #zoom-out, #breadcrumb [data-node-id]
 * (root crumb "__root__"), #tour-start, #tour-next, #tour-prev, #tour-exit,
 * #tour-step-title[data-step-index], body[data-ready], body[data-focus].
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
    'confluence-internal': 'Confluence, SLAC login required',
    'web': 'Web'
  };

  // Layout constants (pixels).
  const L = {
    boxMinW: 140, boxMaxW: 210, boxH: 124,
    colGap: 92, rowGap: 52,
    marginX: 16, marginRight: 40, marginTop: 40, marginBottom: 40,
    maxRows: 4,
    labelMaxW: 74, labelLineH: 13, labelPadX: 4, labelPadY: 2,  // labelMaxW + 2 * labelPadX < colGap - 6
    laneTrack: 19, gutterTrack: 8, cornerRadius: 6  // laneTrack > label height: lane labels stay on their own track
  };
  const LABEL_FONT = '11px system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';

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
    steps: []
  };
  let current = null;            // the state being shown
  let tourReturnHash = '#/';     // where "Exit tour" goes
  let focusMapAfterRender = false;

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
  function go(hash) {
    if (location.hash === hash || (hash === '#/' && (location.hash === '' || location.hash === '#'))) render();
    else location.hash = hash;
  }

  // ------------------------------------------------------------------
  // Prose markup: paragraphs on blank lines, `code`, [text](url),
  // [[node-id]] and [[node-id|text]]. Everything else is literal text.
  // ------------------------------------------------------------------
  const INLINE_RE = /`([^`]+)`|\[\[([^\]|]+)(?:\|([^\]]+))?\]\]|\[([^\]]+)\]\(([^()\s]+)\)/g;

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
        if (idx.nodes.has(id)) parent.append(link(nodeHash(id), m[3] !== undefined ? m[3] : titleOf(id), 'xref'));
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
    if (!current) return;
    if (current.focus === ROOT) return;
    go(nodeHash(parentOf(current.focus)));
  }
  function startTour() {
    if (!idx.steps.length) return;
    if (!current || current.mode !== 'tour') tourReturnHash = location.hash && location.hash !== '#' ? location.hash : '#/';
    go('#/tour/1');
  }
  function exitTour() {
    const back = /^#\/tour/.test(tourReturnHash) ? '#/' : tourReturnHash;
    go(back);
  }

  // ------------------------------------------------------------------
  // Rendering
  // ------------------------------------------------------------------
  function render() {
    if (!model) return;
    const state = parseHash();
    current = state;
    showMessage(state.message || '');
    renderBreadcrumb(state);
    renderMap(state);
    renderDetail(state);
    $('zoom-out').disabled = state.focus === ROOT;
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
    const groups = visibleEdgeGroups(view.ids);
    const availW = Math.max(320, map.clientWidth - 4);
    const layout = layoutBoxes(view.ids, groups, availW);
    const routes = routeEdges(layout);

    const canvas = el('div', { class: 'map-canvas' });
    canvas.style.width = layout.width + 'px';
    canvas.style.height = layout.height + 'px';

    const svgEl = svg('svg', { class: 'edges', width: layout.width, height: layout.height, 'aria-hidden': 'true' });
    svgEl.append(arrowDefs());
    const labelRects = [];
    const boxRects = Array.from(layout.pos.values()).map((p) => ({ x: p.x - 3, y: p.y - 3, w: p.w + 6, h: p.h + 6 }));
    for (const r of routes) {
      const ids = r.group.items.map((e) => e.id);
      const lit = ids.some((id) => highlightEdges.has(id));
      const g = svg('g', {
        class: 'edge kind-' + r.group.kind + (lit ? ' is-highlighted' : '') + (highlightEdges.size && !lit ? ' is-dim' : ''),
        'data-edge-ids': ids.join(' ')
      });
      const tip = svg('title');
      tip.textContent = r.group.items.map((e) => (EDGE_KIND_NAMES[e.kind] || e.kind) + ': ' + titleOf(e.from) + ' → ' + titleOf(e.to) + ' (' + e.label + ')').join('\n');
      g.append(tip);
      g.append(svg('path', { class: 'edge-line', d: r.d, 'marker-end': 'url(#arrow-' + r.group.kind + ')' }));
      placeLabel(g, r, boxRects, labelRects);
      svgEl.append(g);
    }
    canvas.append(svgEl);

    for (const id of view.ids) {
      const p = layout.pos.get(id);
      canvas.append(nodeBox(id, p, id === view.highlight));
    }

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

  function nodeBox(id, p, highlighted) {
    const n = idx.nodes.get(id);
    const kids = childrenOf(id).length;
    const meta = el('span', { class: 'node-meta' }, [
      n.outside_repo === true ? el('span', { class: 'badge badge-outside', text: 'Outside this repo' }) : null,
      el('span', { class: 'node-count', text: kids ? kids + (kids === 1 ? ' part' : ' parts') : 'Read details' })
    ]);
    const box = el('button', {
      type: 'button',
      class: 'node-box' + (kids ? ' has-children' : ' is-leaf') + (n.outside_repo === true ? ' is-outside' : '') + (highlighted ? ' is-highlighted' : ''),
      dataset: { nodeId: id },
      title: typeof n.summary === 'string' ? n.summary : null,
      'aria-current': highlighted ? 'true' : null
    }, [
      el('span', { class: 'node-title', text: n.title }),
      inlineProse('span', n.summary, 'node-summary'),
      meta
    ]);
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
  // grouped by (from, to, kind). Edges whose lifted ends coincide, or with an
  // end outside the view, are not drawn (the detail panel lists them).
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

  // ---- layout --------------------------------------------------------
  // Layered left to right by longest path over the data/trigger/timing
  // edges (back edges of cycles ignored), JSON order as tie-break. A layer
  // with more than maxRows boxes wraps into several columns; when the
  // columns do not fit the width, they wrap into bands below each other,
  // every second band running right to left (so that the flow continues
  // under the last column). Boxes without any data/trigger/timing edge have
  // no rank: they fill the free cells of the bands, then rows below, in JSON
  // order. With no ranking edges at all: a grid in JSON order.
  function layoutBoxes(ids, groups, availW) {
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
    const fit = maxColumnsFor(availW);

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

    // Decide every route on the grid first; busy lanes get taller.
    const routes = classifyRoutes(groups, cell);
    const laneCount = new Array(nRows + 1).fill(0);
    for (const r of routes) if (r.lane !== undefined) laneCount[r.lane]++;
    const laneH = laneCount.map((n, l) => {
      const base = l === 0 ? L.marginTop : (l === nRows ? L.marginBottom : L.rowGap);
      return Math.max(base, 12 + n * L.laneTrack);
    });

    const w = boxWidthFor(availW, nCols);
    const h = L.boxH;
    const colX = (c) => L.marginX + c * (w + L.colGap);
    const rowTop = [];
    let y = laneH[0];
    for (let r = 0; r < nRows; r++) { rowTop.push(y); y += h + laneH[r + 1]; }
    const pos = new Map();
    for (const [id, c] of cell) {
      pos.set(id, { id: id, col: c.col, row: c.row, x: colX(c.col), y: rowTop[c.row], w: w, h: h });
    }
    return {
      pos: pos, routes: routes, nCols: nCols, nRows: nRows, w: w, h: h,
      width: colX(nCols - 1) + w + L.marginRight,
      height: y,
      // x of the vertical gutter left of column c (c = 0..nCols)
      gutterX: (c) => (c <= 0 ? L.marginX / 2 : (c >= nCols ? colX(nCols - 1) + w + L.marginRight / 2 : colX(c) - L.colGap / 2)),
      // y of the middle of the horizontal lane above row r (r = 0..nRows)
      laneY: (r) => (r <= 0 ? laneH[0] / 2 : (r >= nRows ? rowTop[nRows - 1] + h + laneH[nRows] / 2 : rowTop[r] - laneH[r] / 2))
    };
  }
  function maxColumnsFor(availW) {
    const usable = availW - L.marginX - L.marginRight + L.colGap;
    return Math.max(1, Math.floor(usable / (L.boxMinW + L.colGap)));
  }
  function boxWidthFor(availW, nCols) {
    const usable = availW - L.marginX - L.marginRight - (nCols - 1) * L.colGap;
    return Math.max(L.boxMinW, Math.min(L.boxMaxW, Math.floor(usable / nCols)));
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
  function classifyRoutes(groups, cell) {
    return groups.map((g, i) => {
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
  }

  function routeEdges(layout) {
    const routes = layout.routes;
    const sides = new Map();   // "id:side" -> [{route, end}]
    const lanes = new Map();   // lane index -> [route]
    const gutters = new Map(); // gutter index -> [route]
    const use = (map, key, r) => { if (!map.has(key)) map.set(key, []); map.get(key).push(r); };
    for (const r of routes) {
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
      const spacing = Math.min(L.gutterTrack, (L.colGap - 24) / list.length);
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
        else if (side === 'T') pt = { x: box.x + box.w * (0.15 + 0.7 * t), y: box.y };
        else pt = { x: box.x + box.w * (0.15 + 0.7 * t), y: box.y + box.h };
        item.route[item.end === 'from' ? 'S' : 'E'] = pt;
      });
    }

    for (const r of routes) buildPath(r);
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
      // A nearly straight curve keeps its label just above the line.
      const flat = Math.abs(E.y - S.y) < 24;
      r.label = { x: (S.x + 3 * c1.x + 3 * c2.x + E.x) / 8, y: (S.y + 3 * c1.y + 3 * c2.y + E.y) / 8, axis: 'y', min: Math.min(S.y, E.y) - 60, max: Math.max(S.y, E.y) + 60, above: flat };
    } else if (r.type === 'vertical') {
      const dy = (E.y - S.y) / 2;
      r.d = 'M' + S.x + ',' + S.y + ' C' + S.x + ',' + (S.y + dy) + ' ' + E.x + ',' + (E.y - dy) + ' ' + E.x + ',' + E.y;
      r.label = { x: (S.x + E.x) / 2, y: (S.y + E.y) / 2, axis: 'x', min: Math.min(S.x, E.x) - 60, max: Math.max(S.x, E.x) + 60 };
    } else if (r.type === 'lane') {
      const pts = [S, { x: S.x, y: r.ly }, { x: E.x, y: r.ly }, E];
      r.d = roundedPath(pts);
      r.label = { x: (S.x + E.x) / 2, y: r.ly, axis: 'x', min: Math.min(S.x, E.x), max: Math.max(S.x, E.x), inLane: true };
    } else {
      const pts = [S, { x: r.gx, y: S.y }, { x: r.gx, y: r.ly }, { x: E.x, y: r.ly }, E];
      r.d = roundedPath(pts);
      if (Math.abs(E.x - r.gx) >= 60) {
        r.label = { x: (r.gx + E.x) / 2, y: r.ly, axis: 'x', min: Math.min(r.gx, E.x), max: Math.max(r.gx, E.x), inLane: true };
      } else {
        r.label = { x: r.gx, y: (S.y + r.ly) / 2, axis: 'y', min: Math.min(S.y, r.ly), max: Math.max(S.y, r.ly) };
      }
    }
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

  // ---- edge labels ---------------------------------------------------
  let measureCtx = null;
  function textWidth(text) {
    if (!measureCtx) {
      measureCtx = document.createElement('canvas').getContext('2d');
      measureCtx.font = LABEL_FONT;
    }
    return measureCtx.measureText(text).width;
  }
  function wrapLabel(text, maxW) {
    const words = text.split(/\s+/).filter(Boolean);
    const lines = [];
    let line = '';
    for (const w of words) {
      const next = line ? line + ' ' + w : w;
      if (line && textWidth(next) > maxW) { lines.push(line); line = w; } else line = next;
    }
    if (line) lines.push(line);
    return lines;
  }
  function overlaps(a, b) {
    return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
  }
  // Place the label at the middle of its segment; if it would cover a box or
  // another label, slide it along the segment.
  function placeLabel(g, r, boxRects, placed) {
    const items = r.group.items;
    const text = items[0].label + (items.length > 1 ? ' (+' + (items.length - 1) + ' more)' : '');
    // A label on a lane may be as wide as its horizontal segment (one line
    // keeps it on its own track); other labels wrap to fit a gutter.
    const spot0 = r.label;
    const maxW = spot0.inLane ? Math.max(L.labelMaxW, Math.min(220, spot0.max - spot0.min - 12)) : L.labelMaxW;
    const lines = wrapLabel(text, maxW);
    const w = Math.ceil(Math.max(...lines.map(textWidth))) + 2 * L.labelPadX;
    const h = lines.length * L.labelLineH + 2 * L.labelPadY;
    const spot = Object.assign({}, r.label);
    if (spot.above) spot.y -= h / 2 + 2;
    const step = spot.axis === 'y' ? h + 4 : w / 2 + 6;
    // Candidates: the middle, then alternately further along the segment.
    const candidates = [];
    for (let k = 0; k < 9; k++) {
      const shift = (k % 2 ? 1 : -1) * Math.ceil(k / 2) * step;
      const cx = spot.axis === 'x' ? spot.x + shift : spot.x;
      const cy = spot.axis === 'y' ? spot.y + shift : spot.y;
      const along = spot.axis === 'x' ? cx : cy;
      if (k > 0 && (along < spot.min || along > spot.max)) continue;
      candidates.push({ x: cx - w / 2, y: cy - h / 2, w: w, h: h });
    }
    const freeOfLabels = (rect) => !placed.some((b) => overlaps(rect, b));
    const freeOfBoxes = (rect) => !boxRects.some((b) => overlaps(rect, b));
    const chosen = candidates.find((c) => freeOfLabels(c) && freeOfBoxes(c)) ||
      candidates.find(freeOfLabels) || candidates[0];
    placed.push(chosen);
    g.append(svg('rect', { class: 'edge-label-bg', x: chosen.x, y: chosen.y, width: w, height: h, rx: 3 }));
    const t = svg('text', { class: 'edge-label', x: chosen.x + w / 2, y: chosen.y + L.labelPadY + L.labelLineH - 3 });
    lines.forEach((line, i) => {
      const span = svg('tspan', { x: chosen.x + w / 2, dy: i === 0 ? 0 : L.labelLineH });
      span.textContent = line;
      t.append(span);
    });
    g.append(t);
  }

  // ---- the detail panel ----------------------------------------------
  function renderDetail(state) {
    const panel = $('detail');
    panel.textContent = '';
    if (state.mode === 'tour') panel.append(tourCard(state.step));
    panel.append(state.focus === ROOT ? rootDetail() : nodeDetail(state.focus));
    panel.scrollTop = 0;
  }

  function rootDetail() {
    const box = el('div', { class: 'detail' });
    box.append(el('h2', { id: 'detail-title', class: 'detail-title', dataset: { nodeId: ROOT }, tabindex: '-1', text: model.title }));
    box.append(inlineProse('p', model.question, 'question'));
    box.append(prose(model.summary, { id: 'detail-prose' }));
    box.append(el('p', { class: 'hint', text: 'Click a box to zoom in; use Zoom out or the breadcrumb to go back. Tour follows one event step by step.' }));
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

    if (n.outside_repo === true) {
      box.append(el('p', { class: 'outside-note' }, [
        el('span', { class: 'badge badge-outside', text: 'Outside this repo' }),
        ' This part is not implemented in the lcls2 repository (for example firmware, another repository or a facility service). Its description is based on the external sources listed below.'
      ]));
    }
    box.append(inlineProse('p', n.summary, 'summary'));
    box.append(prose(n.prose, { id: 'detail-prose' }));

    if (typeof n.dev_notes === 'string' && n.dev_notes.trim()) {
      box.append(el('h3', { text: 'For developers' }));
      box.append(prose(n.dev_notes, { class: 'prose dev-notes' }));
    }

    const decisions = Array.isArray(n.decisions) ? n.decisions : [];
    if (decisions.length) {
      box.append(el('h3', { text: 'Design decisions' }));
      for (const d of decisions) {
        const art = el('article', { class: 'decision' });
        art.append(el('h4', { text: d.title }));
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
      box.append(el('h3', { text: 'Code references' }));
      box.append(el('ul', { class: 'ref-list' }, codeRefs.map(codeRefItem)));
    }
    const sourceIds = Array.isArray(n.sources) ? n.sources : [];
    if (sourceIds.length) {
      box.append(el('h3', { text: 'Sources' }));
      box.append(el('ul', { class: 'ref-list' }, sourceIds.map(sourceItem)));
    }

    const flows = flowsOf(id);
    if (flows.incoming.length || flows.outgoing.length) {
      box.append(el('h3', { text: 'Flows' }));
      if (flows.incoming.length) {
        box.append(el('h4', { class: 'flow-heading', text: 'Comes from' }));
        box.append(el('ul', { class: 'flow-list' }, flows.incoming.map((e) => flowItem(e, 'in', id))));
      }
      if (flows.outgoing.length) {
        box.append(el('h4', { class: 'flow-heading', text: 'Goes to' }));
        box.append(el('ul', { class: 'flow-list' }, flows.outgoing.map((e) => flowItem(e, 'out', id))));
      }
    }
    return box;
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

  function flowItem(e, direction, focusId) {
    const otherId = direction === 'in' ? e.from : e.to;
    const insideId = direction === 'in' ? e.to : e.from;
    const li = el('li', { class: 'flow kind-' + e.kind });
    const head = el('div', { class: 'flow-head' }, [
      el('span', { class: 'badge badge-kind kind-' + e.kind, text: EDGE_KIND_NAMES[e.kind] || e.kind }),
      ' ',
      el('strong', { text: e.label }),
      direction === 'in' ? ' from ' : ' to ',
      link(nodeHash(otherId), titleOf(otherId), 'xref')
    ]);
    const where = pathTo(otherId).slice(0, -1);
    if (where.length) head.append(el('span', { class: 'flow-where', text: ' (in ' + where.map(titleOf).join(' › ') + ')' }));
    if (insideId !== focusId) {
      head.append(direction === 'in' ? ', into ' : ', from ');
      head.append(link(nodeHash(insideId), titleOf(insideId), 'xref'));
    }
    li.append(head);
    if (typeof e.prose === 'string' && e.prose.trim()) li.append(prose(e.prose, { class: 'prose flow-prose' }));
    const refs = referenceList(e.code_refs, e.sources);
    if (refs) li.append(refs);
    return li;
  }

  function tourCard(k) {
    const tour = model.tour;
    const step = idx.steps[k - 1];
    const T = idx.steps.length;
    const card = el('section', { class: 'tour-card', 'aria-label': 'Tour' });
    card.append(el('div', { class: 'tour-head' }, [
      el('span', { class: 'tour-name', text: tour.title }),
      el('span', { class: 'tour-count', text: 'Step ' + k + ' of ' + T })
    ]));
    card.append(el('div', { class: 'tour-controls' }, [
      el('button', { id: 'tour-prev', type: 'button', disabled: k <= 1, text: '← Previous' }),
      el('button', { id: 'tour-next', type: 'button', class: 'primary', disabled: k >= T, text: 'Next →' }),
      el('button', { id: 'tour-exit', type: 'button', text: 'Exit tour' })
    ]));
    if (k === 1) {
      card.append(prose(tour.intro, { class: 'prose tour-intro' }));
    } else {
      const about = el('details', { class: 'tour-about' }, [el('summary', { text: 'About this tour' })]);
      about.append(prose(tour.intro, { class: 'prose tour-intro' }));
      card.append(about);
    }
    card.append(el('h3', { id: 'tour-step-title', class: 'tour-step-title', dataset: { stepIndex: String(k) }, text: step.title }));
    card.append(prose(step.prose, { id: 'tour-step-prose' }));
    const refs = referenceList(step.code_refs, step.sources);
    if (refs) card.append(refs);
    card.append(el('p', { class: 'tour-node-note', text: 'The highlighted box on the map is the part this step is about; its details follow.' }));
    return card;
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
  }

  // ------------------------------------------------------------------
  // Events
  // ------------------------------------------------------------------
  function bindEvents() {
    $('map').addEventListener('click', (ev) => {
      const box = ev.target.closest('.node-box');
      if (!box) return;
      focusMapAfterRender = true;
      go(nodeHash(box.dataset.nodeId));
    });
    $('breadcrumb').addEventListener('click', (ev) => {
      const crumb = ev.target.closest('.crumb');
      if (crumb) go(nodeHash(crumb.dataset.nodeId));
    });
    $('zoom-out').addEventListener('click', zoomOut);
    $('tour-start').addEventListener('click', startTour);
    $('detail').addEventListener('click', (ev) => {
      const btn = ev.target.closest('button');
      if (!btn || !current || current.mode !== 'tour') return;
      if (btn.id === 'tour-next') go('#/tour/' + (current.step + 1));
      else if (btn.id === 'tour-prev') go('#/tour/' + (current.step - 1));
      else if (btn.id === 'tour-exit') exitTour();
    });
    document.addEventListener('keydown', (ev) => {
      if (ev.key !== 'Escape' && ev.key !== 'Backspace') return;
      if (ev.altKey || ev.ctrlKey || ev.metaKey) return;
      const t = ev.target;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
      ev.preventDefault();
      if (current && current.mode === 'tour' && ev.key === 'Escape') exitTour();
      else zoomOut();
    });
    window.addEventListener('hashchange', render);
    let resizeTimer = null;
    window.addEventListener('resize', () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => { if (current) renderMap(current); }, 150);
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
