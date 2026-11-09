#!/usr/bin/env python3
"""showrec.py EVDIR TYPE: the evidence record of det:drp:TYPE in EVDIR: its rows, run and commit, and per file
the size and sha256 the writer recorded, and whether the file's first that-many bytes still hash the same now
(a log may have grown since; an xtc2 file may not)."""
import glob, hashlib, json, os, sys
ev, T = sys.argv[1], sys.argv[2]
for p in sorted(glob.glob(os.path.join(ev, '*.json'))):
    r = json.load(open(p))
    if 'det:drp:' + T in r['rows']:
        break
else:
    sys.exit('no record of det:drp:' + T)
print(f'{os.path.basename(p)}: rows {" ".join(r["rows"])}')
print(f'  run_id {r["run_id"]}, sha {r["sha"][:9]}, dirty {r["dirty"]}, host {r.get("host")}, job {r.get("job_id")}, kind {r.get("kind")}')
print(f'  {len(r["files"])} files: recorded bytes, sha256 | now: size, sha256 of the recorded bytes')
for f in r['files']:
    c = r['content'][f]
    with open(f, 'rb') as fh:
        h = hashlib.sha256(fh.read(c['bytes'])).hexdigest()
    size = os.path.getsize(f)
    same = 'same' if h == c['sha256'] else 'DIFFERENT'
    print(f'  {c["bytes"]:>8} B {c["sha256"][:12]} | {size:>8} B {same:<4}  {f.split("/p38b/")[-1].split("/covbind/")[-1]}')
