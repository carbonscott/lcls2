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
of 12 or more characters; then every 40-character window of every PROSE
field, taken every 20 characters (plus the last window of each field), so
that text copied from the middle of a field is caught too. Prints, in this
order, `strings_checked=N found_in_viewer=M`,
`titles_checked=N titles_found_in_viewer=M` and
`windows_checked=N windows_found_in_viewer=M` (each preceded by `FOUND:`
lines for its hits). Exit 0 iff all three M are 0.

## browser_test.py

```bash
python -m http.server 8000 --bind 127.0.0.1 --directory docs/design &   # or a free port, see editing-guide.md
python docs/design/tools/browser_test.py --url http://127.0.0.1:8000/ [--headed] [--screenshot-dir DIR]
python docs/design/tools/browser_test.py --url http://127.0.0.1:8000/ \
    --check-node ID --expect-title TEXT --expect-prose SUBSTRING [--full]
python docs/design/tools/browser_test.py --url http://127.0.0.1:8000/ --check-edge ID [--full]
```

Full run: clicks every node's box depth-first from the overview (drill in,
check the focus, zoom out, check the parent), then steps through the tour,
then runs smoke checks of the reader controls. A node counts as visited only
if `body[data-focus]` and `#detail-title[data-node-id]` name it **and** the
panel's visible title text equals the model title (whitespace-normalized)
**and** the visible prose (`#detail-prose`) contains the first 30 characters
of the node's prose as plain text (markup reduced to the text the viewer
shows, as for tour steps). A full run takes roughly 10 to 60 seconds for a
model of about 40 nodes, depending on the machine. A tour step counts only
if its title, focus and highlighted box are right and the visible step
text (`#tour-step-prose`) contains the first 30 characters of the step's
prose as plain text (markup removed, `[[id]]` replaced by the node title).
Prints `nodes_visited=V/N tour_steps=S/T console_errors=C`, where C counts
console errors and warnings, page errors, and failed or HTTP >= 400 requests
to the viewer's origin, and then one more line:

```text
smoke stub_click=ok edge_label=ok arrow_keys=ok help=ok read_page=R/N
```

- `stub_click`: on the first level (in model order) that draws a stub arrow,
  clicking its tag (`#map g.stub-chip`) focuses the node it names.
- `edge_label`: the overview shows exactly one visible, clickable edge label
  (`#map g.edge-label` with a non-empty `data-edge-ids`) for each arrow the
  viewer should label there, derived from the model the way the viewer
  groups edges (both ends lifted to their top-level boxes; edges whose ends
  meet in one box are not drawn; one arrow per from, to and kind), and the
  labels' edge ids are exactly those arrows' ids, all of them edges of the
  model. Clicking one label (preferably one that bundles several flows)
  lists exactly its flows in `#edge-flows`, each with links to both ends;
  `#edge-flows-close` closes it.
- `arrow_keys`: in the tour, the Right and Left arrow keys move to step 2
  and back (fails with fewer than 2 steps).
- `help`: `#help-toggle` opens `#help` and `#help-close` closes it.
- `read_page`: in the one-page view (`#/read`) every node has a section with
  its title (R of N).

Each check prints `ok` or `fail`; a check that finds nothing to test (no
stub arrow at any level, no labelled arrow on the overview, fewer than 2
tour steps) fails. Exit 0 iff N > 0, T > 0, V = N, S = T, C = 0 and every
smoke check is `ok` with R = N.
`--check-node` opens one node by deep link and by clicking down from the
overview, and checks its detail title and that its rendered prose contains
SUBSTRING; prints `check_node id=ID title_ok=<bool> prose_ok=<bool>
console_errors=C`. SUBSTRING is matched against the rendered, visible text,
so it must not contain markup (backticks, `[[...]]`, link syntax).
`--check-edge ID` opens the level where the edge is drawn between two boxes
(the children of the lowest common ancestor of its ends, or the overview) and
checks that `#map g.edge[data-edge-ids~=ID]` is there and is not a stub; then,
for each end whose own level lies deeper, it opens that level and checks the
stub arrow (`g.edge.stub` and `g.stub-chip` with the id). It prints
`check_edge id=ID drawn=<bool> console_errors=C` (drawn is true only if all
are found) and exits 0 iff drawn is true and C = 0. It checks the arrow and
the stubs, not the arrow's label (the full run's `edge_label` check covers
labels on the overview). `--full` adds the full
run to `--check-node` or `--check-edge`. The test also works against
the published site (`--url https://carbonscott.github.io/lcls2/dev/design/`).

