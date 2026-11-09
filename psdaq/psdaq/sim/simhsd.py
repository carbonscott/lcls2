"""simhsd: a software high-speed digitizer (HSD) PV server, so pvatable and the HSD GUIs run with no digitizer.

For each prefix it serves the PVs of psdaq/psdaq/cas/hsdpvs.py (the soft HSD PV host test-hsd.cnf starts beside
hsdpva and pvatable), built by hsdpvs.ChipServer itself, so the names, structures and initial values are hsdpvs's:
CONFIG, READY, PGPCONFIG, FWBUILD, FWVERSION, PADDR, PADDR_U, PLINK, KEEPROWS, FEXOOR, MONTIMING, MONTRIG, MONPGP,
MONRAWBUF, MONFEXBUF, MONRAWDET, MONFEXDET, MONFLOW, MONENV, MONADC, MONJESD, MONJESDTTL, RESET.  Unlike hsdpvs,
once a second MONTIMING counts a locked timing link and a 1 kHz trigger (timframecnt += 928571, trigcntsum += 1000,
trigcntrate = 1000), MONPGP counts frames on its 4 lanes (txcnt / rxcnt = 1000, txcntsum / rxcntsum += 1000), and
MONRAWBUF / MONFEXBUF report free buffers (freesz 2048 - n, freeevt 16 - n for a slowly varying n), and MONTRIG counts
the triggers of cas/hsdPs.py's phase scan ('trigger at 70 kHz', 'MONTRIG counters are 20 bits'): once a second
ontime / early / late grow by montrig_split(phase) (70000 in all, split by the ADC/TIM clock phase, RESET.mmcmphase, a
fixed integer split per phase, so early / total is exact), phase is mmcmphase, and a put to RESET (hsdPs sets each
phase with one) starts the counts again from 0 and posts them at once.  A real HSD counts only while its readout
group's L0 is enabled; simhsd counts always.  At start every field of the other monitoring structures (MONRAWDET,
MONFEXDET, MONFLOW, MONENV, MONADC, MONJESD and the rest of MONTIMING / MONPGP / MONTRIG) gets its own value,
pattern(chip, field, element), so a display of the wrong field or element shows a wrong number (float32 fields get
values float32 cannot hold exactly).
<prefix>:SIM:PID is this process's pid (simhsd only: a client can tell the simulator from an HSD).

The PVA server binds the loopback interface unless told otherwise (--bind, --allow-remote), like simxpm.

    python -m psdaq.sim.simhsd -P DAQ:SIM:HSD:1_DA:A DAQ:SIM:HSD:1_DA:B
"""

import argparse
import logging
import math
import os
import threading
import time

from p4p.nt import NTScalar
from p4p.server import Server, StaticProvider
from p4p.server.thread import SharedPV

FRAMES_PER_S = 928571
TRIG_HZ = 1000
PS_TRIG_HZ = 70000                      # hsdPs: 'Setup is trigger at 70 kHz'
MONTRIG_MAX = (1 << 20) - 1             # hsdPs: 'MONTRIG counters are 20 bits'
PS_PHASES = 56                          # hsdPs --range default (0, 56, 8): mmcmphase 0..55


def montrig_split(phase):
    """(ontime, early, late) of one second of 70 kHz triggers at ADC/TIM clock phase `phase`: early and late come
    and go as the phase moves across a clock (integers, so their ratios are the same at every count)."""
    c = math.cos(2 * math.pi * (phase % PS_PHASES) / PS_PHASES)
    early = int(round(PS_TRIG_HZ * 0.45 * (1 + c) / 2))
    late = int(round(PS_TRIG_HZ * 0.45 * (1 - c) / 2))
    return PS_TRIG_HZ - early - late, early, late


MON_PATTERNED = ('monTiming', 'monTrig', 'monPgp', 'monRawBuf', 'monFexBuf', 'monRawDet', 'monFexDet', 'monFlow',
                 'monEnv', 'monAdc', 'monJesd')


def pattern(chip, field, element, floating):
    """The start value of element `element` (0 for a scalar) of field number `field` of chip `chip`'s structures."""
    if floating:
        return (chip + 1) + field / 10. + element / 100. + 0.05
    return (chip + 1) * 1000 + field * 16 + element + 1


def _chip_class():
    from psdaq.cas.hsdpvs import ChipServer

    class SimChip(ChipServer):
        """hsdpvs's ChipServer whose RESET put (hsdPs: one per phase) restarts the MONTRIG counts."""
        sim = None

        def updateDaqReset(self, value):
            if self.sim is not None:
                self.sim.reset_trig(self, value)
    return SimChip


