"""psdaq.sim.pattern -- the simulated BEB detector data, as psdaq/drp/MemPoolSim.cc makes it.

Pixel i of the image a BEB type's DRP builds (psana2's det.raw.raw array, flattened in C order)
holds, in the event with sequence number seq (1, 2, ... per L1Accept since the run's
GroupL0Reset) and the sim_seed of the run:

    pattern(seed, seq, i, bits) = (mix(i) + seq * 0x9e37 + seed) mod 2**32, masked to bits

mix() is a 32-bit integer hash of the position, so a pixel in the wrong place, a row in the
wrong order or an image shifted by one pixel reads a different value; seq makes every event
different.  MemPoolSim::mix and MemPoolSim::pattern are the same functions in C++.
"""

import numpy as np

MIX_A, MIX_B, SEQ_K = 0x9e3779b1, 0x85ebca6b, 0x9e37


def mix(index):
    """The position hash, for an int or an array of indices (as uint32)."""
    h = np.asarray(index, dtype=np.uint64).astype(np.uint32)
    with np.errstate(over='ignore'):
        h = h * np.uint32(MIX_A)
        h ^= h >> np.uint32(16)
        h = h * np.uint32(MIX_B)
        h ^= h >> np.uint32(13)
    return h


def pattern(seed, seq, index, bits):
    """The value of pixel `index` (int or array) in event `seq`."""
    add = np.uint32((seq * SEQ_K + seed) & 0xffffffff)
    with np.errstate(over='ignore'):
        v = mix(index) + add
    return v if bits >= 32 else v & np.uint32((1 << bits) - 1)


def image(seed, seq, shape, bits, offset=0):
    """The whole image of event `seq`, shape `shape`; `offset` shifts the expected pixel
    indices (a deliberately wrong expectation, to show the check can fail)."""
    n = int(np.prod(shape))
    return pattern(seed, seq, np.arange(offset, offset + n, dtype=np.uint64), bits).reshape(shape)
