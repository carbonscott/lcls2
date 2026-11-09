"""System features of the hardware-free DAQ without a DAQ: simxpm's readout groups at different
rates (--fixed-rates) and per-link seq and counts, its BLD source (--bld) over loopback multicast,
daq_sim's --also/--fixed-rate/--bld plumbing, the two-node plan (up --hosts A,B --dry-run) and the
feature command's argument checks."""

import json
import socket
import struct
import threading
import time

import pytest

zmq = pytest.importorskip('zmq')
pytest.importorskip('p4p')

from psdaq.sim import daq_sim, simxpm                    # noqa: E402
from psdaq.sim.simxpm import FRAME, SimXpm, TransitionId, unpack_frame   # noqa: E402


def _free_tcp():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return f'tcp://127.0.0.1:{port}'


def _link(ctx, endpoint, alias, group):
    """A fake DRP: HELLO, credit, CONNECT to a readout group."""
    d = ctx.socket(zmq.DEALER)
    d.setsockopt(zmq.LINGER, 0)
    d.connect(endpoint)
    d.send_multipart([b'HELLO', json.dumps({'alias': alias, 'lanes': 1}).encode()])
    assert d.recv_multipart()[0] == b'WELCOME'
    d.send_multipart([b'CREDIT', struct.pack('<I', 1000000)])
    d.send_multipart([b'CONNECT', json.dumps({'group': group}).encode()])
    return d


def _drain(d):
    frames = []
    while d.poll(500):
        kind, body = d.recv_multipart()
        frames += [unpack_frame(body, o) for o in range(0, len(body), FRAME.size)]
    return [f for f in frames if f['tid'] == TransitionId.L1Accept]


def _run_groups(fixed_rates, settle=1.0, rate=200.):
    """simxpm in this process (no PVA server), DRPs a0 (group 2) and b0, c0 (group 3); with
    fixed_rates group 2 on the 1.02 kHz marker and group 3 on 102 Hz."""
    endpoint = _free_tcp()
    sim = SimXpm('SIMFEAT', 0, endpoint, rate=rate, fixed_rates=fixed_rates)
    t = threading.Thread(target=sim.run, daemon=True)
    t.start()
    ctx = zmq.Context.instance()
    links = {'a0': _link(ctx, endpoint, 'a0', 2), 'b0': _link(ctx, endpoint, 'b0', 3),
             'c0': _link(ctx, endpoint, 'c0', 3)}
    try:
        end = time.monotonic() + 10
        while sum(l.group is not None for l in list(sim.links.values())) < 3:
            assert time.monotonic() < end
            time.sleep(0.05)
        sim.command('l0select', 2, 0)
        sim.command('fixedrate', 2, 3)
        sim.command('l0select', 3, 0)
        sim.command('fixedrate', 3, 4)
        sim.command('l0reset', None, 0xc)
        sim.command('l0enable', None, 0xc)
        time.sleep(settle)
        sim.command('l0disable', None, 0xc)
        time.sleep(0.3)
        got = {a: _drain(d) for a, d in links.items()}
        return sim, got
    finally:
        sim.stop.set()
        for d in links.values():
            d.close()
        t.join(2)


def test_fixed_rate_markers():
    assert simxpm.fixed_rate_hz(3) == pytest.approx(1020.408, rel=1e-5)
    assert simxpm.fixed_rate_hz(4) == pytest.approx(102.0408, rel=1e-5)
    assert simxpm.fixed_rate_hz(0) == pytest.approx(928571.4, rel=1e-6)
    assert simxpm.fixed_rate_hz(7) is None
    sim = SimXpm('SIMFEAT', 0, _free_tcp(), rate=100., fixed_rates=True)
    assert sim.group_rate(1) == 100.            # FixedRate 0 = 929 kHz: above --max-rate
    sim._do('fixedrate', 1, 4)
    assert sim.group_rate(1) == pytest.approx(102.04, rel=1e-3)
    sim._do('l0select', 1, 2)                   # EventCode: not a fixed rate
    assert sim.group_rate(1) == 100.
    off = SimXpm('SIMFEAT', 0, _free_tcp(), rate=100.)
    off._do('fixedrate', 1, 4)
    assert off.group_rate(1) == 100.            # without --fixed-rates: SIM:L1Rate, as before


def test_groups_at_fixed_rates_are_nested_and_each_link_counts_its_own_seq():
    sim, got = _run_groups(True)
    a, b, c = (got[k] for k in ('a0', 'b0', 'c0'))
    assert len(a) > 500, len(a)
    # group 3 fires on every 10th tick of group 2's marker (its first L1Accept on the first tick)
    assert len(b) == len(c) == (len(a) + 9) // 10, (len(a), len(b))
    assert [f['seq'] for f in a] == list(range(1, len(a) + 1))
    assert [f['seq'] for f in b] == list(range(1, len(b) + 1))     # its own group's count
    times = {(f['seconds'], f['nanoseconds']) for f in a}
    assert all((f['seconds'], f['nanoseconds']) in times for f in b)   # nested: also group 2's
    assert all(f['env'] == 0xc for f in b) and sum(f['env'] == 0x4 for f in a) == len(a) - len(b)
    counts = sim.link_counts()
    assert {k: v['l1acc'] for k, v in counts.items()} == {'a0': len(a), 'b0': len(b), 'c0': len(c)}
    assert sim.num_l0acc[2] == len(a) and sim.num_l0acc[3] == len(b)


