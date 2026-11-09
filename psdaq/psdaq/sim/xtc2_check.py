"""xtc2_check: read a hardware-free DAQ run back with psana2 and check every event's data.

    python -m psdaq.sim.xtc2_check <run .xtc2 file> [--det fakecam] [--seed 0x1234] [--expect N]

The simulated detector (drp -D fakecam -d sim://, psdaq/drp/MemPoolSim.hh) writes, per lane, in
32-bit words: w0 = pulseId & 0xffffffff, w1 = pulseId >> 32, w2 = seq (L1Accepts since the last
GroupL0Reset, counted by simxpm), w3 = seed (the sim_seed the DRP read from the config DB at
Configure), w[k] = seed + w0 + k + (lane << 16) for k >= 4.  fakecam's raw array (det.raw.raw,
psdaq/drp/AreaDetector.cc) holds those bytes as uint16, shape (nlanes, 2 * words); rows are the
lanes of the DRP's -l mask in order (row i = lane i for -l 0x1, 0x3, ...).

Checks, for every L1Accept event psana2 yields: the detector's data is present; w3 == seed;
the w[k] pattern; w2 runs 1..N with no gap or repeat; the pulseId in w0/w1 rises strictly and
matches the event's own timestamp (psana2 does not expose the pulseId, but simxpm derives it
from the same time it puts in the timing header: pid = sec*14e6/13 + ns*14/13000, bumped by at
most a few ticks only to stay strictly increasing); with --expect, N == expect.  Prints the
counts and exits 0 only if every check passes.

For a BEB detector run with -d sim:// (psdaq/drp/MemPoolSim.cc, e.g. epix100) the payload is an
image whose pixel i (flattened) is psdaq.sim.pattern.pattern(seed, seq, i, bits): a hash of the
pixel's position plus seq and seed, masked to the type's bit depth, seq = 1, 2, ... per
L1Accept.  The check is then, event by event: data present, the type's image shape, and every
pixel exactly equal to pattern(seed, n, i, bits) for the n-th event, so a pixel the DRP put in
the wrong place fails.  --self-test-offset K expects pixel i to hold index i+K instead: the
check must then FAIL (it shows the check can fail).

psana2's calibration DB lookup is switched off (skip_calib_load='all') and LCLS_CALIB_HTTP points
at a dead loopback port unless already set, so reading the file contacts no service.
"""

import argparse
import json
import os
import sys


# BEB types: (raw image shape, pixel bit depth), as MemPoolSim's batcher table writes them
IMAGE_TYPES = {'epix100': ((704, 768), 14), 'epixm320': ((4, 192, 384), 15),
               'opal': ((1024, 1024), 12), 'piranha4': ((2048,), 12),
               'epixquad': ((4, 352, 384), 14)}
# BEB types whose data is not one image: {type: (events checker, description)}
WAVE8_SAMPLES = 256


def _wave8_event(det, evt, seed, n, offset=0, state=None):
    """(has data, [problems]) for one wave8 event (MemPoolSim.cc wave8Data, Wave8.cc)."""
    import numpy as np
    from psdaq.sim import pattern
    raws = [getattr(det.raw, 'raw_%d' % ch)(evt) for ch in range(8)]
    fex = {k: getattr(det.fex, k)(evt) for k in
           ['itrigCount', 'ptrigCount', 'intensity', 'posX', 'posY'] +
           ['integral_%d' % i for i in range(8)] + ['base_%d' % i for i in range(8)]}
    if any(r is None for r in raws) or any(v is None for v in fex.values()):
        return False, []
    problems = []
    N = WAVE8_SAMPLES
    for ch, raw in enumerate(raws):
        want = pattern.pattern(seed, n, np.arange(ch * N, (ch + 1) * N) + offset, 16)
        if raw.shape != (N,) or not (raw == want).all():
            bad = int((raw != want).sum()) if raw.shape == (N,) else raw.size
            problems.append(f'raw_{ch}: {bad} of {N} samples differ (shape {raw.shape})')
    base = 8 * N + offset

    def p(i, bits):
        return int(pattern.pattern(seed, n, base + i, bits))
    want = {'itrigCount': n & 0xffff, 'ptrigCount': n, 'intensity': float(p(16, 20)),
            'posX': p(17, 20) / 1024., 'posY': p(18, 20) / 1024.}
    for i in range(8):
        v = p(i, 24)
        want['integral_%d' % i] = v - (1 << 24) if v & (1 << 23) else v     # sign-extended
        want['base_%d' % i] = p(8 + i, 16)
    for k, w in want.items():
        if fex[k] != w:
            problems.append(f'fex.{k} {fex[k]!r} != {w!r}')
    return True, problems


