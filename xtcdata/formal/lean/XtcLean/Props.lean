/-
Properties of the XTC2 model.  Each is either proved for all inputs or
refuted by a checked counterexample.  `Audit.lean` lists them.
-/
import XtcLean.Basic
import XtcLean.Xtc
import XtcLean.FileIter
import Std.Tactic.BVDecide

namespace XtcLean

/-! ## TypeId -/

theorem TypeId.id_ofTypeVersion (t v : UInt32) (h : t < 0x1000) :
    (TypeId.ofTypeVersion t v).id = t := by
  simp only [TypeId.id, TypeId.ofTypeVersion]; bv_decide

theorem TypeId.version_ofTypeVersion (t v : UInt32) (h : t < 0x1000) :
    (TypeId.ofTypeVersion t v).version = v &&& 0xf := by
  simp only [TypeId.version, TypeId.ofTypeVersion]; bv_decide

/-- The string constructor never keeps the version: `TypeId("Names_v3").version()`
is 0, as it is for every other string. -/
theorem TypeId.version_ofString (s : String) : (TypeId.ofString s).version = 0 := by
  unfold TypeId.ofString
  split
  · split
    · split
      · rename_i i hi
        have hm := List.mem_of_find?_eq_some hi
        have hlt : i < 5 := by simpa using hm
        have : i = 0 ∨ i = 1 ∨ i = 2 ∨ i = 3 ∨ i = 4 := by omega
        rcases this with rfl | rfl | rfl | rfl | rfl <;> decide
      · decide
    · decide
  · decide

/-! ## Damage -/

/-- `increase(v)` changes nothing for the four `Damage::Value`s 12..15, which
include `UserDefined` (12): their bit is outside `ValueBitMask`. -/
theorem Damage.increaseValue_noop (d : Damage) (v : UInt32) (h1 : 12 ≤ v) (h2 : v < 16) :
    d.increaseValue v = d := by
  cases d with | mk x =>
  simp only [Damage.increaseValue, Damage.mk.injEq]; bv_decide

theorem Damage.increaseValue_userDefined (d : Damage) :
    d.increaseValue Damage.userDefined = d :=
  Damage.increaseValue_noop d _ (by decide) (by decide)

/-- For the values below 12, `increase(v)` sets bit `v` and nothing else. -/
theorem Damage.increaseValue_exact (d : Damage) (v : UInt32) (h : v < 12) :
    (d.increaseValue v).value = d.value ||| ((1 : UInt32) <<< v).toUInt16 := by
  simp only [Damage.increaseValue]; bv_decide

theorem Damage.userBits_increaseValue (d : Damage) (v : UInt32) :
    (d.increaseValue v).userBits = d.userBits := by
  simp only [Damage.increaseValue, Damage.userBits]; bv_decide

theorem Damage.userBits_increaseBits (d : Damage) (v : UInt16) :
    (d.increaseBits v).userBits = d.userBits := by
  simp only [Damage.increaseBits, Damage.userBits]; bv_decide

theorem Damage.userBits_setUserBits (d : Damage) (v : UInt16) :
    (d.setUserBits v).userBits = v &&& 0xf := by
  simp only [Damage.setUserBits, Damage.userBits]; bv_decide

theorem Damage.bits_setUserBits (d : Damage) (v : UInt16) :
    (d.setUserBits v).bits = d.bits := by
  simp only [Damage.setUserBits, Damage.bits]; bv_decide

/-! ## Src, NamesId -/

theorem Src.level_ofValueLevel (v l : UInt32) : (Src.ofValueLevel v l).level = l &&& 0xf := by
  simp only [Src.ofValueLevel, Src.level]; bv_decide

theorem Src.val_ofValueLevel (v l : UInt32) : (Src.ofValueLevel v l).val = v &&& 0x0fffffff := by
  simp only [Src.ofValueLevel, Src.val]; bv_decide

/-- A NamesId that is constructed without abort reads back its two fields, and
its value is below `NamesId::NumberOf`, the size of the lookup array it indexes. -/
theorem NamesId.make_spec (n k : UInt32) (s : Src) (h : NamesId.make n k = some s) :
    NamesId.nodeId s = n ∧ NamesId.namesId s = k ∧ s.val < NamesId.numberOf ∧ s.level = 0 := by
  unfold NamesId.make at h
  split at h
  · simp at h
  · split at h
    · simp at h
    · rename_i h1 h2
      simp only [Option.some.injEq] at h
      subst h
      simp only [NamesId.nodeId, NamesId.namesId, Src.val, Src.level, Src.ofValueLevel,
        NamesId.numberOf]
      simp only [bne_iff_ne, ne_eq, Decidable.not_not] at h1 h2
      refine ⟨?_, ?_, ?_, ?_⟩ <;> bv_decide

