# Editing the design model

The design document
[How the LCLS-II DAQ works, from detector to disk](index.html) is generated
from one file (the viewer's header links here as "Edit this model"):
`docs/design/daq-model.json` (the *model*). The
viewer (`index.html`, `viewer.js`, `viewer.css`) only draws the model; it
contains no text about the DAQ. **To change what the document says, edit
only `daq-model.json`.** Never edit the viewer files to change content.

This guide is for people and for AI agents. With it and a checkout you can
add a node with a code reference, add an edge, rewrite a node's prose,
check your change and preview it.

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
browser test only, `playwright` with its Chromium browser; the site build
uses Python 3.12. If you already have an environment with these (for example
a conda environment), use it and skip the installs. Otherwise:

```bash
pip install -r docs/requirements.txt        # includes jsonschema, used by the validator
pip install playwright                      # only for the browser test
python -m playwright install chromium       # only for the browser test
```

## The files

| File | What it is | Edit it? |
|---|---|---|
| `docs/design/daq-model.json` | The model: all content. | Yes, this is the only file you edit. |
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

- `title`, `question`, `summary`: shown on the overview (the top level).
- `code_base`: `repo_url` and the full 40-character `commit` that every code
  reference points into. Code links are built as
  `<repo_url>/blob/<commit>/<path>#L<start>-L<end>`.
- `sources`: every document the model cites, each with an `id`, `title`,
  `url`, `kind` and an optional `note`. Nodes, decisions, edges and tour
  steps refer to sources by id.
- `nodes`: the components, as a flat list. Each node has:
    - `id`, `parent` (the parent's id, or `null` for a top-level node),
      `title` (at most 40 characters, shown on the box), `summary` (one
      sentence, at most 160 characters, shown on the box), `prose` (the
      concept, shown first);
    - optional `dev_notes` (shown under "For developers"), `outside_repo`,
      `decisions`, `code_refs`, `sources`.
- `edges`: flows between nodes: `id`, `from`, `to`, `label` (at most 30
  characters, drawn on the arrow), `kind` (one of `data`, `trigger`,
  `timing`, `control`, `monitoring`), optional `prose`, `code_refs`,
  `sources`.
- `tour`: `title`, `intro` and `steps` that follow one event. Each step has
  an `id`, a `title`, the `node` it is about, `prose`, and optional `edges`
  (edge ids to highlight), `code_refs` and `sources`.

### Ids

Ids are lowercase words joined by hyphens (`drp-file-writer`), at most 60
characters. Nodes, edges, tour steps, sources and decisions (decisions may
have an id) share **one** namespace: an id must be unique in the whole file.
Ids appear in links (`#/node/<id>`), so do not rename an existing id.

### Parents and levels

A node with `"parent": null` is at level 1 (a box on the overview). Its
children are level 2, their children level 3, and so on. The viewer shows
the children of the node you click; a node without children (a leaf) is
shown among its siblings. The model must reach level 3 somewhere. Parents
must exist and must not form a cycle.

A parent may have a single child: the validator has no rule on the number
of children, and the viewer then draws a map with one box. A leaf that gets
its first child becomes a parent: its box says "1 part" ("N parts" for
more) instead of "Details", clicking it zooms in to its children instead of
showing it among its siblings, and the panel still shows its own prose,
code references and sources. Like every node below the top level it
still needs a code reference of its own (or `outside_repo` with an external
source). An edge attached to the node itself is not drawn inside it (on the
map of its children), not even as a stub, because neither of its ends is a
box there; the node's panel still lists it under "Flows". To show such a
flow inside the node, attach the edge to the child instead. A tour step
whose `node` is the new parent still shows the parent's own level, with the
parent highlighted among its siblings.

An edge may connect any two nodes, at any levels, except a node and its own
ancestor or descendant. The viewer draws an edge between the boxes that
contain its ends at the current level ("lifted" to the visible ancestors).
An edge with one end outside the current view is drawn as a stub arrow to
the edge of the map, ending at a tag that names the node at the outside end
(click it to go there), and is listed in the detail panel under "Comes
from" and "Goes to". Edges between the same two boxes with the same kind are
drawn as one arrow; its label shows the label of the edge that comes first
in the file plus "(+N more)", and clicking the label lists all of them.
Only `data`, `trigger` and `timing` edges decide the left-to-right order of
the boxes (see "Edge kinds" below). There are no layout hints: the order of
nodes in the file is the tie-break. Give an edge `prose` (one or two
sentences, with a code reference or source): it is what a reader sees for
the flow in the panel and in the one-page view.

The order of nodes in the file sets:

- the order of the parts in "Read as one page" (`#/read`): its contents list
  shows the top-level nodes in file order, and each part is followed by its
  children in file order (depth first);
- the layout tie-break: boxes in the same column are placed top to bottom
  in file order, and boxes without a `data`, `trigger` or `timing` arrow to
  or from another box on the map (stub arrows do not count) fill the free
  places in file order (with no such arrows at all, the boxes form a grid
  in file order);
- the order of the `top:` lines that `validate.py --outline` prints.

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

In the viewer each kind has its own color and line pattern on the map
(shown in the map's legend) and a badge with its name in the lists of
flows. Only `data`, `trigger` and `timing` arrows between two boxes of the
current map rank the layout: the boxes are placed in columns from left to
right along these arrows (by the longest path; arrows that close a cycle
are ignored), and columns that do not fit the width wrap into bands below each
other. `control` and `monitoring` arrows, and stub arrows of any kind, do
not decide the order of the boxes, but they can change the size and place
of boxes: every arrow and stub adds a track to the lane it runs in, a busy
lane gets taller, which moves the boxes below it down and can make all
boxes shorter, and stub tags take width at the left and right edges of the
map, so fewer columns may fit in a band.

### Prose markup

- A blank line (`\n\n` in the JSON string) starts a new paragraph.
- `` `code` `` is inline code.
- `[text](https://example.org/page)` is a link (http, https or a relative URL).
- `[[node-id]]` links to another node (the link text is the node's title);
  `[[node-id|some text]]` uses your text. The id must exist.
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
its title says so). A step's `node` is the box the viewer highlights (the map
shows that node's level); its `edges` are highlighted too, including stub
arrows to other levels. Step links are `#/tour/<k>` with k counted from 1,
so inserting a step changes the numbers of the steps after it. The browser
test checks that the first 30 characters of each step's prose (as plain
text) are visible in the step card.

## Worked example

These snippets are made up for this guide: the ids and texts are examples
only; do not paste them into the model as they are.

**1. Add a node with a code reference.** Append an object to the `nodes`
list (the position in the list is the tie-break for layout):

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

**2. Add an edge.** Append to the `edges` list:

```json
{
  "id": "example-buffered-writer-to-files",
  "from": "example-buffered-writer",
  "to": "files",
  "label": "Datagram blocks",
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

On the overview this edge is drawn between the boxes of `drp` and `files`
(the parent of `example-buffered-writer` is `drp`). Inside `drp` it is listed
under "Goes to" in the detail panel.

**3. Rewrite a node's prose.** Find the node by its `id` and replace its
`prose` string. Keep every sentence supported by the node's own code
references or sources; add a code reference or source if a new sentence
needs one. Use `\n\n` between paragraphs and `[[other-node-id]]` to point
to related nodes.

## Check your change

**Validate** (always; the site build runs the same check):

```bash
python docs/design/tools/validate.py
```

It prints one line per problem and a summary line last, for example:

```text
ERROR: node example-buffered-writer.code_refs[0]: psdaq/drp/FileWriter.cc:108-160: symbol "writeEvnt" does not appear in lines 108-160
nodes=41 edges=30 levels=3 tour_steps=11 code_refs=60 sources=14 errors=1
```

The exit status is 0 only when `errors=0`. Reading the errors:

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

`--outline` also prints the model's sha256, the top-level titles and the tour
step titles.

**Preview** in a browser. Serve `docs/design` on a free port, reachable only
from your own machine (`--bind 127.0.0.1`), and record the server's process
ID so that you can stop exactly that process later. The server's log goes
to `build/design-preview.log`; `build` is ignored by git (see `.gitignore`),
so the log does not show up in `git status`. Any path outside the checkout
works too.

```bash
PORT=$(python -c "import socket; s = socket.socket(); s.bind(('127.0.0.1', 0)); print(s.getsockname()[1])")
mkdir -p build
python -m http.server "$PORT" --bind 127.0.0.1 --directory docs/design > build/design-preview.log 2>&1 &
SERVER_PID=$!
echo "http://127.0.0.1:$PORT/"
```

Open the printed URL. Click a box to zoom in; "Zoom out", the
breadcrumb, Escape or Backspace zoom out; click an arrow's label to list its
flows; click a tag at the map edge to go to that part; "Tour" follows the
event (Left and Right arrow keys move between steps); "Read as one page"
shows the whole model as one document (`#/read`); "How to read this page"
explains the controls. Reload the page after each edit. When you are done,
stop the server by its process ID:

```bash
kill "$SERVER_PID"
```

Do not stop it with a pattern such as `pkill -f http.server`: a pattern can
also match other processes, including the shell that runs the command.

Links to `../` (Documentation home), `editing-guide/` (Edit this model) and
`../features/...` (sources of kind `site-page`) work only on the built site
(`mkdocs serve` or `mkdocs build`), not when `docs/design` is served on its
own as above.

**Browser test** (with the preview server running, in the same shell, so
that `$PORT` is set):

```bash
python docs/design/tools/browser_test.py --url "http://127.0.0.1:$PORT/"
python docs/design/tools/browser_test.py --url "http://127.0.0.1:$PORT/" \
    --check-node example-buffered-writer \
    --expect-title "Example: buffered file writer" \
    --expect-prose "copies each datagram into a memory buffer"
python docs/design/tools/browser_test.py --url "http://127.0.0.1:$PORT/" \
    --check-edge example-buffered-writer-to-files
```

The first command clicks through every node and every tour step and prints
`nodes_visited=V/N tour_steps=S/T console_errors=C`, then a line
`smoke stub_click=ok edge_label=ok arrow_keys=ok help=ok read_page=R/N`; it
passes when V = N, S = T, C = 0 and every smoke check passes (a node counts
only if the panel shows its title and the start of its prose; a step only if
its title and the start of its prose are visible). For a model of about 40
nodes it takes roughly 10 to 60 seconds, depending on the machine. The
second opens one node (by link and by clicking down from the overview) and
checks its title and prose. `--expect-prose` is matched against the
rendered, visible text of the panel (whitespace-normalized), so pick a
substring without markup: no backticks, no `[[...]]` and no link syntax.
The third opens the level where the edge is drawn between two boxes and,
for each end that lies deeper, the level where the edge appears as a stub
arrow, and checks that the arrow and the stubs are there; it prints
`check_edge id=ID drawn=true console_errors=0` when they are. See
`docs/design/tools/README.md` for the details and the test hooks.

**Single-source check** (that no model text was copied into the viewer):

```bash
python docs/design/tools/check_single_source.py
```

It must print `found_in_viewer=0`, `titles_found_in_viewer=0` and
`windows_found_in_viewer=0` (the last one checks every 40-character window of
the prose, so copying text from the middle of a field into the viewer is
caught too).

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
- Run the validator until it prints `errors=0`, then preview.
- After adding an edge, check it in the browser with
  `browser_test.py --check-edge <edge id>` (it checks the arrow and its stub
  arrows, not the arrow's label).
