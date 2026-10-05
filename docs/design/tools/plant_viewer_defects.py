#!/usr/bin/env python3
"""Plant known defects in a COPY of the viewer, to show that the browser test catches them.

Usage:
    python docs/design/tools/plant_viewer_defects.py COPY_DIR KIND [KIND ...]

COPY_DIR is a copy of docs/design (at least index.html, viewer.js and
viewer.css); the script edits COPY_DIR in place and refuses to touch the
viewer next to this script. Several KINDs may be planted in one call (one
after the other, in the order given). The six kinds of the map-modes checks,
each caught by one check of the full run (browser_test.py):

  map-below-fold       the card (#part-card, the overview on #/) is moved
                       above the mode switch, so the map is pushed below the
                       first screen; map_first fails (above_map names
                       part-card, map_bottom > 1000 at 744x1000).
  second-map           a second full-size map (a copy of #map svg.map) is
                       put right after the map once the page is ready;
                       full_maps=2.
  card-empty-on-close  pressing Close hides the card instead of showing the
                       overview; card after_close=FAIL:hidden.
  click-scrolls        an Emphasize chip click scrolls the card into view
                       (smooth scrolling, to prove that the test waits for a
                       smooth scroll); scroll_jumps J > 0 at both viewports.
  matrix-close         a Close button is added to the matrix card's head;
                       matrix close_buttons=1.
  broken-deeplink      #/compare opens Explore instead of Compare kinds (the
                       hash is replaced before the viewer reads it);
                       deeplinks=3/4.

The extra kinds (each makes one more check fail):

  nav-order            #card-next pressed on the overview skips the first
                       part; card nav < 9.
  head-not-sticky      the card heads lose position: sticky; card and matrix
                       sticky_head=false.
  folds-open           every fold of the card is opened when it appears;
                       card folded=false.
  matrix-hscroll       the matrix table gets a min-width of 1100 px; matrix
                       hscroll > 0 at 744.
  moves-page-abuse     #card-next carries [data-moves-page] (so a test that
                       trusts the attribute would skip it); scroll_jumps
                       moves_page_ok=false.
  tour-card-stale      the step text is not updated when Next is pressed;
                       tour_card text < T (and tour_steps < T).

The kinds of the hardened checks (one per check):

  unclickable-control  a transparent overlay covers the second Emphasize
                       button; scroll_jumps failed > 0 (no point of it
                       receives a click; the test does not dispatch events).
  deferred-scroll      an Emphasize click scrolls the card into view 700 ms
                       later; scroll_jumps J > 0 (a deferred jump).
  moves-page-late      the sequence rows carry [data-moves-page] only while
                       the tour shows the sequence chart; scroll_jumps
                       moves_page_ok=false (the mark is audited before every
                       press, in every state).
  tour-detail-hidden   #tour-detail is not displayed; tour_card detail=0/T.
  overview-no-howto    the overview loses "how to read the map" (the
                       elements showing map.sections.map's title and intro);
                       card default=FAIL:no-howto-title,no-howto-intro.
  stuck-blank          a Close pressed while the card's top is above the
                       viewport leaves a blank under the head (as 8c02c6ec
                       did); card after_close=FAIL:stuck-...
  stuck-turn-blank     the same for the card's and the step card's arrows
                       (#card-next/prev, #step-next/prev); card stuck_view < K.
  caption-above-map    #kind-caption is moved above the map; emphasize
                       captions=0/K.
  divider-missing      the "Reference" divider is not displayed; matrix
                       divider=false.
  compare-tap-broken   a tap on a small map of Compare kinds does nothing;
                       smoke compare_tap=fail.
  seq-status-stale     the status line under the sequence chart keeps its
                       first text; sequence rows < T.
  fullsize-keys-move   Left/Right move the tour even with the focus in a
                       frame that scrolls sideways; smoke fullsize_keys=fail.
  dark-ignored         the page forces the light palette under a dark system
                       setting; --layout theme dark=fail.
  override-ignored     data-theme on the root element is removed;
                       --layout theme override=fail.
  close-invisible      #card-close is transparent (it still works): only
                       PROBLEM lines ("#card-close is not displayed ..."),
                       every printed value passes, and the run exits 1.

Kinds kept from the earlier viewer checks:

  page-error           "plantedUndefinedFunction();" is put at the top of
                       viewer.js, so the page throws before its first render;
                       console_errors >= 1, every count 0.
  hide-prose           the node panel shows no prose (#detail-prose empty or
                       hidden); nodes_visited < N.
  no-multiples         the small maps of Compare kinds are not drawn (or not
                       displayed); multiples panels=0/6 or mode=FAIL.
  shift-map-box        viewer.css shifts the TEB's map box 30 px to the right
                       with a CSS transform; map boxes < Q.
  sequence-reversed    the sequence chart draws every arrow between two
                       lifelines backwards; sequence rows < T.
  arrow-global         a keydown listener on the whole document moves the tour
                       with Left/Right in tour mode wherever the focus is, and
                       calls preventDefault; smoke arrow_scope=fail.
  callout-tag-fixed    the callout tag goes back to one fixed place whatever
                       text is there; tour tag_clear < T.

Each kind has one or more anchors (a file and a regex, tried in order); the
first anchor that occurs exactly once in its file is changed. Most map-modes
kinds append a small self-contained script or rule at the end of viewer.js
or viewer.css, so they do not depend on the viewer's internals. Serve
COPY_DIR and run browser_test.py against it: the full run must exit nonzero.
Exit status: 0 if every defect was planted, 1 on a usage error or if a kind
has no anchor that occurs exactly once.
"""

