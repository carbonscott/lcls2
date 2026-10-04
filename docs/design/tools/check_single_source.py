#!/usr/bin/env python3
"""Check that the viewer files contain no content from the design model.

The model (daq-model.json) is the single source of the design document; the
viewer (index.html, viewer.js, viewer.css) must only render it. This script
searches the viewer files for model text in four ways:

1. Prose prefixes: every PROSE field of the model (every field whose schema
   description starts with "PROSE", so new PROSE fields are covered
   automatically), cut to its first 40 characters.
   Layout strings: every string from validate.iter_layout_text (every string
   leaf under the model's "map" block and under each node's "place" and
   "detail", except identifiers). A layout string of 8 or more characters
   that has more than one word is searched as a substring; a shorter one, or
   a single word, only as a quoted literal ('...', "...", `...` or >...<),
   so that "DRP" is caught as 'DRP' but not inside another word, and the
   word "decision" is not found in the model field name "decisions". A
   layout string equal to a kind id (data, trigger, timing, control,
   monitoring) is not searched: kind ids are UI enums the viewer may hold.
   Both searches are case-sensitive and also look for the HTML-escaped and
   JSON/JS-escaped forms.
2. Every title (and edge label) of 12 or more characters.
3. Every 40-character window of every PROSE field, taken every 20 characters
   (plus the last window of the field), so that text copied from the middle
   of a field is found too.
4. Node ids: no model node id (other than the kind ids data, trigger,
   timing, control and monitoring, which are UI enums) may appear in
   viewer.js as a quoted literal ('id', "id" or `id`).

Output:
    strings_checked=N found_in_viewer=M          (N = prose prefixes + layout strings searched)
    titles_checked=N titles_found_in_viewer=M
    windows_checked=N windows_found_in_viewer=M
    layout_checked=L skipped_kind_ids=S          (L: the layout strings searched, among the N above;
                                                  S: layout strings equal to a kind id, not searched)
    node_ids_in_viewer=K
Every count of checked strings counts only the strings actually searched;
L + S (+ skipped_blank=B, printed only when an empty layout string exists)
equals validate.py's layout_text.
each count preceded by FOUND: lines naming what was found where.
Exit status 0 iff every M and K is 0.

Usage:
    python docs/design/tools/check_single_source.py [--model PATH] [--schema PATH] [--viewer-dir DIR]
"""

import argparse
import html
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate import DESIGN_DIR, as_dict, as_list, iter_prose  # noqa: E402
from validate import iter_layout_text  # noqa: E402

VIEWER_FILES = ("index.html", "viewer.js", "viewer.css")
SNIPPET_LENGTH = 40
WINDOW_LENGTH = 40
WINDOW_STRIDE = 20
MIN_TITLE_LENGTH = 12
MIN_SUBSTRING_LENGTH = 8   # shorter layout strings are searched only as quoted literals
KIND_IDS = {"data", "trigger", "timing", "control", "monitoring"}


def variants(text):
    """The forms in which text could appear in an HTML, JS or CSS file."""
    forms = {
        text,
        html.escape(text, quote=False),
        html.escape(text, quote=True),
        json.dumps(text)[1:-1],
        json.dumps(text, ensure_ascii=False)[1:-1],
    }
    return forms


def literal_forms(text):
    """text as a quoted literal: '...', "...", `...` or >...< (each in every escaped form)."""
    forms = set()
    for form in variants(text):
        forms.update({f"'{form}'", f'"{form}"', f"`{form}`", f">{form}<"})
    return forms


def find_in_viewer(text, viewer_texts):
    """Return the names of the viewer files that contain text."""
    hits = []
    for name, content in viewer_texts.items():
        if any(form in content for form in variants(text)):
            hits.append(name)
    return hits


def find_literal_in_viewer(text, viewer_texts):
    """Return the names of the viewer files that contain text as a quoted literal."""
    hits = []
    for name, content in viewer_texts.items():
        if any(form in content for form in literal_forms(text)):
            hits.append(name)
    return hits


def windows(text):
    """Every WINDOW_LENGTH-character window of text, every WINDOW_STRIDE characters, plus the last one."""
    if len(text) <= WINDOW_LENGTH:
        return [text]
    starts = list(range(0, len(text) - WINDOW_LENGTH + 1, WINDOW_STRIDE))
    if starts[-1] != len(text) - WINDOW_LENGTH:
        starts.append(len(text) - WINDOW_LENGTH)
    return [text[i:i + WINDOW_LENGTH] for i in starts]


