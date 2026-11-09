"""Web copy of psdaq/cas/xpmpatt.py (XPM pattern statistics and the groups' trigger selection), as a pvgui page.

    xpmpatt pv              (the PyQt program's argument: an XPM prefix <PVBASE>:XPM:<n>; 'tmo' / 'rix' name
                             DAQ:NEH:XPM:6 / :1 as in xpmpatt.main, which this copy refuses: not a local XPM)

Mirrors xpmpatt.Ui_MainWindow.setupUi: the PatternTab (tabs Stats: pvedit.PvTableDisplay of <pv>:PATT:GROUPS,
rows Group0..7, a column per table label, '-' where a value equals colEmpty (0, 2^20-1, 2^20-1, 2^20-1, 0);
Coincidences: the 36 entries of <pv>:PATT:COINC value.Coinc for groups i <= j), then one 'Group <g>' tab per
group 0..7 with Triggers: L0Select (PvEditEvt) and DstSelect (PvEditDst) of <pv>:PART:<g>.
"""

import argparse

from psdaq.webgui.pvgui import Page, pv_input, pv_edit_evt, pv_edit_dst

NGroups = 8
STATS = ['Sum', 'First', 'Last', 'MinIntv', 'MaxIntv']      # the labels of PATT:GROUPS (pyxpm pvstats pattStats)
V20B = (1 << 20) - 1
COL_EMPTY = (0, V20B, V20B, V20B, 0)                        # xpmpatt.py PatternTab


def parse(argv):
    p = argparse.ArgumentParser(prog='xpmpatt', description='simple pv monitor gui')
    p.add_argument('pv')
    return p.parse_args(argv)


def evt_w(page, nid, pv, label=''):
    return pv_edit_evt(page, nid.split('[', 1)[0], pv)


def dst_w(page, nid, pv, label=''):
    return pv_edit_dst(page, nid.split('[', 1)[0], pv)


def tabs(page, tid, items, current=0):
    out = []
    for title, child in items:
        t = {'title': title, 'child': child, 'id': '%s.tab[%s]' % (tid, title)}
        page.nodes[t['id']] = {'type': 'tab', 'id': t['id']}
        out.append(t)
    return {'type': 'tabs', 'id': tid, 'tabs': out, 'current': current}


def build(argv):
    a = parse(argv)
    if a.pv in ('tmo', 'rix'):
        raise SystemExit('pvgui xpmpatt: %r names a hutch XPM (DAQ:NEH:XPM:...); give a local XPM prefix' % a.pv)
    pvbase = a.pv + ':'
    page = Page('xpmpatt', 'xpmpatt')                       # setWindowTitle('xpmpatt')
    page.xpm_prefix = a.pv
    groups = pvbase + 'PATT:GROUPS'
    # Stats: PvTableDisplay(groups, ['Group0'..], COL_EMPTY): cells built column by column (pvedit.py:315-321)
    cells = {}
    k = 0
    for j, r in enumerate(STATS):
        for i in range(NGroups):
            cells[(i, j)] = page.add({'type': 'text', 'id': 'PatternTab.PvTableDisplay[%s]#%d' % (groups, k),
                                      'pv': groups, 'fmt': 'table', 'column': r, 'row': i, 'empty': COL_EMPTY[j]})
            k += 1
    rows = [[None] + [page.add({'type': 'label', 'text': r}) for r in STATS]]
    for i in range(NGroups):
        rows.append([page.add({'type': 'label', 'text': 'Group%d' % i})] + [cells[(i, j)] for j in range(len(STATS))])
    stats = page.add({'type': 'grid', 'rows': rows})
    # Coincidences: G0..G7 across and down, entry k of PATT:COINC value.Coinc at (i, j >= i)
    coinc = pvbase + 'PATT:COINC'
    grid = [[None] + [page.add({'type': 'label', 'text': 'G%d' % i}) for i in range(NGroups)]]
    k = 0
    for i in range(NGroups):
        row = [page.add({'type': 'label', 'text': 'G%d' % i})] + [None] * NGroups
        for j in range(i, NGroups):
            row[j + 1] = page.add({'type': 'text', 'id': 'PatternTab.w[%s]#%d' % (coinc, k), 'pv': coinc,
                                   'fmt': 'table', 'column': 'Coinc', 'row': k, 'empty': None})
            k += 1
        grid.append(row)
    box = page.add({'type': 'group', 'title': 'Group Coincidences', 'children': [page.add({'type': 'grid', 'rows': grid})]})
    patt = tabs(page, 'Ui_MainWindow.PatternTab', [('Stats', stats), ('Coincidences', box)])
    group_tabs = []
    for g in range(NGroups):                                 # addGroup(tw, pvbase+'PART:', g)
        pb = pvbase + 'PART:%d:' % g
        trg = page.add({'type': 'group', 'title': 'Triggers', 'children': [
            pv_input(page, evt_w, 'addGroup.LblEditEvt', pb, 'L0Select'),
            pv_input(page, dst_w, 'addGroup.LblEditDst', pb, 'DstSelect')]})
        group_tabs.append(('Group %d' % g, trg))
    tw = tabs(page, 'Ui_MainWindow.tw', group_tabs)
    page.tree = {'type': 'box', 'dir': 'v', 'children': [patt, tw]}
    return page
