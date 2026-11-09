"""DAQ-free tests of daq_sim's MEB, AMI, drp_pva and epicsArch options (no DAQ runs here): the
procmgr entries they add name the programs the coverage rows count, AMI's console scripts, the
AMI check's verdict, and simxpm's camera PV."""

import json
import os
import subprocess
import sys

import pytest

from psdaq.sim import ami_check, coverage, daq_sim

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = coverage.find_repo(HERE)


def write_cnf(path, extra):
    with open(path, 'w') as f:
        f.write(daq_sim.CNF.format(
            when='now', platform=5, alias='BEAM', instr='tst', xpm=0, pvbase='DAQ:SIM', trigger='tmoteb',
            slow=1, configdb='http://127.0.0.1:1/ws/configDB', lgbk='http://127.0.0.1:2/',
            activedet='/dev/null', ep=daq_sim.EP, prom='/tmp', det='fakecam', frames=3, data='/tmp',
            length=64, v='', segments=extra,
            simk=daq_sim.SIM_TYPES['fakecam']['kwargs'].format(length=64, seed=0x1234)))
    return path


def test_extra_entries_start_the_programs_the_rows_count(tmp_path):
    """--meb, --ami, --pva and --epics add procmgr entries whose programs are rows coverage
    enumerates from the tree's configs, so a passing cycle's record names them."""
    extra = daq_sim.extra_entries(str(tmp_path), 5, meb=True, ami_bin=str(tmp_path / 'bin'),
                                  pva=True, epics=True, gui=True, udp=True)
    rows = coverage.config_rows(write_cnf(str(tmp_path / 'daq_sim.cnf'), extra))
    want = ['prog:monReqServer', 'prog:shmemClient', 'prog:ami-manager', 'prog:ami-global',
            'prog:ami-node', 'prog:ami-worker', 'prog:ami-client', 'prog:drp_pva', 'prog:epicsArch',
            'prog:control_gui', 'prog:groupca', 'prog:partca', 'prog:pvant', 'prog:procstat', 'prog:epics_exporter',
            'prog:drp_udpencoder',
            'prog:sim_udpencoder']
    assert sorted(rows) == sorted(['det:drp:fakecam', 'prog:control', 'prog:drp', 'prog:teb'] + want)
    enumerated, problems = coverage.enumerate_rows(REPO)
    assert [r for r in want if r not in enumerated] == []


def test_extra_entries_stay_on_loopback(tmp_path):
    """Every AMI address is 127.0.0.1 and the system DRPs read the sim:// device."""
    extra = daq_sim.extra_entries(str(tmp_path), 5, ami_bin='/b', pva=True, epics=True)
    for line in extra.splitlines():
        if 'ami-' in line and 'cmd' in line:
            assert '-H 127.0.0.1' in line, line
    assert extra.count('-d sim://127.0.0.1:') == 2
    udp = daq_sim.extra_entries(str(tmp_path), 5, udp=True)
    assert f'-L {daq_sim.ports(5)["udp"]}' in udp and f'-a 127.0.0.1 -d {daq_sim.ports(5)["udp"]}' in udp
    assert '-T sim://127.0.0.1:' in udp
    assert f'psana://shmem={daq_sim.meb_tag(5)}' in extra and f'-t {daq_sim.meb_tag(5)}' in extra
    assert daq_sim.ami_ports(5) == list(range(31150, 31160))
    others = {k: v for k, v in daq_sim.ports(5).items() if not k.startswith('ami') and isinstance(v, int)}
    assert not set(daq_sim.ami_ports(5)) & set(others.values())
    servers = [p for pair in daq_sim.ports(5)['pvservers'].values() for p in pair]
    assert len(set(servers)) == len(servers) and not set(servers) & (set(daq_sim.ami_ports(5)) | set(others.values()))


def test_procs_and_activedet(tmp_path):
    state = {'segments': 1, 'meb': True, 'ami': True, 'pva': True, 'epics': True, 'gui': True, 'udp': True}
    procs = daq_sim.procs(state)
    for p in ('meb0', 'shmc0', 'ami-manager', 'ami-worker_0', 'pvcam_0', 'epics_0', 'control_gui', 'groupca', 'encoder_0', 'simenc'):
        assert p in procs
    path = str(tmp_path / 'activedet.json')
    daq_sim.write_activedet(path, 5, 1, True, ('pvcam_0', 'epics_0'))
    import json
    act = json.load(open(path))['activedet']
    assert act['meb'] == {'meb0': {'active': 1}}
    assert act['drp']['pvcam_0']['det_info']['readout'] == 5


