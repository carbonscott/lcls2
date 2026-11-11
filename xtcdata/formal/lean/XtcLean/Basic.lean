/-
Lean model of the scalar header classes of the XTC2 format.

Source: lcls2 `xtcdata/xtcdata/xtc/` at agentify b3d052088.  Every definition
cites the file and line it mirrors.  The model keeps the C++ integer widths,
masks and truncations as written; it does not tidy them.

Preconditions shared by all definitions that take an enum argument: the
argument lies in the range of its C++ enumeration (passing any other value is
undefined behaviour in C++17, so there is nothing to model).
  TypeId::Type        0..7      Damage::Value         0..15
  Level::Type         0..3      TransitionBase::Type  0..3
  TransitionId::Value 0..15

Assumption about the compiler.  The library itself casts file values to enums
outside those ranges: `TypeId::id()` casts `_value & 0xfff` to `Type`, and
`Src::level()` casts a 4-bit field to `Level::Type`.  The model treats these
casts as the plain integer, which is what gcc on x86-64 does.

Not modelled (see coverage/functions.tsv): `TimeStamp(double)`,
`TimeStamp(const timespec&)`, `asDouble`, the `Xtc` constructors and
`operator new` overloads, `XtcIterator()`'s uninitialised members.
-/
namespace XtcLean

/-! ## TypeId (TypeId.hh, src/TypeId.cc) -/

/-- TypeId.hh:34 `uint16_t _value` -/
structure TypeId where
  value : UInt16
  deriving DecidableEq, Repr

namespace TypeId

/-- TypeId.hh:39-42 `_value(((version << VersionBitShift) & VersionBitMask) | type)`.
The `unsigned` result is truncated to `uint16_t`. -/
def ofTypeVersion (type version : UInt32) : TypeId :=
  ⟨(((version <<< 12) &&& 0xf000) ||| type).toUInt16⟩

/-- TypeId.hh:61-65 `_value & TypeBitMask` -/
def id (t : TypeId) : UInt32 := (t.value &&& 0x0fff).toUInt32

/-- TypeId.hh:55-59 `(_value & VersionBitMask) >> VersionBitShift` -/
def version (t : TypeId) : UInt32 := ((t.value &&& 0xf000) >>> 12).toUInt32

/-- src/TypeId.cc:25 -/
def names : List String := ["Parent", "ShapesData", "Shapes", "Data", "Names"]

/-- TypeId::NumberOf (TypeId.hh:16) -/
def numberOf : UInt32 := 5

/-- src/TypeId.cc:23-29.  `_names` has no null entry, so "-Unnamed-" is unreachable. -/
def name (type : UInt32) : String :=
  if type < numberOf then names.getD type.toNat "-Invalid-" else "-Invalid-"

/-- C `isspace` in the "C" locale. -/
def isCSpace (c : Char) : Bool :=
  c == ' ' || c == '\t' || c == '\n' || c == '\x0b' || c == '\x0c' || c == '\r'

/-- Whether `strtoul(p, &e, 10)` consumes at least one character and stops at
the end of the string, i.e. the negation of TypeId.cc:15
`e == token + 2 || *e != 0`.  strtoul skips white space, takes an optional
sign and then decimal digits; with no digit it consumes nothing. -/
def strtoulConsumesAll (cs : List Char) : Bool :=
  let cs := cs.dropWhile isCSpace
  let cs := match cs with
    | '+' :: r => r
    | '-' :: r => r
    | r => r
  !cs.isEmpty && cs.all Char.isDigit

/-- `strrchr(s, '_')` as a split: the text before and after the last '_'. -/
def splitLastUnderscore (cs : List Char) : Option (List Char × List Char) :=
  match cs.reverse.span (· != '_') with
  | (afterRev, _ :: beforeRev) => some (beforeRev.reverse, afterRev.reverse)
  | (_, []) => none

/-- src/TypeId.cc:8-21 `TypeId(const char*)`.

