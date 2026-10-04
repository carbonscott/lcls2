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

Layout codes: `E-PLACE-MISSING`, `E-CELL-SHARED`, `E-CHILD-TWICE`,
`E-CHILD-MISSING`, `E-GRID-FOREIGN`, `E-BOX-OUTSIDE-CELL`, `E-LINE-REF`,
`E-LINE-ENDS`, `E-LINE-THROUGH`, `E-TOUR-MAP`, `E-SEQUENCE`, `E-LADDER`,
`E-MAP-EDGES`, `E-SIDES`. Some rules in detail:

- Map lines: a line's `d` may hold several subpaths, each starting with its
  own `M` (for example one per lane segment of a rail, so that each segment
  gets its own arrowhead). With one subpath, its two end points lie on the
  border (+-2 units) of `ends` boxes. With several, each subpath's two end
  points lie on the border of an `ends` box or a `through` box; an `M` that
  draws nothing is an error (`E-LINE-ENDS`). Every `ends` box is touched by
  an end point. Every `through` box is crossed border to border by the line
  as a whole: by one subpath, or across the gap between a subpath that ends
  on its border and another that starts on its border on the far side
  (`E-LINE-THROUGH`). The gap from each subpath's end to the next
  subpath's start must run across exactly one `through` box, border to
  border; a gap anywhere else (outside every box) means part of the line is
  not drawn (`E-LINE-THROUGH`). Per-lane lines (`{y}`, `{y-28}`, `{y+28}`) are checked
  once per lane, as before.
- `E-TOUR-MAP` also flags an empty `map.tour[i].highlight`.
- `E-SIDES`: in a part's `detail.sides`, the side given for a neighbour must
  agree with where the neighbour is on the map. `left` means every box
  centre of the neighbour (all lane copies) lies left of the part's leftmost
  box edge; `right`, `top` and `bottom` likewise (SVG y grows downwards). A
  diagonal neighbour may use either side that agrees. The error line names
  the entry, the neighbour's box centres and the sides that would agree. A
  part without a valid place is skipped (its own error says why). Every
  neighbour that gets a tag in a part's detail (an edge with one end on a
  node below the part and the other end in that neighbour) needs a `sides`
  entry: without one the viewer would put its "from" tag on the left and
  its "to" tag on the right (`E-SIDES`, "no side for ...").
  `E-SIDES` does not lower the `grids` count, which is about grid cells.

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
   kind id is not searched (kind ids are UI enums the viewer may hold) and
   is not counted as checked: it is counted in `skipped_kind_ids`. All
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
strings_checked=N found_in_viewer=M        # N = prose prefixes + layout strings searched
titles_checked=N titles_found_in_viewer=M
windows_checked=N windows_found_in_viewer=M
layout_checked=L skipped_kind_ids=S        # L: layout strings searched (among the N above)
node_ids_in_viewer=K
```

Every "checked" count counts only strings that were actually searched. S is
the number of layout strings equal to a kind id, which are not searched;
L + S equals validate.py's `layout_text` (an empty layout string, if there
ever is one, is also skipped and reported as `skipped_blank=B` on the same
line). Exit 0 iff every M and K is 0.

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
map parts=A/8 lanes=L bands=B columns=K boxes=O/Q
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
  `boxes=O/Q`: Q is the number of map box copies the JSON lists (a per-lane
  box once per lane); O counts those drawn exactly once as
  `g.box[data-box]` (`[data-lane=i]` for lane i) whose `rect.b`, measured in
  viewBox units with CSS transforms included, equals the JSON rect within
  0.5 units (x, w, h from `place.boxes`; y from the box, or
  `lanes.y[i] - h/2` for a per-lane box). A box the JSON does not list also
  fails. So a CSS shift of a map box fails the map check.
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
  is there once, its aria-label contains the step title, it draws one arrow
  (`path.ln`) that starts on the `from` lifeline and ends on the `to`
  lifeline of the step's row in `map.sequence` (an end point within 10
  units of the centre of a lifeline header `g.hdr[data-lifeline]`; no
  lifeline there means `start`), its label (`text.lab`) is that row's
  `label`, and clicking it opens tour step k.
- `matrix`: C is the number of (from part, to part) pairs of model edges
  whose top-level parts differ; the cell `td[data-from][data-to]` of a pair
  counts when its relation items (`.ni[data-edge-ids]`) show exactly those
  edges' labels, deduplicated by kind and label, and name only edges of that
  pair. Cells of other pairs must be empty and the headers must show every
  part's `place.short`.
- `console_errors`: console errors and warnings, page errors, and failed or
  HTTP >= 400 requests to the page's own origin.

Exit 0 iff every count is complete (including `boxes` O = Q), every smoke
check is `ok` with R = N, Q = 0 and C = 0. A check that finds nothing to test fails. A full run takes
about one to two minutes.

`--layout` loads the page at 744x1000 and 1440x900 and compares, on the
map, each top-level part's union box (viewBox units), the set of rendered
text strings and the number of visible elements; it prints
`layout_identical=<bool> parts=<n>`. Then, at widths 400, 744 and 1440, it
prints `width=<w> page_hscroll=<px>` (the page's horizontal overflow, the
maximum over the loaded page, a detail opened and a tour step), after the
744 line the informational `inner_scroll=<section:px,...> min_text_px=<px>`
(horizontal scroll inside each figure container; the smallest rendered SVG
text in CSS px), then

```text
fullsize map-section=ok|fail tour=ok|fail sequence=ok|fail
```

and finally `console_errors=C`. The `fullsize` check runs at 744x1000: each
of `#map-section`, `#tour` and `#sequence` has one `button.fullsize` with
`aria-pressed="false"` on load, and its figure (`#map svg.map`,
`#tour svg.map`, `#sequence svg`) is fitted: no horizontal scroll in any
scroll container between the svg and its section, and the svg no wider
than its sheet's content box. Pressing the button sets
`aria-pressed="true"`, makes the svg exactly as wide (1 px) as its viewBox
and makes the sheet scroll, while the page itself does not scroll;
pressing it again fits the figure again. `--layout` fails if the layouts
differ, any `page_hscroll` > 0, the map sheet of `#map-section` or of
`#tour` scrolls horizontally at 744 on load (a `PROBLEM:` line gives the
pixels), a `fullsize` check fails, `html`, `body` or an element around a
section sets `overflow-x: hidden` or `clip`, or C > 0.

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
python docs/design/tools/geometry_check.py --url http://127.0.0.1:8000/ [--model PATH_OR_URL] [--width 1440] [--height 900] [--verbose]
```

Run it at each width that matters, e.g. `--width 744` and `--width 1440`:
every count except `small_text` is in viewBox units and does not depend on
the width. The page is measured in its default state (no "Full size"
toggle pressed).

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
  (the rect of their box or tag; a group's own texts, i.e. its title,
  against the group's title strip `rect.gtitle`, not the whole group rect),
  plus free labels (`text.lab`, notes, band and column labels) that extend
  past the viewBox or overlap a box, tag or group title strip.
- `box_overlap`: pairs of rects of one view that overlap by more than 1 unit
  in both directions: box rects, tag rects and whole group rects. A box
  inside the group of its own parent node is not an overlap (a kid that
  sticks out of its group is).
- `line_over_label`: (line, text) pairs where the line is painted above the
  text (later in document order, which is SVG paint order), a point sampled
  every 2 units along the line lies in the text's bounding box shrunk by 1
  unit, and no opaque rect painted after the line covers that point; for
  example a tag connector drawn over a group title. A line painted under an
  opaque box (or under the text) does not count, nor a line's own labels.
- `small_text`: texts in the map or a detail whose rendered size is below
  `MIN_TEXT_PX` (7 CSS px) at the run's viewport: the computed font size
  times the text's screen scale. `min_text_px` is the smallest rendered
  size; the `PROBLEM: small_text` line of a view lists its smallest texts
  (all of them with `--verbose`), and an `INFO: smallest text ...` line
  names the smallest text of the run.
- `text_overlap`: pairs of visible texts of one view whose bounding boxes
  overlap by more than 1 unit in both directions (box titles and sub lines,
  tag texts, group titles, line labels, notes, band, column and ladder
  labels), so that one is printed over the other.
- informational: `crossings_allowed` (pairs that would count but the box is
  listed for the line), `line_over_text` (a line drawn across a text other
  than its own label), `label_on_box` (the free labels on a box, also
  counted in `text_overflow`).

Tour tokens (`g.tok`) and selection callouts (`g.callout`) are not measured.
It prints `font=Archivo`, one `view=<map|detail:ID> ...` line per view with
`PROBLEM:` lines naming each counted line, box and text, then

```text
views=V line_through_box=X text_overflow=Y
crossings_allowed=K line_over_text=J label_on_box=Q box_overlap=O line_over_label=W small_text=S text_overlap=E min_text_px=P
```

with V = 1 + P (P: top-level parts with children). The view lines carry the
same new fields. Exit 0 iff the font is Archivo, V = 1 + P, every view has
a box, and X, Y, O, W, S and E are all 0 (K, J and Q are informational).
`--verbose` also lists the allowed crossings, the `line_over_text` pairs and
every small text.

Each failing count has been shown to fail on a planted copy (the planting
script lives outside the repository): a box moved onto a line plus a sub
line too long for its box (`line_through_box`, `text_overflow`); a map box
moved over its neighbour (`box_overlap`); a long group title that wraps
under the tag connectors (`line_over_label`); an unbreakable 70-character
kid title that makes the detail wide and its text small (`small_text`);
two pairs of map labels moved on top of each other (`text_overlap`, kind
`text-overlap`).

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
python docs/design/tools/plant_viewer_defects.py /tmp/viewer-copy KIND
```

