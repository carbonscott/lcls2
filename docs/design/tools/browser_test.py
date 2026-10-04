#!/usr/bin/env python3
"""Browser test of the design model viewer (Playwright, Chromium).

The page has five figures under the header: the map (#map-section), the tour
(#tour), the small multiples (#multiples), the sequence chart (#sequence) and
the N-squared matrix (#matrix); #/read replaces them with the one-page view.
The test reads daq-model.json next to the page and drives the page only by
clicking, as a reader would.

Full run (default) prints, in this order:
  nodes_visited=V/N tour_steps=S/T console_errors=C
  smoke stub_click=ok|fail arrow_keys=ok|fail help=ok|fail read_page=R/N third_party=Q
  map parts=A/P0 lanes=L bands=B columns=K boxes=O/Q
  detail opened=X/P
  tour steps=S/T highlighted=H/T
  multiples panels=M/6
  sequence rows=R/T
  matrix cells=C2/C
  console_errors=C
  * nodes_visited: a node counts when it is reached by clicking (its map box
    for a top-level part; for a lower node, its box (g.box) or group title
    strip (g.dgroup rect.gtitle) in the detail of its top-level part, opened
    by clicking that part's map box) AND #detail-title[data-node-id] names it
    AND the panel's visible title text equals the model title
    (whitespace-normalized) AND the visible prose (#detail-prose) contains the
    first 30 characters of the node's prose as plain text.
  * tour_steps: step k (reached with the pips and #tour-next) counts when
    #tour-step-title[data-step-index=k] shows its title, #tour-step-prose
    contains the first 30 characters of its prose as plain text, and the tour
    map shows a callout (g.callout) on the top-level part of the step's node.
  * smoke: stub_click = clicking the first neighbour tag (g.stub) of the
    detail shown on #/ opens the detail of the part it names (data-other);
    arrow_keys = with focus in the tour, Right then Left move to step 2 and
    back; help = #help-toggle opens #help, #help-close (or the toggle) closes
    it; read_page = in #/read, every node has a section[data-node-id] whose
    title (.read-title, else its first heading) is the node title;
    third_party = requests during the run to hosts other than the page's own
    origin, fonts.googleapis.com and fonts.gstatic.com.
  * map: parts = top-level parts with a map box (g.box[data-part]) out of P0
    top-level parts; lanes = distinct data-lane values of the map boxes (must
    equal map.lanes.count); bands = g.band-label groups (must equal the
    number of map.bands); columns = g.column-label groups (must equal the
    number of map.columns); the map's viewBox must be map.viewbox.
    boxes = map box copies (g.box[data-box], +[data-lane] per lane) whose
    rendered rect.b, in viewBox units with CSS transforms included, equals
    the JSON rect within 0.5 units: x, w, h from place.boxes, y from the box
    (or lanes.y[i] - h/2 for a per-lane box), out of Q = all box copies the
    JSON lists; each copy must be drawn exactly once and no other box drawn.
    A CSS shift of a map box fails here.
  * detail: a part with children counts when clicking its map box opens
    #detail-view svg.detail[data-detail=part] drawing every descendant as a
    g.box[data-node] or g.dgroup[data-node]. On #/ the detail shown must be
    map.default_detail.
  * tour highlighted: step k counts when the callout is on the step node's
    top part AND the set of .hot elements in the tour map (line ids of
    path.ln.hot, "box:<id>" of g.box.hot) equals the step's map.tour
    highlight list exactly, with every lane copy of each listed line or box
    hot, AND at least one hot element belongs to that top part (a hot box of
    the part, or a hot line drawing an edge with an end in it) AND the
    visible tokens (g.tok with opacity 1: data-t and data-target "x,y")
    equal the step's map.tour tokens (t, x, y) AND the step node is .hot in
    #tour-detail svg.detail[data-detail=<top part>].
  * multiples: panel i counts when #multiples figure i holds svg.map.mini
    with data-kind = map.multiples[i].kind and a non-empty figcaption, and
    its undimmed lines (effective opacity > 0.5) are exactly the lines of
    that kind, at least one (for "all": no line dimmed).
  * sequence: row k counts when #sequence svg .row[data-step-index=k] is
    there once, its aria-label contains step k's title, it draws one arrow
    (path.ln) whose start lies on the "from" lifeline and whose end lies on
    the "to" lifeline of step k's row in map.sequence (an end within 10
    units of a lifeline header's centre, g.hdr[data-lifeline]; no lifeline
    there = "start"), its label (text.lab) is that row's label, and clicking
    it opens tour step k.
  * matrix: C = distinct (top(from), top(to)) pairs of model edges whose
    tops differ; a cell #matrix table.nsq td[data-from][data-to] counts when
    its relation items (.ni[data-edge-ids]) show exactly those edges'
    labels, deduplicated by kind+label, and name only edges of that pair.
    Cells of other pairs must be empty; the row and column headers must
    show every part's place.short.
  * console_errors: console errors and warnings, page errors, and failed or
    HTTP-error (>= 400) requests to the page's own origin.
  Exit 0 iff every count is complete (V = N, S = T, A = P0, O = Q, X = P, H = T,
  M = 6, R = T, C2 = C), every smoke check is ok with R = N, Q = 0 and
  C = 0. A check that finds nothing to test fails.

--layout (layout checks; add --full to also run the full test):
  at 744x1000 and 1440x900 compares, on the map, each top-level part's
  union box (viewBox units), the set of rendered map text strings and the
  count of visible map elements, and prints
    layout_identical=<bool> parts=<n>
  then, at widths 400, 744 and 1440,
    width=<w> page_hscroll=<px>
  (the page's horizontal overflow in CSS px, max over: load, a detail
  opened, a tour step), after the 744 line the informational
    inner_scroll=<section:px,...> min_text_px=<px>
  (horizontal scroll inside each figure container, smallest rendered SVG
  text size), then
    fullsize map-section=ok|fail tour=ok|fail sequence=ok|fail
  and finally console_errors=C. fullsize: at 744x1000, each section has one
  button.fullsize with aria-pressed="false" on load and its figure (#map
  svg.map, #tour svg.map, #sequence svg) fitted: no horizontal scroll in the
  sheet and the svg no wider than the sheet's content box; pressing it sets
  aria-pressed="true", the svg's width equals its viewBox width (1 px), the
  sheet scrolls and the page does not; pressing it again fits it again.
  Fails if the layouts differ, any page_hscroll > 0, the map sheet of
  #map-section or of #tour scrolls horizontally at 744 (on load), a
  fullsize check fails, html, body or any element around a section sets
  overflow-x hidden or clip, or C > 0.

--check-node ID --expect-title TEXT --expect-prose SUBSTRING
  opens #/node/ID and also reaches the node by clicking (map box, then its
  box or group in the detail); checks the panel title and that the rendered
  prose contains SUBSTRING (visible text, whitespace-normalized).
  Prints:  check_node id=ID title_ok=<bool> prose_ok=<bool> console_errors=C
--check-edge ID
  an edge inside one part: a path.ln[data-edge-ids~=ID] in that part's
  detail; an edge between parts with a lower-level end: the neighbour tag
  (g.stub[data-edge-ids~=ID], data-other = the other part, data-dir in/out)
  in the detail of each part whose end is a lower node; an edge between two
  top-level parts: a map line (path.ln[data-edge-ids~=ID]) or a matrix
  relation (.ni[data-edge-ids~=ID] in the cell of the pair).
  Prints:  check_edge id=ID drawn=<bool> console_errors=C
--full adds the full run to --check-node, --check-edge or --layout.

Usage:
  python docs/design/tools/browser_test.py --url http://127.0.0.1:8000/
      [--headed] [--screenshot-dir DIR] [--full] [--layout]
      [--check-node ID --expect-title TEXT --expect-prose SUBSTRING]
      [--check-edge ID]

Needs the playwright package and a Chromium browser
(python -m playwright install chromium).
"""

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

READY_TIMEOUT_MS = 30000
STEP_TIMEOUT_MS = 5000
MAX_PRINTED_PROBLEMS = 40
MAX_DRILL_FAILURES = 12  # stop the drill test early when the viewer is clearly broken
PROSE_PREFIX = 30  # characters of a node's or tour step's prose that must be visible
FONT_HOSTS = {"fonts.googleapis.com", "fonts.gstatic.com"}
MAP = "#map svg.map"
TOUR_MAP = "#tour svg.map"
DETAIL = '#detail-view svg.detail[data-detail="{}"]'
TOUR_DETAIL = '#tour-detail svg.detail[data-detail="{}"]'
SECTIONS = ("map-section", "tour", "multiples", "sequence", "matrix")


def normalize(text):
    return re.sub(r"\s+", " ", text or "").strip()


