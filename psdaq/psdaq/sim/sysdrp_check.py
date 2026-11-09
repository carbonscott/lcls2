"""sysdrp_check: read a hardware-free run's every stream with psana2 and check what the system DRPs
(drp_pva, epicsArch) recorded from their simulated sources, event by event.

    python -m psdaq.sim.sysdrp_check --dir <xtc dir> --exp tstx00001 --run 1 --seed 0x1234
                                     [--pva pvcam] [--epics] [--det fakecam]

--pva NAME: drp_pva's detector NAME recorded simxpm's camera PV (simxpm --camera-pv), whose every
update carries one L1Accept's time and the image simxpm.camera_image(seed, seq): pixels 0 and 1
the seq, the rest a pattern of seq, seed and position.  Every event must hold the image, the
image must be exactly camera_image(seed, its seq), and its seq must be the seq the PGP DRP
(--det, fakecam) recorded in the same event, so drp_pva matched each update to its own
L1Accept.  --self-test-offset K expects seq + K instead (the check must then fail).

--epics: epicsArch recorded the stand-in IOC's PVs (daq_sim up --epics): sim_const (PVA) must be
EPICS_CONST wherever psana2 has a value, sim_count (CA, +1 every 0.1 s) must never decrease,
and both must have values in at least one event.

--udp NAME: drp_udpencoder's detector NAME recorded the frames sim_udpencoder sent, one per
L1Accept (sim_udpencoder -T sim://): every event must hold a frame, the frame counts must rise
by exactly one per event and stay frameCount - seq constant (each frame matched to its own
L1Accept), and the value must be sim_udpencoder's test pattern, 200 for an odd frameCount, 100 for an even
one (sim_udpencoder.cc _loopbackSend).

Prints one JSON line of counts; exits 0 only if every check passes.  psana2's calibration DB
lookup is off and LCLS_CALIB_HTTP points at a dead loopback port unless set.
"""

import argparse
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


def check(xtcdir, exp, run, seed, pva=None, epics=False, det='fakecam', offset=0, max_report=5,
          udp=None):
    os.environ.setdefault('LCLS_CALIB_HTTP', 'http://127.0.0.1:9/calib_ws')
    import numpy as np
    from psana import DataSource
    from psdaq.sim.simxpm import camera_image
    ds = DataSource(exp=exp, run=run, dir=xtcdir, skip_calib_load='all')
    out = {'events': 0}
    problems = []

    def problem(text):
        if len(problems) < max_report:
            problems.append(text)
        out['problems total'] = out.get('problems total', 0) + 1

    for r in ds.runs():
        d = r.Detector(det) if det in r.detnames else None
        cam = r.Detector(pva) if pva and pva in r.detnames else None
        if pva and cam is None:
            problem(f'no detector {pva} in the run ({sorted(r.detnames)})')
        cnt = r.Detector('sim_count') if epics else None
        cst = r.Detector('sim_const') if epics else None
        enc = r.Detector(udp) if udp and udp in r.detnames else None
        if udp and enc is None:
            problem(f'no detector {udp} in the run ({sorted(r.detnames)})')
        last_count = None
        last_frame = frame_offset = None
        for evt in r.events():
            out['events'] += 1
            seq = None
            if d is not None:
                raw = d.raw.raw(evt)
                if raw is not None:
                    seq = int(raw[0, 4]) | (int(raw[0, 5]) << 16)
            if cam is not None:
                img = _raw(cam, evt)
                if img is None:
                    problem(f'event {out["events"]}: no {pva} image')
                else:
                    out['pva with data'] = out.get('pva with data', 0) + 1
                    flat = np.asarray(img).ravel()
                    iseq = int(flat[0]) | (int(flat[1]) << 16)
                    want = camera_image(seed, iseq + offset).ravel()
                    if flat.shape != want.shape or not (flat == want).all():
                        problem(f'event {out["events"]}: {pva} image (seq {iseq}) differs from '
                                f'camera_image(seed, {iseq + offset}) in '
                                f'{int((flat != want).sum()) if flat.shape == want.shape else "shape"} pixels')
                    elif seq is not None and iseq != seq:
                        problem(f'event {out["events"]}: {pva} image seq {iseq}, {det} seq {seq}')
                    else:
                        out['pva matched'] = out.get('pva matched', 0) + 1
                        out['pva shape'] = list(np.asarray(img).shape)
            if enc is not None:
                segs = enc.raw._segments(evt)
                if segs is None:
                    problem(f'event {out["events"]}: no {udp} frame')
                else:
                    out['udp with data'] = out.get('udp with data', 0) + 1
                    seg = segs[0]
                    frame = int(np.asarray(seg.frameCount).ravel()[0])
                    value = int(np.asarray(seg.encoderValue).ravel()[0])
                    good = value == (200 if frame & 1 else 100)
                    if last_frame is not None and frame != (last_frame + 1) & 0xffff:
                        problem(f'event {out["events"]}: {udp} frameCount {frame} after {last_frame}')
                        good = False
                    if seq is not None:
                        if frame_offset is None:
                            frame_offset = (frame - seq) & 0xffff
                        elif (frame - seq) & 0xffff != frame_offset:
                            problem(f'event {out["events"]}: {udp} frameCount {frame} for {det} seq {seq}, '
                                    f'offset {(frame - seq) & 0xffff} != {frame_offset}')
                            good = False
                    if value != (200 if frame & 1 else 100):
                        problem(f'event {out["events"]}: {udp} encoderValue {value} for frameCount {frame}')
                    if good:
                        out['udp matched'] = out.get('udp matched', 0) + 1
                    last_frame = frame
            if epics:
                c, k = cst(evt), cnt(evt)
                if c is not None:
                    out['epics const events'] = out.get('epics const events', 0) + 1
                    if float(c) != EPICS_CONST:
                        problem(f'event {out["events"]}: sim_const {c} != {EPICS_CONST}')
                if k is not None:
                    out['epics count events'] = out.get('epics count events', 0) + 1
                    k = float(k)
                    if last_count is not None and k < last_count:
                        problem(f'event {out["events"]}: sim_count went back from {last_count} to {k}')
                    last_count = k
                    out['epics count range'] = [out.get('epics count range', [k])[0], k]
    if pva and out.get('pva with data', 0) != out['events']:
        problem(f'{pva} has data in {out.get("pva with data", 0)} of {out["events"]} events')
    if udp and out.get('udp with data', 0) != out['events']:
        problem(f'{udp} has data in {out.get("udp with data", 0)} of {out["events"]} events')
    if epics and not (out.get('epics const events') and out.get('epics count events')):
        problem('epicsArch: sim_const or sim_count has no value in any event')
    out['problems'] = problems
    out['pass'] = not problems and out['events'] > 0
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
