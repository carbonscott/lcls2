"""Tests for psdaq.sim.rogue_dev: a pyrogue tree on the simulated transports.

A small firmware-like tree (one device on the PCIe map, one behind SRPv3 on a DMA lane) is
built after install(), as a BEB config script builds its roots; the tests check that seeds
are applied, that a seed path not in the tree fails loudly, that the fault hook makes the
register read back wrong and rogue's write-verify name it, and that hardware is refused.
"""

import json

import pytest

rogue = pytest.importorskip('rogue')
pr = pytest.importorskip('pyrogue')
import rogue.hardware.axi                                       # noqa: E402
import rogue.protocols.srp                                      # noqa: E402

from psdaq.sim import rogue_dev                                 # noqa: E402

DEV = 'sim://127.0.0.1:1'


class Regs(pr.Device):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.add(pr.RemoteVariable(name='Version', offset=0x0, bitSize=32, mode='RO'))
        self.add(pr.RemoteVariable(name='Ctrl', offset=0x4, bitSize=32, mode='RW'))
        self.add(pr.RemoteVariable(name='Lock', offset=0x8, bitOffset=3, bitSize=2, mode='RO'))


class Top(pr.Root):
    """A KCU-like map (AxiMemMap) and a front-end board behind SRPv3 on lane 0, VC 0."""
    def __init__(self, dev):
        super().__init__(name='Top', pollEn=False, initRead=True, timeout=2.0)
        self.mem = rogue.hardware.axi.AxiMemMap(dev)
        self.dma = rogue.hardware.axi.AxiStreamDma(dev, 0x0, True)
        self.srp = rogue.protocols.srp.SrpV3()
        pr.streamConnectBiDir(self.dma, self.srp)          # as epix100_config.py does
        self.add(Regs(name='Pcie', memBase=self.mem, offset=0x1000))
        self.add(Regs(name='Feb', memBase=self.srp, offset=0x2000))


@pytest.fixture(autouse=True)
def fresh():
    rogue_dev.uninstall()
    yield
    rogue_dev.uninstall()


def test_seeds_are_applied_on_both_transports():
    seeds = {'Top.Pcie.Version': 0x03040000, 'Top.Pcie.Lock': 3, 'Top.Feb.Version': 0xea020009}
    sim = rogue_dev.install(DEV, seeds=seeds, fault='')
    with Top(DEV) as top:
        assert top.Pcie.Version.get() == 0x03040000
        assert top.Pcie.Lock.get() == 3
        assert top.Feb.Version.get() == 0xea020009          # answered by the SRPv3 responder
        assert sim.pending() == []
        assert sorted(sim.applied) == sorted(seeds)
        mem = [s for s in sim.stores if s.name.startswith('AxiMemMap')][0]
        assert mem.raw_read(0x1008, 4) == (3 << 3).to_bytes(4, 'little')   # at its bits only
        top.Feb.Ctrl.set(0x5a)                              # registers keep what is written
        assert top.Feb.Ctrl.get(read=True) == 0x5a
    assert any('Top.Feb.Ctrl=0x5a' in w['regs'] for w in sim.writes)


def test_seed_file_for_a_type(tmp_path, monkeypatch):
    path = tmp_path / 'seeds.json'
    path.write_text(json.dumps({'_comment': 'ignored', 'Top.Pcie.Version': '0x0304'}))
    monkeypatch.setenv(rogue_dev.ENV_SEEDS, str(path))
    sim = rogue_dev.install(DEV, det_type='nosuchtype', fault='')
    assert sim.seeds == {'Top.Pcie.Version': 0x304}
    with Top(DEV) as top:
        assert top.Pcie.Version.get() == 0x304


@pytest.mark.parametrize('path,message', [
    ('Top.Pcie.NoSuchRegister', "seed path 'Top.Pcie.NoSuchRegister' is not in the Top tree"),
    ('Top.Pcie', "seed path 'Top.Pcie' is a Regs, not a register"),
])
def test_a_seed_path_not_in_the_tree_fails_loudly(path, message):
    rogue_dev.install(DEV, seeds={path: 1}, fault='')
    top = Top(DEV)
    try:
        with pytest.raises(rogue_dev.SimDeviceError) as e:
            top.start()
        assert message in str(e.value)
    finally:
        top.stop()


