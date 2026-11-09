"""pyprobe.py <type>=<xtc2>...: what psana reads from files the CPU DRP recorded (the detectors psana knows,
then per file each detector's events and a hash of its raw arrays, first 400 events)"""
import hashlib, os, sys
os.environ.setdefault('LCLS_CALIB_HTTP', 'http://127.0.0.1:9/ws')   # as xtc2_check: contact no service
import numpy as np
import psana.detector.detectors as dd
from psana import DataSource
names = sorted(n for n in dir(dd) if not n.startswith('__'))
print(f'psana.detector.detectors: {len(names)} names; with "noOp": {[n for n in names if "noOp" in n]}')
for arg in sys.argv[1:]:
    typ, f = arg.split('=', 1)
    run = next(DataSource(files=f, skip_calib_load='all').runs())   # as xtc2_check: no calibration DB
    dets = {n: run.Detector(n) for n in sorted(run.detnames)}
    dets = {n: d for n, d in dets.items() if hasattr(d, 'raw') and hasattr(d.raw, 'raw')}
    h = {n: hashlib.sha1() for n in dets}
    k = {n: 0 for n in dets}
    nev = 0
    for evt in run.events():
        nev += 1
        for n, d in dets.items():
            a = d.raw.raw(evt)
            if a is not None:
                k[n] += 1
                h[n].update(np.ascontiguousarray(a).tobytes())
        if nev == 400:
            break
    for n, d in dets.items():
        print(f'{typ}: {n} ({type(d.raw).__name__}) {k[n]} of {nev} events with raw, sha1 {h[n].hexdigest()[:16]}')
