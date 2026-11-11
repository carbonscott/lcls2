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
            length=64, v='', drp='drp', env='', segments=extra,
            simk=daq_sim.SIM_TYPES['fakecam']['kwargs'].format(length=64, seed=0x1234)))
    return path


def test_extra_entries_start_the_programs_the_rows_count(tmp_path):
    """--meb, --ami, --pva and --epics add procmgr entries whose programs are rows coverage
    enumerates from the tree's configs, so a passing cycle's record names them."""
    extra = daq_sim.extra_entries(str(tmp_path), 5, meb=True, ami_bin=str(tmp_path / 'bin'),
                                  pva=True, epics=True, gui=True, udp=True, pvservers=True)
    rows = coverage.config_rows(write_cnf(str(tmp_path / 'daq_sim.cnf'), extra))
    want = ['prog:monReqServer', 'prog:shmemClient', 'prog:ami-manager', 'prog:ami-global',
            'prog:ami-node', 'prog:ami-worker', 'prog:ami-client', 'prog:drp_pva', 'prog:epicsArch',
            'prog:control_gui', 'prog:groupca', 'prog:partca', 'prog:pvant', 'prog:procstat', 'prog:epics_exporter',
            'prog:drp_udpencoder',
            'prog:sim_udpencoder', 'prog:hsdpva', 'prog:tprca', 'prog:dtica', 'prog:pvatable', 'prog:xpmpva', 'prog:deadca',
            'prog:bldcas', 'prog:hpsdbuscas', 'prog:daqstat']
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
    assert not set(daq_sim.SERVER_GUI_PROCS) & set(procs)            # R4 GUIs need --pvservers too
    assert set(daq_sim.SERVER_GUI_PROCS) <= set(daq_sim.procs(dict(state, pvservers=True)))
    assert not set(daq_sim.SERVER_GUI_PROCS) & set(daq_sim.procs(dict(state, gui=False, pvservers=True)))
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
    assert not cam.pv.isOpen()          # no client yet: it opens OPEN_S after one connects (CameraPV)
    cam._open(cam.clients)              # as onFirstConnect's timer does, with the last image
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
    for name in gui_witness.witnessed() + list(gui_witness.MONITORS):
        cmd = 'python -m psdaq.cas.partca' if name == 'partca' else name   # no partca console script
        assert f"cmd:'{cmd} {' '.join(gui_witness.argv(name, params))}'" in extra, name
    assert f"-M {tmp_path / 'prom'} -P DAQ:SIM:XPM:0 NumL0Acc" in extra
    assert all(f"id:'{g}'" not in extra for g in daq_sim.SERVER_GUI_PROCS)
    # R4: with --pvservers, each GUI on a stand-in searches only that stand-in's PVA ports
    both = daq_sim.extra_entries(str(tmp_path), 5, gui=True, pvservers=True)
    assert tuple(n for n in gui_witness.witnessed(True, True) if n not in gui_witness.witnessed()) == \
        daq_sim.SERVER_GUI_PROCS
    assert daq_sim.SERVER_GUI_PROCS == tuple(n for n, w in gui_witness.WITNESS.items() if w.get('server'))
    for name in daq_sim.SERVER_GUI_PROCS:
        W = gui_witness.WITNESS[name]
        cmd = f'python -m {W["module"]}' if W.get('module') else name
        entry = [e for e in both.split('},') if f"id:'{name}'" in e][0]
        assert f"cmd:'{cmd} {' '.join(gui_witness.argv(name, params))}'" in entry, name
        if W['server'] == 'simxpm':     # xpmpva: simxpm serves on the node's own PVA ports
            assert 'EPICS_PVA' not in entry and W['prefix'].format(**params) == 'DAQ:SIM:XPM:0', entry
            continue
        port = daq_sim.ports(5)['pvservers'][W['server']][1]
        assert f'EPICS_PVA_BROADCAST_PORT={port}' in entry and 'EPICS_PVA_AUTO_ADDR_LIST=NO' in entry, entry
    # the tree's own PV servers, each on its own PVA ports, as lab3-bld.cnf starts them
    for name in daq_sim.PVSERVER_PROCS:
        srv, bcast = daq_sim.ports(5)['pvservers'][name]
        entry = [e for e in both.split('},') if f"id:'{name}'" in e][0]
        assert f'EPICS_PVAS_SERVER_PORT={srv} EPICS_PVAS_BROADCAST_PORT={bcast}' in entry, entry
    assert "cmd:'bldcas -P DAQ:SIM -A 239.254.32.1 HPSEX'" in both and "cmd:'hpsdbuscas -P DAQ:SIM:HPSCPA'" in both
    assert all(f"id:'{g}'" not in daq_sim.extra_entries(str(tmp_path), 5, gui=True) for g in daq_sim.PVSERVER_PROCS)
    assert set(daq_sim.PVSERVER_PROCS) <= set(daq_sim.procs({'pvservers': True}))
    assert "cmd:'python -m psdaq.cas.dtica DAQ:SIM:DTI'" in both and "cmd:'hsdpva DAQ:SIM:HSD:1_DA:A DAQ:SIM:HSD:1_DA:B'" in both


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


