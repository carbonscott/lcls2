/-
Lean model of `Xtc` and `XtcIterator::iterate`.

Source: `xtcdata/xtcdata/xtc/Xtc.hh`, `src/XtcIterator.cc` at agentify b3d052088.

Memory model.  A buffer is a `ByteArray`; its size is the size of the
allocation.  Pointers are byte offsets into it (natural numbers, so pointer
arithmetic does not wrap).  A read that touches a byte at or past the size is
undefined behaviour in C++; the model reports it as the outcome `oob`.
The byte order is little-endian (x86-64).

Layout (`#pragma pack(2)`, Xtc.hh:14): `Src src` at 0 (4 bytes), `Damage damage`
at 4 (2), `TypeId contains` at 6 (2), `uint32_t extent` at 8 (4); 12 bytes.
-/
import XtcLean.Basic

namespace XtcLean

abbrev Mem := ByteArray

def u8 (m : Mem) (o : Nat) : UInt8 := m.data.getD o 0

def u16 (m : Mem) (o : Nat) : UInt16 :=
  (u8 m o).toUInt16 ||| ((u8 m (o + 1)).toUInt16 <<< 8)

def u32 (m : Mem) (o : Nat) : UInt32 :=
  (u8 m o).toUInt32 ||| ((u8 m (o + 1)).toUInt32 <<< 8) |||
  ((u8 m (o + 2)).toUInt32 <<< 16) ||| ((u8 m (o + 3)).toUInt32 <<< 24)

/-- sizeof(Xtc) -/
def xtcSize : Nat := 12

namespace Xtc

/-- Xtc.hh:94-97 `int sizeofPayload() const { return extent - sizeof(Xtc); }`.
The subtraction is done in `size_t`; the conversion to `int` keeps the low
32 bits, so an extent below 12 gives a negative size. -/
def sizeofPayload (extent : UInt32) : Int32 := (extent - 12).toInt32

end Xtc

inductive AllocResult where
  /-- the offset of the new space and the new extent -/
  | ok (p : Nat) (extent : UInt32)
  /-- `abort()` -/
  | abort
  /-- `(char*)buffer + size` leaves the address space: undefined pointer arithmetic.
  The compiled code wraps at 2^64, the check on Xtc.hh:109 passes and the
  extent shrinks (see FINDINGS.md, X6). -/
  | ptrOverflow
  deriving DecidableEq, Repr

namespace Xtc

/-- Xtc.hh:106-116 `alloc(size, end)` for an Xtc at offset `off`.
`extent += size` truncates the `size_t` sum to 32 bits.

Offsets are natural numbers, so the model cannot say where a pointer sum wraps.
A `size` of 2^47 or more cannot fit in the x86-64 user address space; with a
buffer end given, the model classes that call as `ptrOverflow`. -/
def alloc (off : Nat) (extent : UInt32) (size : UInt64) (bufEnd : Option Nat) : AllocResult :=
  let buffer := off + extent.toNat
  match bufEnd with
  | some e =>
    if size ≥ 0x800000000000 then .ptrOverflow
    else if buffer + size.toNat > e then .abort
    else .ok buffer (extent + size.toUInt32)
  | none => .ok buffer (extent + size.toUInt32)

end Xtc

/-- One call of `process`: the offset of the Xtc, its `contains` word and its extent. -/
structure Visit where
  off : Nat
  contains : UInt16
  extent : UInt32
  deriving DecidableEq, Repr

/-- State of the walk: what `process` has seen, and the countdown after which
`process` returns 0 once (0 = never). -/
structure WalkState where
  visits : Array Visit
  left : Nat
  deriving DecidableEq, Repr

inductive Outcome where
  /-- `iterate` returned. -/
  | ok (st : WalkState)
  /-- the library called `abort()` -/
  | abort
  /-- a read past the end of the allocation, for the Xtc at this offset -/
  | oob (off : Nat)
  /-- the model ran out of fuel; `loop_ne_fuel` proves this never happens.
  (The call stack is not modelled: the compiled code recurses once per nested
  Parent and overflows its stack at about 10^5 levels, see FINDINGS.md, X7.) -/
  | fuel
  deriving DecidableEq, Repr

/-- XtcIterator.cc:48 `bufEnd && xtc >= (Xtc*)bufEnd` -/
def endHit (bufEnd : Option Nat) (x : Nat) : Bool :=
  match bufEnd with
  | some e => x ≥ e
  | none => false

/-- The `while (remaining > 0)` loop of XtcIterator.cc:47-60, with the walk
that the readers in the tree use as `process`: record the Xtc, and when its
type is `Parent` call `iterate` on it (XtcIterator.cc:40-45 inlined here).

`x` is the offset of the current Xtc, `rem` the signed 32-bit `remaining`.
Line 58, `remaining -= xtc->sizeofPayload() + sizeof(Xtc)`, is computed in
`size_t` and truncated to `int`; that equals `remaining - extent` mod 2^32. -/
def loop (m : Mem) (bufEnd : Option Nat) : Nat → Nat → Int32 → WalkState → Outcome
  | fuel, x, rem, st =>
    if rem ≤ 0 then .ok st                                   -- :47
    else if endHit bufEnd x then .abort                      -- :48-52
    else if m.size < x + 12 then .oob x                      -- :53 reads x+8..x+12
    else if u32 m (x + 8) < 12 then .abort                   -- :53-56
    else
      match fuel with
      | 0 => .fuel
      | fuel + 1 =>
        let ext := u32 m (x + 8)
        let contains := u16 m (x + 6)
        -- process(xtc, bufEnd)                              -- :57
        let st1 : WalkState := { st with visits := st.visits.push ⟨x, contains, ext⟩ }
        if st1.left = 1 then .ok { st1 with left := 0 }      -- process returned 0: break
        else
          let st2 : WalkState := { st1 with left := st1.left - 1 }
          let inner : Outcome :=
            if contains &&& 0x0fff = 0 then                  -- TypeId::Parent
              if u16 m (x + 4) &&& 8 ≠ 0 then .ok st2        -- :42 Damage::Corrupted
              else loop m bufEnd fuel (x + 12) (Xtc.sizeofPayload ext) st2   -- :44-45
            else .ok st2
          match inner with
          | .ok st3 => loop m bufEnd fuel (x + ext.toNat) (rem - ext.toInt32) st3  -- :58-59
          | o => o

/-- `XtcIterator::iterate(root, bufEnd)` for a root Xtc at offset 0 of `m`
(XtcIterator.cc:40-63).  `stopAfter` is the countdown described at `WalkState`. -/
def iterate (m : Mem) (bufEnd : Option Nat) (stopAfter : Nat) : Outcome :=
  let st : WalkState := { visits := #[], left := stopAfter }
  if m.size < 6 then .oob 0                                   -- :42 reads damage, bytes 4..5
  else if u16 m 4 &&& 8 ≠ 0 then .ok st                       -- :42
  else if m.size < 12 then .oob 0                             -- :45 reads extent, bytes 8..11
  else loop m bufEnd (m.size + 1) 12 (Xtc.sizeofPayload (u32 m 8)) st   -- :44-45

end XtcLean
