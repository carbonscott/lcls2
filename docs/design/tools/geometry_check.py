#!/usr/bin/env python3
"""Geometry check of the viewer's map and detail views (Playwright, Chromium).

Loads the viewer, waits for the first render and for document.fonts.ready,
and checks that the Archivo web font is loaded (document.fonts.check('600
15px Archivo') and a loaded Archivo face). It then measures the Study-1 map
(#map svg.map) and the detail view of every top-level part that has children,
opening each detail by clicking the part's first box on the map and measuring
#detail-view svg.detail[data-detail=<part>], in the page's default state
(no "Full size" toggle pressed). All coordinates are SVG user units (viewBox
units), so every count but small_text does not depend on the window size.

Counts per view:
  line_through_box  (line, box) pairs where a point sampled every 2 units
                    along the line (path.ln) lies inside the box rect shrunk
                    by 3 units, and the box is not one the line may touch: its
                    key (data-box, plus "@<lane>" for a per-lane box; data-node
                    in a detail) is not listed in the line's data-through,
                    data-ends, data-from-box or data-to-box (a per-lane copy of
                    a line, data-lane=i, may name its own lane's box "b" for
                    "b@i"). Stub tags (g.stub
                    rect) count as boxes; a stub's own connector may touch it.
                    For a group (g.dgroup) only its title strip (rect.gtitle)
                    counts, and lines that end on a kid of the group (a box
                    inside the group rect) or on the group are exempt.
  text_overflow     text elements whose bounding box extends more than 1 unit
                    past their container (the rect of the g.box or g.stub
                    around them; for the texts of a g.dgroup, its title strip
                    rect.gtitle, not the whole group rect), plus free labels
                    (every other text: text.lab, notes, band and column labels)
                    that extend past the viewBox or overlap a box rect (box,
                    stub tag or group title strip) by more than 1 unit in both
                    directions.
  box_overlap       pairs of rects of one view that overlap by more than 1 unit
                    in both directions: box rects (g.box rect.b), tag rects
                    (g.stub rect) and whole group rects (g.dgroup rect.gbox).
                    A box inside the group of its parent node (from the model)
                    is not an overlap; a kid that sticks out of its group is.
  line_over_label   (line, text) pairs where the line is painted ABOVE the text
                    (it comes later in document order, which is SVG paint
                    order), a point sampled every 2 units along the line lies
                    inside the text's bounding box shrunk by 1 unit, and no
                    opaque rect painted after the line covers that point (e.g. a
                    tag connector over a group title). A line painted under an
                    opaque box, or under the text, does not count. A line's own
                    free labels are exempt.
  text_overlap      pairs of texts of one view whose bounding boxes overlap by
                    more than 1 unit in both directions (any two visible
                    texts: box titles and sub lines, tag texts, group titles,
                    line labels, notes, band, column and ladder labels), so
                    that one text is printed over the other.
  small_text        texts whose rendered size is below MIN_TEXT_PX (7 px):
                    computed font size times the text's screen scale, in CSS px
                    at the run's viewport (--width). min_text_px is the
                    smallest rendered size; the PROBLEM line lists the smallest
                    texts (all of them with --verbose).
Informational counts per view:
  crossings_allowed (line, box) pairs that would count as line_through_box
                    but the box is listed for the line (through/ends/from/to).
  line_over_text    (line, text) pairs where a sampled line point lies inside
                    the text's bounding box shrunk by 1 unit; a line's own
                    labels (text.lab with the same data-line) are not counted.
  label_on_box      the free labels that overlap a box rect (these are also
                    counted in text_overflow).
Texts and lines inside g.tok (tour tokens) and g.callout (selection marks)
are not measured, nor elements that are not displayed.

Prints:
  font=Archivo                         (or font=missing ... when it is not loaded)
  view=<map|detail:ID> boxes=B lines=L texts=T line_through_box=X text_overflow=Y crossings_allowed=K line_over_text=J label_on_box=Q box_overlap=O line_over_label=W small_text=S text_overlap=E min_text_px=P
  PROBLEM: ... lines naming each counted element (view, line, box, text)
  INFO: smallest text <P>px at width <w>: view=<view> text='<text>'
  views=V line_through_box=X text_overflow=Y
  crossings_allowed=K line_over_text=J label_on_box=Q box_overlap=O line_over_label=W small_text=S text_overlap=E min_text_px=P
V counts the views measured (V = 1 + P, P = top-level parts with children in
the model). Exit status 0 iff the font is Archivo, V == 1 + P, every view
has at least one box, and X, Y, O, W, S and E are all 0. K, J and Q are
informational. Run it at each width that matters (e.g. --width 744 and
--width 1440): the SVG-unit counts do not depend on the width, small_text does.

Usage:
  python docs/design/tools/geometry_check.py --url http://127.0.0.1:8000/
      [--model PATH_OR_URL] [--width 1440] [--height 900] [--verbose]

--model defaults to daq-model.json next to the page. --verbose also lists the
allowed crossings and the line_over_text pairs.
Needs the playwright package and a Chromium browser.
"""

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

