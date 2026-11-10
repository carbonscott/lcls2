"""fg23.py MINE OTHER OUTDIR: forgeries of a programs record by record edits only (no file written, no hash computed):
FG2 my record with its gui_witness.json swapped for OTHER's (OTHER's content entry, the file unchanged);
FG3 FG2 plus OTHER's xtc2 files and its logs of the HPS chain, wave8pvs, lclsBldServer and the TPR programs."""
import json, os, sys, re
mine, other, out = json.load(open(sys.argv[1])), json.load(open(sys.argv[2])), sys.argv[3]
def wit(r): return [f for f in r['files'] if f.endswith('gui_witness.json')]
def put(tag, rec):
    d = os.path.join(out, tag); os.makedirs(d, exist_ok=True)
    p = os.path.join(d, os.path.basename(sys.argv[1]).replace('-cycle-', f'-cycle-{tag}-'))
    json.dump(rec, open(p, 'w'), indent=1); print(tag, 'wrote', p, 'files', len(rec['files']))
fg2 = json.loads(json.dumps(mine))
for f in wit(fg2):
    fg2['files'].remove(f); fg2['content'].pop(f, None)
for f in wit(other):
    fg2['files'].append(f); fg2['content'][f] = other['content'][f]
put('fg2', fg2)
fg3 = json.loads(json.dumps(fg2))
pat = re.compile(r'\.xtc2$|:(hpsbldsvc|hpsbldcpa|hpsbldcas|wave8pvs|lclsbldsvc|tprtrig|enc_trig)\.log$')
add = [f for f in other['files'] if pat.search(f) and f not in fg3['files']]
for f in add:
    fg3['files'].append(f); fg3['content'][f] = other['content'][f]
print('FG3 adds', len(add), 'files of the other run:', [os.path.basename(f) for f in add])
put('fg3', fg3)
