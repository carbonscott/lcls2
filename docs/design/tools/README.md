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
python docs/design/tools/browser_test.py --url http://127.0.0.1:8000/ [--headed] [--screenshot-dir DIR] [--only GROUP[,GROUP]]
python docs/design/tools/browser_test.py --url http://127.0.0.1:8000/ --layout [--full]
python docs/design/tools/browser_test.py --url http://127.0.0.1:8000/ \
    --check-node ID --expect-title TEXT --expect-prose SUBSTRING [--full]
python docs/design/tools/browser_test.py --url http://127.0.0.1:8000/ --check-edge ID [--full]
```

The page is one map with three modes ("Explore the parts", "Follow one
event", "Compare kinds") and one card under it, then the N-squared matrix as
a reference card. The test drives it only by clicks and keys, as a reader
would. The primary viewport is 744x1000 (an iPad held upright); some checks
also run at 1440x900. The page is loaded afresh for each check group, so
that one failure does not cascade.

Full run (default). It prints `PROBLEM:` lines (one per failure, naming the
element) and `NOTE:` lines (informational only), then, in this order (extra
fields are always at the end of a line):

```text
nodes_visited=V/N tour_steps=S/T console_errors=C
smoke stub_click=ok arrow_keys=ok help=ok read_page=R/N third_party=Q arrow_scope=ok compare_tap=ok fullsize_keys=ok
map_first viewport=744x1000 map_top=A map_bottom=B above_map=<names> frame_top=F
map_first viewport=1440x900 map_top=A map_bottom=B above_map=<names> frame_top=F
modes=M full_maps=F
full_map_count explore=1 tour_map=1 tour_seq=1 compare=1 displayed=explore,tour_map
map parts=A/8 lanes=L bands=B columns=K boxes=O/Q
detail opened=X/P
tour steps=S/T highlighted=H/T on_main_map=G/T tag_clear=K/T
tour_card text=X/T detail=Y/T
tour_fit viewport=744x1000 tourbar_bottom=Y1 step_title_bottom=Y2
multiples panels=M/6 mode=<compare|FAIL:...>
sequence rows=R/T mode=<tour|FAIL:...>
emphasize captions=K/K hidden_ok=<bool>
card default=<overview|FAIL:...> after_close=<overview|FAIL:...> nav=X/9 sticky_head=<bool> end_footer=<bool> folded=<bool> stuck_view=K/K
card_head_px=H
matrix cells=C2/C hscroll=<px> sticky_head=<bool> close_buttons=<n> end_footer=<bool> divider=<bool>
matrix_min_text_px=P
deeplinks=D/4
page_height=H
min_tap_px=P
scroll_jumps=J/N viewport=744x1000 failed=F expected=E moves_page_ok=<bool> control_moved=K/N
scroll_jumps=J/N viewport=1440x900 failed=F expected=E moves_page_ok=<bool> control_moved=K/N
console_errors=C
elapsed nodes=s,tour=s,...
```

`full_map_count`, `tour_fit`, `card_head_px`, `matrix_min_text_px`,
`min_tap_px`, `control_moved` and `elapsed` are informational (they never
fail the run); every other value is a check. Every `PROBLEM:` line fails the
run, also when every printed value passes (for example `#card-close is not
displayed on the card of X`); purely informational output is a `NOTE:` line.

- `nodes_visited` (group `nodes`): in Explore mode, a node counts when it is
  reached by clicking (its map box for a top-level part; for a lower node,
  its box or its group's title strip in the detail drawing of its part,
  `#part-card #detail-view svg.detail[data-detail=part]`, opened by clicking
  the part's map box) **and** `#part-card #detail-title[data-node-id]` names
  it **and** the visible title equals the model title (whitespace-normalized;
  when `#detail-title` is visually hidden, class `vh`, as for a top-level
  part, both it and `#card-title` must read the title) **and** the visible
  prose (`#detail-prose`) contains the first 30 characters of the node's
  prose as plain text (markup reduced to the text the viewer shows). The
  same walk checks the folds of all N panels (see `card folded`).
- `tour_steps` (group `tour`): after pressing "Follow one event"
  (`#modes button.mode[data-mode=tour]`), stepping with the pips and
  `#tour-next`, step k counts when `#tour-step-title[data-step-index=k]`
  shows its title, `#tour-step-prose` contains the first 30 characters of
  its prose as plain text, and `#map svg.map` shows a callout
  (`g.callout[data-part]`) on the step node's top-level part.