READY_TIMEOUT_MS = 30000
STEP_TIMEOUT_MS = 8000
# small_text floor: a map or detail text rendered smaller than this (CSS px at
# the run's viewport width) is counted.
MIN_TEXT_PX = 7.0
MAP_SELECTOR = "#map svg.map"
DETAIL_SELECTOR = '#detail-view svg.detail[data-detail="{part}"]'

FONT_JS = r"""
async () => {
  await document.fonts.ready;
  const faces = [...document.fonts].filter(f => f.family.replace(/["']/g, '').trim() === 'Archivo');
  return { check: document.fonts.check('600 15px Archivo'),
           loaded: faces.filter(f => f.status === 'loaded').length,
           faces: faces.length };
}
"""

SETTLE_JS = r"""
async () => {
  await document.fonts.ready;
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  return true;
}
"""

# Measures one SVG. Returns counts and the elements behind them.
MEASURE_JS = r"""
(args) => {
  const STEP = 2, SHRINK = 3, TOL = 1;
  const svg = document.querySelector(args.selector);
  if (!svg) return { error: 'no element matches ' + args.selector };
  const sc = svg.getScreenCTM();
  if (!sc) return { error: args.selector + ' is not rendered' };
  const inv = sc.inverse();
  const mat = el => { const m = el.getScreenCTM(); return m ? inv.multiply(m) : null; };
  const tp = (m, x, y) => [m.a * x + m.c * y + m.e, m.b * x + m.d * y + m.f];
  const r1 = v => Math.round(v * 10) / 10;
  const bb = el => {
    if (!el) return null;
    const m = mat(el); if (!m) return null;
    let b; try { b = el.getBBox(); } catch (e) { return null; }
    const ps = [tp(m, b.x, b.y), tp(m, b.x + b.width, b.y), tp(m, b.x, b.y + b.height), tp(m, b.x + b.width, b.y + b.height)];
    const xs = ps.map(p => p[0]), ys = ps.map(p => p[1]);
    return { x0: Math.min(...xs), y0: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys) };
  };
  const fmt = b => b ? '(' + [b.x0, b.y0, b.x1, b.y1].map(r1).join(',') + ')' : '(none)';
  const shown = el => {
    for (let e = el; e && e !== svg.parentNode; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return false;
    }
    return true;
  };
  const skip = el => !!el.closest('g.tok, g.callout, defs, marker');
  const toks = s => (s || '').split(/[\s,]+/).filter(Boolean);
  const vbb = svg.viewBox && svg.viewBox.baseVal;
  const vb = vbb && vbb.width ? { x0: vbb.x, y0: vbb.y, x1: vbb.x + vbb.width, y1: vbb.y + vbb.height } : null;

  // ---- boxes: g.box (rect.b), stub tags (g.stub rect), group title strips (g.dgroup rect.gtitle)
  const boxes = [], groups = [], hooks = [];
  svg.querySelectorAll('g.box').forEach(g => {
    if (!shown(g) || skip(g)) return;
    const r = g.querySelector('rect.b') || g.querySelector('rect');
    const id = g.dataset.box || g.dataset.node || g.dataset.part;
    if (!id) hooks.push('g.box without data-box/data-node ' + fmt(bb(r)));
    const lane = g.dataset.lane;
    const key = (id || '?') + (lane != null && lane !== '' ? '@' + lane : '');
    const rect = bb(r);
    if (rect) boxes.push({ key, kind: 'box', rect, el: g });
  });
  svg.querySelectorAll('g.stub').forEach(g => {
    if (!shown(g) || skip(g)) return;
    const r = [...g.children].find(c => c.tagName === 'rect') || g.querySelector('rect');
    const key = 'stub:' + (g.dataset.other || '?') + '/' + (g.dataset.dir || '?');
    const rect = bb(r);
    if (rect) boxes.push({ key, kind: 'stub', rect, el: g, edges: toks(g.dataset.edgeIds).sort().join(' ') });
  });
  svg.querySelectorAll('g.dgroup').forEach(g => {
    if (!shown(g) || skip(g)) return;
    const full = bb([...g.children].find(c => c.tagName === 'rect' && !c.classList.contains('gtitle')));
    const strip = bb(g.querySelector('rect.gtitle'));
    const key = g.dataset.node || '?';
    if (!strip) hooks.push('g.dgroup[data-node=' + key + '] has no title strip rect.gtitle');
    const grp = { key, full, strip, el: g, kids: new Set() };
    groups.push(grp);
    if (strip) boxes.push({ key, kind: 'group', rect: strip, el: g, group: grp });
  });
  const within = (a, b) => a && b && a.x0 >= b.x0 - TOL && a.y0 >= b.y0 - TOL && a.x1 <= b.x1 + TOL && a.y1 <= b.y1 + TOL;
  groups.forEach(grp => boxes.forEach(b => { if (b.kind === 'box' && b.key !== grp.key && within(b.rect, grp.full)) grp.kids.add(b.key); }));
  // solids for box_overlap: every box rect, every tag rect, every whole group rect
  const solids = boxes.filter(b => b.kind !== 'group').map(b => ({ key: (b.kind === 'stub' ? '' : 'box:') + b.key, rect: b.rect, node: b.kind === 'box' ? (b.el.dataset.node || null) : null, group: null }))
    .concat(groups.filter(g => g.full).map(g => ({ key: 'group:' + g.key, rect: g.full, node: null, group: g.key })));

  // ---- lines
  const lines = [];
  svg.querySelectorAll('path.ln').forEach((p, i) => {
    if (!shown(p) || skip(p)) return;
    const m = mat(p); if (!m) return;
    let L; try { L = p.getTotalLength(); } catch (e) { return; }
    const pts = [];
    for (let s = 0; s < L; s += STEP) { const q = p.getPointAtLength(s); pts.push(tp(m, q.x, q.y)); }
    const q = p.getPointAtLength(L); pts.push(tp(m, q.x, q.y));
    const fromTo = [...toks(p.dataset.fromBox), ...toks(p.dataset.toBox)];
    // a per-lane copy (data-lane=i) may name its own lane's boxes without "@i"
    const lane = p.dataset.lane;
    const laned = list => lane != null && lane !== '' ? list.concat(list.filter(k => !k.includes('@')).map(k => k + '@' + lane)) : list;
    const own = new Set(laned([...toks(p.dataset.through), ...toks(p.dataset.ends), ...fromTo]));
    const endsOn = new Set(laned([...toks(p.dataset.ends), ...fromTo]));
    // the stub tag this path connects to: the g.stub around it, or (a connector
    // outside its tag, with exactly one of from/to) the stub with the same edge ids
    const stubs = new Set();
    const st = p.closest('g.stub');
    if (st) stubs.add('stub:' + (st.dataset.other || '?') + '/' + (st.dataset.dir || '?'));
    else if (!!p.dataset.fromBox !== !!p.dataset.toBox && p.dataset.edgeIds) {
      const ids = toks(p.dataset.edgeIds).sort().join(' ');
      boxes.forEach(b => { if (b.kind === 'stub' && b.edges === ids) stubs.add(b.key); });
    }
    let desc;
    if (p.dataset.line) desc = 'line=' + p.dataset.line + (p.dataset.lane != null && p.dataset.lane !== '' ? '@' + p.dataset.lane : '');
    else {
      const parts = [];
      if (st) parts.push('connector of stub:' + (st.dataset.other || '?') + '/' + (st.dataset.dir || '?'));
      if (p.dataset.edgeIds) parts.push('edges=' + toks(p.dataset.edgeIds).join(','));
      if (p.dataset.fromBox) parts.push('from=' + p.dataset.fromBox);
      if (p.dataset.toBox) parts.push('to=' + p.dataset.toBox);
      if (!parts.length) parts.push('path#' + i + ' d=' + (p.getAttribute('d') || '').slice(0, 48));
      desc = parts.join(' ');
    }
    lines.push({ el: p, desc, pts, own, endsOn, stubs, line: p.dataset.line || null, edgeIds: toks(p.dataset.edgeIds).sort().join(' ') });
  });

  // ---- texts and their containers
  const texts = [];
  svg.querySelectorAll('text').forEach(t => {
    if (!shown(t) || skip(t)) return;
    const spans = t.querySelectorAll('tspan');
    const raw = spans.length ? [...spans].map(x => x.textContent).join(' ') : t.textContent;
    const s = (raw || '').replace(/\s+/g, ' ').trim(); if (!s) return;
    const b = bb(t); if (!b || b.x1 - b.x0 <= 0) return;
    const c = t.closest('g.box, g.stub, g.dgroup');
    let cont = null, ckey = null;
    if (c) {
      if (c.classList.contains('box')) { cont = bb(c.querySelector('rect.b') || c.querySelector('rect')); ckey = 'box ' + (c.dataset.box || c.dataset.node || '?') + (c.dataset.lane != null && c.dataset.lane !== '' ? '@' + c.dataset.lane : ''); }
      else if (c.classList.contains('stub')) { cont = bb([...c.children].find(x => x.tagName === 'rect') || c.querySelector('rect')); ckey = 'stub ' + (c.dataset.other || '?') + '/' + (c.dataset.dir || '?'); }
      else {
        // a group's own texts are its title: measured against the title strip
        const strip = c.querySelector('rect.gtitle');
        cont = bb(strip || [...c.children].find(x => x.tagName === 'rect' && !x.classList.contains('gtitle')));
        ckey = (strip ? 'group title strip ' : 'group ') + (c.dataset.node || '?');
      }
    }
    // rendered size in CSS px: the computed font size (user units) times the text's screen scale
    const sm = t.getScreenCTM();
    const px = sm ? parseFloat(getComputedStyle(t).fontSize) * Math.hypot(sm.a, sm.b) : NaN;
    texts.push({ el: t, s, b, cont, ckey, free: !c, px, line: t.dataset.line || null, edgeIds: toks(t.dataset.edgeIds).sort().join(' ') });
  });
  // opaque rects (for line_over_label: a line under an opaque rect is hidden there)
  const opaque = r => {
    for (let e = r; e && e !== svg.parentNode; e = e.parentElement) if (parseFloat(getComputedStyle(e).opacity) < 0.99) return false;
    const cs = getComputedStyle(r);
    if (!cs.fill || cs.fill === 'none' || cs.fill.startsWith('url') || parseFloat(cs.fillOpacity) < 0.99) return false;
    const m = cs.fill.match(/rgba\([^)]*,\s*([\d.]+)\)/);
    return !(m && parseFloat(m[1]) < 0.99);
  };
  const covers = [];
  svg.querySelectorAll('rect').forEach(r => { if (shown(r) && !skip(r) && opaque(r)) { const b = bb(r); if (b) covers.push({ el: r, b }); } });

  const inside = (pt, r, d) => pt[0] > r.x0 + d && pt[0] < r.x1 - d && pt[1] > r.y0 + d && pt[1] < r.y1 - d;
  const past = (b, r) => {
    const out = [];
    if (b.x0 < r.x0 - TOL) out.push('left ' + r1(r.x0 - b.x0));
    if (b.x1 > r.x1 + TOL) out.push('right ' + r1(b.x1 - r.x1));
    if (b.y0 < r.y0 - TOL) out.push('top ' + r1(r.y0 - b.y0));
    if (b.y1 > r.y1 + TOL) out.push('bottom ' + r1(b.y1 - r.y1));
    return out;
  };
  const overlap = (a, r) => Math.min(a.x1, r.x1) - Math.max(a.x0, r.x0) > TOL && Math.min(a.y1, r.y1) - Math.max(a.y0, r.y0) > TOL;

  const res = { boxes: boxes.length, lines: lines.length, texts: texts.length, hooks,
                line_through_box: [], allowed: [], text_overflow: [], label_on_box: [], line_over_text: [],
                box_overlap: [], line_over_label: [], small_text: [], text_overlap: [], min_text_px: null, min_text: null };
  // text_overlap: two texts whose bboxes overlap by more than TOL in both directions
  for (let i = 0; i < texts.length; i++) for (let j = i + 1; j < texts.length; j++) {
    const a = texts[i].b, b = texts[j].b;
    if (!overlap(a, b)) continue;
    const ox = Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0);
    const oy = Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0);
    res.text_overlap.push({ a: texts[i].s, ab: fmt(a), b: texts[j].s, bb: fmt(b), by: r1(ox) + 'x' + r1(oy) });
  }
  // box_overlap: two solids overlap by more than TOL in both directions; a box
  // inside the group of its parent node (args.parents) is not an overlap
  for (let i = 0; i < solids.length; i++) for (let j = i + 1; j < solids.length; j++) {
    const a = solids[i], b = solids[j];
    if (!overlap(a.rect, b.rect)) continue;
    const kidOf = (k, g) => k.node && g.group && (args.parents || {})[k.node] === g.group && within(k.rect, g.rect);
    if (kidOf(a, b) || kidOf(b, a)) continue;
    const ox = Math.min(a.rect.x1, b.rect.x1) - Math.max(a.rect.x0, b.rect.x0);
    const oy = Math.min(a.rect.y1, b.rect.y1) - Math.max(a.rect.y0, b.rect.y0);
    res.box_overlap.push({ a: a.key + ' ' + fmt(a.rect), b: b.key + ' ' + fmt(b.rect), by: r1(ox) + 'x' + r1(oy) });
  }
  // small_text: rendered size below the floor (args.minPx); min_text_px: the smallest
  for (const T of texts) {
    if (!isFinite(T.px)) continue;
    if (res.min_text_px === null || T.px < res.min_text_px) { res.min_text_px = T.px; res.min_text = T.s; }
    if (T.px < args.minPx - 1e-6) res.small_text.push({ text: T.s, px: r1(T.px) });
  }
  res.small_text.sort((p, q) => p.px - q.px);
  if (res.min_text_px !== null) res.min_text_px = r1(res.min_text_px);
  // line_over_label: the line is painted above the text (later in document order),
  // a sampled point lies in the text's bbox shrunk by 1, and no opaque rect painted
  // after the line covers that point
  for (const L of lines) for (const T of texts) {
    if (T.free && ((L.line && T.line === L.line) || (L.edgeIds && T.edgeIds === L.edgeIds))) continue;
    if (!(T.el.compareDocumentPosition(L.el) & Node.DOCUMENT_POSITION_FOLLOWING)) continue;
    const later = covers.filter(c => L.el.compareDocumentPosition(c.el) & Node.DOCUMENT_POSITION_FOLLOWING);
    const hit = L.pts.find(pt => inside(pt, T.b, 1) && !later.some(c => inside(pt, c.b, 0)));
    if (hit) res.line_over_label.push({ line: L.desc, text: T.s, at: hit.map(r1).join(','), bbox: fmt(T.b) });
  }
  // line_through_box / crossings_allowed
  for (const L of lines) for (const b of boxes) {
    const hit = L.pts.find(pt => inside(pt, b.rect, SHRINK));
    if (!hit) continue;
    let allowed = L.own.has(b.key) || L.stubs.has(b.key);
    if (!allowed && b.kind === 'group') allowed = [...L.endsOn].some(k => b.group.kids.has(k));
    const rec = { line: L.desc, box: (b.kind === 'box' ? '' : b.kind + ':') + b.key, at: hit.map(r1).join(','), rect: fmt(b.rect) };
    if (b.kind === 'stub') rec.box = b.key;
    (allowed ? res.allowed : res.line_through_box).push(rec);
  }
  // text_overflow / label_on_box
  for (const T of texts) {
    if (!T.free) {
      if (!T.cont) { res.text_overflow.push({ text: T.s, container: T.ckey, why: 'container has no rect', bbox: fmt(T.b) }); continue; }
      const p = past(T.b, T.cont);
      if (p.length) res.text_overflow.push({ text: T.s, container: T.ckey + ' ' + fmt(T.cont), why: 'past ' + p.join(', '), bbox: fmt(T.b) });
      continue;
    }
    const why = [];
    if (vb) { const p = past(T.b, vb); if (p.length) why.push('past the viewBox ' + p.join(', ')); }
    const on = boxes.filter(b => overlap(T.b, b.rect)).map(b => (b.kind === 'box' ? '' : b.kind + ':') + b.key);
    if (on.length) { why.push('overlaps ' + on.join(' ')); res.label_on_box.push({ text: T.s, boxes: on.join(' '), bbox: fmt(T.b) }); }
    if (why.length) res.text_overflow.push({ text: T.s, container: 'free label', why: why.join('; '), bbox: fmt(T.b) });
  }
  // line_over_text (informational)
  for (const L of lines) for (const T of texts) {
    if (T.free && ((L.line && T.line === L.line) || (L.edgeIds && T.edgeIds === L.edgeIds))) continue;
    const hit = L.pts.find(pt => inside(pt, T.b, 1));
    if (hit) res.line_over_text.push({ line: L.desc, text: T.s, at: hit.map(r1).join(',') });
  }
  return res;
}
"""