import re
import sys
from pathlib import Path

DESIGN_DIR = Path(__file__).resolve().parent.parent

# Runs fn once the viewer has set body[data-ready="true"] (a planted snippet's helper).
ON_READY = (
    "const onReady = (fn) => { const go = () => { if (document.body.dataset.ready === 'true') { fn(); return true; } return false; };"
    " const start = () => { if (go()) return; const mo = new MutationObserver(() => { if (go()) mo.disconnect(); });"
    " mo.observe(document.body, { attributes: true, attributeFilter: ['data-ready'] }); };"
    " if (document.body) start(); else document.addEventListener('DOMContentLoaded', start); };"
)


def snippet(kind, body):
    """A self-contained script appended to viewer.js."""
    return f"\n;(function planted() {{  // planted: {kind}\n  {ON_READY}\n  {body}\n}})();\n"


APPEND_JS = r"\Z"
PREPEND = r"\A"

# KIND -> list of (file in COPY_DIR, regex, replacement); the first regex with exactly one match is used.
PLANTS = {
    "map-below-fold": [
        ("viewer.js", APPEND_JS, snippet("map-below-fold",
            "const move = () => { const c = document.getElementById('part-card'), mo = document.getElementById('modes');"
            " if (c && mo && mo.parentNode && c.nextElementSibling !== mo) mo.parentNode.insertBefore(c, mo); };"
            " if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', move); else move();"
            " onReady(move);")),
    ],
    "second-map": [
        ("viewer.js", APPEND_JS, snippet("second-map",
            "onReady(() => { const svg = document.querySelector('#map svg.map'); if (!svg) return;"
            " const copy = svg.cloneNode(true); copy.removeAttribute('id');"
            " copy.querySelectorAll('[id]').forEach((e) => e.removeAttribute('id'));"
            " svg.parentNode.insertBefore(copy, svg.nextSibling); });")),
    ],
    "card-empty-on-close": [
        ("viewer.js", APPEND_JS, snippet("card-empty-on-close",
            "document.addEventListener('click', (ev) => { if (!(ev.target.closest && ev.target.closest('#card-close'))) return;"
            " setTimeout(() => { const c = document.getElementById('part-card'); if (c) { c.hidden = true; c.style.display = 'none'; } }, 0); });")),
    ],
    "click-scrolls": [
        ("viewer.js", APPEND_JS, snippet("click-scrolls",
            "document.addEventListener('click', (ev) => { if (!(ev.target.closest && ev.target.closest('#chips button.chip'))) return;"
            " setTimeout(() => { const c = document.getElementById('part-card'); if (c) c.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, 0); });")),
    ],
    "matrix-close": [
        ("viewer.js", APPEND_JS, snippet("matrix-close",
            "onReady(() => { const head = document.querySelector('#matrix .card-head'); if (!head) return;"
            " const b = document.createElement('button'); b.type = 'button'; b.className = 'btn btn-small'; b.textContent = 'Close';"
            " head.append(b); });")),
    ],
    "broken-deeplink": [
        ("index.html", r"<script\b[^>]*\bsrc=[\"']viewer\.js[^>]*>",
         lambda m: ("<script>/* planted: broken-deeplink */ if (/^#\\/compare/.test(location.hash)) "
                    "history.replaceState(null, '', location.pathname + location.search + '#/');</script>\n" + m.group(0))),
        ("viewer.js", PREPEND,
         "// planted: broken-deeplink\n"
         "if (/^#\\/compare/.test(location.hash)) history.replaceState(null, '', location.pathname + location.search + '#/');\n"),
    ],
    "nav-order": [
        ("viewer.js", APPEND_JS, snippet("nav-order",
            "document.addEventListener('click', (ev) => { if (!ev.isTrusted || !(ev.target.closest && ev.target.closest('#card-next'))) return;"
            " const c = document.getElementById('part-card'); if (!c || c.dataset.card !== 'overview') return;"
            " setTimeout(() => { const n = document.getElementById('card-next'); if (n) n.click(); }, 0); }, true);")),
    ],
    "head-not-sticky": [
        ("viewer.css", r"\Z", "\n/* planted: head-not-sticky */\n#card-head, #matrix .card-head { position: static !important; }\n"),
    ],
    "folds-open": [
        ("viewer.js", APPEND_JS, snippet("folds-open",
            "const open = () => document.querySelectorAll('#part-card details.fold').forEach((d) => { if (!d.open) d.open = true; });"
            " onReady(() => { open(); new MutationObserver(open).observe(document.getElementById('part-card'), { childList: true, subtree: true }); });")),
    ],
    "matrix-hscroll": [
        ("viewer.css", r"\Z", "\n/* planted: matrix-hscroll */\n#matrix table.nsq { min-width: 1100px; }\n"),
    ],
    "moves-page-abuse": [
        ("viewer.js", APPEND_JS, snippet("moves-page-abuse",
            "const mark = () => { const n = document.getElementById('card-next'); if (n && !n.hasAttribute('data-moves-page')) n.setAttribute('data-moves-page', ''); };"
            " onReady(() => { mark(); new MutationObserver(mark).observe(document.body, { childList: true, subtree: true }); });")),
    ],
    "tour-card-stale": [
        ("viewer.js", APPEND_JS, snippet("tour-card-stale",
            "document.addEventListener('click', (ev) => { if (!(ev.target.closest && ev.target.closest('#tour-next'))) return;"
            " const p = document.getElementById('tour-step-prose'); if (!p) return; const old = p.innerHTML;"
            " setTimeout(() => { const q = document.getElementById('tour-step-prose'); if (q) q.innerHTML = old; }, 0); }, true);")),
    ],
    # the kinds of the hardened checks (decisions-2 T12)
    "unclickable-control": [
        ("viewer.js", APPEND_JS, snippet("unclickable-control",
            "onReady(() => { const chips = document.getElementById('chips'); const chip = chips && chips.querySelectorAll('button.chip')[1];"
            " if (!chip) return; chips.style.position = 'relative'; const o = document.createElement('span'); o.className = 'planted-overlay';"
            " o.style.cssText = 'position:absolute;z-index:50;background:transparent;'; chips.append(o);"
            " const place = () => { o.style.left = chip.offsetLeft - 2 + 'px'; o.style.top = chip.offsetTop - 2 + 'px';"
            " o.style.width = chip.offsetWidth + 4 + 'px'; o.style.height = chip.offsetHeight + 4 + 'px'; };"
            " place(); new ResizeObserver(place).observe(chips); window.addEventListener('resize', place); });")),
    ],
    "deferred-scroll": [
        ("viewer.js", APPEND_JS, snippet("deferred-scroll",
            "document.addEventListener('click', (ev) => { if (!(ev.target.closest && ev.target.closest('#chips button.chip'))) return;"
            " setTimeout(() => { const c = document.getElementById('part-card'); if (c) c.scrollIntoView({ behavior: 'instant', block: 'start' }); }, 700); });")),
    ],
    "tour-detail-hidden": [
        ("viewer.css", r"\Z", "\n/* planted: tour-detail-hidden */\n#tour-detail { display: none !important; }\n"),
    ],
    "overview-no-howto": [
        ("viewer.js", APPEND_JS, snippet("overview-no-howto",
            "fetch('daq-model.json').then((r) => r.json()).then((mdl) => {"
            " const titles = {}; (mdl.nodes || []).forEach((n) => { titles[n.id] = n.title; });"
            " const plain = (t) => String(t || '').replace(/\\[\\[([^\\]|]+)\\|([^\\]]+)\\]\\]/g, '$2')"
            ".replace(/\\[\\[([^\\]]+)\\]\\]/g, (m0, id) => titles[id.trim()] || m0).replace(/\\[([^\\]]+)\\]\\([^()\\s]+\\)/g, '$1')"
            ".replace(/`([^`]+)`/g, '$1').replace(/\\*\\*([^*]+)\\*\\*/g, '$1').replace(/\\s+/g, ' ').trim();"
            " const sec = ((mdl.map || {}).sections || {}).map || {};"
            " const keys = [plain(sec.title), plain(sec.intro).slice(0, 24)].filter(Boolean).map((k) => k.toLowerCase());"
            " const strip = () => { const ov = document.getElementById('overview'); if (!ov) return;"
            " const hit = [...ov.querySelectorAll('*')].filter((e) => keys.some((k) => (e.textContent || '').replace(/\\s+/g, ' ').toLowerCase().includes(k)));"
            " hit.filter((e) => !hit.some((x) => x !== e && e.contains(x))).forEach((e) => e.remove()); };"
            " onReady(() => { strip(); new MutationObserver(strip).observe(document.getElementById('overview'), { childList: true, subtree: true }); }); });")),
    ],
    "stuck-blank": [
        ("viewer.js", APPEND_JS, snippet("stuck-blank",
            "document.addEventListener('click', (ev) => { if (!(ev.target.closest && ev.target.closest('#card-close'))) return;"
            " setTimeout(() => { const c = document.getElementById('part-card'); const body = c && c.querySelector('.card-body');"
            " const top = c ? c.getBoundingClientRect().top : 0; if (!body || top >= 0) return;"
            " const d = document.createElement('div'); d.className = 'planted-blank'; d.style.height = Math.ceil(-top + window.innerHeight) + 'px';"
            " body.prepend(d); }, 100); }, true);")),
    ],
    "stuck-turn-blank": [
        ("viewer.js", APPEND_JS, snippet("stuck-turn-blank",
            "document.addEventListener('click', (ev) => { const b = ev.target.closest && ev.target.closest('#card-next, #card-prev, #step-next, #step-prev');"
            " if (!b) return; const c = b.closest('#part-card, #step-card');"
            " setTimeout(() => { const body = c && c.querySelector('.card-body'); const top = c ? c.getBoundingClientRect().top : 0;"
            " if (!body || top >= 0) return; const d = document.createElement('div'); d.className = 'planted-blank';"
            " d.style.height = Math.ceil(-top + window.innerHeight) + 'px'; body.prepend(d); }, 100); }, true);")),
    ],
    "caption-above-map": [
        ("viewer.js", APPEND_JS, snippet("caption-above-map",
            "onReady(() => { const cap = document.getElementById('kind-caption'), map = document.getElementById('map');"
            " if (cap && map && map.parentNode) map.parentNode.insertBefore(cap, map); });")),
    ],
    "divider-missing": [
        ("viewer.css", r"\Z", "\n/* planted: divider-missing */\n.ref-divider { display: none !important; }\n"),
    ],
    "compare-tap-broken": [
        ("viewer.js", APPEND_JS, snippet("compare-tap-broken",
            "document.addEventListener('click', (ev) => { if (!(ev.target.closest && ev.target.closest('#mult figure'))) return;"
            " ev.stopPropagation(); ev.preventDefault(); }, true);")),
    ],
    "seq-status-stale": [
        ("viewer.js", APPEND_JS, snippet("seq-status-stale",
            "onReady(() => { const st = document.getElementById('seq-status'); if (!st) return; const old = st.textContent;"
            " new MutationObserver(() => { if (st.textContent !== old) st.textContent = old; })"
            ".observe(st, { childList: true, characterData: true, subtree: true }); });")),
    ],
    "dark-ignored": [
        ("viewer.js", APPEND_JS, snippet("dark-ignored",
            "if (window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches && !document.documentElement.dataset.theme)"
            " document.documentElement.dataset.theme = 'light';")),
    ],
    "override-ignored": [
        ("viewer.js", APPEND_JS, snippet("override-ignored",
            "const drop = () => { if (document.documentElement.hasAttribute('data-theme')) document.documentElement.removeAttribute('data-theme'); };"
            " drop(); new MutationObserver(drop).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });")),
    ],
    "fullsize-keys-move": [
        ("viewer.js", APPEND_JS, snippet("fullsize-keys-move",
            "document.addEventListener('keydown', (ev) => { if (ev.key !== 'ArrowRight' && ev.key !== 'ArrowLeft') return;"
            " if (document.body.dataset.mode !== 'tour') return; const t = ev.target;"
            " if (!(t && t.closest && (t.closest('#map, #seq') || t.id === 'map-section'))) return;"
            " ev.preventDefault(); ev.stopImmediatePropagation();"
            " const b = document.getElementById(ev.key === 'ArrowRight' ? 'tour-next' : 'tour-prev'); if (b && !b.disabled) b.click(); }, true);")),
    ],
    "moves-page-late": [
        ("viewer.js", APPEND_JS, snippet("moves-page-late",
            "const mark = () => { const seqView = document.body.dataset.mode === 'tour' && !!document.querySelector('#tour-controls button.view[data-view=\"seq\"][aria-pressed=\"true\"]');"
            " document.querySelectorAll('#seq .row').forEach((r) => { if (seqView && !r.hasAttribute('data-moves-page')) r.setAttribute('data-moves-page', '');"
            " if (!seqView && r.hasAttribute('data-moves-page')) r.removeAttribute('data-moves-page'); }); };"
            " onReady(() => { mark(); new MutationObserver(mark).observe(document.body, { attributes: true, subtree: true, attributeFilter: ['data-mode', 'aria-pressed'] }); });")),
    ],
    "close-invisible": [
        ("viewer.css", r"\Z", "\n/* planted: close-invisible */\n#card-close { opacity: 0 !important; }\n"),
    ],
    "page-error": [
        ("viewer.js", PREPEND, "plantedUndefinedFunction();  // planted: page-error\n"),
    ],
    "hide-prose": [
        ("viewer.js", re.escape("box.append(prose(n.prose, proseId === null ? {} : { id: proseId || 'detail-prose' }));"),
         "box.append(prose('', proseId === null ? {} : { id: proseId || 'detail-prose' }));  // planted: hide-prose"),
        ("viewer.js", r"\bprose\(n\.prose\b", "prose(''  /* planted: hide-prose */"),
        ("viewer.css", r"\Z", "\n/* planted: hide-prose */\n#detail-prose { display: none !important; }\n"),
    ],
    "no-multiples": [
        ("viewer.js", r"function buildMultiples\(\) \{", "function buildMultiples() { return;  // planted: no-multiples"),
        ("viewer.css", r"\Z", "\n/* planted: no-multiples */\n#mult figure { display: none !important; }\n"),
    ],
    "shift-map-box": [
        ("viewer.css", r"\Z", '\n/* planted: shift-map-box */\n#map svg.map g.box[data-box="teb"] { transform: translate(30px, 0); }\n'),
    ],
    "sequence-reversed": [
        ("viewer.js", re.escape("S('path', { d: 'M' + xf + ',' + y + ' H' + xt,"),
         "S('path', { d: 'M' + xt + ',' + y + ' H' + xf,  /* planted: sequence-reversed */"),
        ("viewer.js", r"d: 'M' \+ xf \+ ',' \+ y \+ ' H' \+ xt\b", "d: 'M' + xt + ',' + y + ' H' + xf /* planted: sequence-reversed */"),
    ],
    "arrow-global": [
        ("viewer.js", APPEND_JS, snippet("arrow-global",
            "document.addEventListener('keydown', (ev) => { if (ev.key !== 'ArrowRight' && ev.key !== 'ArrowLeft') return;"
            " if (document.body.dataset.mode !== 'tour' || (ev.target && ev.target.closest && ev.target.closest('#map-section'))) return;"
            " ev.preventDefault(); const b = document.getElementById(ev.key === 'ArrowRight' ? 'tour-next' : 'tour-prev'); if (b) b.click(); });")),
    ],
    "callout-tag-fixed": [
        ("viewer.js", re.escape("const pos = placeTag(o, w, 18);"),
         "const pos = { x: Math.min(o.x0, vb.w - w - 2), y: o.y1 + 18 <= vb.h ? o.y1 - 1 : o.y0 - 17 };  // planted: callout-tag-fixed"),
    ],
}

