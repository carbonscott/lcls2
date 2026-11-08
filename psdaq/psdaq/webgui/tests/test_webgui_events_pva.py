"""The events counter from the timing source (--events-source pva) and its network guard.

- netguard.require_loopback_pva_env: the server exits 2 unless EPICS_PVA_AUTO_ADDR_LIST=NO and
  every EPICS_PVA_ADDR_LIST / EPICS_PVA_NAME_SERVERS entry is a loopback IP literal.
- RunLatch: final only after the run stopped (second equal read), held through
  EndRun/Unconfigure/Reset, released at the next BeginRun.
- PvaCountEvents against a p4p PV server on 127.0.0.1 (DAQ-env python; skipped without p4p).
"""

import json
import subprocess
import sys
import textwrap

import pytest

from webgui_harness import PKG_ROOT, SERVER_PYTHON, server_env

sys.path.insert(0, str(PKG_ROOT))

from psdaq.webgui.events import RunLatch, xpm_count_pv          # noqa: E402
from psdaq.webgui.netguard import NonLoopbackError, require_loopback_pva_env  # noqa: E402

GOOD = {'EPICS_PVA_AUTO_ADDR_LIST': 'NO', 'EPICS_PVA_ADDR_LIST': '127.0.0.1',
        'EPICS_PVA_BROADCAST_PORT': '15076', 'EPICS_PVA_SERVER_PORT': '15075', 'EPICS_PVA_NAME_SERVERS': ''}
PVA_ARGS = ['--events-source', 'pva', '--events-pvbase', 'DAQ:SIM', '-p', '5', '--port', '0']


def run_server(args, env_over, drop=()):
    env = server_env()
    for k in list(env):
        if k.startswith('EPICS_PVA'):
            del env[k]
    env.update(env_over)
    for k in drop:
        env.pop(k, None)
    return subprocess.run([SERVER_PYTHON, '-m', 'psdaq.webgui.server'] + args, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)


def test_pv_name_follows_xpm_naming():
    assert xpm_count_pv('DAQ:SIM', 0, 5) == 'DAQ:SIM:XPM:0:PART:5:NumL0Acc'
    assert xpm_count_pv('DAQ:NEH', 2, 3, 'NumL0Inp') == 'DAQ:NEH:XPM:2:PART:3:NumL0Inp'


@pytest.mark.parametrize('over,drop', [
    ({'EPICS_PVA_AUTO_ADDR_LIST': 'YES'}, ()),
    ({}, ('EPICS_PVA_AUTO_ADDR_LIST',)),
    ({'EPICS_PVA_ADDR_LIST': ''}, ()),
    ({'EPICS_PVA_ADDR_LIST': '127.0.0.1 172.24.0.1'}, ()),
    ({'EPICS_PVA_ADDR_LIST': 'localhost'}, ()),                  # names are not looked up
    ({'EPICS_PVA_ADDR_LIST': '255.255.255.255'}, ()),
    ({'EPICS_PVA_NAME_SERVERS': '134.79.0.1:5075'}, ()),
], ids=['auto-yes', 'auto-unset', 'addr-empty', 'addr-offhost', 'addr-name', 'addr-bcast', 'nameserver-offhost'])
def test_server_refuses_non_loopback_pva_env(over, drop):
    r = run_server(PVA_ARGS + ['--print-config'], dict(GOOD, **over), drop)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert 'refusing' in r.stderr, r.stderr
    with pytest.raises(NonLoopbackError):
        require_loopback_pva_env(dict({k: v for k, v in GOOD.items() if k not in drop}, **over))


def test_server_accepts_loopback_pva_env():
    r = run_server(PVA_ARGS + ['--print-config'], GOOD)
    if r.returncode != 0 and 'p4p' in r.stderr:
        pytest.skip('server python has no p4p: %s' % r.stderr[-200:])
    assert r.returncode == 0, r.stderr
    cfg = json.loads(r.stdout)
    assert cfg['events_source'] == 'pva'
    assert cfg['events_pv'] == 'DAQ:SIM:XPM:0:PART:5:NumL0Acc'
    assert cfg['events_drops_pv'] == 'DAQ:SIM:XPM:0:PART:5:NumL0Inp'
    assert cfg['events_pva_conf']['EPICS_PVA_AUTO_ADDR_LIST'] == 'NO'
    assert cfg['events_pva_conf']['EPICS_PVA_ADDR_LIST'] == '127.0.0.1'
    assert cfg['all_loopback'] is True


def test_latch_sequence():
    L = RunLatch()
    # before any run: live, never final
    assert L.feed('configured', 'configure', 0, 0, 1.0) == (0, 0, 1.0, False)
    # running: live
    assert L.feed('running', 'enable', 500, 0, 2.0) == (500, 0, 2.0, False)
    assert L.feed('running', 'enable', 1282, 0, 3.0) == (1282, 0, 3.0, False)
    # first read after Disable: the count posted at Disable, not final yet
    assert L.feed('paused', 'disable', 1857, 0, 4.0) == (1857, 0, 4.0, False)
    # second equal read: final, ts of that read
    assert L.feed('paused', 'disable', 1857, 0, 5.0) == (1857, 0, 5.0, True)
    # held through EndRun, Unconfigure, Reset, even if the PV changes or fails
    assert L.feed('configured', 'endrun', 1857, 0, 6.0) == (1857, 0, 5.0, True)
    assert L.feed('connected', 'unconfigure', 0, 0, 7.0) == (1857, 0, 5.0, True)
    assert L.feed('reset', 'reset', None, None, 8.0) == (1857, 0, 5.0, True)
    # next run: BeginRun releases the latch
    assert L.feed('starting', 'beginrun', 0, 0, 9.0) == (0, 0, 9.0, False)
    assert L.feed('running', 'enable', 10, 0, 10.0) == (10, 0, 10.0, False)