Line 19 stores `(vsn << 16) | i` into the 16-bit `_value`.  The shift is 16,
not `VersionBitShift` (12), so every bit of `vsn` is truncated away and the
stored value is `i`.  The model keeps that. -/
def ofString (s : String) : TypeId :=
  match splitLastUnderscore s.toList with
  | some (pre, 'v' :: digits) =>
    if strtoulConsumesAll digits then
      -- the loop over i assigns on every match; names are distinct, so at most one
      match (List.range 5).find? (fun i => (names.getD i "").toList == pre) with
      | some i => ⟨i.toUInt16⟩
      | none => ⟨5⟩
    else ⟨5⟩
  | _ => ⟨5⟩

end TypeId

/-! ## Damage (Damage.hh) -/

/-- Damage.hh:59 `uint16_t _damage` -/
structure Damage where
  value : UInt16
  deriving DecidableEq, Repr

namespace Damage

/-- Damage.hh:36-39 `_damage |= ((1 << v) & ValueBitMask)`, `v` a `Damage::Value`. -/
def increaseValue (d : Damage) (v : UInt32) : Damage :=
  ⟨d.value ||| (((1 : UInt32) <<< v) &&& 0x0fff).toUInt16⟩

/-- Damage.hh:40-43 `_damage |= v & ValueBitMask` -/
def increaseBits (d : Damage) (v : UInt16) : Damage :=
  ⟨d.value ||| (v &&& 0x0fff)⟩

/-- Damage.hh:44-47 -/
def bits (d : Damage) : UInt16 := d.value &&& 0x0fff

/-- Damage.hh:48-51 `_damage >> UserBitShift` -/
def userBits (d : Damage) : UInt16 := d.value >>> 12

/-- Damage.hh:52-56 `_damage &= ValueBitMask; _damage |= (v << UserBitShift)` -/
def setUserBits (d : Damage) (v : UInt16) : Damage :=
  ⟨(d.value &&& (0x0fff : UInt16)) ||| (v <<< (12 : UInt16))⟩

/-- Damage.hh:12-21 -/
def truncated : UInt32 := 0
def corrupted : UInt32 := 3
def timedOut : UInt32 := 6
def userDefined : UInt32 := 12

end Damage

/-! ## Src and NamesId (Src.hh, NamesId.hh) -/

/-- Src.hh:27 `uint32_t _value` -/
structure Src where
  value : UInt32
  deriving DecidableEq, Repr

namespace Src

/-- Src.hh:20-21 `(value&ValueBitMask)|((level<<LevelBitShift)&LevelBitMask)` -/
def ofValueLevel (value level : UInt32) : Src :=
  ⟨(value &&& (0x0fffffff : UInt32)) ||| ((level <<< (28 : UInt32)) &&& (0xf0000000 : UInt32))⟩

/-- Src.hh:23 -/
def level (s : Src) : UInt32 := (s.value &&& 0xf0000000) >>> 28

/-- Src.hh:24 -/
def val (s : Src) : UInt32 := s.value &&& 0x0fffffff

end Src

namespace NamesId

/-- NamesId::NumberOf (NamesId.hh:26): the size of the NamesLookup array. -/
def numberOf : UInt32 := 0x100000

/-- NamesId.hh:30-39.  `none` is `abort()`. -/
def make (nodeId namesId : UInt32) : Option Src :=
  if nodeId &&& 0xfff != nodeId then none
  else if namesId &&& 0xff != namesId then none
  else some (Src.ofValueLevel (((nodeId &&& 0xfff) <<< 8) ||| (namesId &&& 0xff)) 0)

/-- NamesId.hh:43 -/
def nodeId (s : Src) : UInt32 := (s.value >>> 8) &&& 0xfff

/-- NamesId.hh:44 -/
def namesId (s : Src) : UInt32 := s.value &&& 0xff

end NamesId

