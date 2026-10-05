# Editing the design model

The design document
[How the LCLS-II DAQ works, from detector to disk](index.html) is generated
from one file (the viewer's header links here as "Edit this model"):
`docs/design/daq-model.json` (the *model*). The
viewer (`index.html`, `viewer.js`, `viewer.css`) only draws the model; it
contains no text about the DAQ. **To change what the document says, edit
only `daq-model.json`.** Never edit the viewer files to change content.

This guide is for people and for AI agents. With it and a checkout you can
add a node with a code reference, give it its place in the layout, add an
edge, rewrite a node's prose, check your change and preview it.

The page is laid out by hand, not by an algorithm. It has one fixed map of
the whole DAQ (the top-level parts), and the map has three modes:
"Explore the parts" (the page opens in it), "Follow one event" (the tour,
drawn on the same map; a sequence chart is a second view of the tour) and
"Compare kinds" (small copies of the map, one with one kind of relation each
and one with all of them). Under the map sits one card. With no part open it
is the overview of the whole system; when you open a part it shows that
part's *detail* (a drawing of everything inside the part) and the panel that
describes the selected node. After a "Reference" divider comes the N²
matrix of every relation between two parts. Where everything sits is
stored in the model too (see [Layout](#layout-the-map-places-and-detail-grids)).
The words that name the modes, buttons and cards ("Explore the parts",
"Overview", "Selected part", "Back to the map") are the viewer's: they say
how to use the page. Every sentence about the DAQ comes from the model.

## Before you start

Run every command in this guide from the repository root (the directory
that contains `docs/`); the paths assume it.

You need a **full clone** of the repository (not `git clone --depth ...`).
Every code reference is checked against one pinned commit
(`code_base.commit` in the model); a shallow clone does not have that
commit's files and the validator then fails with
`commit "..." does not exist ... (is this a shallow clone?)`. To fix a
shallow clone, run `git fetch --unshallow`.

Check that the pinned commit is present:

```bash
COMMIT=$(python -c "import json; print(json.load(open('docs/design/daq-model.json'))['code_base']['commit'])")
git cat-file -e "$COMMIT^{commit}" && echo "pinned commit present"
```

The tools need Python 3 with `jsonschema` (for the validator) and, for the
geometry check and the browser test, `playwright` with its Chromium browser; the site build
uses Python 3.12. If you already have an environment with these (for example
a conda environment), use it and skip the installs. Otherwise:

```bash
pip install -r docs/requirements.txt        # includes jsonschema, used by the validator
pip install playwright                      # for the geometry check and the browser test
python -m playwright install chromium       # for the geometry check and the browser test
```

## The files

| File | What it is | Edit it? |
|---|---|---|
| `docs/design/daq-model.json` | The model: all content and the layout. | Yes, this is the only file you edit. |
| [`daq-model.schema.json`](daq-model.schema.json) | JSON Schema of the model: every field, its type and limits. | No (changes need agreement). |
| `index.html`, `viewer.js`, `viewer.css` | The viewer. No content. | No, not for content. |
| `docs/design/tools/` | Validator and test scripts (see `docs/design/tools/README.md`). | No. |

Keep the model's formatting, so that a diff shows only your change: JSON
with an indent of 2 spaces, non-ASCII characters written as they are (not as
`\u` escapes) and one newline at the end of the file. A script that rewrites
the file should write `json.dumps(model, indent=2, ensure_ascii=False) + "\n"`.
This one-line check prints `canonical` when the file is in that form:

```bash
python -c "import json; s = open('docs/design/daq-model.json', encoding='utf-8').read(); print('canonical' if s == json.dumps(json.loads(s), indent=2, ensure_ascii=False) + '\n' else 'NOT canonical')"
```

## What is in the model

The schema describes every field; this is the overview. Fields whose schema
description starts with "PROSE" are text for readers and may use the prose
markup below.

- `title`, `question`, `summary`: `title` is the page's main heading (and
  the browser tab's title); `question` and `summary` fill the overview, the
  card under the map when no part is open: `question` is its first line and
  `summary` follows it. The one-page view ("Read as one page") starts with
  the `question` and the `summary` instead.
- `code_base`: `repo_url` and the full 40-character `commit` that every code
  reference points into. Code links are built as
  `<repo_url>/blob/<commit>/<path>#L<start>-L<end>`.
- `sources`: every document the model cites, each with an `id`, `title`,
  `url`, `kind` and an optional `note`. Nodes, decisions, edges and tour
  steps refer to sources by id.
- `nodes`: the components, as a flat list. Each node has:
    - `id`, `parent` (the parent's id, or `null` for a top-level node),
      `title` (at most 40 characters, shown on the node's box in its part's
      detail and in the panel), `summary` (one sentence, at most 160
      characters, shown in bold at the top of the node's panel and of its
      section in the one-page view, and with the title in the tour card,
      under the step's text), `prose` (the concept, shown under the
      summary);
    - optional `dev_notes` (shown in a folded section "For developers"),
      `outside_repo`, `decisions`, `code_refs`, `sources` (each of the three
      lists is shown in a folded section of the panel).
- `edges`: flows between nodes: `id`, `from`, `to`, `label` (at most 30
  characters, drawn on the arrow), `kind` (one of `data`, `trigger`,
  `timing`, `control`, `monitoring`), optional `prose`, `code_refs`,
  `sources`.
- `tour`: `title`, `intro` and `steps` that follow one event. Each step has
  an `id`, a `title`, the `node` it is about, `prose`, and optional `edges`
  (edge ids to highlight), `code_refs` and `sources`.
- Layout (see [Layout](#layout-the-map-places-and-detail-grids)): the
  top-level `map` block, a `place` on every top-level node and a `detail`
  grid on every top-level node that has children.

### Where each text shows on the page

| Model field | Where the page shows it |
|---|---|
| `title` | The page's heading. |
| `question` | The first line of the overview (the card under the map when no part is open). |
| `summary` | The overview, after the question. |
| `map.sections.map`: `eyebrow`, `title`, `intro` | The overview, after the summary, as "how to read the map": the eyebrow and title as a sub-heading, then the intro. |
| `map.sections.map.caption`, `map.omitted` | Under the map in "Explore the parts": the caption, then the list "Not drawn on the map". |
| `tour.title` | The second line of the "Follow one event" button, with the number of steps. |
| `map.sections.tour`: `eyebrow`, `title`, `intro` | Above the map in "Follow one event": the eyebrow and title as one heading line. The `intro`, together with `tour.intro`, is in a folded section next to it. `tour.intro` also starts the tour in the one-page view. |
| `map.sections.multiples`: `eyebrow`, `title`, `intro` | Above the small maps in "Compare kinds". |
| `map.multiples[i].caption` | Under its small map in "Compare kinds". For a kind, also under the map in "Explore the parts" while that kind's Emphasize button is pressed. |
| `map.sections.sequence` | Around the sequence chart (in "Follow one event", with the steps shown on the sequence chart): eyebrow, title, intro and caption. |
| `map.sections.matrix`: `eyebrow`, `title`, `intro` | The matrix card (under the "Reference" divider): the eyebrow and title in its head, the intro in its body. |
| A top-level node | The card when you open the part: the part's detail drawing, then its panel. |
| A node below the top level | The panel below the drawing, when you select the node in the drawing. |
| A tour step | The tour card: the step's title and `prose`, then the title and `summary` of the step's `node`, then the step's detail drawing ("Where this step happens"). |

"Overview", "Selected part", "Reference", "Where this step happens" and the
footers ("End of ...", "Back to the map") are the viewer's words around
these texts, not model fields.

### Ids

Ids are lowercase words joined by hyphens (`drp-file-writer`), at most 60
characters. Nodes, edges, tour steps, sources and decisions (decisions may
have an id) share **one** namespace: an id must be unique in the whole file.
Ids appear in links (`#/node/<id>`), so do not rename an existing id.

### Parents and levels

A node with `"parent": null` is at level 1: a *part*, drawn on the fixed
map at the place its `place` names. Its children are level 2, their
children level 3, and so on. The descendants of a part are drawn in the
part's detail (the card under the map shows it when the part is open), at
the cells its `detail` grid names; a level-2 node with children is drawn
there as a group (a frame around its children). The model must reach level 3
somewhere. Parents must exist and must not form a cycle.

A parent may have a single child: the validator has no rule on the number
of children. A leaf that gets its first child becomes a parent, and its
part's detail grid must change with it: a level-2 node turns from a node
item into a group whose kids are its children (see "Detail grids" below).
Groups do not nest, so a level-3 node cannot get children without a change
to the layout schema. The new parent's panel still shows its own prose,
code references and sources. Like every node below the top level it still
needs a code reference of its own (or `outside_repo` with an external
source).

An edge may connect any two nodes, at any levels, except a node and its own
ancestor or descendant. Where the page draws an edge depends on its ends:

- Both ends below the same part: an arrow in that part's detail,
  between the two boxes (or a group's frame). Edges of one kind from the
  same box to the same box are merged into one arrow that carries their
  labels (each different label once); edges of another kind, or in the
  other direction, get an arrow of their own.
- One end below a part and the other end in another part: a tag on the side
  of the part's detail that the grid's `sides` names for the other part
  (click the tag to open that part in the card). A detail has one tag per
  neighbouring part and direction ("from DRP ›", "to Files ›") that lists
  the labels of all such edges, with one connector to each box (and kind)
  they reach. If an end is a top-level part itself, not a node below it,
  that part's own detail shows no tag for the edge.
- Ends in two different parts: on the map, only a map line that lists the
  edge in its `edges` draws it, and every pair of parts that an edge connects
  needs such a line or an entry in `map.omitted` with a reason (see "Map
  lines" below); the N² matrix lists every edge between two parts by its
  label.

The node's panel (it follows the detail drawing in the card) lists the
node's flows in the section "Flows", which is folded until the reader opens
it. The section is there when the node has an edge into or out of it.
"Comes from" and "Goes to" list the edges that cross the boundary of the
node and its descendants, each with its kind, the node at the other end, the
label, the edge's `prose` and its references. The one-page view lists each
node's outgoing edges under "Flows out of this part". Give an edge `prose`
(one or two sentences, with a code reference or source): it is what a reader
sees for the flow in both places.

The order of nodes in the file sets:

- the order of the parts in "Read as one page" (`#/read`): its contents list
  shows the top-level nodes in file order, and each part is followed by its
  children in file order (depth first);
- the order of the card's previous and next arrows: the overview, then the
  top-level nodes in file order, and back to the overview;
- the order of the `top:` lines that `validate.py --outline` prints.

The order of nodes does not move anything on the map or in a detail:
positions come only from `place` and `detail`.

Lists of flows ("Comes from", "Goes to" and the one-page view's "Flows out
of this part") follow the order of the edges in the file.

### Edge kinds

An edge's `kind` says what flows. The model's existing edges use the five
kinds like this:

| kind | What the model's edges of this kind carry | Examples |
|---|---|---|
| `data` | Event data on its way to disk and to psana: readouts from the detector into DMA buffers, events through the DRP's threads, datagrams into the files, files to storage, and psana reading and joining the streams. | `e-electronics-to-dma`, `e-drp-to-files`, `e-reading-to-joining` |
| `trigger` | The trigger decision: the DRPs' trigger inputs to the TEB, the TEB's event building and plugin, and the result back to each DRP. | `e-drp-to-teb`, `e-teb-to-drp`, `e-result-to-receiver` |
| `timing` | The timing stream and its triggers, from the accelerator through the XPM to the detectors. | `e-accelerator-to-xpm`, `e-xpm-to-electronics` |
| `control` | Run control and setup: transitions from the control process to the processes and the XPM, their answers and reports back, configuration reads, process launching, chunk requests, and what a process sets up at start or at a transition (the detector class, its threads, the next chunk file). | `e-control-to-drp`, `e-configdb-to-control-process`, `e-launching-to-drp-process` |
| `monitoring` | Live monitoring: monitored events from the DRPs to the MEBs, shared memory and AMI, and the MEBs' free-buffer offers to the TEBs. | `e-drp-to-monitoring`, `e-meb-to-teb-process`, `e-shmem-to-ami` |

A flow that fits none of the five kinds well (run-time metrics or other
telemetry, for example) still takes one of them: the schema allows only
these five, and the viewer has a color, a line pattern and an emphasize
button for each. Pick the kind whose row above is closest to what the flow
does, and say in the edge's `prose` what it carries and where it goes, so
that nobody reads the kind as more than it is.

In the viewer each kind has its own color and line pattern, and its name
(from `map.kinds`) on the Emphasize buttons (they dim the other kinds on the
map) and on the small maps of "Compare kinds". No edge moves a box: the map
and the details are laid out by hand (see
[Layout](#layout-the-map-places-and-detail-grids)).

### Prose markup

- A blank line (`\n\n` in the JSON string) starts a new paragraph.
- `` `code` `` is inline code.
- `[text](https://example.org/page)` is a link (http, https or a relative URL).
- `[[node-id]]` links to another node (the link text is the node's title);
  `[[node-id|some text]]` uses your text. The id must exist. In the card, the
  link opens the card on that node's part with the node selected; it can
  scroll the page so that the card's head is in view.
- Nothing else is markup: `**bold**`, lists and HTML are shown as typed.

### Code references

A code reference is
`{"path": ..., "start": ..., "end": ..., "symbol": ..., "note": ...}`:

- `path`: a file path relative to the repository root, at the pinned commit
  (not under `docs/`).
- `start`, `end`: line numbers, inclusive, at the pinned commit (not in your
  working tree, which may differ). `end - start` must be at most 80; keep the
  range to the function or block that shows the claim. A single line
  (`start` equal to `end`) is allowed: the validator checks that
  1 <= `start` <= `end` <= the number of lines in the file.
- `symbol`: a name (function, class, variable or key, at least 4
  characters) that appears **verbatim** inside lines `start` to `end`. It
  proves that the range points at the right code. The validator only checks
  that the text is a substring of those lines, so it also passes when the
  text appears only in a comment or a string; check yourself that it names
  code.
- `note`: optional, what to look for there.

Comments are not proof. Choose a range whose executable code shows the
claim, not one where only a comment states it, and choose as `symbol` an
identifier used in that code, not a word from a comment.

Find the line numbers at the pinned commit, never in your working tree:

```bash
git show "$COMMIT:psdaq/drp/FileWriter.cc" | grep -n "writeEvent"
git show "$COMMIT:psdaq/drp/FileWriter.cc" | sed -n '108,160p'
```

### Sources and their kinds

| kind | url | notes |
|---|---|---|
| `site-page` | `../<path>/`, optionally `#anchor`, relative to the viewer, for a page `docs/<path>.md` or `docs/<path>/index.md` of this site | e.g. `../features/xtc2/` |
| `confluence-public` | `https://confluence.slac.stanford.edu/pages/viewpage.action?pageId=<digits>` | public SLAC Confluence page |
| `confluence-internal` | same form | a page in one of SLAC's internal Confluence spaces; the viewer marks it "Confluence, internal space" |
| `web` | any `https://` URL | |

Rules for sources:

- Confluence pages, internal and public: **summarize in your own words and
  link; never copy their sentences.**
- Never put credentials, hostnames, IP addresses, people's names or other
  personal data in the model (the site is public).
- Everything except `site-page` counts as an *external* source.
- To check that a `site-page` source supports a sentence, read the page it
  names: `../<path>/` is the file `docs/<path>.md` (or
  `docs/<path>/index.md`) in your checkout. For example
  `../features/daq-control/` is `docs/features/daq-control.md`, which you
  can search with `grep -n -i "beginstep" docs/features/daq-control.md`.
  The validator only checks that the page exists in your working tree (not
  at the pinned commit); it does not check what the page says or the
  `#anchor`.

### Outside the repository

Set `"outside_repo": true` on a node whose mechanism is not implemented in
this repository (firmware, other repositories, facility services). Such a
node needs at least one external source of its own (not a `site-page`). A
missing `outside_repo` means `false`. A node may be `outside_repo` and still
have code references, for example to host software in this repository that
talks to the firmware; its prose then says which pieces are in this
repository. Wherever prose (in any node) describes such a mechanism, say in
the same sentence that it is outside this repository and cite the source.

### Decisions

A design decision (`title`, `decision`, `rationale`, optional `id`) needs at
least one source or code reference of its own: the basis for the
rationale. If neither the code nor the sources show why, the rationale says
so as a statement about the DAQ, never as a statement about the sources
("This repository does not show why ...; the code does X.").

### What every node needs

- Every node has non-empty `prose`.
- Every node below the top level has at least one code reference of its own,
  or is `outside_repo` with at least one external source of its own.

### The accuracy rule

Describe what the cited code and sources show. Every factual sentence must
be supported by a code reference or source attached to the same node (or the
same decision, edge or tour step). Never guess intent; when you are not sure,
say so in the prose. Give numbers (rates, sizes, counts) only when the code
or a source states them, with the right unit (1024³ bytes is a GiB). Expand
acronyms and explain terms of art (field names such as `env`, code names such
as "pebble") the first time each node, decision, edge or tour step uses
them: a reader may open any node first.

A universal ("every metric carries ...", "all DRPs ...", "never") needs
every case checked in the code: cite the one place that every case goes
through, or check each case, or narrow the sentence to the cases you
checked ("the metrics in `<file>` carry ...").

The rule covers the text fields: a node's `prose` and `dev_notes` (counted
together, `prose` first), a decision's `decision` and `rationale`, an
edge's `prose`, a tour step's `prose`, the top-level `summary` and the
tour's `intro`. The short fields shown on boxes, arrows and in lists
(`title`, the top-level `question`, a node's `summary`, an edge's `label`
and the `note` of a code reference or source) may use an acronym without
expanding it, as the existing model does: the node `drp` has the title "DRP:
readout and reduction" and a summary that uses DRP and TEB, and its `prose`
expands both ("A DRP (data reduction pipeline) ...").

### Tour steps

Tour steps follow one event in order, and each step's prose says what
happens to *that* event at the step (a scene-setting first step is fine if
its title says so). In "Follow one event" the tour is drawn on the fixed
map itself (there is no second map): for each step, `map.tour` (one entry
per step, in the same order, naming the step's `id`) gives the tokens that
show where the event's parts are and the map lines and boxes to highlight,
and `map.sequence.rows` has the step's row of the sequence chart, the
tour's second view ("Show the steps on: Sequence chart"). The part that
contains a step's `node` is outlined on the map ("THIS STEP"), and the
step's card under the map shows the step's text and that part's detail with
the `node` highlighted ("Where this step happens"). The lines and boxes
highlighted on the map come only from the `highlight` list of the step's
`map.tour` entry: the viewer does not draw a step's `edges` (the validator
only checks that those edge ids exist), so when you change a step's `edges`,
list the map lines that draw them in its `highlight` as well.
Step links are `#/tour/<k>` with k counted from 1, so inserting a step
changes the numbers of the steps after it, and a new step needs its
`map.tour` entry and sequence row at the same position (the validator
reports `E-TOUR-MAP` and `E-SEQUENCE` otherwise). The browser test checks
that the first 30 characters of each step's prose (as plain text) are
visible in the step card.

## Layout: the map, places and detail grids

Nothing on the page is placed by an algorithm. Three kinds of fields hold
the layout; the schema (`daq-model.schema.json`) describes every field of
them, and the validator checks them (see "What the validator checks"
below). Numbers are SVG user units in the map's `viewbox` (1200 by 690):
x grows to the right, y grows down.

### The map block (`map`, at the top level)

- `columns`: the stages of the event's trip, left to right, each with a
  number `n`, a `name`, an `x` and a width `w`.
- `bands`: horizontal bands that hold kinds of path (`live` at the top,
  `lanes` in the middle, `control` at the bottom), each with `y`, height `h`
  and its `labels`.
- `lanes`: the example readout lanes (`count` and the centre `y` of each).
  A box or line that is `per_lane` is drawn once per lane. Lanes stay
  generic ("readout 1", "readout 2", "readout N"); the model names no
  detector.
- `lines`: the map's lines. Each has an `id`, a `kind`, the model `edges` it
  draws, an SVG path `d` (absolute `M`, `L`, `H`, `V`, `C` commands only),
  an `arrow`, `per_lane`, and the boxes it touches: `ends` (the boxes whose
  borders its end points lie on) and `through` (the boxes it crosses from
  border to border; the viewer draws a port where a shared line crosses a
  box border). A `d` may hold several subpaths, one `M` each: the viewer
  draws each subpath with its own arrowhead. A shared line that enters each
  lane's box uses one subpath per lane, for example the timing line
  `tim-rail`, `M215,166 H335 V247 M335,303 V327 M335,383 V407`: each
  subpath starts and ends on the border of an `ends` or `through` box, and
  the gap between one subpath and the next runs across exactly one `through`
  box, from the border where the first subpath ends to the border where the
  next one starts. In a
  per-lane line, `d` writes the lane's y as `{y}` (`{y-28}`, `{y+28}` for
  offsets) and a per-lane box is named by its id alone. In a shared line, a
  per-lane box is named with its lane, `<box id>@<lane>`, lanes counted
  from 0 (for example `drp@2` is the DRP box of the third lane).
- `labels`: the text on a line, with the `line` it names; `notes`: free
  text on the map.
- `omitted`: edges between two parts that no line draws, each with a
  `reason` (see "Map lines" below).
- `ladder`: the states of the control process drawn as stations on one
  line, with the transitions between them (names as in `control.py`); a
  tour step highlights the segment of transition k as `lad-<k>`. The
  top-level part that holds the ladder's `node` also gets the shaded row and
  column of the N² matrix, and the line under the matrix names it by its
  `place.short`.
- `tour`: one entry per tour step, in order: the step's `id`, the `tokens`
  (dots that show where the event's parts are, each with a type `t`, a
  `lane` or null, and an absolute `x`, `y`) and the `highlight` list (line
  ids, `box:<box id>`, `lad-<k>`).
- `multiples`: the caption of each small copy of the map (one per kind of
  edge, and one with all of them). The page shows a caption under its small
  map in "Compare kinds", and under the map in "Explore the parts" while the
  Emphasize button of its kind is pressed.
- `sequence`: the sequence chart, the tour's second view: `lifelines` (each
  standing for a part) and one row per tour step, in order.
- `sections`: the eyebrow, title, introduction and (for the map and the
  sequence chart) caption of the map, the tour, the small maps, the sequence
  chart and the matrix; "Where each text shows on the page" above says where
  each one appears. `kinds`: the names of the edge kinds. `default_detail`:
  kept for compatibility; the page does not use it any more (it opens on the
  overview, not on a part). Leave it as it is: the validator still requires
  it to name a top-level part that has children.

### Places (`place`, on every top-level node)

`place.short` is the part's short name (on tags, in the matrix and the
sequence chart). `place.boxes` lists the part's boxes on the map: usually
one, but a part may be drawn as several boxes, each standing for the part or
one of its descendants (`node`); the timing part, for example, is drawn as
an Accelerator box and an XPM box. A box has a map-wide unique `id`, its
cell (`column`, `span`, `band`, `slot`), `per_lane`, its rectangle (`x`,
`y`, `w`, `h`; no `y` when `per_lane`, which centres each copy on its lane),
a `title`, `sub` lines (for a per-lane box one line per lane, or one line
for all lanes), `out` (the outside-this-repository tag), and optional
`title_x` (to keep the text clear of lines that cross the box) and `mini`
(a shorter title for the small maps of "Compare kinds").

**The cell rule.** A box's cell is its columns `column` to
`column + span - 1`, its `band` and its `slot` (0, 1, ... for several boxes
in one column and band; for a per-lane box, one cell per lane). The box's
rectangle must lie inside its columns' x range and its band's y range, no
two boxes may share a cell, and no two box rectangles may overlap.

### Detail grids (`detail`, on every top-level node with children)

The detail of a part is a grid with `columns` columns and a list of
`rows`. Each row lists items:

- a node item `{"node": <id>, "col": <c>}` for a descendant without
  children;
- a group `{"group": <id>, "col": <c>, "span": <s>, "kids": [...]}` for a
  descendant with children: its `kids` are exactly its children, each
  `{"node": <id>, "col": <c>}` with a column inside the group's columns.
  Groups do not nest.

Every descendant of the part appears exactly once (as a node item, a group
or a kid), and no two items share a row and column. `sides` names, for each
neighbouring part, the side of the detail (`left`, `right`, `top`,
`bottom`) where the tags for its edges sit. The side must agree with the
map, because the page tells the reader that a tag sits on the side where
that neighbour is on the map: `left` when the centres of all the
neighbour's boxes lie left of this part's leftmost box edge, `right`, `top`
(above) and `bottom` (below) likewise. For a neighbour that lies
diagonally, either side that agrees will do. Every neighbour that gets a
tag in the detail needs an entry. The validator reports `E-SIDES`
otherwise.

**Give a new node a cell.** Find the top-level part that contains the new
node (follow `parent` up to the node with `"parent": null`) and edit that
part's `detail`:

- a child of the part itself: add a node item to a row, in a column that is
  free in that row (or add a new row);
- a child of a group (a level-2 node that already has children): add a kid
  to the group, in a free column inside the group's `col` to
  `col + span - 1` (widen the group with `span`, and the grid with
  `columns`, if there is none);
- a first child of a level-2 node item: turn the item into a group whose
  kids are its children, for example
  `{"node": "x", "col": 1}` becomes
  `{"group": "x", "col": 1, "span": 1, "kids": [{"node": "new-child", "col": 1}]}`.

**Pick a cell for a new top-level part.** A new part needs a `place` (and,
if it has children, a `detail`), and nothing moves out of its way:

1. Choose the column by the stage of the event's trip where the part acts,
   and the band by the kind of path it is on (the live path and event
   builders on top, the recorded lanes in the middle, run control at the
   bottom). Use `per_lane` only for a part that exists once per readout.
2. Find a free `slot` in that column and band, and a rectangle inside the
   cell that overlaps no box, no line and no label. If there is no room,
   move boxes in the same edit, and then move the ends of the lines that
   touch them (their `d`, `ends` and `through`), their labels and the tour
   tokens near them.
3. Add a line for each pair of parts the new part has edges with (or list
   the edges in `map.omitted` with a reason), give the part a `short` name,
   and add its tags' sides to the `detail` of each neighbouring part.
4. Run the validator, then the geometry check in the browser (see
   "Geometry check" under "Check your change"), which finds lines that
   cross boxes they do not name, text that does not fit, and texts that lie
   on top of each other.

### Map lines and `map.omitted`

Every pair of parts with an edge between them must be drawn: at least one
of the pair's edges is listed in the `edges` of a map line, or in
`map.omitted` with a `reason` that says why the map leaves it out and where
the reader finds it instead (the matrix always lists it, and the detail of
each part whose end is a node below the part shows it as a tag). The model
omits one edge this way: the chunk request from the files part to the
control process, which the map leaves out to keep the lanes and the state
ladder clear. A line's `edges` must have the line's `kind`, and both
ends of each edge must lie in parts that the line touches (`ends` or `through`). An edge between
two nodes of one part may also be drawn by a line between that part's
boxes (for example `meb-shm` inside the monitoring part). In
"Explore the parts" the page lists every `map.omitted` entry under the map's
caption ("Not drawn on the map") as the two parts, the edge's label and the
`reason`.

**After adding an edge**, decide what the map needs:

1. Both ends in one part: the map needs nothing; the part's detail
   draws the arrow.
2. Ends in two parts that a map line already connects with an edge of the
   same kind (both parts among the line's `ends` or `through`): the pair is
   already drawn. Add the new edge's id to that line's `edges` so that the
   line names every edge it stands for.
3. Ends in two parts with no such line: add a line (its `d`, `kind`,
   `ends`, `through`, `arrow`, and a label if it needs one) on a route that
   crosses no box it does not name and no text, or, when no clear route
   exists, add `{"edge": "<edge id>", "reason": "..."}` to `map.omitted`,
   with a reason that says why the map leaves it out and where the reader
   finds it (the matrix always lists it, and the detail of each part whose
   end is a node below the part shows it as a tag). The validator reports
   `E-MAP-EDGES` while a pair is neither drawn nor omitted; the geometry
   check (below) finds a new line that crosses a box it does not name.

### Layout text

Strings in `map`, `place` and `detail` (box titles and sub lines, labels,
notes, band and column names, ladder names, captions, section texts) are
reader-facing text, so the accuracy rule applies to them as to prose: each
one must be supported by the model's own prose, summaries or edge labels,
or by the code at the pinned commit. No counts ("14 steps"), no rates other
than the ~929 kHz bucket rate, no claim stronger than the model's. A
universal word (every, each, all, only, never, no, one per) must hold for
every case the string covers: for example a DRP selected as monitor-only
writes no files, the map leaves out the edges in `map.omitted`, and the
matrix leaves out the edges inside one part; narrow or hedge the string
when a case breaks it. Write
them for the reader of the doc, without layout jargon. The single-source
check finds each of these strings if it is copied into the viewer.

### What the validator checks

Every layout error line starts with a code:

| Code | Meaning |
|---|---|
| `E-PLACE-MISSING` | A top-level part has no `place` (or no boxes), or the model has no `map`. |
| `E-CELL-SHARED` | Two boxes share a cell, two box rectangles overlap, or two grid items share a row and column. |
| `E-CHILD-TWICE` | A descendant appears more than once in its part's detail grid. |
| `E-CHILD-MISSING` | A descendant has no cell in its part's detail grid, or a group's kids miss one of its children. |
| `E-GRID-FOREIGN` | A grid or box names a node that is not in the part, a group without children or a nested group, a `sides` key that is not another part, or `place`/`detail` on a node below the top level. |
| `E-BOX-OUTSIDE-CELL` | A box rectangle is not inside its columns and band, a box names a column or band that does not exist, or a grid item lies outside the grid's columns or its group. |
| `E-LINE-REF` | A line names an edge or box that does not exist, an edge of another kind, a lane that does not exist, or a label names an unknown line. |
| `E-LINE-ENDS` | An end point of a line (of each subpath, when `d` has several) is not on the border of one of its `ends` boxes (or, for a subpath, of an `ends` or `through` box) within 2 units, an `ends` box is touched by no end point, or `d` cannot be parsed. |
| `E-LINE-THROUGH` | A `through` box is not crossed from border to border, by one subpath or across the gap between two subpaths; or the gap between two consecutive subpaths does not run across exactly one `through` box (part of the line would not be drawn). |
| `E-TOUR-MAP` | `map.tour` does not have one entry per tour step in order, a `highlight` list is empty or names nothing, nothing highlighted belongs to the step's part, or a token lies off the map. |
| `E-SEQUENCE` | The sequence chart does not have one row per tour step in order, or a row names an unknown lifeline. |
| `E-LADDER` | The ladder's node does not exist, it has the wrong number of transitions, or its stations leave the map. |
| `E-MAP-EDGES` | A pair of parts with an edge has no map line and no `map.omitted` entry, or a line's edge reaches a part the line does not touch. |
| `E-SIDES` | A `sides` entry of a part's `detail` names a side that does not agree with where that neighbour's boxes are on the map, or a neighbour that has tags in the detail has no `sides` entry (see "Detail grids"). |

## Worked example

These snippets are made up for this guide: the ids and texts are examples
only; do not paste them into the model as they are.

**1. Add a node with a code reference.** Append an object to the `nodes`
list (the position in the list sets its order in the one-page view):

```json
{
  "id": "example-buffered-writer",
  "parent": "drp",
  "title": "Example: buffered file writer",
  "summary": "Collects datagrams in memory and writes them to the file in large blocks.",
  "prose": "The `BufferedFileWriter` copies each datagram into a memory buffer.\n\nIt writes the buffer to the file when the next datagram does not fit, or when the batch in the buffer is more than 2 seconds old by event timestamp.",
  "code_refs": [
    {
      "path": "psdaq/drp/FileWriter.cc",
      "start": 108,
      "end": 160,
      "symbol": "BufferedFileWriter::writeEvent",
      "note": "The age and buffer-size checks that trigger a write."
    }
  ]
}
```

Check the reference before you validate:

```bash
git show "$COMMIT:psdaq/drp/FileWriter.cc" | sed -n '108,160p' | grep -F -- 'BufferedFileWriter::writeEvent'
```

Then give the node a cell in its part's detail grid. Its parent is `drp`, a
top-level part, so it goes into the `rows` of the `detail` of the node
`drp`. Its second row holds `drp-process` (col 0) and `detector-classes`
(col 1), so col 2 is free:

```json
[
  {"node": "drp-process", "col": 0},
  {"node": "detector-classes", "col": 1},
  {"node": "example-buffered-writer", "col": 2}
]
```

Without this the validator reports
`ERROR [E-CHILD-MISSING]: node drp.detail: descendant "example-buffered-writer" has no cell in the grid`.

**2. Add an edge.** Append to the `edges` list:

```json
{
  "id": "example-buffered-writer-to-files",
  "from": "example-buffered-writer",
  "to": "files",
  "label": "datagram blocks",
  "kind": "data",
  "prose": "When the next datagram does not fit in the buffer, or the batch in it is more than 2 seconds old, the writer writes the buffer to the file with one `_write()` call.",
  "code_refs": [
    {
      "path": "psdaq/drp/FileWriter.cc",
      "start": 123,
      "end": 133,
      "symbol": "_write",
      "note": "The buffer is written in one call when the next datagram does not fit or the batch is too old."
    }
  ]
}
```

Like every edge, it has `prose` backed by a code reference (or a source).
Check the reference the same way as the node's:

```bash
git show "$COMMIT:psdaq/drp/FileWriter.cc" | sed -n '123,133p' | grep -F -- '_write'
```

This edge goes from the part `drp` (the parent of
`example-buffered-writer`) to the part `files`. The map already has a line
for that pair (case 2 of "After adding an edge"): the `data` line
`drp-files` touches both parts and lists `e-drp-to-files` among its
`edges`, so the validator's `map_edges` count does not change. Add the new
edge's id to that line's `edges`, since the line stands for it too. In the
DRP's detail its label joins the tag for Files (one tag per neighbouring
part and direction), on the side that `sides` names for `files` (`right`,
where the Files boxes are on the map); the Files detail shows no tag for it,
because its end there is the part `files` itself, not a node below it. The
N² matrix lists it in the DRP-to-Files cell.

**3. Rewrite a node's prose.** Find the node by its `id` and replace its
`prose` string. Keep every sentence supported by the node's own code
references or sources; add a code reference or source if a new sentence
needs one. Use `\n\n` between paragraphs and `[[other-node-id]]` to point
to related nodes.

**4. Find your change on the page.** Preview the page (see "Check your
change" below). In "Explore the parts", click the DRP box on the map: the
card under the map opens on the DRP, because the new node's parent is the
part `drp`. The detail drawing in the card now has a box "Example: buffered
file writer" in its second row, third column, after the boxes of
`drp-process` and `detector-classes`. The tag "to Files ›" on the drawing's
right side lists the label "datagram blocks" with the other labels of the
edges to Files. Click the new box: the panel under the drawing shows the
node's title, its `summary` in bold and its `prose`. Its code reference is in
the panel's folded section for code references, and the new edge is in the
folded "Flows" section, under "Goes to". (If the box is missing from the
drawing, the node has no cell in the `detail` grid: the validator reports
`E-CHILD-MISSING`.) `browser_test.py --check-node` (below) makes the same
walk in a browser and checks it.

## Check your change

**Validate** (always; the site build runs the same check):

```bash
python docs/design/tools/validate.py
```

It prints one line per problem and two summary lines last, for example:

```text
ERROR: node example-buffered-writer.code_refs[0]: psdaq/drp/FileWriter.cc:108-160: symbol "writeEvnt" does not appear in lines 108-160
nodes=41 edges=49 levels=3 tour_steps=14 code_refs=183 sources=26 placed=41/41 grids=8/8 errors=1
layout_text=146 map_edges=16/16
```

`placed=X/N`: top-level parts with a valid place plus lower nodes with
exactly one cell in their part's detail grid, out of all nodes. `grids=G/P`:
parts with children whose detail grid has no error, out of all such parts.
`layout_text`: the number of layout strings. `map_edges=A/B`: of the B pairs
of parts that have an edge between them, the A that a map line draws or
`map.omitted` lists.

The exit status is 0 only when `errors=0`. Reading the errors (the layout
error codes are explained in "What the validator checks" above):

| Message (part) | What to do |
|---|---|
| `schema: '...' is a required property` | Add the missing field. `$.nodes[12]` is the 13th node; the id in parentheses says which. |
| `schema: ... is too long` / `does not match` | Shorten the text or fix the format (ids, URLs). |
| `duplicate id` | Choose another id. |
| `parent "..." does not exist` | Fix the `parent` id. |
| `symbol "..." does not appear in lines a-b` | Fix the line numbers at the pinned commit, or the symbol. |
| `path does not exist at commit` | Fix the path; check it with `git cat-file -e "$COMMIT:<path>"`. |
| `the range spans ... lines` | Narrow the range to at most 80 lines. |
| `needs a code ref of its own, or outside_repo ...` | Add a code reference, or mark the node `outside_repo` and cite an external source. |
| `cross-link [[...]] names no existing node` | Fix the id inside `[[...]]`. |
| `a decision needs at least one source or code ref` | Cite the basis of the decision. |
| `site page ... has no docs/....md` | Fix the `../<path>/` URL of the site-page source. |
| `[E-CHILD-MISSING] ... has no cell in the grid` | Give the node a cell in its part's `detail` (see "Detail grids"). |
| `[E-PLACE-MISSING]` | Give the top-level part a `place` (see "Pick a cell for a new top-level part"). |
| `[E-CELL-SHARED]`, `[E-BOX-OUTSIDE-CELL]` | Move the box or grid item to a free cell inside its columns and band. |
| `[E-LINE-ENDS]`, `[E-LINE-THROUGH]` | Fix the line's `d`, `ends` or `through` so that its ends sit on its `ends` boxes and it crosses each `through` box. |
| `[E-MAP-EDGES] no map line draws an edge from ...` | Add the edge to a map line's `edges`, or list it in `map.omitted` with a reason (see "After adding an edge"). |
| `[E-SIDES] ... but on the map the box centres of ... are ...` | Change the side to the one the message names (where that part is on the map). |
| `[E-SIDES] ... no side for "...", whose tags this detail shows` | Add a `sides` entry for that part, on the side where it is on the map. |
| `[E-LINE-THROUGH] ... the gap from subpath ... does not run across a through box` | Make each subpath end on a `through` box's border where the next subpath starts across the box, or join the subpaths. |
| `[E-TOUR-MAP]`, `[E-SEQUENCE]` | Add or move the step's `map.tour` entry or sequence row to the step's position. |

`--outline` also prints the model's sha256, the top-level titles and the tour
step titles.

**Preview** in a browser. Serve `docs/design` on a free port, reachable only
from your own machine (`--bind 127.0.0.1`), and record the server's port
and process ID so that you can stop exactly that process later. Save both
to files: each command below may run in a fresh shell (a new terminal, or
a tool that runs every command on its own), where `$PORT` and `$!` are no
longer set. The server's log, port and process ID go to `build/`; `build`
is ignored by git (see `.gitignore`), so they do not show up in
`git status`. Any path outside the checkout works too. The server reads
its input from `/dev/null` (`< /dev/null`) and writes its output to the
log, so that it holds neither the input nor the output of the shell that
started it: a tool that runs commands without a terminal (a script, a
remote shell, an agent) may otherwise wait for the server to end before it
returns.

```bash
PORT=$(python -c "import socket; s = socket.socket(); s.bind(('127.0.0.1', 0)); print(s.getsockname()[1])")
mkdir -p build
python -m http.server "$PORT" --bind 127.0.0.1 --directory docs/design < /dev/null > build/design-preview.log 2>&1 &
echo $! > build/design-preview.pid
echo "$PORT" > build/design-preview.port
echo "http://127.0.0.1:$PORT/"
```

In any later shell, set the port again first:
`PORT=$(cat build/design-preview.port)`.

Open the printed URL. The page starts with the map: the three mode buttons
and the Emphasize buttons are right above it, and the card is under it.
Clicking on the map, the buttons or inside the card does not scroll the
page. The exceptions are the links that take you somewhere: a link to a
node in a card (in its text, its Flows or the line that says where the node
is) opens that node and, when the card's top is above the window, brings
the card's head back to the top; "Read the full description" in the tour's
card opens the part in "Explore the parts" in the same way; "Back to the
map" scrolls to the map; and a small map in "Compare kinds" may bring the
map section to the top (see below).

- The mode buttons: "Explore the parts" (the page opens in it), "Follow one
  event" and "Compare kinds".
- **Explore the parts.** Click (or tap) a part's box on the map to open it
  in the card under the map. The card shows the part's detail drawing and,
  under it, the panel for the selected node. Click a box or a dashed group
  in the drawing to show that node in the panel, and click a tag on the
  drawing's edge ("from DRP ›") to open that neighbouring part. The card's
  head stays in view while you scroll the card; when a box or dashed group
  inside the part is open, the head shows the part's short name (its
  `place.short`) and then that node's title, for example "DRP › Result
  receiver: record and monitor"; a long name wraps onto a second line
  instead of being cut. Its
  arrows go to the previous or next card (the overview, then the top-level
  parts in the order of the model, then the overview again). "Close", shown
  only while a part is open, returns the card to the overview. When the card
  changes while you are further down in it (its head stuck at the top of the
  window), the new card starts right under the head and the page does not
  move; the space above it is left blank. A blank tall enough to hold a
  short note shows one, saying why the space is blank, with a "Back to the
  map" link; the note stays under the head while you scroll back up through
  the blank. A shorter blank (the card's top was only just above the
  window) has no note and no link. As you scroll back up, the blank
  shrinks only where that moves nothing on screen: its part below the
  bottom of the window goes, and the rest goes once it is all below the
  window, or once the card's top is back in view and what is left of the
  blank at the bottom of the window is too short for its note. When the
  window gets wider or narrower (a tablet turned, for example) while the
  head is stuck, a blank under the head closes up, so that the content
  starts right under the head again. Design
  decisions, code references, sources and flows are folded: open one with
  its heading. A card ends with "End of ..." and a "Back to the map" link.
- A link to a node (`#/node/<id>`) opens the card on that node's part, with
  the node highlighted in the drawing and its panel shown, and brings the
  card into view. The other addresses are `#/` (the overview),
  `#/tour/<k>` (the tour at step k), `#/compare`, `#/read` and
  `#/read/<id>` (the one-page view). Clicks on the map, the modes and the
  card replace the address without adding a history entry, so the
  browser's Back button does not undo them (it leaves the page). "Read as
  one page", and a link you follow in the one-page view, add an entry, so
  Back from the one-page view returns to the page.
- "Emphasize" (All, and one button per kind of edge, named from
  `map.kinds`) dims every other kind on the map and, for a kind, shows that
  kind's caption under the map. All shows no caption.
- Under the map: its caption, then "Not drawn on the map", which lists the
  `map.omitted` entries. "Full size", in a bar under the map's frame,
  enlarges the map to its natural size when the page draws it smaller (if it
  is then wider than its frame, it scrolls sideways in the frame and a note
  next to the button says so); a figure already drawn at its natural size
  or larger stays as it is. Press it again for the usual size.
- **Follow one event.** The tour moves one event across the same map; the
  page has no second map. Use "Back" and "Next", the numbered step buttons,
  or the Left and Right arrow keys once the focus is in the map section
  (click in it first; they do not move the tour inside a figure that scrolls
  sideways). The card under the map holds the step's text, the description
  of the step's node and its detail drawing ("Where this step happens"). It
  has its own head ("Step k of T", with "Back" and "Next") that stays in view
  while you scroll the card, and its footer, after "End of step k of T.",
  has "Previous step" and "Next step" too, so that you can go on from the
  end of the card. "Show the steps on: Sequence chart" swaps the
  map for the sequence chart (it has its own "Full size" button); click a row
  to change the step, and the card and a line under the chart name the new
  step.
- **Compare kinds.** The small maps replace the map: one for each kind of
  edge and one with all of them. Click one to go back to "Explore the
  parts" with that kind emphasized (if the top of the map section is above
  the window, the page brings it to the top, so that the buttons above the
  map are in view).
- After the "Reference" divider, the N² matrix lists every relation between
  two parts in a card of its own, with a line under the table that says what
  its shading means.
- "Read as one page" shows the model's question, summary, every part with
  its sub-parts and the tour as one document (`#/read`; the map, the
  sequence chart and the matrix are not on it); "How to read this page"
  opens a panel over the page that explains the controls.

A figure that is wider than its frame (on a phone, or at full size) says
"Scroll sideways" next to its "Full size" button. Reload the page after each
edit. When you are done, stop the server by its process ID (saved above):

```bash
kill "$(cat build/design-preview.pid)"
```

Do not stop it with a pattern such as `pkill -f http.server`: a pattern can
also match other processes, including the shell that runs the command.

Links to `../` (Documentation home), `editing-guide/` (Edit this model) and
`../features/...` (sources of kind `site-page`) work only on the built site
(`mkdocs serve` or `mkdocs build`), not when `docs/design` is served on its
own as above.

**Geometry check** (with the preview server running; in a fresh shell, set
`PORT=$(cat build/design-preview.port)` first). It measures the map, then
clicks the map box of each part that has children, in "Explore the parts",
so that the part's detail drawing opens in the card, and measures that
drawing. All measures are in SVG units:

```bash
python docs/design/tools/geometry_check.py --url "http://127.0.0.1:$PORT/"
python docs/design/tools/geometry_check.py --url "http://127.0.0.1:$PORT/" --width 744 --height 1000
```

Run it at both widths: the default window is 1440 by 900; 744 is a tablet
held upright, where the map is drawn smallest. It prints:

| Line | Meaning |
|---|---|
| `font=Archivo` | The page's web font is loaded (the measurements depend on it). `font=missing ...` fails the run. |
| `view=<map or detail:ID> boxes=B lines=L texts=T line_through_box=X text_overflow=Y crossings_allowed=K line_over_text=J label_on_box=Q box_overlap=O line_over_label=W small_text=S text_overlap=E min_text_px=P` | One line for the map, then one per detail drawing (each opened in the card). |
| `PROBLEM: ...` | One line per counted element, naming the view, the line, the box or the text. |
| `INFO: smallest text ...` | The smallest text at this width and where it is. |
| `views=V line_through_box=X text_overflow=Y` | Totals. V is 1 plus the number of parts that have children. |
| `crossings_allowed=K ... small_text=S text_overlap=E min_text_px=P` | Totals of the other counts. |

What the counts mean, and what to do:

- `line_through_box`: a line passes over a box that it does not name (in its
  `through` or `ends` on the map; in a detail, its own end boxes). Change the
  line's `d`, or name the box in `through` if the line should cross it.
- `text_overflow`: a text sticks out of its box, tag or group title, or a free
  label (a line's label, a note, a band or column name) leaves the map or
  covers a box. Shorten the text (box `sub` lines are not wrapped) or move
  the label.
- `box_overlap`: two boxes, tags or groups overlap; move one.
- `line_over_label`: a line is painted over a text; move the label or the
  line.
- `text_overlap`: two texts of one view lie on top of each other (for
  example a line's label moved onto another label, or a label on a box's
  title); move one of them.
- `small_text`: texts drawn smaller than 7 px at this width; a detail
  drawing that grows very wide (for example because of a long word in a
  title) makes its text small.
- Informational only: `crossings_allowed` (crossings of boxes that a line
  names, drawn as ports), `line_over_text` (a line that runs under a text
  but is hidden by an opaque box) and `label_on_box`.

The exit status is 0 only when the font is Archivo, V is right and X, Y, O,
W, S and E are all 0.

**Browser test** (with the preview server running; in a fresh shell, set
`PORT=$(cat build/design-preview.port)` first):

```bash
python docs/design/tools/browser_test.py --url "http://127.0.0.1:$PORT/"
python docs/design/tools/browser_test.py --url "http://127.0.0.1:$PORT/" --layout
python docs/design/tools/browser_test.py --url "http://127.0.0.1:$PORT/" \
    --check-node example-buffered-writer \
    --expect-title "Example: buffered file writer" \
    --expect-prose "copies each datagram into a memory buffer"
python docs/design/tools/browser_test.py --url "http://127.0.0.1:$PORT/" \
    --check-edge example-buffered-writer-to-files
```

The first command drives the page by clicking, as a reader would. It
reloads the page between groups of checks, so that one failure does not
hide the others, and it takes several minutes. It prints these lines, in
this order (a line that appears twice is checked at two window sizes):

| Line | It passes when |
|---|---|
| `nodes_visited=V/N tour_steps=S/T console_errors=C` | V = N: every node was reached by clicking (a part's box on the map; a lower node's box or group in its part's detail, in the card) and the panel then showed its title and the first 30 characters of its prose, with a folded section for each non-empty list of decisions, code references and sources, for the flows when the node has an edge, and for the developer notes when the node has `dev_notes`. S = T: every tour step showed its title, the start of its prose and the "THIS STEP" mark on the map. C = 0. |
| `smoke stub_click=ok arrow_keys=ok help=ok read_page=R/N third_party=Q arrow_scope=ok compare_tap=ok fullsize_keys=ok` | A tag opens its part, the arrow keys move the tour when the focus is in the map section in "Follow one event", the help opens and closes, the one-page view has a section with the right title for every node (R = N), the page loads nothing from other sites except the fonts (Q = 0), and the arrow keys pressed elsewhere on the page (on the matrix) neither move the tour nor stop the browser's sideways scroll. `compare_tap`: a tap on a small map in "Compare kinds" opens "Explore the parts" with that kind's Emphasize button pressed and its caption shown; the page stays where it is, or, when the top of the map section was above the window, brings it to the top of the window. `fullsize_keys`: with the map at full size (so that it scrolls sideways in its frame), Left and Right pressed with the focus in the frame do not change the tour's step. |
| `map_first viewport=744x1000 map_top=A map_bottom=B above_map=<names> frame_top=F`, then the same at `viewport=1440x900` | The map comes first: `above_map` is exactly `modes,chips`, so the mode switch and the Emphasize buttons are the only blocks between the page title and the map's frame. At 744x1000 the map's bottom B is at most 1000; at 1440x900 its top A is at most 450. |
| `modes=M full_maps=F` | M = 3: the three mode buttons each switch the mode and press themselves. F = 1: in every mode, and in the tour's sequence view, the document holds exactly one full-size map drawing (not a small map, not a detail drawing), and in "Explore the parts" and in the tour's map view that map is displayed. |
| `map parts=A/P lanes=L bands=B columns=K boxes=O/Q` | Every part has a box on the map, the lanes, bands and columns match `map`, and every box is drawn exactly where its `place` says (O = Q). |
| `detail opened=X/P` | Clicking each part that has children, in "Explore the parts", opens its detail in the card with every descendant drawn. |
| `tour steps=S/T highlighted=H/T on_main_map=G/T tag_clear=K/T` | For every step, the highlighted lines and boxes are exactly the step's `highlight` list and the dots are its `tokens`. G = T: for every step the outline of the step's part and the dots are on the one map (`#map`), the map holds no other outline, and the page has no other full-size map. K = T: the "THIS STEP" tag covers no text of the map. The viewer puts the tag at the first place around the part's dashed outline that is free of text (under it, over it, then beside it); if no place is free, move a label or note away from that part. |
| `tour_card text=X/T detail=Y/T` | For every step, the step card lies below the map's frame. X = T: it shows (displayed, under the map's frame) the step's title and the first 30 characters of its prose. Y = T: it shows, displayed and under the map's frame, the detail of the part that holds the step's node, with the node highlighted. |
| `multiples panels=M/6 mode=compare` | Each of the six small maps leaves exactly its kind of line undimmed (the sixth shows all kinds), and the small maps are displayed only in "Compare kinds". |
| `sequence rows=R/T mode=tour` | Each row of the sequence chart draws its step's arrow between the right lifelines, with its label; clicking a row shows that step in the card, keeps the sequence chart, and the line under the chart reads "Step k of T: <the step's title>" inside the window. The rows are displayed only in "Follow one event" with the steps shown on the sequence chart. |
| `emphasize captions=K/K` | K is the number of edge kinds whose `map.multiples` entry has a caption. A kind counts when its Emphasize button shows that caption under the map's frame (the first 30 characters of it) and dims the lines of the other kinds. |
| `card default=overview after_close=overview nav=X/9 sticky_head=<bool> end_footer=<bool> folded=<bool> stuck_view=K/K head_names=K/N spacer_note=ok` | See "The card line" below. It passes when `default` and `after_close` print `overview` (a failing run prints what was wrong instead), X = 9, every bool is true, `stuck_view` counts every case, `head_names` counts every node and `spacer_note` is `ok`. |
| `matrix cells=C2/C hscroll=<px> sticky_head=<bool> close_buttons=<n> end_footer=<bool> divider=<bool>` | See "The matrix line" below: it passes when C2 = C, hscroll is 0, close_buttons is 0 and every bool is true. |
| `deeplinks=D/4` | Each of these four addresses, loaded in a fresh page, counts when it sets the right mode, shows the right content and lands in view: `#/node/<a lower node's id>` (the card on that node's part, the node highlighted, its panel shown, the card's head within 120 px of the top of the window); `#/tour/3` (the card of step 3) and `#/compare` (the six small maps), each with the map section at the top of the window (or the page cannot scroll that far); `#/read` (the one-page view, at the top of the page). |
| `page_height=H` | The page is at most 4000 px high at 744x1000 on `#/`. |
| `scroll_jumps=J/N viewport=744x1000 failed=F expected=E moves_page_ok=true control_moved=K/N`, then the same at `viewport=1440x900` | No in-page click moves the page: J = 0 and F = 0, N = E and N is at least 40, and `moves_page_ok=true` (see "The scroll_jumps line" below). |
| `console_errors=C` | No errors or warnings in the browser console, and no failed requests. |

**The card line.**

- `default=overview`: on `#/` the card is the overview, under the map's
  frame, and it shows the model's `question`, the start of its `summary`
  and how to read the map (the title of `map.sections.map` and the start of
  its `intro`).
- `after_close=overview`: after a part is opened and Close is pressed, the
  card is the overview again, shown and not empty; and also when Close is
  pressed while the card's head is stuck at the top of the window (the
  card's top 300 px above it, and again near the card's end with every fold
  open): the page does not move, and what shows right under the head is the
  start of the overview, not blank space.
- `stuck_view=K/K`: the same for the card's arrows: with the head stuck,
  the next or previous card starts right under the head and the page does
  not move. It is checked at 744 and 1440 px for the next and the previous
  arrow (and for the step card's own Back and Next, when it has them).
- `head_names=K/N`: every node is opened (its part's box on the map, then
  its box or group in the card), at 744 px and at 400 px wide, and no text
  in the card's head is cut (no "..." and nothing hidden past the edge); at
  744 px the head is also at most 100 px tall. K counts the nodes for which
  both sizes pass.
- `spacer_note=ok`: after each of the stuck cases above (at 744 px), the
  test scrolls back up with the mouse wheel; while the space under the head
  is blank, the blank's note and its "Back to the map" link must show under
  the head. The link is also pressed once from the blank (and once from the
  step card's blank): the map section must then be at the top of the window.
  An informational `NOTE: spacer_blank_px=<px>` gives the tallest blank.
- `nav=X/9`: pressing the card's next arrow nine times from the overview
  visits the overview, the eight top-level parts in the order of the model,
  and the overview again, and the previous arrow gives the exact reverse.
  X counts the presses that land on the right card.
- `sticky_head=true`: with the largest part card scrolled so that its top is
  300 px above the window, the card's head is at the top of the window (within
  2 px) and inside the card, and no element around the head clips it. It is
  checked at 744 and at 1440 px.
- `end_footer=true`: the overview and each part's card end with a footer
  that starts with "End of": "End of the overview." or "End of <the part's
  title>.", with a "Back to the map" link. The tour card's footer ("End of
  step k of T.") is checked the same way.
- `folded=true`: in every part's card, the sections for decisions, code
  references, sources and flows are closed folds, and every non-empty list
  of the node in the model has its fold.

**The matrix line.**

- `cells=C2/C`: each cell of the matrix lists exactly the labels of the
  edges between its two parts.
- `hscroll=0`: at 744 px the table needs no sideways scroll, no cell ends
  beyond the card, and no element around the table clips it sideways.
- `sticky_head=true`: as for the card.
- `close_buttons=0`: the matrix card has no button in it.
- `end_footer=true`: the card ends with "End of the interfaces." (its
  eyebrow, in lower case) and a "Back to the map" link.
- `divider=true`: the "Reference" divider is shown between the card and the
  matrix.

**The scroll_jumps line.** The test first lists every press it will make,
from the model and the page (E, `expected`), then makes each one for real:
a mouse click on a point of the control that receives it, or a key pressed
with the focus on the control. It presses every mode button, Emphasize
button, step button, Back and Next, both buttons that switch the tour's
view, every sequence row, every map part (in "Explore the parts" and in
"Follow one event"), detail box, group and tag, a box and a tag of the tour
card's detail, "About this tour", both "Full size" buttons (and presses them
again), the card's arrows and Close, the step card's own Back and Next when
it has them, and the help button. It also presses Enter on a focused map
box, a sequence row and a tag, and it clicks the card's arrows and Close
when the card's top is 300 px above the window, so that its head is stuck at
the top. It also presses the step card's "Next step" and "Previous step"
at the end of the card, when the card has them. After each press it waits
600 ms, and it logs every scroll event of the window from the press to the
end of that wait. J is the number of presses after which the window
scrolled by more than 1 px: during the wait (even if the page came back
before the wait ended), right away, or later (before the next press, or
1.5 s after the last one); F is the number of presses
that could not be made (the control is missing, covered, or the page is not
in the state the press needs); N is the number of presses made. Only four
kinds of control may scroll the page: the "Back to the map" links, the
button of the tour card that opens the step's part, the small maps of
"Compare kinds", and the links in the text of a card or of the one-page
view that open a node. The test does not press them (nor "Read as one
page", which changes the address to the one-page view), and before every
press it checks that these carry the mark that lets them scroll and that no
other control does (`moves_page_ok`). `control_moved=K/N` is informational: the
number of pressed controls that moved on the screen by more than 2 px.

**Informational lines** (they never fail the run):

| Line | What it shows |
|---|---|
| `full_map_count explore=1 tour_map=1 tour_seq=1 compare=1 displayed=explore,tour_map` | The number of full-size map drawings in each mode and view, and the ones where the map is displayed. |
| `card_head_px=H` | The height of the card's head at 744 px (the target is at most 100). |
| `matrix_min_text_px=P` | The smallest text in the matrix at 744 px (about 12 or more). |
| `tour_fit viewport=744x1000 tourbar_bottom=.. step_title_bottom=..` | Where the tour's Back and Next bar and the step's title end at 744x1000 (the target is at most 1000 for both). |
| `min_tap_px=P` | The smaller side of the smallest control at 744 px (the target is at least 32). |
| `elapsed group=s,...` | The seconds each group of checks took. |

A failing check also prints `PROBLEM: <check>: <detail>`, and every
`PROBLEM:` line fails the run, also when all the lines above pass. `NOTE:`
lines are informational. A check that finds nothing to test fails.

Where a line says that something is shown (displayed), the test checks that
the element has a size, is not hidden or transparent, is not cut away by a
box around it that clips its content (for example a wrapper with
`max-height: 0` and `overflow: hidden`), and passes a hit test: at some
point of its visible part in the window, the browser's `elementFromPoint`
gives the element or something inside it. A layer on top that lets clicks
through (`pointer-events: none`) is not seen by that hit test, so an element
under such a layer still counts as shown. Every click of the test is a real
mouse click on a point of the control that receives it; a control that
cannot be clicked that way fails the run.

`--layout` loads the page at several window sizes and prints
`layout_identical=true parts=P` (the map is the same at 744 and 1440 pixels
wide), `width=W page_hscroll=0` for widths 400, 744 and 1440 (the page itself
never scrolls sideways), the informational
`inner_scroll=<section:px,...> min_text_px=P` at 744 (`none` when no figure
scrolls inside its frame), `fullsize map=ok sequence=ok desktop=ok` (the "Full size"
buttons of the map and of the sequence chart work, the sequence chart's
checked in "Follow one event" with the steps shown on the sequence chart, and
the map fits a 744-pixel window; `desktop=ok`: at 1440 pixels, "Full size"
never draws a figure narrower than before and draws it at least at its
natural size, and the note next to the button shows exactly when the figure
then scrolls sideways), `theme dark=ok light=ok override=ok` (with
the system set to dark the page and the map use the dark colours, with it set
to light the light ones, and a `data-theme` of `light` or `dark` on the
page's root element wins over the system setting) and `console_errors=0`.

`--check-node` opens one node by its link and by clicking (the part's box on
the map, then the node's box or group in the card), and prints
`check_node id=ID title_ok=true prose_ok=true in_detail=true console_errors=0`
when the panel shows the title, the prose contains the text, and the node's
box (or its group's frame) is drawn in its part's detail drawing inside the
card. `--expect-prose` is matched against the rendered, visible text of the
panel (whitespace-normalized), so pick a substring without markup: no
backticks, no `[[...]]` and no link syntax.

`--check-edge` prints `check_edge id=ID drawn=true console_errors=0` when the
edge is drawn: an edge inside one part as an arrow in that part's detail; an
edge between two parts with an end below a part as the tag in the detail of
each such part; an edge between two top-level parts on a map line or in its
matrix cell. It checks that the edge is drawn, not its label.

Add `--full` to a `--layout`, `--check-node` or `--check-edge` command to run
the full run as well.

Every run exits with status 0 only when all of its lines pass and it
printed no `PROBLEM:` line.
`docs/design/tools/README.md` describes the tools, their options and the
test hooks in full.

**Single-source check** (that no model text was copied into the viewer):

```bash
python docs/design/tools/check_single_source.py
```

It must print `found_in_viewer=0`, `titles_found_in_viewer=0` and
`windows_found_in_viewer=0` (the last one checks every 40-character window of
the prose, so copying text from the middle of a field into the viewer is
caught too). It also checks every layout string (box titles, labels,
captions, section texts and the other strings of `map` and `place`) and
that no node id is written into `viewer.js`; see
`docs/design/tools/README.md` for its output lines.

**Site build** (optional; the published site is built the same way):

```bash
mkdocs build --strict -d /tmp/lcls2-site
```

## Rules in short

- Edit only `docs/design/daq-model.json`.
- Every factual sentence is backed by a code reference or source on the same
  node, decision, edge or step; say when the reason is not documented.
- Code references point at the pinned commit, with a symbol inside the range.
  The validator's symbol check is a plain substring match that a comment can
  satisfy too: check that the symbol names code.
- Internal Confluence: summarize and link, never copy; no credentials or
  personal data.
- Give every new node a cell in its part's `detail` grid, and every new
  top-level part a `place` in a free cell of the map; draw or omit (with a
  reason) every new pair of parts that an edge connects.
- Run the validator until it prints `errors=0`, then preview, and run the
  geometry check (at 1440 and at 744 pixels wide) and the browser test.
- After adding an edge, check it in the browser with
  `browser_test.py --check-edge <edge id>` (it checks that the edge is
  drawn, not its label).
