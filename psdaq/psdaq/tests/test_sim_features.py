"""System features of the hardware-free DAQ without a DAQ: simxpm's readout groups at different
rates (--fixed-rates) and per-link seq and counts, its BLD source (--bld) over loopback multicast,
daq_sim's --also/--fixed-rate/--bld plumbing, the two-node plan (up --hosts A,B --dry-run) and the
two-host .cnf, address lists and TCP peers of up --hosts (psdaq.sim.twonode), the feature command's
argument checks, feature c's checks on a recorded result (ami_check again, --break ami-tamper) and
feature d's refusal unless two hosts of the job are given."""

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
    assert daq_sim.main(['up', '--hosts', 'nodeA,nodeB', '--dry-run', '--det', 'hrencoder']) == 0
    assert "id:'hrencoder_0'" in capsys.readouterr().out
    daq_sim.use_det('fakecam')
    assert daq_sim.main(['up', '--hosts', 'nodeA,nodeB']) == 1                 # not run on nodeA (twonode.check_hosts)
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


def test_scan_step_value_takes_numpy_numbers():
    """ConfigScanBase records MyFloatPv.position as step_value: generic_timing_scan.py yields
    np.arange values, which MyFloatPv.update dropped (step_value 0.0 in every step)."""
    np = pytest.importorskip('numpy')
    from psdaq.control.ControlDef import MyFloatPv
    m = MyFloatPv('step_value')
    for value, want in ((np.float64(700000.), 700000.), (np.float32(2.5), 2.5), (np.int64(7), 7.),
                        (3.5, 3.5), (4, 4.)):
        m.update(value)
        assert m.position == want and type(m.position) is float
    for value in ('5', None, True):
        m.update(value)
        assert m.position == 4.



def test_features_c_and_d_have_entries():
    from psdaq.sim import feature
    assert list(feature.FEATURES) == ['a', 'b', 'c', 'd', 'e']
    assert feature.up_options('c', 5) == ['--ami', '--rate', '100']
    assert feature.up_options('d', 5) == ['--segments', '2', '--rate', '100']
    assert feature.BREAKS['c'] == ('ami-tamper',) and feature.BREAKS['d'] == ('kill-remote-drp',)
    assert feature.unavailable('a') is None and feature.unavailable('c') is None


def test_feature_d_not_available_unless_two_allocated_hosts(monkeypatch, tmp_path, capsys):
    from psdaq.sim import feature
    import argparse
    import subprocess
    for k in ('SLURM_JOB_ID', 'SLURM_JOB_NODELIST', 'SLURM_NODELIST'):
        monkeypatch.delenv(k, raising=False)
    assert feature.allocated_hosts() == []
    why = feature.unavailable('d', 'nodeA,nodeB')
    assert 'not in this Slurm job' in why and 'not inside a Slurm job' in why

    def no_scontrol(*a, **k):
        raise OSError('no scontrol')
    monkeypatch.setattr(subprocess, 'run', no_scontrol)
    monkeypatch.setenv('SLURM_JOB_ID', '42')
    monkeypatch.setenv('SLURM_JOB_NODELIST', 'nodeA.example,nodeB')
    assert feature.allocated_hosts() == ['nodeA', 'nodeB']
    monkeypatch.setenv('SLURM_JOB_NODELIST', 'node[1-2]')           # needs scontrol to expand
    assert feature.allocated_hosts() == []
    monkeypatch.undo()

    monkeypatch.setattr(feature, 'allocated_hosts', lambda: ['nodeA'])
    monkeypatch.setenv('SLURM_JOB_ID', '42')
    for hosts in (None, '', 'nodeA', 'nodeA,nodeA', 'nodeA,nodeB,nodeC'):
        why = feature.unavailable('d', hosts)
        assert why.startswith('two nodes needs --hosts HOST_A,HOST_B') and 'job 42 holds nodeA' in why
    assert feature.unavailable('d', 'nodeA,nodeB') == 'nodeB not in this Slurm job\'s allocation (job 42 holds nodeA)'
    args = argparse.Namespace(feature='d', workdir=str(tmp_path), breakage=None, check_only=False, events=None,
                              platform=5, keep_up=False, timeout=60, hosts=None)
    assert feature.cmd_feature(args) == 1
    out = capsys.readouterr().out
    assert 'FEATURE d NOT AVAILABLE: two nodes needs --hosts' in out and 'FEATURE d FAIL' not in out
    args.breakage, args.check_only = 'ami-tamper', True
    with pytest.raises(daq_sim.Fail):
        feature.cmd_feature(args)

    monkeypatch.setattr(feature, 'allocated_hosts', lambda: ['nodeA', 'nodeB'])
    assert feature.unavailable('d', 'nodeA,nodeB') is None
    args.breakage, args.check_only, args.hosts = None, False, 'nodeA,nodeB'
    assert feature.cmd_feature(args) == 1                       # up --hosts runs only on nodeA: FAIL
    out = capsys.readouterr().out
    assert 'up| ' in out and 'run up --hosts on its first host nodeA' in out and 'FEATURE d FAIL' in out
    assert 'problem: up --hosts exit 1' in out and 'NOT AVAILABLE' not in out