- `smoke`: `stub_click` = in the detail of the first part that has a
  neighbour tag (`g.stub[data-other]`), clicking the tag opens the card of
  the part it names; `arrow_keys` = on `#/tour/1`, with the focus in
  `#map-section` (on `#tour-next`), Right then Left move to step 2 and back;
  `arrow_scope` = in tour mode at step 3 (pip 3), after the matrix head is
  clicked (the focus is then outside `#map-section`), ArrowRight pressed
  twice leaves the tour at step 3 and reaches the window not
  default-prevented (the browser can still scroll sideways with it);
  `help` = `#help-toggle` opens `#help` and `#help-close` (or the toggle)
  closes it; `read_page` = in `#/read` every node has one
  `section[data-node-id]` whose title (`.read-title`, else its first
  heading) is the node title (R of N); `third_party` = requests during the
  whole run to hosts other than the page's own origin, fonts.googleapis.com
  and fonts.gstatic.com (must be 0). `compare_tap` (A16) = in Compare kinds,
  a real tap on the small map of the first kind with a caption, with
  `#map-section`'s top in view, switches to explore with that kind's chip
  `aria-pressed="true"` and `#kind-caption[data-kind=kind]` displayed, and
  the page does not move; then, with the small map of the last kind centred
  in the viewport (so that `#map-section`'s top is above it), a tap does
  the same and brings `#map-section`'s top to the viewport's top (+-2 px,
  or the page cannot scroll that far). `fullsize_keys` (A17) = on
  `#/tour/2` with the map's Full size pressed (the map frame `#map` must
  scroll sideways), ArrowRight pressed twice with the focus on a map box in
  the frame, and again after a click on an empty point of the frame, leaves
  the tour at step 2, is not default-prevented and keeps the mode.
- `map_first`: on `#/` after the page is ready, at 744x1000 and at
  1440x900. `map_top`/`map_bottom` are the top and bottom of the
  `#map svg.map` bounding box and `frame_top` (printed last) the top of its
  frame `#map` (CSS px, page coordinates, rounded). `above_map` names the blocks between
  the h1 and the frame: walking down from `.wrap`, the candidates are the
  displayed elements (not `display: none`, not `visibility: hidden`) larger
  than 1 px in both directions (a zero-size or visually hidden element does
  not count; the walk goes into it) that are not ancestors of
  `h1#model-title` or of `#map`; the outermost candidate counts iff its top
  >= h1 bottom - 1 and its bottom <= frame top + 1; its name is its id, else
  its first class, else its tag. Pass iff `above_map` is exactly
  `modes,chips`, `#modes` and `#chips` are direct children of
  `#map-section`, at 744x1000 B <= 1000 and at 1440x900 A <= 450.
- `modes`/`full_maps` (group `modes`): M counts the `#modes button.mode`
  buttons whose press sets `body[data-mode]` to their `data-mode`, puts
  `aria-pressed="true"` on that button only, shows `#chips` only in explore,
  `#tour-controls` only in tour and `#mode-note` only in tour and compare
  (the buttons must be exactly explore, tour and compare). A full-size map
  drawing is any `svg` that is not `.mini` and not `.detail` and either has
  the viewBox of `map.viewbox` or contains `g.box[data-part]` for every
  top-level part. F is the largest number of them in the document over
  explore, tour (map view), tour (sequence view) and compare;
  `full_map_count` prints each count and the states in which `#map svg.map`
  is displayed. Pass iff M = 3, F = 1, every state has exactly one drawing,
  it is `#map svg.map`, and it is displayed in explore and tour (map view)
  only.
- `map`: as before, on `#/`: parts with a map box (`g.box[data-part]`) of
  the top-level parts; distinct `data-lane` values (must equal
  `map.lanes.count`); band label groups (must equal the number of
  `map.bands`); column label groups (must equal the number of
  `map.columns`). The map's viewBox must be `map.viewbox`, and boxes, lines
  and labels carry no transform attribute. `boxes=O/Q`: Q is the number of
  map box copies the JSON lists (a per-lane box once per lane); O counts
  those drawn exactly once as `g.box[data-box]` (`[data-lane=i]` for lane
  i) whose `rect.b`, measured in viewBox units with CSS transforms
  included, equals the JSON rect within 0.5 units (x, w, h from
  `place.boxes`; y from the box, or `lanes.y[i] - h/2` for a per-lane box).
  A box the JSON does not list also fails, so a CSS shift of a map box fails
  the map check.
- `detail`: a part with children counts when clicking its map box opens
  its card (`#part-card[data-card=part]`) with
  `#part-card #detail-view svg.detail[data-detail=part]` drawing every
  descendant as a `g.box[data-node]` or `g.dgroup[data-node]`. (The page no
  longer opens a part on `#/`: `map.default_detail` is kept in the model for
  compatibility and not used.)
- `tour`, measured on `#map svg.map` in tour mode: `highlighted` = step k
  counts when the callout is on the step node's top-level part **and** the
  `.hot` elements of the map (line ids of `path.ln.hot`, `box:<id>` of
  `g.box.hot`) are exactly the step's `map.tour` highlight list, with every
  lane copy hot, **and** at least one hot box or line belongs to that part
  **and** the visible tokens (`g.tok` at opacity 1; `data-t`,
  `data-target="x,y"`) are the step's `map.tour` tokens **and** the step
  node is `.hot` in `#step-card #tour-detail svg.detail[data-detail=part]`.
  `on_main_map` = step k counts when `#map svg.map` holds exactly one
  displayed `g.callout`, on the step's part (no leftover selection outline
  of Explore), no displayed callout or visible token is anywhere else, the
  map shows at least one visible token when the step has tokens, the only
  full-size map drawing is `#map svg.map` and it is displayed.
  `tag_clear` = step k counts when the map has one callout tag
  (`g.callout rect.ctag`) and its box overlaps no visible text of the map by
  more than 0.5 units in both directions (viewBox units; every displayed
  text outside `g.callout` and `g.tok`, dimmed ones included).