NEW_SIX = ("map-below-fold", "second-map", "card-empty-on-close", "click-scrolls", "matrix-close", "broken-deeplink")


def plant(copy_dir, kind):
    """Plant one kind; return (ok, message)."""
    for name, pattern, replacement in PLANTS[kind]:
        target = copy_dir / name
        if not target.is_file():
            continue
        text = target.read_text(encoding="utf-8")
        matches = list(re.finditer(pattern, text))
        if len(matches) == 1:
            m = matches[0]
            new = replacement(m) if callable(replacement) else replacement
            target.write_text(text[:m.start()] + new + text[m.end():], encoding="utf-8")
            line = text.count("\n", 0, m.start()) + 1
            return True, f"planted {kind} in {target} at line {line}"
    counts = ", ".join(f"{name} {pattern!r}: "
                       + (str(len(re.findall(pattern, (copy_dir / name).read_text(encoding='utf-8'))))
                          if (copy_dir / name).is_file() else "no file")
                       for name, pattern, _ in PLANTS[kind])
    return False, f"ERROR: no anchor for {kind} occurs exactly once in {copy_dir} ({counts})"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2 or any(k not in PLANTS for k in argv[1:]):
        print(f"usage: plant_viewer_defects.py COPY_DIR KIND [KIND ...]\nKIND: {' | '.join(PLANTS)}", file=sys.stderr)
        return 1
    copy_dir = Path(argv[0]).resolve()
    if copy_dir == DESIGN_DIR:
        print(f"ERROR: {copy_dir} is the viewer itself; plant defects only in a copy", file=sys.stderr)
        return 1
    if not (copy_dir / "viewer.js").is_file():
        print(f"ERROR: {copy_dir / 'viewer.js'} does not exist", file=sys.stderr)
        return 1
    status = 0
    for kind in argv[1:]:
        ok, message = plant(copy_dir, kind)
        print(message, file=sys.stdout if ok else sys.stderr)
        if not ok:
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
