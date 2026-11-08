"""rows5.py JUNIT WALK [MAPPING]: where the check_parity on PYTHONPATH puts the 5 rows of the widgets the
running PyQt GUI never builds (CGWMainTabs / CGWMainTabUser: control_gui/CGWMain.py:43 and :78 commented out)."""
import os, sys
from psdaq.webgui.parity import check_parity as cp, qt_walk
from psdaq.webgui.parity.enumerate_pyqt import default_src, enumerate_rows
junit, walk = sys.argv[1], sys.argv[2]
mapping = sys.argv[3] if len(sys.argv) > 3 else cp.DEFAULT_MAPPING
FIVE = ['CGWMainTabs.tab_bar.user', 'CGWMainTabs.tab_bar.expert', 'CGWMainTabUser.but_play',
        'CGWMainTabUser.but_record', 'CGWMainTabUser.but_stop']
src = default_src()
rows, _ = enumerate_rows(src)
rep = cp.check(rows, cp.load_mapping(mapping), cp.load_junit([junit]), False, qt_walk.load_walk(walk),
               qt_walk.source_digest(src))
where = {}
for r, e in rep['mapped']:
    where[r['id']] = 'MAPPED (counted in M) by %s' % e['test'].split('::')[-1]
for r, reason, v in rep['na']:
    where[r['id']] = 'not applicable (K): %s' % reason
for r, e, obs in rep.get('not_built', []):
    where[r['id']] = 'NOT BUILT (refused): %s' % obs
for r, e, st in rep['failing']:
    where[r['id']] = 'failing: %s' % st
for r in rep['unmapped']:
    where[r['id']] = 'unmapped'
rel = lambda f: f.replace(os.environ.get('R', '@') + '/', '')
print('check_parity %s, mapping %s' % (rel(cp.__file__), rel(os.path.abspath(mapping))))
print('  N = %d, M = %d, K = %d, ok %s' % (rep['N'], rep['M'], rep['K'], rep['ok']))
for rid in FIVE:
    print('  %-27s %s' % (rid, where.get(rid, '?')[:150]))