def plain_text(text, titles):
    """Prose markup reduced to the text the viewer shows."""
    text = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text or "")
    text = re.sub(r"\[\[([^\]|]+)\]\]", lambda m: titles.get(m.group(1).strip(), m.group(0)), text)
    text = re.sub(r"\[([^\]]+)\]\(([^()\s]+)\)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return normalize(text)


def first_line(exc):
    return str(exc).splitlines()[0] if str(exc) else type(exc).__name__


# ---------------------------------------------------------------------------
# The model, as the test needs it
# ---------------------------------------------------------------------------

class Model:
    def __init__(self, data):
        self.data = data
        self.nodes = [n for n in data.get("nodes", []) if isinstance(n, dict) and "id" in n]
        self.node = {n["id"]: n for n in self.nodes}
        self.ids = [n["id"] for n in self.nodes]
        self.parent = {n["id"]: (n.get("parent") if n.get("parent") in self.node else None) for n in self.nodes}
        self.tops = [i for i in self.ids if self.parent[i] is None]
        self.children = {}
        for i in self.ids:
            if self.parent[i] is not None:
                self.children.setdefault(self.parent[i], []).append(i)
        self.parts_with_children = [t for t in self.tops if self.children.get(t)]
        self.titles = {i: self.node[i].get("title", "") for i in self.ids}
        self.edges = [e for e in data.get("edges", []) if isinstance(e, dict)
                      and e.get("from") in self.node and e.get("to") in self.node]
        self.edge = {e.get("id"): e for e in self.edges}
        self.steps = data.get("tour", {}).get("steps", []) if isinstance(data.get("tour"), dict) else []
        self.map = data.get("map") if isinstance(data.get("map"), dict) else {}

    def top(self, node_id):
        seen = set()
        while self.parent.get(node_id) is not None and node_id not in seen:
            seen.add(node_id)
            node_id = self.parent[node_id]
        return node_id

    def descendants(self, node_id):
        out = []
        for c in self.children.get(node_id, []):
            out.append(c)
            out.extend(self.descendants(c))
        return out

    def short(self, part):
        return ((self.node.get(part) or {}).get("place") or {}).get("short")

    def tour_entry(self, step):
        for t in self.map.get("tour", []) or []:
            if isinstance(t, dict) and t.get("step") == step.get("id"):
                return t
        return None

    def cross_pairs(self):
        """(top(from), top(to)) -> edges, for edges whose tops differ."""
        pairs = {}
        for e in self.edges:
            a, b = self.top(e["from"]), self.top(e["to"])
            if a != b:
                pairs.setdefault((a, b), []).append(e)
        return pairs


def load_model(url):
    model_url = urllib.parse.urljoin(url.split("#", 1)[0], "daq-model.json")
    with urllib.request.urlopen(model_url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# One browser page plus the problems seen on it
# ---------------------------------------------------------------------------

class Session:
    def __init__(self, browser, url, screenshot_dir, viewport=None):
        self.url = url
        parts = urllib.parse.urlsplit(url)
        self.origin = f"{parts.scheme}://{parts.netloc}"
        self.page = browser.new_page(viewport=viewport or {"width": 1280, "height": 800})
        self.page.set_default_timeout(STEP_TIMEOUT_MS)
        self.console_problems = []
        self.failures = []
        self.notes = []
        self.third_party = []
        self.broken = False
        self.screenshot_dir = Path(screenshot_dir) if screenshot_dir else None
        self.page.on("console", self._on_console)
        self.page.on("pageerror", lambda exc: self.console_problems.append(f"pageerror: {exc}"))
        self.page.on("requestfailed", self._on_request_failed)
        self.page.on("response", self._on_response)
        self.page.on("request", self._on_request)

    def _same_origin(self, url):
        return url.startswith(self.origin + "/") or url == self.origin

    def _on_console(self, msg):
        if msg.type in ("error", "warning"):
            self.console_problems.append(f"console {msg.type}: {msg.text}")

    def _on_request(self, request):
        u = urllib.parse.urlsplit(request.url)
        if u.scheme in ("data", "blob", "about", "chrome-extension"):
            return
        if not self._same_origin(request.url) and u.hostname not in FONT_HOSTS:
            if request.url not in self.third_party:
                self.third_party.append(request.url)

    def _on_request_failed(self, request):
        if self._same_origin(request.url):
            self.console_problems.append(f"request failed: {request.url} ({request.failure})")

    def _on_response(self, response):
        if self._same_origin(response.url) and response.status >= 400:
            self.console_problems.append(f"HTTP {response.status}: {response.url}")

    def fail(self, text):
        self.failures.append(text)

    def open(self, fragment="#/"):
        """Load the page afresh at #fragment and wait until it is ready (False, recorded, if never)."""
        if self.broken:
            return False
        target = self.url.split("#", 1)[0] + fragment
        try:
            self.page.goto("about:blank")  # so that a hash-only change is a full load
            self.page.goto(target)
            self.page.wait_for_selector("body[data-ready='true']", timeout=READY_TIMEOUT_MS)
            return True
        except PlaywrightError as exc:
            self.fail(f"open {fragment}: the viewer did not become ready: {first_line(exc)}")
            self.broken = True
            return False

    def click(self, locator, what):
        """Click like a reader; if another element covers the target, try a corner, then dispatch."""
        try:
            locator.click(timeout=2000)
            return True
        except PlaywrightError as exc:
            first = first_line(exc)
        try:
            locator.click(position={"x": 6, "y": 6}, timeout=1500)
            self.notes.append(f"{what}: the centre is covered ({first}); clicked near its top-left corner")
            return True
        except PlaywrightError:
            pass
        try:
            locator.dispatch_event("click")
            self.notes.append(f"{what}: no visible point could be clicked ({first}); dispatched a click event")
            return True
        except PlaywrightError as exc:
            self.fail(f"{what}: cannot click: {first_line(exc)}")
            return False

    def panel_node(self):
        return self.page.evaluate(
            "() => { const t = document.querySelector('#detail-title'); return t ? t.dataset.nodeId : null; }")

    def wait_panel(self, node_id):
        try:
            self.page.wait_for_function(
                "(id) => { const t = document.querySelector('#detail-title'); return !!t && t.dataset.nodeId === id; }",
                arg=node_id, timeout=STEP_TIMEOUT_MS)
            return True
        except PlaywrightError:
            return False

    def wait_detail(self, part, selector=DETAIL):
        try:
            self.page.wait_for_selector(selector.format(part), state="attached", timeout=STEP_TIMEOUT_MS)
            return True
        except PlaywrightError:
            return False

    def shown_text(self, selector):
        loc = self.page.locator(selector)
        try:
            if loc.count() == 1 and loc.is_visible():
                return normalize(loc.inner_text())
        except PlaywrightError:
            pass
        return ""

    def screenshot(self, name):
        if self.screenshot_dir:
            self.screenshot_dir.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(self.screenshot_dir / name))

    def settle(self, ms=450):
        """Let CSS transitions (opacity .25-.6 s) finish."""
        self.page.wait_for_timeout(ms)


def map_box(part):
    return f'{MAP} g.box[data-part="{part}"]'


def open_part(s, part):
    """Click the part's map box (its own box first) and wait for its detail. True if it opened."""
    own = s.page.locator(f'{map_box(part)}[data-node="{part}"]')
    loc = own.first if own.count() else s.page.locator(map_box(part)).first
    if s.page.locator(map_box(part)).count() == 0:
        s.fail(f"no map box for part {part} ({map_box(part)})")
        return False
    if not s.click(loc, f"map box of {part}"):
        return False
    return s.wait_detail(part)


def click_in_detail(s, part, node_id):
    """Click node_id's box, or its group's title strip, in the detail of part."""
    d = DETAIL.format(part)
    box = s.page.locator(f'{d} g.box[data-node="{node_id}"]')
    if box.count():
        return s.click(box.first, f"detail box of {node_id}")
    grp = s.page.locator(f'{d} g.dgroup[data-node="{node_id}"]')
    if grp.count():
        strip = grp.first.locator("rect.gtitle")
        return s.click(strip.first if strip.count() else grp.first, f"group title strip of {node_id}")
    s.fail(f"the detail of {part} draws no g.box or g.dgroup for {node_id}")
    return False


# ---------------------------------------------------------------------------
# Full test
# ---------------------------------------------------------------------------

def check_panel(s, m, node_id, how):
    """True if the panel shows node_id: title equal to the model title, prose with its first characters."""
    if not s.wait_panel(node_id):
        s.fail(f"{how}: {node_id}: #detail-title names {s.panel_node()!r}")
        return False
    shown = s.shown_text("#detail-title")
    if shown != normalize(m.titles.get(node_id, "")):
        s.fail(f"{how}: {node_id}: the panel title reads {shown!r}, expected {m.titles.get(node_id)!r}")
        return False
    want = plain_text(m.node[node_id].get("prose", ""), m.titles)[:PROSE_PREFIX].strip()
    prose = s.shown_text("#detail-prose")
    if not want or want not in prose:
        s.fail(f"{how}: {node_id}: the visible prose (#detail-prose) does not contain {want!r}")
        return False
    return True


def drill_test(s, m):
    visited = set()
    if not s.open("#/"):
        return 0, len(m.ids)
    s.screenshot("root.png")
    for part in m.tops:
        if len([f for f in s.failures if f.startswith("drill")]) >= MAX_DRILL_FAILURES:
            s.fail(f"drill: stopped after {MAX_DRILL_FAILURES} failures")
            break
        own = s.page.locator(f'{map_box(part)}[data-node="{part}"]')
        loc = own.first if own.count() else s.page.locator(map_box(part)).first
        if s.page.locator(map_box(part)).count() == 0:
            s.fail(f"drill: no map box for {part}")
            continue
        if not s.click(loc, f"drill: map box of {part}"):
            continue
        if check_panel(s, m, part, "drill"):
            visited.add(part)
        if not m.children.get(part):
            continue
        if not s.wait_detail(part):
            s.fail(f"drill: clicking the map box of {part} did not open {DETAIL.format(part)}")
            continue
        for node_id in m.descendants(part):
            if click_in_detail(s, part, node_id) and check_panel(s, m, node_id, "drill"):
                visited.add(node_id)
            if not s.wait_detail(part):  # the detail must stay on this part
                s.fail(f"drill: after clicking {node_id} the detail of {part} is gone")
                if not open_part(s, part):
                    break
    return len(visited), len(m.ids)


TOUR_STATE_JS = r"""
(args) => {
  const svg = document.querySelector(args.map);
  if (!svg) return { error: 'no tour map ' + args.map };
  const eff = el => { let o = 1; for (let e = el; e && e !== svg.parentNode; e = e.parentElement) o *= +getComputedStyle(e).opacity; return o; };
  const lines = {}, boxes = {}, unknown = [];
  svg.querySelectorAll('path.ln').forEach(p => {
    const id = p.dataset.line;
    if (!id) { if (p.classList.contains('hot')) unknown.push('path.ln.hot without data-line'); return; }
    (lines[id] = lines[id] || []).push({ hot: p.classList.contains('hot'), edges: (p.dataset.edgeIds || '').split(/\s+/).filter(Boolean) });
  });
  svg.querySelectorAll('g.box').forEach(g => {
    const id = g.dataset.box;
    if (!id) { if (g.classList.contains('hot')) unknown.push('g.box.hot without data-box'); return; }
    (boxes[id] = boxes[id] || []).push({ hot: g.classList.contains('hot'), part: g.dataset.part });
  });
  const callouts = [...svg.querySelectorAll('g.callout')].filter(c => getComputedStyle(c).display !== 'none' && eff(c) > 0.5).map(c => c.dataset.part || '');
  const toks = [...svg.querySelectorAll('g.tok')].map(t => ({ t: t.dataset.t, target: t.dataset.target, op: eff(t) }));
  const fading = toks.some(t => t.op > 0.01 && t.op < 0.99);
  return { lines, boxes, unknown, callouts, toks, fading };
}
"""


def tour_test(s, m):
    """Return (steps shown S, highlighted H, T)."""
    steps = m.steps
    shown_ok = highlighted = 0
    if not s.open("#/"):
        return 0, 0, len(steps)
    pips = s.page.locator("#pips button.pip")
    if pips.count() != len(steps):
        s.fail(f"tour: {pips.count()} pips (#pips button.pip) for {len(steps)} steps")
    if pips.count() and not s.click(pips.first, "tour: pip 1"):
        return 0, 0, len(steps)
    for k, step in enumerate(steps, 1):
        title = s.page.locator(f'#tour-step-title[data-step-index="{k}"]')
        try:
            title.wait_for(state="visible")
            shown = normalize(title.inner_text())
        except PlaywrightError:
            s.fail(f"tour: step {k} title (#tour-step-title[data-step-index={k}]) did not appear")
            shown = None
        ok = shown == normalize(step.get("title", ""))
        if shown is not None and not ok:
            s.fail(f"tour: step {k} title is {shown!r}, expected {step.get('title')!r}")
        want = plain_text(step.get("prose", ""), m.titles)[:PROSE_PREFIX].strip()
        prose = s.shown_text("#tour-step-prose")
        if not want or want not in prose:
            s.fail(f"tour: step {k}: the visible step text does not contain {want!r}")
            ok = False
        top = m.top(step.get("node"))
        s.settle(700)
        state = s.page.evaluate(TOUR_STATE_JS, {"map": TOUR_MAP})
        if "error" in state:
            s.fail(f"tour: step {k}: {state['error']}")
            ok = False
            state = None
        if state is not None and state["fading"]:
            s.page.wait_for_timeout(600)
            state = s.page.evaluate(TOUR_STATE_JS, {"map": TOUR_MAP})
        callout_ok = state is not None and top in state["callouts"]
        if state is not None and not callout_ok:
            s.fail(f"tour: step {k}: no callout (g.callout[data-part={top}]) on the tour map; callouts: {state['callouts']}")
        ok = ok and callout_ok
        if ok:
            shown_ok += 1
        if state is not None and callout_ok and highlight_ok(s, m, k, step, top, state):
            highlighted += 1
        if k == 1:
            s.screenshot("tour-step-1.png")
        if k < len(steps):
            try:
                s.page.locator("#tour-next").click()
            except PlaywrightError as exc:
                s.fail(f"tour: cannot click #tour-next at step {k}: {first_line(exc)}")
                break
    return shown_ok, highlighted, len(steps)


def highlight_ok(s, m, k, step, top, state):
    entry = m.tour_entry(step)
    if entry is None:
        s.fail(f"tour: step {k}: the model has no map.tour entry for step {step.get('id')!r}")
        return False
    good = True
    want = set(entry.get("highlight", []) or [])
    hot, partial = set(), []
    for lid, copies in state["lines"].items():
        if any(c["hot"] for c in copies):
            hot.add(lid)
            if not all(c["hot"] for c in copies):
                partial.append(lid)
    for bid, copies in state["boxes"].items():
        if any(c["hot"] for c in copies):
            hot.add("box:" + bid)
            if not all(c["hot"] for c in copies):
                partial.append("box:" + bid)
    if state["unknown"]:
        s.fail(f"tour: step {k}: hot elements without an id: {sorted(set(state['unknown']))}")
        good = False
    if hot != want:
        s.fail(f"tour: step {k}: hot set {sorted(hot)} != highlight {sorted(want)} "
               f"(extra {sorted(hot - want)}, missing {sorted(want - hot)})")
        good = False
    if partial:
        s.fail(f"tour: step {k}: only some lane copies are hot: {sorted(partial)}")
        good = False
    mine = any(c["hot"] and c["part"] == top for copies in state["boxes"].values() for c in copies)
    for copies in state["lines"].values():
        for c in copies:
            if c["hot"] and any(top in (m.top(m.edge[e]["from"]), m.top(m.edge[e]["to"]))
                                for e in c["edges"] if e in m.edge):
                mine = True
    if not mine:
        s.fail(f"tour: step {k}: no hot box or line belongs to {top}")
        good = False
    shown = sorted((t["t"], *[round(float(v), 1) for v in (t["target"] or "nan,nan").split(",")[:2]])
                   for t in state["toks"] if t["op"] >= 0.99)
    expect = sorted((t.get("t"), round(float(t.get("x", "nan")), 1), round(float(t.get("y", "nan")), 1))
                    for t in entry.get("tokens", []) or [] if isinstance(t, dict))
    if len(shown) != len(expect) or any(a[0] != b[0] or abs(a[1] - b[1]) > 0.51 or abs(a[2] - b[2]) > 0.51
                                        for a, b in zip(shown, expect)):
        s.fail(f"tour: step {k}: visible tokens {shown} != map.tour tokens {expect}")
        good = False
    node = step.get("node")
    if node != top:
        sel = TOUR_DETAIL.format(top)
        n = s.page.locator(f'{sel} g.box.hot[data-node="{node}"], {sel} g.dgroup.hot[data-node="{node}"]').count()
        if n < 1:
            s.fail(f"tour: step {k}: {node} is not .hot in {sel}")
            good = False
    elif s.page.locator(TOUR_DETAIL.format(top)).count() != 1:
        s.fail(f"tour: step {k}: {TOUR_DETAIL.format(top)} is not shown")
        good = False
    return good


# ---------------------------------------------------------------------------
# Smoke checks of the reader controls
# ---------------------------------------------------------------------------

def smoke_test(s, m):
    result = {}

    def attempt(name, func):
        try:
            result[name] = func()
        except (PlaywrightError, AssertionError) as exc:
            s.fail(f"smoke {name}: {first_line(exc)}")
            result[name] = "fail"

    def stub_click():
        if not s.open("#/"):
            return "fail"
        stubs = s.page.locator("#detail-view svg.detail g.stub[data-other]")
        if stubs.count() == 0:
            s.fail("smoke stub_click: the detail shown on #/ has no neighbour tag (g.stub[data-other])")
            return "fail"
        other = stubs.first.get_attribute("data-other")
        if not s.click(stubs.first, f"smoke stub_click: tag to {other}"):
            return "fail"
        if not s.wait_detail(other):
            s.fail(f"smoke stub_click: clicking the tag of {other} did not open {DETAIL.format(other)}")
            return "fail"
        return "ok"

    def arrow_keys():
        if len(m.steps) < 2:
            s.fail(f"smoke arrow_keys: the tour has {len(m.steps)} step(s); at least 2 are needed")
            return "fail"
        if not s.open("#/tour/1"):
            return "fail"
        s.page.wait_for_selector('#tour-step-title[data-step-index="1"]')
        s.page.locator("#tour-next").focus()
        s.page.keyboard.press("ArrowRight")
        s.page.wait_for_selector('#tour-step-title[data-step-index="2"]')
        s.page.keyboard.press("ArrowLeft")
        s.page.wait_for_selector('#tour-step-title[data-step-index="1"]')
        return "ok"

    def help_panel():
        if not s.open("#/"):
            return "fail"
        s.page.locator("#help-toggle").click()
        s.page.wait_for_selector("#help", state="visible")
        close = s.page.locator("#help-close")
        if close.count() and close.first.is_visible():
            close.first.click()
        else:
            s.page.locator("#help-toggle").click()
        s.page.wait_for_selector("#help", state="hidden")
        return "ok"

    if not s.open("#/"):
        return {"stub_click": "fail", "arrow_keys": "fail", "help": "fail", "read_page": (0, len(m.ids))}
    attempt("stub_click", stub_click)
    attempt("arrow_keys", arrow_keys)
    attempt("help", help_panel)

    shown = 0
    try:
        if s.open("#/read"):
            s.page.wait_for_function("() => document.body.dataset.mode === 'read'")
            titles = s.page.evaluate(r"""() => {
              const out = {};
              document.querySelectorAll('#read-page section[data-node-id]').forEach(sec => {
                const t = sec.querySelector(':scope > .read-title') || sec.querySelector('.read-title') ||
                          sec.querySelector('h1, h2, h3, h4, h5, h6');
                (out[sec.dataset.nodeId] = out[sec.dataset.nodeId] || []).push(t ? t.innerText : null);
              });
              return out;
            }""")
            for n in m.nodes:
                got = titles.get(n["id"], [])
                if len(got) == 1 and normalize(got[0]) == normalize(n.get("title", "")):
                    shown += 1
                else:
                    s.fail(f"smoke read_page: the one-page view does not show the title of {n['id']} (found {got})")
    except PlaywrightError as exc:
        s.fail(f"smoke read_page: {first_line(exc)}")
    result["read_page"] = (shown, len(m.ids))
    return result


def smoke_line(result, third_party):
    shown, total = result.get("read_page", (0, 0))
    return (f"smoke stub_click={result.get('stub_click', 'fail')} arrow_keys={result.get('arrow_keys', 'fail')} "
            f"help={result.get('help', 'fail')} read_page={shown}/{total} third_party={third_party}")


def smoke_ok(result):
    shown, total = result.get("read_page", (0, 0))
    return all(result.get(k) == "ok" for k in ("stub_click", "arrow_keys", "help")) and total > 0 and shown == total


# ---------------------------------------------------------------------------
# Map, detail, multiples, sequence, matrix
# ---------------------------------------------------------------------------

BOX_RECT_TOLERANCE = 0.5  # viewBox units between a map box's rendered rect and its JSON rect

MAP_INFO_JS = r"""(sel) => {
  const svg = document.querySelector(sel);
  if (!svg) return null;
  const parts = new Set(), lanes = new Set();
  svg.querySelectorAll('g.box[data-part]').forEach(g => { parts.add(g.dataset.part); if (g.dataset.lane != null && g.dataset.lane !== '') lanes.add(g.dataset.lane); });
  const bands = new Set([...svg.querySelectorAll('g.band-label[data-band]')].map(g => g.dataset.band));
  const cols = new Set([...svg.querySelectorAll('g.column-label[data-column]')].map(g => g.dataset.column));
  const transformed = [...svg.querySelectorAll('g.box[transform], g.box [transform], path.ln[transform], text.lab[transform]')].length;
  // each map box's rendered rect in viewBox units (CSS transforms included)
  const inv = svg.getScreenCTM().inverse();
  const rects = [...svg.querySelectorAll('g.box[data-box]')].map(g => {
    const r = g.querySelector('rect.b') || g.querySelector('rect');
    const lane = g.dataset.lane != null && g.dataset.lane !== '' ? g.dataset.lane : null;
    const key = g.dataset.box + (lane !== null ? '@' + lane : '');
    if (!r) return { key, rect: null };
    const mm = inv.multiply(r.getScreenCTM()), b = r.getBBox();
    const p = [[b.x, b.y], [b.x + b.width, b.y], [b.x, b.y + b.height], [b.x + b.width, b.y + b.height]]
      .map(([x, y]) => [mm.a * x + mm.c * y + mm.e, mm.b * x + mm.d * y + mm.f]);
    const x0 = Math.min(...p.map(q => q[0])), y0 = Math.min(...p.map(q => q[1]));
    return { key, rect: [x0, y0, Math.max(...p.map(q => q[0])) - x0, Math.max(...p.map(q => q[1])) - y0] };
  });
  return { parts: [...parts], lanes: lanes.size, bands: bands.size, nbandgroups: svg.querySelectorAll('g.band-label').length,
           columns: cols.size, viewBox: svg.getAttribute('viewBox'), transformed, rects };
}"""


def expected_box_rects(m):
    """box key (id, or id@lane for a per-lane box) -> (x, y, w, h) from the JSON."""
    lane_ys = (m.map.get("lanes") or {}).get("y") or []
    out = {}
    for part in m.tops:
        for box in ((m.node[part].get("place") or {}).get("boxes") or []):
            if not isinstance(box, dict) or not isinstance(box.get("id"), str):
                continue
            x, w, h = box.get("x"), box.get("w"), box.get("h")
            if box.get("per_lane"):
                for lane, ly in enumerate(lane_ys):
                    out[f"{box['id']}@{lane}"] = (x, ly - h / 2, w, h)
            else:
                out[box["id"]] = (x, box.get("y"), w, h)
    return out


def map_test(s, m):
    """Return (parts A, P0, lanes, bands, columns, boxes matching M, boxes Q, ok)."""
    want_rects = expected_box_rects(m)
    if not s.open("#/"):
        return 0, len(m.tops), 0, 0, 0, 0, len(want_rects), False
    info = s.page.evaluate(MAP_INFO_JS, MAP)
    if info is None:
        s.fail(f"map: no {MAP}")
        return 0, len(m.tops), 0, 0, 0, 0, len(want_rects), False
    # every map box's rendered rect equals its JSON rect (x, y, w, h; per-lane y from lanes.y)
    drawn = {}
    for r in info["rects"]:
        drawn.setdefault(r["key"], []).append(r["rect"])
    matching = 0
    rect_ok = True
    for key, want in want_rects.items():
        got = drawn.get(key, [])
        if len(got) != 1 or got[0] is None:
            s.fail(f"map: box {key} is drawn {len(got)} times (g.box[data-box][data-lane] with rect.b), expected once")
            rect_ok = False
            continue
        if any(not isinstance(v, (int, float)) for v in want) or \
                any(abs(a - b) > BOX_RECT_TOLERANCE for a, b in zip(got[0], want)):
            s.fail(f"map: box {key} rendered at x,y,w,h=({','.join(f'{v:.1f}' for v in got[0])}), "
                   f"the JSON gives ({','.join(str(v) for v in want)})")
            rect_ok = False
            continue
        matching += 1
    extra = sorted(k for k in drawn if k not in want_rects)
    if extra:
        s.fail(f"map: boxes drawn that the JSON does not list: {extra}")
        rect_ok = False
    ok = True
    a = len([p for p in m.tops if p in info["parts"]])
    missing = [p for p in m.tops if p not in info["parts"]]
    if missing:
        s.fail(f"map: no map box for parts {missing}")
        ok = False
    want_lanes = (m.map.get("lanes") or {}).get("count")
    if info["lanes"] != want_lanes:
        s.fail(f"map: {info['lanes']} lanes drawn, map.lanes.count is {want_lanes}")
        ok = False
    want_bands = len(m.map.get("bands") or [])
    if info["bands"] != want_bands or info["nbandgroups"] != want_bands:
        s.fail(f"map: {info['nbandgroups']} g.band-label groups ({info['bands']} distinct), {want_bands} map.bands")
        ok = False
    want_cols = len(m.map.get("columns") or [])
    if info["columns"] != want_cols:
        s.fail(f"map: {info['columns']} g.column-label groups, {want_cols} map.columns")
        ok = False
    vb = m.map.get("viewbox") or {}
    want_vb = f"0 0 {vb.get('w')} {vb.get('h')}"
    if normalize((info["viewBox"] or "").replace(",", " ")) != want_vb:
        s.fail(f"map: viewBox is {info['viewBox']!r}, map.viewbox gives {want_vb!r}")
        ok = False
    if info["transformed"]:
        s.fail(f"map: {info['transformed']} boxes, lines or labels carry a transform attribute")
        ok = False
    return a, len(m.tops), info["lanes"], info["bands"], info["columns"], matching, len(want_rects), ok and rect_ok


def detail_test(s, m):
    """Return (opened X, P, default_ok)."""
    if not s.open("#/"):
        return 0, len(m.parts_with_children), False
    default = m.map.get("default_detail")
    default_ok = s.wait_detail(default) if default else False
    if not default_ok:
        s.fail(f"detail: on #/ the detail shown is not map.default_detail {default!r} ({DETAIL.format(default)})")
    opened = 0
    for part in m.parts_with_children:
        if not open_part(s, part):
            s.fail(f"detail: clicking the map box of {part} did not open {DETAIL.format(part)}")
            continue
        drawn = s.page.evaluate(r"""(sel) => {
          const svg = document.querySelector(sel);
          return svg ? [...svg.querySelectorAll('g.box[data-node], g.dgroup[data-node]')].map(g => g.dataset.node) : [];
        }""", DETAIL.format(part))
        missing = [d for d in m.descendants(part) if d not in drawn]
        if missing:
            s.fail(f"detail: the detail of {part} does not draw {missing}")
        else:
            opened += 1
    return opened, len(m.parts_with_children), default_ok


MULTIPLES_JS = r"""
() => [...document.querySelectorAll('#multiples figure')].map(f => {
  const svg = f.querySelector('svg.map.mini[data-kind]');
  const cap = f.querySelector('figcaption');
  if (!svg) return { kind: null, caption: cap ? cap.innerText : '' };
  const eff = el => { let o = 1; for (let e = el; e && e !== f; e = e.parentElement) o *= +getComputedStyle(e).opacity; return o; };
  const lines = [...svg.querySelectorAll('path.ln')].filter(p => getComputedStyle(p).display !== 'none')
    .map(p => ({ kind: p.dataset.kind || null, lit: eff(p) > 0.5, id: p.dataset.line || '' }));
  return { kind: svg.dataset.kind, caption: cap ? cap.innerText : '', lines };
})
"""


def multiples_test(s, m):
    want = [x.get("kind") for x in (m.map.get("multiples") or []) if isinstance(x, dict)]
    total = len(want) or 6
    if not s.open("#/"):
        return 0, total
    s.page.locator("#multiples").scroll_into_view_if_needed()
    s.settle(500)
    figs = s.page.evaluate(MULTIPLES_JS)
    if len(figs) != total:
        s.fail(f"multiples: {len(figs)} figures in #multiples, {total} in map.multiples")
    good = 0
    for i, kind in enumerate(want):
        if i >= len(figs):
            break
        f = figs[i]
        if f["kind"] != kind:
            s.fail(f"multiples: figure {i + 1} shows kind {f['kind']!r}, map.multiples gives {kind!r}")
            continue
        if not normalize(f["caption"]):
            s.fail(f"multiples: figure {i + 1} ({kind}) has no figcaption text")
            continue
        lines = f["lines"]
        untagged = [ln for ln in lines if not ln["kind"]]
        lit = [ln for ln in lines if ln["lit"]]
        if untagged:
            s.fail(f"multiples: {kind}: {len(untagged)} lines without data-kind")
            continue
        if kind == "all":
            bad = [ln["id"] or ln["kind"] for ln in lines if not ln["lit"]]
            if bad or not lines:
                s.fail(f"multiples: all: dimmed lines {bad}" if bad else "multiples: all: no lines")
                continue
        else:
            wrong = sorted({ln["id"] or ln["kind"] for ln in lit if ln["kind"] != kind})
            dark = sorted({ln["id"] for ln in lines if ln["kind"] == kind and not ln["lit"]})
            if wrong or dark or not any(ln["kind"] == kind for ln in lit):
                s.fail(f"multiples: {kind}: undimmed lines of other kinds {wrong}, dimmed lines of this kind {dark}, "
                       f"undimmed of this kind {sum(1 for ln in lit if ln['kind'] == kind)}")
                continue
        good += 1
    return good, total


LIFELINE_TOLERANCE = 10  # viewBox units between a row arrow's end and a lifeline header's centre

# The drawn arrow of sequence row k: which lifeline (g.hdr[data-lifeline]) its
# start and end lie on, and the text of its label (text.lab).
SEQ_ROW_JS = r"""
([k, tol]) => {
  const svg = document.querySelector('#sequence svg');
  const row = svg && svg.querySelector('.row[data-step-index="' + k + '"]');
  if (!row) return null;
  const inv = svg.getScreenCTM().inverse();
  const at = (el, x, y) => { const mm = inv.multiply(el.getScreenCTM()); return [mm.a * x + mm.c * y + mm.e, mm.b * x + mm.d * y + mm.f]; };
  const heads = [...svg.querySelectorAll('g.hdr[data-lifeline]')].map(g => {
    const r = g.querySelector('rect'); const b = r.getBBox();
    return { id: g.dataset.lifeline, x: at(r, b.x + b.width / 2, b.y)[0] };
  });
  const near = x => { let best = null; heads.forEach(h => { const d = Math.abs(h.x - x); if (d <= tol && (!best || d < best.d)) best = { id: h.id, d }; }); return best ? best.id : 'start'; };
  const paths = [...row.querySelectorAll('path.ln')];
  if (paths.length !== 1) return { paths: paths.length };
  const p = paths[0], L = p.getTotalLength();
  const a = p.getPointAtLength(0), b = p.getPointAtLength(L);
  const p0 = at(p, a.x, a.y), p1 = at(p, b.x, b.y);
  const labels = [...row.querySelectorAll('text.lab')].map(t => t.textContent.replace(/\s+/g, ' ').trim());
  return { paths: 1, from: near(p0[0]), to: near(p1[0]), x0: Math.round(p0[0]), x1: Math.round(p1[0]), labels,
           heads: heads.map(h => h.id + '@' + Math.round(h.x)).join(' ') };
}
"""


def sequence_row_problem(s, k, want):
    """None if row k draws want's from -> to arrow with want's label, else the problem."""
    got = s.page.evaluate(SEQ_ROW_JS, [k, LIFELINE_TOLERANCE])
    if got is None:
        return "no row"
    if got["paths"] != 1:
        return f"{got['paths']} arrows (path.ln) in the row, expected 1"
    want_from = want.get("from") if want.get("from") in {l.get("id") for l in want["_lifelines"]} else "start"
    problems = []
    if got["from"] != want_from or got["to"] != want.get("to"):
        problems.append(f"arrow runs from {got['from']} (x={got['x0']}) to {got['to']} (x={got['x1']}), "
                        f"map.sequence gives {want.get('from')} -> {want.get('to')} (lifelines {got['heads']})")
    if got["labels"] != [normalize(want.get("label", ""))]:
        problems.append(f"label {got['labels']} is not map.sequence's {want.get('label')!r}")
    return "; ".join(problems) or None


def sequence_test(s, m):
    if not s.open("#/"):
        return 0, len(m.steps)
    seq = m.map.get("sequence") or {}
    lifelines = [x for x in (seq.get("lifelines") or []) if isinstance(x, dict)]
    rows_by_step = {r.get("step"): dict(r, _lifelines=lifelines) for r in (seq.get("rows") or []) if isinstance(r, dict)}
    good = 0
    for k, step in enumerate(m.steps, 1):
        rows = s.page.locator(f'#sequence svg .row[data-step-index="{k}"]')
        if rows.count() != 1:
            s.fail(f"sequence: {rows.count()} rows with data-step-index={k}")
            continue
        label = normalize(rows.first.get_attribute("aria-label"))
        if normalize(step.get("title", "")) not in label:
            s.fail(f"sequence: row {k} aria-label {label!r} does not contain the step title")
            continue
        want = rows_by_step.get(step.get("id"))
        if want is None:
            s.fail(f"sequence: map.sequence has no row for step {k} ({step.get('id')})")
            continue
        problem = sequence_row_problem(s, k, want)
        if problem:
            s.fail(f"sequence: row {k}: {problem}")
            continue
        if not s.click(rows.first, f"sequence row {k}"):
            continue
        try:
            s.page.wait_for_selector(f'#tour-step-title[data-step-index="{k}"]')
        except PlaywrightError:
            s.fail(f"sequence: clicking row {k} did not open tour step {k}")
            continue
        if s.shown_text(f'#tour-step-title[data-step-index="{k}"]') != normalize(step.get("title", "")):
            s.fail(f"sequence: clicking row {k} shows another title")
            continue
        good += 1
    extra = s.page.locator("#sequence svg .row[data-step-index]").count() - len(m.steps)
    if extra > 0:
        s.fail(f"sequence: {extra} more rows than tour steps")
        good = min(good, len(m.steps) - 1)
    return good, len(m.steps)


MATRIX_JS = r"""
() => {
  const t = document.querySelector('#matrix table.nsq');
  if (!t) return null;
  const cells = [...t.querySelectorAll('td[data-from][data-to]')].map(td => ({
    from: td.dataset.from, to: td.dataset.to,
    items: [...td.querySelectorAll('.ni')].map(ni => ({ text: ni.innerText, ids: (ni.dataset.edgeIds || '').split(/\s+/).filter(Boolean) })) }));
  const headRow = t.querySelector('thead tr') || t.querySelector('tr');
  const heads = headRow ? [...headRow.children].map(c => c.textContent) : [];
  const rowheads = [...t.querySelectorAll('tbody tr')].map(tr => (tr.firstElementChild || {}).textContent || '');
  return { cells, heads, rowheads };
}
"""


def matrix_test(s, m):
    pairs = m.cross_pairs()
    if not s.open("#/"):
        return 0, len(pairs), False
    info = s.page.evaluate(MATRIX_JS)
    if info is None:
        s.fail("matrix: no #matrix table.nsq")
        return 0, len(pairs), False
    ok = True
    cells = {}
    for c in info["cells"]:
        if (c["from"], c["to"]) in cells:
            s.fail(f"matrix: two cells for {c['from']} -> {c['to']}")
            ok = False
        cells[(c["from"], c["to"])] = c["items"]
    good = 0
    for (a, b), edges in sorted(pairs.items()):
        seen, want = set(), []
        for e in edges:
            if (e.get("kind"), e.get("label")) not in seen:
                seen.add((e.get("kind"), e.get("label")))
                want.append(normalize(e.get("label")))
        items = cells.get((a, b))
        if items is None:
            s.fail(f"matrix: no cell td[data-from={a}][data-to={b}]")
            continue
        got = [normalize(i["text"]) for i in items]
        ids = {e["id"] for e in edges}
        foreign = sorted({x for i in items for x in i["ids"] if x not in ids})
        bare = [normalize(i["text"]) for i in items if not i["ids"]]
        if sorted(got) != sorted(want) or foreign or bare:
            s.fail(f"matrix: {a} -> {b}: shows {got}, expected {want}"
                   + (f"; names edges of other pairs {foreign}" if foreign else "")
                   + (f"; items without data-edge-ids {bare}" if bare else ""))
            continue
        good += 1
    for (a, b), items in cells.items():
        if (a, b) not in pairs and items:
            s.fail(f"matrix: {a} -> {b} has no edges in the model but lists {[normalize(i['text']) for i in items]}")
            ok = False
    heads = [normalize(h) for h in info["heads"]]
    rowheads = [normalize(h) for h in info["rowheads"]]
    for part in m.tops:
        short = m.short(part)
        if not short:
            s.fail(f"matrix: part {part} has no place.short in the model")
            ok = False
        elif short not in heads or short not in rowheads:
            s.fail(f"matrix: the headers do not show place.short {short!r} of {part}")
            ok = False
    return good, len(pairs), ok


# ---------------------------------------------------------------------------
# --layout
# ---------------------------------------------------------------------------

LAYOUT_JS = r"""
(sel) => {
  const svg = document.querySelector(sel);
  if (!svg) return null;
  const inv = svg.getScreenCTM().inverse();
  const bb = el => {
    const m = inv.multiply(el.getScreenCTM()), b = el.getBBox();
    const p = [[b.x, b.y], [b.x + b.width, b.y], [b.x, b.y + b.height], [b.x + b.width, b.y + b.height]]
      .map(([x, y]) => [m.a * x + m.c * y + m.e, m.b * x + m.d * y + m.f]);
    return [Math.min(...p.map(q => q[0])), Math.min(...p.map(q => q[1])), Math.max(...p.map(q => q[0])), Math.max(...p.map(q => q[1]))];
  };
  const shown = el => { for (let e = el; e && e !== svg.parentNode; e = e.parentElement) { const cs = getComputedStyle(e);
    if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return false; } return true; };
  const parts = {};
  svg.querySelectorAll('g.box[data-part]').forEach(g => {
    if (!shown(g)) return;
    const r = bb(g.querySelector('rect.b') || g.querySelector('rect') || g);
    const u = parts[g.dataset.part];
    parts[g.dataset.part] = u ? [Math.min(u[0], r[0]), Math.min(u[1], r[1]), Math.max(u[2], r[2]), Math.max(u[3], r[3])] : r;
  });
  Object.keys(parts).forEach(k => { parts[k] = parts[k].map(v => Math.round(v * 10) / 10); });
  const texts = new Set();
  svg.querySelectorAll('text').forEach(t => {
    if (!shown(t)) return;
    const sp = t.querySelectorAll('tspan');
    const s = (sp.length ? [...sp].map(x => x.textContent).join(' ') : t.textContent).replace(/\s+/g, ' ').trim();
    if (s) texts.add(s);
  });
  let visible = 0;
  svg.querySelectorAll('path, rect, circle, line, text, polyline, polygon, ellipse, use, image').forEach(e => {
    if (e.closest('defs, marker') || !shown(e)) return;
    let b; try { b = e.getBBox(); } catch (x) { return; }
    if (b.width > 0 || b.height > 0) visible++;
  });
  return { parts, texts: [...texts].sort(), visible };
}
"""

FONTS_READY_JS = "async () => { await document.fonts.ready; return true; }"

HSCROLL_JS = r"""
() => {
  const d = document.documentElement;
  return Math.max(d.scrollWidth, document.body ? document.body.scrollWidth : 0) - d.clientWidth;
}
"""

OVERFLOW_JS = r"""
(ids) => {
  const bad = [], seen = new Set();
  const check = el => {
    if (!el || seen.has(el)) return; seen.add(el);
    const v = getComputedStyle(el).overflowX;
    if (v === 'hidden' || v === 'clip') bad.push((el.id ? '#' + el.id : el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).join('.') : '')) + ' overflow-x:' + v);
  };
  check(document.documentElement); check(document.body);
  ids.forEach(id => { for (let e = document.getElementById(id); e; e = e.parentElement) check(e); });
  return bad;
}
"""

INNER_JS = r"""
() => {
  const out = [], count = {};
  let minPx = Infinity, minWhere = '';
  document.querySelectorAll('section[id] *').forEach(el => {
    const cs = getComputedStyle(el);
    if ((cs.overflowX === 'auto' || cs.overflowX === 'scroll') && el.scrollWidth - el.clientWidth > 0) {
      const sec = el.closest('section[id]').id;
      count[sec] = (count[sec] || 0) + 1;
      out.push(sec + (count[sec] > 1 ? '.' + count[sec] : '') + ':' + (el.scrollWidth - el.clientWidth));
    }
  });
  document.querySelectorAll('section[id] svg text').forEach(t => {
    const r = t.getBoundingClientRect();
    if (!r.width || getComputedStyle(t).display === 'none') return;
    const m = t.getScreenCTM(); if (!m) return;
    const px = parseFloat(getComputedStyle(t).fontSize) * Math.hypot(m.a, m.b);
    if (px < minPx) { minPx = px; minWhere = t.closest('section[id]').id + ': ' + (t.textContent || '').trim().slice(0, 40); }
  });
  return { inner: out, minPx: isFinite(minPx) ? Math.round(minPx * 10) / 10 : null, minWhere };
}
"""


# Sections with a "Full size" toggle (button.fullsize[aria-pressed]) and the figure it sizes.
FULLSIZE = (("map-section", "#map svg.map"), ("tour", "#tour svg.map"), ("sequence", "#sequence svg"))
# The figures that must fit (no inner horizontal scroll) at 744 when no toggle is pressed.
MUST_FIT_744 = (("map-section", "#map svg.map"), ("tour", "#tour svg.map"))

# The svg's rendered width, its viewBox width, and the horizontal scroll of every
# scroll container between it and its section (the sheet).
SHEET_JS = r"""
(sel) => {
  const svg = document.querySelector(sel);
  if (!svg) return null;
  const vb = svg.viewBox && svg.viewBox.baseVal;
  const scrolls = [];
  let room = null;
  for (let e = svg.parentElement; e && e.tagName !== 'SECTION'; e = e.parentElement) {
    const cs = getComputedStyle(e);
    if (room === null) room = e.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    if (cs.overflowX === 'auto' || cs.overflowX === 'scroll')
      scrolls.push({ el: (e.id ? '#' + e.id : e.tagName.toLowerCase() + '.' + (e.className || '').toString().trim().split(/\s+/).join('.')), px: e.scrollWidth - e.clientWidth });
  }
  const d = document.documentElement;
  return { width: Math.round(svg.getBoundingClientRect().width * 10) / 10, vbw: vb ? vb.width : null, room: room === null ? null : Math.round(room * 10) / 10,
           scroll: Math.max(0, ...scrolls.map(x => x.px)), scrolls: scrolls.map(x => x.el + ':' + x.px).join(','),
           page: Math.max(d.scrollWidth, document.body ? document.body.scrollWidth : 0) - d.clientWidth };
}
"""


def fullsize_test(browser, url, screenshot_dir):
    """At 744x1000: each section's Full size toggle. Return ({section: 'ok'|'fail'}, problems)."""
    result, problems = {}, []
    s = Session(browser, url, screenshot_dir, {"width": 744, "height": 1000})
    if not s.open("#/"):
        return {sec: "fail" for sec, _ in FULLSIZE}, [f"fullsize: {x}" for x in s.failures]
    s.page.evaluate(FONTS_READY_JS)
    s.settle(300)

    def fitted(sec, sel, when):
        g = s.page.evaluate(SHEET_JS, sel)
        if g is None:
            return [f"fullsize {sec}: no {sel}"]
        out = []
        if g["scroll"] > 0:
            out.append(f"fullsize {sec} {when}: the sheet scrolls by {g['scroll']} px ({g['scrolls']}), expected fitted")
        if g["room"] is not None and g["width"] > g["room"] + 1:
            out.append(f"fullsize {sec} {when}: the svg is {g['width']} px wide, the sheet has {g['room']} px")
        return out

    for sec, sel in FULLSIZE:
        btn = s.page.locator(f"#{sec} button.fullsize")
        bad = []
        if btn.count() != 1:
            bad.append(f"fullsize {sec}: {btn.count()} buttons #{sec} button.fullsize, expected 1")
        elif btn.get_attribute("aria-pressed") != "false":
            bad.append(f"fullsize {sec}: aria-pressed is {btn.get_attribute('aria-pressed')!r} on load, expected 'false'")
        else:
            bad += fitted(sec, sel, "on load")
            btn.scroll_into_view_if_needed()
            if s.click(btn, f"#{sec} button.fullsize"):
                s.settle(300)
                g = s.page.evaluate(SHEET_JS, sel)
                if btn.get_attribute("aria-pressed") != "true":
                    bad.append(f"fullsize {sec}: after a click aria-pressed is {btn.get_attribute('aria-pressed')!r}, expected 'true'")
                if g is None:
                    bad.append(f"fullsize {sec}: no {sel} when pressed")
                else:
                    if g["vbw"] is None or abs(g["width"] - g["vbw"]) > 1:
                        bad.append(f"fullsize {sec} pressed: the svg is {g['width']} px wide, its viewBox {g['vbw']} units")
                    if g["scroll"] <= 0:
                        bad.append(f"fullsize {sec} pressed: the sheet does not scroll ({g['scrolls'] or 'no scroll container'})")
                    if g["page"] > 0:
                        bad.append(f"fullsize {sec} pressed: the page scrolls horizontally by {g['page']} px")
                s.screenshot(f"fullsize-{sec}.png")
                if s.click(btn, f"#{sec} button.fullsize (again)"):
                    s.settle(300)
                    if btn.get_attribute("aria-pressed") != "false":
                        bad.append(f"fullsize {sec}: after a second click aria-pressed is {btn.get_attribute('aria-pressed')!r}")
                    bad += fitted(sec, sel, "unpressed again")
        result[sec] = "fail" if bad else "ok"
        problems += bad
    problems += [f"fullsize: {x}" for x in s.failures + s.console_problems]
    s.page.close()
    return result, problems


def layout_test(browser, url, screenshot_dir, m):
    """Run the --layout checks; return (lines to print, ok, console problems)."""
    out, ok, problems = [], True, []
    snaps = {}
    for w, h in ((744, 1000), (1440, 900)):
        s = Session(browser, url, screenshot_dir, {"width": w, "height": h})
        if s.open("#/"):
            s.page.evaluate(FONTS_READY_JS)
            s.settle(300)
            snaps[w] = s.page.evaluate(LAYOUT_JS, MAP)
            if snaps[w] is None:
                s.fail(f"layout: no {MAP} at {w}x{h}")
        problems += [f"layout {w}x{h}: {x}" for x in s.failures + s.console_problems]
        s.page.close()
    a, b = snaps.get(744), snaps.get(1440)
    identical = bool(a and b)
    nparts = 0
    if a and b:
        common = sorted(set(a["parts"]) & set(b["parts"]))
        nparts = len(common)
        for p in sorted(set(a["parts"]) | set(b["parts"])):
            ra, rb = a["parts"].get(p), b["parts"].get(p)
            if ra is None or rb is None or any(abs(x - y) > 0.5 for x, y in zip(ra, rb)):
                problems.append(f"layout: part {p} union box 744: {ra} 1440: {rb}")
                identical = False
        if a["texts"] != b["texts"]:
            only_a = sorted(set(a["texts"]) - set(b["texts"]))
            only_b = sorted(set(b["texts"]) - set(a["texts"]))
            problems.append(f"layout: map texts differ; only at 744: {only_a[:10]}; only at 1440: {only_b[:10]}")
            identical = False
        if a["visible"] != b["visible"]:
            problems.append(f"layout: visible map elements 744: {a['visible']}, 1440: {b['visible']}")
            identical = False
    out.append(f"layout_identical={str(identical).lower()} parts={nparts}")
    if not identical or nparts != len(m.tops):
        ok = False
    default = m.map.get("default_detail")
    other = next((p for p in m.parts_with_children if p != default), None)
    for w, h in ((400, 900), (744, 1000), (1440, 900)):
        s = Session(browser, url, screenshot_dir, {"width": w, "height": h})
        worst, extra = None, None
        if s.open("#/"):
            s.page.evaluate(FONTS_READY_JS)
            s.settle(300)
            worst = s.page.evaluate(HSCROLL_JS)
            bad = s.page.evaluate(OVERFLOW_JS, list(SECTIONS))
            if bad:
                problems.append(f"layout {w}: overflow-x hidden/clip on {bad}")
                ok = False
            if w == 744:
                extra = s.page.evaluate(INNER_JS)
                for sec, sel in MUST_FIT_744:
                    g = s.page.evaluate(SHEET_JS, sel)
                    if g is None:
                        problems.append(f"layout 744: no {sel} in #{sec}")
                        ok = False
                    elif g["scroll"] > 0:
                        problems.append(f"layout 744: the map sheet of #{sec} scrolls horizontally by {g['scroll']} px "
                                        f"({g['scrolls']}); it must fit")
                        ok = False
            s.screenshot(f"layout-{w}.png")
            if other and open_part(s, other):
                s.settle(300)
                worst = max(worst, s.page.evaluate(HSCROLL_JS))
            else:
                s.fail(f"could not open the detail of {other}")
            try:
                s.page.locator("#tour-next").click()
                s.page.wait_for_selector('#tour-step-title[data-step-index="2"]')
                s.settle(300)
                worst = max(worst, s.page.evaluate(HSCROLL_JS))
            except PlaywrightError as exc:
                s.fail(f"could not move to tour step 2: {first_line(exc)}")
        out.append(f"width={w} page_hscroll={worst if worst is not None else 'unknown'}")
        if worst is None or worst > 0:
            ok = False
        if extra is not None:
            out.append(f"inner_scroll={','.join(extra['inner']) or 'none'} min_text_px={extra['minPx']}")
            problems.append(f"INFO min_text_px at 744 is {extra['minPx']} ({extra['minWhere']})")
        if s.failures:
            ok = False
        problems += [f"layout {w}: {x}" for x in s.failures]
        problems += [f"layout {w}: {x}" for x in s.console_problems]
        s.page.close()
    sizes, size_problems = fullsize_test(browser, url, screenshot_dir)
    out.append("fullsize " + " ".join(f"{sec}={state}" for sec, state in sizes.items()))
    if any(state != "ok" for state in sizes.values()):
        ok = False
    problems += size_problems
    return out, ok, problems


# ---------------------------------------------------------------------------
# Check one node / one edge
# ---------------------------------------------------------------------------

def check_node(s, m, node_id, expect_title, expect_prose):
    title_ok = prose_ok = True
    if node_id not in m.node:
        s.fail(f"check-node: {node_id!r} is not a node of the model")
        return False, False

    def check_here(how):
        nonlocal title_ok, prose_ok
        if not s.wait_panel(node_id):
            s.fail(f"check-node ({how}): #detail-title names {s.panel_node()!r}, expected {node_id!r}")
            title_ok = prose_ok = False
            return
        shown_title = s.shown_text("#detail-title")
        if shown_title != normalize(expect_title):
            s.fail(f"check-node ({how}): title is {shown_title!r}, expected {expect_title!r}")
            title_ok = False
        if normalize(expect_prose) not in s.shown_text("#detail-prose"):
            s.fail(f"check-node ({how}): prose does not contain {expect_prose!r}")
            prose_ok = False

    # 1. deep link
    if not s.open(f"#/node/{node_id}"):
        return False, False
    check_here("deep link")
    # 2. clicking: the map box of the top part, then the node in its detail
    if not s.open("#/"):
        return False, False
    top = m.top(node_id)
    if node_id == top:
        own = s.page.locator(f'{map_box(top)}[data-node="{top}"]')
        loc = own.first if own.count() else s.page.locator(map_box(top)).first
        if not s.click(loc, f"check-node: map box of {top}"):
            return False, prose_ok
    else:
        if not open_part(s, top):
            s.fail(f"check-node: clicking the map box of {top} did not open its detail")
            return False, prose_ok
        if not click_in_detail(s, top, node_id):
            return False, prose_ok
    check_here("click")
    return title_ok, prose_ok


def check_edge(s, m, edge_id):
    edge = m.edge.get(edge_id)
    if edge is None:
        s.fail(f"check-edge: {edge_id!r} is not an edge of the model between two nodes")
        return False
    a, b = m.top(edge["from"]), m.top(edge["to"])
    sel_id = f'[data-edge-ids~="{edge_id}"]'
    if a == b:
        if a in (edge["from"], edge["to"]):
            s.fail(f"check-edge: {edge_id} connects the part {a} with its own descendant; the viewer does not draw it")
            return False
        if not s.open("#/") or not open_part(s, a):
            s.fail(f"check-edge: cannot open the detail of {a}")
            return False
        if s.page.locator(f"{DETAIL.format(a)} path.ln{sel_id}").count() < 1:
            s.fail(f"check-edge: no path.ln{sel_id} in the detail of {a}")
            return False
        return True
    lower = [(end, part, other, d) for end, part, other, d in
             ((edge["from"], a, b, "out"), (edge["to"], b, a, "in")) if end != part]
    if not lower:
        if not s.open("#/"):
            return False
        on_map = s.page.locator(f"{MAP} path.ln{sel_id}").count()
        in_cell = s.page.locator(f'#matrix td[data-from="{a}"][data-to="{b}"] .ni{sel_id}').count()
        if not (on_map or in_cell):
            s.fail(f"check-edge: {edge_id} ({a} -> {b}) is neither a map line ({MAP} path.ln{sel_id}) "
                   f"nor a matrix relation")
            return False
        return True
    drawn = True
    for end, part, other, d in lower:
        if not s.open("#/") or not open_part(s, part):
            s.fail(f"check-edge: cannot open the detail of {part}")
            return False
        tag = f'{DETAIL.format(part)} g.stub[data-other="{other}"][data-dir="{d}"]{sel_id}'
        if s.page.locator(tag).count() != 1:
            s.fail(f"check-edge: in the detail of {part}, no single tag {tag}")
            drawn = False
    return drawn


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def print_problems(s, extra=()):
    lines = s.failures + list(extra) + s.console_problems
    for line in lines[:MAX_PRINTED_PROBLEMS]:
        print(f"PROBLEM: {line}")
    if len(lines) > MAX_PRINTED_PROBLEMS:
        print(f"PROBLEM: ... and {len(lines) - MAX_PRINTED_PROBLEMS} more")
    for line in s.notes[:MAX_PRINTED_PROBLEMS]:
        print(f"NOTE: {line}")


def full_run(browser, url, screenshot_dir, m):
    s = Session(browser, url, screenshot_dir)
    visited, total = drill_test(s, m)
    steps_ok, highlighted, steps = tour_test(s, m)
    smoke = smoke_test(s, m)
    parts, top_total, lanes, bands, columns, box_rects, box_total, map_ok = map_test(s, m)
    opened, with_kids, default_ok = detail_test(s, m)
    panels, panel_total = multiples_test(s, m)
    rows, row_total = sequence_test(s, m)
    cells, cell_total, matrix_ok = matrix_test(s, m)
    errors = len(s.console_problems)
    print_problems(s, [f"third-party request: {u}" for u in s.third_party])
    print(f"nodes_visited={visited}/{total} tour_steps={steps_ok}/{steps} console_errors={errors}")
    print(smoke_line(smoke, len(s.third_party)))
    print(f"map parts={parts}/{top_total} lanes={lanes} bands={bands} columns={columns} boxes={box_rects}/{box_total}")
    print(f"detail opened={opened}/{with_kids}")
    print(f"tour steps={steps_ok}/{steps} highlighted={highlighted}/{steps}")
    print(f"multiples panels={panels}/{panel_total}")
    print(f"sequence rows={rows}/{row_total}")
    print(f"matrix cells={cells}/{cell_total}")
    print(f"console_errors={errors}")
    ok = (total > 0 and steps > 0 and visited == total and steps_ok == steps and errors == 0
          and smoke_ok(smoke) and not s.third_party
          and map_ok and parts == top_total and top_total > 0 and box_rects == box_total and box_total > 0
          and default_ok and opened == with_kids and with_kids > 0
          and highlighted == steps
          and panels == panel_total and panel_total == 6
          and rows == row_total
          and matrix_ok and cells == cell_total and cell_total > 0)
    s.page.close()
    return ok


def main(argv=None):
    parser = argparse.ArgumentParser(description="Browser test of the design model viewer.")
    parser.add_argument("--url", required=True, help="viewer URL, e.g. http://127.0.0.1:8000/")
    parser.add_argument("--headed", action="store_true", help="show the browser window")
    parser.add_argument("--screenshot-dir", default=None)
    parser.add_argument("--check-node", default=None, metavar="ID")
    parser.add_argument("--expect-title", default=None)
    parser.add_argument("--expect-prose", default=None)
    parser.add_argument("--check-edge", default=None, metavar="ID")
    parser.add_argument("--layout", action="store_true", help="run the layout checks (widths, hscroll)")
    parser.add_argument("--full", action="store_true",
                        help="with --check-node, --check-edge or --layout: also run the full test")
    args = parser.parse_args(argv)
    if args.check_node and (args.expect_title is None or args.expect_prose is None):
        parser.error("--check-node needs --expect-title and --expect-prose")

    url = args.url if "#" in args.url or args.url.endswith("/") or args.url.endswith(".html") else args.url + "/"
    try:
        m = Model(load_model(url))
    except Exception as exc:  # noqa: BLE001 - report any load problem
        print(f"ERROR: cannot fetch daq-model.json next to {url}: {exc}")
        print("nodes_visited=0/0 tour_steps=0/0 console_errors=0")
        print(smoke_line({}, 0))
        return 1

    exit_code = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        try:
            if args.check_node:
                s = Session(browser, url, args.screenshot_dir)
                title_ok, prose_ok = check_node(s, m, args.check_node, args.expect_title, args.expect_prose)
                errors = len(s.console_problems)
                print_problems(s)
                print(f"check_node id={args.check_node} title_ok={str(title_ok).lower()} "
                      f"prose_ok={str(prose_ok).lower()} console_errors={errors}")
                if not (title_ok and prose_ok and errors == 0):
                    exit_code = 1
                s.page.close()
            if args.check_edge:
                s = Session(browser, url, args.screenshot_dir)
                drawn = check_edge(s, m, args.check_edge)
                errors = len(s.console_problems)
                print_problems(s)
                print(f"check_edge id={args.check_edge} drawn={str(drawn).lower()} console_errors={errors}")
                if not (drawn and errors == 0):
                    exit_code = 1
                s.page.close()
            if args.layout:
                out, ok, problems = layout_test(browser, url, args.screenshot_dir, m)
                errors = [x for x in problems if "console " in x or "pageerror" in x or "HTTP " in x
                          or "request failed" in x]
                for line in problems[:MAX_PRINTED_PROBLEMS]:
                    print(f"PROBLEM: {line}" if not line.startswith("INFO") else f"NOTE: {line[5:]}")
                for line in out:
                    print(line)
                print(f"console_errors={len(errors)}")
                if not ok or errors:
                    exit_code = 1
            if not (args.check_node or args.check_edge or args.layout) or args.full:
                if not full_run(browser, url, args.screenshot_dir, m):
                    exit_code = 1
        finally:
            browser.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
