"""Web copy of psdaq/cas/groupca.py (readout group control and monitoring), as a pvgui page.

    groupca [--prod] [--mon] [--common G] pvbase xpmroot groups...      (the PyQt program's arguments)

Mirrors groupca.Ui_MainWindow.setupUi: GroupMaster, one 'Group <g>' tab per group (addGroup: Triggers
L0Select / DstSelect / L0RawUpdate, Inhibits InhEnable / InhInterval / InhLimit 0..3), the
'Transitions' tab (PvStateMachine: a button and an Env field per transition; a click puts MsgHeader and
MsgPayload of every group, then GroupMsgInsert = group mask and 0) and the 'Events' tab (PvGroupStats:
Clear, Run, the seven counters per group and the deadtime bottleneck labels of DeadTime).  Without
--mon the program puts Master = 1 for every group when it starts (addGroup), and so does this page.
--prod is not copied yet (the PyQt --prod layout is PvGroupStats alone, without Clear).
"""

import argparse
import time

from psdaq.webgui.pvgui import Page, pv_input, pv_edit_evt, pv_edit_dst, lbl_widget, pvdbl

Transitions = [('ClearReadout', 0), ('Ping', 1), ('Configure', 2), ('BeginRun', 4), ('Enable', 8),
               ('Disable', 9), ('EndRun', 5), ('Unconfigure', 3)]                       # groupca.py:9-16
STATS = ['L0InpRate', 'L0AccRate', 'RunTime', 'NumL0Inp', 'NumL0Acc', 'DeadFrac', 'DeadTime']   # groupca.py:194


def parse(argv):
    p = argparse.ArgumentParser(prog='groupca', description='Readout group control and monitoring')
    p.add_argument('--prod', action='store_true', default=False)
    p.add_argument('--mon', action='store_true')
    p.add_argument('--common', type=int, default=None)
    p.add_argument('pvbase')
    p.add_argument('xpmroot', type=int)
    p.add_argument('groups', type=int, nargs='+')
    return p.parse_args(argv)


def to_mask(lista):
    v = 0
    for g in lista:
        v |= 1 << g
    return v


