#!/usr/bin/env python3
"""Validate the DAQ design model (docs/design/daq-model.json).

Checks the model against the JSON Schema (draft 2020-12) and then runs the
semantic checks (ids, parents, edges, tour, sources, cross-links, code
references at the pinned commit, node rules) and the layout checks (the
top-level "map" block, each top-level node's "place" and "detail"). Every
problem is printed on its own line as

    ERROR: <where>: <what>

or, for a layout problem, with its code first:

    ERROR [E-CELL-SHARED]: <where>: <what>

followed by exactly two summary lines:

    nodes=N edges=E levels=L tour_steps=T code_refs=R sources=S placed=X/N grids=G/P errors=K
    layout_text=M map_edges=A/B

placed: top-level parts with a valid place plus lower nodes with exactly one
cell in their part's detail grid, out of all nodes. grids: top-level parts
with children whose detail grid is valid, out of all such parts.
layout_text: the number of strings that iter_layout_text() yields.
map_edges: B = distinct (top part of from, top part of to) pairs of the
edges whose two ends lie in different top-level parts; A = those pairs with
at least one edge drawn by a map line or listed in map.omitted.

Layout error codes: E-PLACE-MISSING, E-CELL-SHARED, E-CHILD-TWICE,
E-CHILD-MISSING, E-GRID-FOREIGN, E-BOX-OUTSIDE-CELL, E-LINE-REF,
E-LINE-ENDS, E-LINE-THROUGH, E-TOUR-MAP, E-SEQUENCE, E-LADDER, E-MAP-EDGES.

Exit status: 0 if there are no errors, 1 if there are errors, 2 if the
model or schema cannot be read at all (missing file, JSON syntax error).

Usage:
    python docs/design/tools/validate.py [--model PATH] [--schema PATH]
                                         [--repo PATH] [--outline]

The repository must be a full clone: the code references are read from the
pinned commit (code_base.commit) with git.
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
DESIGN_DIR = TOOLS_DIR.parent

# [[node-id]] or [[node-id|text]] in a PROSE field.
CROSS_LINK_RE = re.compile(r"\[\[([^\]|]*)(?:\|[^\]]*)?\]\]")
# A site-page source URL: ../<path>/ with an optional #anchor.
SITE_PAGE_RE = re.compile(r"^\.\./([a-z0-9_/-]+)/(#[a-z0-9_-]+)?$")
MAX_CODE_REF_SPAN = 80


# ---------------------------------------------------------------------------
# Small helpers that never raise on malformed input
# ---------------------------------------------------------------------------

def as_list(value):
    return value if isinstance(value, list) else []


def as_dict(value):
    return value if isinstance(value, dict) else {}


def is_blank(value):
    return not isinstance(value, str) or value.strip() == ""


# ---------------------------------------------------------------------------
# PROSE fields, derived from the schema (shared with the other tools)
# ---------------------------------------------------------------------------

def prose_field_patterns(schema):
    """Return the paths of every PROSE field in the schema.

    A path is a tuple of property names and "*" (any array item), e.g.
    ("nodes", "*", "decisions", "*", "rationale"). A field is PROSE when the
    description of its property starts with "PROSE".
    """
    defs = as_dict(schema.get("$defs"))
    patterns = []

    def resolve(sub):
        ref = sub.get("$ref") if isinstance(sub, dict) else None
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            return as_dict(defs.get(ref[len("#/$defs/"):])), ref
        return as_dict(sub), None

    def walk(sub, path, seen_refs):
        sub, ref = resolve(sub)
        if ref is not None:
            if ref in seen_refs:
                return
            seen_refs = seen_refs | {ref}
        for name, prop in as_dict(sub.get("properties")).items():
            prop_resolved, _ = resolve(prop)
            description = prop_resolved.get("description", "") or as_dict(prop).get("description", "")
            if isinstance(description, str) and description.startswith("PROSE"):
                patterns.append(path + (name,))
                continue
            walk(prop, path + (name,), seen_refs)
        if "items" in sub:
            walk(sub["items"], path + ("*",), seen_refs)

    walk(schema, (), frozenset())
    return patterns


def iter_pattern(data, pattern, where="$"):
    """Yield (json path, value) for every value of data at pattern (best effort)."""
    if not pattern:
        yield where, data
        return
    head, rest = pattern[0], pattern[1:]
    if head == "*":
        for i, item in enumerate(as_list(data)):
            yield from iter_pattern(item, rest, f"{where}[{i}]")
    elif isinstance(data, dict) and head in data:
        yield from iter_pattern(data[head], rest, f"{where}.{head}")


def iter_prose(model, schema):
    """Yield (where, text) for every non-empty PROSE string in the model."""
    for pattern in prose_field_patterns(schema):
        for where, value in iter_pattern(model, pattern):
            if isinstance(value, str):
                yield where, value


# ---------------------------------------------------------------------------
# git access with a per-path cache
# ---------------------------------------------------------------------------

class GitBlobs:
    def __init__(self, repo, commit):
        self.repo = str(repo)
        self.commit = commit
        self.cache = {}

    def _git(self, *args):
        return subprocess.run(["git", "-C", self.repo, *args], capture_output=True)

    def commit_exists(self):
        result = self._git("cat-file", "-e", f"{self.commit}^{{commit}}")
        return result.returncode == 0

    def lines(self, path):
        """Return the list of lines of path at the commit, or a str error."""
        if path not in self.cache:
            spec = f"{self.commit}:{path}"
            if self._git("cat-file", "-e", spec).returncode != 0:
                self.cache[path] = f"path does not exist at commit {self.commit[:12]}"
            elif self._git("cat-file", "-t", spec).stdout.decode().strip() != "blob":
                self.cache[path] = f"path is not a file at commit {self.commit[:12]}"
            else:
                content = self._git("show", spec).stdout.decode("utf-8", errors="replace")
                self.cache[path] = content.splitlines()
        return self.cache[path]


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------

class Report:
    def __init__(self):
        self.errors = []

    def error(self, where, what):
        self.errors.append(f"ERROR: {where}: {what}")

    def layout_error(self, code, where, what):
        self.errors.append(f"ERROR [{code}]: {where}: {what}")


def short(text, limit=300):
    text = str(text)
    return text if len(text) <= limit else text[:limit] + "..."


def check_schema(model, schema, report):
    from jsonschema import Draft202012Validator

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(model), key=lambda e: (e.json_path, e.message))
    for err in errors:
        report.error(with_id(model, err.json_path), "schema: " + short(err.message))


ITEM_PATH_RE = re.compile(r"^\$\.(nodes|edges|sources|tour\.steps)\[(\d+)\]")


def with_id(model, json_path):
    """Append the id of the node/edge/source/step a JSON path points into."""
    match = ITEM_PATH_RE.match(json_path)
    if not match:
        return json_path
    container = as_dict(model)
    for key in match.group(1).split("."):
        container = as_dict(container).get(key) if isinstance(container, dict) else None
    items = as_list(container)
    index = int(match.group(2))
    item_id = as_dict(items[index]).get("id") if index < len(items) else None
    return f"{json_path} ({item_id})" if isinstance(item_id, str) else json_path


def node_label(node, index):
    node_id = as_dict(node).get("id")
    return f"node {node_id}" if isinstance(node_id, str) else f"nodes[{index}]"


def check_semantics(model, schema, repo, report):
    """Rules 2-13. Returns the counts for the summary line."""
    model = as_dict(model)
    nodes = as_list(model.get("nodes"))
    edges = as_list(model.get("edges"))
    sources = as_list(model.get("sources"))
    tour = as_dict(model.get("tour"))
    steps = as_list(tour.get("steps"))

    # ---- rule 2: one id namespace -------------------------------------
    first_use = {}

    def claim(item_id, where):
        if not isinstance(item_id, str):
            return
        if item_id in first_use:
            report.error(where, f'duplicate id "{item_id}" (also used by {first_use[item_id]})')
        else:
            first_use[item_id] = where

    for i, node in enumerate(nodes):
        claim(as_dict(node).get("id"), f"nodes[{i}]")
        for j, decision in enumerate(as_list(as_dict(node).get("decisions"))):
            claim(as_dict(decision).get("id"), f"{node_label(node, i)}.decisions[{j}]")
    for i, edge in enumerate(edges):
        claim(as_dict(edge).get("id"), f"edges[{i}]")
    for i, step in enumerate(steps):
        claim(as_dict(step).get("id"), f"tour.steps[{i}]")
    for i, source in enumerate(sources):
        claim(as_dict(source).get("id"), f"sources[{i}]")

    # ---- lookups (first occurrence wins) ------------------------------
    node_by_id = {}
    for node in nodes:
        node_id = as_dict(node).get("id")
        if isinstance(node_id, str) and node_id not in node_by_id:
            node_by_id[node_id] = node
    source_by_id = {}
    for source in sources:
        source_id = as_dict(source).get("id")
        if isinstance(source_id, str) and source_id not in source_by_id:
            source_by_id[source_id] = source
    edge_ids = {as_dict(e).get("id") for e in edges if isinstance(as_dict(e).get("id"), str)}

    # ---- rule 3: parents, cycles, levels ------------------------------
    def parent_of(node_id):
        parent = as_dict(node_by_id.get(node_id)).get("parent")
        return parent if isinstance(parent, str) else None

    for i, node in enumerate(nodes):
        node = as_dict(node)
        parent = node.get("parent")
        if isinstance(parent, str) and parent not in node_by_id:
            report.error(node_label(node, i), f'parent "{parent}" does not exist')

    # Level: top level = 1. Nodes in (or below) a parent cycle get no level.
    level = {}
    in_cycle = set()
    for node_id in node_by_id:
        chain = []
        current = node_id
        reaches_cycle = False
        while current is not None and current not in level:
            if current in chain or current in in_cycle:
                if current in chain:
                    in_cycle.update(chain[chain.index(current):])
                reaches_cycle = True
                break
            chain.append(current)
            parent = parent_of(current)
            if parent is not None and parent not in node_by_id:
                parent = None  # reported above; counted as top level
            current = parent
        if reaches_cycle:
            continue
        base = level[current] if current is not None else 0
        for offset, member in enumerate(reversed(chain)):
            level[member] = base + offset + 1
    for node_id in sorted(in_cycle):
        report.error(f"node {node_id}", "parent chain forms a cycle")
    max_level = max(level.values(), default=0)
    if node_by_id and max_level < 3:
        report.error("nodes", f"the deepest level is {max_level}; the model must reach level 3")

    def ancestors(node_id):
        seen = []
        current = parent_of(node_id)
        while current is not None and current in node_by_id and current not in seen:
            seen.append(current)
            current = parent_of(current)
        return seen

    # ---- rule 4: edges ------------------------------------------------
    for i, edge in enumerate(edges):
        edge = as_dict(edge)
        where = f"edge {edge['id']}" if isinstance(edge.get("id"), str) else f"edges[{i}]"
        src, dst = edge.get("from"), edge.get("to")
        ok = True
        for end_name, end in (("from", src), ("to", dst)):
            if isinstance(end, str) and end not in node_by_id:
                report.error(where, f'{end_name} node "{end}" does not exist')
                ok = False
        if not (isinstance(src, str) and isinstance(dst, str)) or not ok:
            continue
        if src == dst:
            report.error(where, f'from and to are the same node "{src}"')
        elif src in ancestors(dst) or dst in ancestors(src):
            report.error(where, f'connects "{src}" and "{dst}", where one is an ancestor of the other')

    # ---- rule 5: tour steps -------------------------------------------
    for i, step in enumerate(steps):
        step = as_dict(step)
        where = f"tour.steps[{i}]"
        if isinstance(step.get("node"), str) and step["node"] not in node_by_id:
            report.error(where, f'node "{step["node"]}" does not exist')
        for edge_id in as_list(step.get("edges")):
            if isinstance(edge_id, str) and edge_id not in edge_ids:
                report.error(where, f'edge "{edge_id}" does not exist')

    # ---- rule 6: source references and cross-links --------------------
    holders = []  # (where, object that may have sources/code_refs)
    for i, node in enumerate(nodes):
        label = node_label(node, i)
        holders.append((label, as_dict(node)))
        for j, decision in enumerate(as_list(as_dict(node).get("decisions"))):
            holders.append((f"{label}.decisions[{j}]", as_dict(decision)))
    for i, edge in enumerate(edges):
        edge = as_dict(edge)
        holders.append((f"edge {edge['id']}" if isinstance(edge.get("id"), str) else f"edges[{i}]", edge))
    for i, step in enumerate(steps):
        holders.append((f"tour.steps[{i}]", as_dict(step)))

    for where, holder in holders:
        for source_id in as_list(holder.get("sources")):
            if isinstance(source_id, str) and source_id not in source_by_id:
                report.error(where, f'source "{source_id}" does not exist')

    for where, text in iter_prose(model, schema):
        for match in CROSS_LINK_RE.finditer(text):
            target = match.group(1)
            if target not in node_by_id:
                report.error(with_id(model, where), f'cross-link [[{target}]] names no existing node')

    # ---- rules 7 and 12: code refs at the pinned commit ----------------
    code_base = as_dict(model.get("code_base"))
    commit = code_base.get("commit")
    git = None
    if isinstance(commit, str) and commit:
        git = GitBlobs(repo, commit)
        if not git.commit_exists():
            report.error("code_base.commit", f'commit "{commit}" does not exist in {repo} '
                         "(is this a shallow clone? the validator needs a full clone)")
            git = None
    code_ref_count = 0
    for where, holder in holders:
        for k, code_ref in enumerate(as_list(holder.get("code_refs"))):
            code_ref_count += 1
            if git is None:
                continue
            check_code_ref(as_dict(code_ref), f"{where}.code_refs[{k}]", git, report)

    # ---- rules 8, 9, 11: node rules; rule 10: decisions ----------------
    def external_source_count(holder):
        count = 0
        for source_id in as_list(holder.get("sources")):
            source = as_dict(source_by_id.get(source_id)) if isinstance(source_id, str) else {}
            if source and source.get("kind") != "site-page":
                count += 1
        return count

    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue  # reported by the schema
        label = node_label(node, i)
        outside = node.get("outside_repo") is True
        external = external_source_count(node)
        top_level = node.get("parent") is None
        if is_blank(node.get("prose")):
            report.error(label, "prose is empty" + (" (a top-level node needs prose)" if top_level else ""))
        if not top_level:
            has_code = len(as_list(node.get("code_refs"))) > 0
            if not has_code and not (outside and external > 0):
                report.error(label, "a node below the top level needs a code ref of its own, "
                             "or outside_repo true and an external (non site-page) source")
        if outside and external == 0:
            report.error(label, "outside_repo is true but the node has no external (non site-page) source")
        for j, decision in enumerate(as_list(node.get("decisions"))):
            decision = as_dict(decision)
            if not as_list(decision.get("sources")) and not as_list(decision.get("code_refs")):
                report.error(f"{label}.decisions[{j}]", "a decision needs at least one source or code ref")

    # ---- rule 13: site-page URLs map to docs pages ---------------------
    for i, source in enumerate(sources):
        source = as_dict(source)
        if source.get("kind") != "site-page" or not isinstance(source.get("url"), str):
            continue
        where = f"source {source['id']}" if isinstance(source.get("id"), str) else f"sources[{i}]"
        match = SITE_PAGE_RE.match(source["url"])
        if not match:
            continue  # the schema pattern reports the malformed URL
        page = match.group(1)
        docs = Path(repo) / "docs"
        if not ((docs / f"{page}.md").is_file() or (docs / page / "index.md").is_file()):
            report.error(where, f'site page "{source["url"]}" has no docs/{page}.md or docs/{page}/index.md')

    return {
        "nodes": len(nodes),
        "edges": len(edges),
        "levels": max_level,
        "tour_steps": len(steps),
        "code_refs": code_ref_count,
        "sources": len(sources),
    }


def check_code_ref(code_ref, where, git, report):
    path, start, end, symbol = (code_ref.get(k) for k in ("path", "start", "end", "symbol"))
    if not isinstance(path, str) or not path:
        return  # reported by the schema
    lines = git.lines(path)
    if isinstance(lines, str):
        report.error(where, f'{path}: {lines}')
        return
    if not (isinstance(start, int) and isinstance(end, int)) or isinstance(start, bool) or isinstance(end, bool):
        return  # reported by the schema
    span = f"{path}:{start}-{end}"
    if not (1 <= start <= end <= len(lines)):
        report.error(where, f"{span}: need 1 <= start <= end <= {len(lines)} (the number of lines in the file)")
        return
    if end - start > MAX_CODE_REF_SPAN:
        report.error(where, f"{span}: the range spans {end - start} lines; end - start must be <= {MAX_CODE_REF_SPAN}")
    if isinstance(symbol, str) and symbol:
        text = "\n".join(lines[start - 1:end])
        if symbol not in text:
            report.error(where, f'{span}: symbol "{symbol}" does not appear in lines {start}-{end}')


# ---------------------------------------------------------------------------
# Layout: the map block, each top-level node's place and detail
# ---------------------------------------------------------------------------

# Keys whose values are identifiers, not text (iter_layout_text skips them).
LAYOUT_ID_KEYS = frozenset({
    "id", "node", "part", "step", "kind", "band", "line", "group", "d", "arrow", "anchor",
    "from", "to", "edges", "through", "ends", "highlight", "dots", "edge", "default_detail", "t",
})
COLUMN_NAME_RE = re.compile(r"^\$\.map\.columns\[\d+\]\.name$")
BAND_LABEL_RE = re.compile(r"^\$\.map\.bands\[\d+\]\.labels\[\d+\]\.text(\[\d+\])?$")
# A lane token in the d of a per-lane line: {y}, {y-28}, {y+28}.
LANE_TOKEN_RE = re.compile(r"\{y(?:([+-])(\d+(?:\.\d+)?))?\}")
PATH_NUMBER = r"-?\d+(?:\.\d+)?"
PATH_TOKEN_RE = re.compile(r"[MLHVC]|" + PATH_NUMBER)
PATH_SYNTAX_RE = re.compile(r"^\s*M(?:[\s,]*(?:[MLHVC]|" + PATH_NUMBER + r"))*\s*$")
BOX_KEY_RE = re.compile(r"^([a-z0-9]+(?:-[a-z0-9]+)*)(?:@(\d+))?$")
LADDER_SEGMENT_RE = re.compile(r"^lad-(\d+)$")
BORDER_TOLERANCE = 2.0


def iter_layout_text(model):
    """Yield (where, text, role) for every string leaf of the layout fields.

    The layout fields are the top-level "map" block and each node's "place"
    and "detail". Leaves under identifier keys (LAYOUT_ID_KEYS) and the keys
    and values of "sides" are skipped. role is "column" for a column name,
    "band" for a band label's text and "text" for everything else.
    """
    model = as_dict(model)

    def walk(value, where):
        if isinstance(value, dict):
            for key, sub in value.items():
                if key in LAYOUT_ID_KEYS or key == "sides":
                    continue
                yield from walk(sub, f"{where}.{key}")
        elif isinstance(value, list):
            for i, sub in enumerate(value):
                yield from walk(sub, f"{where}[{i}]")
        elif isinstance(value, str):
            role = "column" if COLUMN_NAME_RE.match(where) else "band" if BAND_LABEL_RE.match(where) else "text"
            yield where, value, role

    if "map" in model:
        yield from walk(model["map"], "$.map")
    for i, node in enumerate(as_list(model.get("nodes"))):
        node = as_dict(node)
        label = node_label(node, i)
        for key in ("place", "detail"):
            if key in node:
                yield from walk(node[key], f"{label}.{key}")


def number(value):
    """value if it is a real number (not a bool), else None."""
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def parse_path_d(d, lane_y=None):
    """Parse an absolute M/L/H/V/C path. Returns (segments, None) or (None, problem).

    lane_y: the lane's y for a per-lane line ({y}, {y-28}, {y+28} tokens);
    None for a shared line, where a lane token is a problem.
    Segments: ("L", p0, p1) or ("C", p0, c1, c2, p3) with points as (x, y)."""
    if not isinstance(d, str) or not d.strip():
        return None, "d is empty"
    if LANE_TOKEN_RE.search(d):
        if lane_y is None:
            return None, f"d {d!r} uses a lane token ({{y}}) but the line is not per_lane"

        def substitute(match):
            offset = float(match.group(2) or 0) * (-1 if match.group(1) == "-" else 1)
            return repr(lane_y + offset)
        d = LANE_TOKEN_RE.sub(substitute, d)
    if "{" in d or not PATH_SYNTAX_RE.match(d):
        return None, f"cannot parse d {d!r} (absolute M, L, H, V, C commands and numbers only)"
    tokens = PATH_TOKEN_RE.findall(d)
    segments, i, cur, command = [], 0, None, None
    arity = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6}
    while i < len(tokens):
        if tokens[i] in arity:
            command = tokens[i]
            i += 1
        if command is None or (command != "M" and cur is None):
            return None, f"cannot parse d {d!r}: it must start with M"
        if command == "M" and cur is not None:
            return None, f"cannot parse d {d!r}: a line is one path (one M)"
        raw = tokens[i:i + arity[command]]
        if len(raw) != arity[command] or any(t in arity for t in raw):
            return None, f"cannot parse d {d!r}: {command} needs {arity[command]} numbers"
        args = [float(t) for t in raw]
        i += arity[command]
        if command == "M":
            cur = (args[0], args[1])
            command = "L"
            continue
        if command == "L":
            seg = ("L", cur, (args[0], args[1]))
        elif command == "H":
            seg = ("L", cur, (args[0], cur[1]))
        elif command == "V":
            seg = ("L", cur, (cur[0], args[0]))
        else:
            seg = ("C", cur, (args[0], args[1]), (args[2], args[3]), (args[4], args[5]))
        segments.append(seg)
        cur = seg[-1]
    if not segments:
        return None, f"d {d!r} draws nothing"
    return segments, None


def sample_path(segments, step=1.0):
    """Points along the path, about `step` units apart (curves: 200 samples)."""
    points = [segments[0][1]]
    for seg in segments:
        if seg[0] == "L":
            (x0, y0), (x1, y1) = seg[1], seg[2]
            n = max(1, int(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 / step))
            points += [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(1, n + 1)]
        else:
            p0, c1, c2, p3 = seg[1:]
            for k in range(1, 201):
                t = k / 200
                u = 1 - t
                points.append(tuple(u ** 3 * p0[j] + 3 * u * u * t * c1[j] + 3 * u * t * t * c2[j] + t ** 3 * p3[j]
                                    for j in (0, 1)))
    return points


def on_border(point, rect, tol=BORDER_TOLERANCE):
    x, y = point
    x0, y0, x1, y1 = rect
    within_x = x0 - tol <= x <= x1 + tol
    within_y = y0 - tol <= y <= y1 + tol
    near_side = abs(x - x0) <= tol or abs(x - x1) <= tol
    near_top_bottom = abs(y - y0) <= tol or abs(y - y1) <= tol
    return (near_side and within_y) or (near_top_bottom and within_x)


def crosses_border_to_border(points, rect):
    """True if the path enters the rect through its border and leaves it again."""
    x0, y0, x1, y1 = rect
    inside = [x0 + 0.5 < x < x1 - 0.5 and y0 + 0.5 < y < y1 - 0.5 for x, y in points]
    k = 0
    while k < len(inside):
        if inside[k]:
            start = k
            while k < len(inside) and inside[k]:
                k += 1
            if start > 0 and k < len(inside):
                return True
        k += 1
    return False


def rects_overlap(a, b):
    return min(a[2], b[2]) - max(a[0], b[0]) > 0 and min(a[3], b[3]) - max(a[1], b[1]) > 0


def check_layout(model, report):
    """The layout checks. Returns the layout counts for the summary lines."""
    model = as_dict(model)
    nodes = [as_dict(n) for n in as_list(model.get("nodes"))]
    edges = [as_dict(e) for e in as_list(model.get("edges"))]
    steps = [as_dict(s) for s in as_list(as_dict(model.get("tour")).get("steps"))]
    node_by_id = {}
    for node in nodes:
        if isinstance(node.get("id"), str) and node["id"] not in node_by_id:
            node_by_id[node["id"]] = node
    edge_by_id = {e["id"]: e for e in edges if isinstance(e.get("id"), str)}
    label_of = {node_id: f"node {node_id}" for node_id in node_by_id}

    def parent_of(node_id):
        parent = node_by_id.get(node_id, {}).get("parent")
        return parent if isinstance(parent, str) and parent in node_by_id else None

    def top_of(node_id):
        seen = set()
        while parent_of(node_id) is not None and node_id not in seen:
            seen.add(node_id)
            node_id = parent_of(node_id)
        return node_id

    children = {}
    for node_id in node_by_id:
        if parent_of(node_id) is not None:
            children.setdefault(parent_of(node_id), []).append(node_id)

    def descendants(node_id):
        out, todo = [], list(children.get(node_id, []))
        while todo:
            current = todo.pop(0)
            if current in out:
                continue
            out.append(current)
            todo += children.get(current, [])
        return out

    tops = [n for n in node_by_id if node_by_id[n].get("parent") is None]
    top_set = set(tops)
    counts = {"placed": 0, "grids": 0, "grid_parts": 0, "layout_text": sum(1 for _ in iter_layout_text(model)),
              "map_edges_drawn": 0, "map_edges": 0}

    # place/detail only on top-level nodes
    for node_id, node in node_by_id.items():
        if node_id in top_set:
            continue
        for key in ("place", "detail"):
            if key in node:
                report.layout_error("E-GRID-FOREIGN", f"{label_of[node_id]}.{key}",
                                    f"only a top-level node may have {key}; this node's parent is \"{node.get('parent')}\"")

    m = model.get("map")
    if not isinstance(m, dict):
        report.layout_error("E-PLACE-MISSING", "$.map", "the model has no map block; no part can be placed")
        m = {}
    viewbox = as_dict(m.get("viewbox"))
    vb_w, vb_h = number(viewbox.get("w")) or 0, number(viewbox.get("h")) or 0
    columns = {}
    for col in as_list(m.get("columns")):
        col = as_dict(col)
        if number(col.get("n")) is not None and number(col.get("x")) is not None and number(col.get("w")) is not None:
            columns[col["n"]] = (col["x"], col["x"] + col["w"])
    bands = {}
    for band in as_list(m.get("bands")):
        band = as_dict(band)
        if isinstance(band.get("id"), str) and number(band.get("y")) is not None and number(band.get("h")) is not None:
            bands[band["id"]] = (band["y"], band["y"] + band["h"])
    lanes = as_dict(m.get("lanes"))
    lane_ys = [y for y in as_list(lanes.get("y")) if number(y) is not None]
    if number(lanes.get("count")) is not None and lanes.get("count") != len(lane_ys):
        report.layout_error("E-BOX-OUTSIDE-CELL", "$.map.lanes", f"count is {lanes.get('count')} but y lists {len(lane_ys)} lanes")

    # ---- place: boxes, cells -------------------------------------------
    boxes = {}        # box id -> {"part", "node", "per_lane", "rects": {lane or None: rect}}
    bad_place = set()
    cells = {}        # (column, band, slot) -> list of (lane, box id, part)
    all_rects = []    # (rect, box key, part)
    for part in tops:
        node = node_by_id[part]
        where = f"{label_of[part]}.place"
        place = node.get("place")
        if not isinstance(place, dict):
            report.layout_error("E-PLACE-MISSING", label_of[part], "top-level part has no place (no box on the map)")
            bad_place.add(part)
            continue
        part_boxes = as_list(place.get("boxes"))
        if not part_boxes:
            report.layout_error("E-PLACE-MISSING", where, "place has no boxes")
            bad_place.add(part)
        own = {part, *descendants(part)}
        for j, box in enumerate(part_boxes):
            box = as_dict(box)
            bwhere = f"{where}.boxes[{j}]"
            box_id = box.get("id")
            if not isinstance(box_id, str):
                bad_place.add(part)
                continue  # reported by the schema
            if box_id in boxes:
                report.layout_error("E-LINE-REF", bwhere, f'box id "{box_id}" is used twice on the map (also by part {boxes[box_id]["part"]})')
                bad_place.add(part)
                continue
            if box.get("node") not in own:
                report.layout_error("E-GRID-FOREIGN", bwhere, f'box node "{box.get("node")}" is not {part} or one of its descendants')
                bad_place.add(part)
            per_lane = box.get("per_lane") is True
            column, span, band, slot = box.get("column"), box.get("span", 1), box.get("band"), box.get("slot", 0)
            x, w, h = number(box.get("x")), number(box.get("w")), number(box.get("h"))
            y = number(box.get("y"))
            entry = {"part": part, "node": box.get("node"), "per_lane": per_lane, "rects": {}}
            boxes[box_id] = entry
            problems = []
            if column not in columns or number(span) is None or span < 1 or column + span - 1 not in columns:
                problems.append(f"column {column} with span {span} is not on the map's columns")
            if band not in bands:
                problems.append(f'band "{band}" is not one of the map\'s bands')
            if per_lane and "y" in box:
                problems.append("a per_lane box takes its y from the lanes; remove y")
            if not per_lane and y is None:
                problems.append("a box that is not per_lane needs y")
            if x is None or w is None or h is None:
                problems.append("x, w and h must be numbers")
            if problems:
                for problem in problems:
                    report.layout_error("E-BOX-OUTSIDE-CELL", bwhere, problem)
                bad_place.add(part)
                continue
            if per_lane:
                for lane, lane_y in enumerate(lane_ys):
                    entry["rects"][lane] = (x, lane_y - h / 2, x + w, lane_y + h / 2)
                subs = as_list(box.get("sub"))
                if subs and len(subs) not in (1, len(lane_ys)):
                    report.layout_error("E-BOX-OUTSIDE-CELL", bwhere,
                                        f"sub has {len(subs)} lines; a per_lane box has one line per lane ({len(lane_ys)}) or one for all")
                    bad_place.add(part)
            else:
                entry["rects"][None] = (x, y, x + w, y + h)
            cx0, cx1 = columns[column][0], columns[column + span - 1][1]
            by0, by1 = bands[band]
            for lane, rect in entry["rects"].items():
                key = box_id if lane is None else f"{box_id}@{lane}"
                if rect[0] < cx0 or rect[2] > cx1 or rect[1] < by0 or rect[3] > by1:
                    report.layout_error("E-BOX-OUTSIDE-CELL", bwhere,
                                        f"box {key} rect x {rect[0]:g}..{rect[2]:g}, y {rect[1]:g}..{rect[3]:g} is not inside "
                                        f"columns {column}..{column + span - 1} (x {cx0:g}..{cx1:g}) and band {band} (y {by0:g}..{by1:g})")
                    bad_place.add(part)
                all_rects.append((rect, key, part))
            title_x = number(box.get("title_x"))
            if title_x is not None and not (x <= title_x <= x + w):
                report.layout_error("E-BOX-OUTSIDE-CELL", bwhere, f"title_x {title_x:g} is outside the box (x {x:g}..{x + w:g})")
                bad_place.add(part)
            for c in range(column, column + span):
                cells.setdefault((c, band, slot), []).append((box_id, part))
    for (c, band, slot), occupants in cells.items():
        if len(occupants) > 1:
            names = ", ".join(f"{b} ({p})" for b, p in occupants)
            report.layout_error("E-CELL-SHARED", f"$.map cell column {c} band {band} slot {slot}",
                                f"boxes {names} share one cell")
            bad_place.update(p for _, p in occupants)
    for i in range(len(all_rects)):
        for j in range(i + 1, len(all_rects)):
            (ra, ka, pa), (rb, kb, pb) = all_rects[i], all_rects[j]
            if rects_overlap(ra, rb):
                report.layout_error("E-CELL-SHARED", f"$.map box {ka}", f"rect overlaps box {kb} ({pb})")
                bad_place.update((pa, pb))
    counts["placed"] += sum(1 for part in tops if part not in bad_place)

    # ---- detail grids --------------------------------------------------
    for part in tops:
        node = node_by_id[part]
        where = f"{label_of[part]}.detail"
        desc = descendants(part)
        detail = node.get("detail")
        if not desc:
            if detail is not None:
                report.layout_error("E-GRID-FOREIGN", where, "the part has no children, so it has no detail grid")
            continue
        counts["grid_parts"] += 1
        if not isinstance(detail, dict):
            report.layout_error("E-CHILD-MISSING", label_of[part],
                                f"part has children but no detail grid; missing: {', '.join(desc)}")
            continue
        errors_before = len(report.errors)
        ncols = detail.get("columns")
        ncols = ncols if number(ncols) is not None else 0
        seen = {}
        occupied = {}
        group_checks = []

        def take(row, col, span, item_where, name):
            if number(col) is None or number(span) is None or col < 0 or col + span > ncols:
                report.layout_error("E-BOX-OUTSIDE-CELL", item_where,
                                    f"{name} at col {col} span {span} is outside the grid's {ncols} columns")
                return
            for c in range(col, col + span):
                if (row, c) in occupied:
                    report.layout_error("E-CELL-SHARED", item_where,
                                        f"{name} and {occupied[(row, c)]} share row {row} col {c}")
                else:
                    occupied[(row, c)] = name

        def count(node_id, item_where):
            seen.setdefault(node_id, []).append(item_where)
            if node_id not in node_by_id or node_id not in desc:
                report.layout_error("E-GRID-FOREIGN", item_where, f'"{node_id}" is not a descendant of {part}')

        for r, row in enumerate(as_list(detail.get("rows"))):
            for k, item in enumerate(as_list(row)):
                item = as_dict(item)
                item_where = f"{where}.rows[{r}][{k}]"
                if "group" in item:
                    group = item.get("group")
                    count(group, item_where)
                    col, span = item.get("col"), item.get("span", 1)
                    take(r, col, span, item_where, f"group {group}")
                    expected = children.get(group, [])
                    if group in node_by_id and not expected:
                        report.layout_error("E-GRID-FOREIGN", item_where, f'group "{group}" has no children; list it as a node')
                    kid_cols = {}
                    for q, kid in enumerate(as_list(item.get("kids"))):
                        kid = as_dict(kid)
                        kid_id, kid_col = kid.get("node"), kid.get("col")
                        kid_where = f"{item_where}.kids[{q}]"
                        count(kid_id, kid_where)
                        if kid_id in node_by_id and kid_id not in expected:
                            report.layout_error("E-GRID-FOREIGN", kid_where, f'"{kid_id}" is not a child of group {group}')
                        if children.get(kid_id):
                            report.layout_error("E-GRID-FOREIGN", kid_where,
                                                f'"{kid_id}" has children of its own; groups do not nest')
                        if number(kid_col) is None or number(col) is None or number(span) is None \
                                or not (col <= kid_col <= col + span - 1):
                            report.layout_error("E-BOX-OUTSIDE-CELL", kid_where,
                                                f"kid col {kid_col} is outside the group's columns {col}..{(col or 0) + (span or 1) - 1}")
                        elif kid_col in kid_cols:
                            report.layout_error("E-CELL-SHARED", kid_where, f"{kid_id} and {kid_cols[kid_col]} share col {kid_col} of group {group}")
                        else:
                            kid_cols[kid_col] = kid_id
                    listed = [as_dict(kid).get("node") for kid in as_list(item.get("kids"))]
                    group_checks.append((item_where, group, [c for c in expected if c not in listed]))
                else:
                    node_id = item.get("node")
                    count(node_id, item_where)
                    take(r, item.get("col"), 1, item_where, f"node {node_id}")
                    if children.get(node_id):
                        report.layout_error("E-GRID-FOREIGN", item_where,
                                            f'"{node_id}" has children; list it as a group with its children as kids')
        for node_id, places in seen.items():
            if len(places) > 1:
                report.layout_error("E-CHILD-TWICE", places[1], f'"{node_id}" appears {len(places)} times in the grid of {part} '
                                    f"(first at {places[0]})")
        for item_where, group, not_listed in group_checks:
            for child in not_listed:
                if child in seen:  # placed elsewhere; a child missing everywhere is reported below
                    report.layout_error("E-CHILD-MISSING", item_where,
                                        f'child "{child}" of group {group} is not among its kids')
        missing = [d for d in desc if d not in seen]
        for d in missing:
            report.layout_error("E-CHILD-MISSING", where, f'descendant "{d}" has no cell in the grid')
        for other in as_dict(detail.get("sides")):
            if other not in top_set or other == part:
                report.layout_error("E-GRID-FOREIGN", f"{where}.sides", f'"{other}" is not another top-level part')
        counts["placed"] += sum(1 for d in desc if len(seen.get(d, [])) == 1)
        if len(report.errors) == errors_before:
            counts["grids"] += 1

    default_detail = m.get("default_detail")
    if "default_detail" in m and (default_detail not in top_set or not children.get(default_detail)):
        report.layout_error("E-GRID-FOREIGN", "$.map.default_detail", f'"{default_detail}" is not a top-level part with children')

    # ---- lines ---------------------------------------------------------
    def resolve_box(key, per_lane_line, where):
        """(box id, lane) for a through/ends key, or None after reporting."""
        match = BOX_KEY_RE.match(key) if isinstance(key, str) else None
        if not match or match.group(1) not in boxes:
            report.layout_error("E-LINE-REF", where, f'"{key}" names no box on the map')
            return None
        box_id, lane = match.group(1), match.group(2)
        box = boxes[box_id]
        if lane is not None:
            lane = int(lane)
            if not box["per_lane"]:
                report.layout_error("E-LINE-REF", where, f'"{key}": box {box_id} is not per_lane, so it takes no @lane')
                return None
            if per_lane_line:
                report.layout_error("E-LINE-REF", where, f'"{key}": in a per_lane line, name a per_lane box without @lane')
                return None
            if lane >= len(lane_ys):
                report.layout_error("E-LINE-REF", where, f'"{key}": there is no lane {lane}')
                return None
        elif box["per_lane"] and not per_lane_line:
            report.layout_error("E-LINE-REF", where, f'"{key}": in a shared line, name a per_lane box with @<lane>')
            return None
        return box_id, lane

    line_by_id = {}
    drawn_edges = set()
    for i, line in enumerate(as_list(m.get("lines"))):
        line = as_dict(line)
        line_id = line.get("id")
        where = f"$.map.lines[{i}]" + (f" ({line_id})" if isinstance(line_id, str) else "")
        if not isinstance(line_id, str):
            continue  # reported by the schema
        if line_id in line_by_id or LADDER_SEGMENT_RE.match(line_id):
            report.layout_error("E-LINE-REF", where, f'line id "{line_id}" is used twice (lad-<k> names ladder segments)')
            continue
        line_by_id[line_id] = line
        per_lane_line = line.get("per_lane") is True
        touched_parts = set()
        resolved = {}
        for key_name in ("through", "ends"):
            resolved[key_name] = []
            for key in as_list(line.get(key_name)):
                ref = resolve_box(key, per_lane_line, f"{where}.{key_name}")
                if ref is not None:
                    resolved[key_name].append((key, ref))
                    touched_parts.add(boxes[ref[0]]["part"])
        if len(as_list(line.get("ends"))) > 2:
            report.layout_error("E-LINE-ENDS", where, "a line has at most two ends")
        unreached = {}
        for edge_id in as_list(line.get("edges")):
            edge = edge_by_id.get(edge_id)
            if edge is None:
                report.layout_error("E-LINE-REF", f"{where}.edges", f'edge "{edge_id}" does not exist')
                continue
            drawn_edges.add(edge_id)
            if edge.get("kind") != line.get("kind"):
                report.layout_error("E-LINE-REF", f"{where}.edges", f'edge "{edge_id}" is {edge.get("kind")}, the line is {line.get("kind")}')
            for end in ("from", "to"):
                if edge.get(end) in node_by_id and top_of(edge[end]) not in touched_parts:
                    unreached.setdefault(top_of(edge[end]), []).append(edge_id)
        for other, ids in unreached.items():
            report.layout_error("E-MAP-EDGES", f"{where}.edges",
                                f"edges {', '.join(dict.fromkeys(ids))} reach part {other}, which has no box among the line's ends and through")
        lanes_to_check = list(enumerate(lane_ys)) if per_lane_line else [(None, None)]
        for lane, lane_y in lanes_to_check:
            segments, problem = parse_path_d(line.get("d"), lane_y)
            if problem:
                report.layout_error("E-LINE-ENDS", f"{where}.d", problem)
                break
            points = sample_path(segments)
            start, end = points[0], points[-1]
            lane_note = "" if lane is None else f" (lane {lane})"

            def rect_of(ref):
                box_id, ref_lane = ref
                return boxes[box_id]["rects"].get(lane if ref_lane is None and boxes[box_id]["per_lane"] else ref_lane)

            ends_rects = [(key, rect_of(ref)) for key, ref in resolved["ends"]]
            for name, point in (("start", start), ("end", end)):
                if not any(rect is not None and on_border(point, rect) for _, rect in ends_rects):
                    report.layout_error("E-LINE-ENDS", where,
                                        f"{name} point ({point[0]:g},{point[1]:g}){lane_note} is not on the border of an ends box "
                                        f"({', '.join(k for k, _ in ends_rects) or 'none listed'})")
            for key, rect in ends_rects:
                if rect is not None and not (on_border(start, rect) or on_border(end, rect)):
                    report.layout_error("E-LINE-ENDS", where, f"ends box {key}{lane_note} is not touched by either end point")
            for key, ref in resolved["through"]:
                rect = rect_of(ref)
                if rect is not None and not crosses_border_to_border(points, rect):
                    report.layout_error("E-LINE-THROUGH", where, f"through box {key}{lane_note} is not crossed border to border")

    for i, label in enumerate(as_list(m.get("labels"))):
        line_id = as_dict(label).get("line")
        if line_id not in line_by_id:
            report.layout_error("E-LINE-REF", f"$.map.labels[{i}]", f'line "{line_id}" does not exist')

    # ---- map edges: every cross-part pair drawn or omitted ----------------
    omitted_edges = set()
    for i, item in enumerate(as_list(m.get("omitted"))):
        item = as_dict(item)
        edge_id = item.get("edge")
        where = f"$.map.omitted[{i}]"
        edge = edge_by_id.get(edge_id)
        if edge is None:
            report.layout_error("E-LINE-REF", where, f'edge "{edge_id}" does not exist')
            continue
        if is_blank(item.get("reason")):
            report.layout_error("E-MAP-EDGES", where, f'omitted edge "{edge_id}" needs a reason')
            continue
        if edge_id in drawn_edges:
            report.layout_error("E-MAP-EDGES", where, f'edge "{edge_id}" is drawn by a map line and also listed as omitted')
        if edge.get("from") in node_by_id and edge.get("to") in node_by_id and top_of(edge["from"]) == top_of(edge["to"]):
            report.layout_error("E-MAP-EDGES", where, f'edge "{edge_id}" stays inside one part; only cross-part edges are omitted')
        omitted_edges.add(edge_id)
    pairs = {}
    for edge in edges:
        a, b = edge.get("from"), edge.get("to")
        if a not in node_by_id or b not in node_by_id or top_of(a) == top_of(b):
            continue
        pairs.setdefault((top_of(a), top_of(b)), []).append(edge.get("id"))
    counts["map_edges"] = len(pairs)
    for (a, b), ids in pairs.items():
        if any(e in drawn_edges or e in omitted_edges for e in ids):
            counts["map_edges_drawn"] += 1
        else:
            report.layout_error("E-MAP-EDGES", "$.map.lines",
                                f"no map line draws an edge from {a} to {b} and none is in map.omitted ({', '.join(ids)})")

    # ---- ladder ----------------------------------------------------------
    ladder = m.get("ladder")
    transitions = []
    ladder_part = None
    if isinstance(ladder, dict):
        states, transitions = as_list(ladder.get("states")), as_list(ladder.get("transitions"))
        if ladder.get("node") not in node_by_id:
            report.layout_error("E-LADDER", "$.map.ladder", f'node "{ladder.get("node")}" does not exist')
        else:
            ladder_part = top_of(ladder["node"])
        if len(states) != len(transitions) + 1:
            report.layout_error("E-LADDER", "$.map.ladder",
                                f"{len(states)} states need {len(states) - 1} transitions between them, not {len(transitions)}")
        for name, names in (("states", states), ("transitions", transitions)):
            if len(set(map(str, names))) != len(names) or any(is_blank(n) for n in names):
                report.layout_error("E-LADDER", f"$.map.ladder.{name}", "names must be non-empty and unique")
        x, dx, y = number(ladder.get("x")), number(ladder.get("dx")), number(ladder.get("y"))
        if None in (x, dx, y) or not (0 <= x and x + dx * (len(states) - 1) <= vb_w and 0 <= y <= vb_h):
            report.layout_error("E-LADDER", "$.map.ladder", "the stations (x + k*dx, y) must lie inside the viewbox")
    elif "ladder" in m:
        report.layout_error("E-LADDER", "$.map.ladder", "the ladder must be an object")

    # ---- tour on the map ---------------------------------------------------
    map_tour = as_list(m.get("tour"))
    if "map" in model and len(map_tour) != len(steps):
        report.layout_error("E-TOUR-MAP", "$.map.tour", f"{len(map_tour)} entries for {len(steps)} tour steps (one per step, same order)")
    for i, entry in enumerate(map_tour):
        entry = as_dict(entry)
        where = f"$.map.tour[{i}]"
        step = steps[i] if i < len(steps) else {}
        if entry.get("step") != step.get("id"):
            report.layout_error("E-TOUR-MAP", where, f'step "{entry.get("step")}" is not tour step {i + 1} ("{step.get("id")}")')
        step_part = top_of(step["node"]) if step.get("node") in node_by_id else None
        belongs = False
        for h in as_list(entry.get("highlight")):
            if isinstance(h, str) and h.startswith("box:"):
                box = boxes.get(h[4:])
                if box is None:
                    report.layout_error("E-TOUR-MAP", f"{where}.highlight", f'"{h}" names no box on the map')
                    continue
                belongs = belongs or box["part"] == step_part
            elif isinstance(h, str) and LADDER_SEGMENT_RE.match(h):
                k = int(LADDER_SEGMENT_RE.match(h).group(1))
                if k >= len(transitions):
                    report.layout_error("E-TOUR-MAP", f"{where}.highlight", f'"{h}": the ladder has no transition {k}')
                    continue
                belongs = belongs or ladder_part == step_part
            elif h in line_by_id:
                keys = as_list(line_by_id[h].get("through")) + as_list(line_by_id[h].get("ends"))
                parts = {boxes[BOX_KEY_RE.match(k).group(1)]["part"] for k in keys
                         if isinstance(k, str) and BOX_KEY_RE.match(k) and BOX_KEY_RE.match(k).group(1) in boxes}
                belongs = belongs or step_part in parts
            else:
                report.layout_error("E-TOUR-MAP", f"{where}.highlight", f'"{h}" names no line, box:<id> or lad-<k>')
        if step_part is not None and as_list(entry.get("highlight")) and not belongs:
            report.layout_error("E-TOUR-MAP", f"{where}.highlight",
                                f"nothing highlighted belongs to {step_part}, the part of the step's node {step.get('node')}")
        for k, token in enumerate(as_list(entry.get("tokens"))):
            token = as_dict(token)
            lane = token.get("lane")
            if lane is not None and (number(lane) is None or not 0 <= lane < len(lane_ys)):
                report.layout_error("E-TOUR-MAP", f"{where}.tokens[{k}]", f"lane {lane} does not exist")
            tx, ty = number(token.get("x")), number(token.get("y"))
            if tx is None or ty is None or not (0 <= tx <= vb_w and 0 <= ty <= vb_h):
                report.layout_error("E-TOUR-MAP", f"{where}.tokens[{k}]", "x, y must lie inside the viewbox")

    # ---- sequence ------------------------------------------------------------
    sequence = m.get("sequence")
    if isinstance(sequence, dict):
        lifelines = {}
        for i, life in enumerate(as_list(sequence.get("lifelines"))):
            life = as_dict(life)
            where = f"$.map.sequence.lifelines[{i}]"
            if life.get("id") in lifelines:
                report.layout_error("E-SEQUENCE", where, f'lifeline id "{life.get("id")}" is used twice')
            lifelines[life.get("id")] = life
            if life.get("part") not in top_set:
                report.layout_error("E-SEQUENCE", where, f'part "{life.get("part")}" is not a top-level part')
        rows = as_list(sequence.get("rows"))
        if len(rows) != len(steps):
            report.layout_error("E-SEQUENCE", "$.map.sequence.rows", f"{len(rows)} rows for {len(steps)} tour steps (one per step, same order)")
        for i, row in enumerate(rows):
            row = as_dict(row)
            where = f"$.map.sequence.rows[{i}]"
            step_id = steps[i].get("id") if i < len(steps) else None
            if row.get("step") != step_id:
                report.layout_error("E-SEQUENCE", where, f'step "{row.get("step")}" is not tour step {i + 1} ("{step_id}")')
            if row.get("from") != "start" and row.get("from") not in lifelines:
                report.layout_error("E-SEQUENCE", where, f'from "{row.get("from")}" is not a lifeline (or "start")')
            if row.get("to") not in lifelines:
                report.layout_error("E-SEQUENCE", where, f'to "{row.get("to")}" is not a lifeline')
            for dot in as_list(row.get("dots")):
                if dot not in lifelines:
                    report.layout_error("E-SEQUENCE", where, f'dot "{dot}" is not a lifeline')
    elif "sequence" in m:
        report.layout_error("E-SEQUENCE", "$.map.sequence", "the sequence must be an object")
    return counts


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def find_repo_root():
    result = subprocess.run(["git", "-C", str(TOOLS_DIR), "rev-parse", "--show-toplevel"],
                            capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip())
    return None


def summary_line(counts, n_errors):
    return ("nodes={nodes} edges={edges} levels={levels} tour_steps={tour_steps} "
            "code_refs={code_refs} sources={sources} placed={placed}/{nodes} grids={grids}/{grid_parts} "
            "errors={errors}").format(errors=n_errors, **counts)


def layout_summary_line(counts):
    return "layout_text={layout_text} map_edges={map_edges_drawn}/{map_edges}".format(**counts)


EMPTY_COUNTS = {"nodes": 0, "edges": 0, "levels": 0, "tour_steps": 0, "code_refs": 0, "sources": 0,
                "placed": 0, "grids": 0, "grid_parts": 0, "layout_text": 0, "map_edges_drawn": 0, "map_edges": 0}


def load_json(path, what):
    """Return (data, None) or (None, error message)."""
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        return None, None, f"cannot read the {what}: {exc}"
    try:
        return json.loads(raw.decode("utf-8")), raw, None
    except (ValueError, UnicodeDecodeError) as exc:
        return None, raw, f"{what} is not valid JSON: {exc}"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate the DAQ design model.")
    parser.add_argument("--model", default=str(DESIGN_DIR / "daq-model.json"))
    parser.add_argument("--schema", default=str(DESIGN_DIR / "daq-model.schema.json"))
    parser.add_argument("--repo", default=None,
                        help="repository root (default: the git checkout that contains this script)")
    parser.add_argument("--outline", action="store_true",
                        help="also print the model sha256, the top-level titles and the tour step titles")
    args = parser.parse_args(argv)

    repo = Path(args.repo) if args.repo else find_repo_root()
    if repo is None:
        print(f"ERROR: --repo: cannot find the git checkout from {TOOLS_DIR}; pass --repo")
        print(summary_line(EMPTY_COUNTS, 1))
        print(layout_summary_line(EMPTY_COUNTS))
        return 2

    schema, _, problem = load_json(args.schema, "schema")
    if problem:
        print(f"ERROR: {args.schema}: {problem}")
        print(summary_line(EMPTY_COUNTS, 1))
        print(layout_summary_line(EMPTY_COUNTS))
        return 2
    model, raw, problem = load_json(args.model, "model")
    if problem:
        print(f"ERROR: {args.model}: {problem}")
        print(summary_line(EMPTY_COUNTS, 1))
        print(layout_summary_line(EMPTY_COUNTS))
        return 2

    report = Report()
    check_schema(model, schema, report)
    counts = check_semantics(model, schema, repo, report)
    counts.update(check_layout(model, report))

    for line in report.errors:
        print(line)
    if args.outline:
        print(f"model_sha256={hashlib.sha256(raw).hexdigest()}")
        tops = [n for n in as_list(as_dict(model).get("nodes")) if as_dict(n).get("parent", "") is None]
        for i, node in enumerate(tops, 1):
            print(f"top: {i}. {as_dict(node).get('title')}")
        for i, step in enumerate(as_list(as_dict(as_dict(model).get("tour")).get("steps")), 1):
            print(f"tour: {i}. {as_dict(step).get('title')}")
    print(summary_line(counts, len(report.errors)))
    print(layout_summary_line(counts))
    return 0 if not report.errors else 1


if __name__ == "__main__":
    sys.exit(main())