def iter_titles(model):
    """Yield (where, text) for every title and edge label in the model."""
    model = as_dict(model)
    if isinstance(model.get("title"), str):
        yield "$.title", model["title"]
    tour = as_dict(model.get("tour"))
    if isinstance(tour.get("title"), str):
        yield "$.tour.title", tour["title"]
    for i, step in enumerate(as_list(tour.get("steps"))):
        if isinstance(as_dict(step).get("title"), str):
            yield f"$.tour.steps[{i}].title", step["title"]
    for i, node in enumerate(as_list(model.get("nodes"))):
        node = as_dict(node)
        if isinstance(node.get("title"), str):
            yield f"$.nodes[{i}].title", node["title"]
        for j, decision in enumerate(as_list(node.get("decisions"))):
            if isinstance(as_dict(decision).get("title"), str):
                yield f"$.nodes[{i}].decisions[{j}].title", decision["title"]
    for i, edge in enumerate(as_list(model.get("edges"))):
        if isinstance(as_dict(edge).get("label"), str):
            yield f"$.edges[{i}].label", edge["label"]
    for i, source in enumerate(as_list(model.get("sources"))):
        if isinstance(as_dict(source).get("title"), str):
            yield f"$.sources[{i}].title", source["title"]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check that the viewer contains no model content.")
    parser.add_argument("--model", default=str(DESIGN_DIR / "daq-model.json"))
    parser.add_argument("--schema", default=str(DESIGN_DIR / "daq-model.schema.json"))
    parser.add_argument("--viewer-dir", default=str(DESIGN_DIR),
                        help="directory with index.html, viewer.js and viewer.css")
    args = parser.parse_args(argv)

    model = json.loads(Path(args.model).read_text(encoding="utf-8"))
    schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    viewer_texts = {}
    for name in VIEWER_FILES:
        path = Path(args.viewer_dir) / name
        if not path.is_file():
            print(f"ERROR: {path}: viewer file is missing")
            return 2
        viewer_texts[name] = path.read_text(encoding="utf-8")

    # 1. prose prefixes and layout strings
    checked = 0
    found = []
    for where, text in iter_prose(model, schema):
        if text.strip() == "":
            continue
        snippet = text[:SNIPPET_LENGTH]
        checked += 1
        hits = find_in_viewer(snippet, viewer_texts)
        if hits:
            found.append((where, snippet, hits, "prose"))
    layout_checked = 0
    skipped_kind_ids = 0
    skipped_blank = 0
    for where, text, role in iter_layout_text(model):
        if not isinstance(text, str) or text.strip() == "":
            skipped_blank += 1
            continue
        if text in KIND_IDS:
            skipped_kind_ids += 1
            continue  # a kind id is a UI enum, allowed in the viewer; not searched, not counted
        layout_checked += 1
        checked += 1
        if len(text) >= MIN_SUBSTRING_LENGTH and re.search(r"\s", text.strip()):
            hits = find_in_viewer(text, viewer_texts)
            how = f"layout {role}"
        else:
            hits = find_literal_in_viewer(text, viewer_texts)
            how = f"layout {role}, quoted literal"
        if hits:
            found.append((where, text, hits, how))

    # 2. titles
    titles_checked = 0
    titles_found = []
    for where, text in iter_titles(model):
        if len(text) < MIN_TITLE_LENGTH:
            continue
        titles_checked += 1
        hits = find_in_viewer(text, viewer_texts)
        if hits:
            titles_found.append((where, text, hits))

    # 3. prose windows
    windows_checked = 0
    windows_found = []
    for where, text in iter_prose(model, schema):
        if text.strip() == "":
            continue
        for window in windows(text):
            windows_checked += 1
            hits = find_in_viewer(window, viewer_texts)
            if hits:
                windows_found.append((where, window, hits))

    # 4. node ids as quoted literals in viewer.js
    node_ids = [as_dict(n).get("id") for n in as_list(as_dict(model).get("nodes"))]
    node_ids = [i for i in node_ids if isinstance(i, str) and i and i not in KIND_IDS]
    js = {"viewer.js": viewer_texts["viewer.js"]}
    ids_found = []
    for node_id in node_ids:
        hits = [form for form in (f"'{node_id}'", f'"{node_id}"', f"`{node_id}`") if form in js["viewer.js"]]
        if hits:
            ids_found.append((node_id, hits))

    for where, text, hits, how in found:
        print(f"FOUND: {where}: {text!r} ({how}) in {', '.join(hits)}")
    print(f"strings_checked={checked} found_in_viewer={len(found)}")
    for where, text, hits in titles_found:
        print(f"FOUND: {where}: {text!r} in {', '.join(hits)}")
    print(f"titles_checked={titles_checked} titles_found_in_viewer={len(titles_found)}")
    for where, window, hits in windows_found[:20]:
        print(f"FOUND: {where}: window {window!r} in {', '.join(hits)}")
    print(f"windows_checked={windows_checked} windows_found_in_viewer={len(windows_found)}")
    print(f"layout_checked={layout_checked} skipped_kind_ids={skipped_kind_ids}"
          + (f" skipped_blank={skipped_blank}" if skipped_blank else ""))
    for node_id, hits in ids_found:
        print(f"FOUND: node id {node_id!r} as {' '.join(hits)} in viewer.js")
    print(f"node_ids_in_viewer={len(ids_found)}")
    ok = not found and not titles_found and not windows_found and not ids_found
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
