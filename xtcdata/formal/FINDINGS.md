# Findings in xtcdata from the formal model

Source under test: `xtcdata/xtcdata/xtc/` at agentify `b3d052088`.
Each finding was first shown on the real C++ through `difftest/oracle.cc`
(case line given), and is stated in Lean where the model can state it.
"Reach" lists callers found by search in the same tree; none of the
findings was reproduced in a running DAQ or in psana.

| id | summary | severity | status |
|----|---------|----------|--------|
| X1 | `Damage::increase(Damage::UserDefined)` changes nothing | medium | proved |
| X2 | `XtcIterator::iterate` reads `extent` of a header that crosses `bufEnd` | low | proved (counterexample), valgrind |
| X3 | `iterate` hands `process()` an Xtc that runs past its parent and `bufEnd` | medium | proved (counterexample) |
| X4 | `XtcFileIterator::next` returns a datagram that is not in the file | low to medium | proved (counterexample), valgrind |
| X5 | `TypeId(const char*)` always loses the version | negligible (unused) | proved |
| X6 | `Xtc::alloc` with a size of 2^64 - k passes its bounds check and shrinks the extent | medium | oracle only |
| X7 | `iterate` overflows the stack at about 10^5 nested Parents | low | oracle only |
| X8 | smaller items: `from_ns` wrap, `sizeofPayload` sign, `alloc` truncation | informational | proved |

## X1  `Damage::increase(Damage::UserDefined)` changes nothing

`Damage.hh:36-39` computes `_damage |= ((1 << v) & ValueBitMask)`.
`UserDefined` is 12 and `ValueBitMask` is `0x0fff`, so the mask removes the
bit. The same holds for the values 13 to 15.

- Oracle: `damage_inc_value 0 12` prints `0` (and `damage_inc_value 0 3` prints `8`).
- Lean: `Damage.increaseValue_noop`, `Damage.increaseValue_userDefined`.
- Reach: `psdaq/drp/Piranha4.cc:502`, `TimeTool.cc:65`, `Opal.cc:471`,
  `UdpEncoder.cc:293`, `Digitizer.cc:263, 272, 305`. They call it for an
  invalid FEX result, a wrong ROI length, a failed UDP read and a JESD
  status error. No damage is recorded for those events.
- psana reads user bits as `damage >> 12` (`psana/psana/detector/damage.py`),
  so it would see bit 12 if it were set.
- A fix in the enum alone would not carry the bit through the event builder:
  the merges there (`teb.cc:604`, `DrpBase.cc:1156`, `monReqServer.cc:230`)
  use `increase(uint16_t)`, which masks the user bits off as well.

## X2  `iterate` reads past `bufEnd` for a header that crosses it

`XtcIterator.cc:48` aborts only when the header *starts* at or after `bufEnd`.
Line 53 then reads `xtc->extent` (bytes 8 to 11 of the header). A header that
starts 1 to 11 bytes before `bufEnd` is read past it.

- Oracle under valgrind, root extent 28 with one 12-byte child and 4 stray bytes, `bufEnd` = 28:
  `iterate 00000000000000001c00000000000000000001000c00000000000000 28 0`
  gives "Invalid read of size 4 at XtcIterator.cc:53 ... 4 bytes after a block of size 28".
- Lean: `iterate_oob_with_exact_bufEnd` (the read happens), `iterate_no_oob`
  (no read is out of bounds when 11 bytes after `bufEnd` are readable),
  `iterate_visits_lt` (every header starts before `bufEnd`).
- Reach: psana passes the end of the datagram allocation as `bufEnd`
  (`psana/src/dgram.cc`, `assignDict`). Needs a file whose inner extents
  leave 1 to 11 stray bytes.

## X3  `process()` gets an Xtc that runs past its parent and `bufEnd`

`iterate` never compares `xtc + extent` with the parent's end or `bufEnd`.

- Oracle: `iterate 000000000000000018000000000000000000010010000000 24 0`
  prints `ok 12:1:16`: extent 16 at offset 12 of a 24-byte buffer.
- Lean: `iterate_passes_xtc_past_bufEnd`.
- Reach: every `process` that reads the payload by extent, for example
  psana's `PyConvertIter::process`. With a corrupt inner extent that is a
  read past the buffer in the caller. Not run against psana.