def test_r4_entry_reads_the_stand_ins_pvs_widget_by_widget(tmp_path):
    """A GUI on a device stand-in (R4): its entry names the stand-in and its prefix, and keeps one read per
    widget, so two fields of one structure PV are never taken for one value that changed."""
    from psdaq.sim import gui_witness
    params = daq_sim.gui_params(5)
    hsd = 'DAQ:SIM:HSD:1_DA'
    walk = {'argv': gui_witness.argv('hsdpva', params), 'instances': [
        {'cls': 'QLineEdit', 'pv': hsd + ':A:MONTIMING', 'text': '7', 'texts': [['shown', '7'], ['pump:1', '7']]},
        {'cls': 'QLineEdit', 'pv': hsd + ':A:MONTIMING', 'text': '9', 'texts': [['shown', '9']]},
        {'cls': 'QLabel', 'pv': params['part'] + ':NumL0Acc', 'text': '5', 'texts': [['shown', '1'], ['pump:1', '5']]}]}
    path = tmp_path / 'hsdpva.walk.json'
    path.write_text(json.dumps(walk))
    e = gui_witness.entry('hsdpva', str(path), 0, 0, 1, params['part'], params)
    assert e['stand_in'] == 'simhsd' and e['prefix'] == hsd
    assert e['reads'] == [{'name': hsd + ':A:MONTIMING', 'widget': 'QLineEdit#0', 'values': ['7']},
                          {'name': hsd + ':A:MONTIMING', 'widget': 'QLineEdit#1', 'values': ['9']}]
    assert not e['pass'] and 'no widget bound to a PV under DAQ:SIM:HSD:1_DA (simhsd)' in e['problems'][0]
    walk['instances'][1].update(text='12', texts=[['shown', '0'], ['pump:1', '12']])   # built with '0', then the PV
    path.write_text(json.dumps(walk))
    e = gui_witness.entry('hsdpva', str(path), 0, 0, 1, params['part'], params)
    assert not e['pass'] and e['live'] == []
    walk['instances'][1].update(text='15kHz', texts=[['shown', '0'], ['pump:1', '12kHz'], ['pump:1', '15kHz']])
    path.write_text(json.dumps(walk))
    e = gui_witness.entry('hsdpva', str(path), 0, 0, 1, params['part'], params)
    assert e['pass'] and e['live'] == [hsd + ':A:MONTIMING']
    assert e['reads'][1]['values'] == ['0', '12kHz', '15kHz']
    assert gui_witness.reads(walk)[0]['values'] == ['7', '0', '12kHz', '15kHz']   # R2's merge, which R4 does not use
    assert gui_witness.pva_env(31301) == {'EPICS_PVA_ADDR_LIST': '127.0.0.1', 'EPICS_PVA_AUTO_ADDR_LIST': 'NO',
                                          'EPICS_PVA_BROADCAST_PORT': '31301'}
    assert gui_witness.SERVER_GUI_BLOCKERS == {}