@pytest.mark.parametrize('state,transition', [('configured', 'configure'), ('starting', 'beginrun'),
                                              ('paused', 'beginstep'), ('running', 'enable')])
def test_latch_released_by_any_transition_up(state, transition):
    """A 1 s poll may miss BeginRun (configured -> starting -> paused -> running in 0.2 s)."""
    L = RunLatch()
    L.feed('running', 'enable', 100, 0, 1.0)
    L.feed('paused', 'disable', 120, 0, 2.0)
    assert L.feed('configured', 'endrun', 120, 0, 3.0) == (120, 0, 3.0, True)
    assert L.feed(state, transition, 0, 0, 4.0) == (0, 0, 4.0, False)


def test_latch_held_through_transitions_down():
    L = RunLatch()
    L.feed('running', 'enable', 100, 0, 1.0)
    L.feed('paused', 'disable', 120, 0, 2.0)
    assert L.feed('paused', 'disable', 120, 0, 3.0)[3] is True
    for state, tr in (('starting', 'endstep'), ('configured', 'endrun'), ('connected', 'unconfigure'),
                      ('allocated', 'disconnect'), ('unallocated', 'dealloc'), ('reset', 'reset'),
                      ('unallocated', 'rollcall'), ('allocated', 'alloc'), ('connected', 'connect')):
        assert L.feed(state, tr, 0, 0, 9.0) == (120, 0, 3.0, True), (state, tr)


def test_latch_needs_two_equal_reads_after_stop():
    L = RunLatch()
    L.feed('running', 'enable', 100, 0, 1.0)
    assert L.feed('paused', 'disable', 120, 0, 2.0)[3] is False
    assert L.feed('paused', 'disable', 130, 0, 3.0)[3] is False     # still moving: not final
    assert L.feed('paused', 'disable', 130, 0, 4.0) == (130, 0, 4.0, True)


def test_latch_not_final_while_running_or_on_error():
    L = RunLatch()
    for i in range(5):
        assert L.feed('running', 'enable', 1000, 0, float(i))[3] is False   # a stalled run is not final
    assert L.feed('paused', 'disable', None, None, 6.0)[3] is False       # failed read
    assert L.feed('paused', 'disable', 1000, 0, 7.0)[3] is False
    assert L.feed('paused', 'disable', 1000, 0, 8.0)[3] is True


PVA_SCRIPT = textwrap.dedent('''
    import json, os, sys, time
    from p4p.nt import NTScalar
    from p4p.server import Server, StaticProvider
    from p4p.server.thread import SharedPV
    acc = SharedPV(nt=NTScalar('f'), initial=0.)
    inp = SharedPV(nt=NTScalar('f'), initial=0.)
    prov = StaticProvider('t')
    prov.add('T:XPM:0:PART:3:NumL0Acc', acc)
    prov.add('T:XPM:0:PART:3:NumL0Inp', inp)
    with Server(providers=[prov], conf={'EPICS_PVAS_INTF_ADDR_LIST': '127.0.0.1',
                                        'EPICS_PVAS_SERVER_PORT': '0', 'EPICS_PVAS_BROADCAST_PORT': '0',
                                        'EPICS_PVAS_AUTO_BEACON_ADDR_LIST': 'NO',
                                        'EPICS_PVAS_BEACON_ADDR_LIST': '127.0.0.1'}, useenv=False) as S:
        port = S.conf()['EPICS_PVAS_SERVER_PORT']
        env = {'EPICS_PVA_AUTO_ADDR_LIST': 'NO', 'EPICS_PVA_ADDR_LIST': '127.0.0.1',
               'EPICS_PVA_NAME_SERVERS': '127.0.0.1:%s' % port}
        from psdaq.webgui.netguard import require_loopback_pva_env
        from psdaq.webgui.events import PvaCountEvents
        src = PvaCountEvents('T:XPM:0:PART:3:NumL0Acc', require_loopback_pva_env(env),
                             'T:XPM:0:PART:3:NumL0Inp')
        class Hub:
            import threading
            lock = threading.Lock()
            status = {'state': 'running', 'transition': 'enable'}
        src.bind(Hub)
        out = []
        for state, a, i in (('running', 1234., 1240.), ('paused', 2000., 2003.), ('paused', 2000., 2003.),
                            ('reset', 0., 0.)):
            Hub.status = {'state': state, 'transition': None}
            acc.post(a); inp.post(i)
            time.sleep(0.2)
            t0 = time.time()
            r = src.poll()
            r['read_after'] = r['ts'] >= t0
            out.append(r)
        src.close()
        print(json.dumps({'port': port, 'polls': out}))
''')


def test_pva_source_reads_a_loopback_pv(tmp_path):
    env = server_env()
    r = subprocess.run([SERVER_PYTHON, '-c', PVA_SCRIPT], env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True, timeout=60)
    if r.returncode != 0 and "No module named 'p4p'" in r.stderr:
        pytest.skip('server python has no p4p')
    assert r.returncode == 0, r.stderr[-2000:]
    polls = json.loads(r.stdout.strip().splitlines()[-1])['polls']
    assert [(p['events'], p['drops'], p['final'], p['ok']) for p in polls] == [
        (1234, 6, False, True), (2000, 3, False, True), (2000, 3, True, True), (2000, 3, True, True)], polls
    assert all(p['read_after'] for p in polls[:3]), polls
    assert polls[3]['ts'] == polls[2]['ts']          # latched: the ts of the read that made it final