def _wave8he_event(det, evt, seed, n, offset=0, state=None):
    """(has data, [problems]) for one wave8he event (MemPoolSim.cc wave8heData, Wave8HE.cc)."""
    import numpy as np
    from psdaq.sim import pattern
    raws = [getattr(det.raw, 'raw_%d' % ch)(evt) for ch in range(8)]
    names = (['peakPos_%d' % i for i in range(8)] + ['peakVal_%d' % i for i in range(8)] +
             ['base_%d' % i for i in range(8)] + ['integral_%d' % i for i in range(8)] +
             ['posPeakX', 'posPeakY', 'posIntegralX', 'posIntegralY'])
    fex = {k: getattr(det.fex, k)(evt) for k in names}
    if any(r is None for r in raws) or any(v is None for v in fex.values()):
        return False, []
    problems = []
    N = WAVE8_SAMPLES
    for ch, raw in enumerate(raws):
        want = pattern.pattern(seed, n, np.arange(ch * N, (ch + 1) * N) + offset, 16)
        if raw.shape != (N,) or not (raw == want).all():
            bad = int((raw != want).sum()) if raw.shape == (N,) else raw.size
            problems.append(f'raw_{ch}: {bad} of {N} samples differ (shape {raw.shape})')
    base = 8 * N + offset

    def p(i, bits):
        return int(pattern.pattern(seed, n, base + i, bits))

    def s24(v):                         # the DRP's 24-bit sign extension, then / 4
        return np.float32((v - (1 << 24) if v & (1 << 23) else v) / 4.0)
    want = {'posPeakX': np.float32(p(24, 20) / 1024.), 'posPeakY': np.float32(p(25, 20) / 1024.),
            'posIntegralX': np.float32(p(40, 20) / 1024.),
            'posIntegralY': np.float32(p(41, 20) / 1024.)}
    for i in range(8):
        want['peakPos_%d' % i] = p(i, 8)
        want['peakVal_%d' % i] = s24(p(8 + i, 24))
        want['base_%d' % i] = s24(p(16 + i, 24))
        want['integral_%d' % i] = s24(p(32 + i, 24))
    for k, w in want.items():
        if fex[k] != w:
            problems.append(f'fex.{k} {fex[k]!r} != {w!r}')
    return True, problems


# ts: the TimingData fields after pulseId and timeStamp, in order, as MemPoolSim.cc's
# TimingFields writes them: (name, elements, bits); element numbers continue from 2
TIMING_FIELDS = [('fixedRates', 10, 1), ('acRates', 6, 1), ('timeSlot', 1, 3),
                 ('timeSlotPhase', 1, 16), ('ebeamPresent', 1, 1), ('ebeamDestn', 1, 4),
                 ('ebeamCharge', 1, 16), ('ebeamEnergy', 4, 16), ('xWavelength', 2, 16),
                 ('dmod5', 1, 16), ('mpsLimits', 16, 1), ('mpsPowerClass', 16, 4),
                 ('sequenceValues', 18, 16), ('inhibitCounts', 8, 32)]


