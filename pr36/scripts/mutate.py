#!/usr/bin/env python3
"""mutate.py SRC DST ROW MODE: copy the evidence records in SRC to DST (a new dir), then change the
copy of the record that proves ROW. MODE dirty: set its "dirty" to true. MODE empty: point its .xtc2
file at an empty file of the same name, made in DST-files/. MODE remove: leave every record that
lists ROW out of the copy. The records in SRC are not touched."""
import glob, json, os, sys
src, dst, row, mode = sys.argv[1:5]
if not (os.path.isdir(src) and not os.path.exists(dst) and mode in ('dirty', 'empty', 'remove')):
    sys.exit(__doc__)
os.makedirs(dst)
base = os.path.dirname(os.path.abspath(dst))
short = lambda p: os.path.relpath(p, base) if p.startswith(base + '/') else p
n = changed = 0
for p in sorted(glob.glob(os.path.join(src, '*.json'))):
    d = json.load(open(p))
    name = os.path.basename(p)
    if row in d.get('rows', []):
        changed += 1
        if mode == 'remove':
            print(f'{name}: left out  (rows {" ".join(d["rows"])})')
            continue
        if mode == 'dirty':
            print(f'{name}: dirty {d["dirty"]} -> True  (rows {" ".join(d["rows"])})')
            d['dirty'] = True
        else:
            k = [i for i, f in enumerate(d['files']) if f.endswith('.xtc2')][0]
            old = d['files'][k]
            new = os.path.join(dst + '-files', os.path.basename(old))
            os.makedirs(os.path.dirname(new), exist_ok=True)
            open(new, 'w').close()
            d['files'][k] = new
            print(f'{name}: files[{k}] {short(old)} ({os.path.getsize(old)} B)')
            print(f'    -> {short(new)} ({os.path.getsize(new)} B)')
    json.dump(d, open(os.path.join(dst, name), 'w'), indent=1, sort_keys=True)
    n += 1
print(f'{n} records copied to {short(os.path.abspath(dst))}; {changed} record(s) for {row} changed ({mode})')
sys.exit(0 if changed else 1)