def test_without_fixed_rates_every_group_takes_every_tick():
    sim, got = _run_groups(False, settle=0.6)
    assert len(got['a0']) == len(got['b0']) == len(got['c0']) > 50
    assert [f['seq'] for f in got['b0']] == list(range(1, len(got['b0']) + 1))


def test_bld_dest_and_packet():
    assert simxpm.check_bld_dest('239.254.31.5:31225') == ('239.254.31.5', 31225)
    for bad in ('239.255.24.0:10148', '127.0.0.1:31225', '224.0.0.1:31225'):
        with pytest.raises(ValueError):
            simxpm.check_bld_dest(bad)
    pkt = simxpm.bld_packet(0x1234, 7, 1000, 500, 0xabc)
    assert len(pkt) == 20 + 24                  # BldDetector.hh HeaderSize + severity and fields
    t, pid, ident = simxpm.BLD_HEADER.unpack_from(pkt, 0)
    assert (t, pid, ident) == ((1000 << 32) | 500, 0xabc, simxpm.BLD_ID)
    sevr, energy, value, seq = simxpm.BLD_PAYLOAD.unpack_from(pkt, 20)
    want_sevr, want = simxpm.bld_values(0x1234, 7)
    assert (sevr, energy, value, seq) == (want_sevr, want['energy'], want['value'], 7)
    assert simxpm.bld_values(0x1234, 8) != simxpm.bld_values(0x1234, 7)


def test_bld_source_sends_one_packet_per_l1accept_on_loopback_multicast():
    """A receiver joined on 127.0.0.1, as drp_bld joins with -k interface=lo, gets one packet per
    L1Accept, each with that L1Accept's time, pulseId and seq."""
    group, port = '239.254.31.7', None
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    rx.bind((group, 0))
    port = rx.getsockname()[1]
    rx.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                  socket.inet_aton(group) + socket.inet_aton('127.0.0.1'))
    rx.settimeout(0.5)
    endpoint = _free_tcp()
    sim = SimXpm('SIMBLD', 0, endpoint, rate=500., bld='SIM:BLD', bld_dest=f'{group}:{port}', bld_seed=0x55)
    assert 'SIM:BLD:BLD_PAYLOAD' in sim.provider.keys()
    assert sim.bld.sock.getsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL) == 1
    t = threading.Thread(target=sim.run, daemon=True)
    t.start()
    ctx = zmq.Context.instance()
    d = _link(ctx, endpoint, 'f0', 1)
    got = []
    try:
        end = time.monotonic() + 10
        while not any(l.group == 1 for l in list(sim.links.values())):
            assert time.monotonic() < end
            time.sleep(0.05)
        sim.command('l0enable', None, 0x2)
        time.sleep(0.5)
        sim.command('l0disable', None, 0x2)
        frames = _drain(d)
        while True:
            try:
                got.append(rx.recv(9000))
            except socket.timeout:
                break
    finally:
        sim.stop.set()
        d.close()
        rx.close()
        t.join(2)
    assert len(frames) > 100 and len(got) == len(frames) == sim.bld.sent
    for f, pkt in zip(frames, got):
        tm, pid, _ = simxpm.BLD_HEADER.unpack_from(pkt, 0)
        assert tm == (f['seconds'] << 32) | f['nanoseconds'] and pid == f['pulseId']
        assert pkt == simxpm.bld_packet(0x55, f['seq'], f['seconds'], f['nanoseconds'], f['pulseId'])


def test_also_and_fixed_rate_options():
    daq_sim.use_det('fakecam')
    also = daq_sim.parse_also(['epix100:6', 'wave8:6'], 5)
    assert also == [{'det': 'epix100', 'group': 6, 'alias': 'epix100_0'},
                    {'det': 'wave8', 'group': 6, 'alias': 'wave8_0'}]
    assert daq_sim.parse_also(['cspad'], 5)[0]['group'] == 5
    for bad in (['fakecam'], ['epix100', 'epix100:6'], ['nosuch'], ['epix100:9'], ['epixhremu']):
        with pytest.raises(daq_sim.Fail):
            daq_sim.parse_also(bad, 5)
    assert daq_sim.parse_fixed_rates(['5:3', '6:4']) == {5: 3, 6: 4}
    for bad in (['5'], ['8:3'], ['5:7']):
        with pytest.raises(daq_sim.Fail):
            daq_sim.parse_fixed_rates(bad)
    cnf = daq_sim.extra_entries('/w', 5, also=also, bld=True, seed=0x1234)
    assert "id:'epix100_0'" in cnf and '-D epix100 -d sim://127.0.0.1:31052' in cnf
    assert "id:'wave8_0'" in cnf and 'epics_prefix=SIM:W8:00' in cnf
    assert "id:'bld_0'" in cnf and 'drp_bld -P tst -C localhost -d sim://127.0.0.1:31052' in cnf
    assert '-k ep_domain=lo,ep_provider=tcp,interface=lo' in cnf and '-D simbld+scbld+DAQ:SIM:BLD' in cnf
    assert daq_sim.ports(5)['bld'] == 31225 and daq_sim.bld_group(5) == '239.254.31.5'
    simxpm.check_bld_dest(f'{daq_sim.bld_group(5)}:31225')