def _ami_result(n=120, ts0=1 << 40):
    rows = [[ts0 + i, 100 + i, (7 * i) % 65536] for i in range(n)]
    return {'rows': rows + rows[:5], 'count': n, 'pixsum': sum(r[2] for r in rows)}, \
        {r[0]: (r[1], r[2]) for r in rows}


def test_feature_c_checks(monkeypatch, tmp_path):
    from psdaq.sim import feature, ami_check
    work = daq_sim.Work(str(tmp_path))
    xtc = tmp_path / 'data' / daq_sim.INSTRUMENT / 'tstx00001' / 'xtc'
    xtc.mkdir(parents=True)
    (xtc / 'tstx00001-r0003-s000-c000.xtc2').write_bytes(b'x')
    (tmp_path / 'logs').mkdir()
    result, events = _ami_result()
    (tmp_path / 'logs' / 'ami_check.rows.json').write_text(json.dumps(result))
    monkeypatch.setattr(ami_check, 'psana_events', lambda path, det='fakecam': events)
    png = tmp_path / 'ami-shot.png'
    png.write_bytes(b'png')
    monkeypatch.setattr(daq_sim, '_per_drp_counts', lambda *a, **k: {
        'drp fakecam_0': 'group 5: DAQ 4000 psana2 events 4000', 'per-DRP checks': 'PASS'})
    state = {'det': 'fakecam', 'meb': True, 'ami': True, 'platform': 5}
    rec = {'experiment': 'tstx00001', 'run': 3, 'ok': True,
           'counts': {'MEB_EvtCt': 4000, 'ami check': 'PASS', 'ami events': 120,
                      'ami shot': f'PASS {png}: window "fakecam:raw:raw" of ami-client pid 1, 30+ colours'}}

    counts, problems = feature.check_c(work, state, rec)
    assert problems == [] and counts['ami screenshot'] == str(png)
    counts, problems = feature.check_c(work, state, rec, recompute=True)      # --check-only
    assert problems == [] and counts['ami check'] == 'PASS' and counts['ami matched'] == 120
    counts, problems = feature.check_c(work, state, rec, breakage='ami-tamper')
    assert counts['ami check'].startswith('FAIL') and any(p.startswith('ami check: FAIL') for p in problems)
    assert json.loads((tmp_path / 'logs' / 'ami_check.rows.json').read_text()) == result   # file untouched

    for change, words in ((('MEB_EvtCt', 0), 'the MEB served no event'),
                          (('MEB_EvtCt', 100), 'more than the MEB served'),
                          (('ami shot', 'FAIL no grab'), 'ami shot: FAIL no grab'),
                          (('ami check', 'FAIL x'), 'ami check: FAIL x')):
        bad = dict(rec, counts=dict(rec['counts'], **dict([change])))
        assert any(words in p for p in feature.check_c(work, state, bad)[1]), change
    assert 'up --ami' in ' '.join(feature.check_c(work, dict(state, ami=False), rec)[1])
    png.unlink()
    assert any(p.startswith('ami shot: PASS') for p in feature.check_c(work, state, rec)[1])


def test_two_host_up_refuses_what_it_cannot_run(monkeypatch):
    """up --hosts A,B: two different hosts of this Slurm job, run on A, neither a hutch host, both with an
    address this host can tell apart (twonode.check_hosts)."""
    from psdaq.sim import twonode
    monkeypatch.setattr(twonode, 'allocated_hosts', lambda: ['nodeA', 'nodeB'])
    monkeypatch.setattr(twonode, 'ipv4', lambda h: {'nodeA': '10.0.0.1', 'nodeB': '10.0.0.2'}[twonode.short(h)])
    monkeypatch.setattr(twonode, 'nic_of', lambda ip: 'eth9' if ip == '10.0.0.1' else None)
    monkeypatch.setenv('SLURM_JOB_ID', '42')
    assert twonode.check_hosts('nodeA,nodeB', 'nodeA.example') == ('nodeA', 'nodeB',
                                                                  {'nodeA': '10.0.0.1', 'nodeB': '10.0.0.2'})
    for hosts, here, why in (('nodeA', 'nodeA', 'two different hosts'), ('nodeA,nodeA', 'nodeA', 'two different'),
                             ('nodeA,drp-srcf-cmp001', 'nodeA', 'hutch or DAQ host'),
                             ('nodeB,nodeA', 'nodeA', 'run up --hosts on its first host nodeB'),
                             ('nodeA,nodeC', 'nodeA', 'nodeC not in Slurm job 42')):
        with pytest.raises(ValueError, match=why):
            twonode.check_hosts(hosts, here)
    monkeypatch.delenv('SLURM_JOB_ID')
    with pytest.raises(ValueError, match='not inside a Slurm job'):
        twonode.check_hosts('nodeA,nodeB', 'nodeA')


