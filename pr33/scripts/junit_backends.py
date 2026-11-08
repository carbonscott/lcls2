"""junit_backends.py JUNIT [TEST ...]: count the headless-browser testcases by status and recorded `backend`,
and the parity rows they tag; with TEST names, print those testcases' properties."""
import collections, sys
import xml.etree.ElementTree as ET
path, names = sys.argv[1], set(sys.argv[2:])
by, rows = collections.Counter(), collections.Counter()
for tc in ET.parse(path).getroot().iter('testcase'):
    st = next(({'failure': 'failed'}.get(c.tag, c.tag) for c in tc if c.tag in ('failure', 'error', 'skipped')), 'passed')
    props = [(p.get('name'), p.get('value', '')) for p in tc.iter('property')]
    be = '+'.join(sorted({v for k, v in props if k == 'backend'})) or 'none'
    if '[chromium' in tc.get('name', ''):
        by[(st, be)] += 1
        rows[be] += len({v for k, v in props if k == 'parity'})
    if tc.get('name') in names:
        print('  %s::%s  %s  %s' % (tc.get('classname'), tc.get('name'), st,
                                    [(k, v[:48]) for k, v in props if k in ('parity', 'backend')]))
if not names:
    print('%s: [chromium] testcases by (status, backend): %s' % (path.rsplit('/', 1)[-1], dict(sorted(by.items()))))
    print('  parity rows tagged by passing-or-not [chromium] tests, by backend: %s' % dict(rows))
