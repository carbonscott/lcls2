"""Tests for the GPU DRP's hardware-free path: drp_gpu -d sim:// (psdaq/drpGpu/MemPool.cc),
daq_sim up --drp drp_gpu, and xtc2_check --drp drp_gpu.

No GPU is needed: they check the pieces that decide what a run records and proves -- the
expected TDet words and calibrations xtc2_check compares the recorded pixels with, the file
EpixUHRsim writes for it, the types daq_sim accepts for each DRP, and the coverage rows a
drp_gpu .cnf proves (never a drp row, and no drp_gpu row from a drp .cnf).
"""

import struct

import numpy as np
import pytest

from psdaq.sim import coverage, daq_sim, xtc2_check

from test_sim_coverage import write_daq_sim_cnf

PID = 0x123456789ab
SEED = 0x1234


def test_gpu_words_are_memposim_fills_tdet_words():
    """MemPoolSim::fill's payload for lane 0 (MemPoolSim.hh), read back as uint16 pixels:
    w0, w1 = the pulseId, w2 = seq, w3 = seed, w[k] = seed + w0 + k."""
    u = xtc2_check._gpu_words(PID, 7, SEED, 16)
    assert u.dtype == np.uint16 and u.size == 32
    w = u.view(np.uint32)
    assert list(w[:4]) == [PID & 0xffffffff, PID >> 32, 7, SEED]
    assert list(w[4:]) == [(SEED + (PID & 0xffffffff) + k) & 0xffffffff for k in range(4, 16)]
    # The self-test offset shifts the pattern words only
    o = xtc2_check._gpu_words(PID, 7, SEED, 16, offset=1).view(np.uint32)
    assert list(o[:4]) == list(w[:4]) and list(o[4:]) == [int(v) + 1 for v in w[4:]]


def test_gpu_calibrations_are_the_types_own():
    """epixuhremu: gain in bit 0, 11 bits of value from bit 1 (EpixUHRemu.hh); fakecam: the
    low 14 bits (AreaDetector.hh); both with pedestals 0 and gains 1."""
    u = np.array([0x0000, 0x0001, 0x0002, 0x0fff, 0x1000, 0xffff], dtype=np.uint16)
    uhr = xtc2_check.GPU_TYPES['epixuhremu'][1](u)
    assert uhr.dtype == np.float32 and list(uhr) == [0, 0, 1, 0x7ff, 0, 0x7ff]
    cam = xtc2_check.GPU_TYPES['fakecam'][1](u)
    assert list(cam) == [0, 1, 2, 0xfff, 0x1000, 0x3fff]
    assert xtc2_check.GPU_TYPES['epixuhremu'][0] == (336, 576)
    assert xtc2_check.GPU_TYPES['epixuhrsim'][1] is None      # checked from its own file
    shape, bits, jf = xtc2_check.GPU_FRAME_TYPES['jungfrau']  # its module's frames (simsls)
    assert (shape, bits) == ((512, 1024), 16)
    assert jf(u).dtype == np.float32 and list(jf(u)) == [0, 1, 2, 0xfff, 0x1000, 0x3fff]


def test_jungfrau_drp_gpu_kwargs_point_at_simsls():
    """drp_gpu -D jungfrau gets the drp's module kwargs (Drp::Jungfrau) and a DMA buffer that
    holds the module's frame as MemPoolSim batches it plus the 32 B DMA frame."""
    P = daq_sim.ports(5)
    t = daq_sim.GPU_SIM_TYPES['jungfrau']
    kw = dict(x.split('=', 1) for x in t['kwargs'].format(length=0, seed=0, work='', **P).split(','))
    assert kw['slsHosts'] == '127.0.0.1:%d' % P['sls'] and kw['sim_udp_port'] == str(P['sls_data'])
    frame = 8 + 40 + 40 + (8 + 128 * (48 + 8192 + 8)) + 8         # MemPoolSim's jungfrau buffer
    assert frame + 4 <= int(kw['sim_dma_size'], 0) and int(kw['sim_dma_size'], 0) + 32 <= int(kw['dmaBufSize'])
    assert t['sls'] and t['sets'] == daq_sim.SIM_TYPES['jungfrau']['sets']


