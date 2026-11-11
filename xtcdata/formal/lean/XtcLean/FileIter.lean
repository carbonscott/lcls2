/-
Lean model of `XtcFileIterator::next` (src/XtcFileIterator.cc:21-54).

The file is a regular file held as a `ByteArray`; `read(fd, p, n)` returns
`min n (bytes left)` and advances the position.  A `count` of 2^63 or more
makes `read` return -1 (EFAULT on the test host: the range is not addressable);
the model reports that as the reason `err`.

Not modelled: `read` returning -1 on the header (I/O error, closed fd).  The
code treats -1 as success there, see FINDINGS.md, X4.

`Dgram` is 24 bytes (`#pragma pack(4)`, Dgram.hh:9): TimeStamp at 0, env at 8,
Xtc at 12, so `xtc.extent` is at 20.

Only the 24 header bytes of the iterator's buffer are modelled; payload bytes
are not looked at by `next`.
-/
import XtcLean.Xtc

namespace XtcLean

structure FileIterState where
  pos : Nat
  /-- the first 24 bytes of `_buf` -/
  hdr : ByteArray
  /-- whether all 24 header bytes have been written since `new char[]` -/
  init : Bool

inductive NextResult where
  /-- returned `&dg`: its extent, and the file position afterwards -/
  | dgram (extent : UInt32) (st : FileIterState)
  /-- returned 0.  `reason` is which path: "eof" (:24), "big" (:26-29),
  "err" (:37-40, the kernel refused a read count ≥ 2^63), "short" (:41-44). -/
  | null (reason : String)
  /-- used header bytes that were never written -/
  | uninit
  /-- read or wrote past `_buf` -/
  | oob

/-- Overwrite the first `n` bytes of `hdr` with file bytes from `pos`. -/
def overwritePrefix (file : Mem) (pos n : Nat) (hdr : ByteArray) : ByteArray :=
  ⟨((List.range 24).map fun i => if i < n then u8 file (pos + i) else u8 hdr i).toArray⟩

def FileIterState.start : FileIterState := ⟨0, ⟨(List.replicate 24 0).toArray⟩, false⟩

/-- XtcFileIterator.cc:21-54 -/
def fileNext (file : Mem) (maxDgramSize : UInt64) (s : FileIterState) : NextResult :=
  let n := min 24 (file.size - s.pos)
  -- :24 asks read() for 24 bytes into a `_buf` of maxDgramSize bytes.  With a smaller
  -- buffer the call is classed as out of bounds even at end of file, where the kernel
  -- writes nothing: the request itself names bytes past the buffer.
  if maxDgramSize < 24 then .oob
  else if n = 0 then .null "eof"                             -- :24
  else if n < 24 && !s.init then .uninit                     -- :25 reads stale bytes
  else
    let hdr := overwritePrefix file s.pos n s.hdr
    let pos := s.pos + n
    let extent := u32 hdr 20
    -- :25 `size_t payloadSize = dg.xtc.sizeofPayload()`: int converted to size_t
    let payloadSize : UInt64 := (Xtc.sizeofPayload extent).toInt64.toUInt64
    if payloadSize + 24 > maxDgramSize then .null "big"      -- :26-29, the sum wraps
    else if payloadSize = 0 then .dgram extent ⟨pos, hdr, true⟩   -- :32-33
    else if payloadSize ≥ 0x8000000000000000 then .null "err"  -- :36-40
    else if file.size - pos ≥ payloadSize.toNat then
      .dgram extent ⟨pos + payloadSize.toNat, hdr, true⟩      -- :45-49
    else .null "short"                                       -- :41-44 on the next pass

/-- The result of calling `next` until it returns 0, at most `maxDgrams` times. -/
structure FileRun where
  dgrams : Array (UInt32 × Nat)
  /-- why `next` returned 0, if it did -/
  ended : Option String
  bad : Option String

def fileRun (file : Mem) (maxDgramSize : UInt64) : Nat → FileIterState → FileRun → FileRun
  | 0, _, acc => acc
  | k + 1, s, acc =>
    match fileNext file maxDgramSize s with
    | .dgram e s' => fileRun file maxDgramSize k s' { acc with dgrams := acc.dgrams.push (e, s'.pos) }
    | .null reason => { acc with ended := some reason }
    | .uninit => { acc with bad := some "UNINIT" }
    | .oob => { acc with bad := some "OOB" }

end XtcLean
