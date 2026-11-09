"""Page specs of the web copies of the pvedit-based PyQt GUIs (psdaq/cas/*.py, widgets of psdaq/cas/pvedit.py).

A page is a tree of nodes built in Python with the same arguments as the PyQt program; the browser
(static/gui/pvgui.js) renders any tree generically.  Each widget node carries `id`, the parity row id
of the PyQt widget it copies (gui_rows: <scope>.<binding>[<PV>]#<n>), so the web element has
data-parity="<id>".  The helpers below mirror pvedit.py one to one (PvInput and the Lbl* helpers,
PvCheckBox, PvEditInt, PvEditCmb, PvDbl, PvMaskTab, PvDstTab, PvEditEvt, PvEditDst, PvDefSeq,
PvDefCuSeq); a page module (pvgui/groupca.py) mirrors the program's layout code.

Node types the renderer knows
  box {dir: 'v'|'h', children}     group {title, children}      grid {rows: [[node|null, ...]]}
  label {text}                     tabs {id, tabs: [{title, child}], current}
  stack {select: <node id>, children}        (QStackedWidget switched by a combo's index)
  pvcheck {pv, label}              PvCheckBox: checked = value != 0; click puts 1 / 0
  pvint {pv}                       PvEditInt: shows int(value); Enter / leaving the field puts int(text)
  pvcombo {pv, choices}            PvEditCmb: index = value; a choice puts its index
  pvdbl {pv}                       PvDbl: read only, '{:.4f}'
  mask {pv, bits: [{id, label}]}   PvMaskTab / PvDstTab: one checkbox per bit, a click puts the mask
  seqsel {pv, choices}             PvDefSeq.seqsel: puts its index to <pv>_Sequence, switches the stack
  button {label, action}           a QPushButton whose action the page module runs server side
  check {label, action, pv_on, pv_off}  a QCheckBox with a server-side action (groupca Run)
  edit {text}                      a plain QLineEdit (no PV; an action reads it)
  value {source}                   a QLabel the program writes (computed server side: values[source])
"""

NBeamSeq = 16
evtsel = ['Fixed Rate', 'AC Rate', 'EventCode', 'Sequence']           # pvedit.py:25
dstsel = ['Include', 'DontCare']                                       # pvedit.py:24
seqGlobal = ['GLT %d' % i for i in range(16)]                          # pvedit.py:33
seqLocal = ['%u0kHz' % (4 * i + 4) for i in range(16)]                 # pvedit.py:32


class Page:
    """Collects the nodes of one page by id, the PVs they read and the PVs a write may target."""

    def __init__(self, name, title):
        self.name, self.title = name, title
        self.nodes = {}
        self.read_pvs, self.write_pvs = set(), set()
        self.startup = []           # [(pv, value)] the PyQt program puts when it starts
        self.computed = {}          # source -> fn(values) for value nodes

    def add(self, node):
        for b in node.get('bits', []):
            self.nodes[b['id']] = {'type': 'maskbit', 'id': b['id'], 'pv': node['pv']}
        nid = node.get('id')
        if nid:
            if nid in self.nodes:
                raise ValueError('%s: duplicate node id %s' % (self.name, nid))
            self.nodes[nid] = node
        for k in ('pv',):
            if node.get(k):
                self.read_pvs.add(node[k])
                if node['type'] in ('pvcheck', 'pvint', 'pvcombo', 'mask', 'seqsel'):
                    self.write_pvs.add(node[k])
        for k in ('pv_on', 'pv_off'):
            if node.get(k):
                self.read_pvs.add(node[k])
        return node


def ordinal_ids(stem, pv, n):
    """ids of n instances of one site that share one PV: <stem>[<pv>]#0 .. #n-1 (gui_rows.make_rows)."""
    return ['%s[%s]#%d' % (stem, pv, i) for i in range(n)]


def pv_input(page, widget, stem, pvbase, name, count=1, start=0, horiz=True, **kw):
    """pvedit.PvInput: a label and one widget, or count widgets on pvname0 .. pvname<count-1>."""
    pvname = pvbase + name
    kids = [page.add({'type': 'label', 'text': name})]
    if count == 1:
        kids.append(widget(page, '%s[%s]' % (stem, pvname), pvname, **kw))
    else:
        for i in range(count):
            pv = pvname + '%d' % (i + start)
            kids.append(widget(page, '%s[%s]' % (stem, pv), pv, label=str(i), **kw))
    return page.add({'type': 'box', 'dir': 'h' if horiz else 'v', 'children': kids})


