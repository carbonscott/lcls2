"""readback37.py WRITES.json: read back with p4p (PV Access, loopback env of sim_env.sh), not through the web server,
the PVs the browser run wrote and left: {"PV": value} or {"PV.field": value} for a structure field."""
import json, os, sys
from p4p.client.thread import Context
from psdaq.webgui.netguard import require_loopback_pva_env
want = json.load(open(sys.argv[1]))
c = Context('pva', conf=require_loopback_pva_env(os.environ), useenv=False)
names = sorted({k.split('.', 1)[0] for k in want})
got = dict(zip(names, c.get(names, timeout=5.0)))
ok = True
for k, w in want.items():
    pv, _, f = k.partition('.')
    v = got[pv]
    if f:
        v = v[f]
    elif hasattr(v, 'raw') and 'value' in v.raw:
        v = v.raw.value
    if isinstance(v, dict) or hasattr(v, 'todict'):
        v = v.todict() if hasattr(v, 'todict') else v
        v = v.get('index', v.get('value', v)) if isinstance(v, dict) else v
    same = float(v) == float(w)
    ok &= same
    print('  pvget %-44s = %-10s  the browser left %-10s %s' % (k, v, w, 'ok' if same else 'DIFFERS'))
c.close()
print('READBACK', 'PASS' if ok else 'FAIL', '(%d PVs)' % len(want))
sys.exit(0 if ok else 1)