def test_deadca_walks_on_simxpm_while_a_link_asserts_full(tmp_path, monkeypatch):
    """deadca (R4 on simxpm): procmgr runs it as python -m psdaq.cas.deadca <base> <platform> <shelf>; its entry passes
    when one DeadFLnk label (bound through its PvDblArray) shows 2 shares after its first text; the cycle's stimulus
    puts SIM:LinkFull with LINK_FULL on the link SIM:LinkL1Acc gives the DRP, and says why when it cannot."""
    from psdaq.sim import gui_witness
    from psdaq.sim.simxpm import NUM_LINKS
    W = gui_witness.WITNESS['deadca']
    params = daq_sim.gui_params(5, str(tmp_path / 'prom'), str(tmp_path / 'daq_sim.cnf'))
    assert gui_witness.argv('deadca', params) == ['DAQ:SIM', '5', '0'] and W['server'] == 'simxpm'
    assert "cmd:'python -m psdaq.cas.deadca DAQ:SIM 5 0'" in daq_sim.extra_entries(str(tmp_path), 5, gui=True,
                                                                                  pvservers=True)
    dead = 'DAQ:SIM:XPM:0:PART:5:DeadFLnk'
    walk = {'argv': ['DAQ:SIM', '5', '0'], 'instances': [
        {'cls': 'PvDblArrayW', 'pv': dead, 'text': '0.000000', 'texts': [['pump:1', '0.000000']] * 3},
        {'cls': 'PvDblArrayW', 'pv': dead, 'text': '0.170000',
         'texts': [['shown', '-'], ['pump:1', '0.390000'], ['pump:1', '0.000000'], ['pump:1', '0.170000']]}]}
    path = tmp_path / 'deadca.walk.json'
    path.write_text(json.dumps(walk))
    e = gui_witness.entry('deadca', str(path), 0, 0, 1, params['part'], params)
    assert e['pass'] and e['stand_in'] == 'simxpm' and e['prefix'] == 'DAQ:SIM:XPM:0' and e['live'] == [dead], e
    walk['instances'].pop()
    path.write_text(json.dumps(walk))
    assert not gui_witness.entry('deadca', str(path), 0, 0, 1, params['part'], params)['pass']
    puts = []
    monkeypatch.setattr(daq_sim, 'pv_put', lambda name, value: puts.append((name, list(value))))
    monkeypatch.setattr(daq_sim, 'pv_get', lambda name: json.dumps({'fakecam_0': {'link': 2, 'group': 5, 'l1acc': 9}}))
    rec = daq_sim.link_full(W['link_full'], gui_witness.LINK_FULL)
    assert rec['link'] == 2 and rec['error'] is None and isinstance(rec['on'], float)
    assert puts == [('DAQ:SIM:XPM:0:SIM:LinkFull', [0., 0., gui_witness.LINK_FULL] + [0.] * (NUM_LINKS - 3))]
    monkeypatch.setattr(daq_sim, 'pv_get', lambda name: 'error: timeout')
    rec = daq_sim.link_full('fakecam_0', 0.3)
    assert rec['link'] is None and 'no link of fakecam_0' in rec['error'] and len(puts) == 1


def test_stand_in_interfaces_come_from_the_programs_own_source():
    """hsdpvs's names from its ChipServer, tprcas's from the table its main() builds, dticas's too."""
    from psdaq.sim import gui_witness
    dti = gui_witness.interface('dticas', ['-P', 'X:DTI'])
    assert 'X:DTI:3:UsLinkUp' in dti and all(n.startswith('X:DTI:') for n in dti) and len(dti) > 50
    hsd = gui_witness.interface('hsdpvs', ['-P', 'X:HSD:A', 'X:HSD:B'])
    assert 'X:HSD:A:MONTIMING' in hsd and 'X:HSD:B:CONFIG' in hsd and len(hsd) == 2 * len([n for n in hsd if n.startswith('X:HSD:A:')])
    tpr = gui_witness.interface('tprcas', ['-P', 'X:TPR'])
    assert 'X:TPR:EVTCNT' in tpr and 'X:TPR:CH0:DELAY' in tpr and all(n.startswith('X:TPR:') for n in tpr)