/-- `abort()` happens exactly when a field does not fit. -/
theorem NamesId.make_isSome (n k : UInt32) :
    (NamesId.make n k).isSome = (decide (n < 0x1000) && decide (k < 0x100)) := by
  by_cases h1 : n < 0x1000 <;> by_cases h2 : k < 0x100
  · have e1 : n &&& 0xfff = n := by bv_decide
    have e2 : k &&& 0xff = k := by bv_decide
    simp [NamesId.make, e1, e2, h1, h2]
  · have e1 : n &&& 0xfff = n := by bv_decide
    have e2 : k &&& 0xff ≠ k := by bv_decide
    simp [NamesId.make, e1, e2, h1, h2]
  · have e1 : n &&& 0xfff ≠ n := by bv_decide
    simp [NamesId.make, e1, h1]
  · have e1 : n &&& 0xfff ≠ n := by bv_decide
    simp [NamesId.make, e1, h1]

/-! ## TimeStamp -/

theorem TimeStamp.value_ofUInt64 (s : UInt64) : (TimeStamp.ofUInt64 s).value = s := by
  simp only [TimeStamp.ofUInt64, TimeStamp.value]; bv_decide

theorem TimeStamp.gt_iff (a b : TimeStamp) : a.gt b = decide (a.value > b.value) := by
  cases a with | mk al ah =>
  cases b with | mk bl bh =>
  simp only [TimeStamp.gt, TimeStamp.value]; bv_decide

theorem TimeStamp.eq_iff (a b : TimeStamp) : a.eq b = decide (a.value = b.value) := by
  cases a with | mk al ah =>
  cases b with | mk bl bh =>
  simp only [TimeStamp.eq, TimeStamp.value]; bv_decide

/-- `from_ns` then `to_ns` gives the input back below 2^32 seconds. -/
theorem TimeStamp.toNs_fromNs (n : UInt64) (h : n < 4294967296000000000) :
    (TimeStamp.fromNs n).toNs = n := by
  have hn : n.toNat < 4294967296000000000 := by simpa [UInt64.lt_iff_toNat_lt] using h
  have hq : n.toNat / 1000000000 < 4294967296 := by omega
  have hr : n.toNat % 1000000000 < 1000000000 := Nat.mod_lt _ (by decide)
  have hdm := Nat.div_add_mod n.toNat 1000000000
  have hp : n.toNat / 1000000000 * 1000000000 < 18446744073709551616 := by omega
  apply UInt64.toNat_inj.mp
  simp only [TimeStamp.fromNs, TimeStamp.toNs, UInt64.toNat_add, UInt64.toNat_mul,
    UInt32.toNat_toUInt64, UInt64.toNat_toUInt32, UInt64.toNat_div, UInt64.toNat_mod,
    UInt64.toNat_ofNat, Nat.reducePow, Nat.reduceMod]
  rw [Nat.mod_eq_of_lt hq, Nat.mod_eq_of_lt (by omega : n.toNat % 1000000000 < 4294967296),
    Nat.mod_eq_of_lt hp]
  omega

/-- Refutes "from_ns then to_ns is the identity": at 2^32 seconds the seconds field wraps. -/
theorem TimeStamp.toNs_fromNs_wraps :
    (TimeStamp.fromNs 4294967296000000000).toNs = 0 := by decide

/-! ## Transition env word -/

theorem Env.service_make (t tid e : UInt32) : Env.service (Env.make t tid e) = tid &&& 0xf := by
  simp only [Env.service, Env.control, Env.make]; bv_decide

theorem Env.type_make (t tid e : UInt32) (h : tid < 16) :
    Env.type (Env.make t tid e) = t &&& 0x3 := by
  simp only [Env.type, Env.control, Env.make]; bv_decide

theorem Env.readoutGroups_make (t tid e : UInt32) :
    Env.readoutGroups (Env.make t tid e) = e &&& 0xffff := by
  simp only [Env.readoutGroups, Env.make]; bv_decide

