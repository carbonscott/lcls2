"""Web copy of psdaq/cas/hsdpva.py (the high-speed digitizer monitor), as a pvgui page.

    hsdpva [-v] [-u] base [base ...]          (the PyQt program's arguments: HSD PV prefixes, or -u TMO|RIX)

Mirrors hsdpva.Ui_MainWindow.setupUi: a combo of the bases selects one QTabWidget per base (QStackedWidget), each with
the tabs Config (PvScalarBox of <base>:CONFIG, editable, Apply), Timing, Trig (PvScalarBox of MONTIMING, MONTRIG), PGP
(PvArrayTable of MONPGP), PgpCfg (PvArrayTable of PGPCONFIG, editable, Apply), Buffers (PvBuf of MONRAWBUF and
MONFEXBUF), RawDetail / FexDetail (PvArrayTable of MONRAWDET / MONFEXDET, vertical), Flow, Env (PvCString FWBUILD and
PADDR, PvPLink PLINK, PvScalarBox MONENV), Adc, Jesd (PvJesd of MONJESD: 8 lanes x the MONJESDTTL rows, 5 clocks) and
Reset (PvScalarBox of RESET, editable, Apply).  Each display shows the text the PyQt widget's update() writes
(pvgui.text_of fmt 'field': str(q[field]) of the structure's todict(), an array element in the field's format or, for a
float32 array, str(numpy.float32)); an editable box shows its PV's fields and is rewritten when the PV changes, and
Apply puts the whole structure, int() / float() of each field's text by the field's type (PvScalarBox.put,
PvArrayTable.put); a text that does not convert puts nothing (the PyQt slot raises ValueError).
Not copied: PvPLink's reverse DNS lookup of 172.21.x.y (the web copy never queries a name server; it shows the
address), and hsdpva's HsdConfig, a class its window never builds.
"""

import argparse

from psdaq.webgui.pvgui import Page, Sites
from psdaq.hsd.pvdef import daqConfig, pgpConfig, daqReset, monTiming, monTrig, monPgp, monBuf, monBufDetail, \
    monFlow, monEnv, monJesdTtl, monAdc

TABS = ['Config', 'Timing', 'Trig', 'PGP', 'PgpCfg', 'Buffers', 'RawDetail', 'FexDetail', 'Flow', 'Env', 'Adc', 'Jesd',
        'Reset']
JESD_CLOCKS = ['PllClk', 'RxClk', 'SysRef', 'DevClk', 'GtRefClk']                    # hsdpva.py:287


def parse(argv):
    p = argparse.ArgumentParser(prog='hsdpva', description='simple pv monitor gui')
    p.add_argument('base', nargs='+', help='pv base to monitor')
    p.add_argument('-v', '--verbose', action='store_true')
    p.add_argument('-u', action='store_true', help='pv base to monitor in hutch')
    return p.parse_args(argv)


def bases_of(a):
    """hsdpva.main: the bases, or with -u the hutch's HSD cards."""
    if not a.u:
        return list(a.base)
    fpgas = {'TMO': ['1B', '1A', '3E', '3D', '01', 'DA', 'B2', 'B1', '89', '88'], 'RIX': ['1B', '1A', '3D', '3E']}
    if a.base[0] not in fpgas:
        raise SystemExit('hsdpva: Please provide one of the following hutches with the option d: TMO, RIX')
    return ['DAQ:%s:HSD:1_%s:%s' % (a.base[0], f, s) for f in fpgas[a.base[0]] for s in ('A', 'B')]


def scalar_box(page, sites, pvname, title, struct, edit=False):
    """PvScalarBox (hsdpva.py:28-69): a grid of the struct's fields; edit: QLineEdits and Apply."""
    rows, fields = [], []
    stem = 'PvScalarBox.w@1' if edit else 'PvScalarBox.w@2'
    for ttl, t in struct.items():
        n = sites.add(stem, pvname, {'type': 'fieldedit' if edit else 'text', 'pv': pvname, 'fmt': 'field',
                                     'field': ttl, 'init': '-', 'conv': 'int' if t[0] == 'i' else 'float'})
        fields.append(n)
        rows.append([{'type': 'label', 'text': ttl}, n, {'type': 'label', 'text': t[2]} if len(t) > 2 else None])
    kids = [{'type': 'grid', 'rows': rows}]
    if edit:
        kids.append(sites.add('PvScalarBox.b', pvname, {'type': 'button', 'label': 'Apply', 'pv': pvname,
                                                        'action': 'put_struct', 'fields': fields}))
    return {'type': 'group', 'title': title, 'children': kids}