def test_a_seed_for_a_root_never_built_stays_pending():
    sim = rogue_dev.install(DEV, seeds={'Other.Dev.Reg': 1}, fault='')
    with Top(DEV):
        pass
    assert sim.pending() == ['Other.Dev.Reg']


@pytest.mark.parametrize('fault,reads', [('Top.Feb.Ctrl=0x7', 0x7), ('Top.Feb.Ctrl', 0xffffffff)])
def test_fault_hook_makes_write_verify_name_the_register(fault, reads, monkeypatch):
    monkeypatch.setenv(rogue_dev.ENV_FAULT, fault)
    sim = rogue_dev.install(DEV, seeds={})
    with Top(DEV) as top:
        assert sim.fault_applied[0] == 'Top.Feb.Ctrl' and sim.fault_applied[3] == reads
        with pytest.raises(Exception) as e:
            top.Feb.Ctrl.set(0x5a)
        print(e.value)
        assert 'Verify error' in str(e.value) and 'Top.Feb.Ctrl' in str(e.value)
        assert top.Feb.Ctrl.get(read=True) == reads
        top.Pcie.Ctrl.set(0x5a)                             # other registers are unaffected
        assert top.Pcie.Ctrl.get(read=True) == 0x5a


def test_a_fault_path_not_in_the_tree_fails_loudly():
    rogue_dev.install(DEV, seeds={}, fault='Top.Feb.Missing')
    top = Top(DEV)
    try:
        with pytest.raises(rogue_dev.SimDeviceError, match="fault path 'Top.Feb.Missing' is not in"):
            top.start()
    finally:
        top.stop()


def test_hardware_is_refused():
    with pytest.raises(rogue_dev.SimDeviceError, match='not a sim:// device'):
        rogue_dev.install('/dev/datadev_0')
    rogue_dev.install(DEV, seeds={}, fault='')
    with pytest.raises(rogue_dev.SimDeviceError, match='refusing to open hardware'):
        rogue.hardware.axi.AxiMemMap('/dev/datadev_0')
    with pytest.raises(rogue_dev.SimDeviceError, match='refusing to open hardware'):
        rogue.hardware.axi.AxiStreamDma('/dev/datadev_0', 0x100, True)


def test_uninstall_restores_rogue():
    real = rogue.hardware.axi.AxiMemMap
    rogue_dev.install(DEV, seeds={}, fault='')
    assert rogue.hardware.axi.AxiMemMap is not real
    rogue_dev.uninstall()
    assert rogue.hardware.axi.AxiMemMap is real


# --- the IOC's PVs and the driver's /proc text (wave8, wave8he, PgpMonitor) ---------------

def test_simulated_ioc_pvs(capsys):
    epics = pytest.importorskip('epics')
    real = epics.PV
    seeds = {'pv:{prefix}:Top:RxId': 1, 'pv:{prefix}:Top:Gain': 2.5}
    sim = rogue_dev.install(DEV, seeds=seeds, fault='', epics_prefix='SIM:W8:00')
    assert epics.PV is rogue_dev.SimPV
    assert epics.PV('SIM:W8:00:Top:RxId').get() == 1
    assert epics.PV('SIM:W8:00:Top:Gain').get() == 2.5            # JSON type kept
    assert epics.PV('SIM:W8:00:Top:RxId').put(7) == 1
    assert epics.PV('SIM:W8:00:Top:RxId').get() == 7
    assert epics.PV('SIM:W8:00:Top:Missing').get() is None         # as pyepics with no IOC
    assert epics.PV('SIM:W8:00:Top:Missing').put(1) is None
    assert sim.missing_pvs == ['SIM:W8:00:Top:Missing']
    assert 'serves no PV SIM:W8:00:Top:Missing' in capsys.readouterr().err
    assert {'store': 'pv', 'pv': 'SIM:W8:00:Top:RxId', 'value': 7, 'old': 1} in sim.writes
    assert sim.seeds == {}                                         # PVs are not register seeds
    rogue_dev.uninstall()
    assert epics.PV is real


