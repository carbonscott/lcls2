# Formal model of the XTC2 format (pilot)

A Lean 4 model of the container layer of `xtcdata/xtcdata/xtc`, proofs about
it, and a differential test that ties the model to the real C++.

The method follows https://github.com/Broyojo/python-formalization:

1. **Copy.** Each C++ function is rewritten in Lean, keeping integer widths,
   masks, truncations and branch order. Every definition cites its source line.
2. **Test.** The Lean model and the real code run on the same generated
   inputs and must print the same result.
3. **Prove or refute.** Properties are stated over all inputs. A false one is
   kept as a checked counterexample, not weakened.
4. **Review.** An agent that did not write the model checks it against the
   source and tries to break it.

A proof speaks about the model only. Step 2 is what connects it to the code.

## Scope

Modelled: `TypeId`, `Damage`, `Src`, `NamesId`, `TimeStamp` (integer part),
the transition `env` word of `Dgram`, `Xtc::sizeofPayload`, `Xtc::alloc`,
`XtcIterator::iterate`, `XtcFileIterator::next`. That is 40 functions;
`coverage/functions.tsv` lists each with its model and theorems, and lists
what is not modelled (the self-describing layer in `ShapesData.hh` and
`DescData.hh` is the next target).

Not modelled anywhere: threads, floating point, the call stack, `read`
errors other than a refused count.

## Layout

```
lean/XtcLean/Basic.lean     TypeId, Damage, Src, NamesId, TimeStamp, env word
lean/XtcLean/Xtc.lean       memory model, Xtc, XtcIterator::iterate
lean/XtcLean/FileIter.lean  XtcFileIterator::next
lean/XtcLean/Props.lean     theorems about the scalar classes, alloc, termination
lean/XtcLean/Safety.lean    memory-safety theorems and counterexamples
lean/DiffMain.lean          xtcdiff, the Lean side of the differential test
lean/Audit.lean             one `#print axioms` per theorem
difftest/oracle.cc          runs the real xtcdata code on a case line
difftest/gen.py             case generator
difftest/run.py             comparator, with optional valgrind checks
difftest/mutate.py          mutation check of the differential test
difftest/findings.sh        shows each finding on the real code
coverage/functions.tsv      function inventory
FINDINGS.md                 what the work found in the C++
env.sh, audit.sh
```

## Running it (S3DF, RHEL 8)

```
export ELAN_HOME=/path/to/elan   # only if lake is not on PATH
. ./env.sh
(cd lean && lake build)          # model, proofs, xtcdiff
./difftest/build.sh              # oracle, from the tree's own sources
./audit.sh                       # axioms per theorem; fails on sorry
python3 difftest/run.py --seeds 1 2 3 --n 80000 --valgrind
python3 difftest/mutate.py       # 14 wrong models; each must be caught
./difftest/findings.sh           # each finding, on the real code
```

`run.py` exits 0 only if no case disagrees, every op has at least 50,000
agreeing cases, and the valgrind checks pass.

## Status at sim-main 1332c994d

Measured on sdfiana025 (RHEL 8, gcc 8.5, Lean 4.35.0, valgrind 3.22.0).

| What | Result |
|---|---|
| Functions modelled | 40 (`coverage/functions.tsv`) |
| Theorems | 39, no `sorry`; 17 checked by the kernel alone, 22 also through `bv_decide` |
| Differential test, 3 seeds x 80,000 cases per op | 4,170,216 cases compared, 0 disagreements |
| Cases the model calls undefined, not compared | 106,476 |
| valgrind, cases the model calls defined | 125,164 iterate and fileiter cases, 0 errors |
| valgrind, sample of cases the model calls undefined | 2,000 of 2,000 flagged |
| Mutation check (`difftest/mutate.py`) | 14 wrong models, 14 caught by the test (12 by a disagreement or a valgrind check, 2 because the wrong model does not finish in 300 s); 7 of them also break a proof |
| Findings in the C++ | 7, plus smaller items (`FINDINGS.md`) |

## How the memory claims are checked

The model classes an input as undefined behaviour when the C++ would read
outside the buffer (`OOB`), use bytes never written (`UNINIT`), or form a
pointer outside the address space (`PTROVF`). Those cases are not compared.
Two valgrind checks test the classification itself:

- **clean**: the oracle under valgrind must report no error on every
  iterate and fileiter case the model calls defined;
- **ub**: a sample of the cases the model calls undefined runs under
  valgrind one by one. An out-of-bounds read within valgrind's 16-byte red
  zone must be flagged.

## Limits

- The differential test covers the inputs the generator makes. The review
  found three changes to the model that the first version of the test did not
  catch; the generator and comparator were extended for each
  (white space in `TypeId` strings, the reason `next()` returns 0, more
  undefined-behaviour samples), and `difftest/mutate.py` now checks 14 such
  changes on every run.
- `bv_decide` proofs (marked in `audit.sh` output) trust the Lean compiler in
  addition to the kernel. The memory-safety theorems about `iterate` do not
  use it.
- There is no theorem yet that `iterate` on a well-formed tree visits exactly
  its nodes in order. That needs an encoder for trees and is the main open
  property.
- The findings were shown on the library through the oracle. None was
  reproduced in a running DAQ or in psana.
