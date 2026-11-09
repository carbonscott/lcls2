"""junit_pick.py JUNIT REGEX: the status and time of each testcase whose <module>::<name> matches REGEX, then the
counts."""
import collections, re, sys
import xml.etree.ElementTree as ET
path, pat = sys.argv[1], re.compile(sys.argv[2])
c = collections.Counter()
for tc in ET.parse(path).getroot().iter('testcase'):
    n = tc.get('classname', '').rsplit('.', 1)[-1] + '::' + tc.get('name', '')
    if not pat.search(n):
        continue
    st = next(({'failure': 'failed'}.get(x.tag, x.tag) for x in tc if x.tag in ('failure', 'error', 'skipped')), 'passed')
    c[st] += 1
    print('  %-80s %-7s %5.1f s' % (n, st, float(tc.get('time', 0))))
print('  %s' % dict(sorted(c.items())))