def _ts_event(det, evt, seed, n, offset=0, state=None):
    """(has data, [problems]) for one ts event (MemPoolSim.cc timingMessage, TimingSystem.cc):
    every TimingData field through ts_raw_2_1_0, and its eventcodes, inhibitCounts,
    destination, pulseId and timestamp methods."""
    import numpy as np
    from psdaq.sim import pattern
    info = det.raw._info(evt)
    if info is None:
        return False, []
    problems, want, element = [], {}, 2 + offset
    for name, count, bits in TIMING_FIELDS:
        want[name] = pattern.pattern(seed, n, np.arange(element, element + count, dtype=np.uint64),
                                     bits).astype(np.uint64)
        element += count
        got = np.atleast_1d(np.asarray(getattr(info, name))).astype(np.uint64)
        if got.shape != (count,) or not (got == want[name]).all():
            problems.append(f'{name} {got[:4].tolist()}... != {want[name][:4].tolist()}...')
    codes = det.raw.eventcodes(evt)
    seqv = want['sequenceValues']
    want_codes = [int((int(seqv[i >> 4]) >> (i & 0xf)) & 1) for i in range(288)]
    if list(codes) != want_codes:
        problems.append(f'eventcodes: {sum(a != b for a, b in zip(codes, want_codes))} of 288 differ')
    if not (np.asarray(det.raw.inhibitCounts(evt)).astype(np.uint64) == want['inhibitCounts']).all():
        problems.append('inhibitCounts differ')
    if det.raw.destination(evt) != int(want['ebeamDestn'][0]):
        problems.append(f'destination {det.raw.destination(evt)} != {int(want["ebeamDestn"][0])}')
    if det.raw.timestamp(evt) != evt.timestamp:
        problems.append(f'timestamp {det.raw.timestamp(evt):#x} != the event\'s {evt.timestamp:#x}')
    pid, clock = det.raw.pulseId(evt), _pulse_id_from_time(evt.timestamp)
    last = state.get('pid', -1) if state is not None else -1
    if not (pid > last and 0 <= pid - clock < 64):
        problems.append(f'pulseId {pid:#x} vs timestamp clock {clock:#x} (previous {last:#x})')
    if state is not None:
        state['pid'] = pid
    return True, problems


def _tb_event(det, evt, seed, n, offset=0, state=None):
    """(has data, [problems]) for one tb event (MemPoolSim.cc tbData; TimingBEB records it with
    TimingDef::createDataETM as ts_raw_2_1_0): the rate markers bit by bit (createDataETM stores
    bit i of the fixed rates at index 9-i, of the AC rates at 5-i), time slot, beam present and
    destination, the 18 sequence values and their event codes; every field the message does not
    carry 0; timestamp == the event's; pulseId the timing header's word: its low 56 bits rising
    with the timestamp, its service field (bits 56-59) L1Accept."""
    import numpy as np
    from psdaq.sim import pattern
    info = det.raw._info(evt)
    if info is None:
        return False, []

    def p(i, bits):
        return int(pattern.pattern(seed, n, i + offset, bits))
    rates, slot, beam = p(2, 16), p(3, 3), p(4, 8)
    seqv = [p(5 + i, 16) for i in range(18)]
    want = {'fixedRates': [(rates >> (9 - k)) & 1 for k in range(10)],
            'acRates': [(rates >> (10 + 5 - k)) & 1 for k in range(6)],
            'timeSlot': [slot], 'timeSlotPhase': [0], 'ebeamPresent': [beam & 1],
            'ebeamDestn': [beam >> 4], 'ebeamCharge': [0], 'ebeamEnergy': [0] * 4,
            'xWavelength': [0] * 2, 'dmod5': [0], 'mpsLimits': [0] * 16, 'mpsPowerClass': [0] * 16,
            'sequenceValues': seqv, 'inhibitCounts': [0] * 8}
    problems = []
    for name, w in want.items():
        got = np.atleast_1d(np.asarray(getattr(info, name))).astype(np.int64).tolist()
        if got != w:
            problems.append(f'{name} {got[:6]} != {w[:6]}')
    codes = det.raw.eventcodes(evt)
    want_codes = [int((seqv[i >> 4] >> (i & 0xf)) & 1) for i in range(288)]
    if list(codes) != want_codes:
        problems.append(f'eventcodes: {sum(a != b for a, b in zip(codes, want_codes))} of 288 differ')
    if det.raw.destination(evt) != beam >> 4:
        problems.append(f'destination {det.raw.destination(evt)} != {beam >> 4}')
    if int(info.timeStamp) != evt.timestamp:
        problems.append(f'timeStamp {int(info.timeStamp):#x} != the event\'s {evt.timestamp:#x}')
    word = det.raw.pulseId(evt)
    pid, clock = word & ((1 << 56) - 1), _pulse_id_from_time(evt.timestamp)
    last = state.get('pid', -1) if state is not None else -1
    if not (pid > last and 0 <= pid - clock < 64) or (word >> 56) & 0xf != 12:
        problems.append(f'pulseId {word:#x} vs timestamp clock {clock:#x} (previous {last:#x}, '
                        f'service {(word >> 56) & 0xf}, L1Accept 12)')
    if state is not None:
        state['pid'] = pid
    return True, problems