/-! ## Xtc -/

/-- For extents in [12, 2^31 + 12), `sizeofPayload` is the true payload size. -/
theorem Xtc.sizeofPayload_toInt (e : UInt32) (h1 : 12 ≤ e) (h2 : e < 0x8000000c) :
    (Xtc.sizeofPayload e).toInt = e.toNat - 12 := by
  have a1 : 12 ≤ e.toNat := by simpa [UInt32.le_iff_toNat_le] using h1
  have a2 : e.toNat < 0x8000000c := by simpa [UInt32.lt_iff_toNat_lt] using h2
  have hsub : (e - 12).toNat = e.toNat - 12 := by
    rw [UInt32.toNat_sub_of_le _ _ h1]; rfl
  simp only [Xtc.sizeofPayload, Int32.toInt, UInt32.toBitVec_toInt32, BitVec.toInt_eq_toNat_bmod,
    UInt32.toNat_toBitVec, hsub, Int.bmod]
  split <;> omega

/-- Outside that range, and only there, `sizeofPayload` is negative. -/
theorem Xtc.sizeofPayload_nonneg_iff (e : UInt32) :
    0 ≤ Xtc.sizeofPayload e ↔ (12 ≤ e ∧ e < 0x8000000c) := by
  simp only [Xtc.sizeofPayload]
  constructor
  · intro h; constructor <;> bv_decide
  · intro ⟨h1, h2⟩; bv_decide

/-- Refutes "sizeofPayload is never negative". -/
theorem Xtc.sizeofPayload_neg : (Xtc.sizeofPayload 0).toInt = -12 := by decide

/-- With a buffer end, a successful `alloc` grows the extent by exactly `size`
and stays inside the buffer (for buffers under 4 GB).  Sizes of 2^47 and more
are outside this statement: the model classes them as `ptrOverflow`. -/
theorem Xtc.alloc_spec (off : Nat) (ext : UInt32) (size : UInt64) (e p : Nat) (ext' : UInt32)
    (hsmall : e < off + 4294967296)
    (h : Xtc.alloc off ext size (some e) = .ok p ext') :
    p = off + ext.toNat ∧ ext'.toNat = ext.toNat + size.toNat ∧ off + ext'.toNat ≤ e := by
  simp only [Xtc.alloc] at h
  split at h
  · simp at h
  · split at h
    · simp at h
    · rename_i hle
      simp only [AllocResult.ok.injEq] at h
      obtain ⟨rfl, rfl⟩ := h
      have : (ext + size.toUInt32).toNat = ext.toNat + size.toNat := by
        simp only [UInt32.toNat_add, UInt64.toNat_toUInt32]
        omega
      omega

/-- Refutes "alloc grows the extent by size" when no buffer end is given. -/
theorem Xtc.alloc_wraps : Xtc.alloc 0 12 4294967296 none = .ok 12 12 := by decide

/-! ## XtcIterator::iterate -/

/-- The fuel in the model is never the reason a walk stops: each step moves
forward by at least 12 bytes, so the loop cannot run forever.  This says nothing
about the call stack, which the model does not have (FINDINGS.md, X7). -/
theorem loop_ne_fuel (m : Mem) (e : Option Nat) :
    ∀ fuel x rem st, m.size < x + fuel → loop m e fuel x rem st ≠ .fuel := by
  intro fuel
  induction fuel with
  | zero =>
    intro x rem st h
    unfold loop
    split
    · simp
    · split
      · simp
      · split
        · simp
        · omega
  | succ n ih =>
    intro x rem st h
    unfold loop
    split
    · simp
    · split
      · simp
      · split
        · simp
        · split
          · simp
          · rename_i hsz hext
            simp only
            split
            · simp
            · have h12 : 12 ≤ (u32 m (x + 8)).toNat := by
                have := hext
                simp only [UInt32.lt_iff_toNat_lt, Nat.not_lt] at this
                simpa using this
              split
              · exact ih _ _ _ (by omega)
              · (repeat' split) <;> first | exact ih _ _ _ (by omega) | simp

theorem iterate_ne_fuel (m : Mem) (e : Option Nat) (stop : Nat) : iterate m e stop ≠ .fuel := by
  unfold iterate
  simp only
  split
  · simp
  · split
    · simp
    · split
      · simp
      · exact loop_ne_fuel m e _ _ _ _ (by omega)

end XtcLean