- `tour_card`: `text` = step k counts when `#step-card` is displayed and
  holds `#tour-step-title[data-step-index=k]` with the step title and
  `#tour-step-prose` with the first 30 characters of the step prose, and the
  card also shows the step node's own description: its title, the first 30
  characters of its summary (plain text) and a displayed `button.open-part`
  (the model's `tour.intro` says the component's description follows the
  step text), and `#tour-step-title` and `#tour-step-prose` are displayed
  (a non-zero box, visible, no hidden ancestor) with their tops at or below
  the bottom of the map frame `#map`. `detail` = `#step-card #tour-detail
  svg.detail[data-detail=<top part of the step node>]` is there with the
  step node `.hot` (for a step on a top-level part, the detail is there),
  it is displayed and its top is at or below the map frame's bottom, and
  the top of `#step-card` is not above the bottom of the map frame. `tour_fit` (informational): right after "Follow one event" is
  pressed on `#/` at 744x1000, the page y of the bottom of `#tourbar` and of
  `#tour-step-title` (targets <= 1000: the step controls and the step title
  in the first screen).
- `multiples panels=M/6 mode=...`: in compare mode, figure i of `#mult
  figure` counts when it holds `svg.map.mini[data-kind]` with the kind of
  `map.multiples[i]`, a figcaption, and its undimmed lines are exactly the
  lines of that kind, at least one (`all`: none dimmed). `mode=compare` iff
  the figures are displayed in compare mode (all six) and in neither
  explore nor tour; otherwise `mode=FAIL:<where>`.
- `sequence rows=R/T mode=...`: in tour mode with the sequence view
  (`#tour-controls button.view[data-view=seq]`), row k
  (`#seq svg.seq .row[data-step-index=k]`) counts when it is there once,
  its aria-label contains the step title, it draws one arrow (`path.ln`)
  that starts on the `from` lifeline and ends on the `to` lifeline of the
  step's row in `map.sequence` (an end point within 10 units of the centre
  of a lifeline header `g.hdr[data-lifeline]`; no lifeline there means
  `start`), its label (`text.lab`) is that row's `label`, and clicking it
  shows step k in the step card while the view stays the sequence chart:
  `#tour-step-title[data-step-index=k]` is displayed and the status line
  `#seq-status` (A14) reads "Step k of T: <step title>" and lies within the
  viewport.
  `mode=tour` iff the rows are displayed (all T) only in tour mode with the
  sequence view (not in explore, the tour's map view or compare).
- `emphasize captions=K/K hidden_ok=...`: K is the number of kinds of
  `map.kinds` whose `map.multiples` entry has a caption. A kind counts when
  clicking its chip (`#chips button.chip[data-kind]`) shows
  `#kind-caption[data-kind=kind]` containing the first 30 characters of
  that caption (plain text), with its top at or below the bottom of the map
  frame `#map` (under the map), and leaves undimmed (effective opacity >
  0.5) on `#map svg.map` only lines of that kind, at least one. `hidden_ok` =
  the All chip hides `#kind-caption`, and the caption of an emphasized kind
  is hidden in tour and in compare mode.
- `card`: `default` = on `#/` the card is `#part-card[data-card=overview]`
  (and `#card-title[data-card=overview]`), displayed, without a displayed
  `#card-close`, its top at or below the bottom of the map frame `#map`,
  and `#overview` shows `question`, the first 30 characters of `summary`,
  and how to read the map: `map.sections.map`'s title and the first 30
  characters of its intro (plain text, case ignored) (else `FAIL:` and what
  is wrong: `no-question`, `no-summary`, `no-howto-title`, `no-howto-intro`,
  `card-not-under-map`, ...). `after_close` = after opening a part (its
  map box) and pressing `#card-close`, the card is `data-card=overview`,
  displayed, `#overview` is displayed and not empty and Close is gone,
  **and** the four stuck Close cases below pass (else `FAIL:hidden`,
  `FAIL:empty`, `FAIL:stuck-close-744`, `FAIL:stuck-foot-close-1440`,
  ...). `stuck_view=K/K` (T6) counts the stuck arrow cases. A stuck case:
  on the largest part card (the tallest seen during `nav`), at 744x1000 and
  1440x900, the card's top is put 300 px above the viewport (the head
  stuck; a wrong state fails the case), or, for "Close near the footer",
  every `<details>` of the card is opened and the page scrolled to the
  card's footer; then `#card-next`, `#card-prev` or `#card-close` gets a
  real click (a hit-tested point, no scroll by the test). The case passes
  when `scrollY` did not change, the head's top is still within 2 px of 0,
  the element at the card's horizontal centre 24 px and 120 px under the
  head's bottom (`elementFromPoint`) is content of the new card (inside
  `#part-card .card-body`; for the overview inside `#overview`, for a part
  inside `#detail-view` or `#detail`; not inside an element whose class
  names a fill, filler or spacer, nor an `aria-hidden` child of
  `.card-body`; the block of the card body under the point shows text or a
  drawing), and the new card's first displayed block (`#overview`, else
  `#detail-view`, else `#detail`) starts between 8 px above and 40 px below
  the head's bottom (the reader sees the start of the new card right under
  the head, not its middle, and no blank between). When
  the step card has its own head with `#step-prev`/`#step-next`, the same
  is checked for `#step-card` on the middle step (`#step-text` first,
  content anywhere in `#step-card .card-body`), and those cases also count
  in `stuck_view` (8 cases with the step head, 4 without). `nav` = from
  the overview, `#card-next` pressed 9 times must give the top-level parts
  in model order and then the overview, and `#card-prev` pressed 9 times
  the exact reverse; X counts the positions where both match. `sticky_head`
  = on the largest part card (the tallest seen during `nav`), at 744x1000
  and 1440x900, with the card's top 300 px above the viewport (less for a
  card too short for that), the top of `#card-head` is within 2 px of the
  viewport top, the head is inside the card, and no ancestor of the head has
  `overflow` other than `visible` or `clip`. `end_footer` = the footer
  starts with "End of the overview." on the overview, "End of <part
  title>." on each of the 8 part cards (`#card-foot`), "End of step k of
  T." on the step card (`#step-foot`, steps 1 and 2), each with a displayed
  `a.back-to-map[data-moves-page]`. `folded` = in the node walk, every one
  of the N panels has exactly its folds, each a `details.fold[data-fold]`,
  displayed and closed when the node opens, and no other `<details>` of the
  card is open: `decisions`, `code` and `sources` iff the node's
  `decisions`, `code_refs` and `sources` lists are non-empty, `flows` iff an
  edge crosses the border of the node's subtree (one end inside, one
  outside), `dev` iff `dev_notes` is non-empty. `card_head_px`
  (informational): the tallest card head at 744 (overview and the 8 parts;
  target <= 100).
