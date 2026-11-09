"""Unit test for simxpm's frame stream, with fake DRPs on ZMQ DEALER sockets.

Runs the generator in-process (no PVA traffic): python -m pytest psdaq/psdaq/tests/test_simxpm.py
The control.py -X test drives simxpm with control.py's own DaqXPM class, so it needs the DAQ env.
"""

import json
import socket
import struct
import threading
import time

import zmq

from psdaq.sim.simxpm import (FRAME, SimXpm, TransitionId, pack_frame, pull_commands,
                              pull_endpoint, unpack_frame)


def _drp(ctx, endpoint, alias, credit, group=0):
    s = ctx.socket(zmq.DEALER)
    s.setsockopt(zmq.LINGER, 0)
    s.connect(endpoint)
    s.send_multipart([b'HELLO', json.dumps({'alias': alias, 'lanes': 1}).encode()])
    kind, body = s.recv_multipart()
    assert kind == b'WELCOME'
    welcome = json.loads(body)
    s.send_multipart([b'CREDIT', struct.pack('<I', credit)])
    s.send_multipart([b'CONNECT', json.dumps({'group': group}).encode()])
    return s, welcome


def _frames(sock, timeout=0.5):
    out = []
    while sock.poll(int(timeout * 1000)):
        kind, body = sock.recv_multipart()
        assert kind == b'FRAMES' and len(body) % FRAME.size == 0
        out += [unpack_frame(body, o) for o in range(0, len(body), FRAME.size)]
    return out


def _transition(sim, tid, groups=1, hdr=None):
    for g in range(8):
        if groups & (1 << g):
            sim.command('msghdr', g, tid if hdr is None else hdr)
    sim.command('insert', None, groups)


def test_pack_roundtrip():
    f = unpack_frame(pack_frame(TransitionId.L1Accept, 0x123456789abc, 1234, 5678, 0x41, 77))
    assert f == {'tid': 12, 'pulseId': 0x123456789abc, 'seconds': 1234, 'nanoseconds': 5678,
                 'env': 0x41, 'seq': 77}


def test_run_sequence_and_deadtime():
    endpoint = 'tcp://127.0.0.1:31987'
    sim = SimXpm('SIMTEST', 3, endpoint, rate=2000.)
    t = threading.Thread(target=sim.run, daemon=True)
    t.start()
    ctx = zmq.Context.instance()
    try:
        a, wa = _drp(ctx, endpoint, 'cam_0', credit=100000)
        b, wb = _drp(ctx, endpoint, 'cam_1', credit=100000)
        assert (wa['xpm'], wa['link'], wb['link']) == (3, 0, 1)
        time.sleep(0.2)                 # Let CREDIT and CONNECT land

        _transition(sim, TransitionId.ClearReadout)
        _transition(sim, TransitionId.Configure)
        _transition(sim, TransitionId.Enable)
        sim.command('l0enable', None, 1)
        time.sleep(0.5)
        sim.command('l0disable', None, 1)
        _transition(sim, TransitionId.Disable, hdr=0x180 | TransitionId.Disable)

        fa, fb = _frames(a), _frames(b)
        assert [f['pulseId'] for f in fa] == [f['pulseId'] for f in fb], 'DRPs not in lockstep'
        tids = [f['tid'] for f in fa]
        n = tids.count(TransitionId.L1Accept)
        assert tids == [0, 2, 8] + [12] * n + [9], tids
        assert 500 < n < 1500, n        # 0.5 s at 2 kHz
        pids = [f['pulseId'] for f in fa]
        assert all(p < q for p, q in zip(pids, pids[1:])), 'pulseIds not increasing'
        assert [f['seq'] for f in fa if f['tid'] == 12] == list(range(1, n + 1))
        assert all(f['env'] == 1 for f in fa)
        assert sim.num_l0acc[0] == n

        # Credit exhausted on one link: L1s stop for both (lockstep), and Disable still waits
        b.send_multipart([b'DISCONNECT', b''])
        c, wc = _drp(ctx, endpoint, 'cam_2', credit=5)
        time.sleep(0.2)
        sim.command('l0enable', None, 1)
        time.sleep(0.3)
        sim.command('l0disable', None, 1)
        _transition(sim, TransitionId.Disable, hdr=0x180 | TransitionId.Disable)
        fa, fc = _frames(a), _frames(c)
        assert [f['tid'] for f in fc] == [12] * 5, [f['tid'] for f in fc]
        assert [f['pulseId'] for f in fa] == [f['pulseId'] for f in fc]
        assert sim.num_l0inp[0] > sim.num_l0acc[0]
        assert len(sim.pending) == 1    # Disable waits for credit, never dropped
        c.send_multipart([b'CREDIT', struct.pack('<I', 1)])
        fc = _frames(c)
        assert [f['tid'] for f in fc] == [TransitionId.Disable]
    finally:
        sim.stop.set()
        t.join(2)


