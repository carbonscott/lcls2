#!/usr/bin/env python3
"""Plant a known defect in a COPY of the viewer, to show that the browser test catches it.

Usage:
    python docs/design/tools/plant_viewer_defects.py COPY_DIR KIND

COPY_DIR is a copy of docs/design (at least viewer.js); the script edits
COPY_DIR/viewer.js in place and refuses to touch the viewer next to this
script. KIND is one of:

  hide-prose      the viewer stops rendering node prose (the detail panel and
                  the one-page view show no prose paragraphs);
  no-edge-labels  the viewer stops drawing the labels of arrows between boxes.

Serve COPY_DIR and run browser_test.py against it: the full run must exit
nonzero (hide-prose: nodes_visited < N; no-edge-labels: edge_label=fail).
Exit status: 0 if the defect was planted, 1 on a usage error or if the
viewer code to change was not found exactly once.
"""

import sys
from pathlib import Path

DESIGN_DIR = Path(__file__).resolve().parent.parent

# KIND -> (exact code in viewer.js, replacement)
PLANTS = {
    "hide-prose": (
        "box.append(prose(n.prose, proseId === null ? {} : { id: proseId || 'detail-prose' }));",
        "box.append(prose('', proseId === null ? {} : { id: proseId || 'detail-prose' }));  // planted: hide-prose",
    ),
    "no-edge-labels": (
        "labels.append(lg);",
        "void lg;  // planted: no-edge-labels",
    ),
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
    old, new = PLANTS[argv[1]]
    text = viewer.read_text(encoding="utf-8")
    if text.count(old) != 1:
        print(f"ERROR: the code to change occurs {text.count(old)} times in {viewer}, expected once: {old}",
              file=sys.stderr)
        return 1
    viewer.write_text(text.replace(old, new), encoding="utf-8")
    print(f"planted {argv[1]} in {viewer}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