def build(argv):
    a = parse(argv)
    if a.prod:
        raise SystemExit('pvgui groupca: --prod is not copied to the web GUI yet')
    base, xpm, groups = a.pvbase, a.xpmroot, a.groups
    page = Page('groupca', base)
    page.xpm_prefix = '%s:XPM:%d' % (base, xpm)
    pvbase = base + ':XPM:%d:PART:' % xpm
    groupc = groups if a.common is None else [a.common] + groups

    # GroupMaster (groupca.py:276-285): 'Master:' and a PvCheckBox per group
    master = page.add({'type': 'box', 'dir': 'h', 'children': [page.add({'type': 'label', 'text': 'Master:'})] + [
        page.add({'type': 'pvcheck', 'id': 'GroupMaster.b[%s%d:Master]' % (pvbase, g), 'pv': '%s%d:Master' % (pvbase, g),
                  'label': 'Group %d' % g}) for g in groups]})
    tabs = []
    for g in groups:                                    # addGroup (groupca.py:247-274)
        pb = pvbase + '%d:' % g
        trg = page.add({'type': 'group', 'title': 'Triggers', 'children': [
            pv_input(page, pv_edit_evt_w, 'addGroup.LblEditEvt', pb, 'L0Select'),
            pv_input(page, pv_edit_dst_w, 'addGroup.LblEditDst', pb, 'DstSelect'),
            pv_input(page, lbl_widget('int'), 'addGroup.LblEditInt@1', pb, 'L0RawUpdate')]})
        inh = page.add({'type': 'group', 'title': 'Inhibits', 'children': [page.add({'type': 'box', 'dir': 'h', 'children': [
            pv_input(page, lbl_widget('check'), 'addGroup.LblCheckBox', pb, 'InhEnable', 4, horiz=False),
            pv_input(page, lbl_widget('int'), 'addGroup.LblEditInt@2', pb, 'InhInterval', 4, horiz=False),
            pv_input(page, lbl_widget('int'), 'addGroup.LblEditInt@3', pb, 'InhLimit', 4, horiz=False)]})]})
        tabs.append({'title': 'Group %d' % g, 'child': page.add({'type': 'box', 'dir': 'v', 'children': [trg, inh]})})
        if not a.mon:
            page.startup.append((pb + 'Master', 1))
            page.write_pvs.add(pb + 'Master')
    if a.common is not None and not a.mon:
        page.startup += [('%s:XPM:%d:PART:%d:L0Groups' % (base, xpm, a.common), to_mask(groups)),
                         ('%s:XPM:%d:PART:%d:Master' % (base, xpm, a.common), 2)]
        page.write_pvs.update(pv for pv, _ in page.startup)

    # PvStateMachine (groupca.py:18-63)
    page.groups_mask = to_mask(groupc)
    page.msg_insert = '%s:XPM:%d:GroupMsgInsert' % (base, xpm)
    page.msg_header = [pvbase + '%d:MsgHeader' % g for g in groupc]
    page.msg_payload = [pvbase + '%d:MsgPayload' % g for g in groupc]
    page.write_pvs.update([page.msg_insert] + page.msg_header + page.msg_payload)
    rows = [[page.add({'type': 'label', 'text': h}) for h in ('Transition', 'Id', 'Env')]]
    for i, (tr, trid) in enumerate(Transitions):
        rows.append([page.add({'type': 'button', 'id': 'PvStateMachine.btn[%s]' % tr, 'label': tr, 'checkable': True,
                               'action': 'transition', 'arg': i, 'env': 'PvStateMachine.env#%d' % i}),
                     page.add({'type': 'label', 'text': '%d' % trid}),
                     page.add({'type': 'edit', 'id': 'PvStateMachine.env#%d' % i, 'text': '0'})])
    page.transitions = Transitions
    trans = page.add({'type': 'grid', 'rows': rows})

    # PvGroupStats (groupca.py:168-245) and DeadTime (122-143)
    page.l0reset = '%s:XPM:%d:GroupL0Reset' % (base, xpm)
    page.l0enable = '%s:XPM:%d:GroupL0Enable' % (base, xpm)
    page.l0disable = '%s:XPM:%d:GroupL0Disable' % (base, xpm)
    page.write_pvs.update([page.l0reset, page.l0enable, page.l0disable])
    head = page.add({'type': 'box', 'dir': 'h', 'children': [
        page.add({'type': 'button', 'id': 'PvGroupStats.b[Clear]', 'label': 'Clear', 'action': 'clear'}),
        page.add({'type': 'check', 'id': 'PvGroupStats.runb', 'label': 'Run', 'action': 'run',
                  'pv_on': page.l0enable, 'pv_off': page.l0disable, 'on_value': page.groups_mask})]})
    grid = [[None] + [page.add({'type': 'label', 'text': 'Group %d' % g}) for g in groupc]]
    for s in STATS:
        grid.append([page.add({'type': 'label', 'text': s})] +
                    [pvdbl(page, 'PvGroupStats.PvDbl[%s%d:%s]' % (pvbase, g, s), '%s%d:%s' % (pvbase, g, s))
                     for g in groupc])
    k = 0
    page.dead = []
    for i, g in enumerate(groupc):
        name_id, val_id = 'PvGroupStats.det#%d' % k, 'PvGroupStats.det#%d' % (k + 1)
        k += 2
        row = [page.add({'type': 'value', 'id': name_id, 'source': 'dead:%d:name' % g})] + [None] * len(groupc)
        row[i + 1] = page.add({'type': 'value', 'id': val_id, 'source': 'dead:%d:value' % g})
        grid.append(row)
        page.dead.append(g)
    events = page.add({'type': 'box', 'dir': 'v', 'children': [head, page.add({'type': 'grid', 'rows': grid})]})
    tabs.append({'title': 'Transitions', 'child': trans})
    tabs.append({'title': 'Events', 'child': events})
    for t in tabs:
        t['id'] = 'Ui_MainWindow.tw.tab[%s]' % t['title']
        page.nodes[t['id']] = {'type': 'tab', 'id': t['id']}
    tw = {'type': 'tabs', 'id': 'Ui_MainWindow.tw', 'tabs': tabs, 'current': len(groups) + 1}   # setCurrentIndex
    page.tree = {'type': 'box', 'dir': 'v', 'children': [master, tw]}
    page.read_pvs.update(page.xpm_link_pvs(xpm) if hasattr(page, 'xpm_link_pvs') else [])
    page.dead_pvs = {g: '%s%d:DeadFLnk' % (pvbase, g) for g in groupc}
    page.read_pvs.update(page.dead_pvs.values())
    page.read_pvs.update(['%s:XPM:%d:FwBuild' % (base, xpm)] +
                         ['%s:XPM:%d:RemoteLinkId%d' % (base, xpm, n) for n in range(14)] +
                         ['%s:XPM:%d:LinkGroupMask%d' % (base, xpm, n) for n in range(14)])
    page.base, page.xpm = base, xpm
    return page


