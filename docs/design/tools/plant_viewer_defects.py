#!/usr/bin/env python3
"""Plant a known defect in a COPY of the viewer, to show that the browser test catches it.

Usage:
    python docs/design/tools/plant_viewer_defects.py COPY_DIR KIND

COPY_DIR is a copy of docs/design (at least viewer.js and viewer.css); the
script edits one file of COPY_DIR in place and refuses to touch the viewer next
to this script. KIND is one of:

  hide-prose         the viewer stops rendering node prose (the node panel shows
                     no prose paragraphs, so #detail-prose is empty);
                     browser_test: nodes_visited < N.
  no-multiples       the viewer stops drawing the small multiples (#multiples
                     gets no figures); browser_test: multiples panels=0/6.
  page-error         "plantedUndefinedFunction();" is put at the top of
                     viewer.js, so the page throws before its first render;
                     browser_test: console_errors >= 1, every count 0.
  shift-map-box      viewer.css gets a rule that shifts the TEB's map box 30 px
                     to the right with a CSS transform (no transform attribute);
                     browser_test: map boxes < Q (the teb box's rendered rect
                     differs from the JSON).
  sequence-reversed  the sequence chart draws every arrow between two lifelines
                     backwards (from "to" to "from"); browser_test: sequence
                     rows < T.
  arrow-global       a keydown listener on the whole document moves the tour
                     with Left/Right wherever the focus is once the tour has
                     been used, and calls preventDefault (the bug of an
                     earlier version); browser_test: smoke arrow_scope=fail.
  callout-tag-fixed  the callout tag goes back to one fixed place (under the
                     outline at its left, or over it when there is no room
                     below) whatever text is there; browser_test: tour
                     tag_clear < T (it covers a map note on some steps).

Serve COPY_DIR and run browser_test.py against it: the full run must exit
nonzero. Each kind has one or more anchors in its file (tried in order); the
first anchor that occurs exactly once is changed. Exit status: 0 if the defect
was planted, 1 on a usage error or if no anchor occurs exactly once.
"""

import re
import sys
from pathlib import Path

DESIGN_DIR = Path(__file__).resolve().parent.parent

# KIND -> (file in COPY_DIR, list of (regex, replacement)); the first regex with exactly one match is used.
PLANTS = {
    "hide-prose": ("viewer.js", [
        (re.escape("box.append(prose(n.prose, proseId === null ? {} : { id: proseId || 'detail-prose' }));"),
         "box.append(prose('', proseId === null ? {} : { id: proseId || 'detail-prose' }));  // planted: hide-prose"),
        (r"\bprose\(n\.prose\b", "prose(''  /* planted: hide-prose */"),
    ]),
    "no-multiples": ("viewer.js", [
        (r"function buildMultiples\(\) \{", "function buildMultiples() { return;  // planted: no-multiples"),
    ]),
    "page-error": ("viewer.js", [
        (r"\A", "plantedUndefinedFunction();  // planted: page-error\n"),
    ]),
    "shift-map-box": ("viewer.css", [
        (r"\Z", '\n/* planted: shift-map-box */\n#map svg.map g.box[data-box="teb"] { transform: translate(30px, 0); }\n'),
    ]),
    "sequence-reversed": ("viewer.js", [
        (re.escape("S('path', { d: 'M' + xf + ',' + y + ' H' + xt,"),
         "S('path', { d: 'M' + xt + ',' + y + ' H' + xf,  /* planted: sequence-reversed */"),
        (r"d: 'M' \+ xf \+ ',' \+ y \+ ' H' \+ xt\b", "d: 'M' + xt + ',' + y + ' H' + xf /* planted: sequence-reversed */"),
    ]),
    "arrow-global": ("viewer.js", [
        (r"function bindEvents\(\) \{",
         "function bindEvents() {\n    // planted: arrow-global\n"
         "    document.addEventListener('keydown', (ev) => { if ((ev.key === 'ArrowRight' || ev.key === 'ArrowLeft') "
         "&& document.body.dataset.mode === 'tour' && !(ev.target && ev.target.closest && ev.target.closest('#tour'))) "
         "{ ev.preventDefault(); tourGo(tourIndex + (ev.key === 'ArrowRight' ? 1 : -1), true); } });"),
    ]),
    "callout-tag-fixed": ("viewer.js", [
        (re.escape("const pos = placeTag(o, w, 18);"),
         "const pos = { x: Math.min(o.x0, vb.w - w - 2), y: o.y1 + 18 <= vb.h ? o.y1 - 1 : o.y0 - 17 };  // planted: callout-tag-fixed"),
    ]),
}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or argv[1] not in PLANTS:
        print(f"usage: plant_viewer_defects.py COPY_DIR {{{'|'.join(PLANTS)}}}", file=sys.stderr)
        return 1
    copy_dir = Path(argv[0]).resolve()
    if copy_dir == DESIGN_DIR:
        print(f"ERROR: {copy_dir} is the viewer itself; plant defects only in a copy", file=sys.stderr)
        return 1
    name, anchors = PLANTS[argv[1]]
    target = copy_dir / name
    if not target.is_file():
        print(f"ERROR: {target} does not exist", file=sys.stderr)
        return 1
    text = target.read_text(encoding="utf-8")
    for pattern, replacement in anchors:
        matches = list(re.finditer(pattern, text))
        if len(matches) == 1:
            m = matches[0]
            target.write_text(text[:m.start()] + replacement + text[m.end():], encoding="utf-8")
            line = text.count("\n", 0, m.start()) + 1
            print(f"planted {argv[1]} in {target} at line {line}")
            return 0
    counts = ", ".join(f"{p!r}: {len(re.findall(p, text))}" for p, _ in anchors)
    print(f"ERROR: no anchor for {argv[1]} occurs exactly once in {target} ({counts})", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
