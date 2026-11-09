"""simhsdioc: the PVs and the IOC of a simulated high-speed digitizer (hsd), for 'drp -D hsd -d sim://'.

On hardware an hsd channel's PVs are hosted by hsdpvs (psdaq/psdaq/cas/hsdpvs.py, which the hsd .cnf
files start for each channel A and B), and hsd134PVs, the IOC on the digitizer's host, programs the
digitizer from them and publishes its monitoring.  The DRP's own config code (psdaq/configdb/
hsd_config.py) talks to both over PV Access only: it disables both channels at start, checks at
Connect that the IOC is alive (FEXOOR's time stamp), reads PADDR_U and checks that MONPGP's remote
link id is the one its card sends, and at Configure clears READY, puts CONFIG, waits for READY, for
MONTIMING's readout group and its L0 delay and for MONRAWBUF's free buffers, reads KEEPROWS, pulses
RESET.jesdclear and reads FWVERSION and FWBUILD.

This process is both for each prefix: the PVs are built by hsdpvs.ChipServer itself (hsdpvs's
names, structures and initial values), and it does what hsd134PVs does with them as far as
hsd_config reads it back:

  CONFIG put       READY = 1 (the IOC applied it); with enable = 1, MONTIMING.group = readoutGroup
                   and MONTIMING.l0delay = --l0delay (the readout group's L0Delay + 1, which the
                   real hsd takes from the timing stream)
  every second     FEXOOR is posted with the time (hsd_connect: 'hsdioc process may be dead' when
                   it is more than 100 s old), MONTIMING counts frames and triggers
  at start         PADDR_U, FWVERSION, FWBUILD, MONRAWBUF/MONFEXBUF free buffers, MONPGP link
                   ready and remlinkid: the link id the DRP's card sends on each PGP lane
                   (hsd_connect writes 0xfb000000 | ip[2] << 8 | ip[3] | lane << 16, ip being this
                   host's address, into TxLinkId[lane] and compares the hsd's report with it;
                   --linkid sets another)

It programs no samples: the data a sim:// DRP records is MemPoolSim's (psdaq/drp/MemPoolSim.cc,
the hsd framer).  The PVA server binds the loopback interface unless told otherwise (--bind,
--allow-remote), like simxpm, on the ports of the environment (psdaq/psdaq/sim/sim_env.sh).

    python -m psdaq.sim.simhsdioc -P DAQ:SIM:HSD:1_SIM:A DAQ:SIM:HSD:1_SIM:B
"""

import argparse
import logging
import os
import socket
import sys
import threading
import time

from p4p.server import Server, StaticProvider

log = logging.getLogger('simhsdioc')

FRAMES_PER_S = 928571                   # 929 kHz timing frames, as MONTIMING.timframecnt counts
FW_VERSION = 0x05000000
FW_BUILD = 'simhsdioc (psdaq/psdaq/sim/simhsdioc.py)'


def card_link_id(host=None, core=True):
    """The link id hsd_connect writes into the card's TxLinkId[0] on this host."""
    ip = socket.gethostbyname(host or socket.gethostname()).split('.')
    lid = 0xfb000000 | (int(ip[2]) << 8) | int(ip[3])
    return lid if core else lid | 0x40000


def _int32(v):
    v &= 0xffffffff
    return v - (1 << 32) if v & 0x80000000 else v


def _set(pv, **fields):
    """Post pv with fields changed (SharedPV.post takes only the type the PV was opened with)."""
    v = pv.current()
    for k, x in fields.items():
        v[k] = x
    pv.post(v)


