#!/bin/bash
# Check every registered theorem and report the axioms it rests on.
#   ./audit.sh        exit 0 only if nothing depends on sorryAx
# "kernel" = only propext / Classical.choice / Quot.sound (checked by Lean's kernel alone).
# "bv_decide" = also a `<theorem>._native.bv_decide.ax_*` axiom (or Lean.ofReduceBool):
#   the bit-vector decision procedure's SAT certificate is checked by compiled Lean code,
#   so these also trust the Lean compiler.
cd "$(dirname "$0")" && . ./env.sh && cd lean || exit 2
lake build >/dev/null || { echo "build failed"; exit 2; }
lake env lean Audit.lean > .lake/audit.out 2>&1 || { cat .lake/audit.out; exit 2; }
python3 - <<'PY'
import re, sys
t = open(".lake/audit.out").read()
items = re.findall(r"'([^']+)' (does not depend on any axioms|depends on axioms: \[([^\]]*)\])", t)
bad = 0
kern = bvd = 0
for name, _, ax in items:
    ax = [a.strip() for a in ax.replace("\n", " ").split(",") if a.strip()]
    if any("sorry" in a for a in ax):
        cls = "SORRY"; bad += 1
    elif any(a in ("Lean.ofReduceBool", "Lean.trustCompiler") or "._native.bv_decide." in a for a in ax):
        cls = "bv_decide"; bvd += 1
    elif all(a in ("propext", "Classical.choice", "Quot.sound") for a in ax):  # includes no axioms
        cls = "kernel"; kern += 1
    else:
        cls = "OTHER:" + ",".join(ax); bad += 1
    print("%-10s %s" % (cls, name))
print("\n%d theorems: %d kernel-only, %d via bv_decide, %d bad" % (len(items), kern, bvd, bad))
sys.exit(1 if bad or not items else 0)
PY
