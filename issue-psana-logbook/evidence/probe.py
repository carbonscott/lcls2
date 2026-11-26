# probe.py XTC_DIR: open a recorded run from files on disk, the way an offline job does, and count its events.
import sys, time
t0 = time.time()
from psana import DataSource
print("probe: DataSource(exp='mfxsim0001', run=1, dir=%s)" % sys.argv[1], flush=True)
ds = DataSource(exp="mfxsim0001", run=1, dir=sys.argv[1])
n = 0
for run in ds.runs():
    for evt in run.events():
        n += 1
print("probe: read %d events from disk in %.1f s" % (n, time.time() - t0), flush=True)