class SimHsd:
    def __init__(self, prefixes, start=True):
        SimChip = _chip_class()
        self.provider = StaticProvider('simhsd')
        self.lock = threading.Lock()
        self.chips = []
        for p in prefixes:
            c = SimChip(self.provider, p, start)
            c.sim, c.trig, c.phase = self, [0, 0, 0], 0
            self.chips.append(c)
        self.prefixes = list(prefixes)
        self.pids = []
        for p in prefixes:
            pv = SharedPV(initial=NTScalar('i').wrap(os.getpid()))
            self.provider.add(p + ':SIM:PID', pv)
            self.pids.append(pv)
        self.stop = threading.Event()

    def post_trig(self, c):
        v = c.monTrig.current()
        v['ontime'], v['early'], v['late'] = c.trig
        v['phase'] = c.phase
        c.monTrig.post(v)

    def reset_trig(self, c, value):
        with self.lock:
            try:
                c.phase = int(value['mmcmphase'])
            except (KeyError, TypeError, ValueError):
                pass
            c.trig = [0, 0, 0]
            self.post_trig(c)

    def count_trig(self):
        with self.lock:
            for c in self.chips:
                c.trig = [min(MONTRIG_MAX, a + b) for a, b in zip(c.trig, montrig_split(c.phase))]
                self.post_trig(c)

    def seed(self):
        for ci, c in enumerate(self.chips):
            for attr in MON_PATTERNED:
                pv = getattr(c, attr)
                v = pv.current()
                for fi, (name, val) in enumerate(v.todict().items()):
                    floating = 'float' in str(getattr(val, 'dtype', type(val)))
                    if hasattr(val, '__len__'):
                        v[name] = [pattern(ci, fi, j, floating) for j in range(len(val))]
                    else:
                        v[name] = pattern(ci, fi, 0, floating)
                pv.post(v)

    def run(self):
        n = 0
        self.seed()
        for c in self.chips:
            for pv, val in ((c.ready, 1), (c.fwBuild, 'simhsd (psdaq/psdaq/sim/simhsd.py)')):
                v = pv.current()                       # post() takes only the exact type the PV was opened with
                v['value'] = val
                pv.post(v)
        while not self.stop.wait(1.0):
            n += 1
            for c in self.chips:
                v = c.monTiming.current()
                v['timframecnt'] = (n * FRAMES_PER_S) & 0x7fffffff
                v['trigcntsum'] = n * TRIG_HZ
                v['trigcntrate'] = TRIG_HZ
                v['hdrcount'] = n * TRIG_HZ
                c.monTiming.post(v)
                v = c.monPgp.current()
                v['loclinkrdy'] = v['remlinkrdy'] = [1] * 4
                v['txcnt'] = v['rxcnt'] = [TRIG_HZ] * 4
                v['txcntsum'] = v['rxcntsum'] = [n * TRIG_HZ] * 4
                c.monPgp.post(v)
                for b in (c.monRawBuf, c.monFexBuf):
                    v = b.current()
                    v['freesz'] = 2048 - (n % 8)
                    v['freeevt'] = 16 - (n % 4)
                    b.post(v)
            self.count_trig()


def main():
    ap = argparse.ArgumentParser(description='software HSD PV server (the PVs of cas/hsdpvs.py) for the HSD GUIs')
    ap.add_argument('-P', required=True, nargs='+', metavar='PREFIX', help='PV prefixes, as hsdpvs -P')
    ap.add_argument('--bind', default='127.0.0.1', help='PVA server interface (default %(default)s)')
    ap.add_argument('--allow-remote', action='store_true', help='allow a non-loopback --bind')
    ap.add_argument('-v', action='store_true')
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.v else logging.INFO, format='%(asctime)s simhsd %(levelname)s %(message)s')
    if a.bind not in ('127.0.0.1', 'localhost') and not a.allow_remote:
        raise SystemExit('simhsd: --bind %s is not loopback; use --allow-remote to mean it' % a.bind)
    conf = {'EPICS_PVAS_INTF_ADDR_LIST': a.bind, 'EPICS_PVAS_BEACON_ADDR_LIST': a.bind,
            'EPICS_PVAS_AUTO_BEACON_ADDR_LIST': 'NO'}
    for key in ('SERVER_PORT', 'BROADCAST_PORT'):
        v = os.environ.get('EPICS_PVAS_%s' % key, os.environ.get('EPICS_PVA_%s' % key))
        if v:
            conf['EPICS_PVAS_%s' % key] = v
    sim = SimHsd(a.P)
    with Server(providers=[sim.provider], conf=conf, useenv=False) as server:
        logging.info('serving HSD PVs under %s; server conf %s', a.P, server.conf())
        print('simhsd: ready, prefixes %s, pid %d' % (' '.join(a.P), os.getpid()), flush=True)
        try:
            sim.run()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
