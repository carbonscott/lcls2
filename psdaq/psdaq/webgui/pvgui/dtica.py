"""Web copy of psdaq/cas/dtica.py (a DTI's allocation and status for its slots 3-7), as a pvgui page.

    dtica [-v] base               (the PyQt program's argument: the DTI PV prefix, e.g. DAQ:LAB2:DTI)

Mirrors dtica.Ui_MainWindow.setupUi: tabs Slot-3 .. Slot-7 of DtiAllocation, then tabs Slot-3 .. Slot-7 of
DtiStatistics, each on <base>:<slot>:.
DtiAllocation: for each upstream link i (0-6) a PvEditCheckList of 9 exclusive boxes None, 0 .. 7 on
UsLinkPartition<i> (box UsLinkPartition+1 is checked when the PV changes; a click puts its index - 1) and 7 boxes of
the downstream links j, each column exclusive (a QButtonGroup per downstream link): when any UsLinkFwdMask<i> changes,
the box (i, j) of every set bit j is checked; a click checks its box and puts all seven UsLinkFwdMask<i> from the
checked box of each column (DtiAllocation.update).
DtiStatistics: LblMask BpLinkUp (1 bit), UsLinkUp, DsLinkUp (7 bits: disabled boxes), PvPushButton CountClear
(puts 1, then 0), PvIntTable 'Upstream Link Stats' (8 arrays x 7 links) and 'Downstream Link Stats' (3 x 7), whose
cells show '{0:.4f}' of each element (pvedit.PvIntRow writes '%d' only for a Python int; PV Access arrays arrive as
numpy arrays, so the PyQt cells show '{0:.4f}' too), and PvLabel QpllLock, MonClkRate [MHz], TimLinkUp, TimRefClk [MHz],
TimFrRate [kHz] in pvedit.PvLabel's text.
"""

import argparse

from psdaq.webgui.pvgui import Page, Sites

NUsLinks = 7                                                         # dtica.py:7-9
NDsLinks = 7
NPartitions = 8
US_STATS = (['UsWrFifoD', 'UsRdFifoD', 'dUsIbEvt', 'UsObSent', 'UsObRecv', 'dUsRxFull', 'dUsRxInh', 'dUsRxErrs'],
            ['FifoWr', 'FifoRd', 'IbEvt', 'CtlOut', 'CtlIn', 'Full', 'InhEvts', 'RxErrs'])
DS_STATS = (['dDsRxErrs', 'dDsRxFull', 'dDsObSent'], ['RxErrs', 'Full', 'MBytes'])
LABELS = [('QpllLock', {}), ('MonClkRate', {'scale': 1.e-6, 'units': 'MHz'}), ('TimLinkUp', {}),
          ('TimRefClk', {'scale': 1.e-6, 'units': 'MHz'}), ('TimFrRate', {'scale': 1.e-3, 'units': 'kHz'})]


def parse(argv):
    p = argparse.ArgumentParser(prog='dtica', description='simple pv monitor gui')
    p.add_argument('base', help='pv base to monitor')
    p.add_argument('-v', '--verbose', action='store_true')
    return p.parse_args(argv)


def lbl(text):
    return {'type': 'label', 'text': text}


def allocation(page, sites, pvbase):
    """DtiAllocation (dtica.py:93-158)."""
    rows = [[lbl('US'), None, lbl('Partition')] + [None] * 8 + [lbl('DS Links')] + [None] * (NDsLinks - 1),
            [None, None, lbl('None')] + [lbl('%d' % i) for i in range(NPartitions)] + [lbl('%d' % i) for i in range(NUsLinks)]]
    for i in range(NUsLinks):
        pv = pvbase + 'UsLinkPartition%d' % i
        boxes = [sites.add('PvEditCheckList.cb', None, {'type': 'exclbox', 'pv': pv, 'index': b, 'offset': -1,
                                                        'group': pv}) for b in range(NPartitions + 1)]
        cells = [sites.add('DtiAllocation.cb', None, {'type': 'fwdcell', 'slot': pvbase, 'i': i, 'j': j,
                                                      'pv': pvbase + 'UsLinkFwdMask%d' % i})
                 for j in range(NDsLinks)]
        rows.append([lbl('%d' % i), None] + boxes + cells)
    for i in range(NUsLinks):
        page.write_pvs.add(pvbase + 'UsLinkFwdMask%d' % i)
    return {'type': 'grid', 'rows': rows}


