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
image whose every pixel is (seed + seq) masked to the type's bit depth, seq = 1, 2, ... per
L1Accept; the check is then: data present, the type's image shape, every pixel equal to
(seed + n) & mask for the n-th event.

psana2's calibration DB lookup is switched off (skip_calib_load='all') and LCLS_CALIB_HTTP points
at a dead loopback port unless already set, so reading the file contacts no service.
"""

import argparse
import json
import os
import sys


# BEB types: (raw image shape, pixel bit depth), as MemPoolSim's batcher table writes them
IMAGE_TYPES = {'epix100': ((704, 768), 14)}


def check_image(path, det_name, shape, bits, seed=None, expect=None, max_report=5):
    os.environ.setdefault('LCLS_CALIB_HTTP', 'http://127.0.0.1:9/ws')
    import numpy as np
    from psana import DataSource

    mask = (1 << bits) - 1
    r = {'file': path, 'detector': det_name, 'events': 0, 'with_data': 0, 'seed_ok': 0,
         'pattern_ok': 0, 'pulseid_ok': 0, 'pulseid_checked': 0, 'seeds': {}, 'shape': None,
         'first_seq': None, 'last_seq': None,
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
            v = int(raw.flat[0]) & mask
            if seed is not None:
                want = (seed + n) & mask
            else:
                want = v
            if tuple(raw.shape) == shape and bool(((raw & mask) == want).all()):
                r['pattern_ok'] += 1
                r['seed_ok'] += 1
            elif len(r['problems']) < max_report:
                bad = int(((raw & mask) != want).sum())
                r['problems'].append(f'event {n}: shape {tuple(raw.shape)}, {bad} pixels != '
                                     f'{want:#x} (pixel[0] {v:#x})')
    n = r['events']
    r['first_seq'], r['last_seq'] = (1, n) if n else (None, None)
    r['seq_gap_free'] = r['pattern_ok'] == n
    r['seeds'] = {seed if seed is not None else -1: r['seed_ok']}
    r['pass'] = bool(n > 0 and r['with_data'] == n and r['pattern_ok'] == n
                     and (expect is None or n == expect))
    if expect is not None and n != expect:
        r['problems'].append(f'{n} events, expected {expect}')
    return r


def check(path, det_name='fakecam', seed=None, expect=None, max_report=5):
    if det_name.rsplit('_', 1)[0] in IMAGE_TYPES:
        shape, bits = IMAGE_TYPES[det_name.rsplit('_', 1)[0]]
        return check_image(path, det_name, shape, bits, seed, expect, max_report)
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
            want = (w[:, 3:4] + w[:, 0:1] + k[None, :] + (lanes << np.uint64(16))) & np.uint64(0xffffffff)
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
    args = parser.parse_args()
    r = check(args.file, args.det, args.seed, args.expect)
    if args.json:
        print(json.dumps(r))
    else:
        n = r['events']
        print(f'xtc2_check: {r["file"]}')
        print(f'  experiment {r.get("experiment")} run {r.get("run")} detector {r["detector"]} raw shape {r["shape"]}')
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
