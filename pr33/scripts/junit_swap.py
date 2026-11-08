"""junit_swap.py BASE REPL OUT: OUT = BASE with every testcase that REPL also has (same classname and name)
replaced by REPL's run of it.  Prints what was swapped."""
import sys
import xml.etree.ElementTree as ET
base, repl, out = sys.argv[1:4]
bt, rt = ET.parse(base), ET.parse(repl)
new = {(tc.get('classname'), tc.get('name')): tc for tc in rt.getroot().iter('testcase')}
swapped = 0
for suite in bt.getroot().iter('testsuite'):
    for i, tc in enumerate(list(suite)):
        k = (tc.get('classname'), tc.get('name'))
        if tc.tag == 'testcase' and k in new:
            suite.remove(tc)
            suite.insert(i, new.pop(k))
            swapped += 1
bt.write(out)
print('junit_swap: %d testcase(s) of %s replaced by their run in %s; %d not in the base -> %s' % (
    swapped, base.rsplit('/', 1)[-1], repl.rsplit('/', 1)[-1], len(new), out))