def pvcheck(page, nid, pv, label=''):
    return page.add({'type': 'pvcheck', 'id': nid, 'pv': pv, 'label': label})


def pvint(page, nid, pv, label=''):
    return page.add({'type': 'pvint', 'id': nid, 'pv': pv})


def pvdbl(page, nid, pv):
    return page.add({'type': 'pvdbl', 'id': nid, 'pv': pv})


def pvcombo(page, nid, pv, choices):
    return page.add({'type': 'pvcombo', 'id': nid, 'pv': pv, 'choices': list(choices)})


def mask(page, stem, pv, names, validate=None):
    ids = ordinal_ids(stem, pv, len(names))
    return page.add({'type': 'mask', 'pv': pv, 'bits': [{'id': i, 'label': n} for i, n in zip(ids, names)],
                     'validate': validate})


def pv_edit_evt(page, stem, pvname, **_):
    """pvedit.PvEditEvt: evtcmb (L0Select) + PvEvtTab stack (FixedRate / AC rate+timeslots / EventCode / Sequence).
    Instances in construction order share the site's stem, so the ordinals follow pvedit's order."""
    from psdaq.configdb import tsdef
    evt = pvcombo(page, '%s[%s]' % (stem, pvname), pvname, evtsel)
    fixed = pvcombo(page, '%s[%s]' % (stem, pvname + '_FixedRate'), pvname + '_FixedRate', tsdef.fixedRates)
    acr = pvcombo(page, '%s[%s]' % (stem, pvname + '_ACRate'), pvname + '_ACRate', tsdef.acRates)
    acm = mask(page, stem, pvname + '_ACTimeslot', list(tsdef.acTS), validate='nonzero')
    cu = page.add({'type': 'box', 'dir': 'h', 'children': [
        page.add({'type': 'label', 'text': 'EventCode'}),
        pvint(page, '%s[%s]' % (stem, pvname + '_EventCode'), pvname + '_EventCode')]})
    seqsel_id = '%s[%s]' % (stem, pvname + '_Sequence')
    seqsel = page.add({'type': 'seqsel', 'id': seqsel_id, 'pv': pvname + '_Sequence',
                       'choices': ['Global_%d' % i for i in range(17)] + ['Local']})
    bits = ordinal_ids(stem, pvname + '_SeqBit', 18)
    seqstack = page.add({'type': 'stack', 'select': seqsel_id, 'children': [
        pvcombo(page, bits[i], pvname + '_SeqBit', seqGlobal if i < 17 else seqLocal) for i in range(18)]})
    seq = page.add({'type': 'box', 'dir': 'v', 'children': [seqsel, seqstack]})
    ac = page.add({'type': 'box', 'dir': 'v', 'children': [acr, acm]})
    tab = page.add({'type': 'stack', 'select': evt['id'], 'children': [fixed, ac, cu, seq]})
    return page.add({'type': 'box', 'dir': 'v', 'children': [evt, tab]})


def pv_edit_dst(page, stem, pvname, **_):
    """pvedit.PvEditDst: DstSelect combo + PvDstTab (16 bits D0..D15) on <pv>_Mask; red when both are 0."""
    sel = pvcombo(page, '%s[%s]' % (stem, pvname), pvname, dstsel)
    sel['validate_pair'] = pvname + '_Mask'
    msk = mask(page, stem, pvname + '_Mask', ['D%d' % i for i in range(NBeamSeq)], validate='pair:' + pvname)
    return page.add({'type': 'box', 'dir': 'v', 'children': [sel, msk]})


def lbl_widget(kind):
    """pvedit.LblCheckBox / LblEditInt / LblEditEvt / LblEditDst as pv_input widgets keyed by (page, id, pv)."""
    def chk(page, nid, pv, label=''):
        return pvcheck(page, nid, pv, label)

    def edit(page, nid, pv, label=''):
        return pvint(page, nid, pv)
    return {'check': chk, 'int': edit}[kind]
