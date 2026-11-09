"""sysdrp_check: read a hardware-free run's every stream with psana2 and check what the system DRPs
(drp_pva, epicsArch, drp_udpencoder) recorded from their simulated sources, event by event.

    python -m psdaq.sim.sysdrp_check --dir <xtc dir> --exp tstx00001 --run 1 --seed 0x1234
                                     [--pva pvcam] [--epics] [--udp encoder] [--det fakecam]

Each DRP writes its own stream (-s<N>-c000.xtc2).  psana2 reads each stream file on its own
(files=..., so it asks no run database for the file list) and the events are joined by their
timestamp to the PGP DRP's (--det, fakecam): those are the run's L1Accepts, and fakecam's seq
word (psdaq/psdaq/sim/xtc2_check.py) numbers them.

--pva NAME: drp_pva's detector NAME recorded simxpm's camera PV (simxpm --camera-pv), whose every
update carries one L1Accept's time and the image simxpm.camera_image(seed, seq): pixels 0 and 1
the seq, the rest a pattern of seq, seed and position.  Every L1Accept must have the image in
drp_pva's stream, the image must be exactly camera_image(seed, its seq), and its seq must be
fakecam's seq of the same L1Accept, so drp_pva matched each update to its own L1Accept.  An
L1Accept may have no image: drp_pva records the L1Accept without one when no update matched it
in time (it queues updates only once it has handled Enable, and counts timeouts); those are
counted here, and daq_sim cycle checks that drp_pva's own drp_match_count equals the number of
L1Accepts that have the image.  At least one must.
--self-test-offset K expects seq + K instead (the check must then fail).

--udp NAME: drp_udpencoder's detector NAME recorded the frames sim_udpencoder sent, one per
L1Accept (sim_udpencoder -T sim://): frameCount - seq must be the same for every L1Accept that has
a frame (frames matched in order, none repeated or out of place), and the value must
be sim_udpencoder's test pattern, 200 for an odd frameCount, 100 for an even one
(sim_udpencoder.cc _loopbackSend).

--epics: epicsArch recorded the stand-in IOC's CA PVs and simxpm's PVA count (daq_sim up --epics):
sim_const must be EPICS_CONST wherever psana2 has a value, sim_count (+1 every 0.1 s) and
sim_l0acc (simxpm's L0 accept count of the partition) must never decrease, sim_l0acc must never
exceed the run's L1Accepts, and all three must have values.

Prints one JSON line of counts; exits 0 only if every check passes.  psana2's calibration DB
lookup is off and LCLS_CALIB_HTTP points at a dead loopback port unless set.
"""

import argparse
import glob
import json
import os
import sys

EPICS_CONST = 1234.5                    # daq_sim.EPICS_CONST


def _raw(det, evt):
    """A pv detector's array: psana2 has two pv_raw_1_0_0 classes (raw() and value())."""
    for name in ('raw', 'value'):
        f = getattr(det.raw, name, None)
        if f is not None:
            return f(evt)
    return None


def _scalar(v):
    import numpy as np
    return int(np.asarray(v).ravel()[0])


def read_streams(xtcdir, exp, run, names):
    """({name: {timestamp: value}}, {name: stream file}) for the detectors in 'names'
    ({name: extractor(det, evt) -> value or None}), over every stream file of the run."""
    os.environ.setdefault('LCLS_CALIB_HTTP', 'http://127.0.0.1:9/calib_ws')
    from psana import DataSource
    out, where = {n: {} for n in names}, {}
    for path in sorted(glob.glob(os.path.join(xtcdir, f'{exp}-r{run:04d}-s*-c000.xtc2'))):
        ds = DataSource(files=path, skip_calib_load='all')
        for r in ds.runs():
            known = set(r.detnames) | {k[0] for k in getattr(r, 'epicsinfo', {})}   # epicsArch aliases
            here = {n: r.Detector(n) for n in names if n in known}
            if not here:
                continue
            for n in here:
                where[n] = os.path.basename(path)
            for evt in r.events():
                ts = int(evt.timestamp)
                for n, d in here.items():
                    out[n][ts] = names[n](d, evt)
    return out, where