def statistics(page, sites, pvbase):
    """DtiStatistics (dtica.py:160-192)."""
    masks = []
    for k, (name, bits) in enumerate((('BpLinkUp', 1), ('UsLinkUp', NUsLinks), ('DsLinkUp', NDsLinks))):
        boxes = [sites.add('DtiStatistics.LblMask@%d' % (k + 1), None, {'type': 'maskdisp', 'pv': pvbase + name,
                                                                        'bit': b}) for b in range(bits)]
        masks.append({'type': 'box', 'dir': 'h', 'children': [lbl(name)] + boxes})
    kids = [{'type': 'box', 'dir': 'h', 'children': masks},
            sites.add('DtiStatistics.PvPushButton', pvbase + 'CountClear', {'type': 'pvbutton', 'pv': pvbase + 'CountClear',
                                                                            'label': 'CountClear'})]
    for k, (title, (pvs, names), length) in enumerate((('Upstream Link Stats', US_STATS, NUsLinks),
                                                       ('Downstream Link Stats', DS_STATS, NDsLinks))):
        rows = []
        for pv, name in zip(pvs, names):
            rows.append([lbl(name)] + [sites.add('DtiStatistics.PvIntTable@%d' % (k + 1), None,
                                                 {'type': 'text', 'pv': pvbase + pv, 'fmt': 'introw', 'index': j,
                                                  'init': ''}) for j in range(length)])
        kids.append({'type': 'group', 'title': title, 'children': [{'type': 'grid', 'rows': rows}]})
    for k, (name, args) in enumerate(LABELS):
        kids.append({'type': 'box', 'dir': 'h', 'children': [
            lbl(name), sites.add('DtiStatistics.PvLabel@%d' % (k + 1), pvbase + name,
                                 {'type': 'text', 'pv': pvbase + name, 'fmt': 'pvlabel', 'args': args})]})
    return {'type': 'box', 'dir': 'v', 'children': kids}


def build(argv):
    a = parse(argv)
    title = a.base
    page = Page('dtica', title)                                     # dtica.py:220 setWindowTitle(title)
    sites = Sites()
    S = 'Ui_MainWindow.'
    tabsets = []
    for name, make in (('alloctab', allocation), ('statstab', statistics)):
        tabs = []
        for i in range(3, 8):
            child = make(page, sites, title + ':%d:' % i)
            tabs.append({'title': 'Slot-%d' % i, 'child': child,
                         'node': sites.add(S + '%s.tab[Slot-%d]' % (name, i), None, {'type': 'tab'})})
        tabsets.append({'type': 'tabs', 'tabs': tabs, 'current': 0})
    sites.assign(page)
    for t in tabsets:
        for tab in t['tabs']:
            tab['id'] = tab.pop('node')['id']
    page.tree = {'type': 'box', 'dir': 'v', 'children': [lbl('Allocation'), tabsets[0], lbl('Status'), tabsets[1]]}
    page.sim_pid_pv = title + ':SIM:PID'                           # simdti's own PV (a DTI IOC does not serve it)
    return page


def act(page, put, node, value):
    """A downstream-link box click (DtiAllocation.update): value = the checked upstream link of each of the 7
    columns (-1: none) as the page shows them after the click; puts UsLinkFwdMask0..6 of the box's slot."""
    if node['type'] != 'fwdcell':
        raise ValueError('no action for %s' % node['type'])
    if not isinstance(value, list) or len(value) != NDsLinks:
        raise ValueError('a downstream-link click needs the checked row of each of the %d columns' % NDsLinks)
    usmask = [0] * NUsLinks
    for j, i in enumerate(value):
        i = int(i)
        if i >= 0:
            usmask[i] |= 1 << j
    done = []
    for i in range(NUsLinks):
        pv = node['slot'] + 'UsLinkFwdMask%d' % i
        put(pv, usmask[i])
        done.append([pv, usmask[i]])
    return done
