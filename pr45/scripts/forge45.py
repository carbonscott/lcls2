"""forge45.py <ev> <rundir>: two copies of the evidence dir <ev> for the coverage negatives.
  <rundir>/ev-no-gpu-fakecam  every record but the one that lists det:drp_gpu:fakecam (the drp_gpu run's);
                              the CPU drp's fakecam record (det:drp:fakecam) stays
  <rundir>/ev-forged          the same, plus a copy of that drp record whose rows are renamed to
                              det:drp_gpu:fakecam and prog:drp_gpu (its files, hashes and run unchanged)
"""
import json, os, shutil, sys
ev, P = sys.argv[1:3]
recs = {n: json.load(open(os.path.join(ev, n))) for n in sorted(os.listdir(ev)) if n.endswith('.json')}
gpu = [n for n, r in recs.items() if 'det:drp_gpu:fakecam' in r['rows']]
drp = [n for n, r in recs.items() if 'det:drp:fakecam' in r['rows']]
a, b = os.path.join(P, 'ev-no-gpu-fakecam'), os.path.join(P, 'ev-forged')
for d in (a, b):
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
for n in recs:
    if n in gpu:
        print(f'left out {n}: {" ".join(recs[n]["rows"])}')
        continue
    for d in (a, b):
        shutil.copy(os.path.join(ev, n), d)
print(f'kept {drp[0]}: {" ".join(recs[drp[0]]["rows"])}')
r = dict(recs[drp[0]])
ren = {'det:drp:fakecam': 'det:drp_gpu:fakecam', 'prog:drp': 'prog:drp_gpu'}
r['rows'] = [ren.get(x, x) for x in r['rows']]
name = 'forged-' + drp[0]
json.dump(r, open(os.path.join(b, name), 'w'), indent=1)
print(f'ev-forged also holds {name}: {" ".join(r["rows"])} (files: '
      f'{", ".join(os.path.basename(f) for f in r["files"])})')
print(f'records: {len(os.listdir(a))} in ev-no-gpu-fakecam, {len(os.listdir(b))} in ev-forged')
