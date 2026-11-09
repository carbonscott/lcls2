"""pvcmp.py SRC WALKS: for every GUI spec whose web copy is a pvgui page, the page built with the walk's argv vs the
walk's rows: each mapped row whose walk instance has a PV must be a page node of the same id with the same PV."""
import collections, importlib, json, os, sys
from psdaq.webgui.parity import check_gui_parity as C, gui_rows, qapps
src, walks = sys.argv[1], sys.argv[2]
specs = C.load_specs()
tot = collections.Counter()
for e in qapps.scan(src, []):
    spec = specs.get(e['file'])
    if not spec or 'na' in spec or not spec.get('web'):
        continue
    name = spec['web'].rsplit('/', 1)[-1]
    if not os.path.isfile(os.path.join(src, 'webgui', 'pvgui', name + '.py')):
        continue
    walk = json.load(open(C.walk_path(spec, walks)))
    rows = gui_rows.make_rows(gui_rows.source_sites(src, e['file']), walk)
    mod = importlib.import_module('psdaq.webgui.pvgui.' + name)
    if getattr(mod, 'GET_AT_BUILD', False):
        fw = {}
        for dv in walk.get('devices', []):
            a = dv['args']
            if dv['module'] == 'simxpm' and '--fwbuild' in a:
                fw['%s:XPM:%s:FwBuild' % (a[a.index('-P') + 1], a[a.index('-x') + 1])] = a[a.index('--fwbuild') + 1]
        print('  fwbuild from the walk devices', fw)
        P = mod.build(walk['argv'], fwbuild=fw.get)
    else:
        P = mod.build(walk['argv'])
    ex = {}
    c = collections.Counter(); bad = []
    for r in rows:
        m = spec.get('mapping', {}).get(r['id'])
        if not m or 'na' in m:
            continue
        n = P.nodes.get(r['id'])
        if n is None:
            c['no node'] += 1; ex.setdefault('no node', r['id']); continue
        wp, np_ = r.get('pv'), n.get('pv')
        if wp is None and np_ is None:
            c['no pv either'] += 1
        elif wp is None:
            c['page pv only'] += 1; ex.setdefault('page pv only:' + n['type'], (r['id'], r.get('widget'), np_))
        elif np_ is None:
            c['walk pv only:' + n['type']] += 1
        elif wp == np_:
            c['same'] += 1
        else:
            c['DIFF'] += 1; bad.append((r['id'], wp, np_))
    tot.update(c)
    print(name, walk['argv'], dict(c))
    for k, v in ex.items():
        print('   e.g.', k, v)
    for b in bad[:10]:
        print('   DIFF', b)
print('TOTAL', dict(tot))
