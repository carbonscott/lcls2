"""Every 0.5 s, for each exporter prometheus_targets() lists: the e2e's own call scrape(<target>, COUNTERS),
which since 71895fbda gets a (host, port) tuple as its port, next to scrape(port, COUNTERS, host)."""
import datetime, sys, time
from psdaq.sim import daq_sim as ds
while True:
    for t in ds.prometheus_targets(sys.argv[1]):
        host, port = t if isinstance(t, tuple) else ('127.0.0.1', t)   # tuples since 71895fbda, ints before
        why = []
        as_e2e = ds.scrape(t, ds.COUNTERS, errors=why)                  # what e2e.py:678-679 passes
        fixed = ds.scrape(port, ds.COUNTERS, host)                       # what the fix passes
        teb = {k.split('{')[0]: int(v) for k, v in fixed.items() if k.startswith('TEB_')}
        if teb:
            got = {k.split('{')[0]: int(v) for k, v in as_e2e.items() if k.startswith('TEB_')}
            print(datetime.datetime.utcnow().strftime('%H:%M:%S.%f')[:12], 'target', t, '| e2e call ->', got, why,
                  '| fixed call ->', teb, flush=True)
    time.sleep(0.5)
