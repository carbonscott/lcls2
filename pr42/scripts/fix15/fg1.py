"""fg1.py SRC_RECORD OUTDIR HEADSHA: copy another commit's evidence record, change only its 'sha' (no file touched)"""
import json, sys, os
r = json.load(open(sys.argv[1]))
old = r['sha']; r['sha'] = sys.argv[3]
os.makedirs(sys.argv[2], exist_ok=True)
out = os.path.join(sys.argv[2], os.path.basename(sys.argv[1]).replace(old[:9], 'forged'))
json.dump(r, open(out, 'w'), indent=1)
print('FG1 wrote', out, 'sha', old[:9], '->', r['sha'][:9], 'rows', len(r['rows']), 'files', len(r['files']))
