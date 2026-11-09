"""Web copy of psdaq/cas/partca.py (one readout group: trigger, transitions, message, inhibits, counters, and the
collection panel), as a pvgui page.

    partca [-v] [-n] [-x] pv            (the PyQt program's arguments; pv = <PVBASE>:XPM:<n>:PART:<group>)

Mirrors partca.Ui_MainWindow.setupUi: Master (PvCheckBox); Trigger: L0Select (PvEditEvt), L0Delay, DstSelect
(PvEditDst), Run; Transitions: Configure (PvPushButton MsgConfig) + Key (PvEditInt MsgConfigKey), Enable,
Disable, ClearReadout; Message: Insert (MsgInsert) + Hdr (MsgHeader) + Payload (MsgPayload); Inhibits:
InhEnable / InhInterval / InhLimit 0..3; on the right Clear (ResetL0) and nine PvLabels (pvedit.PvLabel text,
scale and isInt as in partca.py).  Without -n, the collection panel (psdaq/cas/collection_widget.py
CollectionWidget): Auto connect sends rollcall, alloc and connect, then getstate fills the drp / teb / meb lists
with each process's host; Reset sends reset.  The PyQt widget sends these to tcp://drp-tst-acc06:<rep_port>; this
copy sends them only to the control on this host (tcp://127.0.0.1:<rep_port>, ControlDef.front_rep_port, the
loopback control the web server runs against), with a 10 s reply timeout.
-x (setCuMode) changes no widget partca builds.
"""

import argparse
import json
import threading
from datetime import datetime, timezone

from psdaq.webgui.pvgui import Page, pv_input, pv_edit_evt, pv_edit_dst, lbl_widget, pvint

PORT_BASE = 29980                       # collection_widget.py PORT_BASE, rep_port
POSIX_TIME_AT_EPICS_EPOCH = 631152000
LABELS = [('L0InpRate', {'scale': 1.0}), ('L0AccRate', {'scale': 1.0}), ('L1Rate', {}), ('RunTime', {}),
          ('NumL0Inp', {}), ('NumL0Acc', {'isInt': True}), ('NumL1', {}), ('DeadFrac', {'scale': 1.0}),
          ('DeadTime', {'scale': 1.0})]                                                   # partca.py:81-89
GROUPS = ['drp', 'teb', 'meb']


def parse(argv):
    p = argparse.ArgumentParser(prog='partca', description='simple pv monitor gui')
    p.add_argument('-v', '--verbose', action='store_true')
    p.add_argument('-n', '--no_collection', action='store_true')
    p.add_argument('-x', '--xtpg_mode', action='store_true')
    p.add_argument('pv')
    return p.parse_args(argv)


def rep_port(platform):
    return PORT_BASE + platform + 20


def timestampStr():
    current = datetime.now(timezone.utc)
    return '%010d-%09d' % (int(current.timestamp()) - POSIX_TIME_AT_EPICS_EPOCH, 1000 * current.microsecond)


def create_msg(key, body={}):           # collection_widget.create_msg
    return {'header': {'key': key, 'msg_id': timestampStr(), 'sender_id': None}, 'body': body}


def evt_w(page, nid, pv, label=''):
    return pv_edit_evt(page, nid.split('[', 1)[0], pv)


def dst_w(page, nid, pv, label=''):
    return pv_edit_dst(page, nid.split('[', 1)[0], pv)


def pvbutton(page, nid, pv, label):
    return page.add({'type': 'pvbutton', 'id': nid, 'pv': pv, 'label': label})


