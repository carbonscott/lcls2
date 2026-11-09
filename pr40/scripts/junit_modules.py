"""junit_modules.py JUNIT REGEX: per test module whose name matches REGEX, its testcases by status and the backends they
recorded (junit `backend` properties), and the parity rows they tag."""
import collections, re, sys
import xml.etree.ElementTree as ET
path, pat = sys.argv[1], re.compile(sys.argv[2])
mods = collections.OrderedDict()
for tc in ET.parse(path).getroot().iter('testcase'):
    m = tc.get('classname', '').rsplit('.', 1)[-1]
    if not pat.search(m):
        continue
    st = next(({'failure': 'failed'}.get(x.tag, x.tag) for x in tc if x.tag in ('failure', 'error', 'skipped')), 'passed')
    props = [(p.get('name'), p.get('value', '')) for p in tc.iter('property')]
    d = mods.setdefault(m, [collections.Counter(), collections.Counter(), set()])
    d[0][st] += 1
    for b in {v for k, v in props if k == 'backend'}:
        d[1][b] += 1
    d[2] |= {v for k, v in props if k == 'parity'}
tot = collections.Counter()
for m, (st, be, rows) in mods.items():
    tot.update(st)
    print('  %-42s %-22s rows %4d  backend %s' % (m, ', '.join('%d %s' % (n, s) for s, n in sorted(st.items())), len(rows),
                                                ', '.join('%s x%d' % kv for kv in sorted(be.items())) or '-'))
print('  %d modules: %s' % (len(mods), dict(sorted(tot.items()))))
