/-
xtcdiff: the Lean side of the differential test.  Reads the same case lines
as difftest/oracle.cc and prints one result line per case.

Extra results that the oracle cannot print, because the C++ behaviour is
undefined there:  OOB <offset>, UNINIT, PTROVF.

It imports only the model, not the proofs, so a broken proof cannot leave a
stale executable behind.
-/
import XtcLean.Basic
import XtcLean.Xtc
import XtcLean.FileIter

open XtcLean

def hexVal (c : Char) : UInt8 :=
  if c.isDigit then (c.toNat - '0'.toNat).toUInt8
  else if 'a' ≤ c && c ≤ 'f' then (c.toNat - 'a'.toNat + 10).toUInt8
  else (c.toNat - 'A'.toNat + 10).toUInt8

def unhex (s : String) : ByteArray :=
  if s == "-" then ByteArray.empty else
  let rec go : List Char → ByteArray → ByteArray
    | a :: b :: r, acc => go r (acc.push (hexVal a * 16 + hexVal b))
    | _, acc => acc
  go s.toList ByteArray.empty

def b (x : Bool) : String := if x then "1" else "0"
def n32 (s : String) : UInt32 := s.toNat!.toUInt32
def n64 (s : String) : UInt64 := s.toNat!.toUInt64
def optEnd (s : String) : Option Nat := if s == "none" then none else some s.toNat!

def runCase (line : String) : String :=
  match line.splitOn " " with
  | ["typeid_ctor", t, v] =>
    let x := TypeId.ofTypeVersion (n32 t) (n32 v)
    s!"{x.value} {x.id} {x.version}"
  | ["typeid_str", s] =>
    -- white space travels as ~s ~t ~n
    let s := ((s.replace "~s" " ").replace "~t" "\t").replace "~n" "\n"
    let x := TypeId.ofString s
    s!"{x.value} {x.id} {x.version}"
  | ["typeid_name", t] => TypeId.name (n32 t)
  | ["damage_inc_value", d, v] => s!"{((⟨(n32 d).toUInt16⟩ : Damage).increaseValue (n32 v)).value}"
  | ["damage_inc_u16", d, v] =>
    s!"{((⟨(n32 d).toUInt16⟩ : Damage).increaseBits (n32 v).toUInt16).value}"
  | ["damage_get", d] =>
    let x : Damage := ⟨(n32 d).toUInt16⟩
    s!"{x.bits} {x.userBits}"
  | ["damage_setuser", d, v] =>
    s!"{((⟨(n32 d).toUInt16⟩ : Damage).setUserBits (n32 v).toUInt16).value}"
  | ["src_ctor", value, level] =>
    let x := Src.ofValueLevel (n32 value) (n32 level)
    s!"{x.value} {x.level} {x.val}"
  | ["namesid", node, names] =>
    match NamesId.make (n32 node) (n32 names) with
    | none => "ABORT"
    | some x => s!"{x.value} {NamesId.nodeId x} {NamesId.namesId x} {x.val}"
  | ["ts_u64", s] =>
    let x := TimeStamp.ofUInt64 (n64 s)
    s!"{x.value} {x.high} {x.low} {x.toNs} {b x.isZero}"
  | ["ts_secnsec", s, n] =>
    let x := TimeStamp.ofSecNsec (n32 s) (n32 n)
    s!"{x.value} {x.toNs}"
  | ["ts_from_ns", n] =>
    let x := TimeStamp.fromNs (n64 n)
    s!"{x.value} {x.toNs}"
  | ["ts_cmp", a, c] =>
    let x := TimeStamp.ofUInt64 (n64 a)
    let y := TimeStamp.ofUInt64 (n64 c)
    s!"{b (x.gt y)} {b (x.eq y)}"
  | ["transition", type, tid, env] =>
    let e := Env.make (n32 type) (n32 tid) (n32 env)
    s!"{e} {Env.control e} {Env.service e} {Env.type e} {b (Env.isEvent e)} {b (Env.isExtended e)} {Env.readoutGroups e} {b (Env.keepRaw e)}"
  | ["env", env] =>
    let e := n32 env
    s!"{Env.control e} {Env.service e} {Env.type e} {b (Env.isEvent e)} {b (Env.isExtended e)} {Env.readoutGroups e} {b (Env.keepRaw e)} {Env.reserved e}"
  | ["trname", t] => transitionName (n32 t)
  | ["levelname", t] => levelName (n32 t)
  | ["sizeof_payload", e] => s!"{(Xtc.sizeofPayload (n32 e)).toInt}"
  | ["alloc", e, size, endS] =>
    match Xtc.alloc 0 (n32 e) (n64 size) (optEnd endS) with
    | .abort => "ABORT"
    | .ptrOverflow => "PTROVF"
    | .ok p ext => s!"{p} {ext}"
  | ["iterate", hex, endS, stop] =>
    match iterate (unhex hex) (optEnd endS) stop.toNat! with
    | .ok st => " ".intercalate ("ok" :: st.visits.toList.map fun v => s!"{v.off}:{v.contains}:{v.extent}")
    | .abort => "ABORT"
    | .oob x => s!"OOB {x}"
    | .fuel => "FUEL"
  | ["fileiter", hex, maxSize, maxDg] =>
    let r := fileRun (unhex hex) (n64 maxSize) maxDg.toNat! FileIterState.start ⟨#[], none, none⟩
    match r.bad with
    | some s => s
    | none =>
      let body := r.dgrams.foldl (fun acc d => acc ++ s!" {d.1}@{d.2}") "ok"
      body ++ (match r.ended with | some reason => " end:" ++ reason | none => "")
  | _ => "BADOP"

partial def mainLoop (inp out : IO.FS.Stream) : IO Unit := do
  let line ← inp.getLine
  if line.isEmpty then return
  let line := (line.splitOn "\n").headD ""
  if !line.isEmpty then out.putStrLn (runCase line)
  mainLoop inp out

def main : IO Unit := do
  let inp ← IO.getStdin
  let out ← IO.getStdout
  mainLoop inp out