## X4  `XtcFileIterator::next` returns a datagram that is not in the file

`XtcFileIterator.cc:24` tests only `read(...) == 0`. A short read of the
header (1 to 23 bytes) is taken as a full one, and the rest of the header is
whatever the buffer held.

- After a datagram with an empty payload, 1 to 23 stray bytes produce a
  second datagram built from the old header.
  Oracle: `fileiter 22222222111111110000000c00000000000000000c000000ffffffffff 64 5`
  prints `ok 12@24 12@29 end:eof`. Lean: `fileRun_phantom_dgram`.
- If the first read is short, the header is uninitialised memory.
  Oracle under valgrind: `fileiter 0102030405 64 5` gives "Conditional jump
  ... depends on uninitialised value(s)" at lines 26 and 32. Lean: `fileRun_uninit`.
- `read` returning -1 on the header is also taken as success. The reviewer's
  separate test (not part of the oracle) closed the descriptor after one
  empty datagram and got the same datagram back 1000 times out of 1000; a
  caller's `while ((dg = iter.next()))` would not end. The model does not
  cover read errors.
- What does hold: `fileNext_dgram_spec`. A returned datagram has extent of at
  least 12, fits in the buffer and lies inside the file.
- Reach: `xtcreader`, `xtcupdate`, `xtcsave`, `psalg/shmem/XtcRunSet.cc:107`,
  the Opal and Piranha4 simulation readers in `psdaq/drp`. psana's main
  reader does not use this class.

## X5  `TypeId(const char*)` always loses the version

`src/TypeId.cc:19` stores `(vsn << 16) | i` in the 16-bit `_value`; the
version field is at bit 12.

- Oracle: `typeid_str Names_v3` prints `4 4 0`; `typeid_ctor 4 3` prints `12292 4 3`.
- Lean: `TypeId.version_ofString` (version is 0 for every string).
- Reach: no caller found in the tree.

## X6  `Xtc::alloc` with a size near 2^64

`Xtc.hh:109` checks `(char*)buffer + size > end`. With a size of 2^64 - k the
pointer sum wraps, the check passes, and `extent += size` lowers the extent.

- Oracle: `alloc 12 18446744073709551612 64` prints `12 8`;
  `alloc 12 18446744073709551604 12` prints `12 0`.
- Lean: not stated. Such a pointer sum is undefined in C++; the model classes
  the call as `ptrOverflow` and `Xtc.alloc_spec` excludes it.
- Reach: about 20 call sites pass `other.sizeofPayload()` as the size
  (for example `psdaq/drp/PGPDetector.cc:665`, `Opal.cc:398`,
  `BldDetector.cc:982`). `sizeofPayload()` is negative for an extent below 12
  (`Xtc.sizeofPayload_nonneg_iff`), and converts to such a size.

## X7  Stack overflow on deep nesting

Each nested Parent is one recursive call of `iterate` through `process`.

- Oracle, a chain of nested Parents (`difftest/build/deep.sh`, 8 MB stack):
  depth 70,000 (840 kB buffer) returns; depth 100,000 (1.2 MB) ends with
  signal 11.
- Lean: not stated; the model has no call stack. `loop_ne_fuel` shows only
  that the loop itself cannot run forever.
- Reach: corrupt or hostile input only; `Dgram::MaxSize` is 16 MB.

## X8  Smaller items

- `TimeStamp::from_ns` keeps 32 bits of seconds: `toNs_fromNs` holds below
  2^32 s, `toNs_fromNs_wraps` shows the wrap at 2^32 s.
- `Xtc::alloc` without a buffer end truncates the extent to 32 bits: `Xtc.alloc_wraps`.
- `XtcFileIterator::next` with an extent below 12 passes its size check by
  `size_t` wrap and then relies on `read` refusing a count of 2^63 or more
  (`end:err` in the differential test).

## Seen while reading, outside the modelled files (not tested)

- `psana/psana/detector/damage.py` numbers `DamageBitmask` from 1
  (`MissingData = 6`) and uses `1 << DamageBitmask.MissingData.value`, which
  is bit 6. In `Damage.hh` bit 6 is `TimedOut` and `MissingData` is bit 5.
- `xtcreader` passes the end of its 64 MB buffer as `bufEnd`, so a corrupt
  inner extent walks into bytes of earlier datagrams without an abort.
