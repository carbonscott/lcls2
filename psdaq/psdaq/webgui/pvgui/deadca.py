"""Web copy of psdaq/cas/deadca.py (deadtime of each XPM link for one readout group), as a pvgui page.

    deadca [-v] base partition shelf          (the PyQt program's arguments)

Mirrors deadca.Ui_MainWindow.setupUi: 32 PvDblArrayW cells, element i of <base>:XPM:<shelf>:PART:<partition>:DeadFLnk
in deadca's own format(q[i], '4f') (deadca.PvDblArray.update); links 0-13 in columns 0-1 and 16-20 in columns 2-3,
each named by <base>:XPM:<shelf>:LinkLabel<n> read once at start (QLabel(pv.get())), INH-0..3 (entries 28-31) in
columns 2-3 below.  Like the PyQt program, cells 14, 15 and 21-27 are built and updated but never laid out: they sit
in a hidden box.
"""

import argparse

from psdaq.webgui.pvgui import Page


def parse(argv):
    p = argparse.ArgumentParser(prog='deadca', description='simple pv monitor gui')
    p.add_argument('-v', '--verbose', action='store_true')
    p.add_argument('base')
    p.add_argument('partition')
    p.add_argument('shelf')
    return p.parse_args(argv)


def build(argv):
    a = parse(argv)
    pvbase = a.base + ':XPM:' + a.shelf + ':'
    ppvbase = pvbase + 'PART:' + a.partition + ':'
    page = Page('deadca', 'XPM:' + a.shelf + '\tPART:' + a.partition)      # deadca.py setWindowTitle
    page.xpm_prefix = pvbase[:-1]
    dead = ppvbase + 'DeadFLnk'
    cells = [page.add({'type': 'text', 'id': 'Ui_MainWindow.PvDblArrayW#%d' % i, 'pv': dead, 'fmt': 'arr',
                       'spec': '4f', 'index': i}) for i in range(32)]
    rows = [[None] * 4 for _ in range(14)]
    placed = set()

    def put(r, c, node):
        rows[r][c] = node
    for i in range(14):
        put(i, 0, page.add({'type': 'label', 'pv_once': pvbase + 'LinkLabel%d' % i, 'text': ''}))
        put(i, 1, cells[i])
        placed.add(i)
    for j in range(16, 21):
        put(j - 16, 2, page.add({'type': 'label', 'pv_once': pvbase + 'LinkLabel%d' % j, 'text': ''}))
        put(j - 16, 3, cells[j])
        placed.add(j)
    for j in range(28, 32):
        put(j - 22, 2, page.add({'type': 'label', 'text': 'INH-%d' % (j - 28)}))
        put(j - 22, 3, cells[j])
        placed.add(j)
    page.unplaced = [i for i in range(32) if i not in placed]
    hidden = page.add({'type': 'box', 'dir': 'v', 'hidden': True, 'children': [cells[i] for i in page.unplaced]})
    page.tree = {'type': 'box', 'dir': 'v', 'children': [page.add({'type': 'grid', 'rows': rows}), hidden]}
    page.dead_pv = dead
    return page