def _epixhremu_event(det, evt, seed, n, offset=0, state=None):
    """(has data, [problems]) for one epixhremu event: the frame EpixHRemu replays from the
    file daq_sim wrote (psdaq.sim.epixhremu_frame), as the DRP lays it out, every pixel."""
    from psdaq.sim import epixhremu_frame
    raw = det.raw.raw(evt)
    if raw is None:
        return False, []
    want = epixhremu_frame.expected(seed, 1, offset)[None]
    if raw.shape != want.shape:
        return True, [f'shape {raw.shape}, not {want.shape}']
    bad = int((raw != want).sum())
    return True, ([f'{bad} of {raw.size} pixels differ'] if bad else [])


def _tdet_words(raw):
    """A TDet payload as 32-bit words, per lane: (lanes, words)."""
    import numpy as np
    a = np.ascontiguousarray(raw)
    return a.reshape(a.shape[0], -1).view(np.uint32).astype(np.uint64)


def _jungfrauemu_event(det, evt, seed, n, offset=0, state=None):
    """(has data, [problems]) for one jungfrauemu event: JungfrauEmulator records each lane's
    DMA payload, the TDet words of MemPoolSim::fill, as one 512 x 1024 uint16 panel.  The
    interface's raw() adds random noise ('FOR DEBUGGING ONLY', psana jungfrauemu.py), so the
    words are checked through the AreaDetectorRaw.raw it overrides, and raw() itself only for
    its shape and a noise-sized difference."""
    import numpy as np
    from psana.detector.areadetector import AreaDetectorRaw
    base = AreaDetectorRaw.raw(det.raw, evt)
    if base is None:
        return False, []
    problems = []
    if base.shape[-2:] != (512, 1024):
        return True, [f'panel shape {base.shape}, not (..., 512, 1024)']
    w = _tdet_words(base.reshape(1, 512 * 1024))
    k = np.arange(4, w.shape[1], dtype=np.uint64)
    if int(w[0, 3]) != seed:
        problems.append(f'w3 {int(w[0, 3]):#x} != seed {seed:#x}')
    if int(w[0, 2]) != n:
        problems.append(f'w2 (seq) {int(w[0, 2])} != {n}')
    want = (np.uint64(seed) + w[0, 0] + k + np.uint64(offset)) & np.uint64(0xffffffff)
    if not (w[0, 4:] == want).all():
        problems.append(f'{int((w[0, 4:] != want).sum())} of {w.shape[1] - 4} payload words differ')
    pid, clock = int(w[0, 0]) | (int(w[0, 1]) << 32), _pulse_id_from_time(evt.timestamp)
    last = state.get('pid', -1) if state is not None else -1
    if not (pid > last and 0 <= pid - clock < 64):
        problems.append(f'pulseId {pid:#x} vs timestamp clock {clock:#x} (previous {last:#x})')
    if state is not None:
        state['pid'] = pid
    noisy = det.raw.raw(evt)
    if noisy is None or noisy.shape != base.shape:
        problems.append(f'raw() shape {None if noisy is None else noisy.shape} != {base.shape}')
    else:
        d = np.abs(noisy.astype(np.int64) - base.astype(np.int64))
        if np.mean(d < 100) < 0.99:
            problems.append('raw() differs from the panel by more than its noise')
    return True, problems