def test_ami_scripts_run_the_source_trees_entry_points(tmp_path):
    src = tmp_path / 'amisrc'
    (src / 'ami').mkdir(parents=True)
    (src / 'ami' / '__init__.py').write_text('')
    for module, func in set(daq_sim.AMI_SCRIPTS.values()):
        f = src / (module.replace('.', '/') + '.py')
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, 'a') as out:
            out.write(f'def {func}():\n    print("{module}.{func}")\n    return 7\n')
    assert daq_sim.ami_source(str(src)) == str(src)
    bindir = daq_sim.ami_scripts(str(tmp_path / 'bin'), str(src))
    for name, (module, func) in daq_sim.AMI_SCRIPTS.items():
        r = subprocess.run([os.path.join(bindir, name)], capture_output=True, text=True)
        assert r.returncode == 7 and r.stdout.strip() == f'{module}.{func}', (name, r)
        assert coverage.resolve(os.path.join(bindir, name) + ' -p 31150')[0] == name


def test_ami_source_must_be_a_tree(tmp_path):
    with pytest.raises(daq_sim.Fail):
        daq_sim.ami_source(str(tmp_path))


def test_ami_check_verdict():
    events = {100 + k: (k + 1, 1000 + k) for k in range(200)}         # ts -> (seq, pixel)
    rows = [[ts, seq, pix] for ts, (seq, pix) in list(events.items())[::2]]
    good = {'rows': rows, 'pixsum': sum(r[2] for r in rows), 'count': len(rows)}
    res = ami_check.check(good, None, minimum=100, events=events)
    assert res['pass'] and res['ami matched'] == 100, res
    bad = dict(good, rows=[list(r) for r in rows])
    bad['rows'][5][2] += 1
    res = ami_check.check(bad, None, minimum=100, events=events)
    assert not res['pass'] and 'psana2 reads' in res['problems'][0]
    res = ami_check.check(dict(good, pixsum=good['pixsum'] + 1), None, minimum=100, events=events)
    assert not res['pass'] and 'ami_pixsum' in res['problems'][-1]
    res = ami_check.check(good, None, minimum=101, events=events)
    assert not res['pass'] and 'fewer than 101' in res['problems'][0]
    res = ami_check.check(dict(good, rows=rows + rows[:3]), None, minimum=100, events=events)
    assert res['pass'] and res['ami events'] == 100 and res['ami rows'] == 103, res    # resent rows
    res = ami_check.check(dict(good, rows=rows + [[rows[0][0], rows[0][1], rows[0][2] + 1]]), None,
                          minimum=1, events=events)
    assert not res['pass'] and 'disagree' in res['problems'][0]


def test_ami_graph_functions_need_no_psdaq():
    """dill ships the graph's functions by value, so AMI's processes need nothing of psdaq."""
    pytest.importorskip('ami')
    import dill
    import numpy as np
    nodes = ami_check.graph_nodes('fakecam')
    blob = dill.dumps(nodes)
    assert b'psdaq' not in blob
    raw = np.zeros((1, 64), dtype=np.uint16)
    raw[0, 4], raw[0, 5], raw[0, 8] = 7, 1, 99
    assert dill.loads(blob)[0].func(raw) == (7 + (1 << 16), 99)


def test_camera_pv_carries_the_l1accept_time():
    pytest.importorskip('p4p')
    import numpy as np
    from p4p.server import StaticProvider
    from psdaq.sim import simxpm
    cam = simxpm.CameraPV('SIM:CAM', StaticProvider('t'), 0x1234)
    cam.post(1100000000, 123456789, 70000)
    v = cam.pv.current()
    assert v['timeStamp.secondsPastEpoch'] == 1100000000 + simxpm.POSIX_TIME_AT_EPICS_EPOCH
    assert v['timeStamp.nanoseconds'] == 123456789 and v['uniqueId'] == 70000
    img = np.asarray(v['value']).reshape(simxpm.CAMERA_SHAPE)
    assert (img == simxpm.camera_image(0x1234, 70000)).all()
    assert int(img.flat[0]) | (int(img.flat[1]) << 16) == 70000
    assert not (simxpm.camera_image(0x1234, 70001) == img).all()


