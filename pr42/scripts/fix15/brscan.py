# brscan.py EVDIR...: for each evidence record, the (run, BeginRun) of its listed xtc2 files (D3 check)
import json, sys, glob, os
from psdaq.sim import coverage
bad = 0; n = 0
for d in sys.argv[1:]:
    for p in sorted(glob.glob(os.path.join(d, '*.json'))):
        rec = json.load(open(p)); n += 1
        runid = str(rec.get('run_id'))
        g = {}
        for f in rec.get('files', []):
            if f.endswith('.xtc2'):
                try:
                    c = coverage.xtc2_content(f)[1]
                except Exception as e:
                    c = {'run': 'ERR', 'beginrun': str(e)[:40]}
                g.setdefault((c['run'], c['beginrun']), []).append(os.path.basename(f))
        mine = {k for k in g if k[0] == runid}
        flag = 'MULTI' if len(mine) > 1 else 'ok'
        if len(mine) > 1: bad += 1
        print(f"{flag} {os.path.basename(p)[:60]} run_id={runid} " + '; '.join(f"{k[0]}@{k[1]}:{len(v)}" for k, v in g.items()))
print(f"records {n}, with >1 BeginRun of their run_id: {bad}")
