"""dump_pages.py OUTDIR: the page tree and nodes of each pvgui page with the arguments of the parity walks (no server)."""
import importlib, json, os, sys
out = sys.argv[1]; os.makedirs(out, exist_ok=True)
ARGS = {'deadca': ['DAQ:SIM', '5', '0'], 'partca': ['DAQ:SIM:XPM:0:PART:5'], 'xpmpatt': ['DAQ:SIM:XPM:0'],
        'tprca': ['DAQ:SIM:TPR'], 'hsdpva': ['DAQ:SIM:HSD:1_1B:A', 'DAQ:SIM:HSD:1_1B:B'], 'dtica': ['DAQ:SIM:DTI'],
        'pvatable': ['--bases', 'DAQ:SIM:HSD:1_DA:A', 'DAQ:SIM:HSD:1_DA:B', '--fields', 'MONTIMING.trigcntsum',
                     'MONTIMING.timframecnt', 'MONPGP.txcntsum', 'MONPGP.rxcnt[2]', 'MONRAWBUF.freesz']}
for name, argv in ARGS.items():
    P = importlib.import_module('psdaq.webgui.pvgui.' + name).build(argv)
    with open(os.path.join(out, name + '.json'), 'w') as f:
        json.dump({'tree': P.tree, 'nodes': P.nodes}, f, indent=0, default=str)
    types = {}
    for nid, n in P.nodes.items():
        types.setdefault(n['type'], []).append(nid)
    print(name, {t: len(v) for t, v in types.items()})
