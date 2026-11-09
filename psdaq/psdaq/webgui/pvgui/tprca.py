"""Web copy of psdaq/cas/tprca.py (a TPR's input and its 14 readout channels), as a pvgui page.

    tprca [-v] pv            (the PyQt program's arguments: the TPR PV prefix, e.g. DAQ:XCS:TPR)

Mirrors tprca.Ui_MainWindow.setupUi: tab Input (ACCSEL, LINKSTATE (display), RXERRS (display), RXPOL, FRAME RATE,
RXCLK RATE (displays, '{:g}'), IRQENA, EVTCNT), then one tab CH<i> per channel 0..13: Event (tprca.PvEditEvt: RSEL
selects FRATE / ARATE + ATS / SEQIDX + SEQBIT / XPART), Destn (DSTSEL and the 16 DESTNS bits, which a click writes
from all 16 boxes as tprca.PvDstTab.update does), Rate ('{:.2f}'), Mode, Delay, Width ('{:g}'), Polarity.  tprca's own
widget classes: a combo puts its index if it differs from the PV (PvEditCmb.setValue), an int / double field puts
int(text) / float(text) when editing finishes, the text fields start at "0" and show str(int(q)) / fmt.format(q).
"""

import argparse

from psdaq.webgui.pvgui import Page
from psdaq.configdb.tsdef import fixedRates, acRates, acTS

NReadoutChannels = 14                                                  # tprca.py:10-24
accSel = ['LCLS-I', 'LCLS-II']
linkStates = ['Down', 'Up']
rxpols = ['Normal', 'Inverted']
modes = ['Disable', 'Trigger', '+Readout', '+BSA']
polarities = ['Neg', 'Pos']
dstsel = ['Any', 'Exclude', 'Include']
evtsel = ['Fixed Rate', 'AC Rate', 'Sequence', 'Partition']
seqIdxs = ['s%u' % i for i in range(18)]
seqBits = ['b%u' % i for i in range(16)]
partitions = ['P%u' % i for i in range(8)]
ndestn = 16


def parse(argv):
    p = argparse.ArgumentParser(prog='tprca', description='simple pv monitor gui')
    p.add_argument('-v', '--verbose', action='store_true')
    p.add_argument('pv')
    return p.parse_args(argv)


def cmb(page, nid, pv, choices, disabled=False):
    return page.add({'type': 'pvcombo', 'id': nid, 'pv': pv, 'choices': list(choices), 'disabled': disabled})


def edit(page, nid, pv, conv, fmt, spec=None, disabled=False):
    n = {'type': 'pvedit', 'id': nid, 'pv': pv, 'conv': conv, 'fmt': fmt, 'init': '0', 'disabled': disabled}
    if spec:
        n['spec'] = spec
    return page.add(n)


def lbl(page, text):
    return page.add({'type': 'label', 'text': text})