def test_barrier_conflict():
    assert daq_sim.barrier_conflict(['hrencoder', 'epix100', 'wave8']) is None
    assert daq_sim.barrier_conflict(['fakecam', 'cspad'], system_drps=True) is None
    assert 'epix100' in daq_sim.barrier_conflict(['fakecam', 'epix100'])
    assert daq_sim.barrier_conflict(['epix100'], system_drps=True)
    assert daq_sim.barrier_conflict(['piranha4', 'wave8'])


def test_activedet_puts_each_drp_in_its_group(tmp_path):
    daq_sim.use_det('fakecam')
    path = tmp_path / 'activedet.json'
    daq_sim.write_activedet(str(path), 5, 1, False, ('bld_0',), {'epix100_0': 6, 'wave8_0': 6})
    v = json.loads(path.read_text())
    assert {d: x['det_info']['readout'] for d, x in v['activedet']['drp'].items()} == \
        {'fakecam_0': 5, 'bld_0': 5, 'epix100_0': 6, 'wave8_0': 6}


def test_two_node_plan(capsys):
    daq_sim.use_det('fakecam')
    also = daq_sim.parse_also(['epix100:6'], 5)
    plan = daq_sim.multi_host_plan('nodeA', 'nodeB', 5, also, '/w',
                                   addr={'nodeA': '10.0.0.1', 'nodeB': '10.0.0.2'}, nic='eth9')
    cnf = plan['cnf']
    ns = {}
    exec(cnf, {'platform': None, 'host': 'host', 'id': 'id', 'flags': 'flags', 'cmd': 'cmd'}, ns)
    hosts = {e['id']: e['host'] for e in ns['procmgr_config']}
    assert hosts == {'control': 'nodeA', 'teb0': 'nodeA', 'fakecam_0': 'nodeA', 'epix100_0': 'nodeB'}
    assert '127.0.0.1' not in cnf and 'localhost' not in cnf and 'ep_domain=lo' not in cnf
    assert 'sim://10.0.0.1:31052' in cnf and '-C nodeA' in cnf and 'ep_domain=eth9' in cnf
    assert plan['env']['EPICS_PVA_ADDR_LIST'] == '10.0.0.1 10.0.0.2'
    assert plan['env']['EPICS_CA_ADDR_LIST'] == '10.0.0.1 10.0.0.2'
    assert plan['env']['EPICS_PVA_AUTO_ADDR_LIST'] == plan['env']['EPICS_CA_AUTO_ADDR_LIST'] == 'NO'
    for v in plan['endpoints'].values():
        assert '127.0.0.1' not in v and ('10.0.0.1' in v or 'nodeA' in v)
    assert plan['needs']
    assert daq_sim.main(['up', '--hosts', 'nodeA,nodeB', '--dry-run', '--also', 'epix100:6']) == 0
    out = capsys.readouterr().out
    assert "host:'nodeB', id:'epix100_0'" in out and 'EPICS_PVA_ADDR_LIST="nodeA nodeB"' in out
    assert daq_sim.main(['up', '--hosts', 'nodeA,nodeB']) == 1                 # plan only for now
    assert daq_sim.main(['up', '--hosts', 'nodeA,drp-srcf-cmp001', '--dry-run']) == 1
    assert daq_sim.main(['up', '--hosts', 'nodeA', '--dry-run']) == 1


def test_feature_rejects_a_break_of_another_feature(tmp_path):
    from psdaq.sim import feature
    import argparse
    args = argparse.Namespace(feature='a', workdir=str(tmp_path), breakage='expect-values',
                              check_only=True, events=None, platform=5, keep_up=False, timeout=60)
    with pytest.raises(daq_sim.Fail):
        feature.cmd_feature(args)
    args.breakage, args.check_only = 'drop-l1', False
    with pytest.raises(daq_sim.Fail):
        feature.cmd_feature(args)
    assert feature.up_options('a', 5) == ['--det', 'hrencoder', '--also', 'epix100:6', '--also', 'wave8:6',
                                          '--fixed-rate', '5:3', '--fixed-rate', '6:4']
    assert feature.up_options('a', 7)[3] == 'epix100:0'
