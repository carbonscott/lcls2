"""Tests for the simulated DMA buffer size of MemPoolSim (psdaq/drp/MemPoolSim.cc), issue #76.

The DRP's pebble buffer, where an L1Accept is built with its datagram and XTC headers, is sized
from the DMA size (DrpBase.cc: lanes x dmaSize). With the 64 KiB default and `daq_sim up --length
16384`, MemPoolSim clamped the payload to 16375 words, which fills the DMA buffer exactly; the
event plus its headers then overflowed the pebble buffer and the DRP aborted at the first L1Accept
(Xtc.hh: 'Insufficient space for 65504 bytes'). `drp_sim_frame --dma-size <sim_length>
[<sim_dma_size>]` prints the DMA size MemPoolSim takes for these kwargs and the sim_length its
connect() keeps.
"""

import shutil
import subprocess

import pytest

EXE = shutil.which('drp_sim_frame')
pytestmark = pytest.mark.skipif(EXE is None, reason='drp_sim_frame is not built (build_all.sh -d)')

DEFAULT = 0x10000           # MemPoolSim's DefDmaSize
TIMING_HEADER = 32
# What an L1Accept took in the pebble buffer beyond its payload in the issue's abort: the buffer
# had 65406 of its 65536 B left when Xtc::alloc asked for the payload (end - buffer = 0xff7e)
ISSUE_OVERHEAD = 65536 - 0xff7e


def dma(length, dma_size=None):
    args = [EXE, '--dma-size', str(length)] + ([hex(dma_size)] if dma_size is not None else [])
    out = subprocess.run(args, capture_output=True, text=True, check=True, timeout=60).stdout.split()
    assert out[0::2] == ['dma_size', 'sim_length', 'headroom'], out
    size, kept, headroom = (int(v) for v in out[1::2])
    return size, kept, headroom


def test_headroom_covers_the_events_headers():
    _, _, headroom = dma(0)
    assert headroom >= 4 * ISSUE_OVERHEAD


@pytest.mark.parametrize('length', [0, 64, 1024, 15000])
def test_small_payloads_keep_the_64k_default(length):
    assert dma(length)[:2] == (DEFAULT, length)


@pytest.mark.parametrize('length', [16000, 16300, 16375, 16384, 32768, 100000, 1 << 20])
def test_default_dma_size_holds_the_payload_and_its_headers(length):
    """The issue's case (16384 words) and its neighbours: no clamp, and the event fits."""
    size, kept, headroom = dma(length)
    assert kept == length
    assert size >= 4 * length + headroom
    assert size >= DEFAULT and size & (size - 1) == 0          # a power of two
    assert size < 2 * (4 * length + headroom) or size == DEFAULT  # the smallest such


def test_explicit_dma_size_is_kept_and_the_clamp_leaves_room():
    """An explicit sim_dma_size too small for sim_length still clamps, but to a payload whose
    event fits the pebble buffer, not to one that fills the DMA buffer (16375 words before)."""
    size, kept, headroom = dma(16384, DEFAULT)
    assert size == DEFAULT
    assert kept < 16384
    assert 4 * kept + headroom <= DEFAULT
    assert 4 * kept + ISSUE_OVERHEAD < DEFAULT


@pytest.mark.parametrize('dma_size', [0x2000, 0x110000, 0x201000])
def test_explicit_dma_size_wins_over_the_payload(dma_size):
    """The types daq_sim gives a sim_dma_size (opal, epix100, ...) keep exactly that size."""
    assert dma(0, dma_size)[0] == dma_size
    assert dma(64, dma_size)[0] == dma_size


def test_the_clamped_frame_fits_its_dma_buffer():
    """The DMA buffer MemPoolSim fills for the clamped payload leaves its sentinel word alone."""
    size, kept, _ = dma(16384, DEFAULT)
    buf = subprocess.run([EXE, 'fakecam', '1', '0x1234', str(kept)], capture_output=True,
                         check=True, timeout=60).stdout
    assert len(buf) == TIMING_HEADER + 4 * kept
    assert len(buf) + 4 <= size


@pytest.mark.parametrize('length', [64, 16384])
def test_drp_gpu_types_dma_fits_their_dma_buffers(length):
    """drp_gpu -d sim:// copies each MemPoolSim buffer, after the 32 B DMA frame, into a GPU DMA
    buffer of dmaBufSize (drpGpu/MemPool.cc aborts at start otherwise): a default that grows
    with --length must not outgrow it, so the types with a fixed dmaBufSize pin sim_dma_size."""
    from psdaq.sim import daq_sim
    P = daq_sim.ports(5)
    for name, t in daq_sim.GPU_SIM_TYPES.items():
        kw = dict(x.split('=', 1) for x in
                  t['kwargs'].format(length=length, seed=0, work='', **P).split(','))
        if 'dmaBufSize' not in kw:
            continue
        size, _, _ = dma(int(kw.get('sim_length', '0'), 0), int(kw.get('sim_dma_size', '0'), 0))
        assert size + 32 <= int(kw['dmaBufSize'], 0), (name, size, kw['dmaBufSize'])
