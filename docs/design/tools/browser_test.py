#!/usr/bin/env python3
"""Browser test of the design model viewer (Playwright, Chromium).

The page is one map with three modes ("Explore the parts", "Follow one
event", "Compare kinds") and one card under it, then the N-squared matrix as
a reference card; #/read replaces them with the one-page view. The test reads
daq-model.json next to the page and drives the page by clicks and keys, as a
reader would. Primary viewport 744x1000 (an iPad held upright); the page is
loaded afresh for each check group, so that one failure does not cascade.

Full run (default): PROBLEM: and NOTE: lines, then, in this order:
  nodes_visited=V/N tour_steps=S/T console_errors=C
  smoke stub_click=ok arrow_keys=ok help=ok read_page=R/N third_party=Q arrow_scope=ok
  map_first viewport=744x1000 map_top=A map_bottom=B frame_top=F above_map=<names>
  map_first viewport=1440x900 map_top=A map_bottom=B frame_top=F above_map=<names>
  modes=M full_maps=F
  full_map_count explore=1 tour_map=1 tour_seq=1 compare=1 displayed=explore,tour_map   (informational)
  map parts=A/8 lanes=L bands=B columns=K boxes=O/Q
  detail opened=X/P
  tour steps=S/T highlighted=H/T on_main_map=G/T tag_clear=K/T
  tour_card text=X/T detail=Y/T
  tour_fit viewport=744x1000 tourbar_bottom=Y1 step_title_bottom=Y2                    (informational)
  multiples panels=M/6 mode=<compare|FAIL:...>
  sequence rows=R/T mode=<tour|FAIL:...>
  emphasize captions=K/K hidden_ok=<bool>
  card default=<overview|FAIL:...> after_close=<overview|FAIL:...> nav=X/9 sticky_head=<bool> end_footer=<bool> folded=<bool>
  card_head_px=H                                                                          (informational)
  matrix cells=C2/C hscroll=<px> sticky_head=<bool> close_buttons=<n> end_footer=<bool>
  matrix_min_text_px=P                                                                    (informational)
  deeplinks=D/4
  page_height=H
  min_tap_px=P                                                                            (informational)
  scroll_jumps=J/N viewport=744x1000 moves_page_ok=<bool> control_moved=K/N
  scroll_jumps=J/N viewport=1440x900 moves_page_ok=<bool> control_moved=K/N
  console_errors=C
  elapsed nodes=s,tour=s,...                                                              (informational)

Rules, in brief (tools/README.md has every rule in full):
  * nodes_visited: a node counts when it is reached by clicking in Explore
    mode (its map box for a top-level part; its box or group title strip in
    the detail drawing of the card, #part-card #detail-view
    svg.detail[data-detail=<part>], for a lower node) AND #detail-title
    names it AND the visible title (#detail-title, or #card-title when
    #detail-title is visually hidden) is the model title AND #detail-prose
    shows the first 30 characters of its prose. The same walk checks the
    folds of all N panels (card folded=).
  * tour_steps: in "Follow one event", step k (pips, #tour-next) counts when
    #tour-step-title[data-step-index=k] shows its title, #tour-step-prose its
    prose, and #map svg.map a callout on the step's top-level part.
  * map_first: on #/ the displayed blocks between the bottom of
    h1#model-title and the top of the map's frame (#map) are exactly
    modes,chips; at 744x1000 map_bottom <= 1000; at 1440x900 map_top <= 450.
  * modes/full_maps: 3 mode buttons that each switch body[data-mode] and
    aria-pressed; exactly one full-size map drawing in every mode and view,
    displayed in explore and the tour's map view only.
  * tour: highlighted/tag_clear as v1 on #map svg.map; on_main_map: one
    g.callout in #map svg.map, on the step's part, visible tokens only there,
    no other full-size map drawing. tour_card: the step card shows the step
    (title, prose, the step node's title and summary, button.open-part) and
    #tour-detail svg.detail[data-detail=<part>] with the step node .hot, below
    the map frame.
  * multiples/sequence: v1 rules plus where they are displayed (mode=).
  * emphasize: each kind's chip shows its caption in #kind-caption and dims
    the other kinds' lines; All, tour and compare hide the caption.
  * card: overview on #/ and after Close, prev/next order, sticky head,
    "End of ..." footers, folds.
  * matrix: cells, no horizontal scroll at 744, sticky head, no buttons,
    footer.  deeplinks: #/node/<id>, #/tour/3, #/compare, #/read land in
    view.  page_height <= 4000 at 744x1000.  scroll_jumps: no in-page click
    or key moves window.scrollY (J = 0, N >= 40, moves_page_ok).
Exit 0 iff every check passes (complete counts, every bool true, the
thresholds above, Q = 0, C = 0). A check that finds nothing to test fails.

Options:
  --only GROUP[,GROUP]  run only these check groups (nodes, tour, smoke,
      map_first, modes, map, detail, multiples, sequence, emphasize, card,
      matrix, deeplinks, page_height, scroll_jumps; aliases full_maps=modes,
      after_close=card, close_buttons=matrix, tour_card=tour); prints only
      their lines (same formats) and console_errors=C; exit 0 iff they pass.
  --layout  layout checks (see tools/README.md):
      layout_identical=<bool> parts=<n>
      width=<w> page_hscroll=<px>          (400, 744, 1440)
      inner_scroll=<section:px,...> min_text_px=<px>   (informational, after 744)
      fullsize map=ok|fail sequence=ok|fail
      console_errors=C
  --check-node ID --expect-title TEXT --expect-prose SUBSTRING
      check_node id=ID title_ok=<bool> prose_ok=<bool> in_detail=<bool> console_errors=C
  --check-edge ID
      check_edge id=ID drawn=<bool> console_errors=C
  --full adds the full run to --check-node, --check-edge or --layout.

Usage:
  python docs/design/tools/browser_test.py --url http://127.0.0.1:8000/
      [--headed] [--screenshot-dir DIR] [--full] [--layout] [--only GROUPS]
      [--check-node ID --expect-title TEXT --expect-prose SUBSTRING]
      [--check-edge ID]

Needs the playwright package and a Chromium browser
(python -m playwright install chromium).
"""

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

READY_TIMEOUT_MS = 30000
STEP_TIMEOUT_MS = 5000
MAX_PRINTED_PROBLEMS = 60
MAX_DRILL_FAILURES = 12  # stop the node walk early when the viewer is clearly broken
PROSE_PREFIX = 30  # characters of a prose field that must be visible
FONT_HOSTS = {"fonts.googleapis.com", "fonts.gstatic.com"}
PRIMARY = (744, 1000)
WIDE = (1440, 900)
MAP = "#map svg.map"
DETAIL = '#part-card #detail-view svg.detail[data-detail="{}"]'
TOUR_DETAIL = '#step-card #tour-detail svg.detail[data-detail="{}"]'
SEQ = "#seq svg.seq"
MULT = "#mult figure"
MODE_BUTTON = '#modes button.mode[data-mode="{}"]'
VIEW_BUTTON = '#tour-controls button.view[data-view="{}"]'
MODES = ("explore", "tour", "compare")
MAP_BOTTOM_MAX_744 = 1000
MAP_TOP_MAX_1440 = 450
PAGE_HEIGHT_MAX = 4000
SCROLL_JUMPS_MIN = 40
STICKY_OFFSET = 300  # the card top is put this far above the viewport for the sticky checks
HEAD_TOLERANCE = 2
DEEPLINK_HEAD_MAX = 120
GROUPS = ("nodes", "tour", "smoke", "map_first", "modes", "map", "detail", "multiples", "sequence",
          "emphasize", "card", "matrix", "deeplinks", "page_height", "scroll_jumps")
ALIASES = {"full_maps": "modes", "after_close": "card", "close_buttons": "matrix", "tour_card": "tour",
           "nodes_visited": "nodes", "emphasize_captions": "emphasize", "min_tap_px": "page_height"}


def normalize(text):
    return re.sub(r"\s+", " ", text or "").strip()