def check(xtcdir, exp, run, seed, pva=None, epics=False, det='fakecam', offset=0, max_report=5,
          udp=None):
    import numpy as np
    from psdaq.sim.simxpm import camera_image

    def seq_of(d, evt):
        raw = d.raw.raw(evt)
        return None if raw is None else int(raw[0, 4]) | (int(raw[0, 5]) << 16)

    def image(d, evt):
        img = _raw(d, evt)
        return None if img is None else np.asarray(img)

    def frame(d, evt):
        segs = d.raw._segments(evt)
        return None if segs is None else (_scalar(segs[0].frameCount), _scalar(segs[0].encoderValue))

    names = {det: seq_of}
    if pva:
        names[pva] = image
    if udp:
        names[udp] = frame
    if epics:
        for n in ('sim_count', 'sim_const', 'sim_l0acc'):
            names[n] = lambda d, evt: d(evt)
    data, where = read_streams(xtcdir, exp, run, names)
    events = sorted((ts, s) for ts, s in data[det].items() if s is not None)   # the L1Accepts
    out = {'events': len(events), 'streams': where}
    problems = []

    def problem(text):
        if len(problems) < max_report:
            problems.append(text)
        out['problems total'] = out.get('problems total', 0) + 1

    if not events:
        problem(f'no {det} events in {xtcdir}')
    if pva:
        if pva not in where:
            problem(f'no stream has a detector {pva}')
        got = data[pva]
        out['pva events'] = len(got)
        for k, (ts, seq) in enumerate(events):
            img = got.get(ts)
            if img is None:
                out.setdefault('pva missing (first 5 seqs)', []).append(seq)
                continue
            out['pva with data'] = out.get('pva with data', 0) + 1
            flat = img.ravel()
            iseq = int(flat[0]) | (int(flat[1]) << 16)
            want = camera_image(seed, iseq + offset).ravel()
            if flat.shape != want.shape or not (flat == want).all():
                problem(f'L1Accept {k + 1}: {pva} image (seq {iseq}) differs from camera_image(seed, '
                        f'{iseq + offset})')
            elif iseq != seq:
                problem(f'L1Accept {k + 1}: {pva} image seq {iseq}, {det} seq {seq}')
            else:
                out['pva matched'] = out.get('pva matched', 0) + 1
                out['pva shape'] = list(img.shape)
    if udp:
        if udp not in where:
            problem(f'no stream has a detector {udp}')
        got, first = data[udp], None
        out['udp events'] = len(got)
        for k, (ts, seq) in enumerate(events):
            f = got.get(ts)
            if f is None:
                out.setdefault('udp missing (first 5 seqs)', []).append(seq)
                continue
            out['udp with data'] = out.get('udp with data', 0) + 1
            count, value = f
            if first is None:
                first = (count - seq) & 0xffff
            if (count - seq) & 0xffff != first:
                problem(f'L1Accept {k + 1}: {udp} frameCount {count} for seq {seq} (offset '
                        f'{(count - seq) & 0xffff}, first {first})')
            elif value != (200 if count & 1 else 100):
                problem(f'L1Accept {k + 1}: {udp} encoderValue {value} for frameCount {count}')
            else:
                out['udp matched'] = out.get('udp matched', 0) + 1
        out['udp frameCount - seq'] = first
    for k in ('pva', 'udp'):
        miss = out.pop(f'{k} missing (first 5 seqs)', [])
        if (k == 'pva' and pva) or (k == 'udp' and udp):
            out[f'{k} missing'] = len(miss)
            out[f'{k} missing seqs'] = miss[:5]
            if not out.get(f'{k} with data'):
                problem(f'{pva if k == "pva" else udp}: no L1Accept has its data')
    if epics:
        if 'sim_count' not in where:
            problem('no stream has the epicsArch variables sim_count/sim_const')
        consts = [v for _, v in sorted(data['sim_const'].items()) if v is not None]
        counts = [float(v) for _, v in sorted(data['sim_count'].items()) if v is not None]
        out['epics const events'], out['epics count events'] = len(consts), len(counts)
        out['epics count range'] = [counts[0], counts[-1]] if counts else None
        bad = [c for c in consts if float(c) != EPICS_CONST]
        if bad:
            problem(f'sim_const {bad[0]} != {EPICS_CONST} in {len(bad)} events')
        back = [(a, b) for a, b in zip(counts, counts[1:]) if b < a]
        if back:
            problem(f'sim_count went back {len(back)} times, e.g. {back[0][0]} -> {back[0][1]}')
        l0acc = [float(v) for _, v in sorted(data['sim_l0acc'].items()) if v is not None]
        out['epics l0acc events'] = len(l0acc)
        out['epics l0acc range'] = [l0acc[0], l0acc[-1]] if l0acc else None
        if any(b < a for a, b in zip(l0acc, l0acc[1:])):
            problem('sim_l0acc went back')
        if l0acc and l0acc[-1] > len(events):
            problem(f'sim_l0acc {l0acc[-1]} exceeds the run\'s {len(events)} L1Accepts')
        if not consts or not counts or not l0acc:
            problem('epicsArch: sim_const, sim_count or sim_l0acc has no value in any event')
    out['problems'] = problems
    out['pass'] = not problems and len(events) > 0
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m psdaq.sim.sysdrp_check',
                                     description=__doc__.split('\n\n')[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog=__doc__.split('\n\n', 1)[1])
    parser.add_argument('--dir', required=True, help='the run\'s xtc dir')
    parser.add_argument('--exp', required=True)
    parser.add_argument('--run', type=int, required=True)
    parser.add_argument('--seed', type=lambda s: int(s, 0), required=True)
    parser.add_argument('--pva', default=None, help='drp_pva detector name (e.g. pvcam)')
    parser.add_argument('--epics', action='store_true')
    parser.add_argument('--udp', default=None, help='drp_udpencoder detector name (e.g. encoder)')
    parser.add_argument('--det', default='fakecam')
    parser.add_argument('--self-test-offset', type=int, default=0)
    args = parser.parse_args(argv)
    res = check(args.dir, args.exp, args.run, args.seed, args.pva, args.epics, args.det,
                args.self_test_offset, udp=args.udp)
    print(json.dumps(res))
    return 0 if res['pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