def test_hsd134pvs_interface_comes_from_its_cpp_sources():
    """hsd134PVs's names: read from the sources meson builds it from, for its 2 chips (PVCtrlsBase's 1-chip case,
    <P>:CONFIG and <P>:READY, is not taken), and simhsd on the chips' prefixes stands in under their parent."""
    from psdaq.sim import gui_witness
    names = gui_witness.hsd134pvs_names('P', repo=REPO)
    assert len(names) == 44 and len([n for n in names if n.startswith('P:A:')]) == 22
    assert {'P:A:MONTIMING', 'P:B:FEXOOR', 'P:A:PADDR_U', 'P:B:KEEPROWS', 'P:A:PGPCONFIG', 'P:B:READY'} <= set(names)
    assert 'P:CONFIG' not in names and 'P:READY' not in names
    assert gui_witness.interface('hsd134PVs', ['-P', 'P:A', 'P:B']) == names
    served = gui_witness.interface('hsdpvs', ['-P', 'P:A', 'P:B'])
    assert set(names) <= set(served)        # simhsd (hsdpvs's ChipServer per chip) serves every one


def test_tprioc_interface_comes_from_its_cpp_source():
    """tprioc's names (tprca.cc): TprControl's under the prefix, ChannelControl's under CH0..CH13 (NCHANNELS 14); simtpr
    serves every one: tprcas's table and the 10 names tprioc adds to it."""
    from psdaq.sim import gui_witness, simtpr
    names = gui_witness.tprioc_names('X:TPR', repo=REPO)
    assert {'X:TPR:EVTCNT', 'X:TPR:ACCSEL', 'X:TPR:TXCLKRATE', 'X:TPR:CH0:MODE', 'X:TPR:CH13:RATE', 'X:TPR:CH13:POL'} <= set(names)
    assert 'X:TPR:CH14:MODE' not in names and len([n for n in names if n.startswith('X:TPR:CH0:')]) == 16
    assert len(names) == 13 + 14 * 16
    assert gui_witness.interface('tprioc', ['-P', 'X:TPR']) == names
    tprcas = set(gui_witness.interface('tprcas', ['-P', 'X:TPR']))
    assert len(set(names) - tprcas) == 10 and set(names) - tprcas == {'X:TPR' + k for k in simtpr.tprioc_extra()}
    served = {'X:TPR' + k for k in dict(simtpr.tprcas_pvdb(), **simtpr.tprioc_extra())}
    assert set(names) <= served and tprcas <= served


def test_program_servers_interfaces_come_from_their_own_source():
    """bldcas's names from the table its main() builds (2 per service), hpsdbuscas's from its PVAServer."""
    from psdaq.sim import gui_witness
    assert gui_witness.interface('bldcas', ['-P', 'X', '-A', '239.254.32.1', 'HPSEX', 'HPSCPA']) == \
        ['X:HPSCPA:ADDR', 'X:HPSCPA:PORT', 'X:HPSEX:ADDR', 'X:HPSEX:PORT']
    assert gui_witness.interface('hpsdbuscas', ['-P', 'X:CP']) == \
        ['X:CP:HPS:FIELDMASK', 'X:CP:HPS:FIELDNAMES', 'X:CP:HPS:FIELDTYPES', 'X:CP:PAYLOAD']