class SimHsdIoc(object):
    def __init__(self, prefixes, l0delay=81, linkid=None, paddr=0xff000000, freesz=2048):
        from psdaq.cas.hsdpvs import ChipServer
        ioc = self

        class Chip(ChipServer):                     # hsdpvs's PVs; the IOC acts on CONFIG puts
            def updateDaqConfig(self, value):
                ioc.applied(self, value)

        self.provider = StaticProvider('simhsdioc')
        self.chips = [Chip(self.provider, p, False) for p in prefixes]
        self.prefixes = list(prefixes)
        self.l0delay = l0delay
        self.linkid = card_link_id() if linkid is None else linkid
        self.paddr = paddr
        self.freesz = freesz
        self.configs = 0
        self.stop = threading.Event()

    def applied(self, chip, value):
        """What hsd134PVs does once a CONFIG put has been applied to the digitizer."""
        self.configs += 1
        enable, group = int(value['enable']), int(value['readoutGroup'])
        if enable:
            _set(chip.monTiming, group=group, l0delay=self.l0delay)
        _set(chip.ready, value=1)
        log.info('%s:CONFIG applied (enable %d, readoutGroup %d, raw_gate %d, fex_prescale %d); '
                 'READY 1', chip.prefix, enable, group, int(value['raw_gate']),
                 int(value['fex_prescale']))

    def start(self):
        lanes = [_int32(self.linkid | (i << 16)) for i in range(4)]
        for c in self.chips:
            _set(c.pAddr_u, value=self.paddr)
            _set(c.pAddr, value='%x' % self.paddr)
            _set(c.fwVersion, value=FW_VERSION)
            _set(c.fwBuild, value=FW_BUILD)
            _set(c.monPgp, loclinkrdy=[1] * 4, remlinkrdy=[1] * 4, remlinkid=lanes)
            for b in (c.monRawBuf, c.monFexBuf):
                _set(b, freesz=self.freesz, freeevt=16)
        log.info('PADDR_U 0x%x, MONPGP.remlinkid 0x%08x (+ lane << 16), FWVERSION 0x%x, l0delay %d',
                 self.paddr, self.linkid, FW_VERSION, self.l0delay)

    def tick(self, n):
        t = time.time()
        sec, ns = int(t), int((t % 1) * 1e9)
        for c in self.chips:
            _set(c.fexOor, **{'value': 0, 'timeStamp.secondsPastEpoch': sec,
                              'timeStamp.nanoseconds': ns})
            _set(c.monTiming, timframecnt=(n * FRAMES_PER_S) & 0x7fffffff)

    def run(self):
        self.start()
        n = 0
        self.tick(n)
        while not self.stop.wait(1.0):
            n += 1
            self.tick(n)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('-P', required=True, nargs='+', metavar='PREFIX',
                    help='PV prefixes, as hsdpvs -P (hsd_config disables <prefix[:-1]>A and B)')
    ap.add_argument('--l0delay', type=int, default=81,
                    help='MONTIMING.l0delay once enabled (default %(default)s; hsd_config_store\'s '
                         'user.raw.start_ns of 93000 needs <= 86)')
    ap.add_argument('--linkid', type=lambda s: int(s, 0), default=None,
                    help='the DRP card\'s link id MONPGP.remlinkid reports (default: hsd_connect\'s '
                         'for this host)')
    ap.add_argument('--paddr', type=lambda s: int(s, 0), default=0xff000000,
                    help='PADDR_U (default %(default)#x; a sim:// DRP takes its link from simxpm)')
    ap.add_argument('--bind', default='127.0.0.1', help='PVA server interface (default %(default)s)')
    ap.add_argument('--allow-remote', action='store_true', help='allow a non-loopback --bind')
    ap.add_argument('-v', action='store_true')
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.v else logging.INFO,
                        format='%(asctime)s simhsdioc %(levelname)s %(message)s')
    if a.bind not in ('127.0.0.1', 'localhost') and not a.allow_remote:
        raise SystemExit('simhsdioc: --bind %s is not loopback; use --allow-remote to mean it' % a.bind)
    conf = {'EPICS_PVAS_INTF_ADDR_LIST': a.bind, 'EPICS_PVAS_BEACON_ADDR_LIST': a.bind,
            'EPICS_PVAS_AUTO_BEACON_ADDR_LIST': 'NO'}
    for key in ('SERVER_PORT', 'BROADCAST_PORT'):
        v = os.environ.get('EPICS_PVAS_%s' % key, os.environ.get('EPICS_PVA_%s' % key))
        if v:
            conf['EPICS_PVAS_%s' % key] = v
    ioc = SimHsdIoc(a.P, a.l0delay, a.linkid, a.paddr)
    with Server(providers=[ioc.provider], conf=conf, useenv=False) as server:
        log.info('serving the hsd PVs of %s; server conf %s', ' '.join(a.P), server.conf())
        print('simhsdioc: ready, prefixes %s, pid %d' % (' '.join(a.P), os.getpid()), flush=True)
        try:
            ioc.run()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
