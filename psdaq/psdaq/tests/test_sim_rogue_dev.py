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