Edits one file (`viewer.js`, or `viewer.css` for `shift-map-box`) of a copy
of `docs/design` (it refuses the viewer next to the script) to plant a known
defect, so that one can show that the browser test catches it. KIND:

- `hide-prose`: the viewer stops rendering node prose in the panel; the full
  run then reports `nodes_visited` < N.
- `no-multiples`: the viewer stops drawing the small multiples (the
  `#multiples` figures); the full run then reports `multiples panels=0/6`.
- `page-error`: `plantedUndefinedFunction();` at the top of `viewer.js`; the
  page never becomes ready, every count is 0 and the page error is counted
  (`console_errors=1`).
- `shift-map-box`: a CSS rule shifts the TEB's map box 30 px to the right
  (a CSS transform, no transform attribute); the full run reports
  `map ... boxes=16/17` and names the box.
- `sequence-reversed`: the sequence chart draws each arrow between two
  lifelines backwards; the full run reports `sequence rows` < T and names
  each row's drawn and expected lifelines.

Serve the copy and run `browser_test.py` against it; the full run must exit
nonzero. Exit 0 if the defect was planted, 1 if the code to change was not
found exactly once or on a usage error.

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
| `#sequence svg .row[data-step-index]` | one row per tour step (its arrow `path.ln`, label `text.lab`); click opens that step |
| `#sequence svg g.hdr[data-lifeline]` with `rect` | a lifeline header; its centre is the lifeline's x |
| `button.fullsize[aria-pressed]` in `#map-section`, `#tour`, `#sequence` | "Full size": pressed, the figure is drawn at its viewBox width and its sheet scrolls; unpressed, it fits |
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
