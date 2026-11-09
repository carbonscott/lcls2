"""pvnotcmp.py SRC WALKS: the mapped pvgui rows the PV check does not compare, by page and node type (writers marked)."""
import collections, importlib, json, os, sys
from psdaq.webgui.parity import check_gui_parity as C, gui_rows, qapps
src, walks = sys.argv[1], sys.argv[2]
WRITERS = {'pvcheck', 'pvint', 'pvcombo', 'mask', 'maskbit', 'seqsel', 'pvbutton', 'pvedit', 'exclbox', 'groupmask', 'fwdcell'}
specs = C.load_specs()
tot = collections.Counter()
for e in qapps.scan(src, []):
    spec = specs.get(e['file'])
    if not spec or 'na' in spec or not spec.get('web'):
        continue
    walk = json.load(open(C.walk_path(spec, walks)))
    rows = gui_rows.make_rows(gui_rows.source_sites(src, e['file']), walk)
    pv = C.page_pvs(src, spec, walk, rows)
    if pv is None:
        continue
    name = spec['web'].rsplit('/', 1)[-1]
    mod = importlib.import_module('psdaq.webgui.pvgui.' + name)
    page = mod.build(walk['argv'], fwbuild=C.walk_fwbuild(walk).get) if getattr(mod, 'GET_AT_BUILD', False) else mod.build(walk['argv'])
    c = collections.Counter()
    for r in rows:
        m = spec['mapping'].get(r['id'])
        if not m or 'test' not in m:
            continue
        n = page.nodes.get(r['id'])
        if n is None:
            c['no node'] += 1
        elif not r.get('pv'):
            w = n['type'] in WRITERS and not n.get('disabled')
            c[('walk no PV', n['type'] + (' (writes)' if w else ''))] += 1
        elif not n.get('pv'):
            c[('page node no PV', n['type'])] += 1
    tot.update(c)
    print(name, 'compared %d same %d differ' % (pv['same'], len(pv['differ'])), dict(c))
print('TOTAL not compared', sum(tot.values()), dict(tot))
print('writers not compared', sum(v for k, v in tot.items() if isinstance(k, tuple) and '(writes)' in k[1]))