- `matrix`: `cells` as before: C is the number of (from part, to part)
  pairs of model edges whose top-level parts differ; the cell
  `#matrix table.nsq td[data-from][data-to]` of a pair counts when its
  relation items (`.ni[data-edge-ids]`) show exactly those edges' labels,
  deduplicated by kind and label, and name only edges of that pair; cells of
  other pairs must be empty and the headers must show every part's
  `place.short`. `divider` (T7) = exactly one `.ref-divider`, displayed,
  reading "Reference" (case ignored), between the bottom of `#part-card`
  and the top of `#matrix`. `hscroll` = at 744 the larger of the sideways scroll of the
  table's container (its nearest ancestor with `overflow-x: auto|scroll`;
  `scrollWidth - clientWidth`) and how far the rightmost cell ends past the
  card's content box (`#matrix`), must be 0; no ancestor of the table may
  clip horizontally (`overflow-x: hidden|clip`). `sticky_head` as the
  card's, for `#matrix .card-head` at 744 and 1440 (a spacer is added under
  the page when it cannot scroll far enough). `close_buttons` = buttons in
  `#matrix` (must be 0). `end_footer` = `#matrix-foot` displayed, starting
  with "End of the <`map.sections.matrix.eyebrow` in lower case>.", with a
  displayed `a.back-to-map[data-moves-page]`. `matrix_min_text_px`
  (informational): the smallest font size of the table's text at 744
  (floor about 12).
- `deeplinks`: each route is loaded in a fresh page and must land in view.
  `#/node/<id>` (the deepest lower node): explore mode, the card on the
  node's top-level part, the node `.hot` in its detail, the panel on the
  node, and the top of `#card-head` within [0, 120] px of the viewport top;
  `#/tour/3`: tour mode, step 3, `#map-section` top at the viewport top
  (+-2 px, or the page cannot scroll that far); `#/compare`: compare mode,
  six small maps displayed, `#map-section` top at the viewport top;
  `#/read`: read mode, the one-page view with a section per node, at the
  page top.
- `page_height`: the document's `scrollHeight` at 744x1000 on `#/` (must
  be <= 4000). `min_tap_px` (informational): the smaller side of the
  smallest displayed control (`button`, `summary`, `[role=button]`, form
  fields, links that are not inline text) at 744, over the overview, a part
  card, tour and compare (target >= 32); a `NOTE:` names the smallest ones
  and the smallest focusable shapes of the drawings.
