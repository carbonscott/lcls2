#!/usr/bin/env python3
"""before.py BASE_COVERAGE_PY REPO EVIDENCE FORGED FORGE_LOG: the forged evidence dirs of forge.sh, checked by
agentify's coverage.py (8830147da, before this PR) in the same checkout at the same HEAD, so the records' sha
is HEAD under both rules. Prints, per case, the rows the old rules drop, against the rows the case must drop."""
import importlib.util, os, re, sys
src, repo, ev, forged, log = sys.argv[1:6]
spec = importlib.util.spec_from_file_location('coverage_base', src)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def proven(d):
    r = m.check(repo, evidence_path=d)
    return {x['row'] for x in r['rows'] if x['ok'] and x['status'] in ('RUN', 'STAND-IN')}, r


base, r0 = proven(ev)
print(f'coverage.py of 8830147da ({src}) at HEAD {r0["sha"][:9]} of {repo}')
print(f'real records ({r0["records"]}): proven rows {len(base)}: {" ".join(sorted(base))}')
n = held = 0
for name, drops in re.findall(r'^CASE (\S+) \(must drop: (\S+)\)', open(log).read(), re.M):
    ok, r = proven(os.path.join(forged, name))
    dropped = sorted(base - ok)
    want = sorted(x for x in drops.split(',') if x != '-')
    if not want:
        verdict = 'no row to drop: ' + ('OK' if not dropped else 'MISMATCH')
    elif set(want) <= set(dropped):
        held += 1
        verdict = 'dropped before this PR too\n  why: ' + '; '.join(
            x['text'][:300] for x in r['rows'] if x['row'] in want)
    else:
        verdict = 'ACCEPTED before this PR: still proves ' + ' '.join(sorted(set(want) - set(dropped)))
    n += bool(want)
    print(f'BEFORE {name}: dropped=[{" ".join(dropped)}] want=[{" ".join(want)}] {verdict}')
print(f'BEFORE_SUMMARY: of {n} forgeries, {held} dropped their row under the old rules, {n - held} still proved it')
