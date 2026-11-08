#!/bin/bash
# resha.sh SRC DST SHA: copy the evidence records in SRC to DST (a new dir) and set each copy's "sha" to SHA.
SRC=$1; DST=$2; SHA=$3
[ -d "$SRC" ] && [ -n "$DST" ] && [ ! -e "$DST" ] && [[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "usage: resha.sh SRC DST(new) SHA(40 hex)"; exit 2; }
mkdir -p "$DST" && cp -p "$SRC"/*.json "$DST"/
python3 - "$DST" "$SHA" <<'PY'
import glob, json, os, sys
dst, sha = sys.argv[1], sys.argv[2]
for p in sorted(glob.glob(os.path.join(dst, '*.json'))):
    d = json.load(open(p))
    old = d.get('sha')
    d['sha'] = sha
    json.dump(d, open(p, 'w'), indent=1, sort_keys=True)
    print('%s: sha %s -> %s (rows %s; files still present: %d/%d)' % (
        os.path.basename(p), old, sha, ' '.join(d['rows']), sum(os.path.exists(f) for f in d['files']), len(d['files'])))
PY
