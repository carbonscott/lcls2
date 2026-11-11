/-
Memory-safety properties of `XtcIterator::iterate` and `XtcFileIterator::next`,
proved for all inputs, and the properties one would expect that are false,
each with a checked counterexample.
-/
import XtcLean.Props

namespace XtcLean

/-! ## What the bufEnd check does guarantee -/

/-- With a `bufEnd` that has 11 readable bytes after it, the loop never reads
out of bounds, whatever the bytes are. -/
theorem loop_no_oob (m : Mem) (E : Nat) (hE : E + 11 ≤ m.size) :
    ∀ fuel x rem st y, loop m (some E) fuel x rem st ≠ .oob y := by
  intro fuel
  induction fuel with
  | zero =>
    intro x rem st y
    unfold loop
    split
    · simp
    · split
      · simp
      · rename_i hend
        simp only [endHit, ge_iff_le, decide_eq_true_eq, Nat.not_le] at hend
        split
        · omega
        · split <;> simp
  | succ n ih =>
    intro x rem st y
    unfold loop
    split
    · simp
    · split
      · simp
      · rename_i hend
        simp only [endHit, ge_iff_le, decide_eq_true_eq, Nat.not_le] at hend
        split
        · omega
        · split
          · simp
          · simp only
            split
            · simp
            · split
              · exact ih _ _ _ _
              · (repeat' split) <;> first | exact ih _ _ _ _ | simp

/-- `iterate` with a root header in bounds and 11 readable bytes after `bufEnd`
never reads out of bounds. -/
theorem iterate_no_oob (m : Mem) (E stop : Nat) (hroot : 12 ≤ m.size) (hE : E + 11 ≤ m.size)
    (y : Nat) : iterate m (some E) stop ≠ .oob y := by
  unfold iterate
  simp only
  split
  · omega
  · split
    · simp
    · split
      · omega
      · exact loop_no_oob m E hE _ _ _ _ _

/-- Every Xtc handed to `process` starts before `bufEnd`.  (It need not end
before it: see `iterate_passes_xtc_past_bufEnd`.) -/
theorem loop_visits_lt (m : Mem) (E : Nat) :
    ∀ fuel x rem st st', loop m (some E) fuel x rem st = .ok st' →
      (∀ v ∈ st.visits, v.off < E) → ∀ v ∈ st'.visits, v.off < E := by
  intro fuel
  induction fuel with
  | zero =>
    intro x rem st st' h hst
    unfold loop at h
    split at h
    · simp only [Outcome.ok.injEq] at h; subst h; exact hst
    · split at h
      · simp at h
      · split at h
        · simp at h
        · split at h <;> simp at h
  | succ n ih =>
    intro x rem st st' h hst
    unfold loop at h
    split at h
    · simp only [Outcome.ok.injEq] at h; subst h; exact hst
    · split at h
      · simp at h
      · rename_i hend
        simp only [endHit, ge_iff_le, decide_eq_true_eq, Nat.not_le] at hend
        split at h
        · simp at h
        · split at h
          · simp at h
          · simp only at h
            have hpush : ∀ v ∈ (st.visits.push ⟨x, u16 m (x + 6), u32 m (x + 8)⟩), v.off < E := by
              intro v hv
              rcases Array.mem_push.mp hv with hv | rfl
              · exact hst v hv
              · exact hend
            split at h
            · simp only [Outcome.ok.injEq] at h; subst h; exact hpush
            · split at h
              · rename_i st3 hinner
                apply ih _ _ _ _ h
                (repeat' split at hinner)
                all_goals first
                  | exact ih _ _ _ _ hinner hpush
                  | (simp only [Outcome.ok.injEq] at hinner; subst hinner; exact hpush)
              · rename_i hne
                exact absurd h (hne _)

theorem iterate_visits_lt (m : Mem) (E stop : Nat) (st : WalkState)
    (h : iterate m (some E) stop = .ok st) : ∀ v ∈ st.visits, v.off < E := by
  unfold iterate at h
  simp only at h
  split at h
  · simp at h
  · split at h
    · simp only [Outcome.ok.injEq] at h; subst h; simp
    · split at h
      · simp at h
      · exact loop_visits_lt m E _ _ _ _ _ h (by simp)

/-! ## What it does not guarantee -/

/-- A root whose 16-byte payload holds one 12-byte Xtc and 4 stray bytes.
The buffer is exactly 28 bytes and `bufEnd` points at its end. -/
def exStraddle : Mem := ⟨#[
  0,0,0,0, 0,0, 0,0, 28,0,0,0,
  0,0,0,0, 0,0, 1,0, 12,0,0,0,
  0,0,0,0]⟩

/-- Refutes "iterate with bufEnd at the end of the buffer reads only inside the
buffer": the header at offset 24 starts before `bufEnd`, so the check on
XtcIterator.cc:48 passes, and line 53 reads `extent` at bytes 32..35. -/
theorem iterate_oob_with_exact_bufEnd : iterate exStraddle (some 28) 0 = .oob 24 := by decide

/-- A root with a 12-byte payload holding an Xtc that claims 16 bytes. -/
def exEscape : Mem := ⟨#[
  0,0,0,0, 0,0, 0,0, 24,0,0,0,
  0,0,0,0, 0,0, 1,0, 16,0,0,0]⟩

