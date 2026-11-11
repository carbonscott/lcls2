#!/usr/bin/env python3
"""Mutation check: does the differential test notice a wrong model?

    mutate.py [--n 20000] [--work DIR] [--only M1,M5]

Each mutant is one small wrong change to a copy of the Lean model.  The copy
is rebuilt (the model and xtcdiff only) and compared with the real code by
run.py.  A mutant is "caught" when run.py exits non-zero.  The proofs are then
built against the mutant too; the last column says whether any theorem stops
holding.  Exit status 0 only if every mutant is caught by the test.

Mutants marked valgrind differ from the model only in what they call undefined
behaviour, so they are run with run.py --valgrind.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LEAN = os.path.join(HERE, "..", "lean")

# id, file, text to replace, replacement, what it breaks, needs valgrind
MUTANTS = [
    ("M1", "Basic.lean", "⟨(((version <<< 12) &&& 0xf000) ||| type).toUInt16⟩",
     "⟨(((version <<< 12) &&& 0xe000) ||| type).toUInt16⟩", "TypeId version mask loses a bit", False),
    ("M2", "Basic.lean", "⟨d.value ||| (((1 : UInt32) <<< v) &&& 0x0fff).toUInt16⟩",
     "⟨d.value ||| (((1 : UInt32) <<< v) &&& 0x1fff).toUInt16⟩",
     "Damage::increase(UserDefined) sets bit 12 (what the callers expect)", False),
    ("M3", "Basic.lean", "  let cs := cs.dropWhile isCSpace\n", "", "strtoul does not skip white space", False),
    ("M4", "Basic.lean", '"EndStep", "Enable", "Disable"', '"EndStep", "Disable", "Enable"',
     "two transition names swapped", False),
    ("M5", "Xtc.lean", "  | some e => x ≥ e\n", "  | some e => x > e\n", "bufEnd check off by one", False),
    ("M6", "Xtc.lean", "    if rem ≤ 0 then .ok st ", "    if rem < 0 then .ok st ", "loop runs once more at remaining = 0", False),
    ("M7", "Xtc.lean", "(rem - ext.toInt32) st3", "(rem - ext.toInt32 + 1) st3", "remaining decreases by extent - 1", False),
    ("M8", "Xtc.lean", "  else if u16 m 4 &&& 8 ≠ 0 then .ok st  ", "  else if u16 m 4 &&& 4 ≠ 0 then .ok st  ",
     "root tests the wrong damage bit", False),
    ("M9", "Xtc.lean", "    else if buffer + size.toNat > e then .abort", "    else if buffer + size.toNat ≥ e then .abort",
     "alloc aborts on an exact fit", False),
    ("M10", "FileIter.lean", "    let extent := u32 hdr 20", "    let extent := u32 hdr 16", "extent read at the wrong offset", False),
    ("M11", "FileIter.lean", "(Xtc.sizeofPayload extent).toInt64.toUInt64", "(extent - 12).toUInt64",
     "int to size_t sign extension dropped", False),
    ("M12", "FileIter.lean", "    if payloadSize + 24 > maxDgramSize then", "    if payloadSize + 24 ≥ maxDgramSize then",
     "datagram that exactly fits is refused", False),
    ("M13", "FileIter.lean", "if i < n then u8 file (pos + i) else u8 hdr i", "if i < n then u8 file (pos + i) else 0",
     "stale header bytes replaced by zeros", False),
    ("M14", "Xtc.lean", "    else if m.size < x + 12 then .oob x ", "    else if m.size < x + 13 then .oob x ",
     "calls one more byte out of bounds than the code reads", True),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20000)
    ap.add_argument("--work", default="")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    work = a.work or tempfile.mkdtemp(prefix="xtcmut-")
    only = set(a.only.split(",")) if a.only else None
    rows = []
    for mid, fname, old, new, what, vg in MUTANTS:
        if only and mid not in only:
            continue
        d = os.path.join(work, mid)
        shutil.rmtree(d, ignore_errors=True)
        shutil.copytree(LEAN, d, symlinks=True)
        path = os.path.join(d, "XtcLean", fname)
        src = open(path, encoding="utf-8").read()
        if src.count(old) != 1:
            rows.append((mid, what, "NOT APPLIED", "-", "-"))
            continue
        open(path, "w", encoding="utf-8").write(src.replace(old, new))
        b = subprocess.run(["lake", "build", "xtcdiff"], cwd=d, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if b.returncode != 0:
            rows.append((mid, what, "BUILD FAILED", "-", "-"))
            continue
        cmd = [sys.executable, os.path.join(HERE, "run.py"), "--seeds", "1", "--n", str(a.n), "--min", "0", "--timeout", "300",
               "--model", os.path.join(d, ".lake", "build", "bin", "xtcdiff")]
        if vg:
            cmd += ["--valgrind", "--ub-sample", "400", "--ops", "iterate"]
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out = r.stdout.decode(errors="replace")
        m = re.search(r"disagreements: (\d+)", out)
        nm = re.search(r"near reads not flagged: (\d+)", out)
        detail = (m.group(1) + " disagreements") if m else out.strip().split("\n")[-1][:60]
        if "TIMEOUT" in out:
            detail = "model does not finish in 300 s"
        if vg and nm:
            detail += ", %s undefined-behaviour claims valgrind rejects" % nm.group(1)
        p = subprocess.run(["lake", "build", "XtcLean"], cwd=d, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        proofs = "a proof fails" if p.returncode != 0 else "proofs still pass"
        rows.append((mid, what, "caught" if r.returncode != 0 else "SURVIVED", detail, proofs))
        print("%-4s %-9s %-24s %s" % (mid, rows[-1][2], proofs, detail), flush=True)
    print("\n%-4s %-68s %-9s %-18s %s" % ("id", "wrong change to the model", "diff test", "proofs", "detail"))
    for mid, what, res, detail, proofs in rows:
        print("%-4s %-68s %-9s %-18s %s" % (mid, what, res, proofs, detail))
    bad = [r for r in rows if r[2] != "caught"]
    print("\n%d mutants, %d caught" % (len(rows), len(rows) - len(bad)))
    if not a.work:
        shutil.rmtree(work, ignore_errors=True)
    sys.exit(1 if bad or not rows else 0)


if __name__ == "__main__":
    main()