def _free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_pull_commands():
    """pyxpm zrcv message format (pvctrls.py) -> simxpm commands, as control.py DaqXPM sends them."""
    assert pull_commands({'type': 'set_reg', 'reg': 'groupL0Reset', 'value': 1}) == ([('l0reset', None, 1)], [])
    assert pull_commands({'type': 'set_reg', 'reg': 'groupL0Disable', 'value': 3, 'pv': 'X:GroupL0Disable'}) == \
        ([('l0disable', None, 3)], ['X:GroupL0Disable'])
    assert pull_commands({'type': 'set_idx_reg', 'reg': 'msgHdr', 'groups': 0b101, 'value': 2}) == \
        ([('msghdr', 0, 2), ('msghdr', 2, 2)], [])
    assert pull_commands({'type': 'set_reg', 'reg': 'groupMsgInsert', 'value': 5}) == ([('insert', None, 5)], [])
    assert pull_commands({'type': 'set_reg', 'reg': 'stepEnd3', 'value': 1000, 'pv': 'P:3:StepEnd'}) == \
        ([('stepend', 3, 1000)], ['P:3:StepEnd'])
    assert pull_commands({'type': 'set_reg', 'reg': 'stepGroup0', 'value': 1, 'pv': ['a', 'b']}) == \
        ([('stepgroups', 0, 1)], ['a', 'b'])
    for bad in ({'type': 'set_reg', 'reg': 'groupL0Bogus', 'value': 1},
                {'type': 'set_reg', 'reg': 'stepEnd8', 'value': 1},
                {'type': 'set_idx_reg', 'reg': 'other', 'groups': 1, 'value': 1},
                {'type': 'insert_msg', 'value': 1},
                {'type': 'set_reg', 'reg': 'groupL0Reset'}):
        try:
            pull_commands(bad)
        except ValueError:
            continue
        raise AssertionError(f'accepted {bad}')


class _StubPva:
    """Stands in for control.py's PVA helper: records every put, serves no PV."""
    def __init__(self):
        self.puts = []

    def pv_put(self, pv, value, **kwargs):
        self.puts += [(name, value) for name in (pv if isinstance(pv, list) else [pv])]
        return True

    def pv_get(self, pv, **kwargs):
        return None


def test_control_daqxpm_over_zmq():
    """control.py -X 127.0.0.1: control.py's own DaqXPM drives simxpm through its PULL socket."""
    from psdaq.control.ControlDef import ControlDef, xpm_pull_port
    from psdaq.control.control import DaqXPM

    tid = ControlDef.transitionId
    xpm = _free_port() - xpm_pull_port('SIMTEST:XPM:0')     # So that DaqXPM's port is free
    prefix = f'SIMTEST:XPM:{xpm}'
    pull = pull_endpoint('auto', prefix)
    assert pull == f'tcp://127.0.0.1:{xpm_pull_port(prefix)}', pull
    endpoint = f'tcp://127.0.0.1:{_free_port()}'
    sim = SimXpm('SIMTEST', xpm, endpoint, rate=2000., pull=pull)
    t = threading.Thread(target=sim.run, daemon=True)
    t.start()
    ctx = zmq.Context.instance()
    pva = _StubPva()
    errors = []
    daqxpm = None
    try:
        a, _ = _drp(ctx, endpoint, 'cam_0', credit=100000)
        time.sleep(0.2)
        daqxpm = DaqXPM(platform=0, xpm_master=xpm, pv_base='SIMTEST', pva=pva, zctxt=ctx,
                        xpm_host='127.0.0.1', report_error=errors.append)
        assert not daqxpm._usepva
        assert daqxpm.allocate(1)               # PVA: L0Groups
        daqxpm.clear_readout(1)                 # ZMQ: groupL0Reset, msgHdr, groupMsgInsert (+1 s)
        daqxpm.insert_transition(1, tid['Configure'])
        daqxpm.setup_step(0, 1, 1000000)        # ZMQ: stepEnd0, stepGroup0 (+ PVA StepDone=0)
        daqxpm.insert_transition(1, tid['Enable'])
        assert daqxpm.group_run(1, True)
        time.sleep(0.5)
        assert daqxpm.group_run(1, False)
        daqxpm.insert_transition(1, 0x180 | tid['Disable'])

        frames = _frames(a)
        tids = [f['tid'] for f in frames]
        n = tids.count(TransitionId.L1Accept)
        assert tids == [tid['ClearReadout'], tid['Configure'], tid['Enable']] + [12] * n + [tid['Disable']], tids
        assert 500 < n < 1500, n                # 0.5 s at 2 kHz
        assert [f['seq'] for f in frames if f['tid'] == 12] == list(range(1, n + 1))
        assert sim.num_l0acc[0] == n
        assert sim.pull_count == 13, sim.pull_count  # L0Reset + 4 transitions x 2 + 2 step + 2 run
        names = {name.rsplit(':', 1)[1] for name, _ in pva.puts}
        assert names == {'L0Groups', 'StepDone'}, names  # Nothing frame-producing went over PVA
        assert sim.step_end[0] == 1000000 and sim.step_groups[0] == 1
        # pyxpm posts the value of a message's 'pv' entry; so does simxpm
        assert sim.pvs[f'{prefix}:GroupL0Disable'][0].current()['value'] == 1
        assert sim.pvs[f'{prefix}:PART:0:StepEnd'][0].current()['value'] == 1000000
        assert not errors, errors
    finally:
        if daqxpm is not None:
            daqxpm.push.close(0)
        sim.stop.set()
        t.join(2)


