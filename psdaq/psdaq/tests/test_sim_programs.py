"""DAQ-free tests of daq_sim's MEB, AMI, drp_pva and epicsArch options (no DAQ runs here): the
procmgr entries they add name the programs the coverage rows count, AMI's console scripts, the
AMI check's verdict, and simxpm's camera PV."""

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
            'prog:control_gui', 'prog:groupca', 'prog:drp_udpencoder', 'prog:sim_udpencoder']
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
    others = {k: v for k, v in daq_sim.ports(5).items() if not k.startswith('ami')}
    assert not set(daq_sim.ami_ports(5)) & set(others.values())


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
    res = ami_check.check(dict(good, rows=rows + rows[:1], count=len(rows) + 1), None, minimum=1,
                          events=events)
    assert not res['pass'] and 'twice' in res['problems'][0]


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