def _hrencoder_event(det, evt, seed, n, offset=0, state=None):
    """(has data, [problems]) for one hrencoder event (MemPoolSim.cc hrencoderData,
    HREncoder.cc): value() is the position; error_cnt, missedTrig_cnt and latches too."""
    from psdaq.sim import pattern
    value = det.raw.value(evt)
    if value is None:
        return False, []
    seg = det.raw._segments(evt)[0]
    p = [int(pattern.pattern(seed, n, i + offset, 32 if i == 0 else 8)) for i in range(4)]
    want = {'value': p[0] - (1 << 32) if p[0] & (1 << 31) else p[0],      # int32
            'error_cnt': p[1], 'missedTrig_cnt': p[2], 'latches': p[3]}
    got = {'value': int(value), 'error_cnt': int(seg.error_cnt),
           'missedTrig_cnt': int(seg.missedTrig_cnt), 'latches': int(seg.latches)}
    return True, [f'{k} {got[k]} != {w}' for k, w in want.items() if got[k] != w]


TT_PIXELS = 2048


def _tt_event(det, evt, seed, n, offset=0, state=None):
    """(has data, [problems]) for one tt event (MemPoolSim.cc ttData, TimeTool.cc): tt_raw_2_0_0
    has one field, image, the camera's region of interest as uint8 (TimeTool::_event records
    subframe 2 when its length is the config's ROI); every pixel vs pattern(seed, seq, i, 8),
    through image() and through the segment _info() returns."""
    import numpy as np
    from psdaq.sim import pattern
    image = det.raw.image(evt)
    if image is None:
        return False, []
    want = pattern.image(seed, n, (TT_PIXELS,), 8, offset)
    if image.dtype != np.uint8 or image.shape != want.shape:
        return True, [f'image {image.dtype} {image.shape}, not uint8 {want.shape}']
    problems = []
    if not (image == want).all():
        bad = np.flatnonzero(image != want)
        problems.append(f'{len(bad)} of {image.size} pixels differ, first at {int(bad[0])}: '
                        f'{int(image[bad[0]]):#x} != {int(want[bad[0]]):#x}')
    seg = det.raw._info(evt)
    if seg is None or not np.array_equal(np.asarray(seg.image), image):
        problems.append('_info(evt).image differs from image(evt)')
    return True, problems


EVENT_TYPES = {
    'tt': (_tt_event, f'every pixel of the {TT_PIXELS}-pixel uint8 region of interest '
                      '(tt_raw_2_0_0 image(), and _info().image) vs pattern(seed, seq, i, 8)'),
    'hrencoder': (_hrencoder_event, 'value() (the position), error_cnt, missedTrig_cnt and '
                                    'latches (hrencoder_raw_0_1_0) vs pattern'),
    'ts': (_ts_event, 'every TimingData field (ts_raw_2_1_0) vs pattern, eventcodes, '
                      'inhibitCounts, destination, timestamp == the event\'s, pulseId rising'),
    'tb': (_tb_event, 'the event timing message (TimingDef::createDataETM, ts_raw_2_1_0) vs '
                      'pattern: rate markers, time slot, beam, sequence values and event codes, '
                      'the rest 0; timestamp == the event\'s, pulseId rising'),
    'epixhremu': (_epixhremu_event, 'every pixel of the replayed frame (epixhremu_raw_0_0_1.raw) '
                                    'vs the frame daq_sim wrote'),
    'jungfrauemu': (_jungfrauemu_event, 'every TDet word of the 512 x 1024 panel '
                                        '(jungfrauemu_raw_0_1_0, AreaDetectorRaw.raw): seed, seq, '
                                        'pattern, pulseId; raw() shape and noise'),
    'wave8': (_wave8_event, f'8 raw waveforms of {WAVE8_SAMPLES} samples, each sample, integral, '
                            'baseline and fex value vs pattern'),
    'wave8he': (_wave8he_event, f'8 raw waveforms of {WAVE8_SAMPLES} samples, each sample and '
                                'each peak/baseline/integral/position fex value vs pattern'),
}