def test_sim_ref_file_reads_back(tmp_path):
    """The layout EpixUHRsim::beginrun writes with sim_ref (EpixUHRsim.cu _writeSimRef)."""
    n, npix, nranges = 3, 5, 2
    raw = np.arange(n * npix, dtype=np.uint16).reshape(n, npix)
    peds = np.linspace(0, 1, nranges * npix, dtype=np.float32).reshape(nranges, npix)
    gains = np.linspace(1, 2, nranges * npix, dtype=np.float32).reshape(nranges, npix)
    path = tmp_path / 'ref.bin'
    with open(path, 'wb') as f:
        f.write(b'EUHRSIM1' + struct.pack('<4I', n, npix, nranges, 0))
        f.write(raw.tobytes() + peds.tobytes() + gains.tobytes())
    r, p, g = xtc2_check.read_sim_ref(str(path))
    assert (r == raw).all() and (p == peds).all() and (g == gains).all()
    (tmp_path / 'bad.bin').write_bytes(b'NOTAREF0' + bytes(16))
    with pytest.raises(ValueError):
        xtc2_check.read_sim_ref(str(tmp_path / 'bad.bin'))


def test_daq_sim_types_per_drp(monkeypatch):
    """--drp drp_gpu takes the GPU_SIM_TYPES and nothing else; drp keeps SIM_TYPES."""
    monkeypatch.setattr(daq_sim, 'DETECTOR', daq_sim.DETECTOR)
    monkeypatch.setattr(daq_sim, 'DRP', daq_sim.DRP)
    monkeypatch.setattr(daq_sim, 'PROCS', daq_sim.PROCS)
    for det in daq_sim.GPU_SIM_TYPES:
        daq_sim.use_det(det, 'drp_gpu')
        assert (daq_sim.DETECTOR, daq_sim.DRP, daq_sim.PROCS[-1]) == (det, 'drp_gpu', det + '_0')
        assert 'reducer=NoOpReducer' in daq_sim.GPU_SIM_TYPES[det]['kwargs']
    with pytest.raises(daq_sim.Fail):
        daq_sim.use_det('wave8', 'drp_gpu')
    with pytest.raises(daq_sim.Fail):
        daq_sim.use_det('epixuhremu', 'drp')
    daq_sim.use_det('fakecam')
    assert daq_sim.DRP == 'drp'


@pytest.mark.parametrize('det', ['fakecam', 'epixuhremu', 'epixuhrsim'])
def test_config_rows_of_a_drp_gpu_cnf(tmp_path, det):
    """A drp_gpu .cnf proves drp_gpu's rows and no drp row; a drp .cnf of the same type no
    drp_gpu row.  The CUDA runtime's directory reaches drp_gpu as its procmgr 'env'."""
    cnf = write_daq_sim_cnf(str(tmp_path / 'gpu.cnf'), det, 'drp_gpu',
                            env=" env:'LD_LIBRARY_PATH=/opt/cuda/lib',")
    text = open(cnf).read()
    assert f"cmd:'drp_gpu -P tst -C localhost -D {det} -d sim://127.0.0.1:3" in text
    assert "env:'LD_LIBRARY_PATH=/opt/cuda/lib'" in text
    assert sorted(coverage.config_rows(cnf)) == [f'det:drp_gpu:{det}', 'prog:control',
                                                 'prog:drp_gpu', 'prog:teb']
    cnf = write_daq_sim_cnf(str(tmp_path / 'cpu.cnf'), 'fakecam')
    assert not [r for r in coverage.config_rows(cnf) if 'drp_gpu' in r]
