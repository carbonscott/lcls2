"""Tests for the simulated EventBatcher framer of BEB detectors (psdaq/drp/MemPoolSim.cc).

drp_sim_frame writes one L1Accept DMA buffer as MemPoolSim makes it for drp -D <type> -d sim://;
the tests walk it as BEBDetector does (psdaq/drp/EventBatcher.hh) and check its layout and its
pixels against psdaq.sim.pattern, with the type's readout order written out here on its own.
"""

import shutil
import struct
import subprocess

import numpy as np
import pytest

from psdaq.sim import pattern

EXE = shutil.which('drp_sim_frame')
pytestmark = pytest.mark.skipif(EXE is None, reason='drp_sim_frame is not built (build_all.sh -d)')

PID = 0x123456789ab                 # what drp_sim_frame puts in the frame
SEED = 0x1234


def frame(det, seq, seed=SEED):
    return subprocess.run([EXE, det, str(seq), hex(seed)], capture_output=True, check=True,
                          timeout=60).stdout


def subframes(buf):
    """{tdest: data} and the tdests in buffer order, walking the tails from the end as
    EvtBatcherIterator does; asserts the header and that the tails tile the buffer exactly."""
    version, width = buf[0] & 0xf, buf[0] >> 4
    lw = 2 << width
    assert (version, lw) == (1, 8)
    found, pos = [], len(buf) - lw
    while True:
        size, tdest, first, last, w = struct.unpack_from('<IBBBB', buf, pos)
        assert size > 0 and w == width and first == 0x2
        start = pos - ((size + lw - 1) & ~(lw - 1))
        assert start >= lw
        found.append((tdest, bytes(buf[start:start + size])))
        if start == lw:
            break
        pos = start - lw
    found.reverse()
    return dict(found), [t for t, _ in found]


def timing_header(seq):
    return struct.pack('<QIIIIII', (12 << 56) | PID, 500000000, 1100000000, 1, seq, 0, 0)


def epix100_readout_rows():
    """Image row of each readout row: Epix100.cc puts readout row 2i at image row 352+i and
    2i+1 at 351-i (LCLS1 Epix100aServer's unscramble)."""
    rows = np.empty(704, dtype=int)
    for i in range(352):
        rows[2 * i], rows[2 * i + 1] = 352 + i, 351 - i
    return rows


def test_epix100_frame_layout():
    seq = 5
    buf = frame('epix100', seq)
    assert buf[1] == seq & 0xff                             # sequence_count
    data, order = subframes(buf)
    assert order == [0, 2, 3]
    assert data[0] == timing_header(seq) and data[2] == data[0]
    d = data[3]
    assert len(d) == 32 + (704 + 4) * 768 * 2 + 12          # what Epix100::_event expects
    assert len(buf) == 8 + 2 * (32 + 8) + ((len(d) + 7) & ~7) + 8
    assert struct.unpack_from('<4I', d, 0) == (PID & 0xffffffff, PID >> 32, seq, SEED)
    assert d[16:32] == bytes(16) and d[-12:] == bytes(12)
    readout = np.frombuffer(d, dtype=np.uint16, offset=32, count=(704 + 4) * 768).reshape(708, 768)
    image = pattern.image(SEED, seq, (704, 768), 14)
    assert (readout[:704] == image[epix100_readout_rows()]).all()
    extra = pattern.pattern(SEED, seq, np.arange(704 * 768, 708 * 768), 14).reshape(4, 768)
    assert (readout[704:] == extra).all()
    assert int(readout.max()) < (1 << 14)


def test_epix100_unscrambled_as_the_drp_does_is_the_image():
    """Epix100::_event's memcpy loop, in numpy: it must give back pattern.image exactly."""
    seq = 1000
    d = subframes(frame('epix100', seq))[0][3]
    readout = np.frombuffer(d, dtype=np.uint16, offset=32, count=704 * 768).reshape(704, 768)
    out = np.empty((704, 768), dtype=np.uint16)
    for i in range(352):
        out[352 + i] = readout[2 * i]
        out[351 - i] = readout[2 * i + 1]
    assert (out == pattern.image(SEED, seq, (704, 768), 14)).all()


def test_pattern_catches_order_offset_and_event_errors():
    img = pattern.image(SEED, 7, (704, 768), 14)
    assert (img != pattern.image(SEED, 7, (704, 768), 14, offset=1)).mean() > 0.99
    assert (img != img[::-1]).mean() > 0.99
    assert (img != img[epix100_readout_rows()]).mean() > 0.99
    assert (img != pattern.image(SEED, 8, (704, 768), 14)).all()
    assert (img != pattern.image(SEED + 1, 7, (704, 768), 14)).all()


def test_pattern_matches_the_cxx_mix():
    """Known values of MemPoolSim::mix, so pattern.py and the C++ cannot drift together."""
    d = subframes(frame('epix100', 0, 0))[0][3]
    readout = np.frombuffer(d, dtype=np.uint16, offset=32, count=2 * 768).reshape(2, 768)
    # readout row 0 is image row 352: pixel 352*768 + c
    assert (readout[0] == (pattern.mix(352 * 768 + np.arange(768)) & 0x3fff)).all()
    assert int(pattern.mix(0)) == 0 and int(pattern.mix(1)) == 0x640ca17e