def test_program_server_entry_puts_and_reads_back():
    """A program server's entry: its own interface, and the put PV read back after each put (2 numbers, the
    PAYLOAD type ID with them); one that ignores the puts, or does not serve a name, fails."""
    from psdaq.sim import gui_witness

    class Ctx:
        def __init__(self, missing=(), ignore=False):
            self.v, self.missing, self.ignore, self.puts = 0x8000, set(missing), ignore, []

        def get(self, names, timeout=None, throw=True):
            if isinstance(names, list):
                return [TimeoutError() if n in self.missing else 1 for n in names]
            if names.endswith('PAYLOAD'):
                class V:
                    def getID(s):
                        return str(self.v)
                return V()
            return self.v

        def put(self, name, value, timeout=None):
            self.puts.append((name, value))
            if not self.ignore:
                self.v = value
    params = {'pvbase': 'X'}
    args = ['-P', 'X:HPSCPA']
    names = gui_witness.interface('hpsdbuscas', args)
    ctx = Ctx()
    e = gui_witness.program_server_entry('hpsdbuscas', params, 0, 0.05, period=0.02, prepared=(args, {'hpsdbuscas': names}, ctx))
    assert e['pass'] and e['program'] is True and e['prefix'] == 'X:HPSCPA', e
    assert e['interfaces']['hpsdbuscas'] == {'defined': 4, 'served': 4, 'missing': []}
    assert ctx.puts == [('X:HPSCPA:HPS:FIELDMASK', 0x8001), ('X:HPSCPA:HPS:FIELDMASK', 0x8000)]
    assert e['reads'] == [{'name': 'X:HPSCPA:HPS:FIELDMASK', 'values': ['32768', '32769', '32768']}]
    assert e['live'] == ['X:HPSCPA:HPS:FIELDMASK'] and e['type_ids'][:2] == ['32768', '32769']
    e = gui_witness.program_server_entry('hpsdbuscas', params, 0, 0.05, period=0.02,
                                         prepared=(args, {'hpsdbuscas': names}, Ctx(ignore=True)))
    assert not e['pass'] and e['live'] == [] and 'did not read back 2 or more distinct numbers' in e['problems'][0]
    e = gui_witness.program_server_entry('hpsdbuscas', params, 0, 0.05, period=0.02,
                                         prepared=(args, {'hpsdbuscas': names}, Ctx(missing=['X:HPSCPA:PAYLOAD'])))
    assert not e['pass'] and e['interfaces']['hpsdbuscas']['missing'] == ['X:HPSCPA:PAYLOAD']


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
    defined = {'tprcas': names, 'tprioc': gui_witness.interface('tprioc', args)}
    e = gui_witness.server_entry('simtpr', params, 0, 0.05, period=0.02, prepared=(args, defined, Ctx()))
    assert e['pass'] and e['interfaces']['tprcas'] == {'defined': len(names), 'served': len(names), 'missing': []}
    assert e['interfaces']['tprioc'] == {'defined': 237, 'served': 237, 'missing': []}
    assert e['prefix'] == 'X:TPR' and e['live'] == ['X:TPR:EVTCNT']
    e = gui_witness.server_entry('simtpr', params, 0, 0.05, period=0.02,
                                 prepared=(args, defined, Ctx(missing=['X:TPR:CH3:RATE'])))
    assert not e['pass'] and e['interfaces']['tprcas']['missing'] == ['X:TPR:CH3:RATE']


def test_simslurm_shims_answer_from_the_state_file(tmp_path):
    """R5: daqstat's procmgr instance finds the Slurm commands first on its PATH in <workdir>/slurm/bin, each
    answered by simslurm from the state file, never by a Slurm controller."""
    import subprocess
    import sys
    from psdaq.sim import simslurm
    state = str(tmp_path / 'state.json')
    with simslurm.locked(state) as st:
        st['jobs'] = [{'job_id': 9100001, 'job_name': 'control', 'comment': 'x0_p5_s0_control', 'nodelist': 'localhost',
                       'state': 'RUNNING', 'since': 0, 'logfile': ''}]
    shims = simslurm.write_shims(str(tmp_path / 'bin'), state, sys.executable)
    assert sorted(os.path.basename(p) for p in shims) == sorted(simslurm.SHIMS)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
    r = subprocess.run([str(tmp_path / 'bin' / 'squeue'), '-u', 'x', '-h', '-o', '%k|%T'], capture_output=True,
                       text=True, env=env, timeout=60)
    assert r.returncode == 0 and r.stdout == 'x0_p5_s0_control|RUNNING\n', r
    assert gui_witness_squeue(state)['jobs'] == {'x0_p5_s0_control': 'RUNNING'}
    r = subprocess.run([str(tmp_path / 'bin' / 'srun')] if os.path.exists(tmp_path / 'bin' / 'srun') else
                       [sys.executable, '-m', 'psdaq.sim.simslurm', 'cmd', state, 'srun', 'x'], capture_output=True,
                       text=True, env=env, timeout=60)
    assert r.returncode == 127                       # anything but daqmgr's Slurm commands is refused


def gui_witness_squeue(state):
    from psdaq.sim import gui_witness
    return gui_witness.squeue_read(state, user='x')


