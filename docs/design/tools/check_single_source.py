#!/usr/bin/env python3
"""Check that the viewer files contain no content from the design model.

The model (daq-model.json) is the single source of the design document; the
viewer (index.html, viewer.js, viewer.css) must only render it. This script
takes every PROSE field of the model (every field whose schema description
starts with "PROSE", so new PROSE fields are covered automatically), keeps
its first 40 characters, and searches the viewer files for that text (also
HTML-escaped and JSON/JS-escaped). It then does the same for every title
(and edge label) of 12 or more characters.

Output:
    strings_checked=N found_in_viewer=M
    titles_checked=N titles_found_in_viewer=M
Exit status 0 iff both M are 0.

Usage:
    python docs/design/tools/check_single_source.py [--model PATH] [--schema PATH] [--viewer-dir DIR]
"""

import argparse
import html
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate import DESIGN_DIR, as_dict, as_list, iter_prose  # noqa: E402

VIEWER_FILES = ("index.html", "viewer.js", "viewer.css")
SNIPPET_LENGTH = 40
MIN_TITLE_LENGTH = 12


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


def find_in_viewer(text, viewer_texts):
    """Return the names of the viewer files that contain text."""
    hits = []
    for name, content in viewer_texts.items():
        if any(form in content for form in variants(text)):
            hits.append(name)
    return hits


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

    checked = 0
    found = []
    for where, text in iter_prose(model, schema):
        if text.strip() == "":
            continue
        snippet = text[:SNIPPET_LENGTH]
        checked += 1
        hits = find_in_viewer(snippet, viewer_texts)
        if hits:
            found.append((where, snippet, hits))

    titles_checked = 0
    titles_found = []
    for where, text in iter_titles(model):
        if len(text) < MIN_TITLE_LENGTH:
            continue
        titles_checked += 1
        hits = find_in_viewer(text, viewer_texts)
        if hits:
            titles_found.append((where, text, hits))

    for where, snippet, hits in found:
        print(f"FOUND: {where}: {snippet!r} in {', '.join(hits)}")
    print(f"strings_checked={checked} found_in_viewer={len(found)}")
    for where, text, hits in titles_found:
        print(f"FOUND: {where}: {text!r} in {', '.join(hits)}")
    print(f"titles_checked={titles_checked} titles_found_in_viewer={len(titles_found)}")
    return 0 if not found and not titles_found else 1


if __name__ == "__main__":
    sys.exit(main())
