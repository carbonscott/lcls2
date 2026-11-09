"""epixhremu_frame: write the xtc2 file whose frame drp -D epixhremu replays.

    python -m psdaq.sim.epixhremu_frame <out.xtc2> [--seed 0x1234]

EpixHRemu (psdaq/drp/EpixHRemu.cc) is an emulator: it ignores the DMA payload and, in every
L1Accept, records a frame it read at startup from the file named by its 'xtcfile' kwarg (the
first L1Accept's 'raw' uint16 rank-2 array, after 'l1aOffset' of them).  'daq_sim up --det
epixhremu' writes that file with this module, so the replayed frame is known: a Configure that
names an epixhr2x2 detector, a BeginRun (so psana2 can read the file), then one L1Accept whose raw array, shape FRAME_SHAPE (2 x 2 ASICs
of 144 x 192), holds pixel i = psdaq.sim.pattern.pattern(seed, 0, i, 16).

What EpixHRemu records from it, per event, is expected(): image row r, ASIC a, column c holds
frame pixel r * 384 + c (it copies the first 192 values of each of the first 144 frame rows into
all 4 ASIC positions; EpixHRemu::event).
"""

import argparse
import sys

import numpy as np

ROWS, COLS, ASICS = 144, 192, 4         # EpixHRemu.hh elemRows, elemRowSize, numAsics
FRAME_SHAPE = (2 * ROWS, 2 * COLS)      # numElems = 4 * 144 * 192 values


def frame(seed):
    from psdaq.sim import pattern
    n = FRAME_SHAPE[0] * FRAME_SHAPE[1]
    return pattern.pattern(seed, 0, np.arange(n, dtype=np.uint64), 16).astype(np.uint16) \
        .reshape(FRAME_SHAPE)


def expected(seed, nlanes=1, offset=0):
    """The raw array EpixHRemu records in every event, shape (144, nlanes * 4 * 192);
    offset shifts the frame indices (a deliberately wrong expectation)."""
    from psdaq.sim import pattern
    r = np.arange(ROWS)[:, None]
    c = np.arange(COLS)[None, :]
    rows = pattern.pattern(seed, 0, (r * 2 * COLS + c + offset).astype(np.uint64), 16)
    return np.tile(rows.astype(np.uint16), (1, nlanes * ASICS))


def write(path, seed):
    """Write the Configure and the one L1Accept to path (psana.dgramedit)."""
    from psana.dgramedit import AlgDef, DetectorDef, DgramEdit
    from psana.psexp import TransitionId
    bufsize = 16 * 1024 * 1024
    out = bytearray(bufsize)
    config = DgramEdit(transition_id=TransitionId.Configure, ts=0, bufsize=bufsize)
    det = config.Detector(DetectorDef('epixhr', 'epixhr2x2', 'sim-epixhremu-frame'),
                          AlgDef('raw', 2, 0, 0), {'raw': (np.uint16, 2)})
    with open(path, 'wb') as f:
        config.save(out)
        f.write(out[:config.size])
        begin = DgramEdit(transition_id=TransitionId.BeginRun, config_dgramedit=config, ts=1,
                          bufsize=bufsize)              # so psana2 can open the file as a run
        begin.save(out)
        f.write(out[:begin.size])
        l1 = DgramEdit(transition_id=TransitionId.L1Accept, config_dgramedit=config, ts=2,
                       bufsize=bufsize)
        det.raw.raw = frame(seed)
        l1.adddata(det.raw)
        l1.save(out)
        f.write(out[:l1.size])
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('out')
    ap.add_argument('--seed', type=lambda s: int(s, 0), default=0x1234)
    args = ap.parse_args()
    write(args.out, args.seed)
    print(f'epixhremu frame {FRAME_SHAPE} from seed {args.seed:#x} written to {args.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