/-- Refutes "every Xtc passed to process() lies inside its parent and inside
bufEnd": this one is passed with extent 16 at offset 12 of a 24-byte buffer. -/
theorem iterate_passes_xtc_past_bufEnd :
    iterate exEscape (some 24) 0 = .ok ⟨#[⟨12, 1, 16⟩], 0⟩ := by decide

/-! ## XtcFileIterator -/

/-- One complete datagram with no payload (extent 12), then 5 stray bytes. -/
def exTail : Mem := ⟨#[
  0x22,0x22,0x22,0x22, 0x11,0x11,0x11,0x11,  0,0,0,0x0c,
  0,0,0,0, 0,0, 0,0, 12,0,0,0,
  0xff,0xff,0xff,0xff,0xff]⟩

/-- Refutes "next() returns only datagrams that are in the file": the second
call reads 5 of 24 header bytes, keeps the previous header for the rest, and
returns it as a second datagram ending at byte 29. -/
theorem fileRun_phantom_dgram :
    (fileRun exTail 64 5 FileIterState.start ⟨#[], none, none⟩).dgrams
      = #[(12, 24), (12, 29)] := by decide

/-- A file shorter than one header: the first call uses bytes of `_buf` that
were never written. -/
theorem fileRun_uninit :
    (fileRun ⟨#[1, 2, 3, 4, 5]⟩ 64 5 FileIterState.start ⟨#[], none, none⟩).bad
      = some "UNINIT" := by decide

/-- The size_t value of `sizeofPayload`, when it is a size the kernel accepts,
is the true payload size, and the extent is at least 12. -/
theorem payloadSize_spec (e : UInt32)
    (h : (Xtc.sizeofPayload e).toInt64.toUInt64 < 0x8000000000000000) :
    12 ≤ e ∧ (Xtc.sizeofPayload e).toInt64.toUInt64 = (e - 12).toUInt64 := by
  simp only [Xtc.sizeofPayload] at *
  constructor <;> bv_decide

/-- Buffer safety of `next()`: a datagram it returns has an extent of at least
12, fits in `_buf` (24 header bytes plus the payload is at most maxDgramSize),
and was read from inside the file. -/
theorem fileNext_dgram_spec (file : Mem) (max : UInt64) (s s' : FileIterState) (e : UInt32)
    (h : fileNext file max s = .dgram e s') :
    12 ≤ e ∧ e.toNat + 12 ≤ max.toNat ∧ s'.pos ≤ file.size := by
  unfold fileNext at h
  simp only at h
  split at h
  · simp at h
  · split at h
    · simp at h
    · rename_i hn
      split at h
      · simp at h
      · split at h
        · simp at h
        · rename_i hbig
          split at h
          · rename_i hz
            simp only [NextResult.dgram.injEq] at h
            obtain ⟨rfl, rfl⟩ := h
            have hs := payloadSize_spec _ (by rw [hz]; decide)
            obtain ⟨h12, hp⟩ := hs
            rw [hp] at hbig
            have a1 : 12 ≤ (u32 (overwritePrefix file s.pos (min 24 (file.size - s.pos)) s.hdr) 20).toNat := by
              simpa [UInt32.le_iff_toNat_le] using h12
            have a2 := UInt32.toNat_sub_of_le _ _ h12
            simp only [UInt64.not_lt, UInt64.le_iff_toNat_le, UInt64.toNat_add, UInt32.toNat_toUInt64,
              a2] at hbig
            have a3 : (12 : UInt32).toNat = 12 := rfl
            have a4 : (24 : UInt64).toNat = 24 := rfl
            have a5 := (u32 (overwritePrefix file s.pos (min 24 (file.size - s.pos)) s.hdr) 20).toNat_lt
            refine ⟨h12, ?_, ?_⟩ <;> (try dsimp only) <;> omega
          · split at h
            · simp at h
            · rename_i hk
              split at h
              · rename_i havail
                simp only [NextResult.dgram.injEq] at h
                obtain ⟨rfl, rfl⟩ := h
                have hs := payloadSize_spec _ (by
                  simpa [UInt64.not_le] using hk)
                obtain ⟨h12, hp⟩ := hs
                rw [hp] at hbig havail
                have a1 : 12 ≤ (u32 (overwritePrefix file s.pos (min 24 (file.size - s.pos)) s.hdr) 20).toNat := by
                  simpa [UInt32.le_iff_toNat_le] using h12
                have a2 := UInt32.toNat_sub_of_le _ _ h12
                simp only [UInt64.not_lt, UInt64.le_iff_toNat_le, UInt64.toNat_add, UInt32.toNat_toUInt64,
                  a2] at hbig havail
                have a3 : (12 : UInt32).toNat = 12 := rfl
                have a4 : (24 : UInt64).toNat = 24 := rfl
                have a5 := (u32 (overwritePrefix file s.pos (min 24 (file.size - s.pos)) s.hdr) 20).toNat_lt
                refine ⟨h12, ?_, ?_⟩ <;> (try dsimp only) <;> (try simp only [hp, UInt32.toNat_toUInt64, a2]) <;> omega
              · simp at h

end XtcLean
