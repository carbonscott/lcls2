#!/bin/bash
# Build the oracle from the tree's own xtcdata sources (no install needed).
#   ./build.sh [out-dir]      -> <out>/oracle (-O1), <out>/oracle_O0, and <out>/oracle_asan if libasan exists
# oracle_O0 is for the valgrind check of undefined cases: at -O1 gcc narrows some reads
# (it tests one byte of the 16-bit damage word), which hides a source-level out-of-bounds read.
set -e
here=$(cd "$(dirname "$0")" && pwd)
xtc=$(cd "$here/../.." && pwd)            # .../xtcdata
out=${1:-$here/build}
mkdir -p "$out"
srcs="$xtc/xtcdata/xtc/src/XtcIterator.cc $xtc/xtcdata/xtc/src/XtcFileIterator.cc
      $xtc/xtcdata/xtc/src/TypeId.cc $xtc/xtcdata/xtc/src/TimeStamp.cc
      $xtc/xtcdata/xtc/src/TransitionId.cc $xtc/xtcdata/xtc/src/Level.cc"
g++ -std=c++17 -O1 -g -I"$xtc" "$here/oracle.cc" $srcs -o "$out/oracle"
g++ -std=c++17 -O0 -g -I"$xtc" "$here/oracle.cc" $srcs -o "$out/oracle_O0"
g++ -std=c++17 -O1 -g -fsanitize=address -fno-omit-frame-pointer -I"$xtc" \
    "$here/oracle.cc" $srcs -o "$out/oracle_asan" 2>"$out/asan-build.log" \
  || echo "note: no AddressSanitizer build (see $out/asan-build.log)"
ls -l "$out"