def test_daqstat_witness_entry_matches_refreshes_to_squeue(tmp_path):
    """R5: the walk's recorded refreshes (first table: ID, Status) become the entry's 'refreshes', the cycle's squeue
    reads its 'squeue'; it passes with 2 refreshes that showed what squeue said."""
    from psdaq.sim import gui_witness
    params = daq_sim.gui_params(5, '/p', str(tmp_path / 'daq_sim.cnf'))
    assert gui_witness.argv('daqstat', params) == ['-i', '1', f'{tmp_path}/slurm/daqstat.py']
    E = gui_witness.EPICS_EPOCH
    cells = [['control', 'RUNNING'], ['teb0', 'RUNNING']]
    walk = {'argv': gui_witness.argv('daqstat', params), 'instances': [],
            'refreshes': [{'t': E + 10.0, 'tables': [cells]}, {'t': E + 11.0, 'tables': [cells]}]}
    path = tmp_path / 'daqstat.walk.json'
    path.write_text(json.dumps(walk))
    jobs = {'x0_p5_s0_control': 'RUNNING', 'x0_p5_s0_teb0': 'RUNNING'}
    slurm = {'prefix': 'x0_p5_s0', 'reads': [{'t': 10.2, 'jobs': jobs}, {'t': 11.2, 'jobs': jobs}]}
    e = gui_witness.entry('daqstat', str(path), 0, E + 9, E + 12, params['part'], params, slurm=slurm)
    assert e['pass'] and e['kind'] == 'slurm' and len(e['live']) == 2, e
    assert e['refreshes'][0] == {'t': 10.0, 'rows': cells}
    slurm['reads'] = [{'t': 10.2, 'jobs': dict(jobs, x0_p5_s0_teb0='PENDING')}, {'t': 11.2, 'jobs': jobs}]
    e = gui_witness.entry('daqstat', str(path), 0, E + 9, E + 12, params['part'], params, slurm=slurm)
    assert not e['pass'] and 'shows teb0 RUNNING, squeue said PENDING' in e['problems'][0]
    spec = gui_witness.spec('daqstat', params)['walk']
    assert spec['slurm_state'] == '{workdir}/slurm/state.json' and spec['refresh_calls']
    assert spec['bind_holders'] is True         # the witness walk names labels by their PV's holder; parity's does not


def test_daqmgr_config_of_the_daq_sim_cnf_loads_in_daqmgr(tmp_path, monkeypatch):
    """R5: up --gui writes daqmgr's config of daq_sim.cnf's processes (cnftopy breaks on its two-line entries), and
    daqmgr's Runner loads it: the job comments daqstat looks for are x0_p5_s0_<id>."""
    extra = daq_sim.extra_entries(str(tmp_path), 5, gui=True)
    cnf = write_cnf(str(tmp_path / 'daq_sim.cnf'), extra)
    ids = daq_sim.write_daqmgr_config(cnf, str(tmp_path / 'daqstat.py'), 5)
    assert ids[:3] == ['control', 'teb0', 'fakecam_0'] and 'daqstat' in ids and 'procstat' in ids
    monkeypatch.setenv('USER', 'x')
    from psdaq.slurm.main import Runner
    r = Runner(str(tmp_path / 'daqstat.py'), output=str(tmp_path / 'logs'))
    assert list(r.config) == ids and r.sbman.get_comment('control') == 'x0_p5_s0_control'