def test_unknown_type_is_refused():
    r = subprocess.run([EXE, 'nosuchtype', '1'], capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and "no simulated EventBatcher layout or TDet message for detType 'nosuchtype'" in r.stderr


def test_wave8_frame_layout():
    """Wave8::_event reads subframes 2..9 as raw_0..7, 10 as W8::IntegralStream, 11 as
    W8::ProcStream."""
    seq, N = 9, 256
    data, order = subframes(frame('wave8', seq))
    assert order == [0, 1] + list(range(2, 12))
    assert data[0] == timing_header(seq) and data[1] == data[0]
    for ch in range(8):
        raw = np.frombuffer(data[2 + ch], dtype=np.uint16)
        assert raw.shape == (N,)
        assert (raw == pattern.pattern(SEED, seq, np.arange(ch * N, (ch + 1) * N), 16)).all()
    integ = data[10]
    assert len(integ) == 56
    assert struct.unpack_from('<BBHHH', integ, 0) == (0, 0, 0, seq, 0)
    ints = struct.unpack_from('<8I', integ, 8)
    bases = struct.unpack_from('<8H', integ, 40)
    for i in range(8):
        assert ints[i] == int(pattern.pattern(SEED, seq, 8 * N + i, 24))
        assert bases[i] == int(pattern.pattern(SEED, seq, 8 * N + 8 + i, 16))
    proc = data[11]
    assert len(proc) == 32
    quad, ptrig, inten, x, y = struct.unpack('<IIddd', proc)
    assert (quad, ptrig) == (0, seq)
    assert inten == float(pattern.pattern(SEED, seq, 8 * N + 16, 20))
    assert x == int(pattern.pattern(SEED, seq, 8 * N + 17, 20)) / 1024.
    assert y == int(pattern.pattern(SEED, seq, 8 * N + 18, 20)) / 1024.


def test_wave8he_frame_layout():
    """Wave8HE::_event reads subframes 2..9 as raw_0..7, 0x0C as W8HE::PeakStream and 0x0D as
    W8HE::IntegralStream (24-bit values packed, little-endian)."""
    seq, N = 11, 256
    data, order = subframes(frame('wave8he', seq))
    assert order == [0, 1] + list(range(2, 10)) + [0x0c, 0x0d]
    for ch in range(8):
        raw = np.frombuffer(data[2 + ch], dtype=np.uint16)
        assert (raw == pattern.pattern(SEED, seq, np.arange(ch * N, (ch + 1) * N), 16)).all()
    n = 8 * N

    def p(i, bits):
        return int(pattern.pattern(SEED, seq, n + i, bits))

    def u24(b, i):
        return b[3 * i] | (b[3 * i + 1] << 8) | (b[3 * i + 2] << 16)
    peak, integ = data[0x0c], data[0x0d]
    assert (len(peak), len(integ)) == (64, 32)
    words = struct.unpack_from('<8I', peak, 0)
    for i in range(8):
        assert words[i] >> 24 == p(i, 8) and words[i] & 0xffffff == p(8 + i, 24)
        assert u24(peak[32:56], i) == p(16 + i, 24)
        assert u24(integ[:24], i) == p(32 + i, 24)
    assert struct.unpack_from('<2f', peak, 56) == (p(24, 20) / 1024., p(25, 20) / 1024.)
    assert struct.unpack_from('<2f', integ, 24) == (p(40, 20) / 1024., p(41, 20) / 1024.)


def test_ts_timing_message_layout():
    """TimingSystem::event records the 153 bytes after the TimingHeader as TimingDef's packed
    TimingData: pulseId and timeStamp of the frame, then every other element numbered 2, 3, ...
    holding pattern(seed, seq, element, bits) with the field's meaning as its width."""
    seq = 9
    buf = frame('ts', seq)
    assert len(buf) == 32 + 153
    assert buf[:32] == timing_header(seq)
    pid, time = struct.unpack_from('<QQ', buf, 32)
    assert pid == PID and time == (1100000000 << 32) | 500000000
    layout = [('fixedRates', 10, 'B', 1), ('acRates', 6, 'B', 1), ('timeSlot', 1, 'B', 3),
              ('timeSlotPhase', 1, 'H', 16), ('ebeamPresent', 1, 'B', 1),
              ('ebeamDestn', 1, 'B', 4), ('ebeamCharge', 1, 'H', 16), ('ebeamEnergy', 4, 'H', 16),
              ('xWavelength', 2, 'H', 16), ('dmod5', 1, 'H', 16), ('mpsLimits', 16, 'B', 1),
              ('mpsPowerClass', 16, 'B', 4), ('sequenceValues', 18, 'H', 16),
              ('inhibitCounts', 8, 'I', 32)]
    pos, element = 48, 2
    for name, n, fmt, bits in layout:
        values = struct.unpack_from('<%d%s' % (n, fmt), buf, pos)
        want = pattern.pattern(SEED, seq, np.arange(element, element + n), bits)
        assert list(values) == [int(v) for v in want], name
        assert all(v < (1 << bits) for v in values), name
        pos += n * struct.calcsize(fmt)
        element += n
    assert pos == len(buf)
    from psdaq.sim.xtc2_check import TIMING_FIELDS          # the checker's copy of the layout
    assert [(a, b, d) for a, b, c, d in layout] == TIMING_FIELDS


def test_ts_message_differs_per_event_and_seed():
    assert frame('ts', 1)[48:] != frame('ts', 2)[48:]
    assert frame('ts', 1)[48:] != frame('ts', 1, SEED + 1)[48:]


def test_hrencoder_frame_layout():
    """HREncoder::_event reads subframe 2 as Enc::Stream {int32 position, uint8 encErrCnt,
    missedTrigCnt, latches, reserved}."""
    seq = 5
    data, order = subframes(frame('hrencoder', seq))
    assert order == [0, 2]
    assert data[0] == timing_header(seq)
    assert len(data[2]) == 8
    position, err, missed, latches, rsvd = struct.unpack('<iBBBB', data[2])
    p = lambda i, bits: int(pattern.pattern(SEED, seq, i, bits))
    assert position & 0xffffffff == p(0, 32)
    assert (err, missed, latches, rsvd) == (p(1, 8), p(2, 8), p(3, 8), 0)


def epixm320_descramble(src):
    """EpixM320::_descramble, written out again: 24 banks of 48 x 64 in the readout order,
    reordered (bank = 4 * bankCol + bankRow), even/odd columns split, rows shifted up by one."""
    rows, cols, nbank = 192, 384, 24
    bh, bw = rows // 4, cols // 6
    hw, hb = bw // 2, bh * bw // 2
    dst = np.empty((rows, cols), dtype=src.dtype)
    for r in range(rows):
        bank_row, row = divmod(r, bh)
        row_fix = bh - 1 if row == 0 else row - 1
        for c in range(cols):
            bank_col, col = divmod(c, bw)
            bank = 4 * bank_col + bank_row
            dst[r, c] = src[(((col + 1) % 2) * hb + hw * row_fix + col // 2) * nbank + bank]
    return dst


def test_epixm320_frame_layout():
    """EpixM320::_event reads subframes 2..5 as ASICs 0..3: a 48 B header (frameNo at 4,
    asicNo at 8), 192 x 384 uint16 in bank order, a 48 B trailer; descrambled, ASIC q's
    pixel (r, c) is pattern(seed, seq, q * 73728 + r * 384 + c, 15)."""
    seq = 3
    data, order = subframes(frame('epixm320', seq))
    assert order == [0, 1, 2, 3, 4, 5]
    assert data[0] == timing_header(seq) and data[1] == data[0]
    for q in range(4):
        sf = data[2 + q]
        assert len(sf) == 48 + 2 * 192 * 384 + 48
        assert struct.unpack_from('<IIB', sf, 0) == (0, seq, q)
        src = np.frombuffer(sf[48:48 + 2 * 192 * 384], dtype=np.uint16)
        img = epixm320_descramble(src)
        want = pattern.pattern(SEED, seq, q * 192 * 384 + np.arange(192 * 384), 15).reshape(192, 384)
        assert (img == want).all(), q
        assert sf[-48:] == bytes(48)


@pytest.mark.parametrize('det, shape, bits', [('opal', (1024, 1024), 12), ('piranha4', (2048,), 12)])
def test_camera_link_frame_layout(det, shape, bits):
    """Opal::_event and Piranha4::_event read subframe 2 as the camera's image (rows x columns
    uint16 in row order; Piranha4's one line), after the timing frame in subframe 1."""
    seq = 3
    data, order = subframes(frame(det, seq))
    assert order == [0, 1, 2]
    assert data[0] == timing_header(seq) and data[1] == timing_header(seq)
    img = np.frombuffer(data[2], dtype=np.uint16).reshape(shape)
    assert (img == pattern.image(SEED, seq, shape, bits)).all()


def test_tb_event_timing_message_layout():
    """TimingBEB::_event reads the TimingHeader of subframe 0 and the event timing message of
    the last subframe (TimingDef::createDataETM)."""
    seq = 9
    data, order = subframes(frame('tb', seq))
    assert order == [0, 2]
    assert data[0] == timing_header(seq)
    etm = data[2]
    assert len(etm) == 48
    p = lambda i, bits: int(pattern.pattern(SEED, seq, i, bits))
    pid, rates, slot, beam = struct.unpack_from('<QHBB', etm, 0)
    assert (pid, rates, slot, beam) == (PID, p(2, 16), p(3, 3), p(4, 8))
    assert list(struct.unpack_from('<18H', etm, 12)) == [p(5 + i, 16) for i in range(18)]
