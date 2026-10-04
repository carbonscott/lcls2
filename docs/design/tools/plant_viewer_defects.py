#!/usr/bin/env python3
"""Plant a known defect in a COPY of the viewer, to show that the browser test catches it.

Usage:
    python docs/design/tools/plant_viewer_defects.py COPY_DIR KIND

COPY_DIR is a copy of docs/design (at least viewer.js); the script edits
COPY_DIR/viewer.js in place and refuses to touch the viewer next to this
script. KIND is one of:

  hide-prose    the viewer stops rendering node prose (the node panel shows no
                prose paragraphs, so #detail-prose is empty);
  no-multiples  the viewer stops drawing the small multiples (#multiples gets
                no figures).

Serve COPY_DIR and run browser_test.py against it: the full run must exit
nonzero (hide-prose: nodes_visited < N; no-multiples: multiples panels=0/6).
Each kind has one or more anchors in viewer.js (tried in order); the first
anchor that occurs exactly once is changed. Exit status: 0 if the defect was
planted, 1 on a usage error or if no anchor occurs exactly once.
"""

import re
import sys
from pathlib import Path

DESIGN_DIR = Path(__file__).resolve().parent.parent

# KIND -> list of (regex in viewer.js, replacement); the first regex with exactly one match is used.
PLANTS = {
    "hide-prose": [
        (re.escape("box.append(prose(n.prose, proseId === null ? {} : { id: proseId || 'detail-prose' }));"),
         "box.append(prose('', proseId === null ? {} : { id: proseId || 'detail-prose' }));  // planted: hide-prose"),
        (r"\bprose\(n\.prose\b", "prose(''  /* planted: hide-prose */"),
    ],
    "no-multiples": [
        (r"function buildMultiples\(\) \{", "function buildMultiples() { return;  // planted: no-multiples"),
    ],
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
    viewer = copy_dir / "viewer.js"
    if not viewer.is_file():
        print(f"ERROR: {viewer} does not exist", file=sys.stderr)
        return 1
    text = viewer.read_text(encoding="utf-8")
    for pattern, replacement in PLANTS[argv[1]]:
        matches = list(re.finditer(pattern, text))
        if len(matches) == 1:
            m = matches[0]
            viewer.write_text(text[:m.start()] + replacement + text[m.end():], encoding="utf-8")
            line = text.count("\n", 0, m.start()) + 1
            print(f"planted {argv[1]} in {viewer} at line {line}")
            return 0
    counts = ", ".join(f"{p!r}: {len(re.findall(p, text))}" for p, _ in PLANTS[argv[1]])
    print(f"ERROR: no anchor for {argv[1]} occurs exactly once in {viewer} ({counts})", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