- `scroll_jumps`: at each viewport the test first plans every press from
  the model and the loaded page and prints the plan as a `NOTE:` (E =
  `expected`); then it performs them in order. The presses: every
  Emphasize button (each kind of `map.kinds`, then All); every map part; in
  each part's detail a box, a group title strip (when a node below the part
  has children) and every neighbour tag the model implies (one per
  neighbouring part and direction, for the edges with an end below the
  part; the part's map box is pressed again before each tag after the
  first); Close, then `#card-next` 9 times and `#card-prev` 9 times; on the
  largest part card with its top 300 px above the viewport (the head
  stuck) `#card-next`, `#card-prev` and `#card-close` (the part is opened
  again before each), and `#card-close` near the card's footer with every
  fold open; the map's Full size button (`#bar-map
  button.fullsize[aria-controls=map]`) twice; Enter on a focused map box,
  and Enter on a focused detail tag; "Follow one event", the "About this
  tour" summary (`#mode-note details > summary`, open and close), every
  pip (at the first step whose part has tags, also a box and a tag of the
  tour card's detail `#step-card #tour-detail svg.detail`), `#tour-prev`,
  `#tour-next`; when the step card has its own head: `#step-prev`,
  `#step-next`, both again with `#step-card`'s top 300 px above the
  viewport, and ArrowLeft on the focused `#tour-step-title` with that head
  stuck; the sequence view button, every sequence row, Enter on a focused
  row, the sequence chart's Full size button
  (`button.fullsize[aria-controls=seq]`) twice, the map view button; every
  map part clicked in Follow one event (each opens Explore the parts;
  "Follow one event" is pressed again before the next); "Compare kinds",
  "Explore the parts"; last `#help-toggle` and `#help-close`. A link to a
  node in a card's text and "Read as one page" are deep links: they are
  not pressed (a `NOTE:` names them).
  Every press is real: before it the test audits `[data-moves-page]` in the
  current state, checks the state the press needs (the card or step on the
  right part, the mode and view, the head stuck; a wrong state is a failed
  press), centres the control with an instant scroll of its own only if it
  is not wholly in view with its centre receiving a click, reads
  `scrollY`, then clicks with the mouse at a point of the control that
  `elementFromPoint` gives to it (or presses the key with the focus on it),
  waits 600 ms and two animation frames and reads `scrollY` again. A press
  that cannot be performed (not found, timeout, covered, no hit point,
  cannot take the focus, wrong state) is a failed press (F); there is no
  dispatched-event fallback. J counts the presses after which `scrollY`
  changed by more than 1 px: right after the press, or later (a deferred
  jump): when `scrollY` differs, just before the next press (before the
  test's own scroll), from the value read after the press, or changes while
  the next control is being prepared, or 1500 ms after the last press. N
  counts the presses performed. `moves_page_ok` = before every press, every
  `[data-moves-page]` element is one of `a.back-to-map`,
  `button.open-part`, `#mult figure`, an `a[href^="#/node/"]` inside
  `#part-card` or `#step-card`, or an `a[href^="#/"]` inside `#read-page`;
  every `a.back-to-map`, `button.open-part`, `#mult figure` and
  `a[href^="#/node/"]` in the cards carries it; and no pressed control
  carries it (these are the only controls that may move the page).
  `control_moved` (informational): presses after which the pressed
  control's own viewport position moved by more than 2 px while it is still
  displayed (the Full size buttons and map boxes pressed in Follow one
  event, whose mode note goes away, are expected movers). Pass iff J = 0,
  F = 0, N = E >= 40 and `moves_page_ok`.
- `console_errors`: console errors and warnings, page errors, and failed or
  HTTP >= 400 requests to the page's own origin, over the whole run.
- `elapsed` (informational): seconds per check group.

Exit 0 iff every check passes and no `PROBLEM:` line was printed: every
count complete (V = N, S = T, A = P0, O = Q, X = P, every tour and tour_card
count = T, M = 6 panels, R = T, captions K = K, nav = 9, stuck_view K = K,
C2 = C, D = 4), every bool `true`, both `mode=` values set, `default` and
`after_close` `overview`, `above_map=modes,chips` with the map_first
thresholds, M = 3 and F = 1, `hscroll=0`, `close_buttons=0`,
`page_height` <= 4000, J = 0 and F = 0 with N = E >= 40 at both viewports,
every smoke check `ok` with R = N, Q = 0 and C = 0. A check that finds
nothing to test fails. A full run takes about five to six minutes on
sdfiana025 (`elapsed` gives the seconds per group; `scroll_jumps` takes
about four of them).

`--only GROUP[,GROUP]` runs only the named check groups: `nodes`, `tour`,
`smoke`, `map_first`, `modes`, `map`, `detail`, `multiples`, `sequence`,
`emphasize`, `card`, `matrix`, `deeplinks`, `page_height`, `scroll_jumps`
(aliases: `full_maps` = `modes`, `after_close` = `card`, `close_buttons` =
`matrix`, `tour_card` = `tour`). It prints only those groups' lines, in the
same formats and order (the first line when `nodes` or `tour` runs, with
`-` for the one not run), then `console_errors=C` and `elapsed`; exit 0 iff
they pass and C = 0. `card` without `nodes` walks the nodes for the folds.

`--layout` loads the page at 744x1000 and 1440x900 and compares, on the
map, each top-level part's union box (viewBox units), the set of rendered
text strings and the number of visible elements; it prints
`layout_identical=<bool> parts=<n>`. Then, at widths 400, 744 and 1440,
it prints `width=<w> page_hscroll=<px>` (the page's horizontal overflow,
the maximum over the loaded page, a part opened, tour step 2, the sequence
view and compare), after the 744 line the informational
`inner_scroll=<section:px,...> min_text_px=<px>` (horizontal scroll inside
each section's containers; the smallest rendered SVG text in CSS px), then

```text
fullsize map=ok|fail sequence=ok|fail
theme dark=ok|fail light=ok|fail override=ok|fail
```

and finally `console_errors=C`. The `theme` line (T10) loads `#/` at
744x1000 four times: with `prefers-color-scheme: light`, with `dark`, with
`dark` and `data-theme="light"` set on the root element before the page
renders, and with `light` and `data-theme="dark"`. It reads the body's
background colour and the map's ink (the `color` of `#map svg.map`).
`light=ok` = a light ground (relative luminance >= 0.6), dark ink (<= 0.3),
contrast >= 4.5, no console error; `dark=ok` = a dark ground (<= 0.1), light
ink (>= 0.4), contrast >= 4.5, both colours different from the light page's,
no console error; `override=ok` = `data-theme="light"` under a dark system
gives exactly the light page's colours and `data-theme="dark"` under a
light system gives a dark palette by the same rule, with no console error. The `fullsize` check runs at 744x1000 for
the map's button (`#bar-map button.fullsize[aria-controls=map]`, in
explore) and the sequence chart's (`button.fullsize[aria-controls=seq]`,
in tour mode with the sequence view): there is one button with
`aria-pressed="false"` on load and its figure (`#map svg.map`,
`#seq svg.seq`) is fitted: no horizontal scroll in any scroll container
between the svg and `#map-section`, and the svg no wider than its sheet's
content box. Pressing the button sets `aria-pressed="true"`, makes the svg
exactly as wide (1 px) as its viewBox and makes the sheet scroll, while
the page itself does not scroll; pressing it again fits the figure again.
`--layout` fails if the layouts differ, any `page_hscroll` > 0, the map
sheet scrolls horizontally at 744 on load (a `PROBLEM:` line gives the
pixels), a `fullsize` or `theme` check fails, `html`, `body` or an element
around `#map-section` or `#matrix` sets `overflow-x: hidden` or `clip`,
C > 0, or any other `PROBLEM:` line is printed.

`--check-node` opens the node by deep link (`#/node/ID`) and by clicking
(its part's map box, then its box or group in the detail in the card), and
checks the panel title and that the rendered prose contains SUBSTRING; it
prints `check_node id=ID title_ok=<bool> prose_ok=<bool> in_detail=<bool>
console_errors=C`. `in_detail` = both times, the node is drawn as a
`g.box[data-node=ID]` or `g.dgroup[data-node=ID]` inside `#part-card
#detail-view svg.detail[data-detail=<its top-level part>]` (for a
top-level part: its card is open with its detail drawing). SUBSTRING is
matched against the rendered, visible text, so it must not contain markup
(backticks, `[[...]]`, link syntax).
`--check-edge ID` looks for the edge where the page draws it: an edge inside
one part as a `path.ln[data-edge-ids~=ID]` in that part's detail (in the
card); an edge between two parts with a lower-level end as the neighbour
tag (`g.stub[data-other][data-dir][data-edge-ids~=ID]`) in the detail of
each part whose end is a lower node; an edge between two top-level parts as
a map line or a matrix relation. It prints `check_edge id=ID drawn=<bool>
console_errors=C`. `--full` adds the full run to `--check-node`,
`--check-edge` or `--layout`. Each of these runs exits 1 when it prints a
`PROBLEM:` line. The test also works against the published
site (`--url https://carbonscott.github.io/lcls2/dev/design/`).

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
(`#map svg.map`) and the detail drawing of every top-level part with
children: in Explore mode (the default on `#/`; another mode is a
`PROBLEM:` and fails the run) it clicks the part's map box, which opens the
part in the card under the map, and measures
`#part-card #detail-view svg.detail[data-detail=<part>]`, all in SVG
viewBox units:

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

with V = 1 + P (P: top-level parts with children). Exit 0 iff the font is
Archivo, the page opens in Explore mode, V = 1 + P, every view has a box,
and X, Y, O, W, S and E are all 0 (K, J and Q are informational).
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
python docs/design/tools/plant_viewer_defects.py /tmp/viewer-copy KIND [KIND ...]
```

Plants known defects in a copy of `docs/design` (it refuses the viewer next
to the script), so that one can show that the browser test catches them.
Several kinds may be planted in one call. Most kinds append a small
self-contained script to `viewer.js` (or a rule to `viewer.css`) that acts
on the page's hooks once `body[data-ready]` is set, so they do not depend on
the viewer's internals; the others change one line of `viewer.js` (the
first anchor that occurs exactly once is used; some kinds have a CSS
fallback). Serve the copy and run `browser_test.py` against it; the full
run must exit nonzero.

The six kinds of the map-modes checks, each caught by one check:

- `map-below-fold`: the card (the overview on `#/`) is moved above the mode
  switch; `map_first` fails (`above_map` names `part-card`, and
  `map_bottom` > 1000 at 744x1000).
- `second-map`: a copy of `#map svg.map` is put right after the map once
  the page is ready; `full_maps=2`.
- `card-empty-on-close`: Close hides the card instead of showing the
  overview; `card ... after_close=FAIL:hidden`.
- `click-scrolls`: an Emphasize chip click scrolls the card into view with
  smooth scrolling; `scroll_jumps` J > 0 at both viewports (each chip is
  named).
- `matrix-close`: a Close button is added to the matrix card's head;
  `matrix ... close_buttons=1`.
- `broken-deeplink`: `#/compare` opens Explore (the hash is replaced before
  the viewer reads it); `deeplinks=3/4`.

Extra kinds, one more check each:

- `nav-order`: `#card-next` pressed on the overview skips the first part;
  `card ... nav` < 9.
- `head-not-sticky`: the card heads lose `position: sticky`; `card` and
  `matrix` `sticky_head=false`.
- `folds-open`: every fold of the card is opened when it appears;
  `card ... folded=false`.
- `matrix-hscroll`: the matrix table gets `min-width: 1100px`;
  `matrix hscroll` > 0.
- `moves-page-abuse`: `#card-next` carries `[data-moves-page]`;
  `scroll_jumps ... moves_page_ok=false` (a test that trusted the
  attribute would skip the arrow).
- `tour-card-stale`: the step text is not updated on Next;
  `tour_card text` < T (and `tour_steps` < T).

Kinds of the hardened checks, one per check (each must make it fail on a
copy of the current viewer):

- `unclickable-control`: a transparent overlay covers the second Emphasize
  button; `scroll_jumps ... failed=1` (no point of it receives a click).
- `deferred-scroll`: an Emphasize click scrolls the card into view 700 ms
  later; `scroll_jumps` J > 0, named as deferred jumps.
- `moves-page-late`: the sequence rows carry `[data-moves-page]` only while
  the tour shows the sequence chart; `scroll_jumps ... moves_page_ok=false`.
- `tour-detail-hidden`: `#tour-detail` is not displayed;
  `tour_card ... detail=0/T`.
- `overview-no-howto`: the overview loses the elements that show
  `map.sections.map`'s title and intro;
  `card default=FAIL:no-howto-title,no-howto-intro`.
- `stuck-blank`: a Close pressed while the card's top is above the viewport
  leaves a blank block at the top of the card body (what 8c02c6ec showed:
  filler under the stuck head); `card ... after_close=FAIL:stuck-...`.
- `stuck-turn-blank`: the same after `#card-next`/`#card-prev` (and
  `#step-next`/`#step-prev`); `card ... stuck_view` < K.
- `caption-above-map`: `#kind-caption` is moved above the map;
  `emphasize captions=0/K`.
- `divider-missing`: `.ref-divider` is not displayed;
  `matrix ... divider=false`.
- `compare-tap-broken`: a tap on a small map does nothing;
  `smoke ... compare_tap=fail`.
- `seq-status-stale`: `#seq-status` keeps its first text;
  `sequence rows` < T.
- `fullsize-keys-move`: Left and Right move the tour even with the focus in
  a frame that scrolls sideways; `smoke ... fullsize_keys=fail`.
- `dark-ignored`: the page forces the light palette under a dark system
  setting; `--layout`: `theme dark=fail`.
- `override-ignored`: `data-theme` is removed from the root element;
  `--layout`: `theme ... override=fail`.
- `close-invisible`: `#card-close` is transparent but still works: only
  `PROBLEM:` lines (`#card-close is not displayed on the card of X`), every
  printed value passes, and the run exits 1 (every `PROBLEM:` line fails a
  run).

Kinds kept from the earlier checks:

- `page-error`: `plantedUndefinedFunction();` at the top of `viewer.js`;
  the page never becomes ready, every count is 0 and the page error is
  counted (`console_errors` >= 1).
- `hide-prose`: the node panel shows no prose; `nodes_visited` < N.
- `no-multiples`: the small maps of Compare kinds are not drawn (or not
  displayed); `multiples panels=0/6` or `mode=FAIL:...`.
- `shift-map-box`: a CSS rule shifts the TEB's map box 30 px to the right
  (a CSS transform, no transform attribute); `map ... boxes=16/17`, naming
  the box.
- `sequence-reversed`: the sequence chart draws each arrow between two
  lifelines backwards; `sequence rows` < T, naming each row's drawn and
  expected lifelines.
- `arrow-global`: a keydown listener on the whole document moves the tour
  with Left and Right in tour mode wherever the focus is and calls
  preventDefault; `smoke ... arrow_scope=fail`.
- `callout-tag-fixed`: the callout tag goes back to one fixed place (under
  the dashed outline at its left); `tour ... tag_clear` < T.

Exit 0 if every defect was planted, 1 if the code to change was not found
exactly once for a kind or on a usage error.

## Viewer test hooks

Stable attributes for tests (the UI works the same for people):

| Hook | Meaning |
|---|---|
| `body[data-ready="true"]` | set after the first render (fonts ready, map drawn) |
| `body[data-mode]` | `explore`, `tour`, `compare` or `read` |
| `h1#model-title` | page title (the model's `title`) |
| `#map-section` (`tabindex=-1`) | the map section: modes, chips, stage, tour bar, cards |
| `#modes button.mode[data-mode=explore\|tour\|compare][aria-pressed]` | the mode switch: exactly 3 buttons, one pressed; `#modes` and `#chips` are direct children of `#map-section` |
| `#mode-note` | the tour or compare intro (hidden in explore) |
| `#chips button.chip[data-kind][aria-pressed]` | Emphasize: `all` and the 5 kinds; displayed in explore only |
| `#kind-caption[data-kind]` | the caption of the emphasized kind (its `map.multiples` caption); displayed in explore when a kind other than `all` is emphasized |
| `#tour-controls button.view[data-view=map\|seq][aria-pressed]` | tour only: show the steps on the map or on the sequence chart |
| `#stage` | the figure frame the modes swap |
| `#map svg.map` | THE map (the only full-size map drawing in the document, in any mode); viewBox = `map.viewbox`; hidden only in compare mode and in the tour's sequence view |
| `g.box[data-part][data-node][data-box]` (+ `[data-lane]`) with `rect.b` | a map box: its top-level part, the node it stands for, its box id (and lane) |
| `g.column-label[data-column]`, `g.band-label[data-band]` | column headers; one group per band |
| `path.ln[data-line][data-kind][data-edge-ids][data-through][data-ends]` (+ `[data-lane]`) | a map line; through/ends list box keys `<box id>` or `<box id>@<lane>` |
| `circle.port[data-line]`, `text.lab[data-line]` | ports and labels of a line |
| `g.callout[data-part]` with `rect.cbox` and `rect.ctag`; `g.tok[data-t][data-target]` | in `#map svg.map`: the tour step's callout (dashed outline and tag; Explore's selection outline uses `g.callout` too) and the event tokens (visible ones have opacity 1) |
| `#bar-map button.fullsize[aria-controls=map][aria-pressed]` | "Full size" for the map, below the map frame (with its scroll hint); not between the h1 and the map |
| `button.fullsize[aria-controls=seq][aria-pressed]` | "Full size" for the sequence chart (`#bar-seq`, or `#tour-controls`) |
| `#seq svg.seq .row[data-step-index]` (+ `g.hdr[data-lifeline]` with `rect`, `path.ln`, `text.lab`) | the sequence chart (tour mode, sequence view): one row per step (its arrow and label); a click shows that step; a lifeline header's centre is the lifeline's x |
| `#seq-status` | the status line under the sequence chart: "Step k of T: <step title>" after a row is clicked (in view) |
| `#mode-note details > summary` | "About this tour" in the tour's mode note (a closed `<details>` with `map.sections.tour.intro` and `tour.intro`) |
| `#mult figure[data-kind]` with `svg.map.mini[data-kind]` and `figcaption` | the six small maps (compare mode only); a tap or Enter goes to Explore with that kind emphasized and, when `#map-section`'s top is above the window, brings it to the window's top (carries `data-moves-page`) |
| `#tourbar`: `#tour-prev`, `#tour-next`, `#pips button.pip[aria-current]` | tour controls (tour mode) |
| `#part-card[data-card]` | the card (explore); `data-card` = `overview` or the open part's id |
| `#card-head` (`position: sticky`) with `.eyebrow`, `#card-title[data-card]`, `#card-prev`, `#card-next`, `#card-close` | the card head; `#card-close` absent on the overview; prev/next cycle through the overview and the 8 top-level parts |
| `#overview` | the overview inside the card: the model question, the summary, how to read the map |
| `#detail-view svg.detail[data-detail]` | the part's detail drawing in the card: `g.box[data-node]` (`.hot` when highlighted), `g.dgroup[data-node]` with `rect.gtitle`, `g.stub[data-other][data-dir][data-edge-ids]` (neighbour tag, with `rect` and a connector `path.ln`), `path.ln[data-edge-ids][data-from-box][data-to-box]` |
| `#detail-title[data-node-id]`, `#detail-prose` | the node panel in the card; for a top-level part `#detail-title` may be visually hidden (class `vh`) because `#card-title` shows the same title |
| `details.fold[data-fold=decisions\|code\|sources\|flows\|dev]` | the folded sections of the node panel; closed when a node opens |
| `#card-foot` | the card's footer: "End of the overview." or "End of <part title>." plus `a.back-to-map[data-moves-page]` |
| `#step-card` | the tour card (tour mode): `#tour-step-title[data-step-index]` (k is 1-based), `#tour-step-prose`, the step node's title and summary with `button.open-part[data-moves-page]`, `#tour-detail svg.detail[data-detail]` (step node `.hot`), `#step-foot` ("End of step k of T.") |
| `#step-card > .card-head` (`#step-head`, sticky) with `#step-prev`, `#step-next` | the step card's own head (when the viewer has it): Back and Next change the step in place; the test presses them, also with the head stuck |
| `.card-body > .card-spacer[aria-hidden=true]` | the blank (with a short note) that a card leaves above its new content when it changes while its top is above the window, so that the page does not move; the stuck checks treat it as filler, never as content |
| `.ref-divider` | the "Reference" divider (displayed between `#part-card` and `#matrix`, reads "Reference") |
| `#matrix.ref-card` with `.card-head` (sticky), `table.nsq td[data-from][data-to]`, `.ni[data-edge-ids]`, `#nsq-key`, `#matrix-foot` | the matrix reference card; no buttons in it; footer "End of the <eyebrow>." plus `a.back-to-map` |
| `#read-page section[data-node-id]` | one section per node in the one-page view (read mode replaces `#studies`) |
| `#help-toggle`, `#help`, `#help-close` | "How to read this page": the button, the panel (hidden until opened) and its close button |
| `[data-moves-page]` | marks the only controls allowed to scroll the page: `a.back-to-map`, `button.open-part`, `#mult figure`, links to `#/node/...` in the cards (all of these must carry it), links in the one-page view (may) |

URL routes: `#/` (explore, the overview card), `#/node/<id>` (explore, the
card on the node's top-level part, the node `.hot` in its detail, the panel
on the node), `#/tour/<k>` (tour mode, map view, step k), `#/compare`
(compare mode), `#/read` (the whole model as one page) and `#/read/<id>`
(the one-page view, scrolled to a node). In-page clicks update the address
with `history.replaceState`, so they add no history entries.

Links in the page header (`../`, `editing-guide/`) and `site-page` sources
(`../features/...`) work only on the built site (`mkdocs serve` or
`mkdocs build`), not when `docs/design` is served on its own with
`python -m http.server`. The browser test does not follow them.