def test_pv_fault_reads_back_wrong(capsys):
    epics = pytest.importorskip('epics')
    seeds = {'pv:{prefix}:Top:TriggerDelay': 42}
    rogue_dev.install(DEV, seeds=seeds, fault='pv:{prefix}:Top:TriggerDelay=0', epics_prefix='P')
    assert epics.PV('P:Top:TriggerDelay').get() == 0
    epics.PV('P:Top:TriggerDelay').put(42)
    assert epics.PV('P:Top:TriggerDelay').get() == 0
    assert 'FAULT PV P:Top:TriggerDelay reads back 0' in capsys.readouterr().err


def test_pv_fault_not_served_and_missing_prefix_fail_loudly():
    pytest.importorskip('epics')
    with pytest.raises(rogue_dev.SimDeviceError, match="fault PV 'P:Top:Nope' is not served"):
        rogue_dev.install(DEV, seeds={'pv:{prefix}:Top:A': 1}, fault='pv:{prefix}:Top:Nope=1',
                          epics_prefix='P')
    rogue_dev.uninstall()
    with pytest.raises(rogue_dev.SimDeviceError, match='need the drp.s -k epics_prefix'):
        rogue_dev.install(DEV, det_type='wave8', seeds={'pv:{prefix}:Top:A': 1}, fault='')


PROC_CHECK = """
from psdaq.sim import rogue_dev
rogue_dev.install('%s', seeds={}, fault='', proc='Build String : XilinxKcu1500Pgp4_6Gbps: x')
with open(rogue_dev.proc_path('%s')) as f:
    assert 'Pgp4' in f.read()
import psdaq.utils.enable_lcls2_pgp_pcie_apps     # sys.path for axipcie, as wave8_common does
from psdaq.cas.pgpmonitor import detect_version
print(detect_version('%s'))
with open(rogue_dev.__file__) as f:               # other files are untouched
    assert 'def install' in f.read()
""" % (DEV, DEV, DEV)


