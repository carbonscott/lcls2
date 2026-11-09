"""Web copy of psdaq/cas/pvatable.py (a grid of structure PV fields: --fields down, --bases across), as a pvgui page.

    pvatable --bases B1 [B2 ...] --fields PV.field[index] ... [-v]      (the PyQt program's arguments)

Mirrors PvScalarTable: the bases with their longest common prefix removed head the columns, the part after the '.'
of each field heads its row, and each cell is a pvatable.PvField on <base>:<PV>, element <field>[index] of the
structure: str(int(f)), or for an array its elements one per line.  Nothing on the page writes a PV.
"""

import argparse

from psdaq.webgui.pvgui import Page


def parse(argv):
    p = argparse.ArgumentParser(prog='pvatable', description='simple pv monitor gui')
    p.add_argument('--bases', nargs='+', default='DAQ:LAB2:HSD:DEV06_3E:A')
    p.add_argument('--fields', nargs='+', default='MONTIMING.trigcntsum')
    p.add_argument('-v', '--verbose', action='store_true')
    return p.parse_args(argv)


def build(argv):
    a = parse(argv)
    bases = a.bases if isinstance(a.bases, list) else [a.bases]
    fields = a.fields if isinstance(a.fields, list) else [a.fields]
    page = Page('pvatable', 'pvatable')                  # pvatable.py setWindowTitle("pvatable")
    ncommon = len(bases[0])                              # pvatable.py PvScalarTable: remove the common prefix
    for base in bases[1:]:
        while base[0:ncommon] != bases[0][0:ncommon]:
            ncommon -= 1
    names = [b[ncommon:] for b in bases]
    rows = [[None] + [page.add({'type': 'label', 'text': n}) for n in names]]
    k = 0
    cells = {}
    for i, field in enumerate(fields):                   # PvField(base, field) for each field, then each base
        args = field.split('.')[1].split('[')
        index = int(args[1].split(']')[0]) if len(args) > 1 else -1
        for j, base in enumerate(bases):
            cells[(i, j)] = page.add({'type': 'text', 'id': 'PvScalarTable.PvField#%d' % k,
                                      'pv': base + ':' + field.split('.')[0], 'fmt': 'pvfield', 'field': args[0],
                                      'index': index})
            k += 1
    for i, field in enumerate(fields):
        rows.append([page.add({'type': 'label', 'text': field.split('.')[1]})] + [cells[(i, j)] for j in range(len(bases))])
    page.write_pvs = set()
    page.sim_pid_pv = bases[0] + ':SIM:PID'              # a campaign simulator (simhsd) serves it; an HSD does not
    page.tree = {'type': 'group', 'title': 'PvScalarTable', 'children': [page.add({'type': 'grid', 'rows': rows})]}
    return page