## sample_statements.py

```bash
python docs/design/tools/sample_statements.py --seed S --n 40 [--reserve 20] [--min-per-cell 2] [--model PATH] [--out sample.json] [--markdown sample.md]
```

Splits every PROSE field attached to a node (its own fields and code-ref
notes, its decisions, the tour steps about it, the edges leaving it) into
sentences, tags each with node id, level (1, 2, 3+), outside_repo and field,
and draws a sample stratified over level x outside_repo (proportional, at
least `--min-per-cell` (default 2) per non-empty cell when n allows it,
`random.Random(S)`; exactly n sentences), plus exactly `--reserve` extra
sentences drawn from the rest in proportion to the cell sizes (no per-cell
minimum). Prints the seed, the cell counts and markdown tables; `--out`
writes JSON.

## plant_viewer_defects.py

```bash
cp -r docs/design /tmp/viewer-copy
python docs/design/tools/plant_viewer_defects.py /tmp/viewer-copy hide-prose       # or no-edge-labels
```

Edits `COPY_DIR/viewer.js` of a copy of `docs/design` (it refuses the viewer
next to the script) to plant a known defect, so that one can show that the
browser test catches it: `hide-prose` stops the viewer rendering node prose
(the full run then reports nodes_visited < N), `no-edge-labels` stops it
drawing the labels of arrows between boxes (the full run then reports
`edge_label=fail`). Serve the copy and run `browser_test.py` against it; the
full run must exit nonzero. Exit 0 if the defect was planted, 1 if the code
to change was not found exactly once or on a usage error.

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
| `#map g.edge[data-edge-ids]` | a drawn arrow (its line) and the model edge ids it stands for; `.is-highlighted` in a tour step, `.is-selected` while its flows are listed; stub arrows also have `.stub` and `data-node-id` |
| `#map g.edge-label[data-edge-ids]` | the label of an arrow between two boxes in view; click (or Enter) lists its flows in `#edge-flows` |
| `#map g.stub-chip[data-node-id][data-edge-ids]` | the tag at the map edge of a stub arrow to a node outside the current level; `data-node-id` is that node; click (or Enter) goes there |
| `#edge-flows[data-edge-ids]`, `#edge-flows li.flow[data-edge-id]`, `#edge-flows-close` | the flows of the clicked arrow, at the top of the detail panel; each item links both ends (`a.flow-end`) |
| `#tour-step-prose` | the rendered prose of the current tour step |
| `#help-toggle`, `#help`, `#help-close` | "How to read this page": the button, the panel (hidden until opened) and its close button |
| `#read-toggle` | "Read as one page" / "Back to the map" |
| `#read-page section[data-node-id] > .read-title` | one section per node in the one-page view, with the node title |

URL routes: `#/` (overview), `#/node/<id>`, `#/tour/<k>`, `#/read` (the
whole model as one page) and `#/read/<id>` (the one-page view, scrolled to a
node). Keys: Escape or Backspace zoom out (Escape leaves the tour); in the
tour, Left and Right arrows move between steps; Enter on a focused edge label
or stub tag activates it.

Links in the page header (`../`, `editing-guide/`) and `site-page` sources
(`../features/...`) work only on the built site (`mkdocs serve` or
`mkdocs build`), not when `docs/design` is served on its own with
`python -m http.server`. The browser test does not follow them.
