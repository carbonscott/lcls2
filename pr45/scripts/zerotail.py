"""zerotail.py <xtc2>: for the first events of a drp_gpu epixuhremu file, where the recorded pixels differ
from the expected calibration (xtc2_check's), and what they hold there"""
import os, sys
os.environ.setdefault('LCLS_CALIB_HTTP', 'http://127.0.0.1:9/ws')
import numpy as np
from psana import DataSource
from psdaq.sim.xtc2_check import _gpu_words, _pulse_id_from_time, GPU_TYPES
shape, calib = GPU_TYPES['epixuhremu']
run = next(DataSource(files=[sys.argv[1]], skip_calib_load='all').runs())
det = run.Detector('epixuhremu')
for n, evt in enumerate(run.events(), 1):
    flat = det.noOp.calib(evt).reshape(-1)
    clock = _pulse_id_from_time(evt.timestamp)
    c = next(c for c in range(clock, clock + 64) if (calib(_gpu_words(c, n, 0x1234, 4)) == flat[:8]).all())
    want = calib(_gpu_words(c, n, 0x1234, flat.size // 2))   # 2 pixels per word
    bad = np.nonzero(flat != want)[0]
    if bad.size:
        print(f'event {n}: {bad.size} of {flat.size} pixels differ, indices {bad[0]}..{bad[-1]} '
              f'({"one block" if bad[-1] - bad[0] + 1 == bad.size else "not one block"}, '
              f'{"to the end" if bad[-1] == flat.size - 1 else "not to the end"}), '
              f'recorded there: {np.unique(flat[bad])[:4]} (expected e.g. {want[bad[:2]]})')
    else:
        print(f'event {n}: every pixel as expected')
    if n >= 6:
        break