def test_two_host_env_names_only_the_first_hosts_address():
    from psdaq.sim import twonode
    env = {'PROCMGR_EXPORT': 'EPICS_PVA_ADDR_LIST=127.0.0.1,HTTP_PROXY=http://127.0.0.1:9,FI_PROVIDER=tcp',
           'NO_PROXY': 'localhost,127.0.0.1'}
    got = twonode.apply_env(env, 'nodeA', 'nodeB', {'nodeA': '10.0.0.1', 'nodeB': '10.0.0.2'})
    assert got == twonode.epics_env('10.0.0.1', '10.0.0.1')
    lists = [v for k, v in env.items() if k.startswith('EPICS_') and 'AUTO' not in k]
    assert lists and set(lists) == {'10.0.0.1'}
    assert all(env[k] == 'NO' for k in env if k.startswith('EPICS_') and 'AUTO' in k)
    exported = dict(x.split('=', 1) for x in env['PROCMGR_EXPORT'].split(','))
    assert exported['EPICS_PVA_ADDR_LIST'] == '10.0.0.1' and exported['HTTP_PROXY'] == 'http://127.0.0.1:9'
    assert ' ' not in env['PROCMGR_EXPORT']             # procmgr sends each to tcsh as setenv K V
    assert set(env['NO_PROXY'].split(',')) >= {'10.0.0.1', '10.0.0.2', 'nodeA', 'nodeB', 'localhost'}
    assert twonode.epics_env('10.0.0.1', '10.0.0.2')['EPICS_PVAS_INTF_ADDR_LIST'] == '10.0.0.2'


def test_two_host_cnf_puts_the_other_drps_on_the_second_host(tmp_path):
    import argparse
    daq_sim.use_det('fakecam')
    work = daq_sim.Work(str(tmp_path / 'w'))
    two = {'hosts': ['nodeA', 'nodeB'], 'ips': {'nodeA': '10.0.0.1', 'nodeB': '10.0.0.2'},
           'nic': {'nodeA': 'eth9', 'nodeB': 'eth7'}}
    args = argparse.Namespace(platform=5, slow_update=1, length=64, seed=0x1234)
    P = daq_sim.ports(5)
    common = dict(instr=daq_sim.INSTRUMENT, ep=daq_sim.EP, prom=work.path('prom'), det='fakecam', drp='drp', env='',
                  frames=P['frames'], data=work.path('data'), length=64, v='',
                  simk=daq_sim.SIM_TYPES['fakecam']['kwargs'].format(length=64, seed=0x1234, work=work.dir))
    cnf = daq_sim.two_host_cnf(two, args, 'http://10.0.0.1:31050/ws/', daq_sim.parse_also(['hrencoder:5'], 5), 2,
                               common, work)
    ns = {}
    exec(cnf, {'platform': None, 'host': 'host', 'id': 'id', 'flags': 'flags', 'cmd': 'cmd', 'env': 'env'}, ns)
    e = {x['id']: x for x in ns['procmgr_config']}
    assert {i: x.get('host') for i, x in e.items()} == {'control': None, 'teb0': None, 'fakecam_0': None,
                                                       'fakecam_1': 'nodeB', 'hrencoder_0': 'nodeB'}
    for i in ('fakecam_1', 'hrencoder_0'):
        assert '-C nodeA' in e[i]['cmd'] and 'ep_domain=eth7' in e[i]['cmd'] and 'sim://10.0.0.1:' in e[i]['cmd']
        assert e[i]['env'] == 'EPICS_PVAS_INTF_ADDR_LIST=10.0.0.2 EPICS_CAS_INTF_ADDR_LIST=10.0.0.2'
    for i in ('teb0', 'fakecam_0'):
        assert 'ep_domain=eth9' in e[i]['cmd'] and 'ep_domain=lo' not in e[i]['cmd']
    assert 'sim://127.0.0.1' not in cnf and '-d http://10.0.0.1:31050/ws/configDB' in e['control']['cmd']


def test_tcp_peers_from_ss_lines():
    from psdaq.sim import twonode
    lines = ['0      0      10.0.0.1:41234   10.0.0.2:29980 users:(("drp",pid=1,fd=3))',
             '0 0 [::ffff:10.0.0.1]:5000 [::ffff:10.0.0.2]:6000 users:(("teb",pid=2,fd=4))',
             '0 0 127.0.0.1:1 127.0.0.1:2 users:(("x",pid=3,fd=1))', '0 0 10.0.0.1:7 10.0.0.9:8 users:(("y",pid=4))']
    got = twonode.established('10.0.0.2', '10.0.0.1', lines)
    assert [g[2] for g in got] == ['users:(("drp",pid=1,fd=3))', 'users:(("teb",pid=2,fd=4))']
    assert twonode.established('10.0.0.1', '10.0.0.2', lines) == []