def test_tpr_entries_run_the_configs_tpr_programs_on_cards_of_their_own(tmp_path):
    """--tpr: tprtrig as srcf-rix.cnf starts it and tpr_trigger as rix.py's mono_enc_trig, each with PSDAQ_SIM_TPR on a
    card (a directory) of its own; their rows are enumerated from the tree's configs."""
    from psdaq.sim import gui_witness
    extra = daq_sim.extra_entries(str(tmp_path), 5, tpr=True)
    assert daq_sim.TPR_PROCS == tuple(T['id'] for T in gui_witness.TPR_PROGRAMS.values())
    assert f"id:'tprtrig', flags:'sp', env:'PSDAQ_SIM_TPR={tmp_path}/tpr/tprtrig'" in extra
    assert "cmd:'tprtrig -t a -c 0 -o 1 -d 2 -w 10 -z'" in extra
    assert f"id:'enc_trig', flags:'spu', env:'PSDAQ_SIM_TPR={tmp_path}/tpr/enc_trig'" in extra
    assert "cmd:'tpr_trigger -H tst -C localhost -t a -c 0 -o 1 -d 2 -w 10'" in extra
    assert gui_witness.tpr_card(str(tmp_path), 'tpr_trigger') == f'{tmp_path}/tpr/enc_trig/tpra'
    # lclsBldServer as lab3-bld.cnf:52 starts it, with -b and, on loopback, a group and port off the production network
    assert f"id:'lclsbldsvc', flags:'s', env:'PSDAQ_SIM_TPR={tmp_path}/tpr/lclsbldsvc'" in extra
    assert "cmd:'lclsBldServer -i lo -r 4 -b ebeam -a 239.254.33.0 -p 31245'" in extra
    assert gui_witness.tpr_card(str(tmp_path), 'lclsBldServer') == f'{tmp_path}/tpr/lclsbldsvc/tpra'
    assert daq_sim.ports(5)['lclsbld'] == 31245 and gui_witness.bld_group_ok(gui_witness.BLD_GROUP_BASE)
    assert not gui_witness.bld_group_ok('239.255.25.0') and not gui_witness.bld_group_ok('224.0.0.1')
    assert set(daq_sim.TPR_FRAME_PROCS) <= set(daq_sim.TPR_PROCS)
    assert set(daq_sim.TPR_PROCS) <= set(daq_sim.procs({'tpr': True}))
    assert not set(daq_sim.TPR_PROCS) & set(daq_sim.procs({}))
    assert "PSDAQ_SIM_TPR" not in daq_sim.extra_entries(str(tmp_path), 5, gui=True, pvservers=True)
    rows = coverage.config_rows(write_cnf(str(tmp_path / 'daq_sim.cnf'), extra))
    assert {'prog:tprtrig', 'prog:tpr_trigger', 'prog:lclsBldServer'} <= set(rows)
    enumerated, _ = coverage.enumerate_rows(REPO)
    assert {'prog:tprtrig', 'prog:tpr_trigger', 'prog:lclsBldServer'} <= set(enumerated)