def plain_text(text, titles):
    """Prose markup reduced to the text the viewer shows."""
    text = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text or "")
    text = re.sub(r"\[\[([^\]|]+)\]\]", lambda m: titles.get(m.group(1).strip(), m.group(0)), text)
    text = re.sub(r"\[([^\]]+)\]\(([^()\s]+)\)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    return normalize(text)


def first_line(exc):
    return str(exc).splitlines()[0] if str(exc) else type(exc).__name__


def b(value):
    return "true" if value else "false"


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

    def depth(self, node_id):
        d, seen = 0, set()
        while self.parent.get(node_id) is not None and node_id not in seen:
            seen.add(node_id)
            node_id = self.parent[node_id]
            d += 1
        return d

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
            a, b_ = self.top(e["from"]), self.top(e["to"])
            if a != b_:
                pairs.setdefault((a, b_), []).append(e)
        return pairs

    def crossing_edges(self, node_id):
        """Edges with exactly one end in the node's subtree (its flows)."""
        inside = {node_id, *self.descendants(node_id)}
        return [e for e in self.edges if (e["from"] in inside) != (e["to"] in inside)]

    def expected_folds(self, node_id):
        n = self.node[node_id]
        want = set()
        if isinstance(n.get("decisions"), list) and n["decisions"]:
            want.add("decisions")
        if isinstance(n.get("code_refs"), list) and n["code_refs"]:
            want.add("code")
        if isinstance(n.get("sources"), list) and n["sources"]:
            want.add("sources")
        if self.crossing_edges(node_id):
            want.add("flows")
        if isinstance(n.get("dev_notes"), str) and n["dev_notes"].strip():
            want.add("dev")
        return want

    def kinds_with_caption(self):
        """map.kinds ids whose map.multiples entry has a caption, with that caption."""
        caps = {x.get("kind"): x.get("caption") for x in (self.map.get("multiples") or []) if isinstance(x, dict)}
        out = []
        for k in self.map.get("kinds") or []:
            kid = k.get("id") if isinstance(k, dict) else k
            if isinstance(caps.get(kid), str) and caps[kid].strip():
                out.append((kid, caps[kid]))
        return out


def load_model(url):
    model_url = urllib.parse.urljoin(url.split("#", 1)[0], "daq-model.json")
    with urllib.request.urlopen(model_url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# JavaScript helpers (shared prelude)
# ---------------------------------------------------------------------------

PRELUDE = r"""
const shown = (el) => {
  if (!el || !el.isConnected) return false;
  const r = el.getBoundingClientRect();
  if (!(r.width > 0 && r.height > 0)) return false;
  for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
    const cs = getComputedStyle(e);
    if (cs.display === 'none' || parseFloat(cs.opacity) === 0) return false;
  }
  return getComputedStyle(el).visibility !== 'hidden';
};
const desc = (el) => {
  if (!el || el.nodeType !== 1) return 'none';
  if (el.id) return '#' + el.id;
  const cls = typeof el.className === 'string' ? el.className : ((el.className && el.className.baseVal) || '');
  let s = el.tagName.toLowerCase() + (cls.trim() ? '.' + cls.trim().split(/\s+/).join('.') : '');
  for (const a of ['data-kind', 'data-node', 'data-part', 'data-other', 'data-dir', 'data-step-index', 'data-mode', 'data-view', 'data-fold', 'href'])
    if (el.hasAttribute(a)) s += '[' + a + '=' + el.getAttribute(a) + ']';
  const host = el.parentElement && el.parentElement.closest('[id]');
  return host ? s + ' in #' + host.id : s;
};
"""


def js(body, params="args"):
    """A function expression with the prelude in scope."""
    return f"({params}) => {{ {PRELUDE}\n{body}\n}}"


SETTLE_JS = """async () => {
  try { await document.fonts.ready; } catch (e) { /* no fonts API */ }
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  return true;
}"""
RAF2_JS = "async () => { await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); return true; }"
JUMP_SETTLE_JS = """async () => {
  await new Promise(r => setTimeout(r, 400));
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  return true;
}"""
SHOWN_JS = js("return shown(document.querySelector(args));")
COUNT_SHOWN_JS = js("return [...document.querySelectorAll(args)].filter(shown).length;")
SCROLL_TO_JS = "(y) => { window.scrollTo({ top: y, behavior: 'instant' }); return window.scrollY; }"


# ---------------------------------------------------------------------------
# One browser page plus the problems seen on it
# ---------------------------------------------------------------------------

class Session:
    def __init__(self, browser, url, screenshot_dir, viewport=PRIMARY):
        self.url = url
        parts = urllib.parse.urlsplit(url)
        self.origin = f"{parts.scheme}://{parts.netloc}"
        self.viewport = tuple(viewport)
        self.page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
        self.page.set_default_timeout(STEP_TIMEOUT_MS)
        self.console_problems = []
        self.failures = []
        self.notes = []
        self.third_party = []
        self.broken = False
        self.model_parts_with_children = []  # parts whose card has a detail drawing
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

    def note(self, text):
        self.notes.append(text)

    def set_viewport(self, size):
        size = tuple(size)
        if size != self.viewport:
            self.page.set_viewport_size({"width": size[0], "height": size[1]})
            self.viewport = size

    def open(self, fragment="#/"):
        """Load the page afresh at #fragment and wait until it is ready (False, recorded, if never)."""
        if self.broken:
            return False
        target = self.url.split("#", 1)[0] + fragment
        try:
            self.page.goto("about:blank")  # so that a hash-only change is a full load
            self.page.goto(target)
            self.page.wait_for_selector("body[data-ready='true']", timeout=READY_TIMEOUT_MS)
            self.page.evaluate(SETTLE_JS)
            return True
        except PlaywrightError as exc:
            self.fail(f"open {fragment}: the viewer did not become ready: {first_line(exc)}")
            self.broken = True
            return False

    def shown(self, selector):
        try:
            return bool(self.page.evaluate(SHOWN_JS, selector))
        except PlaywrightError:
            return False

    def count_shown(self, selector):
        try:
            return int(self.page.evaluate(COUNT_SHOWN_JS, selector))
        except PlaywrightError:
            return 0

    def click(self, locator, what):
        """Click like a reader; if another element covers the target, try a corner, then dispatch."""
        try:
            locator.click(timeout=2000)
            return True
        except PlaywrightError as exc:
            first = first_line(exc)
        try:
            locator.click(position={"x": 6, "y": 6}, timeout=1500)
            self.note(f"{what}: the centre is covered ({first}); clicked near its top-left corner")
            return True
        except PlaywrightError:
            pass
        try:
            locator.dispatch_event("click")
            self.note(f"{what}: no visible point could be clicked ({first}); dispatched a click event")
            return True
        except PlaywrightError as exc:
            self.fail(f"{what}: cannot click: {first_line(exc)}")
            return False

    def body_mode(self):
        return self.page.evaluate("() => document.body.dataset.mode || null")

    def set_mode(self, mode, what):
        """Press the mode button and wait for body[data-mode]. True if the mode is set."""
        btn = self.page.locator(MODE_BUTTON.format(mode))
        if btn.count() != 1:
            self.fail(f"{what}: {btn.count()} buttons {MODE_BUTTON.format(mode)}, expected 1")
            return False
        if not self.click(btn, f"{what}: mode button {mode}"):
            return False
        try:
            self.page.wait_for_function("(m) => document.body.dataset.mode === m", arg=mode, timeout=STEP_TIMEOUT_MS)
        except PlaywrightError:
            self.fail(f"{what}: pressing {MODE_BUTTON.format(mode)} left body[data-mode={self.body_mode()}]")
            return False
        self.settle(300)
        return True

    def set_view(self, view, what):
        btn = self.page.locator(VIEW_BUTTON.format(view))
        if btn.count() != 1:
            self.fail(f"{what}: {btn.count()} buttons {VIEW_BUTTON.format(view)}, expected 1")
            return False
        if not self.click(btn, f"{what}: view button {view}"):
            return False
        try:
            self.page.wait_for_function("(sel) => { const b = document.querySelector(sel); return !!b && b.getAttribute('aria-pressed') === 'true'; }",
                                        arg=VIEW_BUTTON.format(view), timeout=STEP_TIMEOUT_MS)
        except PlaywrightError:
            self.fail(f"{what}: {VIEW_BUTTON.format(view)} is not aria-pressed after a click")
            return False
        self.settle(300)
        return True

    def card_id(self):
        return self.page.evaluate("() => { const c = document.querySelector('#part-card'); return c ? (c.dataset.card || null) : null; }")

    def wait_card(self, want, timeout=STEP_TIMEOUT_MS):
        try:
            self.page.wait_for_function("(w) => { const c = document.querySelector('#part-card'); return !!c && c.dataset.card === w; }",
                                        arg=want, timeout=timeout)
            return True
        except PlaywrightError:
            return False

    def panel_node(self):
        return self.page.evaluate(
            "() => { const t = document.querySelector('#part-card #detail-title'); return t ? t.dataset.nodeId : null; }")

    def wait_panel(self, node_id):
        try:
            self.page.wait_for_function(
                "(id) => { const t = document.querySelector('#part-card #detail-title'); return !!t && t.dataset.nodeId === id; }",
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

    def screenshot(self, name, full_page=False):
        if self.screenshot_dir:
            self.screenshot_dir.mkdir(parents=True, exist_ok=True)
            try:
                self.page.screenshot(path=str(self.screenshot_dir / name), full_page=full_page)
            except PlaywrightError as exc:
                self.note(f"screenshot {name}: {first_line(exc)}")

    def settle(self, ms=450):
        """Let CSS transitions (opacity .25-.6 s) finish."""
        self.page.wait_for_timeout(ms)

    def wait_scroll_stable(self, max_ms=3000):
        """Wait until window.scrollY stops changing (a smooth scroll ends)."""
        last, same, waited = None, 0, 0
        while waited < max_ms:
            y = self.page.evaluate("() => window.scrollY")
            same = same + 1 if y == last else 0
            if same >= 3:
                return y
            last = y
            self.page.wait_for_timeout(100)
            waited += 100
        return last


def map_box(part):
    return f'{MAP} g.box[data-part="{part}"]'


def part_box_locator(s, part):
    own = s.page.locator(f'{map_box(part)}[data-node="{part}"]')
    return own.first if own.count() else s.page.locator(map_box(part)).first


def open_part(s, part, what="open part"):
    """Click the part's map box (Explore mode) and wait for its card. True if the card shows the part."""
    if s.page.locator(map_box(part)).count() == 0:
        s.fail(f"{what}: no map box for part {part} ({map_box(part)})")
        return False
    if not s.click(part_box_locator(s, part), f"{what}: map box of {part}"):
        return False
    if not s.wait_card(part):
        s.fail(f"{what}: clicking the map box of {part} left #part-card[data-card={s.card_id()}]")
        return False
    if part in s.model_parts_with_children and not s.wait_detail(part):
        s.fail(f"{what}: the card of {part} has no {DETAIL.format(part)}")
        return False
    return True


def click_in_detail(s, part, node_id, what="drill"):
    """Click node_id's box, or its group's title strip, in the detail of part (in the card)."""
    d = DETAIL.format(part)
    box = s.page.locator(f'{d} g.box[data-node="{node_id}"]')
    if box.count():
        return s.click(box.first, f"{what}: detail box of {node_id}")
    grp = s.page.locator(f'{d} g.dgroup[data-node="{node_id}"]')
    if grp.count():
        strip = grp.first.locator("rect.gtitle")
        return s.click(strip.first if strip.count() else grp.first, f"{what}: group title strip of {node_id}")
    s.fail(f"{what}: the detail of {part} draws no g.box or g.dgroup for {node_id}")
    return False


# ---------------------------------------------------------------------------
# nodes: the node walk (and the folds of every panel)
# ---------------------------------------------------------------------------

PANEL_JS = js(r"""
const t = document.querySelector('#part-card #detail-title');
const c = document.querySelector('#part-card #card-title');
const p = document.querySelector('#part-card #detail-prose');
const r = t ? t.getBoundingClientRect() : null;
return { id: t ? (t.dataset.nodeId || null) : null, title: t ? t.textContent : null,
         vh: !!t && (t.classList.contains('vh') || r.width <= 1 || r.height <= 1),
         titleShown: shown(t), card: c && shown(c) ? c.innerText : null,
         prose: p && shown(p) ? p.innerText : '' };
""", "")

FOLD_JS = js(r"""
const card = document.querySelector('#part-card');
if (!card) return null;
const folds = [...card.querySelectorAll('details.fold[data-fold]')].map(d => ({ fold: d.dataset.fold, open: d.open, shown: shown(d) }));
const open = [...card.querySelectorAll('details')].filter(d => d.open).map(desc);
return { folds, open };
""", "")


def check_panel(s, m, node_id, how):
    """True if the card's panel shows node_id: its title and the first characters of its prose."""
    if not s.wait_panel(node_id):
        s.fail(f"{how}: {node_id}: #part-card #detail-title names {s.panel_node()!r}")
        return False
    p = s.page.evaluate(PANEL_JS)
    want = normalize(m.titles.get(node_id, ""))
    if p["vh"]:
        if normalize(p["title"]) != want or normalize(p["card"]) != want:
            s.fail(f"{how}: {node_id}: #detail-title (visually hidden) reads {normalize(p['title'])!r} and "
                   f"#card-title {normalize(p['card'])!r}, expected {want!r}")
            return False
    elif not p["titleShown"] or normalize(p["title"]) != want:
        s.fail(f"{how}: {node_id}: the panel title reads {normalize(p['title'])!r} "
               f"(shown={b(p['titleShown'])}), expected {want!r}")
        return False
    prefix = plain_text(m.node[node_id].get("prose", ""), m.titles)[:PROSE_PREFIX].strip()
    if not prefix or prefix not in normalize(p["prose"]):
        s.fail(f"{how}: {node_id}: the visible prose (#part-card #detail-prose) does not contain {prefix!r}")
        return False
    return True


def check_folds(s, m, node_id):
    """True if the panel of node_id has exactly its folds, each a closed details.fold[data-fold]."""
    want = m.expected_folds(node_id)
    got = s.page.evaluate(FOLD_JS)
    if got is None:
        s.fail(f"folded: {node_id}: no #part-card")
        return False
    names = [f["fold"] for f in got["folds"]]
    problems = []
    if sorted(names) != sorted(want):
        problems.append(f"folds {sorted(names)}, expected {sorted(want)} (from the node's JSON lists and edges)")
    opened = [f["fold"] for f in got["folds"] if f["open"]]
    if opened:
        problems.append(f"open on arrival: {opened}")
    hidden = [f["fold"] for f in got["folds"] if not f["shown"]]
    if hidden:
        problems.append(f"not displayed: {hidden}")
    if got["open"]:
        problems.append(f"open <details> in the card: {got['open']}")
    if problems:
        s.fail(f"folded: {node_id}: " + "; ".join(problems))
        return False
    return True


def drill_test(s, m, r):
    """Node walk. r gets visited, total, folds ({node: ok})."""
    visited, folds = set(), {}
    r.update(visited=0, total=len(m.ids), folds=folds)
    if not s.open("#/"):
        return
    s.screenshot("root.png")
    for part in m.tops:
        if len([f for f in s.failures if f.startswith("drill")]) >= MAX_DRILL_FAILURES:
            s.fail(f"drill: stopped after {MAX_DRILL_FAILURES} failures")
            break
        if s.page.locator(map_box(part)).count() == 0:
            s.fail(f"drill: no map box for {part}")
            continue
        if not s.click(part_box_locator(s, part), f"drill: map box of {part}"):
            continue
        if check_panel(s, m, part, "drill"):
            visited.add(part)
        folds[part] = check_folds(s, m, part)
        if not m.children.get(part):
            continue
        if not s.wait_detail(part):
            s.fail(f"drill: clicking the map box of {part} did not open {DETAIL.format(part)}")
            continue
        for node_id in m.descendants(part):
            if click_in_detail(s, part, node_id):
                if check_panel(s, m, node_id, "drill"):
                    visited.add(node_id)
                folds[node_id] = check_folds(s, m, node_id)
            if not s.wait_detail(part):  # the card must stay on this part
                s.fail(f"drill: after clicking {node_id} the detail of {part} is gone (card {s.card_id()})")
                if not open_part(s, part, "drill"):
                    break
    r["visited"] = len(visited)


# ---------------------------------------------------------------------------
# tour (on the main map) and the step card
# ---------------------------------------------------------------------------

TOUR_STATE_JS = r"""
(args) => {
  const svg = document.querySelector(args.map);
  if (!svg) return { error: 'no map ' + args.map };
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

# The callout tag of the map and the visible map texts its box overlaps
# (viewBox units, CSS transforms included).
TAG_JS = r"""
(sel) => {
  const svg = document.querySelector(sel);
  if (!svg) return { error: 'no map ' + sel };
  const tags = [...svg.querySelectorAll('g.callout rect.ctag')];
  if (tags.length !== 1) return { error: tags.length + ' callout tags (g.callout rect.ctag), expected 1' };
  const inv = svg.getScreenCTM().inverse();
  const bb = el => {
    const m = inv.multiply(el.getScreenCTM()), b = el.getBBox();
    const p = [[b.x, b.y], [b.x + b.width, b.y], [b.x, b.y + b.height], [b.x + b.width, b.y + b.height]]
      .map(([x, y]) => [m.a * x + m.c * y + m.e, m.b * x + m.d * y + m.f]);
    const x0 = Math.min(...p.map(q => q[0])), y0 = Math.min(...p.map(q => q[1]));
    return { x: x0, y: y0, w: Math.max(...p.map(q => q[0])) - x0, h: Math.max(...p.map(q => q[1])) - y0 };
  };
  const shown = el => { for (let e = el; e && e !== svg.parentNode; e = e.parentElement) { const cs = getComputedStyle(e);
    if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return false; } return true; };
  const t0 = bb(tags[0]);
  const hits = [];
  svg.querySelectorAll('text').forEach(t => {
    if (t.closest('g.callout, g.tok, defs, mask') || !shown(t)) return;
    const r = bb(t);
    if (!r.w || !r.h) return;
    const ox = Math.min(t0.x + t0.w, r.x + r.w) - Math.max(t0.x, r.x);
    const oy = Math.min(t0.y + t0.h, r.y + r.h) - Math.max(t0.y, r.y);
    if (ox > 0.5 && oy > 0.5) hits.push((t.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60));
  });
  return { tag: [t0.x, t0.y, t0.w, t0.h].map(v => Math.round(v * 10) / 10), hits };
}
"""

# Full-size map drawings: any svg that is not .mini and not .detail and either
# has the viewBox of map.viewbox or holds g.box[data-part] for every top-level part.
FULLMAP_JS = js(r"""
const main = document.querySelector(args.map);
const out = [];
document.querySelectorAll('svg').forEach(svg => {
  if (svg.classList.contains('mini') || svg.classList.contains('detail')) return;
  const v = (svg.getAttribute('viewBox') || '').trim().split(/[\s,]+/).map(Number);
  const vbOk = v.length === 4 && v[0] === 0 && v[1] === 0 && v[2] === args.w && v[3] === args.h;
  const parts = new Set([...svg.querySelectorAll('g.box[data-part]')].map(g => g.dataset.part));
  if (vbOk || (args.tops.length && args.tops.every(t => parts.has(t))))
    out.push({ desc: desc(svg), main: svg === main, shown: shown(svg) });
});
return out;
""")

ON_MAIN_JS = js(r"""
const map = document.querySelector(args.map);
const eff = el => { let o = 1; for (let e = el; e && e.nodeType === 1; e = e.parentElement) o *= parseFloat(getComputedStyle(e).opacity); return o; };
const disp = el => { for (let e = el; e && e.nodeType === 1; e = e.parentElement) if (getComputedStyle(e).display === 'none') return false; return true; };
const live = el => disp(el) && eff(el) > 0.01;
const inMap = el => !!map && map.contains(el);
return {
  callouts: map ? [...map.querySelectorAll('g.callout')].filter(live).map(c => c.dataset.part || '') : [],
  outCallouts: [...document.querySelectorAll('g.callout')].filter(c => !inMap(c) && live(c)).map(desc),
  toksIn: map ? [...map.querySelectorAll('g.tok')].filter(t => disp(t) && eff(t) >= 0.99).length : 0,
  toksOut: [...document.querySelectorAll('g.tok')].filter(t => !inMap(t) && disp(t) && eff(t) >= 0.99).map(desc),
  mapShown: shown(map)
};
""")

STEP_CARD_JS = js(r"""
const card = document.querySelector('#step-card'), frame = document.querySelector('#map');
const t = document.querySelector('#tour-step-title'), p = document.querySelector('#tour-step-prose');
const foot = document.querySelector('#step-foot');
return { cardShown: shown(card), cardTop: card ? card.getBoundingClientRect().top : null,
         frameBottom: frame ? frame.getBoundingClientRect().bottom : null,
         titleIn: !!(card && t && card.contains(t)), proseIn: !!(card && p && card.contains(p)),
         text: card && shown(card) ? card.innerText : '',
         openPart: card ? [...card.querySelectorAll('button.open-part')].filter(shown).length : 0,
         foot: foot && shown(foot) ? foot.innerText : null,
         footBack: !!(foot && foot.querySelector('a.back-to-map[data-moves-page]')) };
""", "")

TOUR_FIT_JS = """() => {
  const f = (sel) => { const el = document.querySelector(sel); return el ? Math.round(el.getBoundingClientRect().bottom + window.scrollY) : null; };
  return { tourbar: f('#tourbar'), title: f('#tour-step-title') };
}"""


def full_maps(s, m):
    vb = m.map.get("viewbox") or {}
    return s.page.evaluate(FULLMAP_JS, {"map": MAP, "w": vb.get("w"), "h": vb.get("h"), "tops": m.tops})


def tour_test(s, m, r):
    """Tour on the main map. r gets steps_ok, highlighted, on_main, tag_clear, text, detail, T, fit."""
    steps = m.steps
    T = len(steps)
    r.update(steps_ok=0, highlighted=0, on_main=0, tag_clear=0, text=0, detail=0, T=T, fit=None)
    if not s.open("#/") or not s.set_mode("tour", "tour"):
        return
    r["fit"] = s.page.evaluate(TOUR_FIT_JS)
    pips = s.page.locator("#pips button.pip")
    if pips.count() != T:
        s.fail(f"tour: {pips.count()} pips (#pips button.pip) for {T} steps")
    if pips.count() and not s.click(pips.first, "tour: pip 1"):
        return
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
        prose_ok = bool(want) and want in prose
        if not prose_ok:
            s.fail(f"tour: step {k}: the visible step text does not contain {want!r}")
            ok = False
        node = step.get("node")
        top = m.top(node)
        s.settle(700)
        state = s.page.evaluate(TOUR_STATE_JS, {"map": MAP})
        if "error" in state:
            s.fail(f"tour: step {k}: {state['error']}")
            ok = False
            state = None
        if state is not None and state["fading"]:
            s.page.wait_for_timeout(600)
            state = s.page.evaluate(TOUR_STATE_JS, {"map": MAP})
        callout_ok = state is not None and top in state["callouts"]
        if state is not None and not callout_ok:
            s.fail(f"tour: step {k}: no callout (g.callout[data-part={top}]) on {MAP}; callouts: {state['callouts']}")
        if ok and callout_ok:
            r["steps_ok"] += 1
        if state is not None and callout_ok and highlight_ok(s, m, k, step, top, state):
            r["highlighted"] += 1
        # on_main_map
        on = s.page.evaluate(ON_MAIN_JS, {"map": MAP})
        fulls = full_maps(s, m)
        probs = []
        if on["callouts"] != [top]:
            probs.append(f"g.callout in {MAP}: {on['callouts']}, expected exactly one on {top}")
        if on["outCallouts"]:
            probs.append(f"callouts outside {MAP}: {on['outCallouts']}")
        if on["toksOut"]:
            probs.append(f"visible tokens outside {MAP}: {on['toksOut'][:4]}")
        entry = m.tour_entry(step) or {}
        if entry.get("tokens") and on["toksIn"] == 0:
            probs.append(f"no visible token (g.tok) in {MAP}")
        if len(fulls) != 1 or not fulls[0]["main"]:
            probs.append(f"full-size map drawings: {[f['desc'] for f in fulls]}, expected only {MAP}")
        if not on["mapShown"]:
            probs.append(f"{MAP} is not displayed")
        if probs:
            s.fail(f"tour on_main_map: step {k}: " + "; ".join(probs))
        else:
            r["on_main"] += 1
        tag = s.page.evaluate(TAG_JS, MAP)
        if "error" in tag:
            s.fail(f"tour: step {k}: {tag['error']}")
        elif tag["hits"]:
            s.fail(f"tour: step {k}: the callout tag (g.callout rect.ctag at x,y,w,h={tag['tag']}) "
                   f"covers map text {tag['hits']}")
        else:
            r["tag_clear"] += 1
        # the step card
        c = s.page.evaluate(STEP_CARD_JS)
        cprob = []
        if not c["cardShown"]:
            cprob.append("#step-card is not displayed")
        if not (c["titleIn"] and c["proseIn"]):
            cprob.append("#tour-step-title / #tour-step-prose are not inside #step-card")
        if shown != normalize(step.get("title", "")) or not prose_ok:
            cprob.append("step title or text not shown (see above)")
        text = normalize(c["text"]).lower()
        ntitle = normalize(m.titles.get(node, "")).lower()
        nsum = plain_text(m.node.get(node, {}).get("summary", ""), m.titles)[:PROSE_PREFIX].strip().lower()
        if not ntitle or ntitle not in text:
            cprob.append(f"the step node's title {m.titles.get(node)!r} is not in the card")
        if not nsum or nsum not in text:
            cprob.append(f"the step node's summary ({nsum!r}) is not in the card")
        if c["openPart"] < 1:
            cprob.append("no displayed button.open-part in the card")
        if cprob:
            s.fail(f"tour_card text: step {k}: " + "; ".join(cprob))
        else:
            r["text"] += 1
        dprob = []
        sel = TOUR_DETAIL.format(top)
        if s.page.locator(sel).count() != 1:
            dprob.append(f"no {sel}")
        elif node != top and s.page.locator(f'{sel} g.box.hot[data-node="{node}"], {sel} g.dgroup.hot[data-node="{node}"]').count() < 1:
            dprob.append(f"{node} is not .hot in {sel}")
        if c["cardTop"] is None or c["frameBottom"] is None or c["cardTop"] < c["frameBottom"] - 1:
            dprob.append(f"#step-card top {c['cardTop']} is not below the map frame (#map bottom {c['frameBottom']})")
        if dprob:
            s.fail(f"tour_card detail: step {k}: " + "; ".join(dprob))
        else:
            r["detail"] += 1
        if k == 1:
            s.screenshot("tour-step-1.png")
        if k < T:
            try:
                s.page.locator("#tour-next").click()
            except PlaywrightError as exc:
                s.fail(f"tour: cannot click #tour-next at step {k}: {first_line(exc)}")
                break


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
    if len(shown) != len(expect) or any(a[0] != b_[0] or abs(a[1] - b_[1]) > 0.51 or abs(a[2] - b_[2]) > 0.51
                                        for a, b_ in zip(shown, expect)):
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

def smoke_test(s, m, r):
    result = r

    def attempt(name, func):
        try:
            result[name] = func()
        except (PlaywrightError, AssertionError) as exc:
            s.fail(f"smoke {name}: {first_line(exc)}")
            result[name] = "fail"

    def stub_click():
        if not s.open("#/"):
            return "fail"
        for part in m.parts_with_children:
            if not open_part(s, part, "smoke stub_click"):
                return "fail"
            stubs = s.page.locator(f"{DETAIL.format(part)} g.stub[data-other]")
            if stubs.count() == 0:
                continue
            other = stubs.first.get_attribute("data-other")
            tag_rect = stubs.first.locator("rect").first  # the tag itself, not the group's box (which holds the connector)
            if not s.click(tag_rect, f"smoke stub_click: tag of {part} to {other}"):
                return "fail"
            if not s.wait_card(other) or (other in m.parts_with_children and not s.wait_detail(other)):
                s.fail(f"smoke stub_click: clicking the tag to {other} in the detail of {part} left "
                       f"#part-card[data-card={s.card_id()}]")
                return "fail"
            return "ok"
        s.fail("smoke stub_click: no part's detail has a neighbour tag (g.stub[data-other])")
        return "fail"

    def arrow_keys():
        if len(m.steps) < 2:
            s.fail(f"smoke arrow_keys: the tour has {len(m.steps)} step(s); at least 2 are needed")
            return "fail"
        if not s.open("#/tour/1"):
            return "fail"
        s.page.wait_for_selector('#tour-step-title[data-step-index="1"]')
        s.page.evaluate("() => { const b = document.querySelector('#tour-next'); if (b) b.focus({ preventScroll: true }); }")
        if not s.page.evaluate("() => !!(document.activeElement && document.activeElement.closest('#map-section'))"):
            s.fail("smoke arrow_keys: could not put the focus in #map-section (#tour-next)")
            return "fail"
        s.page.keyboard.press("ArrowRight")
        s.page.wait_for_selector('#tour-step-title[data-step-index="2"]')
        s.page.keyboard.press("ArrowLeft")
        s.page.wait_for_selector('#tour-step-title[data-step-index="1"]')
        return "ok"

    def arrow_scope():
        if len(m.steps) < 3:
            s.fail(f"smoke arrow_scope: the tour has {len(m.steps)} step(s); at least 3 are needed")
            return "fail"
        if not s.open("#/") or not s.set_mode("tour", "smoke arrow_scope"):
            return "fail"
        if not s.click(s.page.locator("#pips button.pip").nth(2), "smoke arrow_scope: pip 3"):
            return "fail"
        s.page.wait_for_selector('#tour-step-title[data-step-index="3"]')
        # scroll to the matrix and click its head (not focusable): the focus leaves #map-section
        s.page.locator("#matrix").scroll_into_view_if_needed()
        head = s.page.locator("#matrix .card-head h1, #matrix .card-head h2, #matrix .card-head h3, #matrix h2, #matrix h3").first
        s.click(head, "smoke arrow_scope: the matrix heading")
        s.page.evaluate("() => { const a = document.activeElement; if (a && a !== document.body && a.closest('#map-section')) a.blur(); }")
        where = s.page.evaluate("() => { const a = document.activeElement; return a ? (a.id ? '#' + a.id : a.tagName) : 'none'; }")
        if s.page.evaluate("() => !!(document.activeElement && document.activeElement.closest('#map-section'))"):
            s.fail(f"smoke arrow_scope: the focus stayed in #map-section ({where})")
            return "fail"
        # counts the arrow keys that reach the window already default-prevented
        s.page.evaluate("""() => { window.__arrows = { seen: 0, prevented: 0 };
          window.addEventListener('keydown', (e) => { if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
            window.__arrows.seen++; if (e.defaultPrevented) window.__arrows.prevented++; } }); }""")
        s.page.keyboard.press("ArrowRight")
        s.page.keyboard.press("ArrowRight")
        s.settle(300)
        step = s.page.evaluate("() => { const t = document.querySelector('#tour-step-title'); return t ? t.dataset.stepIndex : null; }")
        arrows = s.page.evaluate("() => window.__arrows")
        good = True
        if step != "3":
            s.fail(f"smoke arrow_scope: with the focus on {where} (outside #map-section), ArrowRight x2 moved the tour from step 3 to step {step}")
            good = False
        if arrows["prevented"]:
            s.fail(f"smoke arrow_scope: {arrows['prevented']} of {arrows['seen']} arrow keys pressed outside #map-section "
                   f"were default-prevented (the browser cannot scroll sideways with them)")
            good = False
        return "ok" if good else "fail"

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
        result.update(stub_click="fail", arrow_keys="fail", help="fail", read_page=(0, len(m.ids)), arrow_scope="fail")
        return
    attempt("stub_click", stub_click)
    attempt("arrow_keys", arrow_keys)
    attempt("arrow_scope", arrow_scope)
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


def smoke_line(result, third_party):
    shown, total = result.get("read_page", (0, 0))
    return (f"smoke stub_click={result.get('stub_click', 'fail')} arrow_keys={result.get('arrow_keys', 'fail')} "
            f"help={result.get('help', 'fail')} read_page={shown}/{total} third_party={third_party} "
            f"arrow_scope={result.get('arrow_scope', 'fail')}")


def smoke_ok(result):
    shown, total = result.get("read_page", (0, 0))
    return (all(result.get(k) == "ok" for k in ("stub_click", "arrow_keys", "arrow_scope", "help"))
            and total > 0 and shown == total)


# ---------------------------------------------------------------------------
# map_first
# ---------------------------------------------------------------------------

MAP_FIRST_JS = js(r"""
const h1 = document.querySelector('h1#model-title'), frame = document.querySelector('#map');
const svg = document.querySelector('#map svg.map'), wrap = document.querySelector('.wrap') || document.body;
if (!h1 || !frame || !svg) return { error: 'missing ' + [!h1 && 'h1#model-title', !frame && '#map', !svg && '#map svg.map'].filter(Boolean).join(', ') };
const hb = h1.getBoundingClientRect().bottom, ft = frame.getBoundingClientRect().top;
const names = [];
const displayed = el => { const cs = getComputedStyle(el); return cs.display !== 'none' && cs.visibility !== 'hidden'; };
const visit = el => {
  for (const c of el.children) {
    if (!displayed(c)) continue;
    if (c.contains(h1) || c.contains(frame)) { visit(c); continue; }
    const r = c.getBoundingClientRect();
    if (r.height <= 1 || r.width <= 1) { visit(c); continue; }  // zero-size or visually hidden
    if (r.top >= hb - 1 && r.bottom <= ft + 1) {
      const cls = typeof c.className === 'string' ? c.className.trim() : '';
      names.push(c.id || (cls ? cls.split(/\s+/)[0] : c.tagName.toLowerCase()));
    }
  }
};
visit(wrap);
const sr = svg.getBoundingClientRect(), y = window.scrollY;
const parentOf = id => { const e = document.getElementById(id); return e && e.parentElement ? (e.parentElement.id || e.parentElement.tagName) : null; };
return { names, top: Math.round(sr.top + y), bottom: Math.round(sr.bottom + y), frame: Math.round(ft + y),
         modesParent: parentOf('modes'), chipsParent: parentOf('chips'), noteShown: shown(document.querySelector('#mode-note')) };
""", "")


def map_first_test(s, m, size, r):
    r.update(top=None, bottom=None, frame=None, names=None, ok=False)
    s.set_viewport(size)
    if not s.open("#/"):
        return
    s.settle(300)
    g = s.page.evaluate(MAP_FIRST_JS)
    s.screenshot(f"map-first-{size[0]}.png")
    if "error" in g:
        s.fail(f"map_first {size[0]}x{size[1]}: {g['error']}")
        return
    r.update(top=g["top"], bottom=g["bottom"], frame=g["frame"], names=g["names"])
    ok = g["names"] == ["modes", "chips"]
    if not ok:
        s.fail(f"map_first {size[0]}x{size[1]}: the blocks between the h1 and the map frame are "
               f"{g['names']}, expected ['modes', 'chips']")
    for hook, parent in (("#modes", g["modesParent"]), ("#chips", g["chipsParent"])):
        if parent != "map-section":
            s.fail(f"map_first: {hook} is a child of {parent}, expected a direct child of #map-section")
            ok = False
    if size == PRIMARY and not (g["bottom"] <= MAP_BOTTOM_MAX_744):
        s.fail(f"map_first 744x1000: map_bottom={g['bottom']} > {MAP_BOTTOM_MAX_744}")
        ok = False
    if size == WIDE and not (g["top"] <= MAP_TOP_MAX_1440):
        s.fail(f"map_first 1440x900: map_top={g['top']} > {MAP_TOP_MAX_1440}")
        ok = False
    r["ok"] = ok


# ---------------------------------------------------------------------------
# modes / full_maps
# ---------------------------------------------------------------------------

MODE_STATE_JS = js(r"""
return { mode: document.body.dataset.mode || null,
         pressed: [...document.querySelectorAll('#modes button.mode')].filter(b => b.getAttribute('aria-pressed') === 'true').map(b => b.dataset.mode),
         chips: shown(document.querySelector('#chips')), controls: shown(document.querySelector('#tour-controls')),
         note: shown(document.querySelector('#mode-note')) };
""", "")


def modes_test(s, m, r):
    r.update(M=0, F=0, counts={}, displayed=[], ok=False)
    if not s.open("#/"):
        return
    buttons = s.page.evaluate("() => [...document.querySelectorAll('#modes button.mode')].map(b => b.dataset.mode || '')")
    if sorted(buttons) != sorted(MODES):
        s.fail(f"modes: #modes button.mode data-mode values {buttons}, expected {list(MODES)}")
    counts, displayed, problems = {}, [], []

    def count(state):
        fulls = full_maps(s, m)
        counts[state] = len(fulls)
        if any(f["shown"] for f in fulls if f["main"]):
            displayed.append(state)
        extra = [f["desc"] for f in fulls if not f["main"]]
        if extra:
            problems.append(f"{state}: full-size map drawings other than {MAP}: {extra}")

    st = s.page.evaluate(MODE_STATE_JS)
    if st["mode"] != "explore":
        problems.append(f"on #/ body[data-mode={st['mode']}], expected explore")
    count("explore")
    working = 0
    for mode in ("tour", "compare", "explore"):
        if mode not in buttons:
            continue
        btn = s.page.locator(MODE_BUTTON.format(mode))
        if not s.click(btn.first, f"modes: button {mode}"):
            continue
        s.settle(400)
        st = s.page.evaluate(MODE_STATE_JS)
        bad = []
        if st["mode"] != mode:
            bad.append(f"body[data-mode={st['mode']}]")
        if st["pressed"] != [mode]:
            bad.append(f"aria-pressed=true on {st['pressed']}")
        if st["chips"] != (mode == "explore"):
            bad.append(f"#chips displayed={b(st['chips'])}")
        if st["controls"] != (mode == "tour"):
            bad.append(f"#tour-controls displayed={b(st['controls'])}")
        if st["note"] != (mode != "explore"):
            bad.append(f"#mode-note displayed={b(st['note'])}")
        if bad:
            problems.append(f"pressing {mode}: " + ", ".join(bad))
        else:
            working += 1
        if mode == "tour":
            count("tour_map")
            if s.set_view("seq", "modes"):
                count("tour_seq")
                s.set_view("map", "modes")
        elif mode == "compare":
            count("compare")
    r["M"] = working + max(0, len(buttons) - len(MODES))  # an extra button makes M wrong
    r["counts"], r["displayed"] = counts, displayed
    r["F"] = max(counts.values()) if counts else 0
    for state in ("explore", "tour_map", "tour_seq", "compare"):
        if counts.get(state) != 1:
            problems.append(f"{state}: {counts.get(state, 'not measured')} full-size map drawings, expected 1")
    if displayed != ["explore", "tour_map"]:
        problems.append(f"{MAP} displayed in {displayed}, expected explore and tour_map only")
    for p in problems:
        s.fail(f"modes: {p}")
    r["ok"] = r["M"] == 3 and len(buttons) == 3 and r["F"] == 1 and not problems


# ---------------------------------------------------------------------------
# map, detail, multiples, sequence, matrix
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


def map_test(s, m, r):
    want_rects = expected_box_rects(m)
    r.update(parts=0, P0=len(m.tops), lanes=0, bands=0, columns=0, boxes=0, Q=len(want_rects), ok=False)
    if not s.open("#/"):
        return
    info = s.page.evaluate(MAP_INFO_JS, MAP)
    if info is None:
        s.fail(f"map: no {MAP}")
        return
    drawn = {}
    for x in info["rects"]:
        drawn.setdefault(x["key"], []).append(x["rect"])
    matching = 0
    rect_ok = True
    for key, want in want_rects.items():
        got = drawn.get(key, [])
        if len(got) != 1 or got[0] is None:
            s.fail(f"map: box {key} is drawn {len(got)} times (g.box[data-box][data-lane] with rect.b), expected once")
            rect_ok = False
            continue
        if any(not isinstance(v, (int, float)) for v in want) or \
                any(abs(a - b_) > BOX_RECT_TOLERANCE for a, b_ in zip(got[0], want)):
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
    r.update(parts=len(m.tops) - len(missing), lanes=info["lanes"], bands=info["bands"], columns=info["columns"],
             boxes=matching, ok=ok and rect_ok)


def detail_test(s, m, r):
    r.update(opened=0, P=len(m.parts_with_children))
    if not s.open("#/"):
        return
    for part in m.parts_with_children:
        if not open_part(s, part, "detail"):
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
            r["opened"] += 1


MULTIPLES_JS = r"""
(sel) => [...document.querySelectorAll(sel)].map(f => {
  const svg = f.querySelector('svg.map.mini[data-kind]');
  const cap = f.querySelector('figcaption');
  if (!svg) return { kind: null, caption: cap ? cap.innerText : '' };
  const eff = el => { let o = 1; for (let e = el; e && e !== f; e = e.parentElement) o *= +getComputedStyle(e).opacity; return o; };
  const lines = [...svg.querySelectorAll('path.ln')].filter(p => getComputedStyle(p).display !== 'none')
    .map(p => ({ kind: p.dataset.kind || null, lit: eff(p) > 0.5, id: p.dataset.line || '' }));
  return { kind: svg.dataset.kind, caption: cap ? cap.innerText : '', lines };
})
"""


def multiples_test(s, m, r):
    want = [x.get("kind") for x in (m.map.get("multiples") or []) if isinstance(x, dict)]
    total = len(want) or 6
    r.update(panels=0, total=total, mode="FAIL:not-run")
    if not s.open("#/"):
        return
    where = []
    if s.count_shown(MULT):
        where.append("shown-in-explore")
    if s.set_mode("tour", "multiples") and s.count_shown(MULT):
        where.append("shown-in-tour")
    if not s.set_mode("compare", "multiples"):
        r["mode"] = "FAIL:no-compare"
        return
    s.settle(500)
    n_shown = s.count_shown(MULT)
    if n_shown != total:
        where.append(f"{n_shown}-shown-in-compare")
    r["mode"] = "compare" if not where else "FAIL:" + ",".join(where)
    if where:
        s.fail(f"multiples: the small maps ({MULT}) must be displayed in compare mode only: {where}")
    figs = s.page.evaluate(MULTIPLES_JS, MULT)
    if len(figs) != total:
        s.fail(f"multiples: {len(figs)} figures {MULT}, {total} in map.multiples")
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
    r["panels"] = good


LIFELINE_TOLERANCE = 10  # viewBox units between a row arrow's end and a lifeline header's centre

SEQ_ROW_JS = r"""
([sel, k, tol]) => {
  const svg = document.querySelector(sel);
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
    got = s.page.evaluate(SEQ_ROW_JS, [SEQ, k, LIFELINE_TOLERANCE])
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


def sequence_test(s, m, r):
    T = len(m.steps)
    rows_sel = f"{SEQ} .row[data-step-index]"
    r.update(rows=0, T=T, mode="FAIL:not-run")
    if not s.open("#/"):
        return
    where = []
    if s.count_shown(rows_sel):
        where.append("shown-in-explore")
    if not s.set_mode("tour", "sequence"):
        r["mode"] = "FAIL:no-tour"
        return
    if s.count_shown(rows_sel):
        where.append("shown-in-tour-map-view")
    if not s.set_view("seq", "sequence"):
        r["mode"] = "FAIL:no-seq-view"
        return
    n_rows = s.count_shown(rows_sel)
    if n_rows != T:
        where.append(f"{n_rows}-shown-in-seq-view")
    seq = m.map.get("sequence") or {}
    lifelines = [x for x in (seq.get("lifelines") or []) if isinstance(x, dict)]
    rows_by_step = {x.get("step"): dict(x, _lifelines=lifelines) for x in (seq.get("rows") or []) if isinstance(x, dict)}
    good = 0
    for k, step in enumerate(m.steps, 1):
        rows = s.page.locator(f'{SEQ} .row[data-step-index="{k}"]')
        if rows.count() != 1:
            s.fail(f"sequence: {rows.count()} rows {SEQ} .row[data-step-index={k}]")
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
            s.page.wait_for_selector(f'#tour-step-title[data-step-index="{k}"]', state="attached")
        except PlaywrightError:
            s.fail(f"sequence: clicking row {k} did not open tour step {k}")
            continue
        title = s.page.evaluate("(k) => { const t = document.querySelector('#tour-step-title[data-step-index=\"' + k + '\"]'); return t ? t.textContent : ''; }", k)
        if normalize(title) != normalize(step.get("title", "")):
            s.fail(f"sequence: clicking row {k} shows the title {normalize(title)!r}")
            continue
        pressed = s.page.evaluate("(sel) => { const b = document.querySelector(sel); return b ? b.getAttribute('aria-pressed') : null; }",
                                  VIEW_BUTTON.format("seq"))
        if pressed != "true" or not s.shown(SEQ) or s.body_mode() != "tour":
            s.fail(f"sequence: after clicking row {k} the view is not the sequence chart any more "
                   f"(seq aria-pressed={pressed}, {SEQ} shown={b(s.shown(SEQ))}, mode={s.body_mode()})")
            continue
        good += 1
    extra = s.page.locator(rows_sel).count() - T
    if extra > 0:
        s.fail(f"sequence: {extra} more rows than tour steps")
        good = min(good, T - 1)
    if s.set_mode("compare", "sequence") and s.count_shown(rows_sel):
        where.append("shown-in-compare")
    r["mode"] = "tour" if not where else "FAIL:" + ",".join(where)
    if where:
        s.fail(f"sequence: the rows must be displayed only in tour mode with the sequence view: {where}")
    r["rows"] = good


EMPH_JS = js(r"""
const svg = document.querySelector(args);
if (!svg) return null;
const eff = el => { let o = 1; for (let e = el; e && e !== svg.parentNode; e = e.parentElement) o *= parseFloat(getComputedStyle(e).opacity); return o; };
const lines = [...svg.querySelectorAll('path.ln[data-kind]')].filter(p => getComputedStyle(p).display !== 'none').map(p => ({ kind: p.dataset.kind, op: eff(p) }));
const cap = document.querySelector('#kind-caption');
return { lines, capShown: shown(cap), capKind: cap ? (cap.dataset.kind || null) : null, capText: cap && shown(cap) ? cap.innerText : '' };
""")


def emphasize_test(s, m, r):
    kinds = m.kinds_with_caption()
    r.update(good=0, K=len(kinds), hidden_ok=False)
    if not s.open("#/"):
        return
    if not kinds:
        s.fail("emphasize: no kind of map.kinds has a map.multiples caption; nothing to test")
        return
    for kind, caption in kinds:
        chip = s.page.locator(f'#chips button.chip[data-kind="{kind}"]')
        if chip.count() != 1:
            s.fail(f"emphasize: {chip.count()} chips #chips button.chip[data-kind={kind}]")
            continue
        if not s.click(chip, f"emphasize: chip {kind}"):
            continue
        s.settle(650)
        e = s.page.evaluate(EMPH_JS, MAP)
        if e is None:
            s.fail(f"emphasize: no {MAP}")
            return
        want = plain_text(caption, m.titles)[:PROSE_PREFIX].strip()
        probs = []
        if not e["capShown"]:
            probs.append("#kind-caption is not displayed")
        elif e["capKind"] != kind:
            probs.append(f"#kind-caption[data-kind={e['capKind']}]")
        elif want not in normalize(e["capText"]):
            probs.append(f"#kind-caption does not contain {want!r}")
        lit_other = sorted({x["kind"] for x in e["lines"] if x["kind"] != kind and x["op"] > 0.5})
        lit_own = sum(1 for x in e["lines"] if x["kind"] == kind and x["op"] > 0.5)
        if lit_other:
            probs.append(f"lines of other kinds not dimmed: {lit_other}")
        if lit_own == 0:
            probs.append("no undimmed line of this kind")
        if probs:
            s.fail(f"emphasize: {kind}: " + "; ".join(probs))
        else:
            r["good"] += 1
    hidden = []
    all_chip = s.page.locator('#chips button.chip[data-kind="all"]')
    if all_chip.count() == 1 and s.click(all_chip, "emphasize: chip all"):
        s.settle(400)
        if s.shown("#kind-caption"):
            hidden.append("the All chip leaves #kind-caption displayed")
    else:
        hidden.append("no #chips button.chip[data-kind=all]")
    first = s.page.locator(f'#chips button.chip[data-kind="{kinds[0][0]}"]')
    if first.count() == 1 and s.click(first, f"emphasize: chip {kinds[0][0]}"):
        s.settle(400)
        for mode in ("tour", "compare"):
            if s.set_mode(mode, "emphasize") and s.shown("#kind-caption"):
                hidden.append(f"#kind-caption displayed in {mode} mode")
    for h in hidden:
        s.fail(f"emphasize: {h}")
    r["hidden_ok"] = not hidden


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

MATRIX_FIT_JS = js(r"""
const t = document.querySelector('#matrix table.nsq'), card = document.querySelector('#matrix');
if (!t || !card) return null;
let box = t.parentElement;
for (let e = t.parentElement; e && e !== card.parentElement; e = e.parentElement) {
  const ox = getComputedStyle(e).overflowX;
  if (ox === 'auto' || ox === 'scroll') { box = e; break; }
}
const cs = getComputedStyle(card), cr = card.getBoundingClientRect();
const inner = cr.right - parseFloat(cs.borderRightWidth) - parseFloat(cs.paddingRight);
let right = -Infinity;
t.querySelectorAll('td, th').forEach(c => { right = Math.max(right, c.getBoundingClientRect().right); });
const clips = [];
for (let e = t.parentElement; e; e = e.parentElement) {
  const ox = getComputedStyle(e).overflowX;
  if (ox === 'hidden' || ox === 'clip') clips.push(desc(e) + ' overflow-x:' + ox);
}
let minPx = Infinity, minWhere = '';
t.querySelectorAll('*').forEach(el => {
  if (![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) return;
  if (!shown(el)) return;
  const px = parseFloat(getComputedStyle(el).fontSize);
  if (px < minPx) { minPx = px; minWhere = (el.textContent || '').trim().slice(0, 40); }
});
return { scroll: box.scrollWidth - box.clientWidth, box: desc(box), over: Math.ceil(right - inner), clips,
         buttons: [...card.querySelectorAll('button')].map(desc),
         minPx: isFinite(minPx) ? Math.round(minPx * 10) / 10 : null, minWhere };
""", "")

FOOT_JS = js(r"""
const f = document.querySelector(args);
return f ? { shown: shown(f), text: f.innerText || '', back: !!f.querySelector('a.back-to-map[data-moves-page]'),
             backShown: [...f.querySelectorAll('a.back-to-map[data-moves-page]')].some(shown) } : null;
""")


def footer_ok(s, selector, want_start, what):
    f = s.page.evaluate(FOOT_JS, selector)
    if f is None or not f["shown"]:
        s.fail(f"end_footer: {what}: {selector} is not displayed")
        return False
    text = normalize(f["text"])
    if not text.startswith(want_start):
        s.fail(f"end_footer: {what}: {selector} reads {text[:80]!r}, expected it to start with {want_start!r}")
        return False
    if not f["backShown"]:
        s.fail(f"end_footer: {what}: {selector} has no displayed a.back-to-map[data-moves-page]")
        return False
    return True


# Sticky head: put the card's top STICKY_OFFSET px above the viewport (less
# for a card too short for that) and measure the head.
STICKY_SCROLL_JS = r"""
(args) => {
  const card = document.querySelector(args.card), head = document.querySelector(args.head);
  if (!card || !head) return { error: 'missing ' + (!card ? args.card : args.head) };
  const cr = card.getBoundingClientRect(), hr = head.getBoundingClientRect();
  const off = Math.max(0, Math.min(args.offset, cr.height - hr.height - 40));
  const y = cr.top + window.scrollY + off;
  const max = document.documentElement.scrollHeight - window.innerHeight;
  if (y > max) { const sp = document.createElement('div'); sp.id = '__bt_spacer'; sp.style.height = Math.ceil(y - max + 50) + 'px'; document.body.append(sp); }
  window.scrollTo({ top: y, behavior: 'instant' });
  return { off: Math.round(off), y: Math.round(y) };
}
"""
STICKY_MEASURE_JS = js(r"""
const card = document.querySelector(args.card), head = document.querySelector(args.head);
const cr = card.getBoundingClientRect(), hr = head.getBoundingClientRect();
const bad = [];
for (let e = head.parentElement; e; e = e.parentElement) {
  const cs = getComputedStyle(e);
  if (![cs.overflowX, cs.overflowY].every(v => v === 'visible' || v === 'clip')) bad.push(desc(e) + ' overflow:' + cs.overflowX + '/' + cs.overflowY);
}
const sp = document.getElementById('__bt_spacer'); if (sp) sp.remove();
return { headTop: Math.round(hr.top * 10) / 10, headBottom: hr.bottom, cardTop: cr.top, cardBottom: cr.bottom, headH: Math.round(hr.height),
         position: getComputedStyle(head).position, bad };
""")


def sticky_check(s, card, head, what):
    a = {"card": card, "head": head, "offset": STICKY_OFFSET}
    g = s.page.evaluate(STICKY_SCROLL_JS, a)
    if "error" in g:
        s.fail(f"sticky_head: {what}: {g['error']}")
        return False
    s.page.evaluate(RAF2_JS)
    s.settle(250)
    h = s.page.evaluate(STICKY_MEASURE_JS, a)
    probs = []
    if abs(h["headTop"]) > HEAD_TOLERANCE:
        probs.append(f"with the card top {g['off']} px above the viewport the head's top is at {h['headTop']} px "
                     f"(position {h['position']})")
    if h["headTop"] < h["cardTop"] - 1 or h["headBottom"] > h["cardBottom"] + 1:
        probs.append("the head is not inside the card")
    if h["bad"]:
        probs.append(f"ancestors with overflow other than visible/clip: {h['bad']}")
    if probs:
        s.fail(f"sticky_head: {what}: " + "; ".join(probs))
        return False
    return True


CARD_JS = js(r"""
const card = document.querySelector('#part-card'), head = document.querySelector('#card-head');
const title = document.querySelector('#card-title'), ov = document.querySelector('#overview');
const close = document.querySelector('#card-close');
return { card: card ? (card.dataset.card || null) : null, cardShown: shown(card),
         cardH: card ? Math.round(card.getBoundingClientRect().height) : 0,
         headH: head && shown(head) ? Math.round(head.getBoundingClientRect().height) : 0,
         titleCard: title ? (title.dataset.card || null) : null, close: shown(close),
         ovShown: shown(ov), ovText: ov && shown(ov) ? ov.innerText : '', cardText: card && shown(card) ? card.innerText : '' };
""", "")


def card_test(s, m, r, folds):
    """Card checks. r gets default, after_close, nav, sticky, end_footer, folded, head_px."""
    r.update(default="FAIL:not-run", after_close="FAIL:not-run", nav=0, sticky=False, end_footer=False,
             folded=False, head_px=None)
    tops = m.tops
    # folded comes from the node walk
    if folds is not None:
        r["folded"] = len(folds) == len(m.ids) and len(m.ids) > 0 and all(folds.values())
        if len(folds) != len(m.ids):
            s.fail(f"folded: the folds of {len(folds)} of {len(m.ids)} panels were checked")
    if not s.open("#/"):
        return
    c = s.page.evaluate(CARD_JS)
    question = normalize(m.data.get("question", ""))
    summary = plain_text(m.data.get("summary", ""), m.titles)[:PROSE_PREFIX].strip()
    dprob = []
    if c["card"] != "overview":
        dprob.append(c["card"] or "none")
    if not c["cardShown"]:
        dprob.append("hidden")
    if not c["ovShown"]:
        dprob.append("no-overview")
    else:
        ov = normalize(c["ovText"])
        if not question or question not in ov:
            dprob.append("no-question")
        if not summary or summary not in ov:
            dprob.append("no-summary")
    if c["titleCard"] != "overview":
        dprob.append(f"card-title={c['titleCard']}")
    if c["close"]:
        dprob.append("close-on-overview")
    r["default"] = "overview" if not dprob else "FAIL:" + ",".join(dprob)
    if dprob:
        s.fail(f"card default: on #/ the card is not the overview with the model question and summary: {dprob}")
    heads = [c["headH"]]
    feet = [footer_ok(s, "#card-foot", "End of the overview.", "overview")]
    # nav: next x9, then prev x9, from the overview
    seq_next, seq_prev, heights = [], [], {}
    for direction, out in (("next", seq_next), ("prev", seq_prev)):
        if s.card_id() != "overview":
            if not s.open("#/"):
                return
        for i in range(9):
            before = s.card_id()
            btn = s.page.locator(f"#card-{direction}")
            if btn.count() != 1 or not s.click(btn, f"card nav: #card-{direction} ({i + 1})"):
                out.append(None)
                continue
            try:
                s.page.wait_for_function("(w) => { const c = document.querySelector('#part-card'); return !!c && c.dataset.card !== w; }",
                                         arg=before, timeout=3000)
            except PlaywrightError:
                pass
            s.settle(150)
            now = s.card_id()
            out.append(now)
            if direction == "next" and now in m.node:
                cc = s.page.evaluate(CARD_JS)
                heights[now] = cc["cardH"]
                heads.append(cc["headH"])
                if not cc["close"]:
                    s.fail(f"card: #card-close is not displayed on the card of {now}")
                feet.append(footer_ok(s, "#card-foot", f"End of {normalize(m.titles[now])}.", f"card {now}"))
    want_next = tops + ["overview"]
    want_prev = list(reversed(tops)) + ["overview"]
    r["nav"] = sum(1 for i in range(9) if i < len(seq_next) and i < len(seq_prev)
                   and seq_next[i] == want_next[i] and seq_prev[i] == want_prev[i])
    if seq_next != want_next[:9] or seq_prev != want_prev[:9]:
        s.fail(f"card nav: #card-next x9 gave {seq_next} (expected {want_next[:9]}); "
               f"#card-prev x9 gave {seq_prev} (expected {want_prev[:9]})")
    # after_close
    if s.open("#/") and tops:
        part = tops[1] if len(tops) > 1 else tops[0]
        aprob = []
        if open_part(s, part, "card after_close"):
            close = s.page.locator("#card-close")
            if close.count() != 1:
                aprob.append("no-close")
            elif s.click(close, "card after_close: #card-close"):
                s.wait_card("overview", 3000)
                s.settle(300)
                cc = s.page.evaluate(CARD_JS)
                if cc["card"] != "overview":
                    aprob.append(cc["card"] or "none")
                if not cc["cardShown"]:
                    aprob.append("hidden")
                if not cc["ovShown"] or not normalize(cc["ovText"]):
                    aprob.append("empty")
                if cc["close"]:
                    aprob.append("close-still-shown")
        else:
            aprob.append("part-did-not-open")
        r["after_close"] = "overview" if not aprob else "FAIL:" + ",".join(aprob)
        if aprob:
            s.fail(f"card after_close: after opening {part} and pressing #card-close: {aprob}")
    # sticky head on the largest part card, at 744 and 1440
    largest = max(heights, key=heights.get) if heights else (tops[0] if tops else None)
    sticky = []
    for size in (PRIMARY, WIDE):
        s.set_viewport(size)
        if largest and s.open("#/") and open_part(s, largest, f"sticky_head {size[0]}"):
            sticky.append(sticky_check(s, "#part-card", "#card-head", f"card of {largest} at {size[0]}x{size[1]}"))
            if size == PRIMARY:
                s.screenshot("card-sticky-744.png")
        else:
            sticky.append(False)
    s.set_viewport(PRIMARY)
    r["sticky"] = bool(sticky) and all(sticky)
    # the step card's footer (steps 1 and 2)
    T = len(m.steps)
    if s.open("#/") and s.set_mode("tour", "end_footer"):
        for k in (1, 2):
            if k > T:
                break
            try:
                s.page.wait_for_selector(f'#tour-step-title[data-step-index="{k}"]', state="attached")
            except PlaywrightError:
                s.fail(f"end_footer: step {k} did not appear")
                feet.append(False)
                break
            feet.append(footer_ok(s, "#step-foot", f"End of step {k} of {T}.", f"step card {k}"))
            if k < T and not s.click(s.page.locator("#tour-next"), "end_footer: #tour-next"):
                break
    else:
        feet.append(False)
    r["end_footer"] = len(feet) >= 1 + len(tops) + min(2, T) and all(feet)
    r["head_px"] = max(heads) if heads else None


def matrix_test(s, m, r):
    pairs = m.cross_pairs()
    r.update(cells=0, C=len(pairs), ok=False, hscroll=None, sticky=False, close_buttons=None, end_footer=False, min_px=None)
    if not s.open("#/"):
        return
    info = s.page.evaluate(MATRIX_JS)
    if info is None:
        s.fail("matrix: no #matrix table.nsq")
        return
    ok = True
    cells = {}
    for c in info["cells"]:
        if (c["from"], c["to"]) in cells:
            s.fail(f"matrix: two cells for {c['from']} -> {c['to']}")
            ok = False
        cells[(c["from"], c["to"])] = c["items"]
    good = 0
    for (a, b_), edges in sorted(pairs.items()):
        seen, want = set(), []
        for e in edges:
            if (e.get("kind"), e.get("label")) not in seen:
                seen.add((e.get("kind"), e.get("label")))
                want.append(normalize(e.get("label")))
        items = cells.get((a, b_))
        if items is None:
            s.fail(f"matrix: no cell td[data-from={a}][data-to={b_}]")
            continue
        got = [normalize(i["text"]) for i in items]
        ids = {e["id"] for e in edges}
        foreign = sorted({x for i in items for x in i["ids"] if x not in ids})
        bare = [normalize(i["text"]) for i in items if not i["ids"]]
        if sorted(got) != sorted(want) or foreign or bare:
            s.fail(f"matrix: {a} -> {b_}: shows {got}, expected {want}"
                   + (f"; names edges of other pairs {foreign}" if foreign else "")
                   + (f"; items without data-edge-ids {bare}" if bare else ""))
            continue
        good += 1
    for (a, b_), items in cells.items():
        if (a, b_) not in pairs and items:
            s.fail(f"matrix: {a} -> {b_} has no edges in the model but lists {[normalize(i['text']) for i in items]}")
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
    r["cells"] = good
    # fit at 744
    f = s.page.evaluate(MATRIX_FIT_JS)
    if f is None:
        s.fail("matrix: no #matrix")
        return
    r["hscroll"] = max(0, f["scroll"], f["over"])
    if f["scroll"] > 0:
        s.fail(f"matrix: the table's container {f['box']} scrolls sideways by {f['scroll']} px at 744")
    if f["over"] > 0:
        s.fail(f"matrix: a cell ends {f['over']} px right of the card's content box at 744")
    if f["clips"]:
        s.fail(f"matrix: ancestors of the table clip horizontally: {f['clips']}")
        ok = False
    r["min_px"] = f["minPx"]
    if f["minPx"] is not None:
        s.note(f"matrix_min_text_px={f['minPx']} at 744: {f['minWhere']!r}")
    r["close_buttons"] = len(f["buttons"])
    if f["buttons"]:
        s.fail(f"matrix: buttons in #matrix: {f['buttons']}")
    sel = m.map.get("sections") or {}
    eyebrow = normalize(((sel.get("matrix") or {}).get("eyebrow") or "")).lower()
    r["end_footer"] = bool(eyebrow) and footer_ok(s, "#matrix-foot", f"End of the {eyebrow}.", "matrix")
    sticky = []
    for size in (PRIMARY, WIDE):
        s.set_viewport(size)
        if s.open("#/"):
            sticky.append(sticky_check(s, "#matrix", "#matrix .card-head", f"matrix at {size[0]}x{size[1]}"))
        else:
            sticky.append(False)
    s.set_viewport(PRIMARY)
    r["sticky"] = all(sticky)
    r["ok"] = ok


# ---------------------------------------------------------------------------
# deeplinks, page_height, min_tap_px
# ---------------------------------------------------------------------------

LAND_JS = js(r"""
const top = sel => { const e = document.querySelector(sel); return e ? e.getBoundingClientRect().top : null; };
return { mode: document.body.dataset.mode || null, y: window.scrollY,
         max: document.documentElement.scrollHeight - window.innerHeight,
         head: top('#card-head'), section: top('#map-section'),
         card: (() => { const c = document.querySelector('#part-card'); return c ? (c.dataset.card || null) : null; })(),
         panel: (() => { const t = document.querySelector('#part-card #detail-title'); return t ? t.dataset.nodeId || null : null; })(),
         step: (() => { const t = document.querySelector('#tour-step-title'); return t && shown(t) ? t.dataset.stepIndex || null : null; })(),
         mult: [...document.querySelectorAll('#mult figure')].filter(shown).length,
         read: [...document.querySelectorAll('#read-page section[data-node-id]')].length, readShown: shown(document.querySelector('#read-page')) };
""", "")


def deeplinks_test(s, m, r):
    r.update(good=0)
    if s.broken:
        return
    lower = [i for i in m.ids if m.parent[i] is not None]
    node = sorted(lower, key=lambda i: (-m.depth(i), m.ids.index(i)))[0] if lower else None

    def section_at_top(g):
        return g["section"] is not None and (abs(g["section"]) <= 2 or (g["section"] > 0 and g["y"] >= g["max"] - 1))

    checks = []
    if node:
        checks.append((f"#/node/{node}", node))
    else:
        s.fail("deeplinks: the model has no lower node to link to")
    checks += [("#/tour/3", "tour"), ("#/compare", "compare"), ("#/read", "read")]
    for frag, what in checks:
        if not s.open(frag):
            s.broken = False  # one broken route must not stop the others
            continue
        s.settle(300)
        s.wait_scroll_stable()
        g = s.page.evaluate(LAND_JS)
        probs = []
        if frag.startswith("#/node/"):
            top = m.top(node)
            if g["mode"] != "explore":
                probs.append(f"mode {g['mode']}")
            if g["card"] != top:
                probs.append(f"card {g['card']}, expected {top}")
            sel = DETAIL.format(top)
            if s.page.locator(f'{sel} g.box.hot[data-node="{node}"], {sel} g.dgroup.hot[data-node="{node}"]').count() < 1:
                probs.append(f"{node} is not .hot in {sel}")
            if g["panel"] != node:
                probs.append(f"panel on {g['panel']}")
            if g["head"] is None or not (0 - 0.5 <= g["head"] <= DEEPLINK_HEAD_MAX):
                probs.append(f"#card-head top at {g['head']} px, expected within [0, {DEEPLINK_HEAD_MAX}]")
        elif what == "tour":
            if g["mode"] != "tour":
                probs.append(f"mode {g['mode']}")
            if g["step"] != "3":
                probs.append(f"step {g['step']}")
            if not section_at_top(g):
                probs.append(f"#map-section top at {g['section']} px (scrollY {g['y']}), expected 0")
        elif what == "compare":
            if g["mode"] != "compare":
                probs.append(f"mode {g['mode']}")
            if g["mult"] != 6:
                probs.append(f"{g['mult']} small maps displayed")
            if not section_at_top(g):
                probs.append(f"#map-section top at {g['section']} px (scrollY {g['y']}), expected 0")
        else:
            if g["mode"] != "read":
                probs.append(f"mode {g['mode']}")
            if not g["readShown"] or g["read"] < len(m.ids):
                probs.append(f"read page shown={b(g['readShown'])} with {g['read']} sections")
            if g["y"] > 2:
                probs.append(f"scrollY {g['y']}, expected the page top")
        if probs:
            s.fail(f"deeplinks: {frag}: " + "; ".join(probs))
        else:
            r["good"] += 1


MIN_TAP_JS = js(r"""
const out = [];
document.querySelectorAll('button, summary, select, input, textarea, [role=button], [role=tab], a[href]').forEach(el => {
  if (!shown(el)) return;
  if (el.tagName === 'A' && getComputedStyle(el).display === 'inline') return;  // inline text links
  if (el.closest('svg')) return;
  const r = el.getBoundingClientRect();
  out.push([Math.round(Math.min(r.width, r.height) * 10) / 10, desc(el)]);
});
const svgs = [];
document.querySelectorAll('svg [tabindex], svg [role=button]').forEach(el => {
  if (!shown(el)) return;
  const r = el.getBoundingClientRect();
  svgs.push([Math.round(Math.min(r.width, r.height) * 10) / 10, desc(el)]);
});
out.sort((a, b) => a[0] - b[0]); svgs.sort((a, b) => a[0] - b[0]);
return { html: out.slice(0, 5), svg: svgs.slice(0, 3) };
""", "")


def page_height_test(s, m, r):
    r.update(height=None, tap=None)
    if not s.open("#/"):
        return
    s.settle(300)
    r["height"] = s.page.evaluate("() => document.documentElement.scrollHeight")
    if r["height"] > PAGE_HEIGHT_MAX:
        s.fail(f"page_height: the page is {r['height']} px tall at 744x1000 on #/, the limit is {PAGE_HEIGHT_MAX}")
    smallest, svg_small = [], []
    states = [("overview", None)]
    if m.tops:
        states.append(("part", lambda: open_part(s, m.tops[0], "min_tap_px")))
    states += [("tour", lambda: s.set_mode("tour", "min_tap_px")), ("compare", lambda: s.set_mode("compare", "min_tap_px"))]
    for name, go in states:
        if go is not None and not go():
            continue
        g = s.page.evaluate(MIN_TAP_JS)
        smallest += [(px, f"{name}: {d}") for px, d in g["html"]]
        svg_small += [(px, f"{name}: {d}") for px, d in g["svg"]]
    smallest.sort()
    svg_small.sort()
    if smallest:
        r["tap"] = smallest[0][0]
        s.note("min_tap_px: smallest controls at 744x1000: " + "; ".join(f"{px} px {d}" for px, d in smallest[:5]))
    if svg_small:
        s.note("min_tap_px: smallest controls in the drawings (not counted): "
               + "; ".join(f"{px} px {d}" for px, d in svg_small[:3]))


# ---------------------------------------------------------------------------
# scroll_jumps: no in-page click moves the page
# ---------------------------------------------------------------------------

POS_JS = js(r"""
const el = args;
const alive = !!el && el.isConnected && shown(el);
return { y: window.scrollY, top: alive ? el.getBoundingClientRect().top : null, alive };
""")

# A point of the element that the element itself (or a child) receives, in the
# viewport; for an SVG group (a box, a tag) the points are taken in its own rect.
HIT_JS = r"""
(el) => {
  const shape = el instanceof SVGGElement ? (el.querySelector(':scope > rect') || el.querySelector('rect') || el) : el;
  const r = shape.getBoundingClientRect();
  const pts = [[.5, .5], [.3, .5], [.7, .5], [.5, .3], [.5, .7], [.15, .2], [.85, .8], [.1, .5], [.9, .5]];
  for (const [fx, fy] of pts) {
    const x = r.left + r.width * fx, y = r.top + r.height * fy;
    if (x < 0 || y < 0 || x >= window.innerWidth || y >= window.innerHeight) continue;
    const t = document.elementFromPoint(x, y);
    if (t && (t === el || el.contains(t))) return [x, y];
  }
  return null;
}
"""

MOVES_PAGE_JS = js(r"""
const bad = [], missing = [];
let n = 0;
document.querySelectorAll('[data-moves-page]').forEach(el => {
  n++;
  const ok = el.matches('a.back-to-map') || el.matches('button.open-part') || el.matches('#mult figure') ||
    (el.matches('a[href^="#/node/"]') && !!el.closest('#part-card, #step-card')) ||
    (el.matches('a[href^="#/"]') && !!el.closest('#read-page'));
  if (!ok) bad.push(desc(el));
});
document.querySelectorAll('a.back-to-map, button.open-part, #mult figure').forEach(el => { if (!el.hasAttribute('data-moves-page')) missing.push(desc(el)); });
return { n, bad, missing };
""", "")


class Jumps:
    def __init__(self, size):
        self.size = size
        self.n = 0
        self.jumps = []
        self.moved = []
        self.moves_bad = set()
        self.moves_missing = set()
        self.moves_checked = 0


def moves_page(s, rec, where):
    g = s.page.evaluate(MOVES_PAGE_JS)
    rec.moves_checked += 1
    rec.moves_bad.update(f"{d} ({where})" for d in g["bad"])
    rec.moves_missing.update(f"{d} ({where})" for d in g["missing"])


def press(s, rec, loc, name, key=None):
    """One recorded activation: scroll the control into view, record scrollY, click (or key), settle, compare."""
    try:
        if loc.count() == 0:
            s.fail(f"scroll_jumps {rec.size[0]}: {name}: not found")
            return False
        loc = loc.first
        if loc.get_attribute("data-moves-page") is not None:
            s.note(f"scroll_jumps {rec.size[0]}: {name}: skipped ([data-moves-page])")
            return False
        loc.scroll_into_view_if_needed(timeout=2000)
        handle = loc.element_handle(timeout=2000)
    except PlaywrightError as exc:
        s.fail(f"scroll_jumps {rec.size[0]}: {name}: {first_line(exc)}")
        return False
    s.page.evaluate(RAF2_JS)
    s.page.wait_for_timeout(80)
    before = s.page.evaluate(POS_JS, handle)
    try:
        if key:
            s.page.evaluate("(el) => el.focus({ preventScroll: true })", handle)
            s.page.keyboard.press(key)
        else:
            pt = s.page.evaluate(HIT_JS, handle)
            if pt is None:
                handle.dispatch_event("click")
                s.note(f"scroll_jumps {rec.size[0]}: {name}: no point of it receives a click (covered or "
                       f"out of view); dispatched a click event")
            else:
                s.page.mouse.click(pt[0], pt[1])
    except PlaywrightError as exc:
        s.fail(f"scroll_jumps {rec.size[0]}: {name}: cannot activate: {first_line(exc)}")
        return False
    s.page.evaluate(JUMP_SETTLE_JS)
    after = s.page.evaluate(POS_JS, handle)
    rec.n += 1
    if abs(after["y"] - before["y"]) > 1:
        rec.jumps.append(f"{name} (scrollY {round(before['y'])} -> {round(after['y'])})")
    if after["alive"] and before["top"] is not None and abs(after["top"] - before["top"]) > 2:
        rec.moved.append(f"{name} ({round(before['top'])} -> {round(after['top'])})")
    return True


CARD_TOP_JS = """(off) => { const c = document.querySelector('#part-card'); if (!c) return null;
  const y = c.getBoundingClientRect().top + window.scrollY + off; window.scrollTo({ top: y, behavior: 'instant' }); return window.scrollY; }"""
NEAR_FOOT_JS = """() => { const c = document.querySelector('#part-card'); if (!c) return null;
  c.querySelectorAll('details').forEach(d => { d.open = true; });
  const f = document.querySelector('#card-foot') || c;
  const y = f.getBoundingClientRect().bottom + window.scrollY - window.innerHeight + 20;
  window.scrollTo({ top: y, behavior: 'instant' }); return window.scrollY; }"""


def scroll_jumps_test(s, m, size):
    rec = Jumps(size)
    s.set_viewport(size)
    if not s.open("#/"):
        return rec
    P = s.page
    tag = f"{size[0]}"
    moves_page(s, rec, "overview")
    # 1. Emphasize chips (each kind, then All)
    kinds = P.evaluate("() => [...document.querySelectorAll('#chips button.chip[data-kind]')].map(b => b.dataset.kind)")
    for kind in [k for k in kinds if k != "all"] + (["all"] if "all" in kinds else []):
        press(s, rec, P.locator(f'#chips button.chip[data-kind="{kind}"]'), f"chip {kind}")
    # 2. every map part; per part a detail box, a group, every tag
    heights = {}
    for part in m.tops:
        if not press(s, rec, part_box_locator(s, part), f"map part {part}"):
            continue
        if not s.wait_card(part, 3000):
            s.fail(f"scroll_jumps {tag}: clicking the map box of {part} left the card on {s.card_id()}")
            continue
        heights[part] = P.evaluate("() => document.querySelector('#part-card').getBoundingClientRect().height")
        if part == m.tops[0]:
            moves_page(s, rec, f"card {part}")
        if part not in m.parts_with_children or not s.wait_detail(part):
            continue
        d = DETAIL.format(part)
        press(s, rec, P.locator(f"{d} g.box[data-node]"), f"detail box in {part}")
        if P.locator(f"{d} g.dgroup[data-node] rect.gtitle").count():
            press(s, rec, P.locator(f"{d} g.dgroup[data-node] rect.gtitle"), f"group in {part}")
        stubs = P.evaluate("(sel) => [...document.querySelectorAll(sel + ' g.stub[data-other]')].map(g => [g.dataset.other, g.dataset.dir || ''])", d)
        for i, (other, direction) in enumerate(stubs):
            if s.card_id() != part:
                if not press(s, rec, part_box_locator(s, part), f"map part {part} (again)") or not s.wait_card(part, 3000):
                    break
                s.wait_detail(part)
            sel = f'{d} g.stub[data-other="{other}"]' + (f'[data-dir="{direction}"]' if direction else "")
            press(s, rec, P.locator(sel), f"tag {part}->{other}/{direction}")
    # 3. Close, then the card arrows from the overview (next x9, prev x9)
    if s.card_id() != "overview" and P.locator("#card-close").count():
        press(s, rec, P.locator("#card-close"), "card close")
    for direction in ("next", "prev"):
        for i in range(9):
            press(s, rec, P.locator(f"#card-{direction}"), f"card {direction} {i + 1}")
    # 4. D3: arrows and Close with the head stuck (card top 300 px above the viewport), and Close near the footer
    largest = max(heights, key=heights.get) if heights else None
    if largest:
        for btn in ("next", "prev", "close"):
            if s.card_id() != largest:
                if not press(s, rec, part_box_locator(s, largest), f"map part {largest} (for stuck {btn})"):
                    continue
                s.wait_card(largest, 3000)
            P.evaluate(CARD_TOP_JS, STICKY_OFFSET)
            s.settle(150)
            press(s, rec, P.locator(f"#card-{btn}"), f"card {btn} with the head stuck ({largest})")
        if press(s, rec, part_box_locator(s, largest), f"map part {largest} (for close near the footer)"):
            s.wait_card(largest, 3000)
            P.evaluate(NEAR_FOOT_JS)
            s.settle(200)
            press(s, rec, P.locator("#card-close"), f"card close near the footer, folds open ({largest})")
    # 5. Full size (map), twice
    fs = P.locator('#bar-map button.fullsize[aria-controls="map"]')
    if fs.count() != 1:
        s.fail(f"scroll_jumps {tag}: {fs.count()} buttons #bar-map button.fullsize[aria-controls=map], expected 1")
    else:
        press(s, rec, fs, "full size map")
        press(s, rec, fs, "full size map (again)")
    # 6. keyboard: Enter on a focused map box and on a detail tag
    if m.tops:
        if press(s, rec, part_box_locator(s, m.tops[-1]), f"Enter on map box {m.tops[-1]}", key="Enter") \
                and s.card_id() != m.tops[-1]:
            s.note(f"scroll_jumps {tag}: Enter on the focused map box of {m.tops[-1]} did not open its card "
                   f"(card {s.card_id()})")
        for part in m.parts_with_children:
            d = DETAIL.format(part)
            if s.card_id() != part:
                if not press(s, rec, part_box_locator(s, part), f"map part {part} (for Enter on a tag)"):
                    break
                s.wait_card(part, 3000)
                s.wait_detail(part)
            if P.locator(f"{d} g.stub[data-other]").count():
                press(s, rec, P.locator(f"{d} g.stub[data-other]"), f"Enter on a tag in {part}", key="Enter")
                break
    # 7. modes: tour (pips, Back, Next, views, rows), compare, explore
    if press(s, rec, P.locator(MODE_BUTTON.format("tour")), "mode tour"):
        s.settle(200)
        moves_page(s, rec, "tour")
        n_pips = P.locator("#pips button.pip").count()
        for i in range(n_pips):
            press(s, rec, P.locator("#pips button.pip").nth(i), f"pip {i + 1}")
        press(s, rec, P.locator("#tour-prev"), "tour Back")
        press(s, rec, P.locator("#tour-next"), "tour Next")
        if press(s, rec, P.locator(VIEW_BUTTON.format("seq")), "view seq"):
            for k in range(1, len(m.steps) + 1):
                press(s, rec, P.locator(f'{SEQ} .row[data-step-index="{k}"]'), f"sequence row {k}")
            if m.steps:
                press(s, rec, P.locator(f'{SEQ} .row[data-step-index="1"]'), "Enter on sequence row 1", key="Enter")
            sfs = P.locator('button.fullsize[aria-controls="seq"]')
            if sfs.count() != 1:
                s.fail(f"scroll_jumps {tag}: {sfs.count()} buttons button.fullsize[aria-controls=seq], expected 1")
            else:
                press(s, rec, sfs, "full size sequence")
                press(s, rec, sfs, "full size sequence (again)")
            press(s, rec, P.locator(VIEW_BUTTON.format("map")), "view map")
    if press(s, rec, P.locator(MODE_BUTTON.format("compare")), "mode compare"):
        s.settle(200)
        moves_page(s, rec, "compare")
    press(s, rec, P.locator(MODE_BUTTON.format("explore")), "mode explore")
    # 8. help, last
    if press(s, rec, P.locator("#help-toggle"), "help toggle"):
        s.settle(200)
        if P.locator("#help-close").count() and P.locator("#help-close").first.is_visible():
            press(s, rec, P.locator("#help-close"), "help close")
        else:
            press(s, rec, P.locator("#help-toggle"), "help toggle (close)")
    for j in rec.jumps:
        s.fail(f"scroll_jumps {size[0]}x{size[1]}: the page moved after {j}")
    for d in sorted(rec.moves_bad):
        s.fail(f"scroll_jumps {size[0]}x{size[1]}: [data-moves-page] on a control that may not move the page: {d}")
    for d in sorted(rec.moves_missing):
        s.fail(f"scroll_jumps {size[0]}x{size[1]}: no [data-moves-page] on {d}")
    if rec.moved:
        s.note(f"control_moved {size[0]}x{size[1]}: " + "; ".join(rec.moved[:20])
               + (f" (+{len(rec.moved) - 20} more)" if len(rec.moved) > 20 else ""))
    if rec.n < SCROLL_JUMPS_MIN:
        s.fail(f"scroll_jumps {size[0]}x{size[1]}: only {rec.n} clicks, at least {SCROLL_JUMPS_MIN} needed")
    return rec


def moves_ok(rec):
    return rec.moves_checked > 0 and not rec.moves_bad and not rec.moves_missing


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

SECTIONS = ("map-section", "matrix")

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

# The "Full size" toggles (button.fullsize[aria-controls]) and the figures they size.
FULLSIZE = (("map", MAP, '#bar-map button.fullsize[aria-controls="map"]'),
            ("sequence", SEQ, 'button.fullsize[aria-controls="seq"]'))

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
    """At 744x1000: the two Full size toggles. Return ({name: 'ok'|'fail'}, problems)."""
    result, problems = {}, []
    s = Session(browser, url, screenshot_dir, PRIMARY)

    def fitted(name, sel, when):
        g = s.page.evaluate(SHEET_JS, sel)
        if g is None:
            return [f"fullsize {name}: no {sel}"]
        out = []
        if g["scroll"] > 0:
            out.append(f"fullsize {name} {when}: the sheet scrolls by {g['scroll']} px ({g['scrolls']}), expected fitted")
        if g["room"] is not None and g["width"] > g["room"] + 1:
            out.append(f"fullsize {name} {when}: the svg is {g['width']} px wide, the sheet has {g['room']} px")
        return out

    for name, sel, btn_sel in FULLSIZE:
        bad = []
        if not s.open("#/"):
            result[name] = "fail"
            continue
        s.page.evaluate(FONTS_READY_JS)
        s.settle(300)
        if name == "sequence" and not (s.set_mode("tour", "fullsize") and s.set_view("seq", "fullsize")):
            result[name] = "fail"
            continue
        btn = s.page.locator(btn_sel)
        if btn.count() != 1:
            bad.append(f"fullsize {name}: {btn.count()} buttons {btn_sel}, expected 1")
        elif btn.get_attribute("aria-pressed") != "false":
            bad.append(f"fullsize {name}: aria-pressed is {btn.get_attribute('aria-pressed')!r} on load, expected 'false'")
        else:
            bad += fitted(name, sel, "on load")
            btn.scroll_into_view_if_needed()
            if s.click(btn, btn_sel):
                s.settle(300)
                g = s.page.evaluate(SHEET_JS, sel)
                if btn.get_attribute("aria-pressed") != "true":
                    bad.append(f"fullsize {name}: after a click aria-pressed is {btn.get_attribute('aria-pressed')!r}, expected 'true'")
                if g is None:
                    bad.append(f"fullsize {name}: no {sel} when pressed")
                else:
                    if g["vbw"] is None or abs(g["width"] - g["vbw"]) > 1:
                        bad.append(f"fullsize {name} pressed: the svg is {g['width']} px wide, its viewBox {g['vbw']} units")
                    if g["scroll"] <= 0:
                        bad.append(f"fullsize {name} pressed: the sheet does not scroll ({g['scrolls'] or 'no scroll container'})")
                    if g["page"] > 0:
                        bad.append(f"fullsize {name} pressed: the page scrolls horizontally by {g['page']} px")
                s.screenshot(f"fullsize-{name}.png")
                if s.click(btn, f"{btn_sel} (again)"):
                    s.settle(300)
                    if btn.get_attribute("aria-pressed") != "false":
                        bad.append(f"fullsize {name}: after a second click aria-pressed is {btn.get_attribute('aria-pressed')!r}")
                    bad += fitted(name, sel, "unpressed again")
        result[name] = "fail" if bad else "ok"
        problems += bad
    problems += [f"fullsize: {x}" for x in s.failures + s.console_problems]
    s.page.close()
    return result, problems


def layout_test(browser, url, screenshot_dir, m):
    """Run the --layout checks; return (lines to print, ok, problems)."""
    out, ok, problems = [], True, []
    snaps = {}
    for w, h in (PRIMARY, WIDE):
        s = Session(browser, url, screenshot_dir, (w, h))
        if s.open("#/"):
            s.page.evaluate(FONTS_READY_JS)
            s.settle(300)
            snaps[w] = s.page.evaluate(LAYOUT_JS, MAP)
            if snaps[w] is None:
                s.fail(f"layout: no {MAP} at {w}x{h}")
        problems += [f"layout {w}x{h}: {x}" for x in s.failures + s.console_problems]
        s.page.close()
    a, b_ = snaps.get(744), snaps.get(1440)
    identical = bool(a and b_)
    nparts = 0
    if a and b_:
        nparts = len(set(a["parts"]) & set(b_["parts"]))
        for p in sorted(set(a["parts"]) | set(b_["parts"])):
            ra, rb = a["parts"].get(p), b_["parts"].get(p)
            if ra is None or rb is None or any(abs(x - y) > 0.5 for x, y in zip(ra, rb)):
                problems.append(f"layout: part {p} union box 744: {ra} 1440: {rb}")
                identical = False
        if a["texts"] != b_["texts"]:
            only_a = sorted(set(a["texts"]) - set(b_["texts"]))
            only_b = sorted(set(b_["texts"]) - set(a["texts"]))
            problems.append(f"layout: map texts differ; only at 744: {only_a[:10]}; only at 1440: {only_b[:10]}")
            identical = False
        if a["visible"] != b_["visible"]:
            problems.append(f"layout: visible map elements 744: {a['visible']}, 1440: {b_['visible']}")
            identical = False
    out.append(f"layout_identical={b(identical)} parts={nparts}")
    if not identical or nparts != len(m.tops):
        ok = False
    other = m.parts_with_children[1] if len(m.parts_with_children) > 1 else (m.tops[0] if m.tops else None)
    for w, h in ((400, 900), PRIMARY, WIDE):
        s = Session(browser, url, screenshot_dir, (w, h))
        s.model_parts_with_children = m.parts_with_children
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
                g = s.page.evaluate(SHEET_JS, MAP)
                if g is None:
                    problems.append(f"layout 744: no {MAP}")
                    ok = False
                elif g["scroll"] > 0:
                    problems.append(f"layout 744: the map sheet scrolls horizontally by {g['scroll']} px "
                                    f"({g['scrolls']}); it must fit")
                    ok = False
            s.screenshot(f"layout-{w}.png")
            states = []
            if other:
                states.append(("a part opened", lambda: open_part(s, other, "layout")))
            states += [("tour step 2", lambda: s.set_mode("tour", "layout") and s.click(s.page.locator("#tour-next"), "layout: #tour-next")),
                       ("the sequence view", lambda: s.set_view("seq", "layout")),
                       ("compare", lambda: s.set_mode("compare", "layout"))]
            for what, go in states:
                try:
                    if go():
                        s.settle(300)
                        worst = max(worst, s.page.evaluate(HSCROLL_JS))
                    else:
                        s.fail(f"could not reach {what}")
                except PlaywrightError as exc:
                    s.fail(f"could not reach {what}: {first_line(exc)}")
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
    out.append("fullsize " + " ".join(f"{name}={state}" for name, state in sizes.items()))
    if any(state != "ok" for state in sizes.values()) or len(sizes) != len(FULLSIZE):
        ok = False
    problems += size_problems
    return out, ok, problems


# ---------------------------------------------------------------------------
# Check one node / one edge
# ---------------------------------------------------------------------------

def in_detail_now(s, m, node_id):
    top = m.top(node_id)
    if node_id != top:
        sel = DETAIL.format(top)
        return s.page.locator(f'{sel} g.box[data-node="{node_id}"], {sel} g.dgroup[data-node="{node_id}"]').count() >= 1
    if m.children.get(top):
        return s.card_id() == top and s.page.locator(DETAIL.format(top)).count() == 1
    return s.card_id() == top


def check_node(s, m, node_id, expect_title, expect_prose):
    title_ok = prose_ok = in_detail = True
    if node_id not in m.node:
        s.fail(f"check-node: {node_id!r} is not a node of the model")
        return False, False, False

    def check_here(how):
        nonlocal title_ok, prose_ok, in_detail
        if not s.wait_panel(node_id):
            s.fail(f"check-node ({how}): #part-card #detail-title names {s.panel_node()!r}, expected {node_id!r}")
            title_ok = prose_ok = False
        else:
            p = s.page.evaluate(PANEL_JS)
            want = normalize(expect_title)
            if p["vh"]:
                good = normalize(p["title"]) == want and normalize(p["card"]) == want
                shown_title = f"{normalize(p['title'])!r} (visually hidden), #card-title {normalize(p['card'])!r}"
            else:
                good = p["titleShown"] and normalize(p["title"]) == want
                shown_title = repr(normalize(p["title"])) + ("" if p["titleShown"] else " (not displayed)")
            if not good:
                s.fail(f"check-node ({how}): title is {shown_title}, expected {expect_title!r}")
                title_ok = False
            if normalize(expect_prose) not in normalize(p["prose"]):
                s.fail(f"check-node ({how}): prose does not contain {expect_prose!r}")
                prose_ok = False
        if not in_detail_now(s, m, node_id):
            s.fail(f"check-node ({how}): {node_id} is not drawn in {DETAIL.format(m.top(node_id))} "
                   f"(card {s.card_id()})")
            in_detail = False

    # 1. deep link
    if not s.open(f"#/node/{node_id}"):
        return False, False, False
    check_here("deep link")
    # 2. clicking: the map box of the top part, then the node in its detail
    if not s.open("#/"):
        return False, False, False
    top = m.top(node_id)
    if not open_part(s, top, "check-node"):
        return False, prose_ok, False
    if node_id != top and not click_in_detail(s, top, node_id, "check-node"):
        return False, prose_ok, False
    check_here("click")
    return title_ok, prose_ok, in_detail


def check_edge(s, m, edge_id):
    edge = m.edge.get(edge_id)
    if edge is None:
        s.fail(f"check-edge: {edge_id!r} is not an edge of the model between two nodes")
        return False
    a, b_ = m.top(edge["from"]), m.top(edge["to"])
    sel_id = f'[data-edge-ids~="{edge_id}"]'
    if a == b_:
        if a in (edge["from"], edge["to"]):
            s.fail(f"check-edge: {edge_id} connects the part {a} with its own descendant; the viewer does not draw it")
            return False
        if not s.open("#/") or not open_part(s, a, "check-edge"):
            s.fail(f"check-edge: cannot open the detail of {a}")
            return False
        if s.page.locator(f"{DETAIL.format(a)} path.ln{sel_id}").count() < 1:
            s.fail(f"check-edge: no path.ln{sel_id} in the detail of {a}")
            return False
        return True
    lower = [(end, part, other, d) for end, part, other, d in
             ((edge["from"], a, b_, "out"), (edge["to"], b_, a, "in")) if end != part]
    if not lower:
        if not s.open("#/"):
            return False
        on_map = s.page.locator(f"{MAP} path.ln{sel_id}").count()
        in_cell = s.page.locator(f'#matrix td[data-from="{a}"][data-to="{b_}"] .ni{sel_id}').count()
        if not (on_map or in_cell):
            s.fail(f"check-edge: {edge_id} ({a} -> {b_}) is neither a map line ({MAP} path.ln{sel_id}) "
                   f"nor a matrix relation")
            return False
        return True
    drawn = True
    for end, part, other, d in lower:
        if not s.open("#/") or not open_part(s, part, "check-edge"):
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
    if len(s.notes) > MAX_PRINTED_PROBLEMS:
        print(f"NOTE: ... and {len(s.notes) - MAX_PRINTED_PROBLEMS} more")


def full_run(browser, url, screenshot_dir, m, only=None):
    """The full run (or the --only groups). Returns True iff every selected check passes."""
    s = Session(browser, url, screenshot_dir, PRIMARY)
    s.model_parts_with_children = m.parts_with_children
    sel = set(only) if only else set(GROUPS)
    R = {g: {} for g in GROUPS}
    R["map_first"] = {"744": {}, "1440": {}}
    R["scroll_jumps"] = {}
    times = []

    def run(group, func):
        if group not in sel:
            return
        t0 = time.time()
        s.set_viewport(PRIMARY)
        broken = s.broken
        try:
            func()
        except PlaywrightError as exc:
            s.fail(f"{group}: stopped: {first_line(exc)}")
        except Exception as exc:  # noqa: BLE001 - a test bug must not hide the other groups
            s.fail(f"{group}: test error: {type(exc).__name__}: {exc}")
        s.broken = broken or s.broken
        times.append((group, time.time() - t0))

    run("nodes", lambda: drill_test(s, m, R["nodes"]))
    run("tour", lambda: tour_test(s, m, R["tour"]))
    run("smoke", lambda: smoke_test(s, m, R["smoke"]))
    run("map_first", lambda: (map_first_test(s, m, PRIMARY, R["map_first"]["744"]),
                              map_first_test(s, m, WIDE, R["map_first"]["1440"])))
    run("modes", lambda: modes_test(s, m, R["modes"]))
    run("map", lambda: map_test(s, m, R["map"]))
    run("detail", lambda: detail_test(s, m, R["detail"]))
    run("multiples", lambda: multiples_test(s, m, R["multiples"]))
    run("sequence", lambda: sequence_test(s, m, R["sequence"]))
    run("emphasize", lambda: emphasize_test(s, m, R["emphasize"]))

    def card_group():
        folds = R["nodes"].get("folds")
        if folds is None:  # --only without nodes: walk the nodes for the folds alone
            tmp = {}
            n_fail = len(s.failures)
            drill_test(s, m, tmp)
            s.failures[n_fail:] = [f for f in s.failures[n_fail:] if f.startswith("folded")]
            folds = tmp.get("folds")
        card_test(s, m, R["card"], folds)

    run("card", card_group)
    run("matrix", lambda: matrix_test(s, m, R["matrix"]))
    run("deeplinks", lambda: deeplinks_test(s, m, R["deeplinks"]))
    run("page_height", lambda: page_height_test(s, m, R["page_height"]))

    def jumps_group():
        R["scroll_jumps"]["744"] = scroll_jumps_test(s, m, PRIMARY)
        R["scroll_jumps"]["1440"] = scroll_jumps_test(s, m, WIDE)

    run("scroll_jumps", jumps_group)
    s.set_viewport(PRIMARY)

    errors = len(s.console_problems)
    T = len(m.steps)
    print_problems(s, [f"third-party request: {u}" for u in s.third_party])
    oks = []
    if "nodes" in sel or "tour" in sel:
        nv = R["nodes"].get("visited", 0) if "nodes" in sel else "-"
        ts = R["tour"].get("steps_ok", 0) if "tour" in sel else "-"
        print(f"nodes_visited={nv}/{len(m.ids)} tour_steps={ts}/{T} console_errors={errors}")
    if "nodes" in sel:
        oks.append(len(m.ids) > 0 and R["nodes"].get("visited") == len(m.ids))
    if "smoke" in sel:
        print(smoke_line(R["smoke"], len(s.third_party)))
        oks.append(smoke_ok(R["smoke"]) and not s.third_party)
    if "map_first" in sel:
        for key, size in (("744", PRIMARY), ("1440", WIDE)):
            g = R["map_first"][key]
            names = ",".join(g.get("names") or []) if g.get("names") is not None else "unknown"
            print(f"map_first viewport={size[0]}x{size[1]} map_top={g.get('top')} map_bottom={g.get('bottom')} "
                  f"frame_top={g.get('frame')} above_map={names or 'none'}")
            oks.append(bool(g.get("ok")))
    if "modes" in sel:
        g = R["modes"]
        print(f"modes={g.get('M', 0)} full_maps={g.get('F', 0)}")
        c = g.get("counts") or {}
        print("full_map_count " + " ".join(f"{k}={c.get(k, '-')}" for k in ("explore", "tour_map", "tour_seq", "compare"))
              + f" displayed={','.join(g.get('displayed') or []) or 'none'}")
        oks.append(bool(g.get("ok")))
    if "map" in sel:
        g = R["map"]
        print(f"map parts={g.get('parts', 0)}/{g.get('P0', len(m.tops))} lanes={g.get('lanes', 0)} bands={g.get('bands', 0)} "
              f"columns={g.get('columns', 0)} boxes={g.get('boxes', 0)}/{g.get('Q', 0)}")
        oks.append(bool(g.get("ok")) and g.get("parts") == g.get("P0") and g.get("P0", 0) > 0
                   and g.get("boxes") == g.get("Q") and g.get("Q", 0) > 0)
    if "detail" in sel:
        g = R["detail"]
        print(f"detail opened={g.get('opened', 0)}/{g.get('P', len(m.parts_with_children))}")
        oks.append(g.get("P", 0) > 0 and g.get("opened") == g.get("P"))
    if "tour" in sel:
        g = R["tour"]
        print(f"tour steps={g.get('steps_ok', 0)}/{T} highlighted={g.get('highlighted', 0)}/{T} "
              f"on_main_map={g.get('on_main', 0)}/{T} tag_clear={g.get('tag_clear', 0)}/{T}")
        print(f"tour_card text={g.get('text', 0)}/{T} detail={g.get('detail', 0)}/{T}")
        fit = g.get("fit") or {}
        print(f"tour_fit viewport={PRIMARY[0]}x{PRIMARY[1]} tourbar_bottom={fit.get('tourbar')} step_title_bottom={fit.get('title')}")
        oks.append(T > 0 and all(g.get(k) == T for k in ("steps_ok", "highlighted", "on_main", "tag_clear", "text", "detail")))
    if "multiples" in sel:
        g = R["multiples"]
        print(f"multiples panels={g.get('panels', 0)}/{g.get('total', 6)} mode={g.get('mode', 'FAIL:not-run')}")
        oks.append(g.get("total") == 6 and g.get("panels") == 6 and g.get("mode") == "compare")
    if "sequence" in sel:
        g = R["sequence"]
        print(f"sequence rows={g.get('rows', 0)}/{T} mode={g.get('mode', 'FAIL:not-run')}")
        oks.append(T > 0 and g.get("rows") == T and g.get("mode") == "tour")
    if "emphasize" in sel:
        g = R["emphasize"]
        print(f"emphasize captions={g.get('good', 0)}/{g.get('K', 0)} hidden_ok={b(g.get('hidden_ok'))}")
        oks.append(g.get("K", 0) > 0 and g.get("good") == g.get("K") and bool(g.get("hidden_ok")))
    if "card" in sel:
        g = R["card"]
        print(f"card default={g.get('default', 'FAIL:not-run')} after_close={g.get('after_close', 'FAIL:not-run')} "
              f"nav={g.get('nav', 0)}/9 sticky_head={b(g.get('sticky'))} end_footer={b(g.get('end_footer'))} "
              f"folded={b(g.get('folded'))}")
        print(f"card_head_px={g.get('head_px')}")
        oks.append(g.get("default") == "overview" and g.get("after_close") == "overview" and g.get("nav") == 9
                   and all(bool(g.get(k)) for k in ("sticky", "end_footer", "folded")))
    if "matrix" in sel:
        g = R["matrix"]
        print(f"matrix cells={g.get('cells', 0)}/{g.get('C', 0)} hscroll={g.get('hscroll')} sticky_head={b(g.get('sticky'))} "
              f"close_buttons={g.get('close_buttons')} end_footer={b(g.get('end_footer'))}")
        print(f"matrix_min_text_px={g.get('min_px')}")
        oks.append(bool(g.get("ok")) and g.get("C", 0) > 0 and g.get("cells") == g.get("C") and g.get("hscroll") == 0
                   and bool(g.get("sticky")) and g.get("close_buttons") == 0 and bool(g.get("end_footer")))
    if "deeplinks" in sel:
        print(f"deeplinks={R['deeplinks'].get('good', 0)}/4")
        oks.append(R["deeplinks"].get("good") == 4)
    if "page_height" in sel:
        g = R["page_height"]
        print(f"page_height={g.get('height')}")
        print(f"min_tap_px={g.get('tap')}")
        oks.append(g.get("height") is not None and g["height"] <= PAGE_HEIGHT_MAX)
    if "scroll_jumps" in sel:
        for key, size in (("744", PRIMARY), ("1440", WIDE)):
            rec = R["scroll_jumps"].get(key) or Jumps(size)
            print(f"scroll_jumps={len(rec.jumps)}/{rec.n} viewport={size[0]}x{size[1]} moves_page_ok={b(moves_ok(rec))} "
                  f"control_moved={len(rec.moved)}/{rec.n}")
            oks.append(not rec.jumps and rec.n >= SCROLL_JUMPS_MIN and moves_ok(rec))
    print(f"console_errors={errors}")
    print("elapsed " + ",".join(f"{g}={t:.0f}" for g, t in times))
    s.page.close()
    return all(oks) and bool(oks) and errors == 0 and not s.third_party


def parse_only(text, parser):
    out = []
    for g in (text or "").split(","):
        g = g.strip()
        if not g:
            continue
        g = ALIASES.get(g, g)
        if g not in GROUPS:
            parser.error(f"--only: unknown group {g!r}; groups: {', '.join(GROUPS)}; aliases: "
                         + ", ".join(f"{k}={v}" for k, v in ALIASES.items()))
        out.append(g)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="Browser test of the design model viewer.")
    parser.add_argument("--url", required=True, help="viewer URL, e.g. http://127.0.0.1:8000/")
    parser.add_argument("--headed", action="store_true", help="show the browser window")
    parser.add_argument("--screenshot-dir", default=None)
    parser.add_argument("--check-node", default=None, metavar="ID")
    parser.add_argument("--expect-title", default=None)
    parser.add_argument("--expect-prose", default=None)
    parser.add_argument("--check-edge", default=None, metavar="ID")
    parser.add_argument("--layout", action="store_true", help="run the layout checks (widths, hscroll, full size)")
    parser.add_argument("--only", default=None, metavar="GROUP[,GROUP]",
                        help="run only these check groups of the full run: " + ", ".join(GROUPS))
    parser.add_argument("--full", action="store_true",
                        help="with --check-node, --check-edge or --layout: also run the full test")
    args = parser.parse_args(argv)
    if args.check_node and (args.expect_title is None or args.expect_prose is None):
        parser.error("--check-node needs --expect-title and --expect-prose")
    only = parse_only(args.only, parser) if args.only else None

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
                s.model_parts_with_children = m.parts_with_children
                title_ok, prose_ok, in_detail = check_node(s, m, args.check_node, args.expect_title, args.expect_prose)
                errors = len(s.console_problems)
                print_problems(s)
                print(f"check_node id={args.check_node} title_ok={b(title_ok)} prose_ok={b(prose_ok)} "
                      f"in_detail={b(in_detail)} console_errors={errors}")
                if not (title_ok and prose_ok and in_detail and errors == 0):
                    exit_code = 1
                s.page.close()
            if args.check_edge:
                s = Session(browser, url, args.screenshot_dir)
                s.model_parts_with_children = m.parts_with_children
                drawn = check_edge(s, m, args.check_edge)
                errors = len(s.console_problems)
                print_problems(s)
                print(f"check_edge id={args.check_edge} drawn={b(drawn)} console_errors={errors}")
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
            if not (args.check_node or args.check_edge or args.layout) or args.full or only:
                if not full_run(browser, url, args.screenshot_dir, m, only):
                    exit_code = 1
        finally:
            browser.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