/-! ## TimeStamp (TimeStamp.hh).  The `double` constructor and `asDouble` are not modelled. -/

/-- TimeStamp.hh:33-34 -/
structure TimeStamp where
  low : UInt32
  high : UInt32
  deriving DecidableEq, Repr

namespace TimeStamp

/-- TimeStamp.hh:58-63 -/
def ofUInt64 (stamp : UInt64) : TimeStamp :=
  ⟨(stamp &&& 0xffffffff).toUInt32, ((stamp >>> 32) &&& 0xffffffff).toUInt32⟩

/-- TimeStamp.hh:53-56 -/
def ofSecNsec (sec nsec : UInt32) : TimeStamp := ⟨nsec, sec⟩

/-- TimeStamp.hh:65-69 -/
def value (t : TimeStamp) : UInt64 := (t.high.toUInt64 <<< 32) ||| t.low.toUInt64

/-- TimeStamp.hh:71-78.  Both results are truncated to 32 bits. -/
def fromNs (nsec : UInt64) : TimeStamp :=
  ⟨(nsec % 1000000000).toUInt32, (nsec / 1000000000).toUInt32⟩

/-- TimeStamp.hh:80-84 -/
def toNs (t : TimeStamp) : UInt64 := t.high.toUInt64 * 1000000000 + t.low.toUInt64

/-- TimeStamp.hh:98-102 -/
def isZero (t : TimeStamp) : Bool := t.low == 0 && t.high == 0

/-- TimeStamp.hh:118-122 -/
def gt (a b : TimeStamp) : Bool := a.high > b.high || (a.high == b.high && a.low > b.low)

/-- TimeStamp.hh:124-128 -/
def eq (a b : TimeStamp) : Bool := a.high == b.high && a.low == b.low

end TimeStamp

/-! ## Transition env word (Dgram.hh) -/

namespace Env

/-- Dgram.hh:21 `env((type_<<28)|(tid_<<24)|(env_&0xffffff))` -/
def make (type tid env : UInt32) : UInt32 :=
  (type <<< 28) ||| (tid <<< 24) ||| (env &&& 0xffffff)

/-- Dgram.hh:23 (returns `uint16_t`) -/
def readoutGroups (env : UInt32) : UInt32 := env &&& 0xffff
/-- Dgram.hh:26 -/
def keepRaw (env : UInt32) : Bool := (env >>> 22) &&& 1 != 0
/-- Dgram.hh:39 -/
def control (env : UInt32) : UInt32 := (env >>> 24) &&& 0xff
/-- Dgram.hh:40 -/
def service (env : UInt32) : UInt32 := control env &&& 0xf
/-- Dgram.hh:41 -/
def type (env : UInt32) : UInt32 := (control env >>> 4) &&& 0x3
/-- TransitionId::L1Accept (TransitionId.hh:29) -/
def l1Accept : UInt32 := 12
/-- Dgram.hh:42 -/
def isEvent (env : UInt32) : Bool := service env == l1Accept
/-- Dgram.hh:43 -/
def isExtended (env : UInt32) : Bool := ((env >>> 16) &&& 1 != 0) && !isEvent env
/-- Dgram.hh:65 -/
def reserved (env : UInt32) : UInt32 := (env >>> 16) &&& 0xff

end Env

/-- src/TransitionId.cc:5-26 -/
def transitionNames : List String :=
  ["ClearReadout", "Reset", "Configure", "Unconfigure", "BeginRun", "EndRun", "BeginStep",
   "EndStep", "Enable", "Disable", "SlowUpdate", "Unused_11", "L1Accept"]

def transitionName (id : UInt32) : String :=
  if id < 13 then transitionNames.getD id.toNat "-Invalid-" else "-Invalid-"

/-- src/Level.cc:5-9 -/
def levelName (type : UInt32) : String :=
  if type < 2 then ["Segment", "Event"].getD type.toNat "-Invalid-" else "-Invalid-"

end XtcLean
