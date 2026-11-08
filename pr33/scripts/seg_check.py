"""seg_check.py FILE... --seed S --expect N: psana2 read-back of each segment file of a multi-segment fakecam run.
psana's fakecam det.raw.raw() returns segment 0 only (test_detectors.cspad_cspadRawAlg_1_2_3), so xtc2_check
cannot read a file that holds segment 1; this reads det.raw._segments(evt) and checks every segment it finds:
w3 == seed, the payload pattern of xtc2_check, w2 (simxpm's L1 sequence) gap-free from 1."""
import argparse, os
os.environ.setdefault('LCLS_CALIB_HTTP', 'http://127.0.0.1:9/ws')
import numpy as np
from psana import DataSource
ap = argparse.ArgumentParser()
ap.add_argument('files', nargs='+'); ap.add_argument('--seed', type=lambda s: int(s, 0)); ap.add_argument('--expect', type=int)
a = ap.parse_args()
ok_all = True
for f in a.files:
    ds = DataSource(files=[f], skip_calib_load='all')
    run = next(ds.runs()); det = run.Detector('fakecam')
    n, per = 0, {}
    for evt in run.events():
        n += 1
        for sid, seg in (det.raw._segments(evt) or {}).items():
            w = np.ascontiguousarray(seg.array_raw).view(np.uint32).astype(np.uint64)
            d = per.setdefault(sid, {'n': 0, 'seeds': {}, 'pattern': 0, 'seq': []})
            d['n'] += 1
            s = int(w[0, 3]); d['seeds'][s] = d['seeds'].get(s, 0) + 1
            k = np.arange(4, w.shape[1], dtype=np.uint64); lanes = np.arange(w.shape[0], dtype=np.uint64)[:, None]
            want = (w[:, 3:4] + w[:, 0:1] + k[None, :] + (lanes << np.uint64(16))) & np.uint64(0xffffffff)
            d['pattern'] += bool((w[:, 4:] == want).all())
            d['seq'].append(int(w[0, 2]))
    parts = []
    for sid, d in sorted(per.items()):
        gapfree = d['seq'] == list(range(1, len(d['seq']) + 1))
        good = (d['n'] == n and set(d['seeds']) == {a.seed} and d['pattern'] == n and gapfree
                and (a.expect is None or n == a.expect))
        ok_all &= good
        parts.append('segment %d: data in %d, seeds %s, payload pattern ok %d, seq (w2) %s..%s gap-free %s' % (
            sid, d['n'], {('%#x' % k): v for k, v in d['seeds'].items()}, d['pattern'],
            d['seq'][0] if d['seq'] else None, d['seq'][-1] if d['seq'] else None, gapfree))
    ok_all &= bool(per) and (a.expect is None or n == a.expect)
    print('%s: run %d, L1Accept events %d (expected %s); %s' % (os.path.basename(f), run.runnum, n, a.expect, '; '.join(parts) or 'no fakecam segment'))
print('SEG_CHECK', 'PASS' if ok_all else 'FAIL')