def test_sim_udpencoder_sends_one_frame_per_l1accept_from_simxpm(tmp_path):
    """sim_udpencoder -T sim:// takes its timing from simxpm (no /dev/tpra): one encoder frame
    per L1Accept of its readout group, frame counts 0, 1, ..., the 100/200 test pattern, and with
    -v each frame's time printed, the transitions' included (no DAQ: simxpm runs in this process
    on free ports, without its PVA server)."""
    import json
    import shutil
    import socket
    import struct
    import threading
    import time
    import zmq
    from psdaq.sim.simxpm import FRAME, SimXpm, TransitionId, unpack_frame
    exe = shutil.which('sim_udpencoder')
    if exe is None:
        pytest.skip('sim_udpencoder not built')

    def free(kind):
        s = socket.socket(socket.AF_INET, kind)
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
        s.close()
        return port
    endpoint = f'tcp://127.0.0.1:{free(socket.SOCK_STREAM)}'
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.bind(('127.0.0.1', 0))
    udp.settimeout(0.2)
    got, reading = [], threading.Event()
    reading.set()

    def reader():                       # drain as a DRP would, or the socket buffer overflows
        while reading.is_set():
            try:
                got.append(udp.recv(1024))
            except socket.timeout:
                pass
    rt = threading.Thread(target=reader, daemon=True)
    rt.start()
    sim = SimXpm('SIMUDP', 0, endpoint, rate=1000.)
    t = threading.Thread(target=sim.run, daemon=True)
    t.start()
    ctx = zmq.Context.instance()
    log = open(tmp_path / 'simenc.log', 'w+')
    p = subprocess.Popen([exe, '-T', 'sim://' + endpoint[len('tcp://'):], '-p', '2', '-a', '127.0.0.1',
                          '-d', str(udp.getsockname()[1]), '-v'], stdout=log, stderr=subprocess.STDOUT)
    drp = ctx.socket(zmq.DEALER)
    try:
        drp.setsockopt(zmq.LINGER, 0)
        drp.connect(endpoint)
        drp.send_multipart([b'HELLO', json.dumps({'alias': 'cam_0', 'lanes': 1}).encode()])
        assert drp.recv_multipart()[0] == b'WELCOME'
        drp.send_multipart([b'CREDIT', struct.pack('<I', 100000)])
        drp.send_multipart([b'CONNECT', json.dumps({'group': 2}).encode()])
        end = time.monotonic() + 20
        while not any(l.alias == 'sim_udpencoder_2' and l.group == 2 for l in list(sim.links.values())):
            assert time.monotonic() < end and p.poll() is None, 'sim_udpencoder never joined group 2'
            time.sleep(0.1)
        for tid in (TransitionId.Configure, TransitionId.Enable):
            sim.command('msghdr', 2, tid)
            sim.command('insert', None, 1 << 2)
        sim.command('l0enable', None, 1 << 2)
        time.sleep(0.5)
        sim.command('l0disable', None, 1 << 2)
        frames = []
        while drp.poll(1000):
            kind, body = drp.recv_multipart()
            frames += [unpack_frame(body, o) for o in range(0, len(body), FRAME.size)]
        l1 = [f for f in frames if f['tid'] == TransitionId.L1Accept]
        assert len(l1) > 200, len(frames)
        end = time.monotonic() + 5
        while len(got) < len(l1) and time.monotonic() < end:
            time.sleep(0.1)
        time.sleep(0.5)                 # and nothing more arrives
        assert len(got) == len(l1), (len(got), len(l1))
        counts = [struct.unpack_from('>H', g, 0)[0] for g in got]       # encoder_header_t.frameCount
        assert counts == list(range(len(l1))), counts[:5]
        values = [struct.unpack_from('>I', g, 32)[0] for g in got]       # channel 0 encoderValue
        assert values == [200 if c & 1 else 100 for c in counts], values[:5]
        log.flush()
        text = open(tmp_path / 'simenc.log').read()
        conf = [f for f in frames if f['tid'] == TransitionId.Configure][0]
        assert f'Timestamp {conf["seconds"]}.{conf["nanoseconds"]:09d}  Configure' in text, text[:500]
        assert text.count(' L1Accept ') == len(l1)
    finally:
        reading.clear()
        p.terminate()
        p.wait(5)
        drp.close()
        sim.stop.set()
        t.join(2)


def test_ami_check_lists_its_matches():
    """The witness lists every event AMI kept that psana2 read the same: [timestamp, seq, pixel]."""
    events = {100 + i: (i, 7 * i) for i in range(5)}
    res = ami_check.check({'rows': [[100 + i, i, 7 * i] for i in range(3)], 'pixsum': 21, 'count': 3}, None,
                          minimum=1, events=events)
    assert res['pass'] and res['matches'] == [[100, 0, 0], [101, 1, 7], [102, 2, 14]]
    res = ami_check.check({'rows': [[100, 0, 1]], 'pixsum': 1, 'count': 1}, None, minimum=1, events=events)
    assert not res['pass'] and res['matches'] == []


