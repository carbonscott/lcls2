#!/bin/bash
# Show each finding of FINDINGS.md on the real xtcdata code (the oracle),
# next to what the Lean model says, and under valgrind where memory is involved.
#   ./findings.sh        needs build/oracle, build/oracle_O0 and the built xtcdiff
here=$(cd "$(dirname "$0")" && pwd)
oracle=$here/build/oracle
model=$here/../lean/.lake/build/bin/xtcdiff
fail=0
ulimit -c 0

show() {   # show <title> <case line> <expected oracle output> [valgrind pattern]
    local got mod
    got=$(echo "$2" | "$oracle" 2>/dev/null | grep -v '^\*\*\*')
    mod=$(echo "$2" | "$model")
    echo "== $1"
    echo "   case:   ${2:0:110}"
    echo "   model:  $mod"
    echo "   C++:    $got"
    if [ "$got" != "$3" ]; then echo "   UNEXPECTED: wanted '$3'"; fail=1; fi
    if [ -n "$4" ]; then
        local vg
        vg=$(echo "$2" | valgrind -q "$here/build/oracle_O0" 2>&1 >/dev/null | grep -m1 -E "$4")
        if [ -n "$vg" ]; then echo "   valgrind: ${vg#==*== }"; else echo "   UNEXPECTED: valgrind did not report '$4'"; fail=1; fi
    fi
}

show "X1 Damage::increase(UserDefined) changes nothing (Corrupted, for comparison, sets bit 3)" \
     "damage_inc_value 0 12" "0"
show "X1 comparison" "damage_inc_value 0 3" "8"
show "X2 iterate reads extent of a header that crosses bufEnd (28-byte buffer, bufEnd 28)" \
     "iterate 00000000000000001c00000000000000000001000c00000000000000 28 0" "ABORT" "Invalid read of size 4"
show "X3 process() gets an Xtc with extent 16 at offset 12 of a 24-byte buffer" \
     "iterate 000000000000000018000000000000000000010010000000 24 0" "ok 12:1:16"
show "X4 next() returns a second datagram from 5 stray bytes" \
     "fileiter 22222222111111110000000c00000000000000000c000000ffffffffff 64 5" "ok 12@24 12@29 end:eof"
got=$(echo "fileiter 0102030405 64 5" | valgrind -q "$here/build/oracle_O0" 2>&1 >/dev/null | grep -m1 "uninitialised")
echo "== X4 next() on a 5-byte file uses a header that was never written"
echo "   model:  $(echo "fileiter 0102030405 64 5" | "$model")"
if [ -n "$got" ]; then echo "   valgrind: ${got#==*== }"; else echo "   UNEXPECTED: no valgrind report"; fail=1; fi
show "X5 TypeId(\"Names_v3\") has version 0; TypeId(Names, 3) has version 3 (value id version)" \
     "typeid_str Names_v3" "4 4 0"
show "X5 comparison" "typeid_ctor 4 3" "12292 4 3"
show "X6 alloc(size = 2^64 - 4) passes the bounds check and shrinks extent 12 to 8 (offset extent)" \
     "alloc 12 18446744073709551612 64" "12 8"

echo "== X7 a chain of nested Parents overflows the stack (ulimit -s $(ulimit -s) kB)"
for d in 70000 100000; do
    python3 - "$d" > "$here/build/deep.txt" <<'PY'
import struct, sys
d = int(sys.argv[1])
b = b"".join(struct.pack("<IHHI", 0, 0, 0, 12 * (d - i)) for i in range(d))
print("iterate %s %d 0" % (b.hex(), len(b)))
PY
    ( "$oracle" < "$here/build/deep.txt" > "$here/build/deep.out" 2>/dev/null ) 2>/dev/null; rc=$?
    echo "   depth $d ($((d * 12)) byte buffer): oracle exit $rc"
    if [ "$d" = 100000 ] && [ "$rc" = 0 ]; then echo "   UNEXPECTED: no crash"; fail=1; fi
done
rm -f "$here/build/deep.txt" "$here/build/deep.out" core.* "$here"/build/core.*

[ $fail = 0 ] && echo "ALL FINDINGS REPRODUCED" || echo "SOME FINDING DID NOT REPRODUCE"
exit $fail
