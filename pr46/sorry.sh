#!/bin/bash
# Negative control for audit.sh: a copy of xtcdata/formal with one false theorem
# "proved" by sorry must fail the audit.   usage: sorry.sh <formal dir> <scratch dir>
src=$1; dst=$2
mkdir -p "$dst" && cp -r "$src" "$dst/formal" || exit 2
cat >> "$dst/formal/lean/Audit.lean" <<'LEAN'

theorem bogus_claim : (1 : Nat) = 2 := by sorry
#print axioms bogus_claim
LEAN
echo "added to the copy's Audit.lean:"; tail -2 "$dst/formal/lean/Audit.lean"
"$dst/formal/audit.sh" | tail -4
echo "AUDIT_EXIT=${PIPESTATUS[0]}"