def build(argv):
    a = parse(argv)
    base = a.pv
    pb = base + ':'
    S = 'Ui_MainWindow.'
    page = Page('partca', base)                                                  # setWindowTitle(base)
    page.xpm_prefix = base.split(':PART:')[0] if ':PART:' in base else None
    left = [page.add({'type': 'pvcheck', 'id': S + 'PvCheckBox[%sMaster]' % pb, 'pv': pb + 'Master', 'label': 'Master'})]
    left.append(page.add({'type': 'group', 'title': 'Trigger', 'children': [
        pv_input(page, evt_w, S + 'LblEditEvt', pb, 'L0Select'),
        pv_input(page, lbl_widget('int'), S + 'LblEditInt@1', pb, 'L0Delay'),
        pv_input(page, dst_w, S + 'LblEditDst', pb, 'DstSelect'),
        pv_input(page, lbl_widget('check'), S + 'LblCheckBox@1', pb, 'Run')]}))
    left.append(page.add({'type': 'group', 'title': 'Transitions', 'children': [
        page.add({'type': 'box', 'dir': 'h', 'children': [
            pvbutton(page, S + 'PvPushButton@1[%sMsgConfig]' % pb, pb + 'MsgConfig', 'Configure'),
            pvint(page, S + 'PvEditInt@1[%sMsgConfigKey]' % pb, pb + 'MsgConfigKey')]}),
        pvbutton(page, S + 'PvPushButton@2[%sMsgEnable]' % pb, pb + 'MsgEnable', 'Enable'),
        pvbutton(page, S + 'PvPushButton@3[%sMsgDisable]' % pb, pb + 'MsgDisable', 'Disable'),
        pvbutton(page, S + 'PvPushButton@4[%sMsgClear]' % pb, pb + 'MsgClear', 'ClearReadout')]}))
    left.append(page.add({'type': 'group', 'title': 'Message', 'children': [page.add({'type': 'box', 'dir': 'h', 'children': [
        pvbutton(page, S + 'PvPushButton@5[%sMsgInsert]' % pb, pb + 'MsgInsert', 'Insert'),
        pvint(page, S + 'PvEditInt@2[%sMsgHeader]' % pb, pb + 'MsgHeader'),
        pvint(page, S + 'PvEditInt@3[%sMsgPayload]' % pb, pb + 'MsgPayload')]})]}))
    left.append(page.add({'type': 'group', 'title': 'Inhibits', 'children': [page.add({'type': 'box', 'dir': 'h', 'children': [
        pv_input(page, lbl_widget('check'), S + 'LblCheckBox@2', pb, 'InhEnable', 4, horiz=False),
        pv_input(page, lbl_widget('int'), S + 'LblEditInt@2', pb, 'InhInterval', 4, horiz=False),
        pv_input(page, lbl_widget('int'), S + 'LblEditInt@3', pb, 'InhLimit', 4, horiz=False)]})]}))
    right = [pvbutton(page, S + 'b[%sResetL0]' % pb, pb + 'ResetL0', 'Clear')]
    for i, (name, args) in enumerate(LABELS):
        right.append(page.add({'type': 'text', 'id': S + 'PvLabel@%d[%s%s]' % (i + 1, pb, name), 'pv': pb + name,
                               'fmt': 'pvlabel', 'args': args, 'label': name}))
    cols = [page.add({'type': 'box', 'dir': 'v', 'children': left}), page.add({'type': 'box', 'dir': 'v', 'children': right})]
    page.partition = None
    if not a.no_collection:                                                     # partca.py:104-108
        page.partition = int(base.split(':')[-1])
        cw = S + 'collectionWidget'
        page.coll = {'label': '', 'lists': {g: [] for g in GROUPS}, 'replies': []}
        page.coll_lock = threading.Lock()
        lists = [page.add({'type': 'list', 'id': '%s#%d' % (cw, i), 'source': 'coll:' + g}) for i, g in enumerate(GROUPS)]
        cols.append(page.add({'type': 'group', 'title': 'Collection', 'children': [
            page.add({'type': 'box', 'dir': 'h', 'children': [
                page.add({'type': 'button', 'id': cw + '[Auto connect]', 'label': 'Auto connect', 'action': 'auto_connect'}),
                page.add({'type': 'button', 'id': cw + '[Reset]', 'label': 'Reset', 'action': 'reset'})]}),
            page.add({'type': 'value', 'id': 'collection.label', 'source': 'coll:label'}),
            page.add({'type': 'grid', 'rows': [[page.add({'type': 'label', 'text': g}) for g in GROUPS], lists]})]}))
    page.tree = {'type': 'box', 'dir': 'h', 'children': cols}
    return page


def _request(page, key, timeout_ms=10000):
    import zmq
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.REQ)
    s.setsockopt(zmq.LINGER, 0)
    s.setsockopt(zmq.RCVTIMEO, timeout_ms)
    s.connect('tcp://127.0.0.1:%d' % rep_port(page.partition))
    try:
        s.send_json(create_msg(key))
        return s.recv_json()
    finally:
        s.close()


def act(page, ctx_put, node, value):
    """CollectionWidget.auto_connect / reset, against the control on this host."""
    with page.coll_lock:
        try:
            return _act(page, node)
        except Exception as ex:                  # the PyQt widget blocks for ever; this copy says why it stopped
            page.coll['label'] = 'no reply from the control at tcp://127.0.0.1:%d: %s' % (rep_port(page.partition), ex)
            return [['error', str(ex)]]


def _act(page, node):
    c = page.coll
    c['label'] = ''
    c['lists'] = {g: [] for g in GROUPS}
    c['replies'] = []
    if node['action'] == 'reset':
        c['replies'].append(_request(page, 'reset'))
        return [['reset', c['replies'][-1]]]
    for cmd in ['rollcall', 'alloc', 'connect']:
        r = _request(page, cmd)
        c['replies'].append(r)
        if 'err_info' in r['body']:
            c['label'] = r['body']['err_info']
            return [[cmd, r]]
    reply = _request(page, 'getstate')                                     # get_state
    c['replies'].append(reply)
    for group in reply['body']:
        if group in c['lists']:
            c['lists'][group] = [v['proc_info']['host'] for k, v in reply['body'][group].items()]
    return [[x['header']['key'], x['body'] if 'err_info' in x['body'] else 'ok'] for x in c['replies']]


def computed(page, values):
    if page.partition is None:
        return {}
    with page.coll_lock:
        out = {'coll:label': page.coll['label']}
        out.update({'coll:' + g: list(v) for g, v in page.coll['lists'].items()})
    return out
