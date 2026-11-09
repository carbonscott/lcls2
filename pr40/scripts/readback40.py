"""readback40.py WRITES.json: read back, not through the web server, what the browser run left:
  "pv:<PV>" or "pv:<PV>.<field>": with p4p (PV Access, the loopback env of sim_env.sh);
  "cdb:<hutch>/<alias>/<device>:<a.b>": from the config DB stand-in over HTTP (127.0.0.1:47321, /ws/configDB/...);
  "scan:<PV>.<field>": a PV the server's hsdPs scan left (not the browser), read with p4p."""
import json, os, sys, urllib.request
from p4p.client.thread import Context
from psdaq.webgui.netguard import require_loopback_pva_env
want = json.load(open(sys.argv[1]))
c = Context('pva', conf=require_loopback_pva_env(os.environ), useenv=False)
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
ok = True
for k, w in want.items():
    kind, _, name = k.partition(':')
    if kind in ('pv', 'scan'):
        pv, _, f = name.partition('.')
        v = c.get(pv, timeout=5.0)
        if f:
            for part in f.split('.'):
                v = v[part]
        elif hasattr(v, 'raw') and 'value' in v.raw:
            v = v.raw.value
        how = 'pvget'
    elif kind == 'cdb':
        path, _, field = name.partition(':')
        with op.open('http://127.0.0.1:47321/ws/configDB/get_configuration/%s/' % path, timeout=10) as r:
            out = json.loads(r.read())
        v = out['value']
        for part in field.split('.'):
            v = v[part]
        how = 'config DB'
    else:
        raise SystemExit('unknown key %s' % k)
    same = float(v) == float(w)
    ok &= same
    who = 'the server\'s scan left' if kind == 'scan' else 'the browser left'
    print('  %-9s %-48s = %-8s %s %-8s %s' % (how, name, v, who, w, 'ok' if same else 'DIFFERS'))
c.close()
print('READBACK', 'PASS' if ok else 'FAIL', '(%d values)' % len(want))
sys.exit(0 if ok else 1)