if __name__ == '__main__':
    test_pack_roundtrip()
    test_run_sequence_and_deadtime()
    test_pull_commands()
    test_control_daqxpm_over_zmq()
    print('test_simxpm: OK')


def _value(sim, name):
    pv, nt = sim.pvs[name]
    return pv.current()['value']


def test_ts_config_pvs_and_link_ready():
    """The PVs ts_config.py and ts_connect.py use exist with pyxpm's names, and LinkRxReady<n>
    is 1 exactly while a DRP holds link n."""
    endpoint = 'tcp://127.0.0.1:%d' % _free_port()
    sim = SimXpm('SIMTEST', 2, endpoint, rate=100.)
    X = 'SIMTEST:XPM:2'
    for g in range(8):
        for name in ['L0Select', 'L0Select_FixedRate', 'L0Select_EventCode', 'L0Select_ACRate',
                     'L0Select_ACTimeslot', 'L0RawUpdate', 'DstSelect', 'DstSelect_Mask'] + \
                    ['%s%d' % (k, i) for k in ('InhInterval', 'InhLimit', 'InhEnable')
                     for i in range(4)]:
            assert f'{X}:PART:{g}:{name}' in sim.pvs, name
    for n in range(14):
        for name in ('RemoteLinkId', 'LinkGroupMask', 'LinkRxReady', 'LinkRxErrI', 'RxLinkReset'):
            assert f'{X}:{name}{n}' in sim.pvs
    assert 'simxpm' in _value(sim, f'{X}:FwBuild')
    t = threading.Thread(target=sim.run, daemon=True)
    t.start()
    ctx = zmq.Context.instance()
    try:
        assert _value(sim, f'{X}:LinkRxReady0') == 0
        a, wa = _drp(ctx, endpoint, 'ts_0', credit=10)
        time.sleep(0.2)
        assert _value(sim, f'{X}:LinkRxReady{wa["link"]}') == 1
        assert _value(sim, f'{X}:RemoteLinkId{wa["link"]}') == 0     # not an XPM: no recursion
        a.send_multipart([b'BYE', b''])
        time.sleep(0.2)
        assert _value(sim, f'{X}:LinkRxReady{wa["link"]}') == 0
    finally:
        sim.stop.set()
        t.join(2)


def test_pattern_stats_and_xpmpva_start_pvs():
    """PATT:GROUPS: Sum, the low 20 bits of the first and last L0Accept's pulse IDs of the second, the least and most
    pulse IDs between two, all ones for a group with none; and the PVs xpmpva reads at start (PAddr, Us:RxAlign,
    SFPSTATUS) are served."""
    sim = SimXpm('SIMTEST', 3, f'tcp://127.0.0.1:{_free_port()}', rate=100.)
    try:
        sim.patt = {5: [0x1234567, 0x1240000, 9285, 9290]}
        sim.num_l0acc[5], sim._last_acc = 100, [0] * 8          # run() starts _last_acc
        sim._post_patt()
        rows = sim.pvs['SIMTEST:XPM:3:PATT:GROUPS'][0].current().todict()['value']
        assert (rows['Sum'][5], rows['First'][5], rows['Last'][5], rows['MinIntv'][5], rows['MaxIntv'][5]) == \
            (100, 0x34567, 0x40000, 9285, 9290)
        assert (rows['First'][0], rows['MinIntv'][0], rows['MaxIntv'][0]) == ((1 << 20) - 1, (1 << 20) - 1, 0)
        assert sim.patt == {}
        for name in ('PAddr', 'Us:RxAlign', 'Cu:RxAlign', 'SFPSTATUS'):
            assert f'SIMTEST:XPM:3:{name}' in sim.pvs, name
    finally:
        sim.stop.set()