def array_table(page, sites, pvname, title, struct, vertical=False, edit=False):
    """PvArrayTable (hsdpva.py:75-127): one row (vertical: column) per field, one cell per element."""
    cols = {}
    fields = []
    for i, (ttl, t) in enumerate(struct.items()):
        cells = []
        for j in range(len(t[1])):
            n = {'type': 'fieldedit' if edit else 'text', 'pv': pvname, 'fmt': 'field', 'field': ttl, 'index': j,
                 'init': '-' if edit else '', 'conv': 'int', 'spec': t[2] if len(t) > 2 else None,
                 'f32': t[0] == 'af'}
            cells.append(sites.add('PvArrayTable.w', pvname, n))
        fields.extend(cells)
        cols[ttl] = cells
    names = list(struct)
    if vertical:
        n = max(len(c) for c in cols.values())
        rows = [[{'type': 'label', 'text': k} for k in names]] + \
            [[cols[k][j] if j < len(cols[k]) else None for k in names] for j in range(n)]
    else:
        rows = [[{'type': 'label', 'text': k}] + cols[k] for k in names]
    kids = [{'type': 'grid', 'rows': rows}]
    if edit:
        kids.append(sites.add('PvArrayTable.b', pvname, {'type': 'button', 'label': 'Apply', 'pv': pvname,
                                                         'action': 'put_arrays', 'fields': fields}))
    return {'type': 'group', 'title': title, 'children': kids}


def hsd_env(page, sites, base):
    """HsdEnv (hsdpva.py:242-256): PvCString FWBUILD and PADDR, PvPLink PLINK, PvScalarBox MONENV."""
    kids = []
    for k, name in ((1, 'FWBUILD'), (2, 'PADDR')):
        pv = base + ':' + name
        kids.append({'type': 'box', 'dir': 'h', 'children': [
            {'type': 'label', 'text': name},
            sites.add('HsdEnv.PvCString@%d' % k, pv, {'type': 'text', 'pv': pv, 'fmt': 'cstring', 'init': '-'})]})
    pv = base + ':PLINK'
    kids.append({'type': 'box', 'dir': 'h', 'children': [
        {'type': 'label', 'text': 'PLINK'},
        sites.add('PvPLink.__display', pv, {'type': 'text', 'pv': pv, 'fmt': 'plink', 'init': '-'})]})
    kids.append(scalar_box(page, sites, base + ':MONENV', 'Env', monEnv))
    return {'type': 'box', 'dir': 'v', 'children': kids}


def hsd_jesd(page, sites, base, ttl):
    """HsdJesd (hsdpva.py:258-300): 8 lanes x len(MONJESDTTL.ttl) status cells (built lane by lane), 5 clocks [MHz];
    PvJesd.update writes stat[k] to cell k and '{:.4f}' of clks[i]."""
    pv = base + ':MONJESD'
    cells = {}
    for j in range(8):
        for i in range(len(ttl)):
            cells[(i, j)] = sites.add('HsdJesd.w@1', None, {'type': 'text', 'pv': pv, 'fmt': 'field', 'field': 'stat',
                                                           'index': j * len(ttl) + i, 'init': ''})
    rows = [[{'type': 'label', 'text': 'Lane'}] + [{'type': 'label', 'text': '%d' % i} for i in range(8)]]
    rows += [[{'type': 'label', 'text': t}] + [cells[(i, j)] for j in range(8)] for i, t in enumerate(ttl)]
    clk = []
    for i, name in enumerate(JESD_CLOCKS):
        clk.append([{'type': 'label', 'text': name},
                    sites.add('HsdJesd.w@2', None, {'type': 'text', 'pv': pv, 'fmt': 'field', 'field': 'clks',
                                                    'index': i, 'spec': '{0:.4f}', 'init': ''}),
                    {'type': 'label', 'text': 'MHz'}])
    return {'type': 'box', 'dir': 'v', 'children': [{'type': 'grid', 'rows': rows}, {'type': 'grid', 'rows': clk}]}