def check_events(path, det_name, kind, seed=None, expect=None, max_report=5, offset=0):
    """The per-event check of a BEB type in EVENT_TYPES; seed is required."""
    os.environ.setdefault('LCLS_CALIB_HTTP', 'http://127.0.0.1:9/ws')
    from psana import DataSource
    fn, what = EVENT_TYPES[kind]
    seed = 0x1234 if seed is None else seed
    r = {'file': path, 'detector': det_name, 'events': 0, 'with_data': 0, 'seed_ok': 0,
         'pattern_ok': 0, 'pulseid_ok': 0, 'pulseid_checked': 0, 'seeds': {}, 'shape': None,
         'first_seq': None, 'last_seq': None, 'seq_gap_free': None, 'problems': [],
         'check': what + (f', self-test offset {offset}' if offset else '')}
    ds = DataSource(files=[path], skip_calib_load='all')
    state = {}
    for run in ds.runs():
        r['run'] = run.runnum
        r['experiment'] = run.expt
        det = run.Detector(det_name)
        for evt in run.events():
            r['events'] += 1
            n = r['events']
            has, problems = fn(det, evt, seed, n, offset, state)
            if not has:
                if len(r['problems']) < max_report:
                    r['problems'].append(f'event {n}: no {det_name} data')
                continue
            r['with_data'] += 1
            if not problems:
                r['pattern_ok'] += 1
                r['seed_ok'] += 1
            elif len(r['problems']) < max_report:
                r['problems'].append(f'event {n}: ' + '; '.join(problems[:3]))
    n = r['events']
    r['first_seq'], r['last_seq'] = (1, n) if n else (None, None)
    r['seq_gap_free'] = r['pattern_ok'] == n
    r['seeds'] = {seed: r['seed_ok']}
    r['pass'] = bool(n > 0 and r['with_data'] == n and r['pattern_ok'] == n
                     and (expect is None or n == expect))
    if expect is not None and n != expect:
        r['problems'].append(f'{n} events, expected {expect}')
    return r


