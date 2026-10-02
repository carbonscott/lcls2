# Design model tools

Scripts for `docs/design/daq-model.json` (the model) and the viewer
(`index.html`, `viewer.js`, `viewer.css`). Run them from the repository root.
This directory is excluded from the MkDocs site (`exclude_docs` in
`mkdocs.yml`). See `docs/design/editing-guide.md` for how to edit the model.

Requirements: Python 3 with `jsonschema` (in `docs/requirements.txt`); for
the browser test also `playwright` and its Chromium
(`pip install playwright && python -m playwright install chromium`). The
validator needs a full clone (the pinned commit's files are read with git).

## validate.py

```bash
python docs/design/tools/validate.py [--model PATH] [--schema PATH] [--repo PATH] [--outline]
```

Schema check (every error, with its JSON path) plus the semantic rules (ids,
parents and levels, edges, tour, sources and cross-links, code references at
`code_base.commit`, node rules, decisions, site-page URLs). Prints
`ERROR: <where>: <what>` lines, then one summary line:
`nodes=N edges=E levels=L tour_steps=T code_refs=R sources=S errors=K`.
Exit 0 iff `errors=0`; 1 if there are errors; 2 if a file cannot be read or
parsed. `--outline` also prints `model_sha256=...`, the top-level titles
(`top: 1. ...`) and the tour step titles (`tour: 1. ...`). The default
`--repo` is the git checkout that contains this script.

## check_single_source.py

```bash
python docs/design/tools/check_single_source.py [--model PATH] [--schema PATH] [--viewer-dir DIR]
```

Takes the first 40 characters of every PROSE field (fields whose schema
description starts with "PROSE") and searches the viewer files for them
(also HTML- and JSON-escaped); then the same for every title and edge label
of 12 or more characters. Prints `strings_checked=N found_in_viewer=M` and
`titles_checked=N titles_found_in_viewer=M`. Exit 0 iff both M are 0.

## browser_test.py

```bash
cd docs/design && python -m http.server 8000          # in one terminal
python docs/design/tools/browser_test.py --url http://127.0.0.1:8000/ [--headed] [--screenshot-dir DIR]
python docs/design/tools/browser_test.py --url http://127.0.0.1:8000/ \
    --check-node ID --expect-title TEXT --expect-prose SUBSTRING [--full]
```

Full run: clicks every node's box depth-first from the overview (drill in,
check the focus, zoom out, check the parent), then steps through the tour.
Prints `nodes_visited=V/N tour_steps=S/T console_errors=C`, where C counts
console errors and warnings, page errors, and failed or HTTP >= 400 requests
to the viewer's origin. Exit 0 iff N > 0, T > 0, V = N, S = T and C = 0.
`--check-node` opens one node by deep link and by clicking down from the
overview, and checks its detail title and that its rendered prose contains
SUBSTRING; prints `check_node id=ID title_ok=<bool> prose_ok=<bool>
console_errors=C`. `--full` adds the full run. The test also works against
the published site (`--url https://carbonscott.github.io/lcls2/dev/design/`).

## sample_statements.py

```bash
python docs/design/tools/sample_statements.py --seed S --n 40 [--reserve 20] [--model PATH] [--out sample.json] [--markdown sample.md]
```

Splits every PROSE field attached to a node (its own fields and code-ref
notes, its decisions, the tour steps about it, the edges leaving it) into
sentences, tags each with node id, level (1, 2, 3+), outside_repo and field,
and draws a sample stratified over level x outside_repo (proportional, at
least 2 per non-empty cell, `random.Random(S)`), plus `--reserve` extra
sentences. Prints the seed, the cell counts and markdown tables; `--out`
writes JSON.

## Viewer test hooks

Stable attributes for tests (the UI works the same for people):

| Hook | Meaning |
|---|---|
| `#map .node-box[data-node-id="ID"]` | the box (a `<button>`) of node ID on the map; `.is-highlighted` marks the focused leaf or the tour step's node |
| `#detail-title[data-node-id]` | detail panel title; `__root__` on the overview |
| `#detail-prose` | the rendered prose of the node (or the overview summary) |
| `#zoom-out` | zoom out one level (disabled on the overview) |
| `#breadcrumb [data-node-id]` | breadcrumb buttons; the root crumb has `data-node-id="__root__"` |
| `#tour-start`, `#tour-next`, `#tour-prev`, `#tour-exit` | tour controls |
| `#tour-step-title[data-step-index="k"]` | title of tour step k (1-based) |
| `body[data-ready="true"]` | set once the model is rendered |
| `body[data-focus]` | the focused node id, or `__root__` |
| `body[data-mode]` | `browse` or `tour` |
| `body[data-error="true"]` | the model failed to load |
| `#map g.edge[data-edge-ids]` | a drawn arrow and the model edge ids it stands for; `.is-highlighted` in a tour step |

URL routes: `#/` (overview), `#/node/<id>`, `#/tour/<k>`.
