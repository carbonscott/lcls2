#!/usr/bin/env python3
"""Draw a seeded, stratified sample of prose sentences for an accuracy audit.

Every PROSE field attached to a node is split into sentences: the node's own
fields (summary, prose, dev_notes, code_ref notes), its decisions, the tour
steps (attached to their node) and the edges (attached to their "from"
node). Each sentence is tagged with the node id, level (1, 2, 3+),
outside_repo and field. The sample is stratified over the cells
(level x outside_repo): n is split across the cells in proportion to their
size, with at least 2 per non-empty cell, using random.Random(seed).
--reserve extra sentences are drawn the same way (for replacing sentences
that turn out not to be factual statements).

Usage:
    python docs/design/tools/sample_statements.py --seed S --n 40 [--reserve 20]
        [--model PATH] [--schema PATH] [--out sample.json] [--markdown sample.md]
"""

import argparse
import json
import random
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate import DESIGN_DIR, as_dict, as_list, iter_pattern, prose_field_patterns  # noqa: E402

# Abbreviations after which a period does not end a sentence.
ABBREVIATIONS = ("e.g.", "i.e.", "etc.", "vs.", "cf.", "approx.", "Fig.", "No.", "Dr.", "Mr.", "Ms.")


def plain_text(text, node_titles):
    """Strip prose markup to plain text; inline `code` keeps its backticks."""
    text = re.sub(r"\[\[([^\]|]+)\|([^\]]*)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]|]+)\]\]", lambda m: node_titles.get(m.group(1).strip(), m.group(1)), text)
    text = re.sub(r"\[([^\]]+)\]\(([^()\s]+)\)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text):
    """Split plain text into sentences.

    A sentence ends at '.', '!' or '?' followed by whitespace and an
    uppercase letter, a digit, a backtick or an opening quote/bracket. A
    period inside a word (run.xtc2, 1.6.1) is never followed by whitespace,
    so file names and versions are safe; known abbreviations (e.g., i.e.)
    and periods inside `code` do not end a sentence.
    """
    sentences = []
    start = 0
    in_code = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "`":
            in_code = not in_code
        elif ch in ".!?" and not in_code:
            rest = text[i + 1:]
            boundary = re.match(r"[\"')\]]*\s+(?=[A-Z0-9`\"'(\[])", rest)
            if boundary and not text[start:i + 1].endswith(ABBREVIATIONS):
                end = i + 1 + boundary.end()
                sentences.append(text[start:end].strip())
                start = end
                i = end
                continue
        i += 1
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return [s for s in sentences if s]


def level_cell(level):
    return "3+" if level >= 3 else str(level)


def collect(model, schema):
    """Return the list of tagged sentences, in model order."""
    nodes = [n for n in as_list(model.get("nodes")) if isinstance(n, dict) and isinstance(n.get("id"), str)]
    by_id = {n["id"]: n for n in nodes}
    titles = {n["id"]: n.get("title", n["id"]) for n in nodes}

    def level_of(node_id):
        level, seen, cur = 0, set(), node_id
        while cur in by_id and cur not in seen:
            seen.add(cur)
            level += 1
            cur = by_id[cur].get("parent")
        return level

    patterns = prose_field_patterns(schema)

    def prose_fields(obj, prefix):
        """(field, text) for every PROSE field of one model object.

        prefix is the schema path of the object, e.g. ("nodes", "*").
        """
        out = []
        for pattern in patterns:
            if pattern[:len(prefix)] != prefix:
                continue
            for where, value in iter_pattern(obj, pattern[len(prefix):]):
                if isinstance(value, str) and value.strip():
                    out.append((where[2:], value))  # drop the leading "$."
        return out

    items = []

    def add(node_id, field, text):
        node = by_id.get(node_id)
        if node is None:
            return
        for k, sentence in enumerate(split_sentences(plain_text(text, titles))):
            items.append({
                "id": f"{node_id}/{field}/{k + 1}",
                "node": node_id,
                "level": level_cell(level_of(node_id)),
                "outside_repo": node.get("outside_repo") is True,
                "field": field,
                "sentence": sentence,
            })

    for node in nodes:
        for field, text in prose_fields(node, ("nodes", "*")):
            add(node["id"], field, text)
    for edge in as_list(model.get("edges")):
        edge = as_dict(edge)
        for field, text in prose_fields(edge, ("edges", "*")):
            add(edge.get("from"), f"edge:{edge.get('id')}.{field}", text)
    for step in as_list(as_dict(model.get("tour")).get("steps")):
        step = as_dict(step)
        for field, text in prose_fields(step, ("tour", "steps", "*")):
            add(step.get("node"), f"step:{step.get('id')}.{field}", text)
    return items


def allocate(cell_sizes, n):
    """Split n over the cells: proportional to size, at least 2 per non-empty cell."""
    cells = [c for c, size in cell_sizes.items() if size > 0]
    alloc = {c: min(2, cell_sizes[c]) for c in cells}
    remaining = n - sum(alloc.values())
    total = sum(cell_sizes[c] for c in cells)
    if remaining > 0 and total > 0:
        # Largest remainder method on the proportional shares.
        shares = {c: n * cell_sizes[c] / total for c in cells}
        extra = {c: max(0, int(shares[c]) - alloc[c]) for c in cells}
        for c in cells:
            extra[c] = min(extra[c], cell_sizes[c] - alloc[c])
        while sum(extra.values()) > remaining:
            largest = max(cells, key=lambda c: (extra[c], c))
            extra[largest] -= 1
        for c in cells:
            alloc[c] += extra[c]
        remaining = n - sum(alloc.values())
        order = sorted(cells, key=lambda c: (-(shares[c] - int(shares[c])), c))
        while remaining > 0 and any(alloc[c] < cell_sizes[c] for c in cells):
            for c in order:
                if remaining > 0 and alloc[c] < cell_sizes[c]:
                    alloc[c] += 1
                    remaining -= 1
    return alloc


def cell_key(item):
    return f"level={item['level']} outside_repo={str(item['outside_repo']).lower()}"


def stratified(items, n, rng):
    cells = {}
    for item in items:
        cells.setdefault(cell_key(item), []).append(item)
    sizes = {c: len(v) for c, v in sorted(cells.items())}
    alloc = allocate(sizes, n)
    chosen = []
    for c in sorted(alloc):
        chosen.extend(rng.sample(cells[c], alloc[c]))
    return sorted(chosen, key=lambda x: x["id"]), sizes, alloc


def markdown_table(rows):
    lines = ["| # | id | level | outside_repo | field | sentence |", "|---|---|---|---|---|---|"]
    for k, r in enumerate(rows, 1):
        sentence = r["sentence"].replace("|", "\\|")
        lines.append(f"| {k} | `{r['id']}` | {r['level']} | {str(r['outside_repo']).lower()} | {r['field']} | {sentence} |")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Seeded stratified sample of prose sentences.")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--n", type=int, default=40)
    parser.add_argument("--reserve", type=int, default=20)
    parser.add_argument("--model", default=str(DESIGN_DIR / "daq-model.json"))
    parser.add_argument("--schema", default=str(DESIGN_DIR / "daq-model.schema.json"))
    parser.add_argument("--out", default=None, help="write the sample as JSON to this file")
    parser.add_argument("--markdown", default=None, help="also write the markdown table to this file")
    args = parser.parse_args(argv)

    model = json.loads(Path(args.model).read_text(encoding="utf-8"))
    schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    items = collect(as_dict(model), schema)

    rng = random.Random(args.seed)
    sample, sizes, alloc = stratified(items, args.n, rng)
    picked = {x["id"] for x in sample}
    rest = [x for x in items if x["id"] not in picked]
    reserve, _, reserve_alloc = stratified(rest, args.reserve, rng) if args.reserve > 0 else ([], {}, {})

    print(f"seed={args.seed} sentences={len(items)} n={len(sample)} reserve={len(reserve)}")
    for c, size in sizes.items():
        print(f"cell {c}: sentences={size} sampled={alloc.get(c, 0)} reserve={reserve_alloc.get(c, 0)}")
    print()
    print("## Sample")
    print(markdown_table(sample))
    print()
    print("## Reserve")
    print(markdown_table(reserve))

    result = {"seed": args.seed, "model": str(args.model), "sentences": len(items),
              "cells": {c: {"sentences": s, "sampled": alloc.get(c, 0), "reserve": reserve_alloc.get(c, 0)} for c, s in sizes.items()},
              "sample": sample, "reserve": reserve}
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if args.markdown:
        Path(args.markdown).write_text("## Sample\n\n" + markdown_table(sample) + "\n\n## Reserve\n\n" + markdown_table(reserve) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