def check_image(path, det_name, shape, bits, seed=None, expect=None, max_report=5, offset=0):
    os.environ.setdefault('LCLS_CALIB_HTTP', 'http://127.0.0.1:9/ws')
    import numpy as np
    from psana import DataSource
    from psdaq.sim import pattern

    mask = (1 << bits) - 1
    r = {'file': path, 'detector': det_name, 'events': 0, 'with_data': 0, 'seed_ok': 0,
         'pattern_ok': 0, 'pulseid_ok': 0, 'pulseid_checked': 0, 'seeds': {}, 'shape': None,
         'first_seq': None, 'last_seq': None, 'check': f'per pixel, pattern(seed, seq, i, {bits})'
         + (f', self-test offset {offset}' if offset else ''),
         'seq_gap_free': None, 'problems': []}
    ds = DataSource(files=[path], skip_calib_load='all')
    for run in ds.runs():
        r['run'] = run.runnum
        r['experiment'] = run.expt
        det = run.Detector(det_name)
        for evt in run.events():
            r['events'] += 1
            n = r['events']
            raw = det.raw.raw(evt)
            if raw is None:
                if len(r['problems']) < max_report:
                    r['problems'].append(f'event {n}: no {det_name} data')
                continue
            r['with_data'] += 1
            r['shape'] = list(raw.shape)
            if seed is None:            # the seed this event's pixel 0 implies
                seed = (int(raw.flat[0]) - int(pattern.pattern(0, n, offset, 32))) & mask
            if tuple(raw.shape) != shape:
                if len(r['problems']) < max_report:
                    r['problems'].append(f'event {n}: shape {tuple(raw.shape)}, not {shape}')
                continue
            want = pattern.image(seed, n, shape, bits, offset)
            same = raw == want
            if bool(same.all()):
                r['pattern_ok'] += 1
                r['seed_ok'] += 1
            elif len(r['problems']) < max_report:
                bad = np.argwhere(~same)
                i0 = tuple(int(x) for x in bad[0])
                r['problems'].append(f'event {n}: {len(bad)} of {raw.size} pixels differ, first '
                                     f'at {i0}: {int(raw[i0]):#x} != {int(want[i0]):#x}')
    n = r['events']
    r['first_seq'], r['last_seq'] = (1, n) if n else (None, None)
    r['seq_gap_free'] = r['pattern_ok'] == n
    r['seeds'] = {seed if seed is not None else -1: r['seed_ok']}
    r['pass'] = bool(n > 0 and r['with_data'] == n and r['pattern_ok'] == n
                     and (expect is None or n == expect))
    if expect is not None and n != expect:
        r['problems'].append(f'{n} events, expected {expect}')
    return r


def check(path, det_name='fakecam', seed=None, expect=None, max_report=5, offset=0):
    kind = det_name.rsplit('_', 1)[0]
    if kind in IMAGE_TYPES:
        shape, bits = IMAGE_TYPES[kind]
        return check_image(path, det_name, shape, bits, seed, expect, max_report, offset)
    if kind in EVENT_TYPES:
        return check_events(path, det_name, kind, seed, expect, max_report, offset)
    os.environ.setdefault('LCLS_CALIB_HTTP', 'http://127.0.0.1:9/ws')
    import numpy as np
    from psana import DataSource

    r = {'file': path, 'detector': det_name, 'events': 0, 'with_data': 0, 'seed_ok': 0,
         'pattern_ok': 0, 'pulseid_ok': 0, 'pulseid_checked': 0, 'seeds': {}, 'shape': None,
         'first_seq': None, 'last_seq': None, 'seq_gap_free': None, 'problems': []}
    seqs, last_pid = [], -1
    ds = DataSource(files=[path], skip_calib_load='all')
    for run in ds.runs():
        r['run'] = run.runnum
        r['experiment'] = run.expt
        det = run.Detector(det_name)
        for evt in run.events():
            r['events'] += 1
            raw = det.raw.raw(evt)
            if raw is None:
                if len(r['problems']) < max_report:
                    r['problems'].append(f'event {r["events"]}: no {det_name} data')
                continue
            r['with_data'] += 1
            w = np.ascontiguousarray(raw).view(np.uint32).astype(np.uint64)  # (nlanes, words)
            r['shape'] = list(raw.shape)
            s = int(w[0, 3])
            r['seeds'][s] = r['seeds'].get(s, 0) + 1
            if seed is None or s == seed:
                r['seed_ok'] += 1
            elif len(r['problems']) < max_report:
                r['problems'].append(f'event {r["events"]}: w3 {s:#x} != seed {seed:#x}')
            k = np.arange(4, w.shape[1], dtype=np.uint64)
            lanes = np.arange(w.shape[0], dtype=np.uint64)[:, None]
            want = (w[:, 3:4] + w[:, 0:1] + k[None, :] + np.uint64(offset)
                    + (lanes << np.uint64(16))) & np.uint64(0xffffffff)
            same = bool((w[:, 4:] == want).all() and (w[:, :4] == w[0:1, :4]).all())
            if same:
                r['pattern_ok'] += 1
            elif len(r['problems']) < max_report:
                r['problems'].append(f'event {r["events"]}: payload pattern broken')
            pid = int(w[0, 0]) | (int(w[0, 1]) << 32)
            clock = _pulse_id_from_time(evt.timestamp)
            r['pulseid_checked'] += 1
            if pid > last_pid and 0 <= pid - clock < 64:
                r['pulseid_ok'] += 1
            elif len(r['problems']) < max_report:
                r['problems'].append(f'event {r["events"]}: pulseId {pid:#x} vs timestamp clock '
                                     f'{clock:#x} (previous {last_pid:#x})')
            last_pid = pid
            seqs.append(int(w[0, 2]))
    if seqs:
        r['first_seq'], r['last_seq'] = seqs[0], seqs[-1]
        r['seq_gap_free'] = seqs == list(range(1, len(seqs) + 1))
    n = r['events']
    r['pass'] = bool(n > 0 and r['with_data'] == n and r['seed_ok'] == n and r['pattern_ok'] == n
                     and r['pulseid_ok'] == n and r['seq_gap_free']
                     and (expect is None or n == expect))
    if expect is not None and n != expect:
        r['problems'].append(f'{n} events, expected {expect}')
    return r


