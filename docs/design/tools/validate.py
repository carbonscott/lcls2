#!/usr/bin/env python3
"""Validate the DAQ design model (docs/design/daq-model.json).

Checks the model against the JSON Schema (draft 2020-12) and then runs the
semantic checks (ids, parents, edges, tour, sources, cross-links, code
references at the pinned commit, node rules). Every problem is printed on
its own line as

    ERROR: <where>: <what>

followed by exactly one summary line:

    nodes=N edges=E levels=L tour_steps=T code_refs=R sources=S errors=K

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
            "code_refs={code_refs} sources={sources} errors={errors}").format(errors=n_errors, **counts)


EMPTY_COUNTS = {"nodes": 0, "edges": 0, "levels": 0, "tour_steps": 0, "code_refs": 0, "sources": 0}


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
        return 2

    schema, _, problem = load_json(args.schema, "schema")
    if problem:
        print(f"ERROR: {args.schema}: {problem}")
        print(summary_line(EMPTY_COUNTS, 1))
        return 2
    model, raw, problem = load_json(args.model, "model")
    if problem:
        print(f"ERROR: {args.model}: {problem}")
        print(summary_line(EMPTY_COUNTS, 1))
        return 2

    report = Report()
    check_schema(model, schema, report)
    counts = check_semantics(model, schema, repo, report)

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
    return 0 if not report.errors else 1


if __name__ == "__main__":
    sys.exit(main())