def test_served_by_names_the_processes_on_the_ports(tmp_path):
    """served_by finds a process of ours that holds a TCP socket on one of the ports (from /proc),
    and leaves out the pids it is told to."""
    import socket
    import time
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    code = (f'import socket,time; s=socket.socket(); s.bind(("127.0.0.1", {port})); s.listen(1); '
            'print("up", flush=True); time.sleep(30)')
    p = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline().strip() == 'up'
        found = ami_check.served_by([port])
        assert [x['pid'] for x in found] == [p.pid] and 'socket.socket()' in found[0]['cmdline']
        assert ami_check.served_by([port], exclude={p.pid}) == []
        assert ami_check.served_by([port + 1 if port < 65535 else port - 1]) == []
    finally:
        p.kill()
        p.wait()


def test_gui_witness_entry(tmp_path):
    """A walk whose partition PV showed two numbers passes; placeholders and other PVs do not count."""
    from psdaq.sim import gui_witness
    part = 'DAQ:SIM:XPM:0:PART:5'
    params = daq_sim.gui_params(5)
    assert params['part'] == part
    walk = {'argv': gui_witness.argv('groupca', params), 'instances': [
        {'pv': part + ':NumL0Acc', 'text': '300', 'texts': [['shown', '-'], ['pump:1', '120'], ['pump:1', '300']]},
        {'pv': 'DAQ:SIM:XPM:0:PART:3:NumL0Acc', 'text': '2', 'texts': [['shown', '1']]},
        {'pv': None, 'text': 'Clear', 'texts': []}]}
    path = tmp_path / 'groupca.walk.json'
    path.write_text(json.dumps(walk))
    e = gui_witness.entry('groupca', str(path), 0, 1794225080.0, 1794225085.0, part, params)
    assert e['pass'] and e['live'] == [part + ':NumL0Acc']
    assert e['reads'] == [{'name': part + ':NumL0Acc', 'values': ['-', '120', '300']}]
    assert e['start'] == 1794225080.0 - gui_witness.EPICS_EPOCH
    walk['instances'][0]['texts'] = [['shown', '-'], ['pump:1', '300']]
    path.write_text(json.dumps(walk))
    e = gui_witness.entry('groupca', str(path), 0, 0, 1, part, params)
    assert not e['pass'] and 'showed 2 or more distinct numbers' in e['problems'][0]
    e = gui_witness.entry('groupca', str(tmp_path / 'none.json'), 3, 0, 1, part, params)
    assert not e['pass'] and 'walk exited 3' in ' '.join(e['problems'])


def test_gui_entries_run_the_witnessed_argv(tmp_path):
    """The procmgr entries of --gui start each witnessed GUI with the argv its witness walk uses, so
    the GUI's own log and the walk agree."""
    from psdaq.sim import gui_witness
    extra = daq_sim.extra_entries(str(tmp_path), 5, gui=True)
    params = daq_sim.gui_params(5, str(tmp_path / 'prom'), str(tmp_path / 'daq_sim.cnf'))
    for name in list(gui_witness.WITNESS) + list(gui_witness.MONITORS):
        cmd = 'python -m psdaq.cas.partca' if name == 'partca' else name   # no partca console script
        assert f"cmd:'{cmd} {' '.join(gui_witness.argv(name, params))}'" in extra, name
    assert f"-M {tmp_path / 'prom'} -P DAQ:SIM:XPM:0 NumL0Acc" in extra


def test_monitor_witness_reads_the_exporters_gauges(tmp_path):
    """epics_exporter's gauges become reads named by the PV they export; its log gives the port."""
    from psdaq.sim import gui_witness
    log = tmp_path / 'pvrtmon_0.log'
    log.write_text('# CMDLINE: epics_exporter -H tst\nINFO:root:Providing run-time monitoring data on port 9203\n')
    assert gui_witness.exporter_port(str(log)) == 9203
    assert gui_witness.exporter_port(str(tmp_path / 'none.log')) is None
    seq = iter([{'NumL0Acc{instrument="tst",partition="5",id="xpm-0"}': 100.0,
                 'NumL0Acc{instrument="tst",partition="3",id="xpm-0"}': 0.0},
                {'NumL0Acc{instrument="tst",partition="5",id="xpm-0"}': 200.0,
                 'NumL0Acc{instrument="tst",partition="3",id="xpm-0"}': 0.0}])
    t0, t1, reads = gui_witness.scrape_reads(9203, ['NumL0Acc'], 'DAQ:SIM:XPM:0', 0.05, period=0.05,
                                             scrape=lambda port, names: next(seq))
    assert reads == [{'name': 'DAQ:SIM:XPM:0:PART:3:NumL0Acc', 'values': ['0']},
                     {'name': 'DAQ:SIM:XPM:0:PART:5:NumL0Acc', 'values': ['100', '200']}]
    params = daq_sim.gui_params(5, '/p')
    e = gui_witness.monitor_entry('epics_exporter', 9203, t0, t1, reads, params['part'], params)
    assert e['pass'] and e['live'] == ['DAQ:SIM:XPM:0:PART:5:NumL0Acc'] and len(e['reads']) == 1
    e = gui_witness.monitor_entry('epics_exporter', None, t0, t1, reads[:1], params['part'], params)
    assert not e['pass'] and 'its log names no Prometheus port' in e['problems']