def test_proc_text_of_the_simulated_driver():
    """PgpMonitor's detect_version reads the simulated driver text.  In a subprocess: pytest-qt
    loads a Qt binding that pyrogue.pydm (imported by pgpmonitor) cannot use."""
    import subprocess
    import sys
    r = subprocess.run([sys.executable, '-c', PROC_CHECK], capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "('XilinxKcu1500', 4)" in r.stdout


def test_the_wave8_seed_file_loads():
    seeds, path, proc = rogue_dev.load_seeds('wave8', extra=True)
    assert path.endswith('seeds/wave8.json') and 'Pgp4' in proc
    pvs = [k for k in seeds if k.startswith('pv:')]
    assert len(pvs) > 100 and 'pv:{prefix}:Top:TriggerEventManager:XpmMessageAligner:RxId' in pvs
    assert 'pv:{prefix}:Top:TriggerEventManager:EvrV2CoreTriggers:EvrV2TriggerReg[0]:Delay' not in pvs


# --- free-running counters and the XpmDetector types' timing receiver (xpmdet_config) -----

class Clocked(pr.Root):
    def __init__(self, dev):
        super().__init__(name='Clk', pollEn=False, initRead=True, timeout=2.0)
        self.mem = rogue.hardware.axi.AxiMemMap(dev)
        self.add(pr.Device(name='Rx', memBase=self.mem, offset=0x0))
        self.Rx.add(pr.RemoteVariable(name='TxClkCount', offset=0x0, bitSize=32, mode='RO'))


def test_count_hz_seed_is_a_free_running_counter():
    import time
    sim = rogue_dev.install(DEV, seeds={'Clk.Rx.TxClkCount': {'count_hz': 1e6}}, fault='')
    with Clocked(DEV) as top:
        t0, c0 = time.monotonic(), top.Rx.TxClkCount.get(read=True)
        time.sleep(0.2)
        t1, c1 = time.monotonic(), top.Rx.TxClkCount.get(read=True)
        rate = (c1 - c0) / (t1 - t0)
        assert 0.9e6 < rate < 1.1e6, rate
        assert sim.applied['Clk.Rx.TxClkCount'][2] == {'count_hz': 1e6}


def test_a_dict_seed_other_than_count_hz_fails_loudly(tmp_path, monkeypatch):
    path = tmp_path / 'seeds.json'
    path.write_text(json.dumps({'Clk.Rx.TxClkCount': {'hz': 5}}))
    monkeypatch.setenv(rogue_dev.ENV_SEEDS, str(path))
    with pytest.raises(rogue_dev.SimDeviceError, match='count_hz'):
        rogue_dev.install(DEV, det_type='nosuchtype', fault='')


XPMDET_DRIVE = """
import json, os, socket, sys, traceback
from psdaq.sim import rogue_dev
dev = '%s'
fault = sys.argv[1] if len(sys.argv) > 1 else ''
sim = rogue_dev.install(dev, 'xpmdet', fault=fault)
import psdaq.configdb.xpmdet_config as x
def fail(*args):                                            # rogue threads outlive an exception
    traceback.print_exception(*args)
    sys.stderr.flush()
    os._exit(1)
sys.excepthook = fail
root = x.xpmdet_init(dev, 1, '186M', 0)                   # as XpmDetector's constructor
assert sim.pending() == [], sim.pending()
rate = root.PcieControl.DevPcie.TDetTiming.refClockRate()
alloc = {'body': {'drp': {'1': {'proc_info': {'host': socket.gethostname(), 'pid': os.getpid(),
                                              'device': dev}, 'active': True}}}}
info = x.xpmdet_connectionInfo(json.dumps(alloc))           # Alloc
x.xpmdet_connect(3, 64)                                     # Connect: group 3, 64 words
semi = root.PcieControl.DevPcie.TDetSemi
teb = root.PcieControl.DevPcie.TDetTiming.TriggerEventManager.TriggerEventBuffer[0]
print('RESULT', json.dumps({'rate': rate, 'paddr': info['paddr'], 'length': semi.Length_0.get(),
                            'enable': semi.Enable_0.get(), 'partition': teb.Partition.get(),
                            'master': teb.MasterEnable.get(), 'writes': len(sim.writes)}))
x.xpmdet_unconfig()
x.xpmdet_connectionShutdown()
sys.stdout.flush()
os._exit(0)
""" % DEV


def _drive_xpmdet(*args):
    """xpmdet_config's entry points in XpmDetector.cc's order, in a subprocess (its root keeps
    rogue threads alive)."""
    import subprocess
    import sys
    return subprocess.run([sys.executable, '-c', XPMDET_DRIVE] + list(args), capture_output=True,
                          text=True, timeout=120)


def test_xpmdet_config_runs_against_the_emulated_timing_receiver():
    r = _drive_xpmdet()
    if 'SUBMODULEDIR' in r.stderr and r.returncode:
        pytest.skip('needs $SUBMODULEDIR (the DAQ env)')
    assert r.returncode == 0, r.stderr[-3000:]
    res = json.loads(r.stdout.split('RESULT ', 1)[1].splitlines()[0])
    assert 180. < res['rate'] < 190.                        # the count_hz seed: 185.7 MHz
    assert res['paddr'] == 0xff000000                       # the seeded RxId
    assert (res['length'], res['enable'], res['partition'], res['master']) == (64, 1, 3, 1)
    assert res['writes'] > 30


def test_xpmdet_fault_makes_connect_name_the_register():
    r = _drive_xpmdet('DrpTDet.PcieControl.DevPcie.TDetSemi.Length_0')
    if 'SUBMODULEDIR' in r.stderr and r.returncode:
        pytest.skip('needs $SUBMODULEDIR (the DAQ env)')
    assert r.returncode != 0
    assert 'Verify error' in r.stderr and 'TDetSemi' in r.stderr, r.stderr[-3000:]


# --- camera link cameras: a seed may enable a device, name a string register or a root
# whose name starts with '_'; the camera's serial port answers from the seed file ----------

class Linked(pr.Root):
    """A KCU map with a link-ready bit and a front-end board enabled by it (enableDeps), as
    cameralink_gateway.ClinkDevRoot enables its FEB on the PGP link."""
    def __init__(self, dev):
        super().__init__(name='Lnk', pollEn=False, initRead=True, timeout=2.0)
        self.mem = rogue.hardware.axi.AxiMemMap(dev)
        self.dma = rogue.hardware.axi.AxiStreamDma(dev, 0x0, True)
        self.srp = rogue.protocols.srp.SrpV3()
        pr.streamConnectBiDir(self.dma, self.srp)
        self.add(Regs(name='Pcie', memBase=self.mem, offset=0x1000))
        self.Pcie.add(pr.RemoteVariable(name='LinkReady', offset=0xc, bitSize=1, mode='RO'))
        self.add(Regs(name='Feb', memBase=self.srp, offset=0x2000,
                      enableDeps=[self.Pcie.LinkReady]))


def test_a_seed_on_a_device_its_link_seed_enables():
    seeds = {'Lnk.Pcie.LinkReady': 1, 'Lnk.Feb.Version': 0x08020000}
    sim = rogue_dev.install(DEV, seeds=seeds, fault='')
    with Linked(DEV) as top:
        assert top.Feb.Version.get(read=True) == 0x08020000
        assert sim.pending() == []


def test_string_seeds_and_underscore_roots(tmp_path, monkeypatch):
    path = tmp_path / 'seeds.json'
    path.write_text(json.dumps({'_comment': 'ignored', '_Top.Pcie.Version': {'string': 'AB'},
                                'Top.Pcie.Ctrl': {'string': 'Lcls'}}))
    monkeypatch.setenv(rogue_dev.ENV_SEEDS, str(path))
    seeds, _ = rogue_dev.load_seeds('nosuchtype')
    assert seeds == {'_Top.Pcie.Version': 0x4241, 'Top.Pcie.Ctrl': int.from_bytes(b'Lcls', 'little')}


class Serial(pr.Root):
    """A camera's serial port on lane 0 VC2, as surf's ClinkSerialTx/Rx use it."""
    def __init__(self, dev):
        super().__init__(name='Ser', pollEn=False, initRead=False, timeout=2.0)
        self.dma = rogue.hardware.axi.AxiStreamDma(dev, 0x2, True)


class Collect(rogue.interfaces.stream.Slave):
    def __init__(self):
        super().__init__()
        self.got = bytearray()

    def _acceptFrame(self, frame):
        ba = bytearray(frame.getPayload())
        frame.read(ba, 0)
        self.got += ba


def test_the_camera_uart_answers_from_the_seed_file(tmp_path, monkeypatch):
    import time
    import rogue.interfaces.stream
    path = tmp_path / 'seeds.json'
    path.write_text(json.dumps({'_uart': {'dests': ['0x2'], 'replies': {'@ID?': 'OPAL-1000m\r\x06'},
                                          'default': '\x06'}}))
    monkeypatch.setenv(rogue_dev.ENV_SEEDS, str(path))
    sim = rogue_dev.install(DEV, det_type='nosuchtype', fault='')
    with Serial(DEV) as top:
        rx, tx = Collect(), rogue.interfaces.stream.Master()
        pr.streamConnect(top.dma, rx)
        pr.streamConnect(tx, top.dma)
        for cmd in ('@ID?', '@MO1'):
            ba = rogue_dev.SimUart.words(cmd + '\r')
            frame = tx._reqFrame(len(ba), True)
            frame.write(ba, 0)
            tx._sendFrame(frame)
        want = b'OPAL-1000m\r\x06' + b'\x06'               # the two replies, one character per word
        t0 = time.monotonic()
        while len(rx.got) < 4 * len(want) and time.monotonic() - t0 < 5:
            time.sleep(0.01)
        assert bytes(rx.got[0::4]) == want
        assert [w['cmd'] for w in sim.writes if w['store'] == 'uart'] == ['@ID?', '@MO1']
