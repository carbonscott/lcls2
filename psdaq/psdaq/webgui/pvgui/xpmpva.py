"""Web copy of psdaq/cas/xpmpva.py (the XPM monitor), as a pvgui page.

    xpmpva [--nopatt] [--nohier] pv [pv ...]       (the PyQt program's arguments: XPM prefixes <PVBASE>:XPM:<n>)

Mirrors xpmpva.Ui_MainWindow.setupUi: a combo of the XPMs selects one QTabWidget per XPM (QStackedWidget), whose tabs
depend on the XPM's FwBuild (read once when the page is built, as setupUi does): Global (PvPAddr, PvCString FwBuild,
UsRxEnable / CuRxEnable, ModuleInit / Inhibit / TagStream, RecClk / FbClk / BpClk), CuTiming (FwBuild has 'xtpg':
the timing counters of Cu:, the XTPG fields, the four MMCM) or UsTiming, AMC0 / AMC1 (ATCA) or QSFP0 / QSFP1 (FwBuild
has Kcu1500 or C1100: four links each, else seven) with the 13 rows of link widgets (FrontPanelAMC), PLLs (ATCA),
DeadTime (DeadFLnk of each group per link), Groups/EventCodes (XpmGroups: master and L0 input rate of each group,
the 32 sequence event codes, and the sequence engines' Ena / Dis / Dump), Pattern (unless --nopatt: PATT:L0Select,
PATT:GROUPS, PATT:COINC), SFPs or QSFPs (PvTableDisplay of SFPSTATUS / QSFPSTATUS) and PathTimer.  Each display shows
the text the PyQt widget's update() writes (pvgui.text_of): PvLabel, PvCString, PvLinkId (xpm_link_id, without the
reverse name lookup of a host address: it shows the address in hex, as xpm_utils.hostName does when the lookup fails),
PvPAddr (the timing tree position), PvDblArray '.4f' and PvIntArray 'd' of each element, PvTableDisplay; the
Groups/EventCodes texts are computed here with XpmGroups._update's rules.  The DeadTime and PathTimer labels of links
xpmpva builds but never puts in a layout (DeadTime 14..27, PathTimer 14..31 of each group) are on the page, hidden, as
in the PyQt window.  Widgets on PVs pyxpm does not serve (ModuleInit, Inhibit, TagStream, XTPG:CuDelay_ns, LinkIsXpm<n>)
never connect, in either.
"""

import argparse

from psdaq.webgui.pvgui import Page, Sites, pv_edit_evt

NAmcs = 2
NGroups = 8
NSeqCodes = 32
MASKS = ['None', '0', '1', '2', '3', '4', '5', '6', '7', 'All']
FRONT = [("RemoteLinkId", 'linkid', True), ("TxLinkReset", 'pushx', True), ("RxLinkReset", 'pushx', True),
         ("RxLinkDump", 'pushx', True), ("LinkGroupMask", 'groupmask', True), ("LinkRxResetDone", 'check', False),
         ("LinkRxReady", 'check', False), ("LinkTxResetDone", 'check', False), ("LinkTxReady", 'check', False),
         ("LinkIsXpm", 'check', False), ("LinkLoopback", 'check', True), ("LinkRxErr", 'int', False),
         ("LinkRxRcv", 'int', False)]                                   # xpmpva.py:210-222 FrontPanelAMC headers
PLLS = [("PLL_LOS", 'check'), ("PLL_LOSCNT", 'int'), ("PLL_LOL", 'check'), ("PLL_LOLCNT", 'int')]
ABSENT = ('ModuleInit', 'Inhibit', 'TagStream', 'XTPG:CuDelay_ns')      # pyxpm serves none of these
GET_AT_BUILD = True                     # build() reads each XPM's FwBuild (pvgui_api passes its PVA client's get)


def parse(argv):
    p = argparse.ArgumentParser(prog='xpmpva', description='simple pv monitor gui')
    p.add_argument('--nopatt', action='store_true')
    p.add_argument('--nohier', action='store_true')
    p.add_argument('pvs', nargs='+')
    return p.parse_args(argv)


def is_atca(v):
    return ('Kcu1500' not in v) and ('C1100' not in v)                  # xpmpva.isATCA