def load_model(url, model_ref):
    """The model as a dict, from a path, a URL, or daq-model.json next to the page."""
    if model_ref and not urllib.parse.urlsplit(model_ref).scheme:
        return json.loads(Path(model_ref).read_text(encoding="utf-8"))
    model_url = model_ref or urllib.parse.urljoin(url.split("#", 1)[0], "daq-model.json")
    with urllib.request.urlopen(model_url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def parts_with_children(model):
    """Top-level part ids (model order) that have at least one child."""
    nodes = [n for n in model.get("nodes", []) if isinstance(n, dict) and "id" in n]
    known = {n["id"] for n in nodes}
    tops = [n["id"] for n in nodes if n.get("parent") not in known]
    with_kids = {n.get("parent") for n in nodes if n.get("parent") in known}
    return [t for t in tops if t in with_kids]


def first_line(exc):
    return str(exc).splitlines()[0] if str(exc) else type(exc).__name__


def click(page, locator):
    """A real click; if something else covers the element, dispatch the click on it. Returns a note or ''."""
    try:
        locator.click(timeout=3000)
        return ""
    except PlaywrightError as exc:
        locator.dispatch_event("click")
        return f"real click failed ({first_line(exc)}); dispatched a click event instead"


def measure(page, selector, parents):
    page.evaluate(SETTLE_JS)
    return page.evaluate(MEASURE_JS, {"selector": selector, "parents": parents, "minPx": MIN_TEXT_PX})


SMALL_TEXT_LISTED = 5  # small_text: the smallest texts listed per view without --verbose


def report_view(name, res, verbose, out):
    """Print the view line and its problem lines.

    Returns (X, Y, K, J, Q, O, W, S, E, boxes, min_px, min_text) or None."""
    if "error" in res:
        out.append(f"PROBLEM: view={name}: {res['error']}")
        return None
    x, y = len(res["line_through_box"]), len(res["text_overflow"])
    k, j, q = len(res["allowed"]), len(res["line_over_text"]), len(res["label_on_box"])
    o, w, s = len(res["box_overlap"]), len(res["line_over_label"]), len(res["small_text"])
    e = len(res["text_overlap"])
    min_px = res["min_text_px"]
    out.append(f"view={name} boxes={res['boxes']} lines={res['lines']} texts={res['texts']} "
               f"line_through_box={x} text_overflow={y} crossings_allowed={k} line_over_text={j} label_on_box={q} "
               f"box_overlap={o} line_over_label={w} small_text={s} text_overlap={e} "
               f"min_text_px={min_px if min_px is not None else 'none'}")
    for h in res["hooks"]:
        out.append(f"PROBLEM: view={name} hook: {h}")
    for r in res["line_through_box"]:
        out.append(f"PROBLEM: line_through_box view={name} {r['line']} box={r['box']} {r['rect']} at=({r['at']})")
    for r in res["text_overflow"]:
        out.append(f"PROBLEM: text_overflow view={name} text={r['text']!r} {r['container']} bbox={r['bbox']} {r['why']}")
    for r in res["box_overlap"]:
        out.append(f"PROBLEM: box_overlap view={name} {r['a']} and {r['b']} overlap by {r['by']}")
    for r in res["line_over_label"]:
        out.append(f"PROBLEM: line_over_label view={name} {r['line']} text={r['text']!r} bbox={r['bbox']} at=({r['at']})")
    for r in res["text_overlap"]:
        out.append(f"PROBLEM: text_overlap view={name} text={r['a']!r} bbox={r['ab']} and text={r['b']!r} bbox={r['bb']} overlap by {r['by']}")
    if s:
        listed = res["small_text"] if verbose else res["small_text"][:SMALL_TEXT_LISTED]
        more = "" if len(listed) == s else f" (+{s - len(listed)} more; --verbose lists all)"
        out.append(f"PROBLEM: small_text view={name} {s} texts below {MIN_TEXT_PX:g}px: "
                   + ", ".join(f"{r['text']!r} {r['px']}px" for r in listed) + more)
    if verbose:
        for r in res["allowed"]:
            out.append(f"INFO: crossing_allowed view={name} {r['line']} box={r['box']} at=({r['at']})")
        for r in res["line_over_text"]:
            out.append(f"INFO: line_over_text view={name} {r['line']} text={r['text']!r} at=({r['at']})")
    if res["boxes"] == 0:
        out.append(f"PROBLEM: view={name}: no boxes found; nothing to measure")
    return x, y, k, j, q, o, w, s, e, res["boxes"], min_px, res["min_text"]


def parents_of(model):
    """node id -> parent id (for box_overlap: a kid inside its own group)."""
    return {n["id"]: n.get("parent") for n in model.get("nodes", []) if isinstance(n, dict) and "id" in n}


def run_check(url, model_ref=None, width=1440, height=900, verbose=False, init_script=None, headed=False):
    """Run the check and print its report; return the exit status."""
    try:
        model = load_model(url, model_ref)
    except Exception as exc:  # noqa: BLE001 - report any load problem
        print(f"ERROR: cannot load the model ({model_ref or 'daq-model.json next to the page'}): {exc}")
        print("font=unknown")
        print("views=0 line_through_box=0 text_overflow=0")
        print("crossings_allowed=0 line_over_text=0 label_on_box=0 box_overlap=0 line_over_label=0 small_text=0 text_overlap=0 min_text_px=none")
        return 1
    parts = parts_with_children(model)
    parents = parents_of(model)
    out = []
    totals = [0] * 9
    smallest = None  # (px, view, text)
    views = 0
    empty_view = False

    def add(view, r):
        nonlocal totals, smallest, views, empty_view
        views += 1
        empty_view |= r[9] == 0
        totals = [a + b for a, b in zip(totals, r[:9])]
        if r[10] is not None and (smallest is None or r[10] < smallest[0]):
            smallest = (r[10], view, r[11])
    font_ok = False
    font_line = "font=missing"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.set_default_timeout(STEP_TIMEOUT_MS)
            errors = []
            page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
            if init_script:
                page.add_init_script(script=init_script)
            target = url.split("#", 1)[0] + "#/"
            try:
                page.goto(target)
                page.wait_for_selector("body[data-ready='true']", timeout=READY_TIMEOUT_MS)
            except PlaywrightError as exc:
                out.append(f"PROBLEM: the viewer did not become ready: {first_line(exc)}")
                page = None
            if page is not None:
                font = page.evaluate(FONT_JS)
                if not (font["check"] and font["loaded"]):
                    page.wait_for_timeout(3000)  # a late font load
                    font = page.evaluate(FONT_JS)
                font_ok = bool(font["check"] and font["loaded"])
                font_line = ("font=Archivo" if font_ok else
                             f"font=missing check={str(font['check']).lower()} archivo_faces={font['faces']} loaded={font['loaded']}")
                res = measure(page, MAP_SELECTOR, parents)
                r = report_view("map", res, verbose, out)
                if r:
                    add("map", r)
                for part in parts:
                    box = page.locator(f'{MAP_SELECTOR} g.box[data-part="{part}"]').first
                    try:
                        note = click(page, box)
                        if note:
                            out.append(f"NOTE: view=detail:{part}: {note}")
                        page.wait_for_selector(DETAIL_SELECTOR.format(part=part), state="attached")
                    except PlaywrightError as exc:
                        out.append(f"PROBLEM: view=detail:{part}: clicking its map box did not open "
                                   f"{DETAIL_SELECTOR.format(part=part)}: {first_line(exc)}")
                        continue
                    res = measure(page, DETAIL_SELECTOR.format(part=part), parents)
                    r = report_view(f"detail:{part}", res, verbose, out)
                    if r:
                        add(f"detail:{part}", r)
            for e in errors:
                out.append(f"NOTE: {e}")
        finally:
            browser.close()
    x, y, k, j, q, o, w, s, e = totals
    print(font_line)
    for line in out:
        print(line)
    if smallest is not None:
        print(f"INFO: smallest text {smallest[0]}px at width {width}: view={smallest[1]} text={smallest[2]!r}")
    print(f"views={views} line_through_box={x} text_overflow={y}")
    print(f"crossings_allowed={k} line_over_text={j} label_on_box={q} box_overlap={o} line_over_label={w} "
          f"small_text={s} text_overlap={e} min_text_px={smallest[0] if smallest is not None else 'none'}")
    ok = (font_ok and views == 1 + len(parts) and x == 0 and y == 0 and not empty_view
          and o == 0 and w == 0 and s == 0 and e == 0)
    return 0 if ok else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Geometry check of the viewer's map and detail views.")
    parser.add_argument("--url", required=True, help="viewer URL, e.g. http://127.0.0.1:8000/")
    parser.add_argument("--model", default=None, help="model JSON path or URL (default: daq-model.json next to the page)")
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--headed", action="store_true", help="show the browser window")
    parser.add_argument("--verbose", action="store_true", help="also list allowed crossings and line_over_text pairs")
    args = parser.parse_args(argv)
    url = args.url if "#" in args.url or args.url.endswith("/") or args.url.endswith(".html") else args.url + "/"
    return run_check(url, args.model, args.width, args.height, args.verbose, headed=args.headed)


if __name__ == "__main__":
    sys.exit(main())