def build(argv):
    a = parse(argv)
    titles = bases_of(a)
    page = Page('hsdpva', 'hsdpva')                       # hsdpva.py:352 setWindowTitle("hsdpva")
    sites = Sites()
    ttl = list(monJesdTtl['ttl'][1])                    # hsdpva reads <base>:MONJESDTTL once; hsdpvs serves this list
    page.jesd_ttl = ttl
    S = 'Ui_MainWindow.'
    tabsel = sites.add(S + 'tabsel', None, {'type': 'localcombo', 'choices': list(titles)}, qual=titles[0])
    stack = []
    for title in titles:
        kids = [scalar_box(page, sites, title + ':CONFIG', 'Config', daqConfig, edit=True),
                scalar_box(page, sites, title + ':MONTIMING', 'Timing', monTiming),
                scalar_box(page, sites, title + ':MONTRIG', 'Trig', monTrig),
                array_table(page, sites, title + ':MONPGP', 'Pgp', monPgp),
                array_table(page, sites, title + ':PGPCONFIG', 'Pgp Config', pgpConfig, edit=True),
                {'type': 'box', 'dir': 'h', 'children': [scalar_box(page, sites, title + ':MONRAWBUF', 'Raw', monBuf),
                                                         scalar_box(page, sites, title + ':MONFEXBUF', 'Fex', monBuf)]},
                array_table(page, sites, title + ':MONRAWDET', 'Raw Buffers', monBufDetail, vertical=True),
                array_table(page, sites, title + ':MONFEXDET', 'Fex Buffers', monBufDetail, vertical=True),
                scalar_box(page, sites, title + ':MONFLOW', 'Flow', monFlow),
                hsd_env(page, sites, title),
                scalar_box(page, sites, title + ':MONADC', 'Adc', monAdc),
                hsd_jesd(page, sites, title, ttl),
                scalar_box(page, sites, title + ':RESET', 'Reset', daqReset, edit=True)]
        tabs = []
        for name, child in zip(TABS, kids):
            tabs.append({'title': name, 'child': child, 'node': sites.add(S + 'maintab.tab[%s]' % name, None,
                                                                           {'type': 'tab'})})
        stack.append({'type': 'tabs', 'tabs': tabs, 'current': 0})
    sites.assign(page)
    for t in stack:
        for tab in t['tabs']:
            tab['id'] = tab.pop('node')['id']
    page.tree = {'type': 'box', 'dir': 'v', 'children': [tabsel, {'type': 'stack', 'select': tabsel['id'],
                                                                 'children': stack}]}
    page.sim_pid_pv = titles[0] + ':SIM:PID'             # simhsd's own PV (an HSD does not serve it)
    # PVs no HSD PV host serves to hsdpva's window: none (HsdConfig, the only reader of TESTPATTERN and BASE:*, is
    # never built)
    return page


def _conv(n, text):
    return {'int': int, 'float': float}[n['conv']](str(text).strip())


def act(page, put, node, value):
    """Apply (PvScalarBox.put / PvArrayTable.put): value = the texts of node['fields'] in the page; the structure of
    int() / float() of each by the field's type, put whole.  A text that does not convert: ValueError, nothing put."""
    fields = [page.nodes[f] for f in node['fields']]
    if not isinstance(value, list) or len(value) != len(fields):
        raise ValueError('Apply needs the %d field texts' % len(fields))
    if node['action'] == 'put_struct':
        v = {n['field']: _conv(n, t) for n, t in zip(fields, value)}
    else:
        v = {}
        for n, t in zip(fields, value):
            v.setdefault(n['field'], []).append(int(str(t).strip()))
    put(node['pv'], v)
    return [[node['pv'], v]]