def test_ami_shot_flowchart_views_the_source():
    from psdaq.sim import ami_shot
    fc = ami_shot.flowchart('fakecam:raw:raw')
    node = fc['nodes'][0]
    assert node['class'] == 'SourceNode' and node['name'] == 'fakecam:raw:raw' and node['state']['viewed']
    assert 'source_configuration' not in fc     # loading it must not reconfigure AMI's source


def test_procstat_witness_reads_its_table(tmp_path):
    from psdaq.sim import gui_witness
    params = daq_sim.gui_params(5, '/p', '/w/daq_sim.cnf')
    walk = {'argv': gui_witness.argv('procstat', params), 'instances': [
        {'cls': 'QTableWidget', 'pv': None, 'cells': [['control', 'RUNNING'], ['fakecam_0', ' SHUTDOWN'], [None, None]]}]}
    path = tmp_path / 'procstat.walk.json'
    path.write_text(json.dumps(walk))
    e = gui_witness.entry('procstat', str(path), 0, 0, 1, params['part'], params)
    assert e['kind'] == 'procmgr' and e['pass'] and e['live'] == ['procmgr:control']
    assert e['reads'] == [{'name': 'procmgr:control', 'values': ['RUNNING']},
                          {'name': 'procmgr:fakecam_0', 'values': ['SHUTDOWN']}]
    assert gui_witness.spec('procstat', params)['walk']['record_calls'][0].endswith('spawnConsole')


def test_stand_in_interfaces_come_from_the_programs_own_source():
    """hsdpvs's names from its ChipServer, tprcas's from the table its main() builds."""
    from psdaq.sim import gui_witness
    hsd = gui_witness.interface('hsdpvs', ['-P', 'X:HSD:A', 'X:HSD:B'])
    assert 'X:HSD:A:MONTIMING' in hsd and 'X:HSD:B:CONFIG' in hsd and len(hsd) == 2 * len([n for n in hsd if n.startswith('X:HSD:A:')])
    tpr = gui_witness.interface('tprcas', ['-P', 'X:TPR'])
    assert 'X:TPR:EVTCNT' in tpr and 'X:TPR:CH0:DELAY' in tpr and all(n.startswith('X:TPR:') for n in tpr)


def test_server_entry_reads_the_interface_and_live_pvs():
    """Every defined name got from the stand-in (a failed get is 'missing'), and the live PVs read until
    `seconds` pass; a stand-in that serves all and counts passes."""
    from psdaq.sim import gui_witness

    class Ctx:
        def __init__(self, missing=()):
            self.n, self.missing = 0, set(missing)

        def get(self, names, timeout=None, throw=True):
            if isinstance(names, list):
                return [TimeoutError() if n in self.missing else 1 for n in names]
            self.n += 1
            return self.n
    params = {'pvbase': 'X'}
    args = ['-P', 'X:TPR']
    names = gui_witness.interface('tprcas', args)
    e = gui_witness.server_entry('simtpr', params, 0, 0.05, period=0.02, prepared=(args, {'tprcas': names}, Ctx()))
    assert e['pass'] and e['interfaces']['tprcas'] == {'defined': len(names), 'served': len(names), 'missing': []}
    assert e['prefix'] == 'X:TPR' and e['live'] == ['X:TPR:EVTCNT']
    e = gui_witness.server_entry('simtpr', params, 0, 0.05, period=0.02,
                                 prepared=(args, {'tprcas': names}, Ctx(missing=['X:TPR:CH3:RATE'])))
    assert not e['pass'] and e['interfaces']['tprcas']['missing'] == ['X:TPR:CH3:RATE']
