# Design model tools

Scripts for `docs/design/daq-model.json` (the model) and the viewer
(`index.html`, `viewer.js`, `viewer.css`). Run them from the repository root.
This directory is excluded from the MkDocs site (`exclude_docs` in
`mkdocs.yml`). See `docs/design/editing-guide.md` for how to edit the model.

Requirements: Python 3 with `jsonschema` (in `docs/requirements.txt`); for
the browser tests (`browser_test.py`, `geometry_check.py`) also `playwright`
and its Chromium (`pip install playwright && python -m playwright install
chromium`). The validator needs a full clone (the pinned commit's files are
read with git). The page loads its fonts (Archivo, Source Serif 4, IBM Plex
Mono) from Google Fonts, so the browser tests need network access to
fonts.googleapis.com and fonts.gstatic.com.

To serve the viewer for the browser tests:

```bash
python -m http.server 8000 --bind 127.0.0.1 --directory docs/design &   # or a free port
```

## validate.py

```bash
python docs/design/tools/validate.py [--model PATH] [--schema PATH] [--repo PATH] [--outline]
```

Schema check (every error, with its JSON path) plus the semantic rules (ids,
parents and levels, edges, tour, sources and cross-links, code references at
`code_base.commit`, node rules, decisions, site-page URLs) and the layout
rules (the `map` block, each top-level part's `place`, each detail grid).
Prints `ERROR: <where>: <what>` lines (a layout error starts with its code,
e.g. `ERROR [E-CELL-SHARED]`), then the summary lines

```text
nodes=N edges=E levels=L tour_steps=T code_refs=R sources=S placed=X/N grids=G/P errors=K
layout_text=M map_edges=A/B
```

`placed`: top-level parts with a valid place plus lower nodes with exactly
one cell in their part's detail grid; `grids`: parts with children whose
detail grid is valid; `layout_text`: the human-readable strings of the layout
(see `iter_layout_text`); `map_edges`: of the B pairs of different top-level
parts joined by an edge, the A that a map line draws or `map.omitted` lists
with a reason. Exit 0 iff `errors=0`; 1 if there are errors; 2 if a file
cannot be read or parsed. `--outline` also prints `model_sha256=...`, the
top-level titles (`top: 1. ...`) and the tour step titles (`tour: 1. ...`).
The default `--repo` is the git checkout that contains this script.
`validate.iter_layout_text(model)` yields `(where, text, role)` for every
string of the layout (used by `check_single_source.py`).

## check_single_source.py

```bash
python docs/design/tools/check_single_source.py [--model PATH] [--schema PATH] [--viewer-dir DIR]
```

Checks that the viewer files hold no model content:

1. The first 40 characters of every PROSE field (fields whose schema
   description starts with "PROSE"), and every layout string from
   `validate.iter_layout_text` (map labels, captions, section texts, state
   and transition names, short names, lane, column, band and kind names).
   A layout string of 8 or more characters with more than one word is
   searched as a substring; a shorter one, or a single word, only as a
   quoted literal (`'...'`, `"..."`, `` `...` `` or `>...<`), so `'DRP'` is
   caught but not "DRP" inside a longer word, and a box line "decision" is
   not found in the model field name `decisions`. A layout string equal to a
   kind id is not searched (kind ids are UI enums the viewer may hold). All
   searches are case-sensitive and also cover the HTML- and JSON-escaped
   forms.
2. Every title and edge label of 12 or more characters.
3. Every 40-character window of every PROSE field, taken every 20 characters
   (plus the last window of each field), so that text copied from the middle
   of a field is caught too.
4. Every model node id (other than the kind ids `data`, `trigger`, `timing`,
   `control`, `monitoring`, which are UI enums) as a quoted literal in
   `viewer.js`: the viewer must not hard-code the model's structure.

Prints, in this order (each count preceded by `FOUND:` lines for its hits):

```text
strings_checked=N found_in_viewer=M        # N = prose prefixes + layout strings
titles_checked=N titles_found_in_viewer=M
windows_checked=N windows_found_in_viewer=M
layout_checked=L                           # the layout strings among the N above
node_ids_in_viewer=K
```

Exit 0 iff every M and K is 0.

## browser_test.py

```bash
python docs/design/tools/browser_test.py --url http://127.0.0.1:8000/ [--headed] [--screenshot-dir DIR]
python docs/design/tools/browser_test.py --url http://127.0.0.1:8000/ --layout [--full]
python docs/design/tools/browser_test.py --url http://127.0.0.1:8000/ \
    --check-node ID --expect-title TEXT --expect-prose SUBSTRING [--full]
python docs/design/tools/browser_test.py --url http://127.0.0.1:8000/ --check-edge ID [--full]
```

Full run (default). The page is driven only by clicks and keys, as a reader
would. It prints:

```text
nodes_visited=V/N tour_steps=S/T console_errors=C
smoke stub_click=ok arrow_keys=ok help=ok read_page=R/N third_party=Q
map parts=A/8 lanes=L bands=B columns=K
detail opened=X/P
tour steps=S/T highlighted=H/T
multiples panels=M/6
sequence rows=R/T
matrix cells=C2/C
console_errors=C
```

- `nodes_visited`: a node counts when it is reached by clicking (its map box
  for a top-level part; its box or its group's title strip in its part's
  detail, opened by clicking the part's map box, for a lower node) **and**
  `#detail-title[data-node-id]` names it **and** the panel's visible title
  equals the model title (whitespace-normalized) **and** the visible prose
  (`#detail-prose`) contains the first 30 characters of the node's prose as
  plain text (markup reduced to the text the viewer shows).
- `tour_steps`: stepping with the pips and `#tour-next`, step k counts when
  `#tour-step-title[data-step-index=k]` shows its title, `#tour-step-prose`
  contains the first 30 characters of its prose as plain text (markup
  removed, `[[id]]` replaced by the node title) and the tour map shows a
  callout (`g.callout[data-part]`) on the top-level part of the step's node.
- `smoke`: `stub_click` = clicking the first neighbour tag (`g.stub`) of the
  detail shown on `#/` opens the detail of the part it names; `arrow_keys` =
  with focus in the tour, Right and Left move to step 2 and back; `help` =
  `#help-toggle` opens `#help` and `#help-close` (or the toggle) closes it;
  `read_page` = in `#/read` every node has one `section[data-node-id]` whose
  title (`.read-title`, else its first heading) is the node title (R of N);
  `third_party` = requests to hosts other than the page's own origin,
  fonts.googleapis.com and fonts.gstatic.com (must be 0).
- `map`: parts with a map box (`g.box[data-part]`) of the top-level parts;
  distinct `data-lane` values (must equal `map.lanes.count`); band label
  groups (must equal the number of `map.bands`); column label groups (must
  equal the number of `map.columns`). The map's viewBox must be
  `map.viewbox`, and boxes, lines and labels carry no transform attribute.
- `detail`: a part with children counts when clicking its map box opens
  `#detail-view svg.detail[data-detail=part]` drawing every descendant as a
  `g.box[data-node]` or `g.dgroup[data-node]`. On `#/` the detail shown must
  be `map.default_detail`.
- `tour highlighted`: step k counts when the callout is on the step node's
  top-level part **and** the `.hot` elements of the tour map (line ids of
  `path.ln.hot`, `box:<id>` of `g.box.hot`) are exactly the step's
  `map.tour` highlight list, with every lane copy hot, **and** at least one
  hot box or line belongs to that part **and** the visible tokens (`g.tok`
  at opacity 1; `data-t`, `data-target="x,y"`) are the step's `map.tour`
  tokens **and** the step node is `.hot` in `#tour-detail`.
- `multiples`: figure i counts when it holds `svg.map.mini[data-kind]` with
  the kind of `map.multiples[i]`, a figcaption, and its undimmed lines are
  exactly the lines of that kind, at least one (`all`: none dimmed).
- `sequence`: row k (`#sequence svg .row[data-step-index=k]`) counts when it
  is there once, its aria-label contains the step title, and clicking it
  opens tour step k.
- `matrix`: C is the number of (from part, to part) pairs of model edges
  whose top-level parts differ; the cell `td[data-from][data-to]` of a pair
  counts when its relation items (`.ni[data-edge-ids]`) show exactly those
  edges' labels, deduplicated by kind and label, and name only edges of that
  pair. Cells of other pairs must be empty and the headers must show every
  part's `place.short`.
- `console_errors`: console errors and warnings, page errors, and failed or
  HTTP >= 400 requests to the page's own origin.

Exit 0 iff every count is complete, every smoke check is `ok` with R = N,
Q = 0 and C = 0. A check that finds nothing to test fails. A full run takes
about one to two minutes.

`--layout` loads the page at 744x1000 and 1440x900 and compares, on the
map, each top-level part's union box (viewBox units), the set of rendered
text strings and the number of visible elements; it prints
`layout_identical=<bool> parts=<n>`. Then, at widths 400, 744 and 1440, it
prints `width=<w> page_hscroll=<px>` (the page's horizontal overflow, the
maximum over the loaded page, a detail opened and a tour step), after the
744 line the informational `inner_scroll=<section:px,...> min_text_px=<px>`
(horizontal scroll inside each figure container; the smallest rendered SVG
text in CSS px), and finally `console_errors=C`. It fails if the layouts
differ, any `page_hscroll` > 0, `html`, `body` or an element around a section
sets `overflow-x: hidden` or `clip`, or C > 0.

`--check-node` opens the node by deep link (`#/node/ID`) and by clicking
(its part's map box, then its box or group in the detail), and checks the
panel title and that the rendered prose contains SUBSTRING; it prints
`check_node id=ID title_ok=<bool> prose_ok=<bool> console_errors=C`.
SUBSTRING is matched against the rendered, visible text, so it must not
contain markup (backticks, `[[...]]`, link syntax).
`--check-edge ID` looks for the edge where the page draws it: an edge inside
one part as a `path.ln[data-edge-ids~=ID]` in that part's detail; an edge
between two parts with a lower-level end as the neighbour tag
(`g.stub[data-other][data-dir][data-edge-ids~=ID]`) in the detail of each
part whose end is a lower node; an edge between two top-level parts as a map
line or a matrix relation. It prints `check_edge id=ID drawn=<bool>
console_errors=C`. `--full` adds the full run to `--check-node`,
`--check-edge` or `--layout`. The test also works against the published site
(`--url https://carbonscott.github.io/lcls2/dev/design/`).

## geometry_check.py

```bash
python docs/design/tools/geometry_check.py --url http://127.0.0.1:8000/ [--model PATH_OR_URL] [--verbose]
```

Waits for the first render and `document.fonts.ready`, checks that the
Archivo font is loaded (`document.fonts.check('600 15px Archivo')` and a
loaded Archivo face) and prints `font=Archivo`. It then measures the map
(`#map svg.map`) and the detail of every top-level part with children
(opened by clicking the part's map box), all in SVG viewBox units:

- `line_through_box`: (line, box) pairs where a point sampled every 2 units
  along a `path.ln` lies inside the box rect shrunk by 3 units and the box
  (its `data-box`, with `@<lane>` for a per-lane box; its `data-node` in a
  detail) is not in the line's `data-through`, `data-ends`, `data-from-box`
  or `data-to-box`. A per-lane copy of a line (`data-lane=i`) may name its
  own lane's box `b` for `b@i`. Neighbour tags count as boxes (their own
  connector may touch them); for a group only its title strip
  (`rect.gtitle`) counts, and lines ending on a kid of the group are exempt.
- `text_overflow`: texts that extend more than 1 unit past their container
  (the rect of their box, tag or group), plus free labels (`text.lab`,
  notes, band and column labels) that extend past the viewBox or overlap a
  box, tag or group title strip.
- informational: `crossings_allowed` (pairs that would count but the box is
  listed for the line), `line_over_text` (a line drawn across a text other
  than its own label), `label_on_box` (the free labels on a box, also
  counted in `text_overflow`).

Tour tokens (`g.tok`) and selection callouts (`g.callout`) are not measured.
It prints `font=Archivo`, one `view=<map|detail:ID> ...` line per view with
`PROBLEM:` lines naming each counted line, box and text, then

```text
views=V line_through_box=X text_overflow=Y
crossings_allowed=K line_over_text=J label_on_box=Q
```

with V = 1 + P (P: top-level parts with children). Exit 0 iff the font is
Archivo, V = 1 + P, every view has a box, X = 0 and Y = 0. `--verbose`
also lists the allowed crossings and the `line_over_text` pairs.

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
python docs/design/tools/plant_viewer_defects.py /tmp/viewer-copy hide-prose       # or no-multiples
```

Edits `COPY_DIR/viewer.js` of a copy of `docs/design` (it refuses the viewer
next to the script) to plant a known defect, so that one can show that the
browser test catches it:

- `hide-prose`: the viewer stops rendering node prose in the panel; the full
  run then reports `nodes_visited` < N.
- `no-multiples`: the viewer stops drawing the small multiples (the
  `#multiples` figures); the full run then reports `multiples panels=0/6`.

Serve the copy and run `browser_test.py` against it; the full run must exit
nonzero. Exit 0 if the defect was planted, 1 if the code to change was not
found exactly once or on a usage error. A copy whose `viewer.js` starts with
an undefined call (`plantedUndefinedFunction();`) must also make the full
run exit nonzero (the page never becomes ready and the page error is
counted).

## Viewer test hooks

Stable attributes for tests (the UI works the same for people):

| Hook | Meaning |
|---|---|
| `body[data-ready="true"]` | set after the first render |
| `body[data-mode]` | `browse`, `tour` or `read` |
| `#map-section`, `#tour`, `#multiples`, `#sequence`, `#matrix` | the five figures, in this order; `#read-page` replaces them in read mode |
| `#map svg.map` | the map, with the viewBox of `map.viewbox` |
| `g.box[data-part][data-node][data-box]` (+ `[data-lane]`) with `rect.b` | a map box: its top-level part, the node it stands for, its box id (and lane) |
| `g.column-label[data-column]`, `g.band-label[data-band]` | column headers; one group per band |
| `path.ln[data-line][data-kind][data-edge-ids][data-through][data-ends]` (+ `[data-lane]`) | a map line; through/ends list box keys `<box id>` or `<box id>@<lane>` |
| `circle.port[data-line]`, `text.lab[data-line]` | ports and labels of a line |
| `#chips button.chip[data-kind][aria-pressed]` | the "Emphasize" chips (`all` or a kind) |
| `#detail-view svg.detail[data-detail]` | the detail of a top-level part under the map |
| `g.box[data-node]` (`.hot` when highlighted), `g.dgroup[data-node]` with `rect.gtitle` | detail boxes; groups and their clickable title strip |
| `path.ln[data-edge-ids][data-from-box][data-to-box]` | an edge inside the detail |
| `g.stub[data-other][data-dir][data-edge-ids]` with `rect` and a connector `path.ln` | one neighbour tag per (neighbour part, direction) |
| `#detail-title[data-node-id]`, `#detail-prose` | the node panel: title and rendered prose |
| `#tour svg.map`, `#tour-prev`, `#tour-next`, `#pips button.pip[aria-current]` | tour map and controls |
| `#tour-step-title[data-step-index]`, `#tour-step-prose` | title (k is 1-based) and text of the current step |
| `g.callout[data-part]`, `g.tok[data-t][data-target]` | the step's callout; event tokens (visible ones have opacity 1) |
| `#tour-detail svg.detail[data-detail]` | the detail under the tour map, step node `.hot` |
| `#multiples figure` with `svg.map.mini[data-kind]` and `figcaption` | the six small multiples |
| `#sequence svg .row[data-step-index]` | one row per tour step; click opens that step |
| `#matrix table.nsq td[data-from][data-to]`, `.ni[data-edge-ids]` | matrix cells and their listed relations |
| `#read-page section[data-node-id]` | one section per node in the one-page view |
| `#help-toggle`, `#help`, `#help-close` | "How to read this page": the button, the panel (hidden until opened) and its close button |

URL routes: `#/` (top; the map's detail shows `map.default_detail`),
`#/node/<id>` (the detail of the node's part, node highlighted, panel on the
node), `#/tour/<k>` (tour step k), `#/read` (the whole model as one page)
and `#/read/<id>` (the one-page view, scrolled to a node).

Links in the page header (`../`, `editing-guide/`) and `site-page` sources
(`../features/...`) work only on the built site (`mkdocs serve` or
`mkdocs build`), not when `docs/design` is served on its own with
`python -m http.server`. The browser test does not follow them.