def pv_edit_evt_w(page, nid, pv, label=''):
    return pv_edit_evt(page, nid.split('[', 1)[0], pv)


def pv_edit_dst_w(page, nid, pv, label=''):
    return pv_edit_dst(page, nid.split('[', 1)[0], pv)


def act(page, ctx_put, node, value):
    """Run a button / check action as the PyQt slot does; ctx_put(pv, value) puts and waits."""
    if node['action'] == 'transition':                # PvStateMachine.transition
        i = node['arg']
        try:
            env = int(value)
        except (TypeError, ValueError):
            raise ValueError('Env %r is not an integer' % (value,))
        done = []
        for pv in page.msg_header:
            ctx_put(pv, page.transitions[i][1])
            done.append((pv, page.transitions[i][1]))
        for pv in page.msg_payload:
            ctx_put(pv, env)
            done.append((pv, env))
        ctx_put(page.msg_insert, page.groups_mask)
        ctx_put(page.msg_insert, 0)
        return done + [(page.msg_insert, page.groups_mask), (page.msg_insert, 0)]
    if node['action'] == 'clear':                     # PvGroupStats.clear
        ctx_put(page.l0reset, page.groups_mask)
        ctx_put(page.l0reset, 0)
        return [(page.l0reset, page.groups_mask), (page.l0reset, 0)]
    if node['action'] == 'run':                       # PvGroupStats.run
        pv = page.l0enable if value else page.l0disable
        ctx_put(pv, page.groups_mask)
        time.sleep(0.1)
        ctx_put(pv, 0)
        return [(pv, page.groups_mask), (pv, 0)]
    raise ValueError('unknown action %r' % node['action'])


def computed(page, values):
    """DeadTime.update / XpmDeadTime.update for the root XPM: per group, the link of that group (LinkGroupMask ==
    1 << group) with the largest DeadFLnk entry; its name (xpm_utils.xpmLinkId) and value, or '' when its
    RemoteLinkId is 0 (groupca.py:96-104, 133-143)."""
    out = {}
    fw = values.get('%s:XPM:%d:FwBuild' % (page.base, page.xpm))
    nlinks = 8 if isinstance(fw, str) and 'Kcu' in fw else 14
    for g in page.dead:
        v = values.get(page.dead_pvs[g])
        best = (None, -1.)
        if isinstance(v, list):
            for i in range(min(nlinks, len(v))):
                m = values.get('%s:XPM:%d:LinkGroupMask%d' % (page.base, page.xpm, i))
                if m == (1 << g) and v[i] > best[1]:
                    best = (values.get('%s:XPM:%d:RemoteLinkId%d' % (page.base, page.xpm, i)), v[i])
        if best[0]:
            from psdaq.cas.xpm_utils import xpmLinkId
            names = xpmLinkId(best[0])
            out['dead:%d:name' % g] = names[0] + ':' + names[1]
            out['dead:%d:value' % g] = str(best[1])
        else:
            out['dead:%d:name' % g] = ''
            out['dead:%d:value' % g] = ''
    return out