def build(argv):
    a = parse(argv)
    P = a.pv
    page = Page('tprca', P)
    S = 'Ui_MainWindow.'
    rows = [[lbl(page, 'ACCSEL'), cmb(page, S + 'PvEditCmb@1[%s:ACCSEL]' % P, P + ':ACCSEL', accSel)],
            [lbl(page, 'LINKSTATE'), cmb(page, S + 'PvCmb[%s:LINKSTATE]' % P, P + ':LINKSTATE', linkStates, True)],
            [lbl(page, 'RXERRS'), edit(page, S + 'PvInt[%s:RXERRS]' % P, P + ':RXERRS', 'int', 'int', disabled=True)],
            [lbl(page, 'RXPOL'), cmb(page, S + 'PvEditCmb@2[%s:RXPOL]' % P, P + ':RXPOL', rxpols)],
            [lbl(page, 'FRAME RATE [Hz]'), edit(page, S + 'PvDbl@1[%s:FRAMERATE]' % P, P + ':FRAMERATE', 'float',
                                                'pyfmt', '{:g}', True)],
            [lbl(page, 'RXCLK RATE [MHz]'), edit(page, S + 'PvDbl@2[%s:RXCLKRATE]' % P, P + ':RXCLKRATE', 'float',
                                                 'pyfmt', '{:g}', True)],
            [lbl(page, 'IRQENA'), edit(page, S + 'PvEditInt@1[%s:IRQENA]' % P, P + ':IRQENA', 'int', 'int')],
            [lbl(page, 'EVTCNT'), edit(page, S + 'PvEditInt@2[%s:EVTCNT]' % P, P + ':EVTCNT', 'int', 'int')]]
    tabs = [('Input', page.add({'type': 'grid', 'rows': rows}))]
    for i in range(NReadoutChannels):
        c = '%s:CH%u:' % (P, i)
        # PvEditEvt (tprca.py:190-197) and PvEvtTab (166-188): RSEL selects the stack page
        rsel = cmb(page, 'PvEditEvt.evtcmb[%sRSEL]' % c, c + 'RSEL', evtsel)
        stack = page.add({'type': 'stack', 'select': rsel['id'], 'children': [
            cmb(page, 'PvEvtTab.PvEditCmb@1[%sFRATE]' % c, c + 'FRATE', fixedRates),
            page.add({'type': 'box', 'dir': 'v', 'children': [
                cmb(page, 'PvEvtTab.PvEditCmb@2[%sARATE]' % c, c + 'ARATE', acRates),
                cmb(page, 'PvEvtTab.PvEditCmb@3[%sATS]' % c, c + 'ATS', acTS)]}),
            page.add({'type': 'box', 'dir': 'v', 'children': [
                cmb(page, 'PvEvtTab.PvEditCmb@4[%sSEQIDX]' % c, c + 'SEQIDX', seqIdxs),
                cmb(page, 'PvEvtTab.PvEditCmb@5[%sSEQBIT]' % c, c + 'SEQBIT', seqBits)]}),
            cmb(page, 'PvEvtTab.PvEditCmb@6[%sXPART]' % c, c + 'XPART', partitions)]})
        evt = page.add({'type': 'box', 'dir': 'v', 'children': [rsel, stack]})
        # PvEditDst (215-224) and PvDstTab (199-213): a click puts the mask of all 16 boxes
        dst = page.add({'type': 'box', 'dir': 'v', 'children': [
            cmb(page, 'PvEditDst.selcmb[%sDSTSEL]' % c, c + 'DSTSEL', dstsel),
            page.add({'type': 'mask', 'pv': c + 'DESTNS', 'nomon': True, 'cols': 4,
                      'bits': [{'id': 'PvDstTab.chkB[%sDESTNS]#%d' % (c, b), 'label': 'D%d' % b} for b in range(ndestn)]})]})
        rows = [[lbl(page, 'Event'), evt], [lbl(page, 'Destn'), dst],
                [lbl(page, 'Rate'), edit(page, S + 'PvEditDbl@1[%sRATE]' % c, c + 'RATE', 'float', 'pyfmt', '{:.2f}')],
                [lbl(page, 'Mode'), cmb(page, S + 'PvEditCmb@3[%sMODE]' % c, c + 'MODE', modes)],
                [lbl(page, 'Delay [sec]'), edit(page, S + 'PvEditDbl@2[%sDELAY]' % c, c + 'DELAY', 'float', 'pyfmt', '{:g}')],
                [lbl(page, 'Width [sec]'), edit(page, S + 'PvEditDbl@3[%sWIDTH]' % c, c + 'WIDTH', 'float', 'pyfmt', '{:g}')],
                [lbl(page, 'Polarity'), cmb(page, S + 'PvEditCmb@4[%sPOL]' % c, c + 'POL', polarities)]]
        tabs.append(('CH%u' % i, page.add({'type': 'grid', 'rows': rows})))
    out = []
    for title, child in tabs:
        t = {'title': title, 'child': child, 'id': S + 'tw.tab[%s]' % title}
        page.nodes[t['id']] = {'type': 'tab', 'id': t['id']}
        out.append(t)
    page.tree = {'type': 'tabs', 'id': S + 'tw', 'tabs': out, 'current': 0}
    page.sim_pid_pv = P + ':SIM:PID'
    # PVs tprca reads that tprcas (and so simtpr) does not serve: CH12 / CH13 have no DELAY, WIDTH, POL
    page.sim_absent = {'%s:CH%u:%s' % (P, i, x) for i in (12, 13) for x in ('DELAY', 'WIDTH', 'POL')}
    return page
