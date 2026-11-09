"""Web copy of psdaq/cas/pvant.py (a grid of PvInt fields: --fields down, --bases across), as a pvgui page.

    pvant --bases B1 [B2 ...] --fields F1 [F2 ...]       (the PyQt program's arguments)

Mirrors PvScalarTable: the bases with their longest common prefix removed head the columns, the last ':' part
of each field heads its row, and each cell is a pvedit.PvInt on <base>:<field>: it shows int(value) (an array:
' %f' per element) and, as PvInt.setPv does nothing, editing it changes no PV.
"""

import argparse
import re

from psdaq.webgui.pvgui import Page


def parse(argv):
    p = argparse.ArgumentParser(prog='pvant', description='simple pv monitor gui')
    p.add_argument('--bases', nargs='+', default='DAQ:LAB2:HSD:DEV06_3E:A')
    p.add_argument('--fields', nargs='+', default='Top:TimingFrameRx:sofCount')
    p.add_argument('-v', '--verbose', action='store_true')
    return p.parse_args(argv)


def build(argv):
    a = parse(argv)
    bases = a.bases if isinstance(a.bases, list) else [a.bases]
    fields = a.fields if isinstance(a.fields, list) else [a.fields]
    page = Page('pvant', 'pvatable')                     # pvant.py:72 setWindowTitle("pvatable")
    ncommon = len(bases[0])                              # pvant.py:19-22
    for base in bases[1:]:
        while base[0:ncommon] != bases[0][0:ncommon]:
            ncommon -= 1
    names = [b[ncommon:] for b in bases]
    rows = [[None] + [page.add({'type': 'label', 'text': n}) for n in names]]
    for f in fields:
        rows.append([page.add({'type': 'label', 'text': f.split(':')[-1]})] +
                    [page.add({'type': 'pvint', 'id': 'PvScalarTable.PvInt[%s:%s]' % (b, f), 'pv': '%s:%s' % (b, f),
                               'noop': True}) for b in bases])
    page.write_pvs = set()                               # PvInt.setPv: pass
    xpms = set(re.match(r'^(.*?:XPM:\d+)(:|$)', b).group(1) if re.match(r'^(.*?:XPM:\d+)(:|$)', b) else None
               for b in bases)
    page.xpm_prefix = xpms.pop() if len(xpms) == 1 else None     # for /api/pvgui/info: the XPM the PVs belong to
    page.tree = {'type': 'group', 'title': 'PvScalarTable', 'children': [page.add({'type': 'grid', 'rows': rows})]}
    return page
