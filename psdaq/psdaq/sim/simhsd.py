"""simhsd: a software high-speed digitizer (HSD) PV server, so pvatable and the HSD GUIs run with no digitizer.

For each prefix it serves the PVs of psdaq/psdaq/cas/hsdpvs.py (the soft HSD PV host test-hsd.cnf starts beside
hsdpva and pvatable), built by hsdpvs.ChipServer itself, so the names, structures and initial values are hsdpvs's:
CONFIG, READY, PGPCONFIG, FWBUILD, FWVERSION, PADDR, PADDR_U, PLINK, KEEPROWS, FEXOOR, MONTIMING, MONTRIG, MONPGP,
MONRAWBUF, MONFEXBUF, MONRAWDET, MONFEXDET, MONFLOW, MONENV, MONADC, MONJESD, MONJESDTTL, RESET.  Unlike hsdpvs,
once a second MONTIMING counts a locked timing link and a 1 kHz trigger (timframecnt += 928571, trigcntsum += 1000,
trigcntrate = 1000), MONPGP counts frames on its 4 lanes (txcnt / rxcnt = 1000, txcntsum / rxcntsum += 1000), and
MONRAWBUF / MONFEXBUF report free buffers (freesz 2048 - n, freeevt 16 - n for a slowly varying n).  At start every
field of the other monitoring structures (MONTRIG, MONRAWDET, MONFEXDET, MONFLOW, MONENV, MONADC, MONJESD and the rest
of MONTIMING / MONPGP) gets its own value, pattern(chip, field, element), so a display of the wrong field or element
shows a wrong number (float32 fields get values float32 cannot hold exactly).
<prefix>:SIM:PID is this process's pid (simhsd only: a client can tell the simulator from an HSD).

The PVA server binds the loopback interface unless told otherwise (--bind, --allow-remote), like simxpm.

    python -m psdaq.sim.simhsd -P DAQ:SIM:HSD:1_DA:A DAQ:SIM:HSD:1_DA:B
"""

import argparse
import logging
import os
import threading
import time

from p4p.nt import NTScalar
from p4p.server import Server, StaticProvider
from p4p.server.thread import SharedPV

FRAMES_PER_S = 928571
TRIG_HZ = 1000


MON_PATTERNED = ('monTiming', 'monTrig', 'monPgp', 'monRawBuf', 'monFexBuf', 'monRawDet', 'monFexDet', 'monFlow',
                 'monEnv', 'monAdc', 'monJesd')


def pattern(chip, field, element, floating):
    """The start value of element `element` (0 for a scalar) of field number `field` of chip `chip`'s structures."""
    if floating:
        return (chip + 1) + field / 10. + element / 100. + 0.05
    return (chip + 1) * 1000 + field * 16 + element + 1


class SimHsd:
    def __init__(self, prefixes, start=True):
        from psdaq.cas.hsdpvs import ChipServer
        self.provider = StaticProvider('simhsd')
        self.chips = [ChipServer(self.provider, p, start) for p in prefixes]
        self.prefixes = list(prefixes)
        self.pids = []
        for p in prefixes:
            pv = SharedPV(initial=NTScalar('i').wrap(os.getpid()))
            self.provider.add(p + ':SIM:PID', pv)
            self.pids.append(pv)
        self.stop = threading.Event()

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