def build(argv, fwbuild=None):
    """The page; fwbuild(pvname) -> the FwBuild string setupUi reads with pv.get() (the server's PVA client)."""
    a = parse(argv)
    page = Page('xpmpva', 'xpmpva')                                     # MainWindow.setWindowTitle('xpmpva')
    page.xpm_prefix = a.pvs[0]
    page.sim_absent = set()
    page.nohier = a.nohier
    page.titles = list(a.pvs)
    page.groups_tabs = []
    S = Sites()
    lk = {'n': 0}                                                       # PvLinkId instances, in construction order

    def text(stem, pv, fmt, qual=None, self_attr=False, **kw):
        return S.add(stem, pv, {'type': 'text', 'pv': pv, 'fmt': fmt, **kw}, qual=qual, self_attr=self_attr)

    def label(t):
        return {'type': 'label', 'text': t}

    def linkid(pv):
        """PvLinkId(pvname): two labels (type, source) of xpm_link_id(value)."""
        a_ = S.add('PvLinkId.linkType', None, {'type': 'text', 'pv': pv, 'fmt': 'linkid', 'part': 0, 'init': '-'},
                   self_attr=True)
        b_ = S.add('PvLinkId.linkSrc', None, {'type': 'text', 'pv': pv, 'fmt': 'linkid', 'part': 1, 'init': '-'},
                   self_attr=True)
        page.read_pvs.add(pv)
        return a_, b_

    def pv_input_one(stem, pvbase, name, node):
        """pvedit.PvInput with count 1: the name and one widget (its id: <stem>[<pv>])."""
        pv = pvbase + name
        node.update(pv=pv)
        return {'type': 'box', 'dir': 'h', 'children': [label(name), S.add(stem, pv, node)]}

    def walk_only(line, pv, node):
        node = dict(node, pv=pv, id='walk-only:cas/xpmpva.py:%d[%s]' % (line, pv))
        page.add(node)
        return node

    stack_children = []
    for title in a.pvs:
        pvbase = title + ':'
        v = (fwbuild(pvbase + 'FwBuild') if fwbuild else '') or ''
        atca = is_atca(v)
        amc_title, nds = ('AMC', (7, 7)) if atca else ('QSFP', (4, 4))
        tabs = []
        # Global
        g = [{'type': 'box', 'dir': 'h', 'children': [
                 label('PAddr'), text('PvPAddr.__display', pvbase + 'PAddr', 'paddr', self_attr=True, init='-')]},
             {'type': 'box', 'dir': 'h', 'children': [label('FwBuild'),
                                                       text('Ui_MainWindow.PvCString', pvbase + 'FwBuild', 'cstring')]},
             pv_input_one('Ui_MainWindow.LblCheckBox@1', pvbase, 'UsRxEnable', {'type': 'pvcheck', 'disabled': True}),
             pv_input_one('Ui_MainWindow.LblCheckBox@2', pvbase, 'CuRxEnable', {'type': 'pvcheck', 'disabled': True})]
        for n in ('ModuleInit', 'Inhibit', 'TagStream'):
            g.append(pv_input_one('LblPushButtonX.PvInput', pvbase, n, {'type': 'pvbutton', 'label': ''}))
        for k, n in enumerate(('RecClk', 'FbClk', 'BpClk')):
            g.append({'type': 'box', 'dir': 'h', 'children': [
                label(n), text('Ui_MainWindow.PvLabel@%d' % (k + 1), pvbase + n, 'pvlabel')]})
        tabs.append(('Global', {'type': 'box', 'dir': 'v', 'children': g}))
        # Cu / Us timing
        cu = 'xtpg' in v
        tb = pvbase + ('Cu:' if cu else 'Us:')
        t = []
        for k, n in enumerate(('RxClks', 'RxRsts', 'CrcErrs', 'RxDecErrs', 'RxDspErrs', 'BypassRsts', 'BypassDones',
                               'RxLinkUp', 'FIDs')):
            t.append({'type': 'box', 'dir': 'h', 'children': [
                label(n), text('addTiming.PvLabel@%d' % (k + 1), tb + n, 'pvlabel')]})
        for n in ('RxReset', 'RxCountReset'):
            t.append(pv_input_one('LblPushButtonX.PvInput', tb, n, {'type': 'pvbutton', 'label': ''}))
        t.append({'type': 'label', 'text': 'RxAlign'})          # PvRxAlign: a title and a picture (no row)
        if cu:
            x = pvbase + 'XTPG:'
            for n in ('CuInput', 'CuBeamCode', 'CuDelay'):
                t.append(pv_input_one('LblEditIntX.PvInput', x, n, {'type': 'pvint'}))
            for k, (n, kw) in enumerate((('CuDelay_ns', {}), ('PulseId', {'isInt': True}), ('TimeStamp', {'isTime': True}),
                                         ('FiducialIntv', {'isInt': True}))):
                if n == 'CuDelay_ns':        # no IOC serves it: its display is never written (no row), '-' in both
                    disp = page.add({'type': 'text', 'pv': x + n, 'fmt': 'pvlabel', 'init': '-'})
                else:
                    disp = text('addCuTab.PvLabel@%d' % (k + 1), x + n, 'pvlabel', args=kw)
                t.append({'type': 'box', 'dir': 'h', 'children': [label(n), disp]})
            t.append(pv_input_one('addCuTab.LblCheckBox', x, 'FiducialErr', {'type': 'pvcheck', 'disabled': True}))
            t.append(pv_input_one('LblPushButtonX.PvInput', x, 'ClearErr', {'type': 'pvbutton', 'label': ''}))
            for i in range(4):
                t.append({'type': 'box', 'dir': 'h', 'children': [         # PvMmcm: a title, R, a picture
                    {'type': 'label', 'text': 'mmcm%d' % i},
                    S.add('PvMmcm.PvPushButton', x + 'ResetMmcm%d' % i,
                          {'type': 'pvbutton', 'pv': x + 'ResetMmcm%d' % i, 'label': 'R'})]})
            page.sim_absent.add(x + 'CuDelay_ns')
        tabs.append(('CuTiming' if cu else 'UsTiming', {'type': 'box', 'dir': 'v', 'children': t}))
        for n in ('ModuleInit', 'Inhibit', 'TagStream'):
            page.sim_absent.add(pvbase + n)
        # Front panel AMC0 / AMC1 (QSFP0 / QSFP1)
        for amc, (nlinks, start) in enumerate(((nds[0], 0), (nds[1], nds[0]))):
            rows = []
            for name, kind, en in FRONT:
                row = [label(name)]
                for col in range(nlinks):
                    pv = '%s%s%d' % (pvbase, name, col + start)
                    if kind == 'linkid':
                        a_, b_ = linkid(pv)
                        row.append({'type': 'box', 'dir': 'v', 'children': [a_, b_]})
                    elif kind == 'pushx':
                        row.append(walk_only(226, pv, {'type': 'pvbutton', 'label': str(col + start)}))
                    elif kind == 'groupmask':
                        row.append(walk_only(226, pv, {'type': 'groupmask', 'choices': MASKS}))
                    elif kind == 'check':
                        row.append(walk_only(226, pv, {'type': 'pvcheck', 'label': str(col + start), 'disabled': not en}))
                        if name == 'LinkIsXpm':
                            page.sim_absent.add(pv)
                    else:
                        row.append(walk_only(226, pv, {'type': 'pvint', 'disabled': not en}))
                rows.append(row)
            tabs.append(('%s%d' % (amc_title, amc), {'type': 'grid', 'rows': rows}))
        if atca:                                                         # PLLs
            rows = []
            for name, kind in PLLS:
                row = [label(name)]
                for col in range(NAmcs):
                    pv = '%s%s%d' % (pvbase, name, col)
                    row.append(walk_only(244, pv, {'type': 'pvcheck', 'label': str(col), 'disabled': True} if kind == 'check'
                                         else {'type': 'pvint', 'disabled': True}))
                rows.append(row)
            tabs.append(('PLLs', {'type': 'grid', 'rows': rows}))
        # DeadTime: PvDblArrayW of each group x 32 links (rows 0..13 and INH 28..31 shown), DeadFLnk of each group
        cells = {}
        for j in range(NGroups):
            for i in range(32):
                cells[(j, i)] = S.add('DeadTime.PvDblArrayW', None, {'type': 'text', 'pv': pvbase + 'PART:%d:DeadFLnk' % j,
                                                                     'fmt': 'arr', 'index': i, 'spec': '.4f', 'init': '-'})
        rows = [[label('Group'), None] + [label('%d' % j) for j in range(NGroups)]]
        for i in range(14):
            a_, b_ = linkid(pvbase + 'RemoteLinkId%d' % i)
            rows.append([a_, b_] + [cells[(j, i)] for j in range(NGroups)])
        for i in range(28, 32):
            rows.append([label('INH%d' % (i - 28)), None] + [cells[(j, i)] for j in range(8)])
        hidden = {'type': 'box', 'dir': 'v', 'hidden': True,
                  'children': [cells[(j, i)] for j in range(NGroups) for i in range(14, 28)]}
        tabs.append(('DeadTime', {'type': 'box', 'dir': 'v', 'children': [{'type': 'grid', 'rows': rows}, hidden]}))
        # Groups/EventCodes
        seqcodes = pvbase + 'SEQCODES'
        grid1 = [[label('Group'), label('Master'), label('L0InpRate')]]
        gt = {'pvbase': pvbase, 'master': [], 'l0rate': [], 'codes': {'master': [], 'desc': [], 'rate': []}}
        for i in range(NGroups):
            m = S.add('GroupsTab.masterText', seqcodes, {'type': 'value', 'source': 'groups:%s:master:%d' % (title, i)},
                      self_attr=True)
            r = S.add('GroupsTab.l0RateText', seqcodes, {'type': 'value', 'source': 'groups:%s:l0rate:%d' % (title, i)},
                      self_attr=True)
            grid1.append([label(str(i)), m, r])
        grid3 = [[label('Sequence'), None, None, None]]
        for i in range(NSeqCodes // 4):
            row = [label(str(i))]
            for k, (n, lab, val) in enumerate((('ENABLE', 'Ena', 1), ('ENABLE', 'Dis', 0), ('DUMP', 'Dump', 1))):
                pv = '%sSEQENG:%d:%s' % (pvbase, i, n)
                row.append(S.add('GroupsTab.PvPushButtonVal@%d' % (k + 1), pv,
                                 {'type': 'pvbutton', 'pv': pv, 'label': lab, 'puts': [val]}))
            grid3.append(row)
        grid2 = [[label('EventCode'), label('Master'), label('Description'), label('Rate')]]
        for i in range(NSeqCodes):
            row = [label(str(i + 288 - NSeqCodes))]
            for k, f in enumerate(('master', 'desc', 'rate')):
                row.append(S.add('GroupsTab.codesText@%d' % (k + 1), seqcodes,
                                 {'type': 'value', 'source': 'groups:%s:codes:%s:%d' % (title, f, i)}, self_attr=True))
            grid2.append(row)
        for i in range(NGroups):
            page.read_pvs.update({pvbase + 'PART:%d:Master' % i, pvbase + 'PART:%d:L0InpRate' % i})
        page.read_pvs.update({seqcodes, pvbase + 'PAddr'})
        page.groups_tabs.append(title)
        tabs.append(('Groups/EventCodes', {'type': 'box', 'dir': 'h', 'children': [
            {'type': 'box', 'dir': 'v', 'children': [{'type': 'group', 'title': 'Groups', 'children': [
                {'type': 'grid', 'rows': grid1}]}, {'type': 'group', 'title': 'Sequence Control', 'children': [
                    {'type': 'grid', 'rows': grid3}]}]},
            {'type': 'group', 'title': 'Event Code Sources', 'children': [{'type': 'grid', 'rows': grid2}]}]}))
        # Pattern
        if not a.nopatt:
            evt = pv_edit_evt(page, 'PatternTab.PvEditEvt', pvbase + 'PATT:L0Select')
            groups = pvbase + 'PATT:GROUPS'
            stats = ['Sum', 'First', 'Last', 'MinIntv', 'MaxIntv']
            v20b = (1 << 20) - 1
            empty = (0, v20b, v20b, v20b, 0)
            tcells = {}
            k = 0
            for j, r in enumerate(stats):
                for i in range(NGroups):
                    tcells[(i, j)] = page.add({'type': 'text', 'id': 'PatternTab.PvTableDisplay[%s]#%d' % (groups, k),
                                               'pv': groups, 'fmt': 'table', 'column': r, 'row': i, 'empty': empty[j]})
                    k += 1
            trows = [[None] + [label(r) for r in stats]]
            for i in range(NGroups):
                trows.append([label('Group%d' % i)] + [tcells[(i, j)] for j in range(len(stats))])
            coinc = pvbase + 'PATT:COINC'
            cg = [[None] + [label('G%d' % i) for i in range(8)]]
            k = 0
            for i in range(8):
                row = [label('G%d' % i)] + [None] * 8
                for j in range(i, 8):
                    row[j + 1] = page.add({'type': 'text', 'id': 'PatternTab.w[%s]#%d' % (coinc, k), 'pv': coinc,
                                           'fmt': 'table', 'column': 'Coinc', 'row': k, 'empty': None})
                    k += 1
                cg.append(row)
            tabs.append(('Pattern', {'type': 'box', 'dir': 'v', 'children': [
                evt, {'type': 'grid', 'rows': trows},
                {'type': 'group', 'title': 'Group Coincidences', 'children': [{'type': 'grid', 'rows': cg}]}]}))
        # SFPs / QSFPs: PvTableDisplay in setupUi
        if atca:
            spv, names, cols = pvbase + 'SFPSTATUS', ['Amc%d-%d' % (j // 7, j % 7) for j in range(14)], \
                ['LossOfSignal', 'ModuleAbsent', 'TxPower', 'RxPower']
        else:
            spv, names, cols = pvbase + 'QSFPSTATUS', ['QSFP%d-%d' % (j // 4, j % 4) for j in range(8)], ['TxPower', 'RxPower']
        scells, k = {}, 0
        for j, r in enumerate(cols):
            for i in range(len(names)):
                scells[(i, j)] = page.add({'type': 'text', 'id': 'Ui_MainWindow.PvTableDisplay@%d[%s]#%d' % (
                                           1 if atca else 2, spv, k),
                                           'pv': spv, 'fmt': 'table', 'column': r, 'row': i, 'empty': None})
                k += 1
        srows = [[None] + [label(r) for r in cols]]
        for i, n in enumerate(names):
            srows.append([label(n)] + [scells[(i, j)] for j in range(len(cols))])
        tabs.append(('SFPs' if atca else 'QSFPs', {'type': 'grid', 'rows': srows}))
        # PathTimer
        pcells = {}
        for j in range(NGroups):
            for i in range(32):
                pcells[(j, i)] = S.add('PathTimer.PvIntArrayW', None, {
                    'type': 'text', 'pv': pvbase + 'PART:%d:PATH_TIME:Array' % j, 'fmt': 'arr', 'index': i, 'spec': 'd',
                    'init': '-'})
        prow = [label('Group'), None] + [label('%d' % j) for j in range(NGroups)]
        urow = [None, None]
        for j in range(NGroups):
            pv = '%sPART:%d:PATH_TIME:Update' % (pvbase, j)
            urow.append(S.add('PathTimer.PvPushButtonVal', pv, {'type': 'pvbutton', 'pv': pv, 'label': 'Upd', 'puts': [1]}))
        rows = [prow, urow]
        for i in range(14):
            a_, b_ = linkid(pvbase + 'RemoteLinkId%d' % i)
            rows.append([a_, b_] + [pcells[(j, i)] for j in range(NGroups)])
        hidden = {'type': 'box', 'dir': 'v', 'hidden': True,
                  'children': [pcells[(j, i)] for j in range(NGroups) for i in range(14, 32)]}
        tabs.append(('PathTimer', {'type': 'box', 'dir': 'v', 'children': [{'type': 'grid', 'rows': rows}, hidden]}))
        tw = []
        for ttl, child in tabs:
            tw.append(S.add('Ui_MainWindow.tw.tab[%s]' % ttl, None, {'type': 'tabdef', 'title': ttl, 'child': child}))
        stack_children.append({'type': 'tabs', 'id': None, 'tabs': tw, 'current': 0})
    sel = S.add('Ui_MainWindow.tabsel', None, {'type': 'localcombo', 'choices': list(a.pvs)}, qual=a.pvs[0])
    S.assign(page)
    for st in stack_children:                                         # Sites named the tab buttons
        st['tabs'] = [{'title': t['title'], 'child': t['child'], 'id': t['id']} for t in st['tabs']]
        for t in st['tabs']:
            page.nodes[t['id']] = {'type': 'tab', 'id': t['id']}
    page.tree = {'type': 'box', 'dir': 'v', 'children': [sel, {'type': 'stack', 'select': sel['id'],
                                                               'children': stack_children}]}
    return page


def xpm_link_id(value):
    """xpm_utils.xpmLinkId(value), with hostName's reverse name lookup left out (its '{:x}' of the address, what
    hostName returns when the lookup fails)."""
    value = int(value)
    host = '{:x}'.format(value)
    atca_ip = '10.0.{:}.{:}'.format((value >> 12) & 0xf, 100 + ((value >> 8) & 0xf))
    names = {0xff: ('XPM:{:}'.format((value >> 16) & 0xff), atca_ip), 0xfe: ('DTI', atca_ip), 0xfd: ('TDetSim', host),
             0xfc: ('HSD', '{:}.{:02X}'.format(host, (value >> 16) & 0xff)), 0xfb: ('TDetSim', host),
             0xfa: ('Wave8', host), 0xf9: ('Opal', host), 0xf8: ('TimeTool', host), 0xf7: ('EpixQuad', host),
             0xf6: ('EpixHR2x2', host), 0xf5: ('Epix100', host), 0xf4: ('Piranha4', host), 0xf3: ('ePixM320', host),
             0xf2: ('epixUHR', host), 0xf1: ('HREncoder', host), 0xf0: ('Jungfrau', host), 0xef: ('EpixUHR3x2', host),
             0xee: ('Wave8HE', host)}
    itype = (value >> 24) & 0xff
    if itype in names:
        return names[itype]
    if value == 0x10080:
        return ('Fanout/', 'Loopback')
    return ('undef', '{:x}'.format(value))


def paddr_text(q, nohier=False):
    """PvPAddr.update for this XPM's PAddr (the top of the tree, or an XPM shelf port)."""
    qs = '%x' % int(q)
    if qs[0:8] == 'ffffffff' or nohier:
        return 'XTPG'
    if qs[0:2] == 'ff':
        shelf, port = int(qs[2:4], 16), int(qs[6:8], 16)
        return 'XPM:%d:AMC%d-%d' % (shelf, port / 7, port % 7)        # an ATCA shelf (its FwBuild is not read here)
    return '-'


def computed(page, vals):
    """GroupsTab.update / XpmGroups._update: each group's master and L0 input rate, each sequence event code's
    master, description and rate (this XPM is the top of the tree: PAddr 0xffffffff, or --nohier)."""
    out = {}
    for title in page.groups_tabs:
        pvbase = title + ':'
        parts = pvbase.split(':')
        pos = parts.index('XPM')
        name = ':'.join([parts[pos], parts[pos + 1], ''])
        for i in range(NGroups):
            m = vals.get(pvbase + 'PART:%d:Master' % i)
            r = vals.get(pvbase + 'PART:%d:L0InpRate' % i)
            out['groups:%s:master:%d' % (title, i)] = name if (m is not None and m > 0) else '-'
            out['groups:%s:l0rate:%d' % (title, i)] = str(r) if (m is not None and m > 0) else '-'
        codes = vals.get(pvbase + 'SEQCODES')
        col = (codes or {}).get('value') or {}
        for i in range(NSeqCodes):
            on = (col.get('Enabled') or [False] * NSeqCodes)[i] if codes else False
            out['groups:%s:codes:master:%d' % (title, i)] = name if on else '-'
            out['groups:%s:codes:desc:%d' % (title, i)] = col['Description'][i] if on else '-'
            out['groups:%s:codes:rate:%d' % (title, i)] = str(col['Rate'][i]) if on else '-'
    return out