def test_tprtrig_programs_a_simulated_card_as_its_argv_says(tmp_path):
    """tpr::Client with PSDAQ_SIM_TPR (psdaq/psdaq/tpr/Client.cc) maps a file for /dev/tpra; tprtrig programs it as it
    would a card, and gui_witness.tpr_registers reads back what coverage.tpr_expected says its argv programs.  Without
    PSDAQ_SIM_TPR it opens /dev/tpra, as before (none here)."""
    import shutil
    from psdaq.sim import gui_witness
    exe = shutil.which('tprtrig')
    if not exe:
        pytest.skip('tprtrig is not built')
    argv = ['-t', 'a', '-c', '0', '-o', '1', '-d', '2', '-w', '10', '-p', '5']
    env = dict(os.environ, PSDAQ_SIM_TPR=str(tmp_path))
    r = subprocess.run([exe] + argv, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert f'simulated TPR (PSDAQ_SIM_TPR): /dev/tpra is {tmp_path}/tpra\n' in r.stdout
    regs = gui_witness.tpr_registers(str(tmp_path / 'tpra'))
    chan, trigs = coverage.tpr_expected('tprtrig', argv)
    assert regs['channels'][0] == {'control': chan['control'], 'evtSel': chan['evtSel']}
    assert regs['triggers'][0] == {k: trigs[0][k] for k in ('control', 'delay', 'width', 'delayTap')}
    assert all(t['control'] == 0 for t in regs['triggers'][1:]) and len(trigs) == 1
    if not os.path.exists('/dev/tpra'):
        env.pop('PSDAQ_SIM_TPR')
        r = subprocess.run([exe] + argv, env=env, capture_output=True, text=True, timeout=60)
        assert r.returncode != 0 and 'Could not open tpr: No such file or directory' in r.stdout + r.stderr


def _free_udp_port():
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def test_lclsBldServer_sends_its_bld_for_the_frames_tprframes_delivers(tmp_path):
    """lclsBldServer on a simulated card (PSDAQ_SIM_TPR) whose channel-1 frames psdaq.sim.tprframes writes, as the
    driver would, at the fixed rate the channel selects: a receiver on its group (-a, -p: off the production network,
    on loopback) gets its packets, which coverage.bld_problem accepts (times, fixed rate 4's marker, simxpm's pulse
    IDs, the ebeam words, its pid); the queue file tpr::Client made is sizeof(Queues) as tprframes lays it out."""
    import shutil
    import time
    from psdaq.sim import gui_witness, tprframes
    exe = shutil.which('lclsBldServer')
    if not exe:
        pytest.skip('lclsBldServer is not built')
    port = _free_udp_port()
    argv = ['-i', 'lo', '-r', '4', '-b', 'ebeam', '-a', gui_witness.BLD_GROUP_BASE, '-p', str(port)]
    env = dict(os.environ, PSDAQ_SIM_TPR=str(tmp_path))
    card = str(tmp_path / 'tpra')
    feed = subprocess.Popen([sys.executable, '-m', 'psdaq.sim.tprframes', card, '--duration', '30'], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    srv = subprocess.Popen([exe] + argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.time() + 30     # F9: until its first packet, not a fixed 2 s (its start takes 2-5 s on a busy node)
        while not gui_witness.bld_receive(gui_witness.BLD_GROUP_BASE, port, 0.5)[2]:
            assert srv.poll() is None and time.time() < deadline, 'lclsBldServer sent no packet within 30 s'
        t0, t1, packets = gui_witness.bld_receive(gui_witness.BLD_GROUP_BASE, port, 3)
        _, t2, reads = gui_witness.tpr_reads(card, 1)
    finally:
        srv.kill()
        feed.terminate()
    out, log = srv.communicate(timeout=30)[0], feed.communicate(timeout=30)[0]
    assert os.path.getsize(card + '1') == tprframes.QUEUES_SIZE
    assert 'fixed rate 4 (102.0 Hz): frames to ' + card + '1' in log, log
    e = gui_witness.bld_entry('lclsBldServer', card, gui_witness.BLD_GROUP_BASE, port, t0, t1, reads, packets)
    assert e['pass'], e['problems']
    assert 200 <= len(e['packets']) <= 400, len(e['packets'])          # 3 s at 102 Hz
    text = (f'Tpr::Client: simulated TPR (PSDAQ_SIM_TPR): /dev/tpra is {card}\n'
            f'@@@ The PID of new child "lclsBldServer" is: {srv.pid}\r\n')
    logs = [(('lclsBldServer', argv), text)]
    lo, hi = e['start'] - 5, t2 - gui_witness.EPICS_EPOCH + 1     # the run: around the packets and the reads
    assert coverage.tpr_problem('lclsBldServer', e, logs, None, lo, hi) is None
    assert coverage.bld_problem('lclsBldServer', e, logs, lo, hi) is None
    assert 'pid' in coverage.bld_problem('lclsBldServer', e, [(('lclsBldServer', argv), text.replace(
        str(srv.pid), str(srv.pid + 1)))], lo, hi)


def test_lclsBldServer_refuses_a_bad_group_or_port_and_keeps_its_usage_otherwise():
    """-a and -p are new; without them lclsBldServer parses its command line as before (lab3-bld.cnf:52's line, with no
    -b, still ends in its usage, exit 1); a bad -a or -p is refused with the usage."""
    import shutil
    exe = shutil.which('lclsBldServer')
    if not exe:
        pytest.skip('lclsBldServer is not built')
    env = {k: v for k, v in os.environ.items() if k != 'PSDAQ_SIM_TPR'}
    for argv, why in ((['-i', 'lo', '-r', '4'], 'Usage:'), (['-i', 'lo', '-b', 'ebeam', '-a', 'x'], "option `-a' parsing error"),
                      (['-i', 'lo', '-b', 'ebeam', '-p', '70000'], "option `-p' parsing error")):
        r = subprocess.run([exe] + argv, env=env, capture_output=True, text=True, timeout=30)
        assert r.returncode == 1 and why in r.stdout, r.stdout