def _pulse_id_from_time(timestamp):
    """simxpm's pulseId for an EPICS-epoch (seconds << 32 | nanoseconds) time (simxpm.timing_now)."""
    sec, ns = timestamp >> 32, timestamp & 0xffffffff
    return ((sec * 14000000) // 13 + (ns * 14) // 13000) & ((1 << 56) - 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog=__doc__.split('\n\n', 1)[1])
    parser.add_argument('file', help='the run\'s .xtc2 file (not the smalldata .smd.xtc2)')
    parser.add_argument('--det', default='fakecam', help='detector name (default %(default)s)')
    parser.add_argument('--seed', type=lambda s: int(s, 0), help='expected sim_seed (default: any, reported)')
    parser.add_argument('--expect', type=int, help='expected number of L1Accept events')
    parser.add_argument('--json', action='store_true', help='print the result as one JSON line')
    parser.add_argument('--self-test-offset', type=int, default=0, metavar='K',
                        help='expect pixel/sample/word i to hold the value of i+K (must FAIL)')
    args = parser.parse_args()
    r = check(args.file, args.det, args.seed, args.expect, offset=args.self_test_offset)
    if args.json:
        print(json.dumps(r))
    else:
        n = r['events']
        print(f'xtc2_check: {r["file"]}')
        print(f'  experiment {r.get("experiment")} run {r.get("run")} detector {r["detector"]} raw shape {r["shape"]}')
        if 'check' in r:                # a type checked against its pattern, field by field
            print(f'  L1Accept events {n}; with {r["detector"]} data {r["with_data"]}; '
                  f'events matching the pattern of seed {next(iter(r["seeds"]), -1):#x}: '
                  f'{r["pattern_ok"]}')
            print(f'  check: {r["check"]}{"" if args.expect is None else f"; expected {args.expect} events"}')
        else:
            print(f'  L1Accept events {n}; with {r["detector"]} data {r["with_data"]}; '
                  f'w3 == seed {r["seed_ok"]} (seeds seen {{{", ".join(f"{s:#x}: {c}" for s, c in r["seeds"].items())}}}); '
                  f'payload pattern ok {r["pattern_ok"]}; w0/w1 pulseId rising and == timestamp clock {r["pulseid_ok"]}/{r["pulseid_checked"]}')
            print(f'  seq (w2) {r["first_seq"]}..{r["last_seq"]} gap-free from 1: {r["seq_gap_free"]}'
                  f'{"" if args.expect is None else f"; expected {args.expect} events"}')
        for p in r['problems']:
            print('  problem:', p)
        print('  PASS' if r['pass'] else '  FAIL')
    return 0 if r['pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
